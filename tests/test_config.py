import importlib.util
import pathlib
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime', ROOT / 'runtime.py')
runtime = importlib.util.module_from_spec(spec)
if spec.loader and (ROOT / 'runtime.py').exists():
    spec.loader.exec_module(runtime)


class ConfigTests(unittest.TestCase):
    def test_managed_merge_preserves_custom_values_and_escapes(self):
        self.assertTrue(hasattr(runtime, 'configure'), 'managed XML configurator is not implemented')
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 'serverconfig.xml'
            path.write_text('<ServerSettings><!--keep--><property name="ServerName" value="old"/><property name="SandboxCode" value="CUSTOM"/><property name="Unknown" value="preserve"/></ServerSettings>')
            runtime.configure(path, {'SERVER_NAME': 'A & "B" <C>', 'SERVER_PORT': '26900'})
            root = ET.parse(path).getroot()
            values = {x.get('name'): x.get('value') for x in root.findall('property')}
            self.assertEqual(values['ServerName'], 'A & "B" <C>')
            self.assertEqual(values['SandboxCode'], 'CUSTOM')
            self.assertEqual(values['Unknown'], 'preserve')
            self.assertEqual(values['TelnetPassword'], '')
            self.assertEqual(values['TelnetEnabled'], 'true')
            self.assertEqual(values['WebDashboardEnabled'], 'false')
            self.assertIn('<!--keep-->', path.read_text())

    def test_validation_and_user_xml_mode(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / 'serverconfig.xml'
            original = '<ServerSettings><property name="ServerName" value="custom"/><property name="SandboxCode" value="keep"/></ServerSettings>'
            for env in ({'SERVER_PORT': '0'}, {'SERVER_PORT': '$(touch pwn)'}, {'SERVER_VISIBILITY': '3'}, {'GAME_NAME': '../world'}, {'WORLD_SIZE': '999'}, {'USER_XML_MODE': 'nonsense'}, {'SANDBOX_CODE': '<bad>'}, {'SERVER_NAME': 'bad\x00'}):
                p.write_text(original)
                with self.subTest(env=env), self.assertRaises(ValueError):
                    runtime.configure(p, env)
                self.assertEqual(p.read_text(), original)
            p.write_text(original)
            runtime.configure(p, {'USER_XML_MODE': 'user', 'SERVER_NAME': 'ignored'})
            props = {x.get('name'): x.get('value') for x in ET.parse(p).getroot()}
            self.assertEqual(props['ServerName'], 'custom')
            self.assertEqual(props['SandboxCode'], 'keep')
            self.assertEqual(props['TelnetPassword'], '')
            runtime.configure(p, {'SANDBOX_CODE': 'AAAJABJAC'})
            props = {x.get('name'): x.get('value') for x in ET.parse(p).getroot()}
            self.assertEqual(props['SandboxCode'], 'AAAJABJAC')

    def test_corrupt_duplicate_and_unsafe_xml_left_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / 'serverconfig.xml'
            for xml in ('<broken', '<!DOCTYPE x [<!ENTITY y "evil">]><ServerSettings/>', '<Wrong/>', '<ServerSettings><property name="ServerPort" value="1"/><property name="ServerPort" value="2"/></ServerSettings>'):
                p.write_text(xml)
                with self.subTest(xml=xml), self.assertRaises(ValueError):
                    runtime.configure(p, {})
                self.assertEqual(p.read_text(), xml)

if __name__ == '__main__':
    unittest.main()
