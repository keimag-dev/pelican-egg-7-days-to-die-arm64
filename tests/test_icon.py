"""Standalone icon integrity, using the official game's square site icon."""
import base64
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_egg


class IconTests(unittest.TestCase):
    def test_embeds_exact_official_seven_days_icon(self):
        data = (ROOT / 'assets/7-days-to-die.png').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), '4804c9f215ae96520366402e2c26feb03c414f5c70618b3cd0a9a7b221d2fcb0')
        expected = 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')
        self.assertEqual(build_egg.make_egg().get('icon'), expected)


if __name__ == '__main__':
    unittest.main()
