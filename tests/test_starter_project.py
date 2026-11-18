import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from template_repository import (
    STARTER_PROJECT_ASSET,
    Release,
    ensure_starter_project_archive,
    install_starter_project,
)
from engine.project import DEFAULT_PROJECT
from tools.package_starter_project import package_starter_project


class StarterProjectTests(unittest.TestCase):
    def test_install_creates_current_template_locally_without_release_asset(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "user-project"
            with patch(
                "template_repository.ensure_starter_project_archive",
                side_effect=AssertionError("starter project should not be downloaded"),
            ):
                self.assertTrue(
                    install_starter_project(project, project_template=DEFAULT_PROJECT)
                )

            installed = json.loads(
                (project / "data" / "project.json").read_text(encoding="utf-8")
            )
            self.assertEqual(installed["theme"], DEFAULT_PROJECT["theme"])
            self.assertEqual(
                installed["theme"]["game_font_sizes"],
                DEFAULT_PROJECT["theme"]["game_font_sizes"],
            )
            self.assertTrue((project / "assets").is_dir())
            self.assertTrue((project / "data" / "story.yaml").is_file())

    def test_release_archive_contains_ready_project_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = package_starter_project(Path(temporary) / "starter.zip")
            with ZipFile(archive_path) as archive:
                self.assertIn("data/project.json", archive.namelist())
                self.assertIn("data/story.yaml", archive.namelist())
                self.assertIn("assets/", archive.namelist())
                project = json.loads(archive.read("data/project.json"))

            self.assertEqual(project["theme"], DEFAULT_PROJECT["theme"])
            self.assertEqual(project["theme"]["textbox"]["bottom"], 0.0)
            self.assertEqual(
                project["theme"]["choice_buttons"],
                {"normal": None, "hovered": None, "width": 900, "height": 56, "gap": 12},
            )

    def test_release_archive_download_is_cached(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = package_starter_project(root / "source.zip")
            cached = root / "cache" / STARTER_PROJECT_ASSET
            release = Release(
                tag="v1.2.3",
                assets={STARTER_PROJECT_ASSET: {"browser_download_url": "https://example.invalid/starter.zip"}},
            )

            def cache_archive(_asset, _name, destination):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())

            with patch("template_repository._cached_starter_project", return_value=cached):
                with patch("template_repository._release_for_tag", return_value=release):
                    with patch(
                        "template_repository._download_template_asset",
                        side_effect=cache_archive,
                    ) as download:
                        first = ensure_starter_project_archive("v1.2.3")
                        second = ensure_starter_project_archive("v1.2.3")

            self.assertEqual(first, second)
            download.assert_called_once()

    def test_install_preserves_existing_project_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = package_starter_project(root / "starter.zip")
            project = root / "user-project"
            with patch("template_repository.ensure_starter_project_archive", return_value=archive_path):
                self.assertTrue(install_starter_project(project, "v1.2.3"))
            project_file = project / "data" / "project.json"
            project_file.write_text('{"name": "My Existing Project"}\n', encoding="utf-8")
            original = project_file.read_bytes()

            with patch("template_repository.ensure_starter_project_archive") as ensure:
                self.assertFalse(install_starter_project(project, "v2.0.0"))

            ensure.assert_not_called()
            self.assertEqual(project_file.read_bytes(), original)

    def test_install_rejects_archive_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "unsafe.zip"
            with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("data/project.json", "{}")
                archive.writestr("data/story.yaml", "title: Test")
                archive.writestr("../outside.txt", "unsafe")
            project = root / "user-project"

            with patch("template_repository.ensure_starter_project_archive", return_value=archive_path):
                with self.assertRaisesRegex(ValueError, "Unsafe path"):
                    install_starter_project(project, "v1.2.3")

            self.assertFalse((root / "outside.txt").exists())
            self.assertFalse(project.exists())


if __name__ == "__main__":
    unittest.main()
