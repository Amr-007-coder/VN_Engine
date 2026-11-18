import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pygame

from engine.platform_runtime import (
    centered_window_position,
    configure_webview_viewport,
    fit_window_size,
)
from engine.engine import Engine
from engine.project import ProjectConfig


class PlatformRuntimeTests(unittest.TestCase):
    def test_window_fits_monitor_and_centers_inside_it(self):
        size = fit_window_size((1920, 1200), (1366, 768))
        self.assertLessEqual(size[0], 1270)
        self.assertLessEqual(size[1], 672)
        self.assertEqual(centered_window_position(size, (1366, 768)), ((1366 - size[0]) // 2, (768 - size[1]) // 2))

    def test_webview_hook_uses_css_viewport_and_device_pixel_ratio(self):
        canvas = SimpleNamespace(clientWidth=400, clientHeight=800, width=0, height=0)
        config = SimpleNamespace()
        window = SimpleNamespace(canvas=canvas, config=config, devicePixelRatio=2, window_resize=lambda: None)
        project = SimpleNamespace(
            values={
                "window": {"width": 1920, "height": 1200},
                "theme": {"menu": {}},
            },
            menus={"main": {"items": [{"action": "new_game"}]}, "settings": {"items": []}},
        )

        self.assertEqual(configure_webview_viewport(project, SimpleNamespace(window=window)), (800, 1600))
        self.assertEqual((canvas.width, canvas.height), (800, 1600))
        self.assertEqual((config.fb_width, config.fb_height), (800, 1600))
        self.assertEqual((project.values["window"]["width"], project.values["window"]["height"]), (800, 1600))

    def test_offscreen_recovery_recenters_the_window_on_the_primary_display(self):
        engine = Engine.__new__(Engine)
        engine.allow_fullscreen = True
        engine.settings = SimpleNamespace(values={"fullscreen": False})
        engine.windowed_size = (1920, 1200)
        engine._sync_window_size = Mock()
        surface = pygame.Surface((1075, 672))

        with patch("engine.engine.primary_display_size", return_value=(1366, 768)), \
                patch("pygame.display.set_mode", return_value=surface) as set_mode, \
                patch("pygame.display.set_window_position") as set_position:
            engine._recover_window_position()

        set_mode.assert_called_once_with((1075, 672))
        set_position.assert_called_once_with(145, 48)
        engine._sync_window_size.assert_called_once_with()

    def test_engine_uses_the_webview_runtime_hook_and_disables_fullscreen(self):
        project = ProjectConfig()
        with patch("engine.engine.sys.platform", "emscripten"), \
                patch("engine.engine.configure_webview_viewport", return_value=(800, 600)) as configure:
            engine = Engine(project_config=project)

        configure.assert_called_once()
        self.assertEqual(engine.window_size, (800, 600))
        self.assertFalse(engine.allow_fullscreen)

    def test_recovery_keyboard_shortcut_is_global(self):
        engine = Engine.__new__(Engine)
        engine.running = True
        engine.mode = "main_menu"
        engine._recover_window_position = Mock()
        event = pygame.event.Event(
            pygame.KEYDOWN,
            key=pygame.K_HOME,
            mod=pygame.KMOD_CTRL | pygame.KMOD_SHIFT,
        )
        with patch("pygame.event.get", return_value=[event]):
            engine._handle_events()
        engine._recover_window_position.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
