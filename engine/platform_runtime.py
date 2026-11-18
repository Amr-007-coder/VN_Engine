"""Platform display helpers shared by desktop and WebView runtimes."""

from __future__ import annotations

import math
import sys


ANDROID_WEBVIEW_HOOK_VERSION = 1


def fit_window_size(requested: tuple[int, int], display: tuple[int, int], margin: int = 48) -> tuple[int, int]:
    """Fit a design resolution inside a monitor while preserving its aspect ratio."""
    width, height = requested
    display_width, display_height = display
    if min(width, height, display_width, display_height) < 1:
        raise ValueError("Window and display dimensions must be positive.")
    available_width = max(1, display_width - margin * 2)
    available_height = max(1, display_height - margin * 2)
    scale = min(1.0, available_width / width, available_height / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def centered_window_position(size: tuple[int, int], display: tuple[int, int]) -> tuple[int, int]:
    """Return a visible, centered position on the primary display."""
    width, height = size
    display_width, display_height = display
    return max(0, (display_width - width) // 2), max(0, (display_height - height) // 2)


def primary_display_size(display_module) -> tuple[int, int] | None:
    """Return a usable primary monitor size, including headless-safe fallback."""
    try:
        sizes = display_module.get_desktop_sizes()
    except Exception:
        sizes = []
    for size in sizes if isinstance(sizes, (tuple, list)) else ():
        if isinstance(size, (tuple, list)) and len(size) == 2:
            try:
                width, height = int(size[0]), int(size[1])
            except (TypeError, ValueError, OverflowError):
                continue
            if width > 0 and height > 0:
                return width, height
    try:
        info = display_module.Info()
        width, height = int(info.current_w), int(info.current_h)
    except Exception:
        return None
    return (width, height) if width > 0 and height > 0 else None


def set_process_dpi_awareness() -> None:
    """Ask Windows to report monitor dimensions in per-monitor-aware pixels."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError, TypeError):
        # Older Windows releases can still run with SDL's default DPI behavior.
        return


def configure_webview_viewport(project, platform_module=None) -> tuple[int, int] | None:
    """Read the CSS viewport, size the Pygbag canvas, and fit the main menu."""
    if platform_module is None:
        try:
            import platform as platform_module
        except ImportError:
            return None
    try:
        window = platform_module.window
        canvas = window.canvas
    except AttributeError:
        return None

    try:
        ratio = float(getattr(window, "devicePixelRatio", 1.0) or 1.0)
    except (TypeError, ValueError, OverflowError):
        ratio = 1.0
    if not math.isfinite(ratio) or ratio <= 0:
        ratio = 1.0
    css_width = getattr(canvas, "clientWidth", 0) or getattr(window, "innerWidth", 0)
    css_height = getattr(canvas, "clientHeight", 0) or getattr(window, "innerHeight", 0)
    try:
        width = round(float(css_width) * ratio)
        height = round(float(css_height) * ratio)
    except (TypeError, ValueError, OverflowError):
        return None
    if width < 1 or height < 1:
        return None

    size = (width, height)
    values = project.values
    values["window"]["width"], values["window"]["height"] = size
    _fit_main_menu(project, size)
    sync_webview_canvas(platform_module, size, notify=False)
    return size


def sync_webview_canvas(platform_module, size: tuple[int, int], notify: bool = True) -> None:
    """Keep the Pygbag framebuffer aligned with the actual Pygame surface."""
    if platform_module is None:
        return
    width, height = size
    try:
        window = platform_module.window
        window.canvas.width = width
        window.canvas.height = height
        config = window.config
        config.gui_divider = 1
        config.gui_debug = 1
        config.fb_ar = width / max(1, height)
        config.fb_width = width
        config.fb_height = height
        if notify:
            resize = getattr(window, "window_resize", None)
            if callable(resize):
                resize()
    except (AttributeError, TypeError, ValueError):
        return


def _fit_main_menu(project, size: tuple[int, int]) -> None:
    values = project.values
    theme = values.setdefault("theme", {})
    if not isinstance(theme, dict):
        theme = {}
        values["theme"] = theme
    menu_theme = theme.setdefault("menu", {})
    if not isinstance(menu_theme, dict):
        menu_theme = {}
        theme["menu"] = menu_theme

    main_menu = project.menus.get("main", {})
    items = main_menu.get("items", []) if isinstance(main_menu, dict) else []
    item_count = len(items) + (not any(item.get("action") == "open_extras" for item in items if isinstance(item, dict)))
    row_height = menu_theme.get("row_height")
    row_gap = menu_theme.get("row_gap")
    menu_top = menu_theme.get("top")
    menu_title_y = menu_theme.get("title_y")
    row_height = 56 if row_height is None else row_height
    row_gap = 9 if row_gap is None else row_gap
    menu_top = 190 if menu_top is None else menu_top
    menu_title_y = 112 if menu_title_y is None else menu_title_y
    try:
        menu_height = item_count * max(1, int(row_height)) + max(0, item_count - 1) * max(0, int(row_gap))
        centered_top = max(0, (size[1] - menu_height) // 2)
        menu_theme["top"] = min(int(menu_top), centered_top)
        menu_theme["title_y"] = min(int(menu_title_y), max(30, centered_top // 2))
    except (TypeError, ValueError, OverflowError):
        return
