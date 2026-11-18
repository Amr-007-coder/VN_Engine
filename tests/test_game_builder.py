import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from zipfile import ZipFile

from engine.embedded import PROJECT_BUNDLE_COMMENT, _load_project_bundle
from engine.game_builder import _game_name, _write_resource_bundle


class GameBuilderTests(unittest.TestCase):
    def test_game_name_is_safe_for_windows_files(self):
        self.assertEqual(_game_name("A/B: Story."), "A_B_ Story")
        self.assertEqual(_game_name("engine"), "Visual Novel")
        self.assertEqual(_game_name("CON"), "_CON")

    def test_resource_bundle_normalizes_project_paths_and_contains_story_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "source-data"
            assets_dir = root / "source-assets"
            data_dir.mkdir()
            (assets_dir / "characters" / "Aiko" / "Default").mkdir(parents=True)
            (data_dir / "story.yaml").write_text(
                "title: Test\n"
                "start: opening\n"
                "dialogues:\n"
                "  opening:\n"
                "    speaker: Narrator\n"
                "    text: Hello\n",
                encoding="utf-8",
            )
            (assets_dir / "characters" / "Aiko" / "Default" / "Smile.png").write_bytes(b"png")
            project = SimpleNamespace(
                data_dir=data_dir,
                assets_dir=assets_dir,
                user_data_dir=root / "user-data",
                story_file="story.yaml",
                name="Test",
                values={
                    "name": "Test",
                    "story": "story.yaml",
                    "paths": {
                        "data": "source-data",
                        "assets": "source-assets",
                        "user_data": "user_data",
                    },
                },
            )
            bundle_path = root / "resources.zip"

            count = _write_resource_bundle(bundle_path, project)

            with ZipFile(bundle_path) as bundle:
                self.assertEqual(bundle.comment, PROJECT_BUNDLE_COMMENT)
                self.assertEqual(count, 3)
                config = json.loads(bundle.read("data/project.json"))
                self.assertEqual(config["paths"]["data"], "data")
                self.assertEqual(config["paths"]["assets"], "assets")
                self.assertEqual(bundle.read("assets/characters/Aiko/Default/Smile.png"), b"png")
                self.assertIn(b"Hello", bundle.read("data/story.yaml"))

    def test_project_bundle_is_read_from_executable_overlay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "game.exe"
            shutil.copy2(sys.executable, executable)
            bundle_path = root / "resources.zip"
            with ZipFile(bundle_path, "w") as bundle:
                bundle.comment = PROJECT_BUNDLE_COMMENT
                bundle.writestr("data/project.json", b"{}")
                bundle.writestr("data/story.yaml", b"story")

            with executable.open("ab") as target, bundle_path.open("rb") as source:
                shutil.copyfileobj(source, target)

            original_argv0 = sys.argv[0]
            try:
                sys.argv[0] = str(executable)
                archive, resources = _load_project_bundle()
            finally:
                sys.argv[0] = original_argv0

            try:
                self.assertEqual(resources["data/story.yaml"], "data/story.yaml")
                self.assertEqual(archive.read("data/story.yaml"), b"story")
            finally:
                archive.close()


if __name__ == "__main__":
    unittest.main()
