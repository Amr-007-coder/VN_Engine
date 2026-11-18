import json
from pathlib import Path
import unittest

import editor
from engine.config import FONTS, load_assets
from engine.project import ProjectConfig
from engine.theme import resolve_theme
from engine.ui_scale import get_ui_scale, set_ui_scale


class FontConfigTests(unittest.TestCase):
    def test_project_config_accepts_custom_font_families_and_sizes(self):
        project = ProjectConfig({
            "theme": {
                "fonts": {"menu": "Menu.ttf", "title": "Title.ttf", "item_size": 22},
                "game_fonts": {
                    "text": "Dialogue.ttf",
                    "name": "Name.ttf",
                    "button": "Button.ttf",
                    "intro": "Intro.ttf",
                },
                "game_font_sizes": {
                    "text": 27,
                    "name": 31,
                    "button": 19,
                    "dialogue_controls": 13,
                    "intro": 42,
                    "intro_small": 18,
                },
            }
        })

        self.assertEqual(project.theme["game_font_sizes"]["text"], 27)
        self.assertEqual(project.theme["game_fonts"]["intro"], "Intro.ttf")

    def test_project_config_rejects_non_positive_font_sizes(self):
        with self.assertRaisesRegex(ValueError, "game_font_sizes.text"):
            ProjectConfig({"theme": {"game_font_sizes": {"text": 0}}})
        with self.assertRaisesRegex(ValueError, "fonts.item_size"):
            ProjectConfig({"theme": {"fonts": {"item_size": True}}})

    def test_runtime_loads_font_files_at_configured_scaled_sizes(self):
        class FakeAssets:
            def __init__(self):
                self.loaded = []

            def load_font(self, name, size):
                self.loaded.append((name, size))
                return (name, size)

        assets = FakeAssets()
        original_scale = get_ui_scale()
        original_fonts = (
            FONTS.normal_text,
            FONTS.char_name,
            FONTS.button_text,
            FONTS.dialogue_controls,
        )
        set_ui_scale(1.0)
        try:
            load_assets(assets, resolve_theme({
                "game_fonts": {
                    "text": "Dialogue.ttf",
                    "name": "Name.ttf",
                    "button": "Button.ttf",
                },
                "game_font_sizes": {
                    "text": 30,
                    "name": 34,
                    "button": 22,
                    "dialogue_controls": 14,
                },
            }))
            self.assertEqual(FONTS.dialogue_controls, ("Button.ttf", 14))
        finally:
            set_ui_scale(original_scale)
            (
                FONTS.normal_text,
                FONTS.char_name,
                FONTS.button_text,
                FONTS.dialogue_controls,
            ) = original_fonts

        self.assertEqual(
            assets.loaded,
            [
                ("Dialogue.ttf", 30),
                ("Name.ttf", 34),
                ("Button.ttf", 22),
                ("Button.ttf", 14),
            ],
        )

    def test_editor_reports_invalid_font_sizes_and_suggests_all_font_keys(self):
        project = {"theme": {"game_font_sizes": {"dialogue_controls": -1}}}
        source = json.dumps(project)
        catalog = editor.AssetCatalog(Path.cwd(), project)

        diagnostics = editor.analyze_project(source, catalog)

        self.assertTrue(any(
            "theme.game_font_sizes.dialogue_controls must be a positive integer"
            in item.message
            for item in diagnostics
        ))
        self.assertEqual(
            set(editor.VNEditorApp._json_allowed_keys(("theme", "game_fonts"))),
            {"text", "name", "button", "intro"},
        )


if __name__ == "__main__":
    unittest.main()
