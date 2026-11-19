from engine.assets import AssetManager
from engine.ui_scale import ui_size


class FONTS:
    normal_text = None
    char_name = None
    button_text = None
    dialogue_controls = None


class IMAGES:
    cat = None


class SOUNDS:
    error = None


class COLORS:
    blank = (0, 0, 0, 0)
    text = (230, 230, 230)
    text_highlight = (233, 79, 88)
    panel = (0, 0, 0, 128)
    background = (30, 30, 45)


class CHAR_PARS:
    @classmethod
    def values(cls) -> set[str]:
        all_chars = set()
        for attr in cls.__dict__.values():
            if isinstance(attr, type):
                if hasattr(attr, "start"):
                    all_chars.add(attr.start)
                if hasattr(attr, "end"):
                    all_chars.add(attr.end)
        return all_chars

    class value:
        start = "{"
        end = "}"

    class bold:
        start = "*"
        end = "*"

    class italic:
        start = "_"
        end = "_"

    class highlight:
        start = "#"
        end = "#"

    class strike:
        start = "~"
        end = "~"

    class set_image:
        start = "%"
        end = "%"

    class play_sound:
        start = "\u00a7"
        end = "\u00a7"


def load_assets(asset_manager: AssetManager, theme=None):
    """Load the dialogue UI's fonts and default assets after pygame startup."""
    theme = theme or {}
    colors = theme.get("colors", {})
    COLORS.background = tuple(colors.get("background", COLORS.background))
    COLORS.text = tuple(colors.get("text", COLORS.text))
    COLORS.text_highlight = tuple(colors.get("accent", COLORS.text_highlight))
    COLORS.panel = tuple(colors.get("panel", COLORS.panel))

    game_fonts = theme.get("game_fonts", {})
    font_sizes = theme.get("game_font_sizes", {})
    button_font = game_fonts.get("button", "standard.ttf")
    FONTS.normal_text = asset_manager.load_font(
        game_fonts.get("text", "standard.ttf"),
        ui_size(font_sizes.get("text", 24)),
    )
    FONTS.char_name = asset_manager.load_font(
        game_fonts.get("name", "standard.ttf"),
        ui_size(font_sizes.get("name", 28)),
    )
    FONTS.button_text = asset_manager.load_font(
        button_font,
        ui_size(font_sizes.get("button", 20)),
    )
    FONTS.dialogue_controls = asset_manager.load_font(
        button_font,
        ui_size(font_sizes.get("dialogue_controls", 16)),
    )


def load_ui_fonts(asset_manager: AssetManager, theme=None, style=None, preferences=None):
    """Load component fonts used by both the game and the off-screen editor preview."""
    theme = theme or {}
    style = style if isinstance(style, dict) else {}
    preferences = preferences if isinstance(preferences, dict) else {}
    game_fonts = theme.get("game_fonts", {})
    sizes = theme.get("game_font_sizes", {})
    components = style.get("components", {})
    dialogue_style = components.get("dialogue_text", {}) if isinstance(components, dict) else {}
    text_style = dialogue_style.get("text", {}) if isinstance(dialogue_style, dict) else {}
    speaker_style = dialogue_style.get("speaker", {}) if isinstance(dialogue_style, dict) else {}
    choices_style = components.get("choices", {}) if isinstance(components, dict) else {}
    controls_style = components.get("dialogue_controls", {}) if isinstance(components, dict) else {}
    for global_name, setting, theme_key, component in (
        ("normal_text", "dialogue_font_scale", "text", text_style),
        ("char_name", "speaker_font_scale", "name", speaker_style),
        ("button_text", None, "button", choices_style),
        ("dialogue_controls", None, "dialogue_controls", controls_style),
    ):
        defaults = {"text": 24, "name": 28, "button": 20, "dialogue_controls": 16}
        size = component.get("font_size", sizes.get(theme_key, defaults[theme_key]))
        scale = float(preferences.get(setting, 1.0)) if setting else 1.0
        family = component.get("font", game_fonts.get(theme_key, "standard.ttf"))
        setattr(FONTS, global_name, asset_manager.load_font(family, max(1, ui_size(float(size) * scale))))
    return FONTS
