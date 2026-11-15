from copy import deepcopy


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
    },
    "slot": {
        "layout": "list",
        "normal": None,
        "hovered": None,
        "width": 900,
        "row_height": 82,
        "row_gap": 8,
        "icon_width": 30,
        "icon_height": 72,
        "text_offset": 62,
    },
    "textbox": {
        "background": None,
        "color": None,
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
