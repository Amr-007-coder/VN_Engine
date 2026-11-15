from copy import deepcopy
import os
import re
from pathlib import Path, PurePosixPath

from engine.loader import PATHS, loader


DEFAULT_PROJECT = {
    "name": "Visual Novel",
    "story": "story.yaml",
    "icon": None,
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
    "theme": {
        "textbox": {"background": None, "color": None},
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
                    if not isinstance(setting, str) or setting not in {"type_speed", "music_volume", "sfx_volume", "fullscreen"}:
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
        textbox_theme = values["theme"].get("textbox", {})
        if not isinstance(textbox_theme, dict):
            raise ValueError("Project theme 'textbox' must be an object.")
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
