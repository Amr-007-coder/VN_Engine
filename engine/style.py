"""Versioned, data-only visual style configuration for a VN project."""

from copy import deepcopy

from engine.theme import DEFAULT_THEME


DEFAULT_STYLE = {
    "schema_version": 1,
    "theme": DEFAULT_THEME,
    "dialogue_buttons": {
        "back": {"visible": True, "label": "Back", "label_alignment": "center"},
        "history": {"visible": True, "label": "History", "label_alignment": "center"},
        "quick_save": {"visible": True, "label": "Q. Save", "label_alignment": "center"},
        "quick_load": {"visible": True, "label": "Q. Load", "label_alignment": "center"},
        "auto": {"visible": True, "label": "Auto", "label_alignment": "center"},
        "mute": {"visible": True, "label": "Mute", "label_alignment": "center"},
    },
    "intro": {
        "credit_image": None,
        "warning_image": "content_warning.png",
        "headphones_image": "headphones.png",
    },
    "characters": {},
    "components": {
        "scene": {"background_color": [30, 30, 45], "background_fit": "cover"},
        "intro_cards": {
            "background_color": [0, 0, 0], "logo_max_screen_fraction": 0.45, "logo_y_offset": 20, "allow_logo_upscale": False,
            "logo_hold": 3.0, "credit_hold": 2.5, "warning_hold": 2.5, "fade_seconds": 0.75,
            "font": "standard.ttf", "font_size": 40, "small_font_size": 21,
            "text_color": [238, 238, 245], "small_text_color": [190, 198, 215], "trademark_color": [238, 238, 245],
            "trademark_right_offset": 5, "trademark_top_offset": 95,
            "copyright_bottom_offset": 100, "copyright_line_gap": 28,
            "credit_image_width_fraction": 0.5, "credit_image_height_fraction": 0.5,
            "credit_image_y_offset": 90, "warning_image_y_offset": 150,
            "warning_image_width_fraction": 0.5, "warning_image_height_fraction": 0.5,
            "extra_image_width_fraction": 0.333, "extra_image_height_fraction": 0.333, "extra_image_y_offset": 190,
            "allow_card_image_upscale": False,
            "credit_text_gap": 24,
            "star_count": 36, "star_min_brightness": 0.2, "star_max_brightness": 1.0,
            "star_base_shade": 75, "star_shade_range": 100, "star_blue_offset": 12, "star_radius": 1,
            "star_twinkle_period_ms": 520,
        },
        "chrome": {
            "scrollbar": {"track_color": [45, 43, 56], "thumb_color": [170, 150, 192], "width": 8, "margin_right": 25, "inset_top": 18, "inset_bottom": 18, "min_thumb": 28, "radius": 4},
            "status": {"font_size": 16, "color": [233, 79, 88], "bottom": 40},
            "autosave_notice": {"font_size": 18, "text_color": [230, 230, 230], "background_color": [0, 0, 0, 190], "top": 18, "padding_x": 28, "padding_y": 16, "radius": 8},
            "mode_badge": {"font_size": 16, "text_color": [233, 79, 88], "background_color": [0, 0, 0, 190], "top": 18, "right": 20, "padding_x": 20, "padding_y": 12, "radius": 6},
            "test_hint": {"font_size": 14, "text_color": [230, 230, 230], "background_color": [0, 0, 0, 175], "left": 18, "top": 18, "padding_x": 18, "padding_y": 10, "radius": 5},
            "countdown": {"font": "standard.ttf", "font_size": 16, "text_color": [230, 230, 230], "background_color": [0, 0, 0, 190], "top": 12, "padding_x": 20, "padding_y": 10, "radius": 6},
        },
        "mod_details": {"font": "standard.ttf", "font_size": 16, "title_font_size": 28, "title_color": [233, 79, 88], "text_color": [230, 230, 230], "button_color": [18, 18, 29], "button_selected_color": [45, 92, 78], "button_text_color": [230, 230, 230], "button_border_color": [112, 86, 101], "button_height": 44, "button_width": 190, "button_min_width": 100, "button_gap": 14, "button_bottom": 26, "button_horizontal_margin": 40, "content_top": 100, "content_bottom": 210, "line_gap": 5, "title_top": 58, "radius": 5, "border_width": 1},
        "gallery": {"image_fit": "contain", "background_color": [8, 8, 16, 255], "padding": 24},
        "dialogue_text": {
            "text": {"color": [230, 230, 230], "highlight_color": [233, 79, 88], "font": "standard.ttf", "font_size": 24, "margin_left": 40, "margin_top": 55, "line_gap": 3},
            "speaker": {"color": [233, 79, 88], "font": "standard.ttf", "font_size": 28, "margin_left": 40, "margin_top": 15},
        },
        "textbox": {"opacity": 0.95, "fit": "stretch", "nine_slice": None, "fade_sides": 0.15, "background_image": None, "background_color": [0, 0, 0, 128], "padding": 0, "border_color": None, "border_width": 0, "radius": 0},
        "choices": {
            "text_color": [230, 230, 230], "font": "standard.ttf", "font_size": 20, "padding": 8, "radius": 6, "border_width": 0, "opacity": 1.0, "fit": "stretch", "nine_slice": None, "width": None, "height": None, "gap": 12, "label_alignment": "center",
            "states": {
                "normal": {"color": [18, 18, 29], "image": None},
                "hover": {"color": [73, 50, 65], "image": None},
                "focus": {"color": [45, 92, 78], "image": None},
                "pressed": {"color": [45, 92, 78], "image": None},
                "disabled": {"color": [70, 70, 78], "image": None},
                "selected": {"color": [45, 92, 78], "image": None},
            },
        },
        "dialogue_controls": {
            "height": 22, "gap": 8, "min_width": 58, "padding": 14, "radius": 4, "border_width": 0, "opacity": 1.0, "fit": "stretch", "nine_slice": None, "font": "standard.ttf", "font_size": 16,
            "text_color": [230, 230, 230], "focus_color": [233, 79, 88], "disabled_color": [130, 130, 138],
            "states": {
                "normal": {"color": None, "image": None},
                "hover": {"color": [73, 50, 65], "image": None},
                "focus": {"color": [45, 92, 78], "image": None},
                "pressed": {"color": [45, 92, 78], "image": None},
                "disabled": {"color": [70, 70, 78], "image": None},
                "selected": {"color": [45, 92, 78], "image": None},
            },
        },
        "menu": {
            "title_color": [230, 230, 230], "title_font_size": 30,
            "title_font": "standard.ttf", "title_alignment": "center", "title_padding": 8,
            "item_color": [230, 230, 230], "item_font": "standard.ttf", "item_font_size": 20,
            "detail_color": [178, 178, 188], "detail_font": "standard.ttf", "detail_font_size": 16,
            "label_alignment": "left",
            "background_image": None, "background_fit": "cover",
            "border_width": 1, "radius": 8, "padding": 8,
            "opacity": 1.0, "nine_slice": None,
            "panel_color": [8, 8, 16, 210], "panel_border_color": [95, 84, 112],
            "panel_border_width": 1, "panel_radius": 10,
            "states": {
                "normal": {"color": [18, 18, 29], "image": None},
                "hover": {"color": [73, 50, 65], "image": None},
                "focus": {"color": [73, 50, 65], "image": None},
                "pressed": {"color": [45, 92, 78], "image": None},
                "disabled": {"color": [42, 42, 48], "image": None},
                "selected": {"color": [45, 92, 78], "image": None},
            },
        },
        "history": {
            "scrim_color": [0, 0, 0, 190], "panel_color": [24, 25, 38],
            "border_color": [112, 86, 101], "border_width": 2, "radius": 10,
            "opacity": 1.0,
            "padding": 24, "heading_top": 18, "footer_bottom": 34, "line_gap": 3,
            "font": "standard.ttf", "font_size": 20, "heading_font_size": 28, "text_color": [230, 230, 230],
            "heading_color": [233, 79, 88], "footer_color": [230, 230, 230],
            "opacity": 1.0,
        },
        "save_slots": {
            "selected_color": [45, 92, 78], "normal_color": [18, 18, 29],
            "item_color": [230, 230, 230], "detail_color": [178, 178, 188],
            "border_color": [112, 86, 101], "border_width": 1, "radius": 5,
            "thumbnail_fit": "contain", "padding": 8,
            "nine_slice": None,
            "action_height": 46, "action_width": 150, "action_gap": 12,
            "font": "standard.ttf", "font_size": 18, "text_color": [230, 230, 230], "disabled_color": [115, 115, 122], "label_alignment": "center",
            "opacity": 1.0,
            "states": {
                "normal": {"color": [18, 18, 29], "image": None},
                "hover": {"color": [73, 50, 65], "image": None},
                "focus": {"color": [73, 50, 65], "image": None},
                "pressed": {"color": [45, 92, 78], "image": None},
                "disabled": {"color": [42, 42, 48], "image": None},
                "selected": {"color": [45, 92, 78], "image": None},
            },
        },
        "pause_control": {"image": None, "size": 78, "margin": 16, "background_color": [242, 242, 247], "fit": "contain", "nine_slice": None, "padding": 8, "opacity": 1.0,
                           "states": {"normal": {"color": None, "image": None}, "hover": {"color": None, "image": None}}},
        "overlays": {
            "scrim_color": [0, 0, 0, 190], "panel_color": [8, 8, 16, 210],
            "border_color": [95, 84, 112], "border_width": 1, "radius": 10,
            "padding": 24, "text_color": [230, 230, 230],
            "opacity": 1.0,
            "font": "standard.ttf", "title_font_size": 28, "body_font_size": 20, "button_font_size": 18,
            "label_alignment": "center",
            "field_color": [8, 9, 16], "field_border_color": [112, 86, 101],
            "button_gap": 16, "button_height": 38, "button_width": 130,
            "button_color": [73, 50, 65], "hint_color": [145, 145, 155],
            "field_radius": 5, "field_border_width": 1, "heading_top": 18,
            "title_color": [233, 79, 88], "selection_color": [42, 62, 91, 235],
            "value_color": [205, 214, 228], "selected_text_color": [250, 250, 250],
            "line_height": 30,
            "states": {
                "normal": {"color": [73, 50, 65], "image": None},
                "hover": {"color": [96, 65, 83], "image": None},
                "focus": {"color": [45, 92, 78], "image": None},
                "pressed": {"color": [45, 92, 78], "image": None},
                "disabled": {"color": [70, 70, 78], "image": None},
                "selected": {"color": [45, 92, 78], "image": None},
            },
        },
    },
    "layouts": {
        "safe_area": {"top": 0, "right": 0, "bottom": 0, "left": 0},
        "profiles": [
            {
                "name": "mobile_portrait",
                "when": {"max_aspect": 0.9},
                "safe_area": {"top": "4%", "right": "3%", "bottom": "3%", "left": "3%"},
                "screens": {
                    "dialogue": {"components": {
                        "textbox": {"anchor": "bottom_left", "x": "1%", "bottom": "1%", "width": "98%", "height": "31%"},
                        "choices": {"anchor": "top_center", "x": 0, "y": "2%", "width": "94%", "height": "58%", "type": "flex", "direction": "column", "item_size": 64, "gap": 10, "justify": "center"},
                    }},
                    "history": {"components": {"panel": {"anchor": "center", "width": "94%", "height": "92%"}}},
                    "menu": {"components": {
                        "title": {"anchor": "top_center", "y": "3%", "width": "94%", "height": 64},
                        "items": {"anchor": "center", "width": "94%", "height": "88%", "type": "flex", "direction": "column", "item_size": 58, "gap": 8},
                    }},
                    "save_slots": {"components": {
                        "title": {"anchor": "top_center", "y": "3%", "width": "94%", "height": 56},
                        "items": {"anchor": "top_center", "y": "8%", "width": "94%", "height": "72%", "type": "grid", "columns": 1, "gap": 8},
                        "actions": {"anchor": "bottom_center", "width": "94%", "height": "27%", "bottom": 1, "type": "grid", "columns": 2, "gap": 6},
                    }},
                    "overlays": {"components": {
                        "panel": {"anchor": "center", "width": "92%", "height": "82%"},
                        "confirmation": {"anchor": "center", "width": "92%", "height": "36%"},
                        "confirmation_actions": {"anchor": "bottom_center", "width": "90%", "height": 44, "bottom": 8, "type": "flex", "direction": "row", "item_size": 110, "gap": 16},
                        "save_name": {"anchor": "center", "width": "92%", "height": "40%"},
                        "save_name_field": {"anchor": "top_center", "width": "92%", "height": 48, "y": 72},
                        "save_name_actions": {"anchor": "bottom_center", "width": "92%", "height": 38, "bottom": 18, "type": "flex", "direction": "row", "item_size": 130, "gap": 16},
                        "story_input": {"anchor": "center", "width": "94%", "height": "82%"},
                        "story_input_field": {"anchor": "top_left", "x": 24, "y": 76, "width": "92%", "height": 46},
                        "variable_inspector": {"anchor": "center", "width": "92%", "height": "76%"},
                    }},
                },
            },
            {
                "name": "compact_landscape",
                "when": {"max_width": 900, "min_aspect": 1.3, "max_aspect": 2.2},
                "safe_area": {"top": "3%", "right": "4%", "bottom": "3%", "left": "4%"},
                "screens": {
                    "dialogue": {"components": {
                        "textbox": {"anchor": "bottom_left", "x": "1%", "bottom": "1%", "width": "98%", "height": "38%"},
                        "choices": {"anchor": "top_center", "y": "2%", "width": "92%", "height": "52%", "type": "flex", "direction": "column", "item_size": 48, "gap": 6},
                    }},
                    "menu": {"components": {
                        "title": {"anchor": "top_center", "y": "2%", "width": "92%", "height": 52},
                        "items": {"anchor": "center", "width": "86%", "height": "86%", "type": "flex", "direction": "column", "item_size": 48, "gap": 6},
                    }},
                    "history": {"components": {"panel": {"anchor": "center", "width": "92%", "height": "92%"}}},
                    "save_slots": {"components": {
                        "title": {"anchor": "top_center", "y": "2%", "width": "92%", "height": 48},
                        "items": {"anchor": "top_center", "y": "7%", "width": "92%", "height": "72%", "type": "grid", "columns": 2, "gap": 8},
                        "actions": {"anchor": "bottom_center", "width": "92%", "height": "26%", "bottom": 1, "type": "grid", "columns": 3, "gap": 6},
                    }},
                    "overlays": {"components": {
                        "panel": {"anchor": "center", "width": "92%", "height": "88%"},
                        "confirmation": {"anchor": "center", "width": "90%", "height": "52%"},
                        "save_name": {"anchor": "center", "width": "90%", "height": "58%"},
                        "story_input": {"anchor": "center", "width": "92%", "height": "88%"},
                        "variable_inspector": {"anchor": "center", "width": "92%", "height": "84%"},
                    }},
                    "cg_viewer": {"components": {"image": {"anchor": "center", "width": "96%", "height": "94%"}}},
                },
            },
        ],
        "screens": {
            "dialogue": {"components": {
                "textbox": {"anchor": "bottom_left", "x": "2%", "bottom": 0, "width": "96%", "height": "21%"},
                "choices": {"anchor": "top_center", "x": 0, "y": "3%", "width": "90%", "height": "64%", "type": "flex", "direction": "column", "item_size": 56, "gap": 12, "justify": "center"},
                "controls": {"anchor": "bottom_center", "width": "96%", "height": 22, "y": 8, "type": "flex", "direction": "row", "gap": 8},
                "pause_control": {"anchor": "top_left", "x": 16, "y": 16, "width": 78, "height": 78},
            }},
            "menu": {"components": {
                "title": {"anchor": "top_center", "y": "3%", "width": "90%", "height": 72},
                "items": {"anchor": "center", "width": "90%", "height": "88%", "type": "flex", "direction": "column", "item_size": 56, "gap": 9},
                "panel": {"anchor": "center", "width": "90%", "height": "88%", "constraints": {"max_width": 1080}},
            }},
            "history": {"components": {"panel": {"anchor": "center", "width": "86%", "height": "90%", "constraints": {"max_width": 1100}}}},
            "cg_viewer": {"components": {"image": {"anchor": "center", "width": "94%", "height": "92%"}}},
            "save_slots": {"components": {
                "title": {"anchor": "top_center", "y": "3%", "width": "90%", "height": 64},
                "items": {"anchor": "top_center", "y": "8%", "width": "90%", "height": "72%", "type": "grid", "columns": 2, "gap": 12},
                "actions": {"anchor": "bottom_center", "width": "90%", "height": 46, "bottom": 18, "type": "flex", "direction": "row", "item_size": 150, "gap": 12},
            }},
            "overlays": {"components": {
                "panel": {"anchor": "center", "width": "72%", "height": "72%", "constraints": {"max_width": 1000}},
                "confirmation": {"anchor": "center", "width": 560, "height": 190, "constraints": {"max_width": "94%", "max_height": "90%"}},
                "confirmation_actions": {"anchor": "bottom_center", "width": "70%", "height": 38, "bottom": 16, "type": "flex", "direction": "row", "item_size": 110, "gap": 16},
                "save_name": {"anchor": "center", "width": 620, "height": 220, "constraints": {"max_width": "94%", "max_height": "90%"}},
                "save_name_field": {"anchor": "top_center", "width": "92%", "height": 48, "y": 72},
                "save_name_actions": {"anchor": "bottom_center", "width": "70%", "height": 38, "bottom": 18, "type": "flex", "direction": "row", "item_size": 130, "gap": 16},
                "story_input": {"anchor": "center", "width": 720, "height": "76%", "constraints": {"max_width": "94%", "max_height": "92%"}},
                "story_input_field": {"anchor": "top_left", "x": 24, "y": 76, "width": "92%", "height": 46},
                "variable_inspector": {"anchor": "center", "width": 540, "height": 520, "constraints": {"max_width": "94%", "max_height": "92%"}},
            }},
        },
    },
    "skins": {
        "button": {
            "fit": "stretch", "nine_slice": 0,
            "states": {"normal": None, "hover": None, "focus": None, "pressed": None, "disabled": None, "selected": None},
        },
    },
    "variants": {},
}


