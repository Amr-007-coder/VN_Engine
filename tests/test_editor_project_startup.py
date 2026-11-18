from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from editor import _initial_project_root, _load_last_project, _save_last_project, project_root_from


class EditorProjectStartupTests(unittest.TestCase):
    def test_project_root_detection_skips_engine_assets_and_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            (root / "data" / "project.json").write_text("{}", encoding="utf-8")
            engine = root / "engine"
            (engine / "data").mkdir(parents=True)
            (engine / "data" / "version.txt").write_text("1.2.3\n", encoding="utf-8")
            (engine / "assets").mkdir()

            self.assertEqual(project_root_from(engine), root)

    def test_last_opened_project_is_reused_when_launched_from_editor_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "VN_Editor"
            package.mkdir()
            (package / "VN_Editor.exe").write_bytes(b"editor")
            package_project = package / "data"
            package_project.mkdir()
            (package_project / "project.json").write_text("{}", encoding="utf-8")
            last_project = root / "My Project"
            (last_project / "data").mkdir(parents=True)
            (last_project / "data" / "project.json").write_text("{}", encoding="utf-8")

            selected = _initial_project_root(None, package, package, last_project)

            self.assertEqual(selected, last_project)

    def test_source_editor_uses_project_in_repository_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            (root / "data" / "project.json").write_text("{}", encoding="utf-8")
            remembered = root / "Previous Project"
            (remembered / "data").mkdir(parents=True)
            (remembered / "data" / "project.json").write_text("{}", encoding="utf-8")

            selected = _initial_project_root(None, root, root, remembered)

            self.assertEqual(selected, root)

    def test_current_project_folder_overrides_saved_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root / "Current Project"
            (current / "data").mkdir(parents=True)
            (current / "data" / "project.json").write_text("{}", encoding="utf-8")
            package = root / "VN_Editor"
            package.mkdir()
            saved = root / "Saved Project"
            (saved / "data").mkdir(parents=True)
            (saved / "data" / "project.json").write_text("{}", encoding="utf-8")

            selected = _initial_project_root(None, current, package, saved)

            self.assertEqual(selected, current)

    def test_last_project_path_round_trips_in_editor_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = root / "config" / "editor.json"
            project = root / "My Project"
            project.mkdir()
            with patch("editor._editor_settings_path", return_value=settings):
                _save_last_project(project)
                self.assertEqual(_load_last_project(), project)


if __name__ == "__main__":
    unittest.main()
