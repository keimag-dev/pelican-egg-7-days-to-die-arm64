"""Regression coverage for bootstrap trust boundary and atomic first config."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bootstrap_build', ROOT / 'build_egg.py')
assert spec is not None and spec.loader is not None
build = importlib.util.module_from_spec(spec); spec.loader.exec_module(build)
spec = importlib.util.spec_from_file_location('atomic_installer', ROOT / 'installer.py')
assert spec is not None and spec.loader is not None
installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)

def shell_path(path):
    text = str(path).replace('\\', '/')
    return '/' + text[0].lower() + text[2:] if len(text) > 2 and text[1] == ':' else text

class BootstrapSafetyTests(unittest.TestCase):
    def run_bootstrap(self, root, server, trace, source=None, rewrite_target=False, extra_env=None):
        bash = shutil.which('bash')
        if not bash:
            self.skipTest('Bash required for actual bootstrap test')
        tools = root / 'tools'
        tools.mkdir()
        python = '#!/bin/bash\nprintf called > "$TRACE"\nexit 0\n'
        if source is not None:
            python = ('#!/bin/bash\n'
                      + ('printf "%s\\n" "raise SystemExit(91)" > "$PERSISTENT_INSTALLER"\n' if rewrite_target else '')
                      + 'source="${@: -1}"\nif command -v cygpath >/dev/null; then source=$(cygpath -w "$source"); fi\n'
                      + 'args=("$@"); args[${#args[@]}-1]="$source"\nexec "$REAL_PYTHON" "${args[@]}"\n')
        for name, body in (('uname', '#!/bin/bash\nprintf aarch64\n'), ('python3', python)):
            path = tools / name
            path.write_text(body, encoding='utf-8', newline='\n')
            path.chmod(0o755)
        text = build.installation_script()
        if source is not None:
            text = text.replace((ROOT / 'installer.py').read_text(encoding='utf-8'), source)
        text = text.replace('/mnt/server', shell_path(server)).replace('/tmp/pelican-bootstrap.', shell_path(root / 'private-bootstrap.'))
        script = root / 'install.sh'
        script.write_text(text, encoding='utf-8', newline='\n')
        import sys
        env = dict(os.environ, TRACE=shell_path(trace) if source is None else str(trace),
                   REAL_PYTHON=sys.executable.replace('\\', '/'),
                   PERSISTENT_INSTALLER=shell_path(server / '.pelican/installer.py'),
                   PATH=str(tools) + os.pathsep + os.environ['PATH'])
        env.update(extra_env or {})
        return subprocess.run([bash, shell_path(script)], capture_output=True, env=env, timeout=20)

    def test_directory_helper_destinations_are_rejected_before_python(self):
        for helper in ('installer.py', 'runtime.py'):
            with self.subTest(helper=helper), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                server = root / 'server'
                target = server / '.pelican' / helper
                target.mkdir(parents=True)
                (target / '__main__.py').write_text('raise SystemExit(91)\n')
                trace = root / 'executed'
                result = self.run_bootstrap(root, server, trace)
                self.assertNotEqual(result.returncode, 0, 'Directory destination must fail closed')
                self.assertFalse(trace.exists(), 'User directory must never reach Python execution')
                self.assertEqual(list(target.iterdir()), [target / '__main__.py'])

    def check_symlink_destination(self, directory):
        for helper in ('installer.py', 'runtime.py'):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                server = root / 'server'
                managed = server / '.pelican'
                managed.mkdir(parents=True)
                outside = root / 'outside'
                if directory:
                    outside.mkdir()
                    sentinel = outside / '__main__.py'
                else:
                    sentinel = outside
                sentinel.write_text('unchanged')
                try:
                    (managed / helper).symlink_to(outside, target_is_directory=directory)
                except OSError as exc:
                    if os.name == 'nt' and getattr(exc, 'winerror', None) == 1314:
                        self.skipTest('Windows account lacks native symlink privilege')
                    raise
                trace = root / 'executed'
                result = self.run_bootstrap(root, server, trace)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(trace.exists())
                self.assertEqual(sentinel.read_text(), 'unchanged')
                self.assertTrue((managed / helper).is_symlink())

    def test_symlink_to_file_helper_destinations_are_rejected(self):
        self.check_symlink_destination(False)

    def test_symlink_to_directory_helper_destinations_are_rejected(self):
        self.check_symlink_destination(True)

    def test_regular_helpers_publish_exact_sources_but_execute_private_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = root / 'server'
            managed = server / '.pelican'
            managed.mkdir(parents=True)
            for helper in ('installer.py', 'runtime.py'):
                (managed / helper).write_text('old helper')
            trace = root / 'executed'
            source = 'import os\nfrom pathlib import Path\nPath(os.environ["TRACE"]).write_text(__file__)\n'
            result = self.run_bootstrap(root, server, trace, source=source)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((managed / 'installer.py').read_text(encoding='utf-8'), source)
            self.assertEqual((managed / 'runtime.py').read_text(encoding='utf-8'), (ROOT / 'runtime.py').read_text(encoding='utf-8'))
            executed = Path(trace.read_text()).resolve()
            self.assertNotIn(server.resolve(), executed.parents)
            self.assertEqual(executed.name, 'installer.py')
            self.assertFalse(executed.exists(), 'Private staging is removed after execution')

    def test_replaced_persistent_helper_cannot_change_root_execution_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = root / 'server'
            server.mkdir()
            trace = root / 'executed'
            source = 'import os\nfrom pathlib import Path\nPath(os.environ["TRACE"]).write_text("trusted staging ran")\n'
            result = self.run_bootstrap(root, server, trace, source=source, rewrite_target=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(trace.read_text(), 'trusted staging ran')
            self.assertEqual((server / '.pelican/installer.py').read_text().strip(), 'raise SystemExit(91)')

    def test_bootstrap_ignores_user_controlled_python_import_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = root / 'server'
            server.mkdir()
            (server / 'decimal.py').write_text('raise SystemExit(91)\n')
            trace = root / 'executed'
            source = 'import decimal, os\nfrom pathlib import Path\nPath(os.environ["TRACE"]).write_text("trusted imports")\n'
            result = self.run_bootstrap(root, server, trace, source=source, extra_env={'PYTHONPATH': str(server)})
            self.assertEqual(result.returncode, 0, 'User import path must never affect root bootstrap: ' + result.stderr.decode(errors='replace'))
            self.assertEqual(trace.read_text(), 'trusted imports')

    def test_missing_stock_never_creates_persistent_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'game').mkdir();(root/'game/7DaysToDieServer.x86_64').write_bytes(b'\x7fELF'+b'\0'*14+b'\x3e\0')
            with self.assertRaises(OSError):installer.finalize_install(root)
            self.assertFalse((root/'serverconfig.xml').exists(),'Missing source must not leave empty persistent XML')
            (root / 'game/serverconfig.xml').write_text('<ServerSettings/>')
            installer.finalize_install(root)
            self.assertEqual((root / 'serverconfig.xml').read_text(), '<ServerSettings/>')
            self.assertFalse(list(root.glob('.serverconfig-*')))

    def test_fsync_failure_cleans_staging_without_publishing_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'game').mkdir()
            (root / 'game/7DaysToDieServer.x86_64').write_bytes(b'\x7fELF' + b'\0'*14 + b'\x3e\0')
            (root / 'game/serverconfig.xml').write_text('<ServerSettings/>')
            with patch.object(installer.os, 'fsync', side_effect=OSError('injected fsync failure')), self.assertRaises(OSError):
                installer.finalize_install(root)
            self.assertFalse((root / 'serverconfig.xml').exists())
            self.assertFalse(list(root.glob('.serverconfig-*')))

    def test_concurrently_created_user_xml_wins_create_only_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'game').mkdir()
            (root / 'game/7DaysToDieServer.x86_64').write_bytes(b'\x7fELF' + b'\0'*14 + b'\x3e\0')
            (root / 'game/serverconfig.xml').write_text('<ServerSettings/>')
            real_link, real_fsync = os.link, os.fsync
            synced = []
            def sync(fd):
                real_fsync(fd)
                synced.append(True)
            def publish(source, destination):
                self.assertTrue(synced, 'Complete staging must be fsynced before publication')
                self.assertEqual(Path(source).read_text(), '<ServerSettings/>')
                self.assertFalse(Path(destination).exists(), 'Persistent path must not be pre-created')
                Path(destination).write_text('new user XML')
                real_link(source, destination)  # Real filesystem raises FileExistsError.
            with patch.object(installer.os, 'fsync', side_effect=sync), patch.object(installer.os, 'link', side_effect=publish):
                installer.finalize_install(root)
            self.assertEqual((root / 'serverconfig.xml').read_text(), 'new user XML')
            self.assertFalse(list(root.glob('.serverconfig-*')))

    def test_unsafe_stock_xml_is_never_published(self):
        for data in (b'<ServerSettings>', b'<other/>',
                     b'<!DOCTYPE ServerSettings [<!ENTITY x "expanded">]><ServerSettings>&x;</ServerSettings>',
                     b'<ServerSettings><property name="a" value="1"/><property name="a" value="2"/></ServerSettings>'):
            with self.subTest(data=data), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'game').mkdir()
                (root / 'game/7DaysToDieServer.x86_64').write_bytes(b'\x7fELF' + b'\0'*14 + b'\x3e\0')
                (root / 'game/serverconfig.xml').write_bytes(data)
                with self.assertRaises(ValueError):
                    installer.finalize_install(root)
                self.assertFalse((root / 'serverconfig.xml').exists())
                self.assertFalse(list(root.glob('.serverconfig-*')))

    def test_interrupted_copy_never_publishes_partial_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'game').mkdir();(root/'game/7DaysToDieServer.x86_64').write_bytes(b'\x7fELF'+b'\0'*14+b'\x3e\0');(root/'game/serverconfig.xml').write_text('<ServerSettings/>')
            def interrupt(src,dst):dst.write(b'<bad');raise OSError('injected I/O failure')
            with patch.object(installer.shutil,'copyfileobj',side_effect=interrupt),self.assertRaises(OSError):installer.finalize_install(root)
            self.assertFalse((root/'serverconfig.xml').exists(),'Partial copy must never be published')
            self.assertFalse(list(root.glob('.serverconfig-*')),'Temporary copy must be removed')

if __name__=='__main__':unittest.main()
