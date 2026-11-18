import unittest
from types import SimpleNamespace

import pygame

from engine.engine import Engine, _intro_warning_card_needed
from engine.menu_renderer import DeclarativeMenuRenderer
from engine.project import ProjectConfig
from engine.theme import resolve_theme, validate_menu_grid
from engine.ui import Button
from engine.ui_scale import get_ui_scale, set_ui_scale


class VisualCustomizationTests(unittest.TestCase):
    def test_notice_card_is_skipped_only_when_text_and_images_are_absent(self):
        self.assertFalse(_intro_warning_card_needed("", None, None))
        self.assertFalse(_intro_warning_card_needed(" \n ", None, None))
        self.assertTrue(_intro_warning_card_needed("Take care", None, None))
        self.assertTrue(_intro_warning_card_needed("", object(), None))
        self.assertTrue(_intro_warning_card_needed("", None, object()))

    def test_menu_grid_supports_ragged_rows_and_requires_each_item_once(self):
        grid = [[0, 1, 0], [2, None, 3], [0, 4]]
        validate_menu_grid(grid, 4)
        with self.assertRaisesRegex(ValueError, "must not repeat"):
            validate_menu_grid([[1, 1]], 2)
        with self.assertRaisesRegex(ValueError, "every button exactly once"):
            validate_menu_grid([[1, 3]], 2)
        with self.assertRaisesRegex(ValueError, "positive button indexes"):
            validate_menu_grid([[True]], 1)

    def test_menu_grid_places_fixed_size_buttons_at_cell_centers(self):
        original_scale = get_ui_scale()
        set_ui_scale(1.0)
        try:
            grid = [[0, 1, 0], [2, None, 3], [0, 4]]
            rects = DeclarativeMenuRenderer._grid_rectangles(
                grid,
                4,
                (900, 600),
                {"button_width": 120, "button_height": 80},
            )
        finally:
            set_ui_scale(original_scale)

        self.assertEqual(
            [rect.center for rect in rects],
            [(450, 100), (150, 300), (750, 300), (450, 500)],
        )
        self.assertEqual([rect.size for rect in rects], [(120, 80)] * 4)

    def test_project_config_accepts_valid_independent_grid_and_rejects_bad_grid(self):
        ProjectConfig({
            "theme": {
                "menu": {
                    "screens": {
                        "main": {
                            "grid": [[1, 2, 3], [4, 5, 6], [7]],
                            "button_width": 240,
                            "button_height": 72,
                        }
                    }
                }
            }
        })

        with self.assertRaisesRegex(ValueError, "every button exactly once"):
            ProjectConfig({
                "theme": {
                    "menu": {
                        "screens": {
                            "main": {"grid": [[1, 2, 3], [4, 5, 0]]}
                        }
                    }
                }
            })

    def test_textbox_geometry_is_window_relative_and_panel_opacity_is_applied(self):
        class Assets:
            @staticmethod
            def load_image(_name):
                return pygame.Surface((4, 4), pygame.SRCALPHA)

        engine = Engine.__new__(Engine)
        engine.theme = resolve_theme({
            "textbox": {
                "background": "images/frame.png",
                "x": 0.1,
                "bottom": 0.0,
                "width": 0.6,
                "height": 0.3,
                "opacity": 0.4,
            }
        })
        engine.window_size = (1000, 800)
        engine.assets = Assets()
        engine.project = SimpleNamespace(values={"dialogue_buttons": {}})
        engine.settings = SimpleNamespace(values={})

        textbox = Engine._create_textbox(engine)

        self.assertEqual(textbox.rect, pygame.Rect(100, 560, 600, 240))
        self.assertEqual(textbox.panel.surface.get_alpha(), round(255 * 0.4))
        effective_panel_alpha = round(
            textbox.panel.surface.get_at((textbox.panel.rect.centerx, textbox.panel.rect.centery)).a
            * textbox.panel.surface.get_alpha()
            / 255
        )
        self.assertEqual(effective_panel_alpha, round(128 * 0.4))

    def test_one_choice_button_image_supplies_both_states(self):
        image = pygame.Surface((8, 8), pygame.SRCALPHA)
        image.fill((40, 100, 200, 255))

        button = Button(0, 0, 80, 40, normal_image=image)

        self.assertEqual(button.normal_image.get_size(), (80, 40))
        self.assertEqual(button.hovered_image.get_size(), (80, 40))
        self.assertEqual(button.normal_image.get_at((10, 10)), button.hovered_image.get_at((10, 10)))


if __name__ == "__main__":
    unittest.main()
