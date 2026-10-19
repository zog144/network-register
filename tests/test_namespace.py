import importlib.util
import unittest

import zog.network_register


class NamespaceMigrationTests(unittest.TestCase):
    def test_component_version_is_exposed(self):
        self.assertEqual(zog.network_register.__version__, "0.12.0")

    def test_legacy_top_level_package_is_not_importable(self):
        self.assertIsNone(importlib.util.find_spec("network_register"))


if __name__ == "__main__":
    unittest.main()