def merge_style(defaults, overrides):
    result = deepcopy(defaults)
    if not isinstance(overrides, dict):
        return result
    for key, value in overrides.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = merge_style(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def resolve_style(style_values=None):
    if style_values is not None and not isinstance(style_values, dict):
        raise ValueError("Style configuration must contain a JSON object.")
    overrides = style_values or {}
    unknown = set(overrides) - set(DEFAULT_STYLE)
    if unknown:
        names = ", ".join(sorted(map(str, unknown)))
        raise ValueError(f"Unknown style.json key(s): {names}.")
    version = overrides.get("schema_version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise ValueError(f"Unsupported style.json schema_version {version!r}; this engine supports version 1.")
    result = merge_style(DEFAULT_STYLE, overrides)
    _map_legacy_theme_values(result, overrides)
    return result


def style_component(style_values, name):
    components = style_values.get("components", {}) if isinstance(style_values, dict) else {}
    value = components.get(name, {}) if isinstance(components, dict) else {}
    return value if isinstance(value, dict) else {}


def _map_legacy_theme_values(style, overrides):
    """Keep existing theme overrides effective unless a component override is explicit."""
    theme_overrides = overrides.get("theme", {}) if isinstance(overrides, dict) else {}
    component_overrides = overrides.get("components", {}) if isinstance(overrides, dict) else {}
    theme = style["theme"]

    mappings = (
        (("game_fonts", "text"), ("dialogue_text", "text", "font")),
        (("game_fonts", "name"), ("dialogue_text", "speaker", "font")),
        (("game_fonts", "button"), ("choices", "font")),
        (("game_fonts", "button"), ("dialogue_controls", "font")),
        (("game_fonts", "intro"), ("intro_cards", "font")),
        (("game_font_sizes", "text"), ("dialogue_text", "text", "font_size")),
        (("game_font_sizes", "name"), ("dialogue_text", "speaker", "font_size")),
        (("game_font_sizes", "button"), ("choices", "font_size")),
        (("game_font_sizes", "dialogue_controls"), ("dialogue_controls", "font_size")),
        (("game_font_sizes", "intro"), ("intro_cards", "font_size")),
        (("game_font_sizes", "intro_small"), ("intro_cards", "small_font_size")),
        (("colors", "text"), ("dialogue_text", "text", "color")),
        (("colors", "accent"), ("dialogue_text", "text", "highlight_color")),
        (("colors", "accent"), ("dialogue_text", "speaker", "color")),
        (("colors", "text"), ("choices", "text_color")),
        (("fonts", "title_size"), ("menu", "title_font_size")),
        (("fonts", "item_size"), ("menu", "item_font_size")),
        (("fonts", "detail_size"), ("menu", "detail_font_size")),
        (("fonts", "title"), ("menu", "title_font")),
        (("fonts", "menu"), ("menu", "item_font")),
        (("fonts", "menu"), ("menu", "detail_font")),
        (("colors", "text"), ("menu", "item_color")),
        (("colors", "muted"), ("menu", "detail_color")),
        (("menu", "label_alignment"), ("menu", "label_alignment")),
        (("colors", "normal"), ("menu", "states", "normal", "color")),
        (("colors", "hover"), ("menu", "states", "hover", "color")),
        (("colors", "hover"), ("menu", "states", "focus", "color")),
        (("colors", "selected"), ("menu", "states", "selected", "color")),
        (("colors", "border"), ("menu", "states", "normal", "border_color")),
        (("colors", "normal"), ("choices", "states", "normal", "color")),
        (("colors", "hover"), ("choices", "states", "hover", "color")),
        (("colors", "selected"), ("choices", "states", "selected", "color")),
        (("colors", "border"), ("history", "border_color")),
        (("textbox", "opacity"), ("textbox", "opacity")),
        (("textbox", "background"), ("textbox", "background_image")),
        (("textbox", "color"), ("textbox", "background_color")),
        (("choice_buttons", "width"), ("choices", "width")),
        (("choice_buttons", "height"), ("choices", "height")),
        (("choice_buttons", "gap"), ("choices", "gap")),
        (("choice_buttons", "normal"), ("choices", "states", "normal", "image")),
        (("choice_buttons", "hovered"), ("choices", "states", "hover", "image")),
        (("pause_button", "image"), ("pause_control", "image")),
        (("pause_button", "size"), ("pause_control", "size")),
        (("pause_button", "margin"), ("pause_control", "margin")),
        (("menu", "border_radius"), ("menu", "radius")),
    )

    def read_path(source, path):
        value = source
        for key in path:
            if not isinstance(value, dict) or key not in value:
                return None, False
            value = value[key]
        return value, True

    def write_path(destination, path, value):
        target = destination
        for key in path[:-1]:
            target = target.setdefault(key, {})
        target[path[-1]] = deepcopy(value)

    for source_path, destination_path in mappings:
        _old_value, was_set = read_path(theme_overrides, source_path)
        existing, explicitly_set = read_path(component_overrides, destination_path)
        default_value, has_default = read_path(DEFAULT_STYLE["components"], destination_path)
        if explicitly_set and has_default and existing == default_value:
            explicitly_set = False
        if was_set and explicitly_set:
            continue
        if was_set:
            mapped_value, _ = read_path(theme, source_path)
            write_path(style["components"], destination_path, mapped_value)

    layout_mappings = (
        (("textbox", "x"), ("screens", "dialogue", "components", "textbox", "x"), True),
        (("textbox", "bottom"), ("screens", "dialogue", "components", "textbox", "bottom"), True),
        (("textbox", "width"), ("screens", "dialogue", "components", "textbox", "width"), True),
        (("textbox", "height"), ("screens", "dialogue", "components", "textbox", "height"), True),
        (("choice_buttons", "gap"), ("screens", "dialogue", "components", "choices", "gap"), False),
        (("choice_buttons", "height"), ("screens", "dialogue", "components", "choices", "item_size"), False),
        (("choice_buttons", "width"), ("screens", "dialogue", "components", "choices", "width"), False),
        (("menu", "width"), ("screens", "menu", "components", "items", "width"), False),
        (("menu", "row_height"), ("screens", "menu", "components", "items", "item_size"), False),
        (("menu", "row_gap"), ("screens", "menu", "components", "items", "gap"), False),
    )
    layout_overrides = overrides.get("layouts", {}) if isinstance(overrides, dict) else {}
    for source_path, destination_path, fraction in layout_mappings:
        _old_value, was_set = read_path(theme_overrides, source_path)
        _existing, explicitly_set = read_path(layout_overrides, destination_path)
        if not was_set or explicitly_set:
            continue
        value, _ = read_path(theme, source_path)
        if fraction and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = f"{float(value) * 100:g}%"
        write_path(style["layouts"], destination_path, value)


def apply_style_variant(style_values, variant_name="default"):
    """Return a composed style without modifying the creator's base style."""
    style = deepcopy(style_values if isinstance(style_values, dict) else resolve_style())
    variants = style.get("variants", {})
    variant = variants.get(variant_name, {}) if isinstance(variants, dict) else {}
    if isinstance(variant, dict):
        variant = {key: value for key, value in variant.items() if key != "label"}
        style = merge_style(style, variant)
        _map_legacy_theme_values(style, variant)
    style["variants"] = variants if isinstance(variants, dict) else {}
    style["active_variant"] = variant_name
    return style


def split_style_from_project(project_values, style_values=None):
    """Return clean project settings and merged style, migrating legacy keys."""
    if not isinstance(project_values, dict):
        raise ValueError("Project configuration must contain a JSON object.")
    if style_values is not None and not isinstance(style_values, dict):
        raise ValueError("Style configuration must contain a JSON object.")
    project = deepcopy(project_values)
    legacy_style = {}
    for key in ("theme", "dialogue_buttons"):
        if key in project:
            legacy_style[key] = project.pop(key)

    if "characters" in project:
        legacy_style["characters"] = project.pop("characters")

    intro = project.get("intro")
    if isinstance(intro, dict):
        intro_style = {}
        for key in DEFAULT_STYLE["intro"]:
            if key in intro:
                intro_style[key] = intro.pop(key)
        if intro_style:
            legacy_style["intro"] = intro_style

    style_source = merge_style(legacy_style, style_values or {})
    return project, resolve_style(style_source)


def clean_project_values(project_values):
    """Remove visual keys from project.json while preserving all other values."""
    project, _style = split_style_from_project(project_values)
    return project
