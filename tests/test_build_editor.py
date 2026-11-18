import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_editor


class BuildEditorTests(unittest.TestCase):
    def test_move_editor_to_dist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built_output = root / "editor.exe"
            dist_output = root / "dist" / "editor.exe"
            built_output.write_bytes(b"editor")

            with patch.multiple(
                build_editor,
                BUILT_EDITOR_OUTPUT=built_output,
                EDITOR_OUTPUT=dist_output,
            ):
                build_editor._move_editor_to_dist()

            self.assertFalse(built_output.exists())
            self.assertEqual(dist_output.read_bytes(), b"editor")


if __name__ == "__main__":
    unittest.main()
