from engine.assets import AssetManager
from engine.ui_scale import ui_size


class FONTS:
    normal_text = None
    char_name = None
    button_text = None


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
    FONTS.normal_text = asset_manager.load_font(game_fonts.get("text", "standard.ttf"), ui_size(24))
    FONTS.char_name = asset_manager.load_font(game_fonts.get("name", "standard.ttf"), ui_size(28))
    FONTS.button_text = asset_manager.load_font(game_fonts.get("button", "standard.ttf"), ui_size(20))
