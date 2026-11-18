import json
import unittest
from unittest.mock import patch

import editor


class EditorAndroidConfigTests(unittest.TestCase):
    def test_android_is_known_and_defaulted_without_engine_source_files(self):
        project_with_android = {
            "android": {
                "app_name": "My Novel",
                "app_id": "com.example.mynovel",
                "orientation": "portrait",
            }
        }

        with patch("editor.DEFAULT_PROJECT", editor.FALLBACK_DEFAULT_PROJECT):
            for raw in (project_with_android, {}):
                diagnostics = []
                source = json.dumps(raw)
                values = editor.merge_defaults(editor.DEFAULT_PROJECT, raw)

                editor._validate_project_object(values, raw, source, diagnostics)

                android_diagnostics = [
                    item.message for item in diagnostics if "android" in item.message.casefold()
                ]
                self.assertEqual(android_diagnostics, [])
                self.assertIsInstance(values["android"], dict)


if __name__ == "__main__":
    unittest.main()
