from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from tools.package_editor import package_editor


class PackageEditorTests(unittest.TestCase):
    def test_editor_package_omits_runtime_templates_and_records_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build = root / "build"
            build.mkdir()
            (build / "VN_Editor.exe").write_bytes(b"editor")
            output = root / "VN_Editor-windows.zip"

            package_editor("windows", build, output)

            with ZipFile(output) as package:
                names = set(package.namelist())
                self.assertFalse(any(name.startswith("templates/") for name in names))
                self.assertNotIn("data/project.json", names)
                self.assertNotIn("data/story.yaml", names)
                self.assertIn("engine-version.txt", names)
                self.assertEqual(
                    package.read("engine-version.txt").decode("utf-8").strip(),
                    (Path(__file__).resolve().parents[1] / "engine" / "data" / "version.txt")
                    .read_text(encoding="utf-8")
                    .strip(),
                )


if __name__ == "__main__":
    unittest.main()
