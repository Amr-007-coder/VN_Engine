"""Shared sizing helpers for the engine's user interface."""

MIN_UI_SCALE = 0.8
MAX_UI_SCALE = 1.6
DEFAULT_UI_SCALE = 1.2

_ui_scale = DEFAULT_UI_SCALE


def set_ui_scale(value) -> float:
    """Set the interface scale, clamped to the range exposed in Settings."""
    global _ui_scale
    try:
        scale = float(value)
    except (TypeError, ValueError):
        scale = DEFAULT_UI_SCALE
    _ui_scale = min(MAX_UI_SCALE, max(MIN_UI_SCALE, scale))
    return _ui_scale


def get_ui_scale() -> float:
    return _ui_scale


def ui_size(value: int | float) -> int:
    """Scale a design-space length while keeping nonzero UI elements visible."""
    scaled = round(float(value) * _ui_scale)
    return max(1, scaled) if value else 0
