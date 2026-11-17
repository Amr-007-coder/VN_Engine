from copy import deepcopy
import os
import re
from pathlib import Path, PurePosixPath

from engine.loader import PATHS, loader
from engine.theme import MENU_SCREEN_NAMES, resolve_theme, validate_menu_grid


DEFAULT_PROJECT = {
    "name": "Visual Novel",
    "story": "story.yaml",
    "icon": None,
    "android": {
        "app_name": "VN Engine",
        "app_id": "com.example.vnengine",
        "orientation": "landscape",
    },
    "save_slots": 5,
    "credits": [],
    "intro": {
        "creator": "Marpp",
        "game_version": None,
        "warning_message": "",
        "credit_image": None,
        "warning_image": "content_warning.png",
        "headphones_image": "headphones.png",
    },
    "messages": {
        "unknown_menu_action": "Unknown menu action: {action}",
        "no_continue_save": "There is no save to continue from.",
        "no_active_game": "There is no active game to save.",
        "save_success": "Saved the game in slot {slot}.",
        "save_error": "Failed to save: {error}",
        "slot_empty": "Slot {slot} is empty.",
        "different_story": "This save belongs to a different story.",
        "load_error": "Failed to load: {error}",
        "delete_success": "Deleted the save in slot {slot}.",
        "delete_empty": "Slot {slot} is already empty.",
        "delete_error": "Failed to delete: {error}",
    },
    "paths": {"data": "data", "assets": "assets", "user_data": "user_data"},
    "window": {"width": 1920, "height": 1200, "caption": "VN Engine"},
    "theme": {
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
        "game_fonts": {
            "text": "standard.ttf",
            "name": "standard.ttf",
            "button": "standard.ttf",
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
            "right_margin": 48,
            "screens": {
                "main": {
                    "background": None,
                    "alignment": None,
                    "top": None,
                    "row_gap": None,
                    "button_width": None,
                    "button_height": None,
                    "grid": None,
                    "buttons": {"normal": None, "hovered": None},
                },
                "pause": {
                    "background": None,
                    "alignment": None,
                    "top": None,
                    "row_gap": None,
                    "button_width": None,
                    "button_height": None,
                    "grid": None,
                    "buttons": {"normal": None, "hovered": None},
                },
                "settings": {
                    "background": None,
                    "alignment": None,
                    "top": None,
                    "row_gap": None,
                    "button_width": None,
                    "button_height": None,
                    "grid": None,
                    "buttons": {"normal": None, "hovered": None},
                },
                "slots": {
                    "background": None,
                    "alignment": None,
                    "top": None,
                    "row_gap": None,
                    "button_width": None,
                    "button_height": None,
                    "grid": None,
                    "buttons": {"normal": None, "hovered": None},
                },
                "credits": {
                    "background": None,
                    "alignment": None,
                    "top": None,
                    "row_gap": None,
                    "button_width": None,
                    "button_height": None,
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
        "pause_button": {"image": None, "size": 78, "margin": 16},
        "sounds": {
            "hover": "sounds/hover_button.wav",
            "click": "sounds/click_button.wav",
            "cancel": "sounds/click_button.wav",
            "load": "sounds/click_button.wav",
        },
    },
    "menus": {
        "main": {
            "title": "Visual Novel",
            "items": [
                {"label": "New Game", "action": "new_game"},
                {"label": "Continue", "action": "continue_game"},
                {"label": "Load Game", "action": "open_load_slots"},
                {"label": "Settings", "action": "open_settings"},
                {"label": "Credits", "action": "open_credits"},
                {"label": "Quit", "action": "quit"},
            ],
        },
        "pause": {
            "title": "Paused",
            "items": [
                {"label": "Resume", "action": "resume"},
                {"label": "Save Game", "action": "open_save_slots"},
                {"label": "Load Game", "action": "open_load_slots"},
                {"label": "Settings", "action": "open_settings"},
                {"label": "Main Menu", "action": "return_to_main_menu"},
            ],
        },
        "settings": {
            "title": "Settings",
            "items": [
                {"label": "Text Speed", "action": "adjust_setting", "setting": "type_speed"},
                {"label": "Music Volume", "action": "adjust_setting", "setting": "music_volume"},
                {"label": "Sound Effects Volume", "action": "adjust_setting", "setting": "sfx_volume"},
                {"label": "UI Size", "action": "adjust_setting", "setting": "ui_scale"},
                {"label": "Display Mode", "action": "toggle_setting", "setting": "fullscreen"},
                {"label": "Back", "action": "back"},
            ],
        },
        "slots": {
            "title_save": "Save Game",
            "title_load": "Load Game",
            "labels": {
                "slot": "Slot {slot}",
                "saved": "Slot {slot}: {chapter}",
                "empty": "Empty",
                "corrupt": "Corrupted Save",
                "unknown_chapter": "Unknown Chapter",
                "unknown_time": "Unknown Time",
            },
            "delete": {"label": "Delete Selected Slot", "action": "delete_selected_slot"},
            "back": {"label": "Back", "action": "back"},
        },
    },
}


class ProjectConfig:
    def __init__(self, values: dict | None = None):
        values = values or {}
        self.values = _merge_dicts(DEFAULT_PROJECT, values)
        self._validate()
        self.name = self.values["name"]
        project_root = PATHS.project
        self.data_dir = self._resolve_project_path(self.values["paths"].get("data", "data"), project_root)
        assets_path = self.values["paths"].get("assets", "assets")
        self.assets_dir = self._resolve_project_path(assets_path, project_root)
        if assets_path == "assets" and not self.assets_dir.is_dir() and PATHS.project_assets.is_dir():
            self.assets_dir = PATHS.project_assets
        user_data_override = os.environ.get("VN_ENGINE_USER_DATA_DIR")
        if user_data_override:
            self.user_data_dir = Path(user_data_override).expanduser().resolve()
        else:
            user_data_root = PATHS.user_data_root
            if PATHS.use_local_app_data:
                project_folder = re.sub(r"[^A-Za-z0-9_-]+", "-", self.name).strip("-_")
                user_data_root = user_data_root / (project_folder or "visual-novel")
            self.user_data_dir = self._resolve_project_path(
                self.values["paths"].get("user_data", "user_data"),
                user_data_root,
            )

        self.story_file = self.values["story"]
        icon = self.values["icon"]
        self.icon = PurePosixPath(icon.replace("\\", "/")).as_posix() if icon else None
        self.window = self.values["window"]
        self.menus = self.values["menus"]
        self.theme = self.values.get("theme", {})

    @classmethod
    def load(cls, config_file: str = "project.json"):
        path = PATHS.project_data / config_file
        if not loader.project_file_exists(config_file, PATHS.project_data):
            return cls()
        values = loader.load_project_json(config_file)
        if not isinstance(values, dict):
            raise ValueError(f"Project config {path} must contain a JSON object.")
        return cls(values)

    def load_story(self, story_file: str | None = None):
        filename = story_file or self.story_file
        return loader.load_project_yaml(filename, self.data_dir)

    def _validate(self):
        values = self.values
        if not isinstance(values.get("name"), str) or not isinstance(values.get("story"), str):
            raise ValueError("Project config needs string values for 'name' and 'story'.")
        icon = values.get("icon")
        if icon is not None:
            icon_path = PurePosixPath(icon.replace("\\", "/")) if isinstance(icon, str) else None
            if (
                icon_path is None
                or not icon.strip()
                or icon_path.is_absolute()
                or re.match(r"^[A-Za-z]:", icon) is not None
                or ".." in icon_path.parts
                or icon_path.suffix.casefold() != ".png"
            ):
                raise ValueError("Project config 'icon' must be a relative PNG path inside the project's assets folder or null.")
        android = values.get("android")
        if not isinstance(android, dict):
            raise ValueError("Project config 'android' must be an object.")
        if not isinstance(android.get("app_name"), str) or not android["app_name"].strip():
            raise ValueError("Project config 'android.app_name' must be a non-empty string.")
        app_id = android.get("app_id")
        if not isinstance(app_id, str) or re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", app_id) is None:
            raise ValueError("Project config 'android.app_id' must be a lowercase reverse-DNS identifier.")
        orientation = android.get("orientation")
        if not isinstance(orientation, str) or orientation not in {"landscape", "portrait"}:
            raise ValueError("Project config 'android.orientation' must be 'landscape' or 'portrait'.")
        intro = values.get("intro")
        if (
            not isinstance(intro, dict)
            or not isinstance(intro.get("creator"), str)
            or not isinstance(intro.get("warning_message", ""), str)
            or (intro.get("game_version") is not None and not isinstance(intro["game_version"], str))
            or any(intro.get(key) is not None and not isinstance(intro[key], str)
                   for key in ("credit_image", "warning_image", "headphones_image"))
        ):
            raise ValueError("Project config 'intro' needs creator, version, warning_message, and optional image paths.")
        if (
            not isinstance(values.get("save_slots"), int)
            or isinstance(values.get("save_slots"), bool)
            or values["save_slots"] < 1
        ):
            raise ValueError("Project config 'save_slots' must be a positive integer.")
        paths = values.get("paths")
        if not isinstance(paths, dict) or any(
            not isinstance(paths.get(key), str) for key in ("data", "assets", "user_data")
        ):
            raise ValueError("Project config paths must define string values for data, assets, and user_data.")
        window = values.get("window")
        if not isinstance(window, dict):
            raise ValueError("Project config 'window' must be an object.")
        if any(
            not isinstance(window.get(key), int)
            or isinstance(window.get(key), bool)
            or window[key] <= 0
            for key in ("width", "height")
        ):
            raise ValueError("Project window width and height must be positive integers.")
        if not isinstance(window.get("caption"), str):
            raise ValueError("Project window caption must be a string.")

        menus = values.get("menus")
        if not isinstance(menus, dict):
            raise ValueError("Project config 'menus' must be an object.")
        allowed_actions = {
            "new_game", "continue_game", "open_load_slots", "open_save_slots",
            "open_settings", "open_credits", "quit", "resume", "return_to_main_menu", "back",
            "adjust_setting", "toggle_setting", "save_slot", "load_slot",
            "delete_selected_slot",
        }
        for menu_name in ("main", "pause", "settings"):
            menu = menus.get(menu_name)
            if not isinstance(menu, dict) or not isinstance(menu.get("title"), str):
                raise ValueError(f"Project menu {menu_name!r} needs a string title.")
            items = menu.get("items")
            if not isinstance(items, list):
                raise ValueError(f"Project menu {menu_name!r} items must be a list.")
            for index, item in enumerate(items):
                if not isinstance(item, dict) or not isinstance(item.get("label"), str):
                    raise ValueError(f"Project menu {menu_name!r} item {index} needs a string label.")
                action = item.get("action")
                if not isinstance(action, str) or action not in allowed_actions:
                    raise ValueError(f"Project menu {menu_name!r} item {index} has an unknown action ID.")
                if action in {"adjust_setting", "toggle_setting"}:
                    setting = item.get("setting")
                    if not isinstance(setting, str) or setting not in {"type_speed", "music_volume", "sfx_volume", "fullscreen", "ui_scale"}:
                        raise ValueError(f"Project menu {menu_name!r} item {index} has an unknown setting ID.")

        slot_menu = menus.get("slots")
        if not isinstance(slot_menu, dict):
            raise ValueError("Project config 'menus.slots' must be an object.")
        for key in ("title_save", "title_load"):
            if not isinstance(slot_menu.get(key), str):
                raise ValueError(f"Project config menus.slots.{key} must be a string.")
        labels = slot_menu.get("labels")
        if not isinstance(labels, dict) or any(
            not isinstance(labels.get(key), str)
            for key in ("slot", "saved", "empty", "corrupt", "unknown_chapter", "unknown_time")
        ):
            raise ValueError("Project config menus.slots.labels must define string labels for slot states.")
        try:
            labels["slot"].format(slot=1)
            labels["saved"].format(slot=1, chapter="", dialogue="")
        except (IndexError, KeyError, ValueError) as error:
            raise ValueError(f"Project slot labels have an invalid format placeholder: {error}.") from error
        for key in ("delete", "back"):
            item = slot_menu.get(key)
            if not isinstance(item, dict) or not isinstance(item.get("label"), str):
                raise ValueError(f"Project config menus.slots.{key} needs a label and action.")
            action = item.get("action")
            if not isinstance(action, str) or action not in allowed_actions:
                raise ValueError(f"Project config menus.slots.{key} has an unknown action ID.")
            required_action = "delete_selected_slot" if key == "delete" else "back"
            if action != required_action:
                raise ValueError(f"Project config menus.slots.{key} must use action {required_action!r}.")
        if not isinstance(values.get("theme"), dict):
            raise ValueError("Project config 'theme' must be an object.")
        raw_theme = values["theme"]
        raw_textbox_theme = raw_theme.get("textbox", {})
        if not isinstance(raw_textbox_theme, dict):
            raise ValueError("Project theme 'textbox' must be an object.")
        theme = resolve_theme(raw_theme)
        textbox_theme = theme["textbox"]
        textbox_image = textbox_theme.get("background")
        if textbox_image is not None and not isinstance(textbox_image, str):
            raise ValueError("Project theme 'textbox.background' must be an image path or null.")
        textbox_color = textbox_theme.get("color")
        if textbox_color is not None and (
            not isinstance(textbox_color, list)
            or len(textbox_color) not in {3, 4}
            or any(not isinstance(channel, int) or isinstance(channel, bool) or not 0 <= channel <= 255
                   for channel in textbox_color)
        ):
            raise ValueError("Project theme 'textbox.color' must be an RGB or RGBA array of values from 0 to 255.")
        for key in ("x", "bottom", "width", "height", "opacity"):
            value = textbox_theme[key]
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0 <= value <= 1
                or (key in {"width", "height"} and value == 0)
            ):
                raise ValueError(f"Project theme 'textbox.{key}' must be a fraction from 0 to 1.")
        if (
            textbox_theme["x"] + textbox_theme["width"] > 1
            or textbox_theme["bottom"] + textbox_theme["height"] > 1
        ):
            raise ValueError("Project theme textbox geometry must fit within the window.")

        menu_theme = raw_theme.get("menu", {})
        if not isinstance(menu_theme, dict):
            raise ValueError("Project theme 'menu' must be an object.")
        screens = menu_theme.get("screens", {})
        if not isinstance(screens, dict):
            raise ValueError("Project theme 'menu.screens' must be an object.")
        menu_item_counts = {
            "main": len(menus["main"]["items"]),
            "pause": len(menus["pause"]["items"]),
            "settings": len(menus["settings"]["items"])
            + (0 if any(item.get("setting") == "ui_scale" for item in menus["settings"]["items"]) else 1),
            "slots": values["save_slots"],
        }
        for screen_name, screen_theme in screens.items():
            if screen_name not in MENU_SCREEN_NAMES:
                raise ValueError(f"Project theme has unknown menu screen {screen_name!r}.")
            if not isinstance(screen_theme, dict):
                raise ValueError(f"Project theme 'menu.screens.{screen_name}' must be an object.")
            alignment = screen_theme.get("alignment")
            if alignment is not None and (
                not isinstance(alignment, str)
                or alignment not in {"centered", "left", "right"}
            ):
                raise ValueError(
                    f"Project theme 'menu.screens.{screen_name}.alignment' must be centered, left, or right."
                )
            for key in ("top", "row_gap", "button_width", "button_height"):
                value = screen_theme.get(key)
                if value is not None and (
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value < (0 if key in {"top", "row_gap"} else 1)
                ):
                    raise ValueError(
                        f"Project theme 'menu.screens.{screen_name}.{key}' must be a "
                        f"{'non-negative' if key in {'top', 'row_gap'} else 'positive'} integer."
                    )
            background = screen_theme.get("background")
            if background is not None and not isinstance(background, str):
                raise ValueError(
                    f"Project theme 'menu.screens.{screen_name}.background' must be an image path or null."
                )
            buttons = screen_theme.get("buttons", {})
            if not isinstance(buttons, dict):
                raise ValueError(f"Project theme 'menu.screens.{screen_name}.buttons' must be an object.")
            for state in ("normal", "hovered"):
                path = buttons.get(state)
                if path is not None and (
                    not isinstance(path, str) or Path(path).suffix.casefold() != ".png"
                ):
                    raise ValueError(
                        f"Project theme 'menu.screens.{screen_name}.buttons.{state}' must be a PNG path or null."
                    )
            grid = screen_theme.get("grid")
            if grid is not None:
                if screen_name == "credits":
                    raise ValueError("The Credits screen is a scrolling list and does not support a button grid.")
                try:
                    validate_menu_grid(grid, menu_item_counts[screen_name])
                except ValueError as error:
                    raise ValueError(f"Project theme 'menu.screens.{screen_name}.grid': {error}") from error

        choice_theme = raw_theme.get("choice_buttons", {})
        if not isinstance(choice_theme, dict):
            raise ValueError("Project theme 'choice_buttons' must be an object.")
        for state in ("normal", "hovered"):
            path = choice_theme.get(state)
            if path is not None and (
                not isinstance(path, str) or Path(path).suffix.casefold() != ".png"
            ):
                raise ValueError(f"Project theme 'choice_buttons.{state}' must be a PNG path or null.")
        for key in ("width", "height"):
            value = choice_theme.get(key, theme["choice_buttons"][key])
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"Project theme 'choice_buttons.{key}' must be a positive integer.")
        gap = choice_theme.get("gap", theme["choice_buttons"]["gap"])
        if not isinstance(gap, int) or isinstance(gap, bool) or gap < 0:
            raise ValueError("Project theme 'choice_buttons.gap' must be a non-negative integer.")

        pause_theme = raw_theme.get("pause_button", {})
        if not isinstance(pause_theme, dict):
            raise ValueError("Project theme 'pause_button' must be an object.")
        pause_image = pause_theme.get("image")
        if pause_image is not None and (
            not isinstance(pause_image, str) or Path(pause_image).suffix.casefold() != ".png"
        ):
            raise ValueError("Project theme 'pause_button.image' must be a PNG path or null.")
        pause_size = pause_theme.get("size", theme["pause_button"]["size"])
        pause_margin = pause_theme.get("margin", theme["pause_button"]["margin"])
        if not isinstance(pause_size, int) or isinstance(pause_size, bool) or pause_size < 1:
            raise ValueError("Project theme 'pause_button.size' must be a positive integer.")
        if not isinstance(pause_margin, int) or isinstance(pause_margin, bool) or pause_margin < 0:
            raise ValueError("Project theme 'pause_button.margin' must be a non-negative integer.")
        credits = values.get("credits")
        if not isinstance(credits, list):
            raise ValueError("Project config 'credits' must be a list.")
        for credit in credits:
            if isinstance(credit, str):
                continue
            if not isinstance(credit, dict) or not isinstance(credit.get("label"), str):
                raise ValueError("Each project credit must be a string or an object with a label.")
            url = credit.get("url")
            if url is not None and (
                not isinstance(url, str)
                or not url.startswith(("https://", "http://"))
            ):
                raise ValueError("Credit links must use http:// or https:// URLs.")
        messages = values.get("messages")
        if not isinstance(messages, dict) or any(not isinstance(message, str) for message in messages.values()):
            raise ValueError("Project config 'messages' must map message IDs to strings.")
        message_arguments = {
            "unknown_menu_action": {"action": "action"},
            "no_continue_save": {},
            "no_active_game": {},
            "save_success": {"slot": 1},
            "save_error": {"error": "error"},
            "slot_empty": {"slot": 1},
            "different_story": {},
            "load_error": {"error": "error"},
            "delete_success": {"slot": 1},
            "delete_empty": {"slot": 1},
            "delete_error": {"error": "error"},
        }
        for message_id, arguments in message_arguments.items():
            try:
                messages[message_id].format(**arguments)
            except (IndexError, KeyError, ValueError) as error:
                raise ValueError(f"Project message {message_id!r} has an invalid format placeholder: {error}.") from error

    @staticmethod
    def _resolve_project_path(path: str, project_root: Path):
        candidate = Path(path)
        return candidate if candidate.is_absolute() else (project_root / candidate).resolve()


def _merge_dicts(defaults: dict, overrides: dict) -> dict:
    result = deepcopy(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result
