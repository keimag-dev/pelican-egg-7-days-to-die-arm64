import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_egg', ROOT / 'build_egg.py')
assert spec and spec.loader
build = importlib.util.module_from_spec(spec)
if (ROOT / 'build_egg.py').exists():
    spec.loader.exec_module(build)

class ExportTests(unittest.TestCase):
    def test_publication_uuid_is_fresh_v4_valid_and_stable_across_builds(self):
        first = build.make_egg()['uuid']
        parsed = uuid.UUID(first)
        self.assertEqual(str(parsed), first)
        self.assertEqual(parsed.version, 4, 'Publication needs a newly generated, fixed UUIDv4, not a derived/trial identity')
        self.assertEqual(build.make_egg()['uuid'], first)
        self.assertEqual(build.make_egg(update_url='https://example.invalid/egg.json')['uuid'], first)

    def test_startup_replaces_image_shell_for_signal_delivery(self):
        self.assertTrue(build.make_egg()['startup_commands']['Default'].startswith('exec '),
                        'Box64 image has no init; shell must hand off to supervisor')

    def test_native_self_contained_export_and_exact_sources(self):
        self.assertTrue(hasattr(build, 'make_egg'), 'standalone Egg builder is missing')
        egg = build.make_egg()
        self.assertEqual(egg['meta'], {'version': 'PLCN_v3', 'update_url': build.UPDATE_URL})
        self.assertEqual(egg['startup_commands'], {'Default': 'exec python3 -u /home/container/.pelican/runtime.py'})
        self.assertIsInstance(egg['config']['files'], dict)
        self.assertEqual(egg['config']['stop'], 'shutdown')
        self.assertEqual(egg['config']['startup']['done'], 'GameServer.Init successful')
        script = egg['scripts']['installation']['script']
        self.assertIn((ROOT / 'installer.py').read_text(encoding='utf-8'), script)
        self.assertIn((ROOT / 'runtime.py').read_text(encoding='utf-8'), script)
        self.assertNotIn('base64', script)
        self.assertNotIn('{{', egg['startup_commands']['Default'])
        self.assertEqual(egg, build.make_egg())
        variables = {v['env_variable']: v for v in egg['variables']}
        for key, choice in (('STEAM_BRANCH', 'in:public,latest_experimental'), ('USER_XML_MODE', 'in:managed,user'), ('GAME_WORLD', 'in:Navezgane,RWG'), ('SERVER_VISIBILITY', 'in:0,1,2')):
            self.assertIn(choice, variables[key]['rules'])
        self.assertTrue(all(isinstance(v['rules'], list) and isinstance(v['sort'], int) for v in egg['variables']))
        self.assertEqual(variables['STEAM_MANIFEST']['default_value'], '')
        self.assertEqual(variables['GAME_WORLD']['default_value'], 'Navezgane')
        self.assertNotIn('SERVER_PORT', variables)  # Wings owns the default allocation env.
        json.loads(json.dumps(egg))

    def test_standalone_export_includes_mit_notice(self):
        self.assertIn('Permission is hereby granted', build.make_egg()['_comment'])
        self.assertIn('Copyright (c) 2026 keimag-dev', build.make_egg()['_comment'])

    def test_publication_update_url_is_explicit_override_only(self):
        self.assertEqual(build.make_egg()['meta']['update_url'], build.UPDATE_URL)
        self.assertEqual(build.make_egg(update_url='https://example.invalid/egg.json')['meta']['update_url'], 'https://example.invalid/egg.json')

    def test_cli_publication_override_writes_both_files_beside_builder(self):
        url = 'https://example.invalid/releases/latest/download/egg.json'
        with tempfile.TemporaryDirectory() as tmp:
            module = pathlib.Path(tmp) / 'module'
            module.mkdir()
            for name in ('build_egg.py', 'install.sh.in', 'installer.py', 'runtime.py', 'LICENSE'):
                shutil.copyfile(ROOT / name, module / name)
            result = subprocess.run([sys.executable, str(module / 'build_egg.py'), '--update-url', url],
                                    cwd=tmp, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            egg = json.loads((module / 'egg-7-days-to-die-arm64.json').read_text(encoding='utf-8'))
            self.assertEqual(egg, build.make_egg(update_url=url))
            self.assertEqual((module / 'install.sh').read_text(encoding='utf-8'), egg['scripts']['installation']['script'])
            self.assertFalse((pathlib.Path(tmp) / 'install.sh').exists())
            self.assertFalse((pathlib.Path(tmp) / 'egg-7-days-to-die-arm64.json').exists())

    def test_generated_files_match_sources(self):
        egg = build.make_egg()
        self.assertEqual((ROOT / 'install.sh').read_text(encoding='utf-8'), egg['scripts']['installation']['script'])
        self.assertEqual(json.loads((ROOT / 'egg-7-days-to-die-arm64.json').read_text(encoding='utf-8')), egg)

if __name__ == '__main__':
    unittest.main()
