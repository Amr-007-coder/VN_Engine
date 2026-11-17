from copy import deepcopy


MENU_SCREEN_NAMES = ("main", "pause", "settings", "slots", "credits")


def validate_menu_grid(grid, item_count=None):
    if not isinstance(grid, list) or not grid:
        raise ValueError("Menu grid must be a non-empty list of rows.")
    indexes = []
    columns = 0
    for row_index, row in enumerate(grid, 1):
        if not isinstance(row, list):
            raise ValueError(f"Menu grid row {row_index} must be a list.")
        columns = max(columns, len(row))
        for cell in row:
            if cell is None or (
                isinstance(cell, int) and not isinstance(cell, bool) and cell == 0
            ):
                continue
            if not isinstance(cell, int) or isinstance(cell, bool) or cell < 1:
                raise ValueError("Menu grid cells must be null, 0, or positive button indexes.")
            indexes.append(cell)
    if columns == 0 or not indexes:
        raise ValueError("Menu grid must place at least one button.")
    if len(indexes) != len(set(indexes)):
        raise ValueError("Menu grid button indexes must not repeat.")
    expected_count = item_count if item_count is not None else max(indexes)
    if sorted(indexes) != list(range(1, expected_count + 1)):
        raise ValueError(f"Menu grid must place every button exactly once from 1 to {expected_count}.")


DEFAULT_THEME = {
    "colors": {
        "background": [30, 30, 45],
        "text": [230, 230, 230],
        "muted": [170, 170, 180],
        "normal": [18, 18, 29],
        "hover": [73, 50, 65],
        "selected": [45, 92, 78],
        "border": [112, 86, 101],
        "accent": [233, 79, 88],
        "panel": [0, 0, 0, 128],
    },
    "fonts": {
        "menu": None,
        "title": None,
        "item_size": 20,
        "detail_size": 16,
        "title_size": 30,
    },
    "menu": {
        "layout": "centered",
        "background": None,
        "width": 860,
        "x": None,
        "row_height": 56,
        "row_gap": 9,
        "title_y": 112,
        "top": 190,
        "border_radius": 8,
        "screens": {
            "main": {
                "background": None, "alignment": None, "top": None, "row_gap": None,
                "button_width": None, "button_height": None, "grid": None,
                "buttons": {"normal": None, "hovered": None},
            },
            "pause": {
                "background": None, "alignment": None, "top": None, "row_gap": None,
                "button_width": None, "button_height": None, "grid": None,
                "buttons": {"normal": None, "hovered": None},
            },
            "settings": {
                "background": None, "alignment": None, "top": None, "row_gap": None,
                "button_width": None, "button_height": None, "grid": None,
                "buttons": {"normal": None, "hovered": None},
            },
            "slots": {
                "background": None, "alignment": None, "top": None, "row_gap": None,
                "button_width": None, "button_height": None, "grid": None,
                "buttons": {"normal": None, "hovered": None},
            },
            "credits": {
                "background": None, "alignment": None, "top": None, "row_gap": None,
                "button_width": None, "button_height": None,
                "buttons": {"normal": None, "hovered": None},
            },
        },
    },
    "textbox": {
        "background": None,
        "color": None,
        "x": 0.02,
        "bottom": 0.0,
        "width": 0.96,
        "height": 0.21,
        "opacity": 0.95,
    },
    "choice_buttons": {
        "normal": None,
        "hovered": None,
        "width": 900,
        "height": 56,
        "gap": 12,
    },
    "pause_button": {
        "image": None,
        "size": 78,
        "margin": 16,
    },
    "sounds": {
        "hover": "sounds/hover_button.wav",
        "click": "sounds/click_button.wav",
        "cancel": "sounds/click_button.wav",
        "load": "sounds/click_button.wav",
    },
}


def resolve_theme(project_theme=None):
    """Merge project values over complete engine defaults."""
    return _merge(DEFAULT_THEME, project_theme or {})


def _merge(defaults, overrides):
    result = deepcopy(defaults)
    if not isinstance(overrides, dict):
        return result
    for key, value in overrides.items():
        if isinstance(result.get(key), dict):
            if isinstance(value, dict):
                result[key] = _merge(result[key], value)
        elif value is not None:
            result[key] = deepcopy(value)
    return result
