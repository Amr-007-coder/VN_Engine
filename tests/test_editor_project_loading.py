import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from editor import DEFAULT_PROJECT, SETTING_NAMES, VNEditorApp
from engine.project import ProjectConfig


class MemoryEditor:
    def __init__(self):
        self.content = ""
        self.dirty = False

    def set_text(self, content):
        self.content = content
        self.dirty = False


class EditorProjectLoadingTests(unittest.TestCase):
    def test_editor_setting_names_match_all_runtime_settings(self):
        expected = {
            "type_speed", "music_volume", "sfx_volume", "fullscreen", "ui_scale",
            "auto_advance", "auto_wait", "dialogue_font_scale", "speaker_font_scale",
            "high_contrast", "muted", "reduced_motion", "voice_enabled",
            "subtitles_enabled", "animated_text", "touch_advance_mode",
            "locale", "speech_enabled",
        }
        self.assertEqual(SETTING_NAMES, expected)

    def test_project_user_setting_accepts_admin_and_user_modes(self):
        self.assertEqual(ProjectConfig({"USER": "admin"}).values["USER"], "admin")
        self.assertEqual(ProjectConfig({"USER": "user"}).values["USER"], "user")
        self.assertEqual(ProjectConfig({"USER": "something-else"}).values["USER"], "something-else")
        with self.assertRaisesRegex(ValueError, "USER"):
            ProjectConfig({"USER": 123})

    def test_admin_test_play_stages_workspace_source_without_export_template(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            (workspace / "main.py").write_text("print('source test')\n", encoding="utf-8")
            (workspace / "engine").mkdir()
            (workspace / "engine" / "engine.py").write_text("SOURCE = True\n", encoding="utf-8")

            project_root = Path(temporary) / "project"
            (project_root / "assets").mkdir(parents=True)
            (project_root / "data").mkdir()
            (project_root / "assets" / "test.txt").write_text("asset", encoding="utf-8")
            (project_root / "data" / "project.json").write_text("{}", encoding="utf-8")

            app = SimpleNamespace(
                project_root=project_root,
                project_file=project_root / "data" / "project.json",
                project_editor=SimpleNamespace(
                    get_text=lambda: '{"USER": "admin", "name": "Test"}'
                ),
                _test_play_executable=lambda *_args: None,
                _current_platform=lambda: "windows",
                _uses_workspace_source_test_play=lambda values=None: (
                    isinstance(values, dict) and values.get("USER") == "admin"
                ),
                _create_source_test_play=lambda temporary_root, game_name: (
                    VNEditorApp._create_source_test_play(
                        SimpleNamespace(
                            project_root=project_root,
                        ),
                        temporary_root,
                        game_name,
                    )
                ),
            )

            with patch("editor.__file__", str(workspace / "editor.py")), patch(
                "editor.export_project"
            ) as export_template:
                temporary_game, _platform, _name, executable = VNEditorApp._create_temporary_game(app)

            try:
                export_template.assert_not_called()
                self.assertEqual(executable.name, "main.py")
                self.assertTrue(executable.is_file())
                self.assertTrue(executable.parent.joinpath("engine", "engine.py").is_file())
                self.assertTrue(executable.parent.joinpath("assets", "test.txt").is_file())
                self.assertTrue(executable.parent.joinpath("data", "project.json").is_file())
            finally:
                temporary_game.cleanup()

    def test_empty_project_json_uses_default_template_without_writing_until_saved(self):
        for empty_contents in ("", " \n ", "{}"):
            with self.subTest(empty_contents=empty_contents), tempfile.TemporaryDirectory() as temporary:
                project_root = Path(temporary)
                data_dir = project_root / "data"
                data_dir.mkdir()
                story_file = data_dir / "story.yaml"
                story_file.write_text("title: Test\nstart: intro\n", encoding="utf-8")
                project_file = data_dir / "project.json"
                project_file.write_text(empty_contents, encoding="utf-8")

                app = SimpleNamespace(
                    project_root=project_root,
                    project_label=SimpleNamespace(configure=lambda **_kwargs: None),
                    story_editor=MemoryEditor(),
                    project_editor=MemoryEditor(),
                    _clear_included_story_tabs=lambda: None,
                    _story_path_from=lambda _values: story_file,
                    _sync_included_story_tabs=lambda: None,
                    _update_tab_labels=lambda: None,
                    _refresh_markdown_tabs=lambda: None,
                    refresh_asset_tree=lambda: None,
                    analyze_document=lambda _kind: None,
                    _refresh_search_highlights=lambda: None,
                    _start_terminal=lambda: None,
                    set_status=lambda _status: None,
                )

                with patch("editor._save_last_project"):
                    VNEditorApp.load_project(app, project_root)

                self.assertEqual(json.loads(app.project_editor.content), DEFAULT_PROJECT)
                self.assertTrue(app.project_editor.dirty)
                self.assertEqual(project_file.read_text(encoding="utf-8"), empty_contents)

    def test_existing_project_json_is_loaded_verbatim_and_not_marked_dirty(self):
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            data_dir = project_root / "data"
            data_dir.mkdir()
            story_file = data_dir / "story.yaml"
            story_file.write_text("title: Test\nstart: intro\n", encoding="utf-8")
            project_file = data_dir / "project.json"
            project_contents = json.dumps(
                {"name": "My edited novel", "story": "story.yaml", "theme": {}},
                indent=4,
            ) + "\n"
            project_file.write_text(project_contents, encoding="utf-8")

            app = SimpleNamespace(
                project_root=project_root,
                project_label=SimpleNamespace(configure=lambda **_kwargs: None),
                story_editor=MemoryEditor(),
                project_editor=MemoryEditor(),
                _clear_included_story_tabs=lambda: None,
                _story_path_from=lambda _values: story_file,
                _sync_included_story_tabs=lambda: None,
                _update_tab_labels=lambda: None,
                _refresh_markdown_tabs=lambda: None,
                refresh_asset_tree=lambda: None,
                analyze_document=lambda _kind: None,
                _refresh_search_highlights=lambda: None,
                _start_terminal=lambda: None,
                set_status=lambda _status: None,
            )

            with patch("editor._save_last_project"):
                VNEditorApp.load_project(app, project_root)

            self.assertEqual(app.project_editor.content, project_contents)
            self.assertFalse(app.project_editor.dirty)
            self.assertEqual(app.project_file, project_file)


if __name__ == "__main__":
    unittest.main()
