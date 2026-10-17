import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'installer.py')
assert spec and spec.loader
installer = importlib.util.module_from_spec(spec)
if (ROOT / 'installer.py').exists():
    spec.loader.exec_module(installer)

class InstallerTests(unittest.TestCase):
    def test_anonymous_native_download_selection_and_literal_rejection(self):
        self.assertTrue(hasattr(installer, 'download_command'), 'native installer missing')
        command = installer.download_command('/tools/DepotDownloader', '/srv/game', {})
        self.assertEqual(command, ['/tools/DepotDownloader', '-app', '294420', '-depot', '294422', '-os', 'linux', '-osarch', '64', '-branch', 'public', '-dir', '/srv/game', '-validate', '-max-downloads', '4'])
        command = installer.download_command('/tools/dd', '/srv/game', {'STEAM_BRANCH': 'latest_experimental', 'STEAM_MANIFEST': '3031329678505041777'})
        self.assertIn('latest_experimental', command)
        self.assertEqual(command[-2:], ['-manifest', '3031329678505041777'])
        for env in ({'STEAM_BRANCH': ' public'}, {'STEAM_BRANCH': 'public;id'}, {'STEAM_MANIFEST': ' 123'}, {'STEAM_MANIFEST': '0'}, {'DEPOTDOWNLOADER_VERSION': 'latest'}, {'INSTALL_TIMEOUT': '-1'}, {'DEPOTDOWNLOADER_SHA256': 'bad'}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                installer.download_command('/tools/dd', '/srv/game', env)

    def test_release_asset_digest_and_archive_safety(self):
        self.assertTrue(hasattr(installer, 'release_asset'), 'official release asset verifier missing')
        asset = {'name': 'DepotDownloader-linux-arm64.zip', 'size': 123, 'digest': 'sha256:' + 'a' * 64, 'browser_download_url': 'https://github.com/SteamRE/DepotDownloader/releases/download/DepotDownloader_3.4.0/DepotDownloader-linux-arm64.zip'}
        release = {'tag_name': 'DepotDownloader_3.4.0', 'draft': False, 'assets': [asset]}
        self.assertEqual(installer.release_asset(release, '3.4.0'), asset)
        for modified in ({**release, 'tag_name': 'wrong'}, {**release, 'draft': True}, {**release, 'assets': [{**asset, 'browser_download_url': 'https://evil.invalid/payload.zip'}]}):
            with self.assertRaises(ValueError):
                installer.release_asset(modified, '3.4.0')
        for name in ('../outside', '/absolute', 'C:/native', 'dir\\bad', 'safe/../../outside'):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.writestr(name, b'bad')
            stream.seek(0)
            with tempfile.TemporaryDirectory() as d, zipfile.ZipFile(stream) as archive:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    installer.extract_tool(archive, pathlib.Path(d))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('DepotDownloader', b'fixture native tool')
        stream.seek(0)
        with tempfile.TemporaryDirectory() as d, zipfile.ZipFile(stream) as archive:
            tool = installer.extract_tool(archive, pathlib.Path(d))
            self.assertEqual(tool.read_bytes(), b'fixture native tool')

    def test_persistent_config_and_world_survive_reinstall(self):
        self.assertTrue(hasattr(installer, 'finalize_install'), 'persistent install finalizer missing')
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            game = root / 'game'
            game.mkdir()
            (game / '7DaysToDieServer.x86_64').write_bytes(b'\x7fELF' + b'\x00' * 14 + b'\x3e\x00')
            (game / 'serverconfig.xml').write_text('<ServerSettings/>')
            installer.finalize_install(root)
            self.assertEqual((root / 'serverconfig.xml').read_text(), '<ServerSettings/>')
            (root / 'serverconfig.xml').write_text('custom config')
            (root / 'UserData').mkdir()
            (root / 'UserData' / 'world').write_text('world state')
            (game / 'serverconfig.xml').write_text('new upstream config')
            installer.finalize_install(root)
            self.assertEqual((root / 'serverconfig.xml').read_text(), 'custom config')
            self.assertEqual((root / 'UserData' / 'world').read_text(), 'world state')

    def test_entrypoint_rejects_invalid_settings_before_touching_files(self):
        self.assertTrue(hasattr(installer, 'install'), 'installer entrypoint missing')
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            with self.assertRaises(ValueError):
                installer.install(root, {'STEAM_BRANCH': 'malformed'})
            self.assertEqual(list(root.iterdir()), [])

if __name__ == '__main__':
    unittest.main()
