"""Android WebView entry point for Pygbag builds."""

import asyncio
import platform
import pygame
import pygame.surface

from engine.engine import Engine
from engine.project import ProjectConfig


project = ProjectConfig.load()
device_pixel_ratio = max(
    1.0,
    float(getattr(platform.window, "devicePixelRatio", 1.0) or 1.0),
)
viewport_width = max(1, round(float(platform.window.canvas.clientWidth) * device_pixel_ratio))
viewport_height = max(1, round(float(platform.window.canvas.clientHeight) * device_pixel_ratio))
viewport_size = (viewport_width, viewport_height)
platform.window.canvas.width = viewport_width
platform.window.canvas.height = viewport_height
platform.window.config.gui_divider = 1
platform.window.config.gui_debug = 1
platform.window.config.fb_ar = viewport_width / viewport_height
platform.window.config.fb_width = viewport_width
platform.window.config.fb_height = viewport_height
project.values["window"]["width"] = viewport_width
project.values["window"]["height"] = viewport_height

menu_theme = project.values.setdefault("theme", {}).get("menu")
if not isinstance(menu_theme, dict):
    menu_theme = {}
    project.values["theme"]["menu"] = menu_theme
row_height_value = menu_theme.get("row_height", 56)
row_gap_value = menu_theme.get("row_gap", 9)
menu_top_value = menu_theme.get("top", 190)
menu_title_value = menu_theme.get("title_y", 112)
row_height_value = 56 if row_height_value is None else row_height_value
row_gap_value = 9 if row_gap_value is None else row_gap_value
menu_top_value = 190 if menu_top_value is None else menu_top_value
menu_title_value = 112 if menu_title_value is None else menu_title_value
menu_items = project.menus["main"]["items"]
row_height = max(1, int(row_height_value))
row_gap = max(0, int(row_gap_value))
menu_height = len(menu_items) * row_height + max(0, len(menu_items) - 1) * row_gap
centered_top = max(0, (viewport_height - menu_height) // 2)
menu_theme["top"] = min(int(menu_top_value), centered_top)
menu_theme["title_y"] = min(int(menu_title_value), max(30, centered_top // 2))
project.menus["settings"]["items"] = [
    item for item in project.menus["settings"]["items"]
    if not isinstance(item, dict) or item.get("setting") != "fullscreen"
]

engine = Engine(project_config=project, window_size=viewport_size)
engine.allow_fullscreen = False
engine.initialize()
actual_width, actual_height = engine.screen.get_size()
engine.windowed_size = (actual_width, actual_height)
platform.window.canvas.width = actual_width
platform.window.canvas.height = actual_height
platform.window.config.fb_ar = actual_width / actual_height
platform.window.config.fb_width = actual_width
platform.window.config.fb_height = actual_height
centered_top = max(0, (actual_height - menu_height) // 2)
engine.theme["menu"]["top"] = min(int(engine.theme["menu"].get("top", 190)), centered_top)
engine.theme["menu"]["title_y"] = min(
    int(engine.theme["menu"].get("title_y", 112)),
    max(30, centered_top // 2),
)
platform.window.console.info(
    f"VN Android canvas: {viewport_width}x{viewport_height} device px; "
    f"Pygame: {actual_width}x{actual_height}; DPR: {device_pixel_ratio}"
)
platform.window.window_resize()


async def main():
    engine.running = True
    try:
        await engine.play_intro_async()
        while engine.running:
            engine.step()
            engine.clock.tick(engine.fps)
            await asyncio.sleep(0)
    finally:
        engine.shutdown()


asyncio.run(main())
