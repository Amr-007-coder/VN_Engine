"""Standalone PySide6 authoring editor for VN Engine projects.

Run ``python editor.py`` from a project folder, or pass ``--project-dir``.
Without a project folder, the editor installs a starter project in Documents.
"""

from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from dataclasses import dataclass
from difflib import get_close_matches
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import editor_qt as tk
from editor_qt import filedialog, messagebox, simpledialog, ttk
from typing import Any
from zipfile import BadZipFile, ZipFile

from engine.style import (
    DEFAULT_STYLE as ENGINE_DEFAULT_STYLE,
    clean_project_values,
    merge_style,
    resolve_style,
    split_style_from_project,
)
from engine.mods import build_asset_package
from engine.localization import catalog_report, load_catalog, translation_template, write_catalog
from engine.ui_text import UI_LABEL_KEYS

try:
    import yaml
except ImportError:
    yaml = None


APP_TITLE = "VN Engine Editor"
STORY_TOP_KEYS = {"title", "start", "includes", "variables", "character_defaults", "localization", "dialogues"}
DIALOGUE_KEYS = {
    "chapter", "speaker", "speaker_name", "text", "next", "call", "return", "options", "actions", "active_character", "voice",
    "choice_timeout", "choice_timeout_target",
}
OPTION_KEYS = {"label", "target", "condition"}
CONDITION_KEYS = {"var", "op", "value", "all", "any", "not"}
ACTION_TYPES = {
    "set", "add", "subtract", "background", "clear_background", "music", "stop_music",
    "sound", "show_character", "animate_character", "hide_character", "clear_characters", "fade", "shake", "autosave",
    "input", "unlock_cg", "unlock_music", "achievement", "complete_route",
}
ACTION_FIELDS = {
    "set": {"type", "var", "value"},
    "add": {"type", "var", "value"},
    "subtract": {"type", "var", "value"},
    "input": {"type", "var", "prompt", "input_type"},
    "background": {"type", "image"},
    "clear_background": {"type"},
    "music": {"type", "track"},
    "stop_music": {"type"},
    "sound": {"type", "name"},
    "show_character": {"type", "name", "look", "expression", "position", "transition", "duration", "easing"},
    "animate_character": {"type", "name", "frames", "look", "position", "frame_duration", "loop"},
    "hide_character": {"type", "name", "transition", "duration", "easing"},
    "clear_characters": {"type"},
    "fade": {"type", "direction", "duration", "color"},
    "shake": {"type", "duration", "intensity"},
    "autosave": {"type"},
    "unlock_cg": {"type", "id", "image", "label"},
    "unlock_music": {"type", "id", "track", "label"},
    "achievement": {"type", "id", "title", "description"},
    "complete_route": {"type", "id", "title"},
}
REQUIRED_ACTION_FIELDS = {
    "set": {"var", "value"},
    "add": {"var", "value"},
    "subtract": {"var", "value"},
    "input": {"var", "prompt"},
    "background": {"image"},
    "music": {"track"},
    "sound": {"name"},
    "show_character": {"name", "expression"},
    "animate_character": {"name", "frames"},
    "hide_character": {"name"},
    "fade": {"direction"},
    "unlock_cg": {"id", "image"},
    "unlock_music": {"id", "track"},
    "achievement": {"id"},
    "complete_route": {"id"},
}
CONDITION_OPERATORS = {"==", "!=", "<", "<=", ">", ">=", "in", "not_in"}
CHARACTER_POSITIONS = {"far_left", "left", "center", "right", "far_right"}
MENU_ACTIONS = {
    "new_game", "continue_game", "open_load_slots", "open_save_slots", "open_settings",
    "open_credits", "quit", "resume", "return_to_main_menu", "back", "adjust_setting",
    "toggle_setting", "save_slot", "load_slot", "delete_selected_slot", "open_extras",
}
SETTING_NAMES = {"type_speed", "music_volume", "sfx_volume", "fullscreen", "ui_scale"}
SETTING_NAMES = SETTING_NAMES | {
    "auto_advance", "auto_wait", "dialogue_font_scale", "speaker_font_scale",
    "high_contrast", "muted", "reduced_motion", "voice_enabled",
    "subtitles_enabled", "animated_text", "touch_advance_mode", "locale", "speech_enabled",
}
BUILTIN_ASSETS = {
    "image": {"logo.png", "content_warning.png", "headphones.png", "test.png"},
    "sound": {"intro.wav", "hover_button.wav", "click_button.wav"},
    "music": set(),
    "font": {
        "standard.ttf", "Joystix.ttf", "MS Gothic.ttf", "PermanentMarker.ttf",
        "rpg-maker-2k.ttf", "Toriko.ttf", "VCR_OSD_Mono.ttf",
    },
}
ASSET_FOLDER = {"image": "images", "sound": "sounds", "music": "music", "font": "fonts"}
EDITOR_DOCUMENTS = (
    Path("docs/guide_vn-engine.md"),
    Path("docs/project-config.md"),
    Path("docs/story-format.md"),
)


def _literal_from_engine(relative_file: str, variable: str):
    """Read the engine's literal defaults without importing pygame or the engine."""
    source = Path(__file__).resolve().parent / relative_file
    if not source.is_file():
        return None
    try:
        module = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in module.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == variable for target in node.targets
            ):
                return ast.literal_eval(node.value)
    except (OSError, SyntaxError, ValueError):
        return None
    return None


FALLBACK_DEFAULT_PROJECT = {
    "USER": "user",
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
        "creator": "Marpp", "game_version": None, "warning_message": "",
        "credit_image": None, "warning_image": "content_warning.png",
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
    "dialogue_buttons": {
        "back": {"visible": True, "label": "Back", "label_alignment": "center"},
        "history": {"visible": True, "label": "History", "label_alignment": "center"},
        "quick_save": {"visible": True, "label": "Q. Save", "label_alignment": "center"},
        "quick_load": {"visible": True, "label": "Q. Load", "label_alignment": "center"},
        "auto": {"visible": True, "label": "Auto", "label_alignment": "center"},
        "mute": {"visible": True, "label": "Mute", "label_alignment": "center"},
    },
    "menus": {
        "main": {"title": "Visual Novel", "items": [
            {"label": "New Game", "action": "new_game"},
            {"label": "Continue", "action": "continue_game"},
            {"label": "Load Game", "action": "open_load_slots"},
            {"label": "Settings", "action": "open_settings"},
            {"label": "Credits", "action": "open_credits"},
            {"label": "Extras", "action": "open_extras"},
            {"label": "Quit", "action": "quit"},
        ]},
        "pause": {"title": "Paused", "items": [
            {"label": "Resume", "action": "resume"},
            {"label": "Save Game", "action": "open_save_slots"},
            {"label": "Load Game", "action": "open_load_slots"},
            {"label": "Settings", "action": "open_settings"},
            {"label": "Extras", "action": "open_extras"},
            {"label": "Main Menu", "action": "return_to_main_menu"},
        ]},
        "settings": {"title": "Settings", "items": [
            {"label": "Text Speed", "action": "adjust_setting", "setting": "type_speed"},
            {"label": "Music Volume", "action": "adjust_setting", "setting": "music_volume"},
            {"label": "Sound Effects Volume", "action": "adjust_setting", "setting": "sfx_volume"},
            {"label": "UI Size", "action": "adjust_setting", "setting": "ui_scale"},
            {"label": "Display Mode", "action": "toggle_setting", "setting": "fullscreen"},
            {"label": "Back", "action": "back"},
        ]},
        "slots": {
            "title_save": "Save Game", "title_load": "Load Game",
            "labels": {"slot": "Slot {slot}", "saved": "Slot {slot}: {chapter}",
                       "empty": "Empty", "corrupt": "Corrupted Save",
                       "unknown_chapter": "Unknown Chapter", "unknown_time": "Unknown Time"},
            "delete": {"label": "Delete Selected Slot", "action": "delete_selected_slot"},
            "back": {"label": "Back", "action": "back"},
        },
    },
    "characters": {},
    "theme": {},
}
LEGACY_DEFAULT_PROJECT = _literal_from_engine("engine/project.py", "DEFAULT_PROJECT") or FALLBACK_DEFAULT_PROJECT
LEGACY_DEFAULT_PROJECT.setdefault("android", dict(FALLBACK_DEFAULT_PROJECT["android"]))
DEFAULT_THEME = _literal_from_engine("engine/theme.py", "DEFAULT_THEME") or {
    "colors": {"background": [30, 30, 45], "text": [230, 230, 230], "muted": [170, 170, 180],
               "normal": [18, 18, 29], "hover": [73, 50, 65],
               "selected": [45, 92, 78], "border": [112, 86, 101],
               "accent": [233, 79, 88], "panel": [0, 0, 0, 128]},
    "fonts": {"menu": None, "title": None, "item_size": 20,
              "detail_size": 16, "title_size": 30},
    "game_fonts": {
        "text": "standard.ttf", "name": "standard.ttf",
        "button": "standard.ttf", "intro": "standard.ttf",
    },
    "game_font_sizes": {
        "text": 24, "name": 28, "button": 20, "dialogue_controls": 12,
        "intro": 40, "intro_small": 21,
    },
    "menu": {
        "layout": "centered", "background": None, "width": 860,
        "label_alignment": "left",
        "x": None, "row_height": 56, "row_gap": 9, "title_y": 112,
        "top": 190, "border_radius": 8,
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
        "background": None, "color": None, "x": 0.02, "bottom": 0.0,
        "width": 0.96, "height": 0.21, "opacity": 0.95,
    },
    "choice_buttons": {
        "normal": None, "hovered": None, "width": 900, "height": 56, "gap": 12,
    },
    "pause_button": {"image": None, "size": 78, "margin": 16},
    "sounds": {"hover": "sounds/hover_button.wav", "click": "sounds/click_button.wav",
               "cancel": "sounds/click_button.wav", "load": "sounds/click_button.wav"},
}
DEFAULT_THEME.setdefault("game_fonts", {
    "text": None, "name": None, "button": None, "intro": None,
})
DEFAULT_THEME.setdefault("game_font_sizes", {
    "text": 24, "name": 28, "button": 20, "dialogue_controls": 12,
    "intro": 40, "intro_small": 21,
})
DEFAULT_THEME.setdefault("menu", {}).setdefault("right_margin", 48)
DEFAULT_THEME.setdefault("textbox", {"background": None, "color": None})


def merge_defaults(defaults: Any, overrides: Any):
    if isinstance(defaults, dict) and isinstance(overrides, dict):
        result = dict(defaults)
        for key, value in overrides.items():
            result[key] = merge_defaults(result[key], value) if key in result else value
        return result
    return overrides


DEFAULT_PROJECT = clean_project_values(LEGACY_DEFAULT_PROJECT)
DEFAULT_RUNTIME_PROJECT = merge_defaults(DEFAULT_PROJECT, LEGACY_DEFAULT_PROJECT)
DEFAULT_STYLE = merge_defaults(
    ENGINE_DEFAULT_STYLE,
    split_style_from_project(LEGACY_DEFAULT_PROJECT)[1],
)


def _starter_story_content() -> str:
    return (
        "title: My Visual Novel\n"
        "start: opening\n\n"
        "dialogues:\n"
        "  opening:\n"
        "    chapter: Chapter 1\n"
        "    speaker: Narrator\n"
        "    active_character: null\n"
        "    text: Replace this line with your opening dialogue.\n"
    )


def _write_text_if_missing(path: Path, contents: str) -> None:
    if path.exists():
        if path.is_file():
            return
        raise IsADirectoryError(f"Expected a file, found a directory: {path}")
    try:
        with path.open("x", encoding="utf-8", newline="\n") as output:
            output.write(contents)
    except FileExistsError:
        if path.is_file():
            return
        raise


def _ensure_project_structure(project_root: Path) -> None:
    project_root = Path(project_root)
    for relative in (
        "assets/fonts",
        "assets/images",
        "assets/sounds",
        "assets/characters",
        "data",
    ):
        (project_root / relative).mkdir(parents=True, exist_ok=True)

    starter_files = (
        (
            project_root / "data" / "project.json",
            json.dumps(DEFAULT_PROJECT, ensure_ascii=False, indent=2) + "\n",
        ),
        (
            project_root / "data" / "style.json",
            json.dumps(DEFAULT_STYLE, ensure_ascii=False, indent=2) + "\n",
        ),
        (project_root / "data" / "story.yaml", _starter_story_content()),
    )
    for path, contents in starter_files:
        _write_text_if_missing(path, contents)


def editor_index(start: str, offset: int) -> str:
    return f"{start}+{offset}c"


def project_root_from(path: Path) -> Path:
    path = path.resolve()
    if path.is_file():
        path = path.parent
    for candidate in (path, *path.parents):
        if _contains_project(candidate):
            return candidate
    return path


def _contains_project(root: Path) -> bool:
    return (
        (root / "data" / "project.json").is_file()
        or (root / "data" / "story.yaml").is_file()
    )


def editor_package_root(path: Path) -> Path:
    """Return the folder beside the editor app bundle or executable."""
    path = Path(path).resolve()
    if path.is_file():
        path = path.parent
    for candidate in (path, *path.parents):
        if candidate.suffix.casefold() == ".app":
            return candidate.parent
    return path


def _is_standalone_editor_package(root: Path) -> bool:
    return (
        (root / "VN_Editor.exe").is_file()
        or (root / "VN_Editor").is_file()
        or (root / "VN_Editor.app" / "Contents" / "MacOS" / "VN_Editor").is_file()
    )


def _starter_project_directory() -> Path:
    return Path.home() / "Documents" / "VN Engine Projects" / "My Visual Novel"


def _editor_markdown_paths(editor_home: Path) -> list[Path]:
    readme = editor_home / "readme.md"
    if not readme.is_file():
        readme = editor_home / "docs" / "README.md"
    paths = [readme] if readme.is_file() else []
    paths.extend(editor_home / relative_path for relative_path in EDITOR_DOCUMENTS)
    return [path.resolve() for path in paths if path.is_file()]


def _editor_settings_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "VN_Engine" / "editor.json"


def _load_last_project() -> Path | None:
    settings_path = _editor_settings_path()
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as error:
        raise ValueError(f"Could not read editor settings from {settings_path}: {error}") from error
    if not isinstance(settings, dict) or not isinstance(settings.get("last_project"), str):
        raise ValueError(f"Editor settings do not contain a valid last project path: {settings_path}")
    project = Path(settings["last_project"]).expanduser()
    return project.resolve() if project.is_dir() else None


def _save_last_project(project: Path) -> None:
    settings_path = _editor_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".editor-settings.", dir=settings_path.parent)
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        temporary_path.write_text(
            json.dumps({"last_project": str(project.resolve())}, ensure_ascii=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary_path, settings_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _initial_project_root(
    project_dir: Path | None,
    current_directory: Path,
    package_root: Path,
    last_project: Path | None,
) -> Path:
    if project_dir is not None:
        return project_root_from(project_dir)

    current = project_root_from(current_directory)
    package = editor_package_root(package_root)
    if _contains_project(current) and (
        current != package or not _is_standalone_editor_package(package)
    ):
        return current
    if last_project is not None and _contains_project(last_project):
        return last_project
    if _contains_project(package):
        return package
    if _contains_project(current):
        return current
    return _starter_project_directory()


@dataclass
class Diagnostic:
    severity: str
    message: str
    line: int = 1
    source: str = "Editor"


class AssetCatalog:
    """Project-first view of the asset paths used by VN Engine."""

    def __init__(self, project_root: Path, project_values: dict | None = None):
        self.project_root = project_root
        values = merge_defaults(DEFAULT_PROJECT, project_values or {})
        paths = values.get("paths", {})
        if not isinstance(paths, dict):
            paths = {}
        self.data_dir = self._resolve_path(paths.get("data", "data"), project_root)
        self.assets_dir = self._resolve_path(paths.get("assets", "assets"), project_root)
        self.engine_assets_dir = project_root / "engine" / "assets"
        self.roots = [self.assets_dir, self.engine_assets_dir]
        self.characters: dict[str, dict] = {}
        self.mod_assets = {"images": [], "sounds": [], "music": [], "fonts": [], "characters": []}
        self._suggestion_cache = {}
        self._filesystem_asset_index = {}
        self._mod_packages_scanned = False
        self._characters_scanned = False

    @staticmethod
    def _resolve_path(value, root: Path) -> Path:
        path = Path(value) if isinstance(value, (str, Path)) else Path(".")
        return path if path.is_absolute() else (root / path).resolve()

    def _scan_characters(self):
        for priority, root in enumerate(self.roots):
            character_root = root / "characters"
            if not character_root.is_dir():
                continue
            try:
                files = sorted(
                    (path for path in character_root.rglob("*") if path.is_file() and path.suffix.casefold() == ".png"),
                    key=lambda p: p.as_posix().casefold(),
                )
            except OSError:
                continue
            for file_path in files:
                try:
                    relative = file_path.relative_to(character_root)
                except ValueError:
                    continue
                if len(relative.parts) < 2:
                    continue
                character_name = relative.parts[0]
                look = "/".join(relative.parts[1:-1])
                expression = relative.stem
                char_key = character_name.casefold()
                look_key = look.casefold()
                expr_key = expression.casefold()
                character = self.characters.setdefault(
                    char_key, {"name": character_name, "looks": {}}
                )
                look_data = character["looks"].setdefault(
                    look_key, {"name": look, "expressions": {}}
                )
                expressions = look_data["expressions"].setdefault(expr_key, [])
                if any(item["priority"] < priority for item in expressions):
                    continue
                if any(item["priority"] == priority and item["expression"] == expression
                       for item in expressions):
                    continue
                expressions.append({"expression": expression, "path": file_path, "priority": priority})

        for asset_name in self.mod_assets["characters"]:
            relative = PurePosixPath(asset_name)
            if len(relative.parts) < 2 or relative.suffix.casefold() != ".png":
                continue
            character_name = relative.parts[0]
            look = "/".join(relative.parts[1:-1])
            expression = relative.stem
            char_key = character_name.casefold()
            look_key = look.casefold()
            expr_key = expression.casefold()
            character = self.characters.setdefault(char_key, {"name": character_name, "looks": {}})
            look_data = character["looks"].setdefault(look_key, {"name": look, "expressions": {}})
            expressions = look_data["expressions"].setdefault(expr_key, [])
            if any(item["priority"] < 0.5 for item in expressions):
                continue
            expressions[:] = [item for item in expressions if item["priority"] < 0.5]
            expressions.append({"expression": expression, "path": self.assets_dir / "mods" / asset_name, "priority": 0.5})

    def _scan_mod_packages(self):
        mod_directory = self.assets_dir / "mods"
        if not mod_directory.is_dir():
            return
        for package_path in sorted(mod_directory.glob("*.vnmod"), key=lambda path: path.name.casefold()):
            try:
                with ZipFile(package_path) as archive:
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                    if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
                        continue
                    for info in archive.infolist():
                        if info.is_dir():
                            continue
                        path = PurePosixPath(info.filename.replace("\\", "/"))
                        if path.is_absolute() or ".." in path.parts or len(path.parts) < 3 or path.parts[0] != "assets":
                            continue
                        category = path.parts[1]
                        if category not in self.mod_assets or (info.external_attr >> 16) & 0o170000 == 0o120000:
                            continue
                        self.mod_assets[category].append("/".join(path.parts[2:]))
            except (OSError, ValueError, KeyError, UnicodeDecodeError, BadZipFile):
                continue
        for category, names in self.mod_assets.items():
            self.mod_assets[category] = sorted(set(names), key=str.casefold)

    def _ensure_mod_packages(self):
        if self._mod_packages_scanned:
            return
        self._scan_mod_packages()
        self._mod_packages_scanned = True

    def _ensure_characters(self):
        if self._characters_scanned:
            return
        self._ensure_mod_packages()
        self._scan_characters()
        self._characters_scanned = True

    def _ensure_filesystem_asset_index(self, kind: str):
        if kind in self._filesystem_asset_index:
            return self._filesystem_asset_index[kind]
        folder = ASSET_FOLDER[kind]
        stems = set()
        paths_without_suffix = set()
        for root in self.roots:
            category = root / folder
            if not category.is_dir():
                continue
            try:
                for path in category.rglob("*"):
                    if not path.is_file():
                        continue
                    relative = path.relative_to(category)
                    stems.add(path.stem.casefold())
                    paths_without_suffix.add(relative.with_suffix("").as_posix().casefold())
            except OSError:
                continue
        index = (stems, paths_without_suffix)
        self._filesystem_asset_index[kind] = index
        return index

    def character_names(self):
        self._ensure_characters()
        return sorted((item["name"] for item in self.characters.values()), key=str.casefold)

    def find_character(self, name):
        self._ensure_characters()
        if not isinstance(name, str):
            return None
        return self.characters.get(name.casefold())

    def looks_for(self, name):
        character = self.find_character(name)
        if not character:
            return []
        return sorted((look["name"] for look in character["looks"].values()), key=str.casefold)

    def expressions_for(self, name, look=None):
        character = self.find_character(name)
        if not character:
            return []
        look_values = character["looks"].values()
        if look is not None:
            look_data = character["looks"].get(str(look).replace("\\", "/").casefold())
            look_values = [look_data] if look_data else []
        found = set()
        for look_data in look_values:
            if look_data:
                for records in look_data["expressions"].values():
                    found.update(record["expression"] for record in records)
        return sorted(found, key=str.casefold)

    def asset_exists(self, kind: str, name: str) -> bool:
        if not isinstance(name, str) or not name:
            return False
        candidate = Path(name)
        if candidate.is_absolute():
            return candidate.is_file()
        normalized = name.replace("\\", "/")
        wanted = normalized.casefold()
        for root in self.roots:
            folder = ASSET_FOLDER[kind]
            for base in (root, root / folder):
                direct = base / Path(normalized)
                if direct.is_file():
                    return True
        if not candidate.suffix:
            stems, paths_without_suffix = self._ensure_filesystem_asset_index(kind)
            if wanted in stems or wanted in paths_without_suffix:
                return True
        self._ensure_mod_packages()
        mod_names = self.mod_assets.get(ASSET_FOLDER.get(kind, ""), [])
        for item in mod_names:
            candidates = {item.casefold(), f"{ASSET_FOLDER[kind]}/{item}".casefold()}
            if wanted in candidates:
                return True
            if not candidate.suffix and (
                Path(item).stem.casefold() == wanted
                or Path(item).with_suffix("").as_posix().casefold() == wanted
            ):
                matches = [value for value in mod_names if Path(value).stem.casefold() == wanted]
                if len(matches) == 1:
                    return True
        builtins = BUILTIN_ASSETS[kind]
        category = ASSET_FOLDER[kind]
        builtin_names = {item.casefold() for item in builtins}
        builtin_names.update(f"{category}/{item}".casefold() for item in builtins)
        if not candidate.suffix:
            short_names = {Path(item).stem.casefold() for item in builtins}
            relative_names = {Path(item).with_suffix("").as_posix().casefold() for item in builtins}
            relative_names.update(f"{category}/{Path(item).with_suffix('').as_posix()}".casefold() for item in builtins)
            return wanted in short_names or wanted in relative_names
        return normalized.casefold() in builtin_names

    def asset_suggestions(self, kind: str):
        if kind in self._suggestion_cache:
            return self._suggestion_cache[kind]
        self._ensure_mod_packages()
        folder = ASSET_FOLDER[kind]
        result = set()
        for root in self.roots:
            category = root / folder
            if not category.is_dir():
                continue
            try:
                for path in category.rglob("*"):
                    if not path.is_file():
                        continue
                    relative = path.relative_to(category)
                    if kind in {"image", "sound"}:
                        value = relative.with_suffix("").as_posix()
                    else:
                        value = relative.as_posix()
                    result.add(value)
            except OSError:
                pass
        for filename in BUILTIN_ASSETS[kind]:
            result.add(Path(filename).stem if kind in {"image", "sound"} else filename)
        result.update(
            Path(filename).stem if kind in {"image", "sound"} else filename
            for filename in self.mod_assets.get(folder, [])
        )
        suggestions = sorted(result, key=str.casefold)
        self._suggestion_cache[kind] = suggestions
        return suggestions

    def asset_tree_path(self, file_path: Path, root: Path):
        relative = file_path.relative_to(root).as_posix()
        return relative


def _line_of_key(source: str, key: str, start: int = 1, indent: int | None = None) -> int:
    escaped = re.escape(str(key))
    for number, line in enumerate(source.splitlines(), 1):
        if number < start:
            continue
        match = re.match(r"^(\s*)(?:-\s*)?" + escaped + r"\s*:", line)
        if match and (indent is None or len(match.group(1).replace("\t", "  ")) == indent):
            return number
    return max(1, start)


def _suggest_typo(value: str, choices) -> str:
    matches = get_close_matches(str(value), sorted(choices), n=1, cutoff=0.55)
    return f" Did you mean '{matches[0]}'?" if matches else ""


def _mapping_key_diagnostics(mapping: dict, allowed: set[str], source: str, line: int, path: str):
    result = []
    for key in mapping:
        if not isinstance(key, str):
            result.append(Diagnostic("error", f"{path}: keys must be strings.", line))
        elif key not in allowed:
            key_line = _line_of_key(source, key, start=line)
            result.append(Diagnostic(
                "error", f"Unknown key '{key}' in {path}.{_suggest_typo(key, allowed)}", key_line
            ))
    return result


def _yaml_duplicate_keys(source: str):
    if yaml is None:
        return []
    try:
        root = yaml.compose(source)
    except Exception:
        return []
    duplicates = []

    def walk(node):
        if isinstance(node, yaml.MappingNode):
            seen = set()
            for key_node, value_node in node.value:
                try:
                    key = yaml.safe_load(key_node.value) if isinstance(key_node, yaml.ScalarNode) else None
                except Exception:
                    key = None
                try:
                    hash(key)
                    duplicate_key = key in seen
                    seen.add(key)
                except TypeError:
                    duplicate_key = False
                if duplicate_key:
                    duplicates.append(Diagnostic(
                        "error", f"Duplicate YAML key '{key}'. The later value replaces the earlier one.",
                        key_node.start_mark.line + 1,
                    ))
                walk(value_node)
        elif isinstance(node, yaml.SequenceNode):
            for child in node.value:
                walk(child)

    if root is not None:
        walk(root)
    return duplicates


def analyze_story(
    source: str,
    catalog: AssetCatalog,
    *,
    fragment: bool = False,
    context_variables: dict | None = None,
    context_dialogues: set[str] | None = None,
    source_path: Path | None = None,
):
    diagnostics: list[Diagnostic] = []
    if yaml is None:
        diagnostics.append(Diagnostic(
            "warning", "PyYAML is not installed. Install it with 'python -m pip install PyYAML' for YAML parsing and semantic checks.", 1
        ))
        return diagnostics
    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        line = mark.line + 1 if mark is not None else 1
        message = getattr(error, "problem", None) or str(error).splitlines()[0]
        diagnostics.append(Diagnostic("error", f"YAML syntax: {message}", line))
        text_line = next((n for n, row in enumerate(source.splitlines(), 1)
                          if n >= line and re.match(r"^\s*text\s*:", row)), None)
        if text_line is not None:
            diagnostics.append(Diagnostic(
                "hint", "Quote this dialogue text with double quotes; punctuation can change YAML structure.", text_line
            ))
        return diagnostics
    except Exception as error:
        diagnostics.append(Diagnostic("error", f"Could not parse YAML: {error}", 1))
        return diagnostics

    diagnostics.extend(_yaml_duplicate_keys(source))
    if not isinstance(data, dict):
        diagnostics.append(Diagnostic("error", "Story root must be a YAML mapping.", 1))
        return diagnostics

    allowed_story_keys = {"includes", "variables", "character_defaults", "dialogues"} if fragment else STORY_TOP_KEYS
    diagnostics.extend(_mapping_key_diagnostics(data, allowed_story_keys, source, 1, "story"))
    includes = data.get("includes", [])
    if not isinstance(includes, list) or any(not isinstance(item, str) or not item.strip() for item in includes):
        diagnostics.append(Diagnostic("error", "'includes' must be a list of YAML paths relative to the current file.", _line_of_key(source, "includes")))
    elif hasattr(catalog, "data_dir"):
        for include in includes:
            include_path = Path(include.replace("\\", "/"))
            include_base = source_path.parent if source_path is not None else catalog.data_dir
            try:
                include_candidate = (include_base / include_path).resolve()
                include_candidate.relative_to(catalog.data_dir.resolve())
            except ValueError:
                include_candidate = None
            if include_path.is_absolute():
                diagnostics.append(Diagnostic("error", f"Story include {include!r} must stay inside the data folder.", _line_of_key(source, "includes")))
            elif include_path.suffix.casefold() not in {".yaml", ".yml"}:
                diagnostics.append(Diagnostic("error", f"Story include {include!r} must use .yaml or .yml.", _line_of_key(source, "includes")))
            elif include_candidate is None or not include_candidate.is_file():
                diagnostics.append(Diagnostic("error", f"Story include {include!r} was not found under {catalog.data_dir}.", _line_of_key(source, "includes")))
    if not fragment and "title" in data and not isinstance(data["title"], str):
        diagnostics.append(Diagnostic("error", "Story title must be a string.", _line_of_key(source, "title")))
    localization = data.get(
        "localization",
        {"default_locale": "en", "locales": {"en": "English"}},
    )
    if not fragment:
        if not isinstance(localization, dict):
            diagnostics.append(Diagnostic("error", "localization must be a mapping.", _line_of_key(source, "localization")))
            localization = {"default_locale": "en", "locales": {"en": "English"}}
        diagnostics.extend(_mapping_key_diagnostics(
            localization, {"default_locale", "locales"}, source,
            _line_of_key(source, "localization"), "localization",
        ))
        locale_names = localization.get("locales", {})
        if not isinstance(locale_names, dict) or not locale_names:
            diagnostics.append(Diagnostic("error", "localization.locales must map locale IDs to display names.", _line_of_key(source, "locales", _line_of_key(source, "localization"))))
            locale_names = {"en": "English"}
        else:
            for locale_id, display_name in locale_names.items():
                if not isinstance(locale_id, str) or re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", locale_id) is None:
                    diagnostics.append(Diagnostic("error", f"Invalid locale ID {locale_id!r}; use a BCP-47 style ID such as 'en' or 'pt-BR'.", _line_of_key(source, locale_id, _line_of_key(source, "locales"))))
                if not isinstance(display_name, str) or not display_name.strip():
                    diagnostics.append(Diagnostic("error", f"Display name for locale {locale_id!r} must be a non-empty string.", _line_of_key(source, locale_id, _line_of_key(source, "locales"))))
        default_locale = localization.get("default_locale", "en")
        if not isinstance(default_locale, str) or default_locale not in locale_names:
            diagnostics.append(Diagnostic("error", "localization.default_locale must name one of localization.locales.", _line_of_key(source, "default_locale", _line_of_key(source, "localization"))))
            default_locale = next(iter(locale_names), "en")
    else:
        locale_names = {"en": "English"}
        default_locale = "en"

    def validate_localized_text(value, field, line, required=False):
        if isinstance(value, str):
            if required and not value:
                diagnostics.append(Diagnostic("error", f"{field} must be a non-empty string.", line))
            return
        if not isinstance(value, dict):
            diagnostics.append(Diagnostic("error", f"{field} must be a string or locale-to-string mapping.", line))
            return
        if default_locale not in value:
            diagnostics.append(Diagnostic("error", f"{field} must include the default locale '{default_locale}'.", line))
        for locale_id, translated in value.items():
            if locale_id not in locale_names:
                diagnostics.append(Diagnostic("error", f"{field} uses undeclared locale '{locale_id}'.", _line_of_key(source, locale_id, line)))
            if not isinstance(translated, str) or (required and not translated):
                diagnostics.append(Diagnostic("error", f"{field}.{locale_id} must be a non-empty string.", _line_of_key(source, locale_id, line)))
        missing = set(locale_names) - set(value)
        if missing:
            diagnostics.append(Diagnostic("warning", f"{field} is missing translations for {', '.join(sorted(missing))}; the default locale will be used.", line))
    variables = data.get("variables", {})
    if not isinstance(variables, dict):
        diagnostics.append(Diagnostic("error", "'variables' must be a mapping of names to scalar starting values.", _line_of_key(source, "variables")))
        variables = {}
    local_variables = variables
    if context_variables is not None:
        variables = context_variables
    for name, value in local_variables.items():
        if not isinstance(name, str) or not name:
            diagnostics.append(Diagnostic("error", "Variable names must be non-empty strings.", _line_of_key(source, "variables")))
        if not _is_scalar(value):
            diagnostics.append(Diagnostic("error", f"Starting value for variable '{name}' must be a string, number, boolean, or null.", _line_of_key(source, name, _line_of_key(source, "variables"))))

    raw_defaults = data.get("character_defaults", {})
    if not isinstance(raw_defaults, dict):
        diagnostics.append(Diagnostic("error", "'character_defaults' must be a mapping.", _line_of_key(source, "character_defaults")))
        raw_defaults = {}
    for name, defaults in raw_defaults.items():
        line = _line_of_key(source, name, _line_of_key(source, "character_defaults"))
        if not isinstance(defaults, dict):
            diagnostics.append(Diagnostic("error", f"character_defaults.{name} must be a mapping.", line))
            continue
        diagnostics.extend(_mapping_key_diagnostics(defaults, {"look", "position"}, source, line, f"character_defaults.{name}"))
        if not catalog.find_character(name):
            choices = catalog.character_names()
            hint = _suggest_typo(name, choices)
            diagnostics.append(Diagnostic("error", f"Unknown character '{name}' in character_defaults.{name}.{hint}", line))
        look = defaults.get("look")
        if look is not None and (not isinstance(look, str) or look.casefold() not in {item.casefold() for item in catalog.looks_for(name)}):
            diagnostics.append(Diagnostic("error", f"Unknown look '{look}' for character '{name}'.", _line_of_key(source, "look", line)))
        position = defaults.get("position")
        if position is not None and (not isinstance(position, str) or position not in CHARACTER_POSITIONS):
            diagnostics.append(Diagnostic("error", f"Invalid character position '{position}'. Use {', '.join(sorted(CHARACTER_POSITIONS))}.", _line_of_key(source, "position", line)))

    dialogues = data.get("dialogues")
    if not isinstance(dialogues, dict):
        diagnostics.append(Diagnostic("error", "'dialogues' must be a mapping.", _line_of_key(source, "dialogues")))
        dialogues = {}
    if not dialogues and not fragment and not (includes and context_dialogues):
        diagnostics.append(Diagnostic("error", "'dialogues' must be a non-empty mapping.", _line_of_key(source, "dialogues")))
        return diagnostics
    start = data.get("start")
    known_dialogues = context_dialogues if context_dialogues is not None else set(dialogues)
    if not fragment and (not isinstance(start, str) or start not in known_dialogues):
        diagnostics.append(Diagnostic("error", f"'start' must name an existing dialogue; got {start!r}.", _line_of_key(source, "start")))

    targets = []
    for dialogue_id, dialogue in dialogues.items():
        line = _line_of_key(source, dialogue_id, _line_of_key(source, "dialogues"))
        if not isinstance(dialogue_id, str) or not dialogue_id:
            diagnostics.append(Diagnostic("error", "Dialogue IDs must be non-empty strings.", line))
        if not isinstance(dialogue, dict):
            diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id} must be a mapping.", line))
            continue
        diagnostics.extend(_mapping_key_diagnostics(dialogue, DIALOGUE_KEYS, source, line, f"dialogues.{dialogue_id}"))
        if not isinstance(dialogue.get("speaker"), str) or not dialogue.get("speaker"):
            diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.speaker must be a non-empty string.", _line_of_key(source, "speaker", line)))
        validate_localized_text(dialogue.get("text"), f"dialogues.{dialogue_id}.text", _line_of_key(source, "text", line), required=True)
        if "speaker_name" in dialogue:
            validate_localized_text(dialogue.get("speaker_name"), f"dialogues.{dialogue_id}.speaker_name", _line_of_key(source, "speaker_name", line), required=True)
        chapter = dialogue.get("chapter")
        if "chapter" in dialogue and not isinstance(chapter, str):
            diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.chapter must be a string.", _line_of_key(source, "chapter", line)))
        voice = dialogue.get("voice")
        if voice is not None and (not isinstance(voice, str) or not voice):
            diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.voice must be a sound asset path.", _line_of_key(source, "voice", line)))
        elif voice and not catalog.asset_exists("sound", voice):
            diagnostics.append(Diagnostic("error", f"Missing voice sound asset '{voice}'. Check assets/sounds/.", _line_of_key(source, "voice", line)))
        active = dialogue.get("active_character", dialogue.get("speaker"))
        if active is not None and (not isinstance(active, str) or not active):
            diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.active_character must be a character ID or null.", _line_of_key(source, "active_character", line)))
        elif "active_character" in dialogue and active is not None and not catalog.find_character(active):
            hint = _suggest_typo(active, catalog.character_names())
            diagnostics.append(Diagnostic(
                "error", f"Unknown active character asset '{active}'.{hint}",
                _line_of_key(source, "active_character", line),
            ))
        next_id = dialogue.get("next")
        if next_id is not None:
            if not isinstance(next_id, str):
                diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.next must be a dialogue ID.", _line_of_key(source, "next", line)))
            else:
                targets.append((next_id, _line_of_key(source, "next", line), f"dialogues.{dialogue_id}.next"))
        call_id = dialogue.get("call")
        if call_id is not None:
            if not isinstance(call_id, str):
                diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.call must be a dialogue ID.", _line_of_key(source, "call", line)))
            else:
                targets.append((call_id, _line_of_key(source, "call", line), f"dialogues.{dialogue_id}.call"))
            if not isinstance(next_id, str):
                diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.call requires a 'next' dialogue as its return continuation.", _line_of_key(source, "call", line)))
            if "options" in dialogue:
                diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.call cannot be combined with 'options'.", line))
        return_value = dialogue.get("return", False)
        if not isinstance(return_value, bool):
            diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.return must be true or false.", _line_of_key(source, "return", line)))
        elif return_value:
            if call_id is not None:
                diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id} cannot both call and return.", line))
            if next_id is not None or "options" in dialogue:
                diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.return cannot be combined with 'next' or 'options'.", line))
        options = dialogue.get("options", [])
        if not isinstance(options, list):
            diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.options must be a list.", _line_of_key(source, "options", line)))
            options = []
        if options and next_id is not None:
            diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id} cannot define both 'next' and 'options'.", line))
        for option in options:
            if not isinstance(option, dict):
                diagnostics.append(Diagnostic("error", f"Choices in dialogues.{dialogue_id}.options must be mappings.", _line_of_key(source, "options", line)))
                continue
            option_line = _line_of_key(source, "label", _line_of_key(source, "options", line))
            diagnostics.extend(_mapping_key_diagnostics(option, OPTION_KEYS, source, option_line, f"dialogues.{dialogue_id}.options"))
            validate_localized_text(option.get("label"), f"dialogues.{dialogue_id}.options.label", _line_of_key(source, "label", option_line), required=True)
            target = option.get("target")
            if not isinstance(target, str):
                diagnostics.append(Diagnostic("error", "Choice target must be a dialogue ID.", _line_of_key(source, "target", option_line)))
            else:
                targets.append((target, _line_of_key(source, "target", option_line), f"dialogues.{dialogue_id}.options"))
            if "condition" in option:
                diagnostics.extend(_validate_condition(option["condition"], variables, source, option_line, f"dialogues.{dialogue_id}.options.condition"))

        choice_timeout = dialogue.get("choice_timeout")
        timeout_target = dialogue.get("choice_timeout_target")
        if choice_timeout is not None:
            try:
                timeout_value = float(choice_timeout)
            except (TypeError, ValueError, OverflowError):
                timeout_value = math.nan
            if (
                not isinstance(choice_timeout, (int, float))
                or isinstance(choice_timeout, bool)
                or not math.isfinite(timeout_value)
                or not 0.1 <= timeout_value <= 3600
            ):
                diagnostics.append(Diagnostic("error", "choice_timeout must be from 0.1 to 3600 seconds.", _line_of_key(source, "choice_timeout", line)))
            if not options:
                diagnostics.append(Diagnostic("error", "choice_timeout requires at least one choice option.", _line_of_key(source, "choice_timeout", line)))
        if timeout_target is not None:
            option_targets = {
                option.get("target") for option in options
                if isinstance(option, dict) and isinstance(option.get("target"), str)
            }
            if not isinstance(timeout_target, str) or timeout_target not in option_targets:
                diagnostics.append(Diagnostic("error", "choice_timeout_target must match one of this dialogue's option targets.", _line_of_key(source, "choice_timeout_target", line)))
            if choice_timeout is None:
                diagnostics.append(Diagnostic("error", "choice_timeout_target requires choice_timeout.", _line_of_key(source, "choice_timeout_target", line)))

        actions = dialogue.get("actions", [])
        if not isinstance(actions, list):
            diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.actions must be a list.", _line_of_key(source, "actions", line)))
            actions = []
        input_actions = [
            action for action in actions
            if isinstance(action, dict) and action.get("type") == "input"
        ]
        if len(input_actions) > 1:
            diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id} may contain at most one input action.", _line_of_key(source, "actions", line)))
        if input_actions and any(
            isinstance(action, dict) and action.get("type") == "autosave"
            for action in actions
        ):
            diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id} cannot combine an input action with autosave.", _line_of_key(source, "actions", line)))
        for action in actions:
            diagnostics.extend(_validate_action(action, variables, catalog, source, line, dialogue_id))

    for target, line, where in targets:
        if target not in known_dialogues:
            diagnostics.append(Diagnostic("error", f"{where} points to missing dialogue '{target}'.", line))

    # Quote text that YAML accepts but does not preserve as a plain string.
    for number, row in enumerate(source.splitlines(), 1):
        match = re.match(r"^\s*(?:-\s*)?text\s*:\s*(.*)$", row)
        if not match:
            continue
        value = match.group(1).strip()
        if not value or value.startswith(("'", '"', "|", ">")):
            continue
        if (" #" in value or ": " in value or value in {"yes", "no", "true", "false", "null", "~"}
                or value.startswith(("[", "{", "&", "*", "!", "?"))):
            diagnostics.append(Diagnostic("hint", "Quote this dialogue text so YAML keeps it as text and does not treat punctuation as syntax.", number))
    diagnostics.extend(_validate_inline_assets(source, catalog))
    # Keep the live panel readable when several checks report the same line/message.
    unique = {}
    for item in diagnostics:
        unique[(item.severity, item.line, item.message)] = item
    return list(unique.values())


def _is_scalar(value):
    return value is None or isinstance(value, (str, int, float, bool))


def _validate_condition(condition, variables, source, line, where):
    result = []
    if not isinstance(condition, dict) or not condition:
        return [Diagnostic("error", f"{where} must be a mapping.", line)]
    result.extend(_mapping_key_diagnostics(condition, CONDITION_KEYS, source, line, where))
    if len(condition) == 1 and "all" in condition or len(condition) == 1 and "any" in condition:
        kind = "all" if "all" in condition else "any"
        children = condition[kind]
        if not isinstance(children, list) or not children:
            result.append(Diagnostic("error", f"{where}.{kind} must be a non-empty list.", _line_of_key(source, kind, line)))
        else:
            for child in children:
                result.extend(_validate_condition(child, variables, source, line, f"{where}.{kind}"))
        return result
    if len(condition) == 1 and "not" in condition:
        return _validate_condition(condition["not"], variables, source, line, f"{where}.not")
    variable = condition.get("var")
    operator = condition.get("op")
    if not isinstance(variable, str) or variable not in variables:
        result.append(Diagnostic("error", f"{where} references undeclared variable {variable!r}.", _line_of_key(source, "var", line)))
    if not isinstance(operator, str) or operator not in CONDITION_OPERATORS:
        result.append(Diagnostic("error", f"{where}.op must be one of {', '.join(sorted(CONDITION_OPERATORS))}.", _line_of_key(source, "op", line)))
    elif "value" not in condition:
        result.append(Diagnostic("error", f"{where} requires a 'value'.", _line_of_key(source, "op", line)))
    elif isinstance(variable, str) and variable in variables:
        initial, expected = variables[variable], condition["value"]
        if operator in {"<", "<=", ">", ">="}:
            numbers = (int, float)
            numeric = isinstance(initial, numbers) and not isinstance(initial, bool) and isinstance(expected, numbers) and not isinstance(expected, bool)
            strings = isinstance(initial, str) and isinstance(expected, str)
            if not (numeric or strings):
                result.append(Diagnostic("error", f"{where} compares incompatible value types.", _line_of_key(source, "value", line)))
        elif operator in {"in", "not_in"}:
            if not isinstance(expected, (str, list)):
                result.append(Diagnostic("error", f"{where}.value must be a string or list for '{operator}'.", _line_of_key(source, "value", line)))
            elif isinstance(expected, str) and not isinstance(initial, str):
                result.append(Diagnostic("error", f"{where} requires a string variable for '{operator}'.", _line_of_key(source, "var", line)))
    return result


def _validate_action(action, variables, catalog, source, dialogue_line, dialogue_id):
    result = []
    action_line = _line_of_key(source, "type", dialogue_line)
    if not isinstance(action, dict):
        return [Diagnostic("error", f"Actions in dialogues.{dialogue_id} must be mappings.", _line_of_key(source, "actions", dialogue_line))]
    kind = action.get("type")
    if not isinstance(kind, str) or kind not in ACTION_TYPES:
        result.append(Diagnostic("error", f"Unknown action type {kind!r}.{_suggest_typo(kind, ACTION_TYPES)}", action_line))
        result.extend(_mapping_key_diagnostics(
            action,
            {"type", "var", "value", "prompt", "input_type", "image", "track", "name", "look", "expression", "frames", "position", "direction", "duration", "frame_duration", "loop", "color", "intensity"},
            source,
            action_line,
            "action",
        ))
        return result
    result.extend(_mapping_key_diagnostics(action, ACTION_FIELDS[kind], source, action_line, f"action '{kind}'"))
    required = REQUIRED_ACTION_FIELDS.get(kind, set())
    for key in required:
        if key not in action:
            result.append(Diagnostic("error", f"Action '{kind}' requires '{key}'.", action_line))
    if kind in {"show_character", "hide_character"}:
        transition = action.get("transition", "none")
        if not isinstance(transition, str) or transition not in {"none", "fade", "slide"}:
            result.append(Diagnostic("error", "Character transition must be 'none', 'fade', or 'slide'.", _line_of_key(source, "transition", action_line)))
        duration = action.get("duration", 0.35)
        try:
            duration_value = float(duration)
        except (TypeError, ValueError, OverflowError):
            duration_value = math.nan
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not math.isfinite(duration_value)
            or not 0 < duration_value <= 30
        ):
            result.append(Diagnostic("error", "Character transition duration must be greater than 0 and at most 30 seconds.", _line_of_key(source, "duration", action_line)))
        easing = action.get("easing", "ease_out")
        if not isinstance(easing, str) or easing not in {"linear", "ease_in", "ease_out", "ease_in_out"}:
            result.append(Diagnostic("error", "Character transition easing must be linear, ease_in, ease_out, or ease_in_out.", _line_of_key(source, "easing", action_line)))
    if kind in {"set", "add", "subtract"}:
        variable = action.get("var")
        value = action.get("value")
        if not isinstance(variable, str) or variable not in variables:
            result.append(Diagnostic("error", f"Action '{kind}' references undeclared variable {variable!r}.", _line_of_key(source, "var", action_line)))
        if "value" in action and not _is_scalar(value):
            result.append(Diagnostic("error", f"Action '{kind}' value must be a scalar.", _line_of_key(source, "value", action_line)))
        if kind in {"add", "subtract"}:
            initial = variables.get(variable) if isinstance(variable, str) else None
            if not isinstance(initial, (int, float)) or isinstance(initial, bool):
                result.append(Diagnostic("error", f"Action '{kind}' needs a numeric story variable.", _line_of_key(source, "var", action_line)))
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                result.append(Diagnostic("error", f"Action '{kind}' needs a numeric value.", _line_of_key(source, "value", action_line)))
    elif kind == "input":
        variable = action.get("var")
        if not isinstance(variable, str) or variable not in variables:
            result.append(Diagnostic("error", f"Action 'input' references undeclared variable {variable!r}.", _line_of_key(source, "var", action_line)))
        prompt = action.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            result.append(Diagnostic("error", "Action 'input' requires a non-empty prompt.", _line_of_key(source, "prompt", action_line)))
        input_type = action.get("input_type", "text")
        if not isinstance(input_type, str) or input_type not in {"text", "integer"}:
            result.append(Diagnostic("error", "Action 'input' input_type must be 'text' or 'integer'.", _line_of_key(source, "input_type", action_line)))
        elif isinstance(variable, str) and variable in variables:
            initial = variables[variable]
            if input_type == "text" and initial is not None and not isinstance(initial, str):
                result.append(Diagnostic("error", f"Action 'input' requires variable '{variable}' to start as a string or null.", _line_of_key(source, "var", action_line)))
            elif input_type == "integer" and initial is not None and (
                not isinstance(initial, int) or isinstance(initial, bool)
            ):
                result.append(Diagnostic("error", f"Action 'input' requires variable '{variable}' to start as an integer or null.", _line_of_key(source, "var", action_line)))
    elif kind in {"background", "sound", "music"}:
        field, category = {"background": ("image", "image"), "sound": ("name", "sound"), "music": ("track", "music")}[kind]
        asset_name = action.get(field)
        if not isinstance(asset_name, str) or not asset_name:
            result.append(Diagnostic("error", f"Action '{kind}' requires a non-empty '{field}'.", _line_of_key(source, field, action_line)))
        elif not catalog.asset_exists(category, asset_name):
            result.append(Diagnostic("error", f"Missing {category} asset '{asset_name}'. Check project assets and built-in engine assets.", _line_of_key(source, field, action_line)))
    elif kind in {"unlock_cg", "unlock_music", "achievement", "complete_route"}:
        identifier = action.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            result.append(Diagnostic("error", f"Action '{kind}' requires a non-empty stable id.", _line_of_key(source, "id", action_line)))
        title_field = "label" if kind in {"unlock_cg", "unlock_music"} else "title"
        if title_field in action and (not isinstance(action[title_field], str) or not action[title_field].strip()):
            result.append(Diagnostic("error", f"Action '{kind}' {title_field} must be a non-empty string.", _line_of_key(source, title_field, action_line)))
        if kind == "unlock_cg":
            image_name = action.get("image")
            if not isinstance(image_name, str) or not image_name.strip():
                result.append(Diagnostic("error", "Action 'unlock_cg' requires an image asset path.", _line_of_key(source, "image", action_line)))
            elif not catalog.asset_exists("image", image_name):
                result.append(Diagnostic("error", f"Missing image asset '{image_name}'.", _line_of_key(source, "image", action_line)))
        elif kind == "unlock_music":
            track_name = action.get("track")
            if not isinstance(track_name, str) or not track_name.strip():
                result.append(Diagnostic("error", "Action 'unlock_music' requires a music track path.", _line_of_key(source, "track", action_line)))
            elif not catalog.asset_exists("music", track_name):
                result.append(Diagnostic("error", f"Missing music asset '{track_name}'.", _line_of_key(source, "track", action_line)))
        if "description" in action and (not isinstance(action["description"], str) or not action["description"].strip()):
            result.append(Diagnostic("error", "Action 'achievement' description must be a non-empty string.", _line_of_key(source, "description", action_line)))
    elif kind in {"show_character", "hide_character"}:
        name = action.get("name")
        character = catalog.find_character(name)
        if not character:
            hint = _suggest_typo(name, catalog.character_names())
            result.append(Diagnostic("error", f"Unknown character asset '{name}'.{hint}", _line_of_key(source, "name", action_line)))
        elif kind == "show_character":
            look = action.get("look")
            expression = action.get("expression")
            looks = catalog.looks_for(name)
            if look is not None and (not isinstance(look, str) or look.casefold() not in {item.casefold() for item in looks}):
                result.append(Diagnostic("error", f"Unknown look '{look}' for '{name}'. Available: {', '.join(looks) or '(root)'}.", _line_of_key(source, "look", action_line)))
            if not isinstance(expression, str) or not expression:
                result.append(Diagnostic("error", "show_character requires an expression PNG name without '.png'.", _line_of_key(source, "expression", action_line)))
            else:
                expressions = catalog.expressions_for(name, look)
                if expression.casefold() not in {item.casefold() for item in expressions}:
                    hint = _suggest_typo(expression, expressions)
                    result.append(Diagnostic("error", f"Unknown expression '{expression}' for '{name}'.{hint} Available: {', '.join(expressions)}.", _line_of_key(source, "expression", action_line)))
                elif look is None:
                    matching_looks = [look_name for look_name in looks if expression.casefold() in {x.casefold() for x in catalog.expressions_for(name, look_name)}]
                    if len(matching_looks) > 1:
                        result.append(Diagnostic("warning", f"Expression '{expression}' exists in multiple looks ({', '.join(matching_looks)}); set 'look' or character_defaults.", _line_of_key(source, "expression", action_line)))
            position = action.get("position")
            if position is not None and (not isinstance(position, str) or position not in CHARACTER_POSITIONS):
                result.append(Diagnostic("error", f"Invalid position '{position}'. Use {', '.join(sorted(CHARACTER_POSITIONS))}.", _line_of_key(source, "position", action_line)))
    elif kind == "animate_character":
        name = action.get("name")
        if not catalog.find_character(name):
            hint = _suggest_typo(name, catalog.character_names())
            result.append(Diagnostic("error", f"Unknown character asset '{name}'.{hint}", _line_of_key(source, "name", action_line)))
        frames = action.get("frames")
        if not isinstance(frames, list) or len(frames) < 2:
            result.append(Diagnostic("error", "animate_character.frames must contain at least two expression names.", _line_of_key(source, "frames", action_line)))
        else:
            look = action.get("look")
            available = catalog.expressions_for(name, look)
            for expression in frames:
                if not isinstance(expression, str) or expression.casefold() not in {item.casefold() for item in available}:
                    hint = _suggest_typo(expression, available)
                    result.append(Diagnostic("error", f"Unknown animation frame '{expression}' for '{name}'.{hint} Available: {', '.join(available)}.", _line_of_key(source, "frames", action_line)))
        look = action.get("look")
        looks = catalog.looks_for(name)
        if look is not None and (not isinstance(look, str) or look.casefold() not in {item.casefold() for item in looks}):
            result.append(Diagnostic("error", f"Unknown look '{look}' for '{name}'. Available: {', '.join(looks) or '(root)' }.", _line_of_key(source, "look", action_line)))
        position = action.get("position")
        if position is not None and (not isinstance(position, str) or position not in CHARACTER_POSITIONS):
            result.append(Diagnostic("error", f"Invalid position '{position}'. Use {', '.join(sorted(CHARACTER_POSITIONS))}.", _line_of_key(source, "position", action_line)))
        frame_duration = action.get("frame_duration", 0.25)
        if not isinstance(frame_duration, (int, float)) or isinstance(frame_duration, bool) or not 0 < frame_duration <= 60:
            result.append(Diagnostic("error", "animate_character.frame_duration must be greater than 0 and at most 60 seconds.", _line_of_key(source, "frame_duration", action_line)))
        if "loop" in action and not isinstance(action["loop"], bool):
            result.append(Diagnostic("error", "animate_character.loop must be true or false.", _line_of_key(source, "loop", action_line)))
    elif kind == "fade":
        direction = action.get("direction")
        if not isinstance(direction, str) or direction not in {"in", "out"}:
            result.append(Diagnostic("error", "fade.direction must be 'in' or 'out'.", _line_of_key(source, "direction", action_line)))
        duration = action.get("duration", 0.6)
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not 0 < duration <= 120:
            result.append(Diagnostic("error", "fade.duration must be greater than 0 and at most 120 seconds.", _line_of_key(source, "duration", action_line)))
        color = action.get("color", [0, 0, 0])
        if not isinstance(color, list) or len(color) not in {3, 4} or any(not isinstance(item, int) or isinstance(item, bool) or not 0 <= item <= 255 for item in color):
            result.append(Diagnostic("error", "fade.color must be an RGB or RGBA list with values from 0 to 255.", _line_of_key(source, "color", action_line)))
    elif kind == "shake":
        duration = action.get("duration", 0.35)
        intensity = action.get("intensity", 8)
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not 0 < duration <= 120:
            result.append(Diagnostic("error", "shake.duration must be greater than 0 and at most 120 seconds.", _line_of_key(source, "duration", action_line)))
        if not isinstance(intensity, (int, float)) or isinstance(intensity, bool) or not 0 < intensity <= 100:
            result.append(Diagnostic("error", "shake.intensity must be greater than 0 and at most 100.", _line_of_key(source, "intensity", action_line)))
    return result


def _validate_inline_assets(source: str, catalog: AssetCatalog):
    result = []
    for number, row in enumerate(source.splitlines(), 1):
        for image in re.findall(r"%([^%]+)%", row):
            if not catalog.asset_exists("image", image):
                result.append(Diagnostic("error", f"Inline marker references missing image '{image}'.", number))
        for sound in re.findall("§([^§]+)§", row):
            if not catalog.asset_exists("sound", sound):
                result.append(Diagnostic("error", f"Inline marker references missing sound '{sound}'.", number))
    return result


def analyze_project(source: str, catalog: AssetCatalog):
    try:
        raw = json.loads(source)
    except json.JSONDecodeError as error:
        return [Diagnostic("error", f"JSON syntax: {error.msg}", error.lineno)]
    if not isinstance(raw, dict):
        return [Diagnostic("error", "Project configuration root must be a JSON object.", 1)]
    diagnostics: list[Diagnostic] = []
    project_raw = json.loads(json.dumps(raw))
    for key in ("theme", "dialogue_buttons", "characters"):
        if key in project_raw:
            diagnostics.append(Diagnostic(
                "warning",
                f"'{key}' is a visual setting; move it to data/style.json.",
                _line_of_key(source, key),
            ))
            project_raw.pop(key, None)
    intro = project_raw.get("intro")
    if isinstance(intro, dict):
        for key in ("credit_image", "warning_image", "headphones_image"):
            if key in intro:
                diagnostics.append(Diagnostic(
                    "warning",
                    f"'intro.{key}' is a visual setting; move it to style.json under 'intro'.",
                    _line_of_key(source, key, _line_of_key(source, "intro")),
                ))
                intro.pop(key, None)
    values = merge_defaults(DEFAULT_RUNTIME_PROJECT, project_raw)
    _validate_project_object(values, project_raw, source, diagnostics)
    story_name = values.get("story")
    if isinstance(story_name, str):
        story_path = Path(story_name)
        if not story_path.is_absolute():
            story_path = catalog.data_dir / story_path
        if not story_path.is_file():
            diagnostics.append(Diagnostic("error", f"Configured story file was not found: {story_path}.", _line_of_key(source, "story")))
    return diagnostics


def analyze_style(source: str, catalog: AssetCatalog, project_source: str = "{}"):
    try:
        raw = json.loads(source)
    except json.JSONDecodeError as error:
        return [Diagnostic("error", f"JSON syntax: {error.msg}", error.lineno)]
    if not isinstance(raw, dict):
        return [Diagnostic("error", "Style configuration root must be a JSON object.", 1)]

    diagnostics: list[Diagnostic] = []

    def check_unknown(override, schema, path, line):
        if not isinstance(override, dict) or not isinstance(schema, dict):
            return
        if path == "style.json.characters":
            return
        if path == "style.json.variants":
            for name, variant in override.items():
                variant_line = _line_of_key(source, str(name), line)
                if not isinstance(name, str) or not name.strip():
                    diagnostics.append(Diagnostic("error", "Variant names must be non-empty strings.", variant_line))
                    continue
                if not isinstance(variant, dict):
                    diagnostics.append(Diagnostic("error", f"variants.{name} must be an object.", variant_line))
                    continue
                variant_values = {key: value for key, value in variant.items() if key != "label"}
                check_unknown(
                    variant_values,
                    {key: value for key, value in DEFAULT_STYLE.items() if key != "variants"},
                    f"style.json.variants.{name}",
                    variant_line,
                )
            return
        if path == "style.json.skins":
            for name, skin in override.items():
                skin_line = _line_of_key(source, str(name), line)
                if not isinstance(skin, dict):
                    diagnostics.append(Diagnostic("error", f"skins.{name} must be an object.", skin_line))
                    continue
                check_unknown(skin, DEFAULT_STYLE["skins"]["button"], f"style.json.skins.{name}", skin_line)
            return
        diagnostics.extend(_mapping_key_diagnostics(override, set(schema), source, line, path))
        for key, child in override.items():
            if key in schema and isinstance(child, dict) and isinstance(schema[key], dict):
                check_unknown(child, schema[key], path + "." + str(key), _line_of_key(source, key, line))

    check_unknown(raw, DEFAULT_STYLE, "style.json", 1)
    character_styles = raw.get("characters", {})
    if not isinstance(character_styles, dict):
        diagnostics.append(Diagnostic(
            "error", "characters must be an object mapping character names to settings.",
            _line_of_key(source, "characters"),
        ))
    else:
        for name, settings in character_styles.items():
            line = _line_of_key(source, str(name), _line_of_key(source, "characters"))
            if not isinstance(name, str) or not name.strip():
                diagnostics.append(Diagnostic("error", "characters keys must be non-empty character names.", line))
                continue
            if not isinstance(settings, dict):
                diagnostics.append(Diagnostic("error", f"characters.{name} must be an object.", line))
                continue
            diagnostics.extend(_mapping_key_diagnostics(
                settings, {"scale"}, source, line, f"characters.{name}"
            ))
            scale = settings.get("scale", 100)
            try:
                valid_scale = (
                    isinstance(scale, (int, float))
                    and not isinstance(scale, bool)
                    and math.isfinite(scale)
                    and scale > 0
                )
            except OverflowError:
                valid_scale = False
            if not valid_scale:
                diagnostics.append(Diagnostic(
                    "error", f"characters.{name}.scale must be a positive percentage.",
                    _line_of_key(source, "scale", line),
                ))
    version = raw.get("schema_version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        diagnostics.append(Diagnostic(
            "error", "schema_version must be 1 for this engine version.",
            _line_of_key(source, "schema_version"),
        ))

    try:
        project_values = json.loads(project_source)
        if not isinstance(project_values, dict):
            project_values = {}
    except json.JSONDecodeError:
        project_values = {}
    try:
        from engine.project import ProjectConfig

        project = ProjectConfig(project_values, raw)
    except (TypeError, ValueError) as error:
        diagnostics.append(Diagnostic("error", str(error), 1))
        return diagnostics
    _validate_project_assets(project.values, catalog, source, diagnostics)
    return diagnostics


def _validate_project_object(values, raw, source, diagnostics):
    def check_unknown(override, schema, path, line):
        if not isinstance(override, dict) or not isinstance(schema, dict):
            return
        diagnostics.extend(_mapping_key_diagnostics(override, set(schema), source, line, path))
        for key, child in override.items():
            if key in schema and isinstance(child, dict) and isinstance(schema[key], dict):
                check_unknown(child, schema[key], path + "." + str(key), _line_of_key(source, key, line))

    diagnostics.extend(_mapping_key_diagnostics(raw, set(DEFAULT_PROJECT), source, 1, "project.json"))
    if "USER" in raw and not isinstance(raw["USER"], str):
        diagnostics.append(Diagnostic(
            "error",
            "USER must be a string; 'admin' requires workspace-source Test Play, while 'user' permits template fallback.",
            _line_of_key(source, "USER"),
        ))
    for key, child in raw.items():
        if (
            key not in {"theme", "characters"}
            and key in DEFAULT_PROJECT
            and isinstance(child, dict)
            and isinstance(DEFAULT_PROJECT[key], dict)
        ):
            check_unknown(child, DEFAULT_PROJECT[key], f"project.json.{key}", _line_of_key(source, key))
    characters = raw.get("characters", {})
    if not isinstance(characters, dict):
        diagnostics.append(Diagnostic(
            "error",
            "characters must be an object mapping character names to settings.",
            _line_of_key(source, "characters"),
        ))
    else:
        for name, settings in characters.items():
            character_line = _line_of_key(
                source, str(name), _line_of_key(source, "characters")
            )
            if not isinstance(name, str) or not name.strip():
                diagnostics.append(Diagnostic(
                    "error",
                    "characters keys must be non-empty character names.",
                    character_line,
                ))
                continue
            if not isinstance(settings, dict):
                diagnostics.append(Diagnostic(
                    "error",
                    f"characters.{name} must be an object.",
                    character_line,
                ))
                continue
            diagnostics.extend(_mapping_key_diagnostics(
                settings, {"scale"}, source, character_line, f"characters.{name}"
            ))
            scale = settings.get("scale", 100)
            try:
                valid_scale = (
                    isinstance(scale, (int, float))
                    and not isinstance(scale, bool)
                    and math.isfinite(scale)
                    and scale > 0
                )
            except OverflowError:
                valid_scale = False
            if not valid_scale:
                diagnostics.append(Diagnostic(
                    "error",
                    f"characters.{name}.scale must be a positive percentage.",
                    _line_of_key(source, "scale", character_line),
                ))
    dialogue_buttons = raw.get("dialogue_buttons", {})
    if not isinstance(dialogue_buttons, dict):
        diagnostics.append(Diagnostic(
            "error",
            "dialogue_buttons must be an object.",
            _line_of_key(source, "dialogue_buttons"),
        ))
    else:
        for button_name in ("back", "history", "quick_save", "quick_load", "auto", "mute"):
            button = dialogue_buttons.get(button_name)
            if button is None:
                continue
            button_line = _line_of_key(
                source, button_name, _line_of_key(source, "dialogue_buttons")
            )
            if not isinstance(button, dict):
                diagnostics.append(Diagnostic(
                    "error",
                    f"dialogue_buttons.{button_name} must be an object.",
                    button_line,
                ))
                continue
            if "visible" in button and not isinstance(button["visible"], bool):
                diagnostics.append(Diagnostic(
                    "error",
                    f"dialogue_buttons.{button_name}.visible must be a boolean.",
                    _line_of_key(source, "visible", button_line),
                ))
            if "label" in button and not isinstance(button["label"], str):
                diagnostics.append(Diagnostic(
                    "error",
                    f"dialogue_buttons.{button_name}.label must be a string.",
                    _line_of_key(source, "label", button_line),
                ))
    theme = raw.get("theme", {})
    if isinstance(theme, dict):
        check_unknown(theme, DEFAULT_THEME, "theme", _line_of_key(source, "theme"))
        theme_values = merge_defaults(DEFAULT_THEME, theme)
        for group, font_names in (
            ("fonts", ("menu", "title")),
            ("game_fonts", ("text", "name", "button", "intro")),
        ):
            font_config = theme.get(group, {})
            if not isinstance(font_config, dict):
                diagnostics.append(Diagnostic(
                    "error",
                    f"theme.{group} must be an object.",
                    _line_of_key(source, group, _line_of_key(source, "theme")),
                ))
                continue
            for name in font_names:
                font = font_config.get(name)
                if font is not None and not isinstance(font, str):
                    diagnostics.append(Diagnostic(
                        "error",
                        f"theme.{group}.{name} must be a font path or null.",
                        _line_of_key(source, name, _line_of_key(source, group)),
                    ))
        for group, size_names in (
            ("fonts", ("item_size", "detail_size", "title_size")),
            (
                "game_font_sizes",
                ("text", "name", "button", "dialogue_controls", "intro", "intro_small"),
            ),
        ):
            size_config = theme.get(group, {})
            if not isinstance(size_config, dict):
                diagnostics.append(Diagnostic(
                    "error",
                    f"theme.{group} must be an object.",
                    _line_of_key(source, group, _line_of_key(source, "theme")),
                ))
                continue
            defaults = DEFAULT_THEME[group]
            for name in size_names:
                size = size_config.get(name, defaults[name])
                if not isinstance(size, int) or isinstance(size, bool) or size < 1:
                    diagnostics.append(Diagnostic(
                        "error",
                        f"theme.{group}.{name} must be a positive integer.",
                        _line_of_key(source, name, _line_of_key(source, group)),
                    ))
        menu_theme = theme.get("menu", {})
        resolved_menu = theme_values.get("menu", {})
        if not isinstance(menu_theme, dict):
            diagnostics.append(Diagnostic("error", "theme.menu must be an object.", _line_of_key(source, "menu")))
        if isinstance(menu_theme, dict) and menu_theme.get("layout") not in (None, "centered", "left", "right"):
            diagnostics.append(Diagnostic("error", "theme.menu.layout must be centered, left, or right.", _line_of_key(source, "layout", _line_of_key(source, "menu"))))
        raw_screens = menu_theme.get("screens", {}) if isinstance(menu_theme, dict) else {}
        if not isinstance(raw_screens, dict):
            diagnostics.append(Diagnostic(
                "error",
                "theme.menu.screens must be an object.",
                _line_of_key(source, "screens", _line_of_key(source, "menu")),
            ))
        menu_configs = values.get("menus", {})
        if not isinstance(menu_configs, dict):
            menu_configs = {}

        def menu_items(name):
            config = menu_configs.get(name, {})
            items = config.get("items", []) if isinstance(config, dict) else []
            return items if isinstance(items, list) else []

        main_items = menu_items("main")
        pause_items = menu_items("pause")
        settings_items = menu_items("settings")
        slots_count = values.get("save_slots", 0)
        if not isinstance(slots_count, int) or isinstance(slots_count, bool) or slots_count < 1:
            slots_count = 0
        menu_item_counts = {
            "main": len(main_items),
            "pause": len(pause_items),
            "settings": len(settings_items)
            + (
                0
                if any(
                    item.get("setting") == "ui_scale"
                    for item in settings_items
                    if isinstance(item, dict)
                )
                else 1
            ),
            "slots": slots_count,
        }

        def grid_indexes(grid, screen_name, expected_count, line):
            if screen_name == "credits":
                diagnostics.append(Diagnostic("error", "Credits uses a scrolling list and does not support a grid.", line))
                return
            if not isinstance(grid, list) or not grid:
                diagnostics.append(Diagnostic("error", "Menu grid must be a non-empty list of rows.", line))
                return
            indexes = []
            columns = 0
            valid = True
            for row_index, row in enumerate(grid, 1):
                if not isinstance(row, list):
                    diagnostics.append(Diagnostic("error", f"Menu grid row {row_index} must be a list.", line))
                    valid = False
                    continue
                columns = max(columns, len(row))
                for cell in row:
                    if cell is None or (
                        isinstance(cell, int) and not isinstance(cell, bool) and cell == 0
                    ):
                        continue
                    if not isinstance(cell, int) or isinstance(cell, bool) or cell < 1:
                        diagnostics.append(Diagnostic("error", "Menu grid cells must be null, 0, or positive button indexes.", line))
                        valid = False
                    else:
                        indexes.append(cell)
            if not columns or not indexes:
                diagnostics.append(Diagnostic("error", "Menu grid must place at least one button.", line))
                valid = False
            if len(indexes) != len(set(indexes)):
                diagnostics.append(Diagnostic("error", "Menu grid button indexes must not repeat.", line))
                valid = False
            if valid and sorted(indexes) != list(range(1, expected_count + 1)):
                diagnostics.append(Diagnostic(
                    "error",
                    f"Menu grid must place every button exactly once from 1 to {expected_count}.",
                    line,
                ))

        if isinstance(raw_screens, dict):
            for screen_name, screen in raw_screens.items():
                if not isinstance(screen, dict):
                    diagnostics.append(Diagnostic(
                        "error",
                        f"theme.menu.screens.{screen_name} must be an object.",
                        _line_of_key(source, screen_name, _line_of_key(source, "screens", _line_of_key(source, "menu"))),
                    ))
                    continue
                screen_line = _line_of_key(source, screen_name, _line_of_key(source, "screens", _line_of_key(source, "menu")))
                alignment = screen.get("alignment")
                if alignment is not None and (
                    not isinstance(alignment, str)
                    or alignment not in {"centered", "left", "right"}
                ):
                    diagnostics.append(Diagnostic(
                        "error",
                        f"theme.menu.screens.{screen_name}.alignment must be centered, left, or right.",
                        _line_of_key(source, "alignment", screen_line),
                    ))
                for dimension in ("top", "row_gap", "button_width", "button_height"):
                    value = screen.get(dimension)
                    minimum = 0 if dimension in {"top", "row_gap"} else 1
                    if value is not None and (
                        not isinstance(value, int) or isinstance(value, bool) or value < minimum
                    ):
                        diagnostics.append(Diagnostic(
                            "error",
                            f"theme.menu.screens.{screen_name}.{dimension} must be an integer of at least {minimum}.",
                            _line_of_key(source, dimension, screen_line),
                        ))
                background = screen.get("background")
                if background is not None and not isinstance(background, str):
                    diagnostics.append(Diagnostic(
                        "error",
                        f"theme.menu.screens.{screen_name}.background must be an image path or null.",
                        _line_of_key(source, "background", screen_line),
                    ))
                buttons = screen.get("buttons", {})
                if not isinstance(buttons, dict):
                    diagnostics.append(Diagnostic(
                        "error",
                        f"theme.menu.screens.{screen_name}.buttons must be an object.",
                        _line_of_key(source, "buttons", screen_line),
                    ))
                else:
                    for state in ("normal", "hovered"):
                        image = buttons.get(state)
                        if image is not None and (
                            not isinstance(image, str) or Path(image).suffix.casefold() != ".png"
                        ):
                            diagnostics.append(Diagnostic(
                                "error",
                                f"theme.menu.screens.{screen_name}.buttons.{state} must be a PNG path or null.",
                                _line_of_key(source, state, _line_of_key(source, "buttons", screen_line)),
                            ))
                grid = screen.get("grid")
                if grid is not None:
                    grid_indexes(
                        grid,
                        screen_name,
                        menu_item_counts.get(screen_name, 0),
                        _line_of_key(source, "grid", screen_line),
                    )

        textbox_theme = theme_values.get("textbox", {})
        raw_textbox = theme.get("textbox", {})
        if not isinstance(raw_textbox, dict):
            diagnostics.append(Diagnostic(
                "error",
                "theme.textbox must be an object.",
                _line_of_key(source, "textbox"),
            ))
        if isinstance(raw_textbox, dict):
            color = raw_textbox.get("color")
            if color is not None and (
                not isinstance(color, list) or len(color) not in {3, 4}
                or any(not isinstance(channel, int) or isinstance(channel, bool) or not 0 <= channel <= 255 for channel in color)
            ):
                diagnostics.append(Diagnostic("error", "theme.textbox.color must be an RGB or RGBA array with values from 0 to 255.", _line_of_key(source, "color", _line_of_key(source, "textbox"))))
        textbox_values = textbox_theme if isinstance(textbox_theme, dict) else {}
        geometry = {}
        for key in ("x", "bottom", "width", "height", "opacity"):
            value = textbox_values.get(key)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0 <= value <= 1
                or (key in {"width", "height"} and value == 0)
            ):
                diagnostics.append(Diagnostic(
                    "error",
                    f"theme.textbox.{key} must be a fraction from 0 to 1.",
                    _line_of_key(source, key, _line_of_key(source, "textbox")),
                ))
            else:
                geometry[key] = value
        if (
            all(key in geometry for key in ("x", "width", "bottom", "height"))
            and (
                geometry["x"] + geometry["width"] > 1
                or geometry["bottom"] + geometry["height"] > 1
            )
        ):
            diagnostics.append(Diagnostic(
                "error",
                "theme.textbox geometry must fit within the window.",
                _line_of_key(source, "textbox"),
            ))

        choice_theme = theme.get("choice_buttons", {})
        if not isinstance(choice_theme, dict):
            diagnostics.append(Diagnostic(
                "error",
                "theme.choice_buttons must be an object.",
                _line_of_key(source, "choice_buttons"),
            ))
        else:
            for state in ("normal", "hovered"):
                image = choice_theme.get(state)
                if image is not None and (
                    not isinstance(image, str) or Path(image).suffix.casefold() != ".png"
                ):
                    diagnostics.append(Diagnostic(
                        "error",
                        f"theme.choice_buttons.{state} must be a PNG path or null.",
                        _line_of_key(source, state, _line_of_key(source, "choice_buttons")),
                    ))
            for dimension in ("width", "height"):
                value = choice_theme.get(dimension, DEFAULT_THEME["choice_buttons"][dimension])
                if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                    diagnostics.append(Diagnostic(
                        "error",
                        f"theme.choice_buttons.{dimension} must be a positive integer.",
                        _line_of_key(source, dimension, _line_of_key(source, "choice_buttons")),
                    ))
            gap = choice_theme.get("gap", DEFAULT_THEME["choice_buttons"]["gap"])
            if not isinstance(gap, int) or isinstance(gap, bool) or gap < 0:
                diagnostics.append(Diagnostic(
                    "error",
                    "theme.choice_buttons.gap must be a non-negative integer.",
                    _line_of_key(source, "gap", _line_of_key(source, "choice_buttons")),
                ))
        pause_theme = theme.get("pause_button", {})
        if not isinstance(pause_theme, dict):
            diagnostics.append(Diagnostic(
                "error",
                "theme.pause_button must be an object.",
                _line_of_key(source, "pause_button"),
            ))
        else:
            image = pause_theme.get("image")
            if image is not None and (
                not isinstance(image, str) or Path(image).suffix.casefold() != ".png"
            ):
                diagnostics.append(Diagnostic(
                    "error",
                    "theme.pause_button.image must be a PNG path or null.",
                    _line_of_key(source, "image", _line_of_key(source, "pause_button")),
                ))
    elif "theme" in raw:
        diagnostics.append(Diagnostic("error", "theme must be an object.", _line_of_key(source, "theme")))

    intro = values.get("intro", {})
    if not isinstance(intro, dict):
        diagnostics.append(Diagnostic("error", "intro must be an object.", _line_of_key(source, "intro")))
    else:
        for key in ("creator", "warning_message"):
            if not isinstance(intro.get(key), str):
                diagnostics.append(Diagnostic("error", f"intro.{key} must be a string.", _line_of_key(source, key, _line_of_key(source, "intro"))))
        version = intro.get("game_version")
        if version is not None and not isinstance(version, str):
            diagnostics.append(Diagnostic("error", "intro.game_version must be a string or null.", _line_of_key(source, "game_version", _line_of_key(source, "intro"))))

    paths = values.get("paths", {})
    if not isinstance(paths, dict):
        diagnostics.append(Diagnostic("error", "paths must be an object.", _line_of_key(source, "paths")))
        paths = {}
    for path_name in ("data", "assets", "user_data"):
        if not isinstance(paths.get(path_name), str):
            diagnostics.append(Diagnostic("error", f"paths.{path_name} must be a string path.", _line_of_key(source, path_name, _line_of_key(source, "paths"))))
    if not isinstance(values.get("name"), str):
        diagnostics.append(Diagnostic("error", "name must be a string.", _line_of_key(source, "name")))
    if not isinstance(values.get("story"), str):
        diagnostics.append(Diagnostic("error", "story must be a YAML filename.", _line_of_key(source, "story")))
    else:
        story_name = Path(values["story"])
        if story_name.suffix.casefold() not in {".yaml", ".yml"}:
            diagnostics.append(Diagnostic("error", "story must refer to a .yaml or .yml file.", _line_of_key(source, "story")))
    slots = values.get("save_slots")
    if not isinstance(slots, int) or isinstance(slots, bool) or slots < 1:
        diagnostics.append(Diagnostic("error", "save_slots must be a positive integer.", _line_of_key(source, "save_slots")))
    window = values.get("window", {})
    if isinstance(window, dict):
        for key in ("width", "height"):
            if not isinstance(window.get(key), int) or isinstance(window.get(key), bool) or window.get(key) < 1:
                diagnostics.append(Diagnostic("error", f"window.{key} must be a positive integer.", _line_of_key(source, key, _line_of_key(source, "window"))))
        if not isinstance(window.get("caption"), str):
            diagnostics.append(Diagnostic("error", "window.caption must be a string.", _line_of_key(source, "caption", _line_of_key(source, "window"))))
    else:
        diagnostics.append(Diagnostic("error", "window must be an object.", _line_of_key(source, "window")))
    android = values.get("android")
    android_line = _line_of_key(source, "android")
    if not isinstance(android, dict):
        diagnostics.append(Diagnostic("error", "android must be an object.", android_line))
    else:
        if not isinstance(android.get("app_name"), str) or not android["app_name"].strip():
            diagnostics.append(Diagnostic("error", "android.app_name must be a non-empty string.", _line_of_key(source, "app_name", android_line)))
        app_id = android.get("app_id")
        if not isinstance(app_id, str) or re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", app_id) is None:
            diagnostics.append(Diagnostic("error", "android.app_id must be a lowercase reverse-DNS identifier.", _line_of_key(source, "app_id", android_line)))
        orientation = android.get("orientation")
        if not isinstance(orientation, str) or orientation not in {"landscape", "portrait"}:
            diagnostics.append(Diagnostic("error", "android.orientation must be landscape or portrait.", _line_of_key(source, "orientation", android_line)))

    menus = values.get("menus", {})
    if not isinstance(menus, dict):
        diagnostics.append(Diagnostic("error", "menus must be an object.", _line_of_key(source, "menus")))
    else:
        for menu_name in ("main", "pause", "settings"):
            menu = menus.get(menu_name)
            menu_line = _line_of_key(source, menu_name, _line_of_key(source, "menus"))
            if not isinstance(menu, dict) or not isinstance(menu.get("title"), str):
                diagnostics.append(Diagnostic("error", f"menus.{menu_name} needs a string title.", menu_line))
                continue
            items = menu.get("items")
            if not isinstance(items, list):
                diagnostics.append(Diagnostic("error", f"menus.{menu_name}.items must be a list.", _line_of_key(source, "items", menu_line)))
                continue
            for item in items:
                if not isinstance(item, dict):
                    diagnostics.append(Diagnostic("error", f"Items in menus.{menu_name}.items must be objects.", _line_of_key(source, "items", menu_line)))
                    continue
                item_line = _line_of_key(source, "label", _line_of_key(source, "items", menu_line))
                diagnostics.extend(_mapping_key_diagnostics(item, {"label", "action", "setting", "detail"}, source, item_line, f"menus.{menu_name}.items"))
                if not isinstance(item.get("label"), str):
                    diagnostics.append(Diagnostic("error", "Menu item needs a string label.", item_line))
                action = item.get("action")
                if not isinstance(action, str) or action not in MENU_ACTIONS:
                    diagnostics.append(Diagnostic("error", f"Unknown menu action {action!r}.{_suggest_typo(action, MENU_ACTIONS)}", _line_of_key(source, "action", item_line)))
                setting = item.get("setting")
                if isinstance(action, str) and action in {"adjust_setting", "toggle_setting"} and (not isinstance(setting, str) or setting not in SETTING_NAMES):
                    diagnostics.append(Diagnostic("error", f"Unknown setting {item.get('setting')!r}.", _line_of_key(source, "setting", item_line)))
                if action == "adjust_setting" and setting == "fullscreen":
                    diagnostics.append(Diagnostic("warning", "Use toggle_setting for fullscreen; adjust_setting does not change it.", _line_of_key(source, "action", item_line)))
                adjust_settings = {
                    "type_speed", "music_volume", "sfx_volume", "ui_scale",
                    "auto_wait", "dialogue_font_scale", "speaker_font_scale",
                    "touch_advance_mode",
                }
                toggle_settings = {
                    "fullscreen", "auto_advance", "high_contrast", "muted",
                    "reduced_motion", "voice_enabled", "subtitles_enabled", "speech_enabled",
                    "animated_text",
                }
                if action == "adjust_setting" and setting in toggle_settings:
                    diagnostics.append(Diagnostic("warning", f"Use toggle_setting for {setting!r}; it is an on/off setting.", _line_of_key(source, "action", item_line)))
                if action == "toggle_setting" and setting in adjust_settings:
                    diagnostics.append(Diagnostic("warning", f"Use adjust_setting for {setting!r}; it has adjustable values.", _line_of_key(source, "action", item_line)))

        slot_menu = menus.get("slots")
        if not isinstance(slot_menu, dict):
            diagnostics.append(Diagnostic("error", "menus.slots must be an object.", _line_of_key(source, "slots", _line_of_key(source, "menus"))))
        else:
            slot_line = _line_of_key(source, "slots", _line_of_key(source, "menus"))
            for key in ("title_save", "title_load"):
                if not isinstance(slot_menu.get(key), str):
                    diagnostics.append(Diagnostic("error", f"menus.slots.{key} must be a string.", _line_of_key(source, key, slot_line)))
            labels = slot_menu.get("labels")
            required_labels = ("slot", "saved", "empty", "corrupt", "unknown_chapter", "unknown_time")
            if not isinstance(labels, dict):
                diagnostics.append(Diagnostic("error", "menus.slots.labels must be an object.", _line_of_key(source, "labels", slot_line)))
            else:
                for key in required_labels:
                    if not isinstance(labels.get(key), str):
                        diagnostics.append(Diagnostic("error", f"menus.slots.labels.{key} must be a string.", _line_of_key(source, key, _line_of_key(source, "labels", slot_line))))
            for key, expected_action in (("delete", "delete_selected_slot"), ("back", "back")):
                item = slot_menu.get(key)
                if not isinstance(item, dict) or not isinstance(item.get("label"), str) or item.get("action") != expected_action:
                    diagnostics.append(Diagnostic("error", f"menus.slots.{key} needs a label and action '{expected_action}'.", _line_of_key(source, key, slot_line)))

    credits = values.get("credits", [])
    if not isinstance(credits, list):
        diagnostics.append(Diagnostic("error", "credits must be a list.", _line_of_key(source, "credits")))
    else:
        for item in credits:
            if isinstance(item, dict):
                diagnostics.extend(_mapping_key_diagnostics(item, {"label", "url"}, source, _line_of_key(source, "credits"), "credits item"))
                if not isinstance(item.get("label"), str):
                    diagnostics.append(Diagnostic("error", "Credit objects need a string label.", _line_of_key(source, "label", _line_of_key(source, "credits"))))
                url = item.get("url")
                if url is not None and (not isinstance(url, str) or not url.startswith(("http://", "https://"))):
                    diagnostics.append(Diagnostic("error", "Credit URLs must start with http:// or https://.", _line_of_key(source, "url", _line_of_key(source, "credits"))))
            elif not isinstance(item, str):
                diagnostics.append(Diagnostic("error", "Credit entries must be strings or objects with a label.", _line_of_key(source, "credits")))

    messages = values.get("messages", {})
    if not isinstance(messages, dict) or any(not isinstance(message, str) for message in messages.values()):
        diagnostics.append(Diagnostic("error", "messages must be an object of message IDs and text values.", _line_of_key(source, "messages")))
    else:
        required_arguments = {
            "unknown_menu_action": {"action": "action"}, "no_continue_save": {}, "no_active_game": {},
            "save_success": {"slot": 1}, "save_error": {"error": "error"},
            "slot_empty": {"slot": 1}, "different_story": {}, "load_error": {"error": "error"},
            "delete_success": {"slot": 1}, "delete_empty": {"slot": 1}, "delete_error": {"error": "error"},
        }
        for key, arguments in required_arguments.items():
            try:
                messages[key].format(**arguments)
            except (KeyError, IndexError, ValueError, AttributeError) as error:
                diagnostics.append(Diagnostic("error", f"Invalid placeholder in messages.{key}: {error}.", _line_of_key(source, key, _line_of_key(source, "messages"))))


def _validate_project_assets(values, catalog, source, diagnostics):
    def check(name, kind, path):
        if name and not catalog.asset_exists(kind, name):
            diagnostics.append(Diagnostic(
                "error", f"Missing style {kind} asset '{name}'.", _line_of_key(source, path.split(".")[-1]),
            ))

    intro = values.get("intro", {})
    if isinstance(intro, dict):
        for key in ("credit_image", "warning_image", "headphones_image"):
            check(intro.get(key), "image", f"intro.{key}")

    theme = values.get("theme", {})
    if not isinstance(theme, dict):
        return
    for group, keys in (("fonts", ("menu", "title")), ("game_fonts", ("text", "name", "button", "intro"))):
        values_group = theme.get(group, {})
        if isinstance(values_group, dict):
            for key in keys:
                check(values_group.get(key), "font", f"theme.{group}.{key}")
    menu = theme.get("menu", {})
    if isinstance(menu, dict):
        check(menu.get("background"), "image", "theme.menu.background")
        screens = menu.get("screens", {})
        if isinstance(screens, dict):
            for screen_name, screen in screens.items():
                if not isinstance(screen, dict):
                    continue
                check(screen.get("background"), "image", f"theme.menu.screens.{screen_name}.background")
                buttons = screen.get("buttons", {})
                if isinstance(buttons, dict):
                    for state, name in buttons.items():
                        check(name, "image", f"theme.menu.screens.{screen_name}.buttons.{state}")
    textbox = theme.get("textbox", {})
    if isinstance(textbox, dict):
        check(textbox.get("background"), "image", "theme.textbox.background")
    choice_buttons = theme.get("choice_buttons", {})
    if isinstance(choice_buttons, dict):
        for state in ("normal", "hovered"):
            check(choice_buttons.get(state), "image", f"theme.choice_buttons.{state}")
    pause_button = theme.get("pause_button", {})
    if isinstance(pause_button, dict):
        check(pause_button.get("image"), "image", "theme.pause_button.image")
    sounds = theme.get("sounds", {})
    if isinstance(sounds, dict):
        for key in ("hover", "click", "cancel", "load"):
            check(sounds.get(key), "sound", f"theme.sounds.{key}")


class CodeEditor(ttk.Frame):
    """Text surface with a line gutter, syntax colors, diagnostics, and completion."""

    def __init__(self, parent, app, document_kind: str):
        super().__init__(parent)
        self.app = app
        self.document_kind = document_kind
        self.dirty = False
        self._highlight_job = None
        self._completion_popup = None
        self._completion_list = None
        self._completion_range = None
        self._completion_items = []
        self._syntax_installed = False
        self._highlight_complete = False
        self._highlight_block = None

        self.gutter = tk.Canvas(self, width=48, highlightthickness=0, background="#20242d")
        self.gutter.setAlignment(
            tk.QtCore.Qt.AlignmentFlag.AlignLeft | tk.QtCore.Qt.AlignmentFlag.AlignTop
        )
        self.text = tk.Text(
            self,
            wrap="none",
            undo=True,
            autoseparators=True,
            maxundo=-1,
            font=("Consolas", 11),
            background="#171a21",
            foreground="#d8dee9",
            insertbackground="#f8f8f2",
            selectbackground="#3b4d65",
            relief="flat",
            padx=10,
            pady=8,
            tabs=("2c",),
            exportselection=False,
        )
        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.hscroll = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=self._on_yview, xscrollcommand=self.hscroll.set)
        text_layout = tk.QtWidgets.QGridLayout(self)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        text_layout.addWidget(self.gutter, 0, 0)
        text_layout.addWidget(self.text, 0, 1)
        text_layout.addWidget(self.vscroll, 0, 2)
        text_layout.addWidget(self.hscroll, 1, 1)
        text_layout.setColumnStretch(1, 1)
        text_layout.setRowStretch(0, 1)

        self.text.tag_configure("yaml_key", foreground="#8be9fd")
        self.text.tag_configure("json_key", foreground="#8be9fd")
        self.text.tag_configure("string", foreground="#f1fa8c")
        self.text.tag_configure("number", foreground="#bd93f9")
        self.text.tag_configure("keyword", foreground="#ff79c6")
        self.text.tag_configure("punctuation", foreground="#8b9bb4")
        self.text.tag_configure("comment", foreground="#737c8c", font=("Consolas", 11, "italic"))
        self.text.tag_configure("diagnostic_error", background="#4b252e", underline=True)
        self.text.tag_configure("diagnostic_warning", background="#493d24", underline=True)
        self.text.tag_configure("diagnostic_hint", underline=True, foreground="#72c7d7")
        self.text.tag_configure("search_match", background="#5a4b22", foreground="#fff2b0")
        self.text.tag_configure("search_current", background="#b06d19", foreground="#ffffff")

        self.text.bind("<<Modified>>", self._on_modified)
        self.text.bind("<KeyRelease>", self._on_key_release)
        self.text.bind("<ButtonRelease-1>", self._on_button_release)
        self.text.bind("<Configure>", lambda _event: self.redraw_gutter())
        self.text.bind("<Control-space>", self.show_completion)
        self.text.bind("<Tab>", self._tab_key)
        self.text.bind("<Return>", self._return_key)
        self.text.bind("<Escape>", self._escape_key)
        self.text.bind("<Up>", self._completion_up)
        self.text.bind("<Down>", self._completion_down)
        self.text.bind("<Control-slash>", self._comment_key)
        self.text.edit_modified(False)

    def get_text(self):
        return self.text.get_all_text()

    def _edit_history(self, operation):
        try:
            if operation == "undo":
                self.text.edit_undo()
            else:
                self.text.edit_redo()
        except tk.TclError:
            self.app.set_status(f"Nothing to {operation}.")
        return "break"

    def set_text(self, content: str):
        self.text.set_text_silently(content)
        self.dirty = False
        self._syntax_installed = False
        self._highlight_complete = False
        self._highlight_block = self.text.document().begin()
        self.schedule_highlight()
        self.redraw_gutter()

    def _on_modified(self, _event=None):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if not self.dirty:
            self.dirty = True
            self.app.document_changed(self.document_kind)
        self.app.schedule_analysis(self.document_kind)
        self.schedule_highlight()

    def _on_key_release(self, event):
        self.redraw_gutter()
        self.app.update_cursor_status()
        if event.keysym in {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Up", "Down", "Left", "Right", "Escape", "Return", "Tab"}:
            return
        if self._completion_popup is not None:
            self.hide_completion()
            self._completion_items = []
        self.app.schedule_completion(self, event)

    def _on_button_release(self, _event):
        if self._completion_popup is not None:
            self.hide_completion()
            self._completion_items = []
            self._completion_range = None
        self.app.update_cursor_status()

    def _on_yview(self, first, last):
        self.vscroll.set(first, last)
        self.redraw_gutter()

    def redraw_gutter(self):
        if not self.winfo_exists():
            return
        self.gutter.delete("all")
        self.gutter.setSceneRect(
            0, 0, self.gutter.viewport().width(), self.gutter.viewport().height()
        )
        try:
            first = int(self.text.index("@0,0").split(".")[0])
            last = int(self.text.index(f"@0,{self.text.winfo_height()}").split(".")[0]) + 1
        except (tk.TclError, ValueError):
            return
        for line in range(first, last + 1):
            info = self.text.dlineinfo(f"{line}.0")
            if info is None:
                continue
            y = info[1]
            current = line == int(self.text.index("insert").split(".")[0])
            color = "#d8dee9" if current else "#697386"
            self.gutter.create_text(40, y, anchor="ne", text=str(line), fill=color, font=("Consolas", 10))

    def schedule_highlight(self):
        if self._highlight_job is not None:
            self.after_cancel(self._highlight_job)
        self._highlight_job = self.after(90, self.highlight)

    def highlight(self):
        if self._highlight_job is not None:
            self.after_cancel(self._highlight_job)
        self._highlight_job = None
        if not self._syntax_installed:
            self.text.set_syntax_callback(self._line_syntax_spans)
            self._syntax_installed = True
            self._highlight_block = self.text.document().begin()
        self.app.apply_diagnostic_marks(self)
        if not self._highlight_complete and (self._highlight_block is None or not self._highlight_block.isValid()):
            self._highlight_block = self.text.document().begin()
        self._continue_highlighting()

    def _continue_highlighting(self):
        self._highlight_job = None
        block = self._highlight_block
        if self._highlight_complete:
            return
        if block is None or not block.isValid():
            block = self.text.document().begin()
        for _ in range(160):
            if not block.isValid():
                break
            self.text.rehighlight_block(block)
            block = block.next()
        self._highlight_block = block
        if block.isValid():
            self._highlight_job = self.after(5, self._continue_highlighting)
        else:
            self._highlight_complete = True

    def _line_syntax_spans(self, line):
        if self.document_kind == "story":
            return self._yaml_syntax_spans(line)
        return self._json_syntax_spans(line)

    def _yaml_syntax_spans(self, line):
        spans = []
        quote = None
        escaped = False
        comment_start = None
        for index, char in enumerate(line):
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\" and quote == '"':
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in {'"', "'"}:
                quote = char
            elif char == "#" and (index == 0 or line[index - 1].isspace()):
                comment_start = index
                break
        content_end = comment_start if comment_start is not None else len(line)
        key = re.match(r"^\s*(?:-\s*)?([A-Za-z_][\w-]*)(?=\s*:)", line[:content_end])
        if key:
            spans.append((key.start(1), key.end(1) - key.start(1), "yaml_key"))
        spans.extend(self._quoted_syntax_spans(line, content_end))
        for match in re.finditer(r"(?<![\w./-])(?:true|false|null|yes|no|on|off)(?![\w./-])", line[:content_end], re.I):
            spans.append((match.start(), match.end() - match.start(), "keyword"))
        for match in re.finditer(r"(?<![\w])[-+]?\d+(?:\.\d+)?(?![\w])", line[:content_end]):
            spans.append((match.start(), match.end() - match.start(), "number"))
        for match in re.finditer(r"[\[\]{},:]", line[:content_end]):
            spans.append((match.start(), match.end() - match.start(), "punctuation"))
        if comment_start is not None:
            spans.append((comment_start, len(line) - comment_start, "comment"))
        return spans

    def _json_syntax_spans(self, line):
        spans = []
        for match in re.finditer(r'"(?:\\.|[^"\\])*"(?=\s*:)', line):
            spans.append((match.start(), match.end() - match.start(), "json_key"))
        spans.extend(self._quoted_syntax_spans(line, len(line)))
        for match in re.finditer(r'\b(?:true|false|null)\b', line):
            spans.append((match.start(), match.end() - match.start(), "keyword"))
        for match in re.finditer(r"-?\b\d+(?:\.\d+)?\b", line):
            spans.append((match.start(), match.end() - match.start(), "number"))
        for match in re.finditer(r"[\[\]{},:]", line):
            spans.append((match.start(), match.end() - match.start(), "punctuation"))
        return spans

    @staticmethod
    def _quoted_syntax_spans(line, end):
        spans = []
        quote = None
        start = 0
        escaped = False
        for index, char in enumerate(line[:end]):
            if quote is None and char in {'"', "'"}:
                quote = char
                start = index
                escaped = False
            elif quote is not None:
                if escaped:
                    escaped = False
                elif char == "\\" and quote == '"':
                    escaped = True
                elif char == quote:
                    spans.append((start, index + 1 - start, "string"))
                    quote = None
        return spans

    def show_completion(self, _event=None, automatic=False):
        candidates, replace_start, prefix = self.app.completions_for(self)
        if prefix:
            filtered = [item for item in candidates if item[0].strip("'\"").casefold().startswith(prefix.casefold())]
            if not filtered:
                filtered = [item for item in candidates if prefix.casefold() in item[0].strip("'\"").casefold()]
            candidates = filtered
        if not candidates:
            if not automatic:
                self.app.set_status("No suggestions for this field.")
            self.hide_completion()
            self._completion_items = []
            self._completion_range = None
            return "break"
        self._completion_items = candidates[:18]
        self._completion_range = (replace_start, self.text.index("insert"))
        self._show_completion_popup()
        return "break"

    def _show_completion_popup(self):
        self.hide_completion()
        bbox = self.text.bbox("insert")
        if bbox is None:
            return
        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(background="#303744")
        x = self.text.winfo_rootx() + bbox[0]
        y = self.text.winfo_rooty() + bbox[1] + bbox[3]
        popup.geometry(f"+{x}+{y}")
        listing = tk.Listbox(
            popup, height=min(10, len(self._completion_items)), width=56,
            background="#252b36", foreground="#e6edf3", selectbackground="#3c5270",
            activestyle="none", relief="flat", borderwidth=1, font=("Consolas", 10),
            exportselection=False,
        )
        for label, detail in self._completion_items:
            listing.insert("end", f"{label}    {detail}" if detail else label)
        listing.selection_set(0)
        listing.pack()
        listing.bind("<ButtonRelease-1>", lambda _event: self.accept_completion())
        self._completion_popup = popup
        self._completion_list = listing

    def hide_completion(self):
        if self._completion_popup is not None:
            try:
                self._completion_popup.destroy()
            except tk.TclError:
                pass
        self._completion_popup = None
        self._completion_list = None

    def accept_completion(self):
        if not self._completion_items or not self._completion_range:
            return
        index = 0
        if self._completion_list is not None:
            selection = self._completion_list.curselection()
            if selection:
                index = selection[0]
        insertion = self._completion_items[index][0]
        start, end = self._completion_range
        self.text.delete(start, end)
        self.text.insert(start, insertion)
        self.text.mark_set("insert", f"{start}+{len(insertion)}c")
        self.text.see("insert")
        self.hide_completion()
        self._completion_items = []
        self._completion_range = None
        self.text.focus_set()
        return "break"

    def _completion_up(self, _event):
        if self._completion_list is not None:
            selection = self._completion_list.curselection()
            index = max(0, (selection[0] if selection else 0) - 1)
            self._completion_list.selection_clear(0, "end")
            self._completion_list.selection_set(index)
            self._completion_list.see(index)
            return "break"

    def _completion_down(self, _event):
        if self._completion_list is not None:
            selection = self._completion_list.curselection()
            index = min(len(self._completion_items) - 1, (selection[0] if selection else 0) + 1)
            self._completion_list.selection_clear(0, "end")
            self._completion_list.selection_set(index)
            self._completion_list.see(index)
            return "break"

    def _tab_key(self, _event):
        if self._completion_items:
            self.accept_completion()
            return "break"
        self.text.insert("insert", "  ")
        return "break"

    def _return_key(self, _event):
        if self._completion_items:
            self.accept_completion()
            return "break"
        line = self.text.get("insert linestart", "insert lineend")
        indent = re.match(r"\s*", line).group(0)
        stripped = line.strip()
        if self.document_kind in {"project", "style"} and stripped.startswith(("}", "]")):
            indent = indent[:-2] if len(indent) >= 2 else ""
        elif line.rstrip().endswith(":") or line.rstrip().endswith("-") or (
            self.document_kind in {"project", "style"} and line.rstrip().endswith(("{", "["))
        ):
            indent += "  "
        self.text.insert("insert", "\n" + indent)
        return "break"

    def _escape_key(self, _event):
        if self._completion_items:
            self.hide_completion()
            self._completion_items = []
            return "break"

    def _comment_key(self, _event):
        if self.document_kind in {"project", "style"}:
            self.app.set_status("JSON does not allow comments.")
            return "break"
        start = self.text.index("insert linestart")
        end = self.text.index("insert lineend")
        line = self.text.get(start, end)
        if line.lstrip().startswith("#"):
            offset = len(line) - len(line.lstrip())
            self.text.delete(f"{start}+{offset}c", f"{start}+{offset + 1}c")
        else:
            self.text.insert(start, "# ")
        return "break"


class VNEditorApp:
    def __init__(self, root: tk.Tk, project_root: Path):
        self.root = root
        self.project_root = project_root.resolve()
        self.editor_home = editor_package_root(Path(sys.argv[0]))
        self.project_file = self.project_root / "data" / "project.json"
        self.style_file = self.project_root / "data" / "style.json"
        self.story_file = self.project_root / "data" / "story.yaml"
        self.project_buffer = ""
        self.style_buffer = ""
        self.story_buffer = ""
        self.live_diagnostics: dict[str, list[Diagnostic]] = {"story": [], "project": [], "style": []}
        self.engine_diagnostics: list[Diagnostic] = []
        self._analysis_jobs = {}
        self._tab_change_analysis_job = None
        self._analysis_revisions = {"story": 0, "project": 0, "style": 0}
        self._document_analysis_cache = {"story": {}, "project": {}, "style": {}}
        self._completion_jobs = {}
        self._asset_catalog = None
        self._asset_catalog_key = None
        self._asset_refresh_job = None
        self._loading = False
        self.story_editors: dict[Path, CodeEditor] = {}
        self.open_text_editors: dict[Path, CodeEditor] = {}
        self.markdown_texts = {}
        self.markdown_paths = {}
        self.find_window = None
        self.find_entry = None
        self.find_case_sensitive = None
        self.test_play_process = None
        self.test_play_tempdir = None
        self.test_play_poll_job = None
        self.test_play_coverage_path = None
        self.test_play_log_path = None
        self._project_load_generation = 0
        self._project_load_pending = True
        self._initial_project_load_job = None
        self._included_story_load_job = None
        self._included_story_load_queue = []

        self.root.title(f"{APP_TITLE} — {self.project_root.name}")
        self.root.geometry("1320x880")
        self.root.minsize(940, 620)
        self._build_ui()
        self.set_status("Opening project…")
        self._initial_project_load_job = self.root.after(40, self._start_initial_project_load)
        self.root.bind("<Control-f>", lambda _event: self.show_find())
        self.root.bind("<Control-g>", lambda _event: self.open_story_graph())
        self.root.bind("<F5>", lambda _event: self.validate_with_engine())
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _start_initial_project_load(self):
        self._initial_project_load_job = None
        if self._project_load_generation == 0 and self._project_load_pending:
            self.load_project(self.project_root)

    def _build_ui(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook.Tab", padding=(14, 7))
        style.configure("Treeview", rowheight=23)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

        menu_bar = tk.Menu(self.root)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Open Project...", command=self.choose_project)
        file_menu.add_command(label="Open Story File...", command=self.open_file)
        file_menu.add_command(label="Close Tab", command=self.close_active_tab)
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_active)
        file_menu.add_command(label="Save All", accelerator="Ctrl+Shift+S", command=self.save_all)
        menu_bar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu_bar, tearoff=False)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=lambda: self._edit_active("undo"))
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=lambda: self._edit_active("redo"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Find...", accelerator="Ctrl+F", command=self.show_find)
        menu_bar.add_cascade(label="Edit", menu=edit_menu)

        project_menu = tk.Menu(menu_bar, tearoff=False)
        project_menu.add_command(label="Export Game...", command=self.export_game)
        project_menu.add_command(label="Refresh Assets", command=self.refresh_asset_tree)
        project_menu.add_separator()
        project_menu.add_command(label="Story Graph", command=self.open_story_graph)
        project_menu.add_separator()
        project_menu.add_command(label="Package Asset Add-on...", command=self.package_asset_addon)
        project_menu.add_command(label="Asset Diagnostics...", command=self.show_asset_diagnostics)
        project_menu.add_separator()
        project_menu.add_command(label="Visual Theme Editor...", command=self.open_visual_theme_editor)
        project_menu.add_command(label="Import Theme Preset...", command=self.import_theme_preset)
        project_menu.add_command(label="Export Theme Preset...", command=self.export_theme_preset)
        project_menu.add_separator()
        project_menu.add_command(label="Export Translation Template...", command=self.export_translation_template)
        project_menu.add_command(label="Import Translation Catalog...", command=self.import_translation_catalog)
        project_menu.add_command(label="Translation Preview and Missing Strings...", command=self.show_translation_preview)
        project_menu.add_separator()
        project_menu.add_command(label="Run Playthrough Suite...", command=self.run_playthrough_suite)
        menu_bar.add_cascade(label="Project", menu=project_menu)

        run_menu = tk.Menu(menu_bar, tearoff=False)
        run_menu.add_command(label="Validate Story", accelerator="F5", command=self.validate_with_engine)
        run_menu.add_separator()
        run_menu.add_command(label="Test Play", command=self.test_play)
        run_menu.add_command(label="Test from Dialogue...", command=self.test_from_dialogue)
        menu_bar.add_cascade(label="Run", menu=run_menu)

        help_menu = tk.Menu(menu_bar, tearoff=False)
        self.help_menu = help_menu
        menu_bar.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menu_bar)

        main = ttk.Panedwindow(self.root, orient="horizontal")
        main.pack(side="top", fill="both", expand=True, padx=8, pady=(3, 4))
        left = ttk.Frame(main, width=300)
        right = ttk.Frame(main)
        main.add(left, weight=0)
        main.add(right, weight=1)

        document_area = ttk.Frame(right)
        document_area.pack(fill="both", expand=True)

        asset_header = ttk.Frame(left)
        asset_header.pack(fill="x", pady=(0, 4))
        ttk.Label(asset_header, text="Asset hierarchy", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.add_button = ttk.Button(asset_header, text="Add", width=6, command=self.show_add_menu)
        self.add_button.pack(side="right", padx=(5, 0))
        ttk.Button(asset_header, text="Insert", width=7, command=self.insert_selected_asset).pack(side="right")
        ttk.Label(left, text="Select a file, then click Insert to add its reference.", foreground="#707987").pack(anchor="w", pady=(0, 5))
        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill="both", expand=True)
        self.asset_tree = ttk.Treeview(
            tree_frame, show="tree", selectmode="browse", compact_files=True
        )
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.asset_tree.yview)
        self.asset_tree.configure(yscrollcommand=tree_scroll.set)
        self.asset_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.asset_tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.asset_tree.bind("<Return>", lambda _event: self.insert_selected_asset())

        self.notebook = ttk.Notebook(document_area)
        self.notebook.pack(fill="both", expand=True)
        self.story_editor = CodeEditor(self.notebook, self, "story")
        self.project_editor = CodeEditor(self.notebook, self, "project")
        self.style_editor = CodeEditor(self.notebook, self, "style")
        self.story_editor._tab_closable = False
        self.project_editor._tab_closable = False
        self.style_editor._tab_closable = False
        self.story_editor.story_path = self.story_file
        self.story_editors = {self.story_file: self.story_editor}
        self.notebook.add(self.story_editor, text="story.yaml")
        self.notebook.add(self.project_editor, text="project.json")
        self.notebook.add(self.style_editor, text="style.json")
        self.notebook.close_callback = self.close_tab
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        diagnostics_frame = ttk.Frame(document_area)
        diagnostics_frame.pack(fill="x", expand=False, pady=(5, 0))
        ttk.Label(diagnostics_frame, text="Diagnostics", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        diag_tree_frame = ttk.Frame(diagnostics_frame)
        diag_tree_frame.pack(fill="x", expand=False)
        self.diagnostics_tree = ttk.Treeview(
            diag_tree_frame, columns=("source", "severity", "line", "message"), show="headings", height=6
        )
        self.diagnostics_tree.heading("source", text="Source")
        self.diagnostics_tree.heading("severity", text="Type")
        self.diagnostics_tree.heading("line", text="Line")
        self.diagnostics_tree.heading("message", text="Message")
        self.diagnostics_tree.column("source", width=75, stretch=False)
        self.diagnostics_tree.column("severity", width=75, stretch=False)
        self.diagnostics_tree.column("line", width=55, stretch=False, anchor="center")
        self.diagnostics_tree.column("message", width=780, stretch=True)
        diag_scroll = ttk.Scrollbar(diag_tree_frame, orient="vertical", command=self.diagnostics_tree.yview)
        self.diagnostics_tree.configure(yscrollcommand=diag_scroll.set)
        self.diagnostics_tree.pack(side="left", fill="x", expand=True)
        diag_scroll.pack(side="right", fill="y")
        self.diagnostics_tree.bind("<Double-1>", self._jump_to_diagnostic)

        self.status = ttk.Label(self.root, text="", anchor="w", relief="sunken", padding=(7, 4))
        self.status.pack(side="bottom", fill="x")

    def _refresh_markdown_tabs(self):
        self.markdown_texts.clear()
        self.markdown_paths.clear()
        self.help_menu.clear()
        paths = _editor_markdown_paths(self.editor_home)
        for path in paths:
            label = path.stem.replace("-", " ").replace("_", " ").title()
            if path.name.casefold() == "readme.md":
                label = "Editor Overview"
            if not path.is_file():
                continue
            self.help_menu.add_command(label=label, command=lambda selected=path: self.open_help_document(selected))

    def open_help_document(self, path):
        path = Path(path)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Help", f"Could not open {path.name}: {error}", parent=self.root)
            return
        tk.show_markdown(self.root, path.stem.replace("-", " ").title(), content)

    def _style_object_for_visual_editor(self):
        try:
            raw = json.loads(self.style_editor.get_text())
            return resolve_style(raw)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            messagebox.showerror(
                "Visual Theme Editor",
                f"Fix the style configuration before opening the visual editor:\n{error}",
                parent=self.root,
            )
            return None

    def _apply_visual_style(self, style_values):
        content = json.dumps(style_values, ensure_ascii=False, indent=2) + "\n"
        self.style_editor.set_text(content)
        self.style_editor.dirty = True
        self.style_buffer = content
        self._update_tab_labels()
        self.analyze_document("style")
        self.notebook.select(self.style_editor)
        self.set_status("Visual theme changes are ready in style.json. Save the tab or use Save All to keep them.")

    def open_visual_theme_editor(self):
        from editor_theme import VisualThemeEditor

        style_values = self._style_object_for_visual_editor()
        if style_values is None:
            return
        dialog = VisualThemeEditor(self.root, style_values, self.project_root)
        if dialog.exec() == tk.QtWidgets.QDialog.DialogCode.Accepted:
            self._apply_visual_style(dialog.style_values)

    def import_theme_preset(self):
        selected = filedialog.askopenfilename(
            title="Import theme preset",
            initialdir=self.project_root,
            filetypes=(("VN style presets", "*.vnstyle *.json"), ("All files", "*")),
            parent=self.root,
        )
        if not selected:
            return
        try:
            raw = json.loads(Path(selected).read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("style"), dict):
                raw = raw["style"]
            resolve_style(raw)
            current_style = self._style_object_for_visual_editor()
            if current_style is None:
                return
            style_values = resolve_style(merge_style(current_style, raw))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            messagebox.showerror("Import Theme Preset", f"Could not import this preset:\n{error}", parent=self.root)
            return
        self._apply_visual_style(style_values)

    def export_theme_preset(self):
        style_values = self._style_object_for_visual_editor()
        if style_values is None:
            return
        selected = filedialog.asksaveasfilename(
            title="Export reusable theme preset",
            initialdir=self.project_root,
            initialfile=f"{self.project_root.name}-theme.vnstyle",
            defaultextension=".vnstyle",
            filetypes=(("VN style preset", "*.vnstyle"), ("JSON", "*.json")),
            parent=self.root,
        )
        if not selected:
            return
        try:
            Path(selected).write_text(
                json.dumps({"format": "vn-style-preset", "version": 1, "style": style_values}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        except OSError as error:
            messagebox.showerror("Export Theme Preset", f"Could not write the preset:\n{error}", parent=self.root)
            return
        self.set_status(f"Exported reusable theme preset to {selected}")

    def choose_project(self):
        selected = filedialog.askdirectory(title="Choose VN Engine project folder", initialdir=self.project_root)
        if selected:
            if not self._confirm_discard_or_save("switching projects"):
                return
            self.load_project(Path(selected))

    def open_file(self):
        selected = filedialog.askopenfilename(
            title="Open story YAML file",
            initialdir=self._story_data_dir(),
            filetypes=(("Story YAML", "*.yaml *.yml"), ("All files", "*")),
            parent=self.root,
        )
        if not selected:
            return
        path = Path(selected).expanduser().resolve()
        if path.suffix.casefold() not in {".yaml", ".yml"}:
            messagebox.showerror("Open Story File", "Choose a .yaml or .yml story file.", parent=self.root)
            return
        editor = self.story_editors.get(path)
        if editor is not None:
            if str(editor) not in self.notebook.tabs():
                self.notebook.add(editor, text=self._story_tab_label(path, editor.dirty))
            self.notebook.select(editor)
            return
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Open Story File", f"Could not read {path}:\n{error}", parent=self.root)
            return
        editor = CodeEditor(self.notebook, self, "story")
        editor.story_path = path
        editor.set_text(content)
        self.story_editors[path] = editor
        self.notebook.add(editor, text=self._story_tab_label(path))
        self.notebook.select(editor)
        self.analyze_document("story")
        self.set_status(f"Opened {path}")

    def close_active_tab(self):
        selected = self.notebook.select()
        if selected:
            self.close_tab(self.notebook.nametowidget(selected))

    def close_tab(self, editor):
        if editor in {self.story_editor, self.project_editor, self.style_editor}:
            self.set_status("The project story, project settings, and style tabs stay open.")
            return
        path = next((path for path, candidate in self.story_editors.items() if candidate is editor), None)
        if path is None:
            return
        if editor.dirty:
            answer = messagebox.askyesnocancel(
                APP_TITLE,
                f"Save changes to {path.name} before closing this tab?",
                parent=self.root,
            )
            if answer is None:
                return
            if answer:
                try:
                    self._write_story_editor(editor)
                except OSError as error:
                    messagebox.showerror(APP_TITLE, f"Could not save {path}:\n{error}", parent=self.root)
                    return
        self.notebook.forget(editor)
        self.story_editors.pop(path, None)
        self._document_analysis_cache["story"].pop(id(editor), None)
        editor.destroy()
        self._update_tab_labels()
        if self.active_kind() == "story":
            self.analyze_document("story")

    def load_project(self, root: Path):
        if self._initial_project_load_job is not None:
            self.root.after_cancel(self._initial_project_load_job)
            self._initial_project_load_job = None
        self._project_load_generation += 1
        generation = self._project_load_generation
        self._project_load_pending = True
        self._included_story_load_queue = []
        if self._included_story_load_job is not None:
            self.root.after_cancel(self._included_story_load_job)
            self._included_story_load_job = None
        for kind in self._analysis_revisions:
            self._analysis_revisions[kind] += 1
            self._document_analysis_cache[kind].clear()
            pending_analysis = self._analysis_jobs.pop(kind, None)
            if pending_analysis is not None:
                self.root.after_cancel(pending_analysis)
        requested_root = Path(root)
        self.set_status("Loading project files in the background…")
        self.root.run_in_background(
            lambda: self._prepare_project_snapshot(requested_root),
            lambda snapshot, error: self._finish_project_load(generation, snapshot, error),
        )

    def _prepare_project_snapshot(self, requested_root: Path):
        """Read project files and resolve included stories without touching Qt widgets."""
        project_root = project_root_from(requested_root)
        project_file = project_root / "data" / "project.json"
        style_file = project_root / "data" / "style.json"
        _ensure_project_structure(project_root)
        load_errors = []

        raw_project = None
        raw_project_text = ""
        project_parse_failed = False
        project_buffer = ""
        project_dirty = False
        if project_file.is_file():
            try:
                raw_project_text = project_file.read_text(encoding="utf-8")
                raw_project = json.loads(raw_project_text) if raw_project_text.strip() else {}
            except json.JSONDecodeError:
                project_buffer = raw_project_text
                project_parse_failed = True
            except OSError as error:
                load_errors.append(f"Could not read project.json: {error}")
        if not isinstance(raw_project, dict) or raw_project == {}:
            raw_project = deepcopy(DEFAULT_PROJECT)
            if not project_parse_failed:
                project_buffer = json.dumps(raw_project, ensure_ascii=False, indent=2) + "\n"
                project_dirty = True

        clean_project, legacy_style = split_style_from_project(raw_project)
        has_legacy_style = clean_project != raw_project
        if has_legacy_style:
            project_buffer = json.dumps(clean_project, ensure_ascii=False, indent=2) + "\n"
            project_dirty = True
        elif not project_parse_failed and raw_project_text.strip() and isinstance(raw_project, dict):
            project_buffer = raw_project_text

        style_text = ""
        raw_style = None
        style_exists = style_file.is_file()
        if style_exists:
            try:
                style_text = style_file.read_text(encoding="utf-8")
                raw_style = json.loads(style_text) if style_text.strip() else {}
            except (OSError, json.JSONDecodeError) as error:
                style_text = style_text or "{}\n"
                load_errors.append(f"Could not read style.json: {error}")
        if isinstance(raw_style, dict):
            _clean_again, effective_style = split_style_from_project(raw_project, raw_style)
        else:
            effective_style = legacy_style
        style_dirty = not style_exists or has_legacy_style
        if style_dirty:
            style_buffer = json.dumps(effective_style, ensure_ascii=False, indent=2) + "\n"
        elif style_text:
            style_buffer = style_text
        else:
            style_buffer = json.dumps(DEFAULT_STYLE, ensure_ascii=False, indent=2) + "\n"
            style_dirty = True

        values = clean_project if isinstance(clean_project, dict) else DEFAULT_PROJECT
        paths = values.get("paths", {}) if isinstance(values.get("paths", {}), dict) else {}
        data_dir = AssetCatalog._resolve_path(paths.get("data", "data"), project_root)
        story_name = values.get("story", "story.yaml")
        story_file = Path(story_name) if isinstance(story_name, str) else Path("story.yaml")
        if not story_file.is_absolute():
            story_file = (data_dir / story_file).resolve()

        story_dirty = not story_file.is_file()
        try:
            story_buffer = story_file.read_text(encoding="utf-8") if story_file.is_file() else _starter_story_content()
        except OSError as error:
            story_buffer = _starter_story_content()
            story_dirty = True
            load_errors.append(f"Could not read {story_file}: {error}")

        included_stories = {}
        if yaml is not None:
            pending = [(story_file, story_buffer)]
            visited = set()
            while pending:
                parent_path, content = pending.pop()
                parent_path = parent_path.resolve()
                if parent_path in visited:
                    continue
                visited.add(parent_path)
                try:
                    document = yaml.safe_load(content)
                except Exception:
                    continue
                if not isinstance(document, dict) or not isinstance(document.get("includes", []), list):
                    continue
                for include in document.get("includes", []):
                    if not isinstance(include, str) or not include.strip():
                        continue
                    relative = Path(include.replace("\\", "/"))
                    if relative.is_absolute():
                        continue
                    child_path = (parent_path.parent / relative).resolve()
                    try:
                        child_path.relative_to(data_dir.resolve())
                    except ValueError:
                        continue
                    if child_path == story_file.resolve():
                        pending.append((child_path, story_buffer))
                        continue
                    child = included_stories.get(child_path)
                    if child is None:
                        try:
                            child_content = child_path.read_text(encoding="utf-8")
                            child_dirty = False
                        except OSError:
                            child_content = "# Add dialogue content here.\ndialogues: {}\n"
                            child_dirty = True
                        child = (child_content, child_dirty)
                        included_stories[child_path] = child
                    pending.append((child_path, child[0]))

        return {
            "project_root": project_root,
            "project_file": project_file,
            "style_file": style_file,
            "project_buffer": project_buffer,
            "style_buffer": style_buffer,
            "story_file": story_file,
            "story_buffer": story_buffer,
            "project_dirty": project_dirty,
            "style_dirty": style_dirty,
            "story_dirty": story_dirty,
            "included_stories": included_stories,
            "load_errors": load_errors,
        }

    def _finish_project_load(self, generation, snapshot, error):
        if generation != self._project_load_generation:
            return
        if error is not None:
            self._project_load_pending = False
            self.set_status(f"Could not load project: {error}")
            return
        if any(editor.dirty for editor in self.story_editors.values()) or self.project_editor.dirty or self.style_editor.dirty:
            if not messagebox.askyesno(
                "Project Load",
                "Discard edits made while the project was loading?",
                parent=self.root,
            ):
                self._project_load_pending = False
                self.set_status("Project load canceled; your edits were kept.")
                return
        try:
            self._apply_project_snapshot(snapshot)
        except Exception as apply_error:
            self._loading = False
            self._project_load_pending = False
            self.set_status(f"Could not finish loading project: {apply_error}")

    def _apply_project_snapshot(self, snapshot):
        self._loading = True
        for kind in self._analysis_revisions:
            self._analysis_revisions[kind] += 1
            self._document_analysis_cache[kind].clear()
            pending_analysis = self._analysis_jobs.pop(kind, None)
            if pending_analysis is not None:
                self.root.after_cancel(pending_analysis)
        self._clear_included_story_tabs()
        self.project_root = snapshot["project_root"]
        self.project_file = snapshot["project_file"]
        self.style_file = snapshot["style_file"]
        self.story_file = snapshot["story_file"]
        self.project_buffer = snapshot["project_buffer"]
        self.style_buffer = snapshot["style_buffer"]
        self.story_buffer = snapshot["story_buffer"]
        self.root.title(f"{APP_TITLE} — {self.project_root}")

        self.story_editor.set_text(self.story_buffer)
        self.story_editor.dirty = snapshot["story_dirty"]
        self.story_editor.story_path = self.story_file
        self.project_editor.set_text(self.project_buffer)
        self.project_editor.dirty = snapshot["project_dirty"]
        self.style_editor.set_text(self.style_buffer)
        self.style_editor.dirty = snapshot["style_dirty"]

        self.story_editors = {self.story_file: self.story_editor}
        self.live_diagnostics = {"story": [], "project": [], "style": []}
        self.engine_diagnostics = []
        self._loading = False
        self._update_tab_labels()
        self._refresh_markdown_tabs()
        self.refresh_asset_tree()
        self.render_diagnostics()
        self._included_story_load_queue = list(snapshot["included_stories"].items())
        generation = self._project_load_generation
        self.set_status(
            f"Loading {len(self._included_story_load_queue)} included story file(s)…"
            if self._included_story_load_queue
            else "Finishing project setup…"
        )
        self._included_story_load_job = self.root.after(
            0, lambda selected=generation, result=snapshot: self._load_included_story_batch(selected, result)
        )

    def _load_included_story_batch(self, generation, snapshot):
        self._included_story_load_job = None
        if generation != self._project_load_generation:
            return
        for _ in range(4):
            if not self._included_story_load_queue:
                break
            path, (content, dirty) = self._included_story_load_queue.pop(0)
            child_editor = CodeEditor(self.notebook, self, "story")
            child_editor.story_path = path
            child_editor.set_text(content)
            child_editor.dirty = dirty
            index = len(self.story_editors)
            self.story_editors[path] = child_editor
            self.notebook.insert(index, child_editor, text=self._story_tab_label(path, dirty))
        if self._included_story_load_queue:
            self.set_status(f"Loading {len(self._included_story_load_queue)} included story file(s)…")
            self._included_story_load_job = self.root.after(
                8, lambda selected=generation, result=snapshot: self._load_included_story_batch(selected, result)
            )
            return

        self._finish_included_story_load(snapshot)

    def _finish_included_story_load(self, snapshot):
        self._project_load_pending = False
        self._update_tab_labels()
        for delay, kind in enumerate(("story", "project", "style"), start=1):
            self.root.after(delay * 60, lambda selected=kind: self.analyze_document(selected))
        self.root.after(0, self._refresh_search_highlights)
        if snapshot["project_dirty"] or snapshot["style_dirty"]:
            status = "Project defaults are ready. Save All to write pending configuration changes."
        else:
            status = "Ready. Ctrl+Space shows suggestions; F5 runs the engine validator."
        if snapshot["load_errors"]:
            status += " " + " ".join(snapshot["load_errors"])
        self.set_status(status)
        try:
            _save_last_project(self.project_root)
        except OSError as error:
            self.set_status(f"Could not remember the last project folder: {error}")

    def _clear_included_story_tabs(self):
        if not self.story_editors:
            return
        for path, editor in list(self.story_editors.items()):
            if editor is self.story_editor:
                continue
            try:
                self.notebook.forget(editor)
                editor.destroy()
            except tk.TclError:
                pass
        if hasattr(self, "story_editor"):
            self.story_editors = {self.story_file: self.story_editor}

    def _story_data_dir(self):
        values = self._current_project_values()
        paths = values.get("paths", {}) if isinstance(values.get("paths", {}), dict) else {}
        return AssetCatalog._resolve_path(paths.get("data", "data"), self.project_root)

    def _story_tab_label(self, path, dirty=False):
        try:
            label = Path(path).relative_to(self._story_data_dir()).as_posix()
        except ValueError:
            label = Path(path).name
        return label + (" *" if dirty else "")

    def _story_source_label(self, path):
        try:
            return Path(path).resolve().relative_to(self._story_data_dir().resolve()).as_posix()
        except ValueError:
            return Path(path).name

    def _sync_included_story_tabs(self):
        if not hasattr(self, "notebook") or not hasattr(self, "story_editor"):
            return
        data_dir = self._story_data_dir().resolve()
        previously_open = dict(self.story_editors)
        desired = {self.story_file: self.story_editor}
        pending = [(self.story_file, self.story_editor.get_text())]
        visited = set()
        while pending:
            parent_path, content = pending.pop()
            parent_path = parent_path.resolve()
            if parent_path in visited:
                continue
            visited.add(parent_path)
            try:
                document = yaml.safe_load(content) if yaml is not None else None
            except Exception:
                continue
            if not isinstance(document, dict) or not isinstance(document.get("includes", []), list):
                continue
            for include in document.get("includes", []):
                if not isinstance(include, str) or not include.strip():
                    continue
                relative = Path(include.replace("\\", "/"))
                if relative.is_absolute():
                    continue
                child_path = (parent_path.parent / relative).resolve()
                try:
                    child_path.relative_to(data_dir)
                except ValueError:
                    continue
                child_editor = self.story_editors.get(child_path)
                if child_editor is None:
                    child_editor = CodeEditor(self.notebook, self, "story")
                    child_editor.story_path = child_path
                    if child_path.is_file():
                        try:
                            content = child_path.read_text(encoding="utf-8")
                            dirty = False
                        except OSError:
                            content, dirty = "# Add dialogue content here.\ndialogues: {}\n", True
                    else:
                        content, dirty = "# Add dialogue content here.\ndialogues: {}\n", True
                    child_editor.set_text(content)
                    child_editor.dirty = dirty
                desired[child_path] = child_editor
                try:
                    child_content = child_editor.get_text()
                except tk.TclError:
                    child_content = ""
                pending.append((child_path, child_content))

        # Keep tabs removed from `includes` open so their unsaved edits are not lost.
        orphaned = {
            path for path in previously_open
            if path not in desired and previously_open[path] is not self.story_editor
        }
        for path in orphaned:
            desired[path] = previously_open[path]

        selected_widget = None
        try:
            selected_widget = self.notebook.nametowidget(self.notebook.select())
        except (tk.TclError, KeyError):
            pass
        for path, editor in list(self.story_editors.items()):
            if editor is self.story_editor or path in desired:
                continue
            try:
                self.notebook.forget(editor)
                editor.destroy()
            except tk.TclError:
                pass
        self.story_editors = desired
        for index, (path, editor) in enumerate(desired.items()):
            editor.story_path = path
            label = self._story_tab_label(path, editor.dirty)
            if path in orphaned:
                label = f"{label} (not included)"
            try:
                if not self.notebook.tabs() or str(editor) not in self.notebook.tabs():
                    self.notebook.add(editor, text=label)
                self.notebook.insert(index, editor, text=label)
            except tk.TclError:
                continue
        if selected_widget is not None and str(selected_widget) in self.notebook.tabs():
            self.notebook.select(selected_widget)
        self._update_tab_labels()

    @staticmethod
    def _starter_story():
        return _starter_story_content()

    def _story_path_from(self, values):
        values = merge_defaults(DEFAULT_PROJECT, values if isinstance(values, dict) else {})
        paths = values.get("paths", {})
        data_path = paths.get("data", "data") if isinstance(paths, dict) else "data"
        data_dir = AssetCatalog._resolve_path(data_path, self.project_root)
        story_name = values.get("story", "story.yaml")
        story_path = Path(story_name) if isinstance(story_name, str) else Path("story.yaml")
        return story_path if story_path.is_absolute() else (data_dir / story_path).resolve()

    def _current_project_values(self):
        try:
            value = json.loads(self.project_editor.get_text())
            return merge_defaults(DEFAULT_PROJECT, value) if isinstance(value, dict) else DEFAULT_PROJECT
        except (json.JSONDecodeError, AttributeError):
            return DEFAULT_PROJECT

    def _current_style_values(self):
        try:
            value = json.loads(self.style_editor.get_text())
            return resolve_style(value) if isinstance(value, dict) else DEFAULT_STYLE
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            return DEFAULT_STYLE

    def _catalog(self):
        values = self._current_project_values()
        paths = values.get("paths", {}) if isinstance(values.get("paths", {}), dict) else {}
        key = (
            str(AssetCatalog._resolve_path(paths.get("assets", "assets"), self.project_root)),
            str(self.project_root / "engine" / "assets"),
        )
        if self._asset_catalog is None or self._asset_catalog_key != key:
            self._asset_catalog = AssetCatalog(self.project_root, values)
            self._asset_catalog_key = key
        return self._asset_catalog

    def refresh_asset_tree(self):
        self._asset_catalog = None
        self._asset_catalog_key = None
        for item in self.asset_tree.get_children(""):
            self.asset_tree.delete(item)
        values = self._current_project_values()
        paths = values.get("paths", {}) if isinstance(values.get("paths", {}), dict) else {}
        assets_dir = AssetCatalog._resolve_path(paths.get("assets", "assets"), self.project_root)
        roots = [
            ("Project assets", assets_dir),
            ("Engine built-in assets", self.project_root / "engine" / "assets"),
        ]
        for label, path in roots:
            iid = self.asset_tree.insert("", "end", text=label, open=False, values=("root", str(path), str(path)))
            if path.is_dir():
                self.asset_tree.insert(iid, "end", text="", values=("placeholder", "", str(path)))
            elif label == "Engine built-in assets":
                self._populate_builtin_tree(iid)
        self.asset_tree.tag_configure("folder", foreground="#b7c7e0")
        self.asset_tree.tag_configure("file", foreground="#d1d7df")

    def package_asset_addon(self):
        values = self._current_project_values()
        paths = values.get("paths", {}) if isinstance(values.get("paths", {}), dict) else {}
        assets_dir = AssetCatalog._resolve_path(paths.get("assets", "assets"), self.project_root)
        source = filedialog.askdirectory(
            title="Choose an add-on assets folder",
            initialdir=assets_dir if assets_dir.is_dir() else self.project_root,
            parent=self.root,
        )
        if not source:
            return
        source_path = Path(source)
        default_name = re.sub(r"[^a-z0-9-]+", "-", source_path.name.casefold()).strip("-") or "asset-pack"
        mods_folder = assets_dir / "mods"
        output_folder = mods_folder if mods_folder.is_dir() else assets_dir if assets_dir.is_dir() else self.project_root
        destination = filedialog.asksaveasfilename(
            title="Save add-on in project assets/mods",
            initialdir=output_folder,
            initialfile=f"{source_path.name}.vnmod",
            defaultextension=".vnmod",
            filetypes=(("VN asset add-on", "*.vnmod"),),
            parent=self.root,
        )
        if not destination:
            return
        try:
            output = build_asset_package(source_path, destination, mod_id=default_name)
        except (OSError, ValueError) as error:
            messagebox.showerror("Add-on Packaging Failed", str(error), parent=self.root)
            return
        self.refresh_asset_tree()
        try:
            Path(output).resolve().relative_to(mods_folder.resolve())
            install_note = "The game will load it from assets/mods when restarted."
        except ValueError:
            install_note = "Copy it into assets/mods to load it with this project."
        messagebox.showinfo(
            "Add-on Packaged",
            f"Created {output.name}. {install_note}",
            parent=self.root,
        )

    def _story_model_from_open_tabs(self):
        if yaml is None:
            raise ValueError("Install PyYAML to use localization and asset diagnostics.")
        root_editor = self.story_editors.get(self.story_file)
        if root_editor is None:
            root_editor = self.story_editor
        root_data = yaml.safe_load(root_editor.get_text())
        if not isinstance(root_data, dict):
            raise ValueError("The root story must be a YAML mapping.")
        merged = dict(root_data)
        merged_dialogues = dict(root_data.get("dialogues", {}))
        merged_variables = dict(root_data.get("variables", {}))
        for path, editor in self.story_editors.items():
            if path.resolve() == self.story_file.resolve():
                continue
            document = yaml.safe_load(editor.get_text())
            if not isinstance(document, dict):
                continue
            dialogues = document.get("dialogues", {})
            if isinstance(dialogues, dict):
                merged_dialogues.update(dialogues)
            variables = document.get("variables", {})
            if isinstance(variables, dict):
                merged_variables.update(variables)
        merged["dialogues"] = merged_dialogues
        if merged_variables:
            merged["variables"] = merged_variables
        return merged

    def _translation_ui_sources(self):
        sources = {key: label for label, key in UI_LABEL_KEYS.items()}
        values = self._current_project_values()
        messages = values.get("messages", {})
        if isinstance(messages, dict):
            sources.update({f"message.{key}": value for key, value in messages.items() if isinstance(value, str)})
        menus = values.get("menus", {})
        if isinstance(menus, dict):
            for menu_name in ("main", "pause", "settings"):
                menu = menus.get(menu_name, {})
                if not isinstance(menu, dict):
                    continue
                if isinstance(menu.get("title"), str):
                    sources[f"project.menus.{menu_name}.title"] = menu["title"]
                menu_items = menu.get("items", [])
                if isinstance(menu_items, list):
                    for index, item in enumerate(menu_items):
                        if not isinstance(item, dict):
                            continue
                        if isinstance(item.get("label"), str):
                            sources[f"project.menus.{menu_name}.items.{index}.label"] = item["label"]
                        if isinstance(item.get("detail"), str):
                            sources[f"project.menus.{menu_name}.items.{index}.detail"] = item["detail"]
            slots = menus.get("slots", {})
            if isinstance(slots, dict):
                for key in ("title_save", "title_load", "title_copy"):
                    if isinstance(slots.get(key), str):
                        sources[f"project.menus.slots.{key}"] = slots[key]
                labels = slots.get("labels", {})
                if isinstance(labels, dict):
                    for key, value in labels.items():
                        if isinstance(value, str):
                            sources[f"project.menus.slots.labels.{key}"] = value
                    sources.setdefault("project.menus.slots.labels.slot_custom", "Slot {slot}: {name}")
        return sources

    def export_translation_template(self):
        try:
            story = self._story_model_from_open_tabs()
            catalog = self._catalog()
            localization = story.get("localization", {})
            locales = localization.get("locales", {}) if isinstance(localization, dict) else {}
            locale = simpledialog.askstring(
                "Export Translation Template",
                "Target locale ID (declare it in localization.locales first):",
                parent=self.root,
            )
            if not locale:
                return
            if locale not in locales:
                messagebox.showerror("Translation Template", f"Locale {locale!r} is not declared in the root story.", parent=self.root)
                return
            destination = filedialog.asksaveasfilename(
                parent=self.root,
                title="Export Translation Template",
                initialdir=(catalog.data_dir / "locales") if (catalog.data_dir / "locales").is_dir() else catalog.data_dir,
                initialfile=f"{locale}.template.json",
                defaultextension=".json",
                filetypes=(("JSON", "*.json"),),
            )
            if not destination:
                return
            ui_sources = self._translation_ui_sources()
            template = translation_template(story, locale, ui_sources)
            Path(destination).write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.set_status(f"Exported translation template for {locale}.")
        except (OSError, ValueError, yaml.YAMLError if yaml is not None else ValueError) as error:
            messagebox.showerror("Translation Template", str(error), parent=self.root)

    def import_translation_catalog(self):
        try:
            story = self._story_model_from_open_tabs()
            catalog = self._catalog()
            source = filedialog.askopenfilename(
                parent=self.root,
                title="Import Translation Catalog",
                filetypes=(("JSON catalogs", "*.json"),),
            )
            if not source:
                return
            raw_catalog = json.loads(Path(source).read_text(encoding="utf-8"))
            locale = raw_catalog.get("locale") if isinstance(raw_catalog, dict) else None
            locales = story.get("localization", {}).get("locales", {})
            if not isinstance(locale, str) or re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", locale) is None or locale not in locales:
                messagebox.showerror("Translation Catalog", f"Locale {locale!r} is not declared in the root story.", parent=self.root)
                return
            data_root = catalog.data_dir.resolve()
            locale_dir = (data_root / "locales").resolve()
            locale_dir.relative_to(data_root)
            locale_dir.mkdir(parents=True, exist_ok=True)
            destination = (locale_dir / f"{locale}.json").resolve()
            destination.relative_to(locale_dir)
            if destination.exists() and not messagebox.askyesno(
                "Replace Translation Catalog",
                f"Replace the existing catalog at {destination}?",
                parent=self.root,
            ):
                return
            write_catalog(destination, raw_catalog, locale)
            self.set_status(f"Imported {locale} catalog to data/locales/{locale}.json.")
            self.analyze_document("story")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("Translation Catalog", str(error), parent=self.root)

    def show_translation_preview(self):
        try:
            story = self._story_model_from_open_tabs()
            catalog = self._catalog()
            locales = story.get("localization", {}).get("locales", {})
            locale = simpledialog.askstring(
                "Translation Preview",
                "Locale ID to compare:",
                initialvalue=next((key for key in locales if key != story.get("localization", {}).get("default_locale")), story.get("localization", {}).get("default_locale", "en")),
                parent=self.root,
            )
            if not locale:
                return
            if locale not in locales:
                raise ValueError(f"Locale {locale!r} is not declared in the root story.")
            path = catalog.data_dir / "locales" / f"{locale}.json"
            loaded = load_catalog(path, locale) if path.is_file() else {"strings": {}, "ui": {}}
            rows = catalog_report(story, locale, loaded)
            ui_sources = self._translation_ui_sources()
            for key, source in ui_sources.items():
                value = loaded.get("ui", {}).get(key, "")
                rows.append({
                    "key": f"ui.{key}", "source": source, "translation": value,
                    "missing": not bool(value.strip()), "source_chars": len(source),
                    "translation_chars": len(value),
                    "expansion": round(len(value) / max(1, len(source)), 2),
                })
            missing = sum(row["missing"] for row in rows)
            rtl = locale.split("-", 1)[0].casefold() in {"ar", "fa", "he", "ur", "ps", "sd", "ug", "yi"}
            window = tk.Toplevel(self.root)
            window.title(f"Translation Preview — {locale}")
            window.geometry("980x680")
            toolbar = ttk.Frame(window, padding=8)
            toolbar.pack(fill="x")
            direction = "right-aligned RTL preview" if rtl else "left-aligned LTR preview"
            ttk.Label(toolbar, text=f"{missing} missing of {len(rows)} strings · {direction}").pack(side="left")
            preview_body = ttk.Frame(window)
            preview_body.pack(fill="both", expand=True)
            content = tk.Text(preview_body, wrap="word", font=("Segoe UI", 10), padx=12, pady=10)
            scroll = ttk.Scrollbar(preview_body, orient="vertical", command=content.yview)
            content.configure(yscrollcommand=scroll.set)
            content.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            content.tag_configure("rtl", justify="right")
            content.tag_configure("ltr", justify="left")
            for row in rows:
                status = "MISSING" if row["missing"] else f"{row['expansion']:.2f}× length"
                content.insert("end", f"{status} · {row['key']}\n", "rtl" if rtl else "ltr")
                content.insert("end", f"Source ({row['source_chars']} chars): {row['source']}\n", "rtl" if rtl else "ltr")
                content.insert("end", f"Preview ({row['translation_chars']} chars): {row['translation']}\n\n", "rtl" if rtl else "ltr")
            content.configure(state="disabled")
        except (OSError, ValueError, yaml.YAMLError if yaml is not None else ValueError) as error:
            messagebox.showerror("Translation Preview", str(error), parent=self.root)

    def show_asset_diagnostics(self):
        try:
            story = self._story_model_from_open_tabs()
            catalog = self._catalog()
            report = self._build_asset_diagnostics(story, catalog)
            window = tk.Toplevel(self.root)
            window.title("Asset Diagnostics")
            window.geometry("900x620")
            content = tk.Text(window, wrap="word", font=("Consolas", 10), padx=12, pady=10)
            scroll = ttk.Scrollbar(window, orient="vertical", command=content.yview)
            content.configure(yscrollcommand=scroll.set)
            content.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            content.insert("1.0", "\n".join(report))
            content.configure(state="disabled")
        except (OSError, ValueError, yaml.YAMLError if yaml is not None else ValueError) as error:
            messagebox.showerror("Asset Diagnostics", str(error), parent=self.root)

    def run_playthrough_suite(self):
        suite_path = filedialog.askopenfilename(
            parent=self.root,
            title="Run Playthrough Suite",
            initialdir=self.project_root,
            filetypes=(("VN Playthrough Suites", "*.vnplay.json"), ("JSON files", "*.json")),
        )
        if not suite_path:
            return
        if not self.save_all():
            return
        try:
            from engine.playthrough import run_suite

            results = run_suite(self.project_root, Path(suite_path))
            passed = sum(result["passed"] for result in results)
            window = tk.Toplevel(self.root)
            window.title(f"Playthrough Results — {passed}/{len(results)} passed")
            window.geometry("850x540")
            content = tk.Text(window, wrap="word", font=("Consolas", 10), padx=12, pady=10)
            scroll = ttk.Scrollbar(window, orient="vertical", command=content.yview)
            content.configure(yscrollcommand=scroll.set)
            content.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            for result in results:
                label = "PASS" if result["passed"] else "FAIL"
                content.insert("end", f"{label}: {result['name']}\n")
                content.insert("end", f"  {result.get('error', result.get('outcome', {}))}\n\n")
            content.configure(state="disabled")
        except Exception as error:
            messagebox.showerror("Playthrough Suite", str(error), parent=self.root)

    def _build_asset_diagnostics(self, story, catalog):
        notes = []
        references = {"images": set(), "sounds": set(), "music": set(), "fonts": set(), "characters": set()}

        def add_reference(category, value):
            if isinstance(value, str) and value.strip():
                references[category].add(value.replace("\\", "/").casefold())

        for dialogue in story.get("dialogues", {}).values():
            if not isinstance(dialogue, dict):
                continue
            add_reference("sounds", dialogue.get("voice"))
            text_value = dialogue.get("text", "")
            if isinstance(text_value, dict):
                text_value = " ".join(value for value in text_value.values() if isinstance(value, str))
            if isinstance(text_value, str):
                for match in re.findall(r"%([^%]+)%", text_value):
                    add_reference("images", match)
                for match in re.findall(r"§([^§]+)§", text_value):
                    add_reference("sounds", match)
            for action in dialogue.get("actions", []):
                if not isinstance(action, dict):
                    continue
                action_type = action.get("type")
                if action_type in {"background", "unlock_cg"}:
                    add_reference("images", action.get("image"))
                elif action_type in {"music", "unlock_music"}:
                    add_reference("music", action.get("track"))
                elif action_type == "sound":
                    add_reference("sounds", action.get("name"))
                elif action_type in {"show_character", "animate_character", "hide_character"}:
                    add_reference("characters", action.get("name"))
        for character in story.get("character_defaults", {}):
            add_reference("characters", character)
        for dialogue in story.get("dialogues", {}).values():
            if isinstance(dialogue, dict):
                add_reference("characters", dialogue.get("speaker"))
                add_reference("characters", dialogue.get("active_character"))

        project_values = self._current_project_values()
        style_values = self._current_style_values()
        for key in ("icon",):
            add_reference("images", project_values.get(key))
        intro = style_values.get("intro", {})
        if isinstance(intro, dict):
            for key in ("credit_image", "warning_image", "headphones_image"):
                add_reference("images", intro.get(key))
        theme = style_values.get("theme", {})
        if isinstance(theme, dict):
            textbox = theme.get("textbox", {})
            if isinstance(textbox, dict):
                add_reference("images", textbox.get("background"))
            menu = theme.get("menu", {})
            if isinstance(menu, dict):
                add_reference("images", menu.get("background"))
                for screen in menu.get("screens", {}).values() if isinstance(menu.get("screens", {}), dict) else []:
                    if isinstance(screen, dict):
                        add_reference("images", screen.get("background"))
            for font_group in ("fonts", "game_fonts"):
                values = theme.get(font_group, {})
                if isinstance(values, dict):
                    for font_name in values.values():
                        add_reference("fonts", font_name)
            for sound in theme.get("sounds", {}).values() if isinstance(theme.get("sounds", {}), dict) else []:
                add_reference("sounds", sound)
            choice_buttons = theme.get("choice_buttons", {})
            if isinstance(choice_buttons, dict):
                for key in ("normal", "hovered"):
                    add_reference("images", choice_buttons.get(key))
            pause_button = theme.get("pause_button", {})
            if isinstance(pause_button, dict):
                add_reference("images", pause_button.get("image"))

        files_by_category = {category: [] for category in references}
        for category in files_by_category:
            root = catalog.assets_dir / category
            if root.is_dir():
                try:
                    files_by_category[category] = sorted(
                        (path for path in root.rglob("*") if path.is_file() and not path.is_symlink()),
                        key=lambda path: path.as_posix().casefold(),
                    )
                except OSError as error:
                    notes.append(f"Could not scan {root}: {error}")
        duplicates = []
        unused = []
        for category, paths in files_by_category.items():
            names = {}
            for path in paths:
                relative = path.relative_to(catalog.assets_dir / category).as_posix()
                normalized = relative.casefold()
                stem_key = Path(relative).stem.casefold()
                names.setdefault(stem_key, []).append(path)
                try:
                    file_size = path.stat().st_size
                except OSError as error:
                    notes.append(f"Could not inspect asset {category}/{relative}: {error}")
                    continue
                if file_size > 10 * 1024 * 1024:
                    notes.append(f"Large asset ({file_size / (1024 * 1024):.1f} MB): {category}/{relative}")
                if category == "images":
                    dimensions = self._read_image_dimensions(path)
                    if dimensions and max(dimensions) > 4096:
                        notes.append(f"Large image dimensions ({dimensions[0]}×{dimensions[1]}): images/{relative}")
                candidates = {normalized, stem_key, Path(relative).name.casefold(), Path(relative).stem.casefold()}
                if category == "characters":
                    is_used = Path(relative).parts[0].casefold() in references[category]
                else:
                    is_used = any(
                        ref in candidates
                        or ref.endswith("/" + normalized)
                        or ref.endswith("/" + Path(relative).name.casefold())
                        for ref in references[category]
                    )
                if not is_used:
                    unused.append(f"{category}/{relative}")
            for stem, matching in names.items():
                if len(matching) > 1:
                    duplicates.append(f"{category}/{stem}: " + ", ".join(path.name for path in matching))

        mod_members = {}
        mod_asset_details = []
        mods_dir = catalog.assets_dir / "mods"
        if mods_dir.is_dir():
            for package_path in sorted(mods_dir.glob("*.vnmod"), key=lambda path: path.name.casefold()):
                try:
                    with ZipFile(package_path) as archive:
                        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                        if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
                            notes.append(f"Invalid add-on manifest: {package_path.name}")
                            continue
                        for info in archive.infolist():
                            if info.is_dir():
                                continue
                            member = PurePosixPath(info.filename.replace("\\", "/"))
                            if member.is_absolute() or ".." in member.parts:
                                notes.append(f"Unsafe package member ignored: {package_path.name}:{info.filename}")
                                continue
                            if len(member.parts) >= 3 and member.parts[0] == "assets" and member.parts[1] in files_by_category:
                                category = member.parts[1]
                                relative_name = "/".join(member.parts[2:])
                                asset_name = f"{category}/{relative_name}".casefold()
                                mod_members.setdefault(asset_name, []).append(package_path.name)
                                mod_asset_details.append({
                                    "category": category,
                                    "relative": relative_name,
                                    "package": package_path.name,
                                    "size": info.file_size,
                                })
                                if info.file_size > 10 * 1024 * 1024:
                                    notes.append(f"Large packaged asset ({info.file_size / (1024 * 1024):.1f} MB): {package_path.name}:{asset_name}")
                                if category == "images":
                                    try:
                                        with archive.open(info) as stream:
                                            header = stream.read(30)
                                        dimensions = self._read_image_dimensions_from_header(header)
                                        if dimensions is None and header[:2] == b"\xff\xd8":
                                            with archive.open(info) as stream:
                                                stream.seek(2)
                                                dimensions = self._read_jpeg_dimensions(stream)
                                        if dimensions and max(dimensions) > 4096:
                                            notes.append(f"Large packaged image ({dimensions[0]}×{dimensions[1]}): {package_path.name}:{asset_name}")
                                    except (OSError, struct.error):
                                        pass
                except (OSError, ValueError, KeyError, UnicodeDecodeError, BadZipFile) as error:
                    notes.append(f"Could not load add-on {package_path.name}: {error}")
        conflicts = [f"{asset}: {', '.join(packages)}" for asset, packages in mod_members.items() if len(packages) > 1]
        for asset, packages in mod_members.items():
            if (catalog.assets_dir / asset).is_file():
                conflicts.append(f"{asset}: project asset wins over {', '.join(packages)}")
        unused_addon_assets = []
        for item in mod_asset_details:
            relative = item["relative"]
            category = item["category"]
            normalized = relative.casefold()
            stem_key = PurePosixPath(relative).with_suffix("").as_posix().casefold()
            candidates = {normalized, stem_key, PurePosixPath(relative).name.casefold(), PurePosixPath(relative).stem.casefold()}
            if category == "characters":
                used = PurePosixPath(relative).parts[0].casefold() in references[category]
            else:
                used = any(ref in candidates or ref.endswith("/" + normalized) for ref in references[category])
            if not used:
                unused_addon_assets.append(f"{item['package']}:{category}/{relative}")
        counts = sum(len(items) for items in files_by_category.values())
        report = [f"Scanned {counts} project asset files.", ""]
        all_unused = unused + unused_addon_assets
        report.append("UNUSED ASSETS" if all_unused else "UNUSED ASSETS: none detected")
        report.extend(f"  {item}" for item in all_unused)
        report.extend(["", "DUPLICATE ASSET NAMES" if duplicates else "DUPLICATE ASSET NAMES: none detected"])
        report.extend(f"  {item}" for item in duplicates)
        report.extend(["", "MOD / ASSET CONFLICTS" if conflicts else "MOD / ASSET CONFLICTS: none detected"])
        report.extend(f"  {item}" for item in conflicts)
        report.extend(["", "SIZE AND LOAD DIAGNOSTICS" if notes else "SIZE AND LOAD DIAGNOSTICS: none detected"])
        report.extend(f"  {item}" for item in notes)
        report.append("\nUnused checks use story dialogue, choice actions, and character IDs; dynamic asset names may need manual review.")
        return report

    def _read_image_dimensions(self, path):
        try:
            with Path(path).open("rb") as stream:
                header = stream.read(30)
                if header[:2] == b"\xff\xd8":
                    stream.seek(2)
                    return self._read_jpeg_dimensions(stream)
                return self._read_image_dimensions_from_header(header)
        except (OSError, struct.error, OverflowError, ValueError):
            return None

    @staticmethod
    def _read_jpeg_dimensions(stream):
        while True:
            prefix = stream.read(1)
            if not prefix:
                return None
            if prefix != b"\xff":
                continue
            marker = stream.read(1)
            while marker == b"\xff":
                marker = stream.read(1)
            if not marker:
                return None
            value = marker[0]
            if value in {0xD8, 0xD9, 0x01} or 0xD0 <= value <= 0xD7:
                continue
            length_data = stream.read(2)
            if len(length_data) != 2:
                return None
            length = int.from_bytes(length_data, "big")
            if length < 2:
                return None
            if value in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                frame = stream.read(5)
                if len(frame) != 5:
                    return None
                height, width = struct.unpack(">HH", frame[1:5])
                return width, height
            stream.seek(length - 2, os.SEEK_CUR)

    @staticmethod
    def _read_image_dimensions_from_header(header):
        if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
            return struct.unpack(">II", header[16:24])
        if header[:6] in {b"GIF87a", b"GIF89a"} and len(header) >= 10:
            return struct.unpack("<HH", header[6:10])
        if header.startswith(b"BM") and len(header) >= 26:
            width, height = struct.unpack("<ii", header[18:26])
            return abs(width), abs(height)
        if header[:4] == b"RIFF" and header[8:12] == b"WEBP" and header[12:16] == b"VP8X" and len(header) >= 30:
            width = 1 + int.from_bytes(header[24:27], "little")
            height = 1 + int.from_bytes(header[27:30], "little")
            return width, height
        return None

    def _populate_builtin_tree(self, parent):
        static = {
            "fonts": sorted(BUILTIN_ASSETS["font"]),
            "images": sorted(BUILTIN_ASSETS["image"]),
            "sounds": sorted(BUILTIN_ASSETS["sound"]),
            "music": [],
            "characters": [],
        }
        for folder, names in static.items():
            folder_iid = self.asset_tree.insert(parent, "end", text=folder, open=False, values=("virtual-folder", folder, ""), tags=("folder",))
            for name in names:
                self.asset_tree.insert(folder_iid, "end", text=name, values=("builtin-file", f"{folder}/{name}", ""), tags=("file",))

    def _on_tree_open(self, _event=None):
        iid = self.asset_tree.focus()
        self._populate_tree_node(iid)

    def _populate_tree_node(self, iid):
        values = self.asset_tree.item(iid, "values")
        if not values or values[0] not in {"root", "directory"}:
            return
        path = Path(values[1])
        children = self.asset_tree.get_children(iid)
        if children and self.asset_tree.item(children[0], "values")[0] != "placeholder":
            return
        for child in children:
            self.asset_tree.delete(child)
        try:
            entries = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith(".") or entry.name == "__pycache__":
                continue
            if entry.is_dir():
                child_id = self.asset_tree.insert(iid, "end", text=entry.name, values=("directory", str(entry), values[2]), tags=("folder",))
                self.asset_tree.insert(child_id, "end", text="", values=("placeholder", "", values[2]))
            elif entry.is_file():
                self.asset_tree.insert(iid, "end", text=entry.name, values=("file", str(entry), values[2]), tags=("file",))

    def insert_selected_asset(self):
        selection = self.asset_tree.selection()
        if not selection:
            return
        values = self.asset_tree.item(selection[0], "values")
        if not values or values[0] not in {"file", "builtin-file"}:
            return
        kind, source, root_value = values
        if kind == "builtin-file":
            reference = source
        else:
            file_path = Path(source)
            root = Path(root_value)
            try:
                reference = file_path.relative_to(root).as_posix()
            except ValueError:
                reference = file_path.name
            if reference.startswith("characters/"):
                reference = file_path.stem
        editor = self.active_editor()
        if editor is None:
            self.set_status("Select a story, project, or style tab before inserting an asset reference.")
            return
        editor.text.insert("insert", reference)
        editor.text.focus_set()
        self.set_status(f"Inserted asset reference: {reference}")

    def show_add_menu(self):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Dialogue", command=self._add_dialogue_block)
        menu.add_command(label="Dialogue Text", command=self._add_dialogue_text)
        menu.add_command(label="Choice Option", command=self._add_choice_option)
        menu.add_separator()
        menu.add_command(label="Story Variable", command=self._add_story_variable)
        menu.add_command(label="Input Action (with variable)", command=self._add_input_action)
        try:
            menu.tk_popup(self.add_button.winfo_rootx(), self.add_button.winfo_rooty() + self.add_button.winfo_height())
        finally:
            menu.grab_release()

    def _active_story_editor(self):
        editor = self.active_editor()
        if editor is None or editor.document_kind != "story":
            self.set_status("Select a story YAML tab before using Add.")
            return None
        return editor

    @staticmethod
    def _insert_yaml_lines(editor, line_index, lines):
        text_widget = editor.text
        current = editor.get_text()
        existing_lines = current.splitlines()
        insertion = "\n".join(lines) + "\n"
        if line_index < len(existing_lines):
            start_index = f"{line_index + 1}.0"
        else:
            prefix = "\n" if current and not current.endswith("\n") else ""
            start_index = "end-1c"
            insertion = prefix + "\n" + insertion
        text_widget.mark_set("insert", start_index)
        text_widget.insert("insert", insertion)
        text_widget.focus_set()
        text_widget.see("insert")

    def _dialogue_context_at_cursor(self, editor):
        lines = editor.get_text().splitlines()
        cursor_line = int(editor.text.index("insert").split(".")[0]) - 1
        section_start = None
        section_indent = 0
        for index in range(min(cursor_line, len(lines) - 1), -1, -1):
            match = re.match(r"^(\s*)dialogues\s*:\s*(?:#.*)?$", lines[index])
            if match:
                section_start = index
                section_indent = len(match.group(1))
                break
        if section_start is None:
            return None
        dialogue_indent = section_indent + 2
        header_pattern = re.compile(rf"^ {{{dialogue_indent}}}([\w-]+)\s*:\s*(?:#.*)?$")
        dialogue_start = None
        dialogue_id = None
        for index in range(section_start + 1, min(cursor_line, len(lines) - 1) + 1):
            match = header_pattern.match(lines[index])
            if match:
                dialogue_start = index
                dialogue_id = match.group(1)
        if dialogue_start is None:
            return None
        dialogue_end = len(lines)
        for index in range(dialogue_start + 1, len(lines)):
            line = lines[index]
            if header_pattern.match(line):
                dialogue_end = index
                break
            if line.strip() and len(line) - len(line.lstrip()) <= section_indent:
                dialogue_end = index
                break
        return {
            "id": dialogue_id,
            "start": dialogue_start,
            "end": dialogue_end,
            "indent": dialogue_indent,
            "section_start": section_start,
            "section_indent": section_indent,
            "lines": lines,
        }

    def _story_section_end(self, editor, section_name):
        lines = editor.get_text().splitlines()
        section_start = next(
            (
                index for index, line in enumerate(lines)
                if re.match(rf"^{re.escape(section_name)}\s*:", line)
            ),
            None,
        )
        if section_start is None:
            return None, None, lines
        section_end = len(lines)
        for index in range(section_start + 1, len(lines)):
            if lines[index].strip() and not lines[index][0].isspace() and re.match(r"^[\w-]+\s*:", lines[index]):
                section_end = index
                break
        return section_start, section_end, lines

    @staticmethod
    def _unique_story_name(base, names):
        if base not in names:
            return base
        suffix = 2
        while f"{base}_{suffix}" in names:
            suffix += 1
        return f"{base}_{suffix}"

    def _add_dialogue_block(self):
        editor = self._active_story_editor()
        if editor is None:
            return
        section_start, section_end, lines = self._story_section_end(editor, "dialogues")
        if section_start is None:
            self.set_status("Add a top-level 'dialogues:' section first.")
            return
        _variables, dialogue_ids = self._story_context()
        dialogue_id = self._unique_story_name("new_dialogue", dialogue_ids)
        indent_match = re.match(r"^(\s*)dialogues\s*:", lines[section_start])
        node_indent = len(indent_match.group(1)) + 2
        field_indent = node_indent + 2
        self._insert_yaml_lines(
            editor,
            section_end,
            [
                " " * node_indent + f"{dialogue_id}:",
                " " * field_indent + "speaker: Narrator",
                " " * field_indent + 'text: "Write dialogue here."',
            ],
        )
        self.set_status(f"Added dialogue '{dialogue_id}'. Add a link or choice to make it reachable.")

    def _add_dialogue_text(self):
        editor = self._active_story_editor()
        if editor is None:
            return
        context = self._dialogue_context_at_cursor(editor)
        if context is None:
            self.set_status("Place the cursor inside a dialogue before adding its text field.")
            return
        field_indent = context["indent"] + 2
        text_field = re.compile(rf"^ {{{field_indent}}}text\s*:")
        text_line = next(
            (index for index in range(context["start"] + 1, context["end"])
             if text_field.match(context["lines"][index])),
            None,
        )
        replacement = "Write dialogue here."
        if text_line is None:
            self._insert_yaml_lines(
                editor,
                context["end"],
                [" " * field_indent + f"text: {json.dumps(replacement)}"],
            )
        else:
            line = context["lines"][text_line]
            colon = line.find(":")
            text_end = context["end"]
            for index in range(text_line + 1, context["end"]):
                child_line = context["lines"][index]
                if child_line.strip() and len(child_line) - len(child_line.lstrip()) <= field_indent:
                    text_end = index
                    break
            if text_end > text_line + 1:
                end_index = (
                    f"{text_end + 1}.0"
                    if text_end < len(context["lines"])
                    else "end-1c"
                )
                editor.text.delete(f"{text_line + 2}.0", end_index)
            editor.text.delete(f"{text_line + 1}.{colon + 1}", f"{text_line + 1}.end")
            editor.text.insert(f"{text_line + 1}.{colon + 1}", " " + json.dumps(replacement))
            editor.text.mark_set("insert", f"{text_line + 1}.{colon + 2}")
            editor.text.focus_set()
        self.set_status(f"Added dialogue text for '{context['id']}'.")

    def _add_choice_option(self):
        editor = self._active_story_editor()
        if editor is None:
            return
        context = self._dialogue_context_at_cursor(editor)
        if context is None:
            self.set_status("Place the cursor inside a dialogue before adding a choice.")
            return
        _variables, dialogue_ids = self._story_context()
        target = next((item for item in sorted(dialogue_ids) if item != context["id"]), context["id"])
        field_indent = context["indent"] + 2
        options_field = re.compile(rf"^ {{{field_indent}}}options\s*:")
        options_line = next(
            (index for index in range(context["start"] + 1, context["end"])
             if options_field.match(context["lines"][index])),
            None,
        )
        if options_line is None:
            lines = [
                " " * field_indent + "options:",
                " " * (field_indent + 2) + '- label: "New choice"',
                " " * (field_indent + 4) + f"target: {target}",
            ]
            self._insert_yaml_lines(editor, context["end"], lines)
        else:
            options_value = context["lines"][options_line].partition(":")[2].strip()
            if options_value not in {"", "[]"} and not options_value.startswith("#"):
                self.set_status("Use block-style options before adding an option.")
                return
            if options_value == "[]":
                editor.text.delete(f"{options_line + 1}.0", f"{options_line + 1}.end")
                editor.text.insert(f"{options_line + 1}.0", " " * field_indent + "options:")
            option_indent = field_indent + 2
            insert_line = context["end"]
            for index in range(options_line + 1, context["end"]):
                line = context["lines"][index]
                if line.strip() and len(line) - len(line.lstrip()) <= field_indent:
                    insert_line = index
                    break
            self._insert_yaml_lines(
                editor,
                insert_line,
                [
                    " " * option_indent + '- label: "New choice"',
                    " " * (option_indent + 2) + f"target: {target}",
                ],
            )
        self.set_status(f"Added a choice to '{context['id']}' targeting '{target}'.")

    def _ensure_story_variable(self, name):
        editor = self.story_editor
        source = editor.get_text()
        try:
            document = yaml.safe_load(source) if yaml is not None else None
        except Exception:
            document = None
        if not isinstance(document, dict):
            self.set_status("Could not add a variable while story YAML has syntax errors.")
            return False
        variables = document.get("variables", {})
        if isinstance(variables, dict) and name in variables:
            return True
        lines = source.splitlines()
        section_start, section_end, _lines = self._story_section_end(editor, "variables")
        if section_start is not None:
            header = lines[section_start]
            if header.partition(":")[2].strip().startswith("{"):
                variables[name] = None
                new_header = "variables: " + json.dumps(variables, ensure_ascii=False)
                editor.text.delete(f"{section_start + 1}.0", f"{section_start + 1}.end")
                editor.text.insert(f"{section_start + 1}.0", new_header)
                return True
            self._insert_yaml_lines(editor, section_end, [f"  {name}: null"])
            return True

        dialogues_start, _dialogues_end, _lines = self._story_section_end(editor, "dialogues")
        insert_at = dialogues_start if dialogues_start is not None else len(lines)
        self._insert_yaml_lines(
            editor,
            insert_at,
            ["variables:", f"  {name}: null", ""],
        )
        return True

    def _add_story_variable(self):
        editor = self._active_story_editor()
        if editor is None:
            return
        variables, _dialogues = self._story_context()
        name = self._unique_story_name("new_variable", set(variables))
        if self._ensure_story_variable(name):
            self.set_status(f"Added story variable '{name}' with a null starting value.")

    def _add_input_action(self):
        editor = self._active_story_editor()
        if editor is None:
            return
        context = self._dialogue_context_at_cursor(editor)
        if context is None:
            self.set_status("Place the cursor inside a dialogue before adding an input action.")
            return
        variables, _dialogues = self._story_context()
        variable_name = self._unique_story_name("player_input", set(variables))
        field_indent = context["indent"] + 2
        actions_field = re.compile(rf"^ {{{field_indent}}}actions\s*:")
        actions_line = next(
            (index for index in range(context["start"] + 1, context["end"])
             if actions_field.match(context["lines"][index])),
            None,
        )
        actions_value = ""
        if actions_line is not None:
            actions_value = context["lines"][actions_line].partition(":")[2].strip()
            if actions_value not in {"", "[]"} and not actions_value.startswith("#"):
                self.set_status("Use block-style actions before adding an input action.")
                return
            if any(
                re.match(r"^\s*-\s*type\s*:\s*input\b", context["lines"][index])
                for index in range(actions_line + 1, context["end"])
            ):
                self.set_status("This dialogue already has an input action; the story format allows one per dialogue.")
                return
        if not self._ensure_story_variable(variable_name):
            return
        if actions_line is None:
            action_indent = field_indent + 2
            self._insert_yaml_lines(
                editor,
                context["end"],
                [
                    " " * field_indent + "actions:",
                    " " * action_indent + "- type: input",
                    " " * (action_indent + 2) + f"var: {variable_name}",
                    " " * (action_indent + 2) + 'prompt: "Your answer"',
                    " " * (action_indent + 2) + "input_type: text",
                ],
            )
        else:
            if actions_value == "[]":
                editor.text.delete(f"{actions_line + 1}.0", f"{actions_line + 1}.end")
                editor.text.insert(f"{actions_line + 1}.0", " " * field_indent + "actions:")
            action_indent = field_indent + 2
            insert_line = context["end"]
            for index in range(actions_line + 1, context["end"]):
                line = context["lines"][index]
                if line.strip() and len(line) - len(line.lstrip()) <= field_indent:
                    insert_line = index
                    break
            self._insert_yaml_lines(
                editor,
                insert_line,
                [
                    " " * action_indent + "- type: input",
                    " " * (action_indent + 2) + f"var: {variable_name}",
                    " " * (action_indent + 2) + 'prompt: "Your answer"',
                    " " * (action_indent + 2) + "input_type: text",
                ],
            )
        self.set_status(f"Added input action to '{context['id']}' and declared '{variable_name}'.")

    def _on_tab_changed(self, _event=None):
        self.engine_diagnostics = []
        kind = self.active_kind()
        if kind in {"story", "project", "style"}:
            self.update_cursor_status()
            if self._tab_change_analysis_job is not None:
                self.root.after_cancel(self._tab_change_analysis_job)
            pending_analysis = self._analysis_jobs.pop(kind, None)
            if pending_analysis is not None:
                self.root.after_cancel(pending_analysis)
            self._tab_change_analysis_job = self.root.after(
                150, self._analyze_active_tab_after_change
            )
        else:
            if self._tab_change_analysis_job is not None:
                self.root.after_cancel(self._tab_change_analysis_job)
                self._tab_change_analysis_job = None
            self.render_diagnostics()
            path = self.markdown_paths.get(self.notebook.nametowidget(self.notebook.select()))
            self.set_status(f"Viewing {path.name if path else 'documentation'} (read-only). Ctrl+F searches this file.")
        self._refresh_search_highlights()

    def _analyze_active_tab_after_change(self):
        self._tab_change_analysis_job = None
        kind = self.active_kind()
        if kind in {"story", "project", "style"}:
            editor = self.active_editor()
            cached = self._document_analysis_cache[kind].get(id(editor))
            if cached is not None and cached[0] == self._analysis_revisions[kind]:
                self.live_diagnostics[kind] = list(cached[1])
                editor.highlight()
                self.render_diagnostics()
            else:
                self.analyze_document(kind)
            self.update_cursor_status()

    def active_kind(self):
        selected = self.notebook.select()
        if selected == str(self.project_editor):
            return "project"
        if selected == str(self.style_editor):
            return "style"
        if any(selected == str(editor) for editor in self.story_editors.values()):
            return "story"
        return "markdown"

    def active_editor(self):
        if self.active_kind() == "project":
            return self.project_editor
        if self.active_kind() == "style":
            return self.style_editor
        if self.active_kind() == "story":
            selected = self.notebook.select()
            return next((editor for editor in self.story_editors.values() if str(editor) == selected), self.story_editor)
        return None

    def active_text(self):
        editor = self.active_editor()
        if editor is not None:
            return editor.text
        try:
            frame = self.notebook.nametowidget(self.notebook.select())
        except tk.TclError:
            return None
        return self.markdown_texts.get(frame)

    def _edit_active(self, operation):
        editor = self.active_editor()
        if editor is None:
            return "break"
        try:
            if operation == "undo":
                editor.text.edit_undo()
            else:
                editor.text.edit_redo()
            editor.text.focus_set()
        except tk.TclError:
            self.set_status(f"Nothing to {operation}.")
        return "break"

    def show_find(self):
        if self.active_text() is None:
            return "break"
        if self.find_window is not None and self.find_window.winfo_exists():
            self.find_window.deiconify()
            self.find_window.lift()
            self.find_entry.focus_set()
            self.find_entry.select_range(0, "end")
            self._refresh_search_highlights()
            return "break"

        window = tk.Toplevel(self.root)
        self.find_window = window
        window.title("Find")
        window.geometry("520x120")
        window.transient(self.root)
        window.resizable(False, False)
        row = ttk.Frame(window, padding=10)
        row.pack(fill="x")
        ttk.Label(row, text="Find:").pack(side="left", padx=(0, 6))
        self.find_entry = ttk.Entry(row, width=38)
        self.find_entry.pack(side="left", fill="x", expand=True)
        self.find_entry.bind("<KeyRelease>", lambda _event: self._refresh_search_highlights())
        self.find_entry.bind("<Return>", lambda _event: self._find_next())
        self.find_entry.bind("<Shift-Return>", lambda _event: self._find_next(backwards=True))
        self.find_entry.bind("<Escape>", lambda _event: self.close_find())

        controls = ttk.Frame(window, padding=(10, 0, 10, 10))
        controls.pack(fill="x")
        self.find_case_sensitive = tk.BooleanVar(self.root, value=False)
        ttk.Checkbutton(
            controls, text="Case sensitive", variable=self.find_case_sensitive,
            command=self._refresh_search_highlights,
        ).pack(side="left")
        ttk.Button(controls, text="Previous", command=lambda: self._find_next(backwards=True)).pack(side="right")
        ttk.Button(controls, text="Next", command=self._find_next).pack(side="right", padx=(0, 5))
        ttk.Button(controls, text="Replace...", command=self._show_replace_dialog).pack(side="right", padx=(0, 5))
        ttk.Button(controls, text="Close", command=self.close_find).pack(side="right", padx=(0, 5))
        window.protocol("WM_DELETE_WINDOW", self.close_find)
        self.find_entry.focus_set()
        self._refresh_search_highlights()
        return "break"

    def _all_text_widgets(self):
        widgets = [editor.text for editor in self.story_editors.values()]
        widgets.extend((self.project_editor.text, self.style_editor.text, *self.markdown_texts.values()))
        return widgets

    def _refresh_search_highlights(self):
        if self.find_window is None or not self.find_window.winfo_exists() or self.find_entry is None:
            return
        text = self.active_text()
        if text is None:
            return
        text.tag_remove("search_match", "1.0", "end")
        text.tag_remove("search_current", "1.0", "end")
        query = self.find_entry.get()
        if not query:
            return
        nocase = not bool(self.find_case_sensitive.get())
        start = "1.0"
        while True:
            count = tk.IntVar(self.root)
            match = text.search(query, start, stopindex="end", nocase=nocase, count=count)
            if not match:
                break
            end = f"{match}+{count.get()}c"
            text.tag_add("search_match", match, end)
            start = end

    def _find_next(self, backwards=False):
        if self.find_entry is None:
            return
        query = self.find_entry.get()
        text = self.active_text()
        if not query or text is None:
            return
        self._refresh_search_highlights()
        nocase = not bool(self.find_case_sensitive.get())
        matches = []
        start = "1.0"
        while True:
            count = tk.IntVar(self.root)
            match = text.search(query, start, stopindex="end", nocase=nocase, count=count)
            if not match:
                break
            end = f"{match}+{count.get()}c"
            matches.append((match, end))
            start = end
        if not matches:
            self.set_status(f"No matches for {query!r}.")
            return

        cursor = text.index("insert")
        if backwards:
            target = next((item for item in reversed(matches) if text.compare(item[1], "<=", cursor)), matches[-1])
        else:
            target = next((item for item in matches if text.compare(item[0], ">=", cursor)), matches[0])
        text.tag_remove("search_current", "1.0", "end")
        text.tag_add("search_current", target[0], target[1])
        text.tag_remove("sel", "1.0", "end")
        text.mark_set("insert", target[0] if backwards else target[1])
        text.see(target[0])
        self.set_status(f"Found {query!r}.")

    def _show_replace_dialog(self):
        if self.find_entry is None or not self.find_entry.get():
            messagebox.showinfo("Replace", "Enter text to find first.", parent=self.root)
            return

        window = tk.Toplevel(self.root)
        window.title("Replace in Story Tabs")
        window.transient(self.root)
        window.geometry("850x470")
        window.minsize(620, 320)
        window.grab_set()
        body = ttk.Frame(window, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text="Preview replacements across the open story and include tabs. Project settings and assets are excluded.",
            wraplength=800,
        ).pack(anchor="w", pady=(0, 8))

        query_var = tk.StringVar(window, value=self.find_entry.get())
        replacement_var = tk.StringVar(window)
        fields = ttk.Frame(body)
        fields.pack(fill="x", pady=(0, 8))
        ttk.Label(fields, text="Find:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        query_entry = ttk.Entry(fields, textvariable=query_var, width=32)
        query_entry.grid(row=0, column=1, sticky="ew", padx=(0, 14))
        ttk.Label(fields, text="Replace with:").grid(row=0, column=2, sticky="w", padx=(0, 6))
        replacement_entry = ttk.Entry(fields, textvariable=replacement_var, width=32)
        replacement_entry.grid(row=0, column=3, sticky="ew")
        fields.columnconfigure(1, weight=1)
        fields.columnconfigure(3, weight=1)

        results_frame = ttk.Frame(body)
        results_frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(results_frame, columns=("file", "line", "change"), show="headings")
        tree.heading("file", text="Story File")
        tree.heading("line", text="Line")
        tree.heading("change", text="Preview")
        tree.column("file", width=190, stretch=False)
        tree.column("line", width=65, anchor="e", stretch=False)
        tree.column("change", width=520, stretch=True)
        scrollbar = ttk.Scrollbar(results_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        footer = ttk.Frame(window, padding=(10, 0, 10, 10))
        footer.pack(fill="x")
        status = ttk.Label(footer, text="Choose Preview to review changes before replacing.")
        status.pack(side="left", fill="x", expand=True)
        matches = []
        replace_button = ttk.Button(footer, text="Replace All", state="disabled")
        replace_button.pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="Close", command=window.destroy).pack(side="right")

        def build_preview():
            matches.clear()
            tree.delete(*tree.get_children())
            needle = query_var.get()
            if not needle:
                status.configure(text="Find text cannot be empty.")
                replace_button.configure(state="disabled")
                return
            nocase = not bool(self.find_case_sensitive.get())
            for path, editor in self.story_editors.items():
                widget = editor.text
                start = "1.0"
                while True:
                    count = tk.IntVar(window)
                    found = widget.search(needle, start, stopindex="end", nocase=nocase, count=count)
                    if not found:
                        break
                    end = f"{found}+{count.get()}c"
                    old_text = widget.get(found, end)
                    line_number, column = (int(part) for part in widget.index(found).split("."))
                    line_text = widget.get(f"{line_number}.0", f"{line_number}.end")
                    before = line_text[max(0, column - 24):column]
                    after_start = column + len(old_text)
                    after = line_text[after_start:after_start + 24]
                    change = f"{before}[[{old_text}]]{after}  ->  {replacement_var.get()}"
                    if len(change) > 150:
                        change = change[:147] + "..."
                    matches.append((widget, path, found, end))
                    tree.insert("", "end", values=(path.name, line_number, change))
                    start = end
            file_count = len({item[1] for item in matches})
            status.configure(text=f"{len(matches)} occurrence(s) in {file_count} story file(s).")
            replace_button.configure(state="normal" if matches else "disabled")

        def replace_all():
            if not matches:
                return
            replacement = replacement_var.get()
            by_widget = {}
            for widget, path, start, end in matches:
                by_widget.setdefault(widget, []).append((start, end))
            for widget, ranges in by_widget.items():
                ranges.sort(
                    key=lambda pair: tuple(int(part) for part in widget.index(pair[0]).split(".")),
                    reverse=True,
                )
                widget.edit_separator()
                for start, end in ranges:
                    widget.delete(start, end)
                    widget.insert(start, replacement)
                widget.edit_separator()
            count = len(matches)
            window.destroy()
            self._refresh_search_highlights()
            self.set_status(f"Replaced {count} occurrence(s) across {len(by_widget)} story file(s).")

        replace_button.configure(command=replace_all)
        ttk.Button(footer, text="Preview", command=build_preview).pack(side="right")
        query_entry.bind("<Return>", lambda _event: build_preview())
        replacement_entry.bind("<Return>", lambda _event: build_preview())
        query_entry.bind("<KeyRelease>", lambda _event: build_preview())
        replacement_entry.bind("<KeyRelease>", lambda _event: build_preview())
        query_entry.focus_set()
        build_preview()

    def close_find(self):
        for widget in self._all_text_widgets():
            widget.tag_remove("search_match", "1.0", "end")
            widget.tag_remove("search_current", "1.0", "end")
        if self.find_window is not None and self.find_window.winfo_exists():
            self.find_window.destroy()
        self.find_window = None
        self.find_entry = None
        editor = self.active_editor()
        if editor is not None:
            editor.text.focus_set()

    def document_changed(self, kind):
        if self._loading:
            return
        if kind == "story":
            editor = self.active_editor()
            if editor is self.story_editor:
                self.story_buffer = editor.get_text()
        elif kind == "project":
            self.project_buffer = self.project_editor.get_text()
        else:
            self.style_buffer = self.style_editor.get_text()
        self.engine_diagnostics = []
        self._update_tab_labels()
        if kind in {"project", "style"}:
            if self._asset_refresh_job:
                self.root.after_cancel(self._asset_refresh_job)
            self._asset_refresh_job = self.root.after(700, self._refresh_asset_tree_debounced)

    def _refresh_asset_tree_debounced(self):
        self._asset_refresh_job = None
        self.refresh_asset_tree()

    def _update_tab_labels(self):
        if not hasattr(self, "notebook"):
            return
        project_name = self.project_file.name + (" *" if self.project_editor.dirty else "")
        style_name = self.style_file.name + (" *" if self.style_editor.dirty else "")
        for path, editor in self.story_editors.items():
            try:
                self.notebook.tab(editor, text=self._story_tab_label(path, editor.dirty))
            except tk.TclError:
                pass
        self.notebook.tab(self.project_editor, text=project_name)
        self.notebook.tab(self.style_editor, text=style_name)
        marker = " *" if any(editor.dirty for editor in self.story_editors.values()) or self.project_editor.dirty or self.style_editor.dirty else ""
        self.root.title(f"{APP_TITLE} — {self.project_root.name}{marker}")

    def schedule_analysis(self, kind):
        if kind in self._analysis_revisions:
            self._analysis_revisions[kind] += 1
        old = self._analysis_jobs.get(kind)
        if old:
            self.root.after_cancel(old)
        self._analysis_jobs[kind] = self.root.after(350, lambda: self.analyze_document(kind))

    def analyze_document(self, kind):
        self._analysis_jobs.pop(kind, None)
        if kind not in self._analysis_revisions or self._loading:
            return
        if kind == "story":
            editor = self.active_editor() or self.story_editor
            document_text = editor.get_text()
            source_path = Path(getattr(editor, "story_path", self.story_file))
        else:
            if kind == "project":
                editor = self.project_editor
                document_text = self.project_editor.get_text()
            else:
                editor = self.style_editor
                document_text = self.style_editor.get_text()
            source_path = None
        revision = self._analysis_revisions[kind]
        snapshot = {
            "kind": kind,
            "revision": revision,
            "project_root": self.project_root,
            "story_file": self.story_file,
            "story_data_dir": self._story_data_dir(),
            "source_path": source_path,
            "document_text": document_text,
            "project_text": self.project_editor.get_text(),
            "style_text": self.style_editor.get_text(),
            "story_sources": [
                (path, story_editor.get_text())
                for path, story_editor in self.story_editors.items()
            ],
        }
        self.root.run_in_background(
            lambda: self._analyze_document_snapshot(snapshot),
            lambda diagnostics, error: self._finish_document_analysis(
                kind, editor, revision, diagnostics, error
            ),
        )

    @staticmethod
    def _analyze_document_snapshot(snapshot):
        kind = snapshot["kind"]
        project_root = snapshot["project_root"]
        try:
            project_values = json.loads(snapshot["project_text"])
        except json.JSONDecodeError:
            project_values = {}
        catalog = AssetCatalog(project_root, project_values if isinstance(project_values, dict) else {})

        if kind == "project":
            return analyze_project(snapshot["project_text"], catalog)
        if kind == "style":
            diagnostics = analyze_style(snapshot["style_text"], catalog, snapshot["project_text"])
            for diagnostic in diagnostics:
                diagnostic.source = "style.json"
            return diagnostics

        if yaml is None:
            return analyze_story(snapshot["document_text"], catalog, source_path=snapshot["source_path"])

        data_dir = Path(snapshot["story_data_dir"]).resolve()
        story_file = Path(snapshot["story_file"]).resolve()
        source_path = Path(snapshot["source_path"])
        source_map = {Path(path).resolve(): content for path, content in snapshot["story_sources"]}
        documents = {}
        sources = {}
        variables = {}
        dialogue_ids = set()
        start_id = None
        default_locale = "en"
        pending = [story_file]
        visited = set()
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            try:
                content = source_map.get(path)
                if content is None:
                    content = path.read_text(encoding="utf-8")
                document = yaml.safe_load(content)
            except Exception:
                continue
            if not isinstance(document, dict):
                continue
            documents[path] = document
            local_variables = document.get("variables", {})
            if isinstance(local_variables, dict):
                variables.update(local_variables)
            local_dialogues = document.get("dialogues", {})
            if isinstance(local_dialogues, dict):
                dialogue_ids.update(key for key in local_dialogues if isinstance(key, str))
                for dialogue_id, dialogue in local_dialogues.items():
                    if isinstance(dialogue_id, str) and isinstance(dialogue, dict):
                        sources[dialogue_id] = path
            if path == story_file:
                start_id = document.get("start")
                localization = document.get("localization", {})
                if isinstance(localization, dict) and isinstance(localization.get("default_locale"), str):
                    default_locale = localization["default_locale"]
            includes = document.get("includes", [])
            if isinstance(includes, list):
                for include in includes:
                    if not isinstance(include, str) or not include.strip():
                        continue
                    child_path = (path.parent / include.replace("\\", "/")).resolve()
                    try:
                        child_path.relative_to(data_dir)
                    except ValueError:
                        continue
                    pending.append(child_path)

        diagnostics = analyze_story(
            snapshot["document_text"],
            catalog,
            fragment=source_path.resolve() != story_file,
            context_variables=variables,
            context_dialogues=dialogue_ids,
            source_path=source_path,
        )
        for diagnostic in diagnostics:
            diagnostic.source = source_path.name

        if source_path.resolve() == story_file and documents:
            dialogues = {
                dialogue_id: dialogue
                for document in documents.values()
                for dialogue_id, dialogue in (document.get("dialogues", {}) if isinstance(document.get("dialogues", {}), dict) else {}).items()
                if isinstance(dialogue_id, str) and isinstance(dialogue, dict)
            }
            edges = {dialogue_id: [] for dialogue_id in dialogues}
            for dialogue_id, dialogue in dialogues.items():
                next_id = dialogue.get("next")
                if isinstance(next_id, str) and next_id in dialogues:
                    edges[dialogue_id].append(next_id)
                call_id = dialogue.get("call")
                if isinstance(call_id, str) and call_id in dialogues:
                    edges[dialogue_id].append(call_id)
                options = dialogue.get("options", [])
                if isinstance(options, list):
                    edges[dialogue_id].extend(
                        option.get("target") for option in options
                        if isinstance(option, dict) and isinstance(option.get("target"), str)
                        and option.get("target") in dialogues
                    )
            reachable = set()
            if isinstance(start_id, str) and start_id in dialogues:
                pending_ids = [start_id]
                while pending_ids:
                    current = pending_ids.pop()
                    if current in reachable:
                        continue
                    reachable.add(current)
                    pending_ids.extend(edges[current])
            for dialogue_id in sorted(set(dialogues) - reachable):
                source = sources.get(dialogue_id, story_file)
                source_text = source_map.get(source.resolve(), "")
                line = _line_of_key(source_text, dialogue_id, _line_of_key(source_text, "dialogues"))
                try:
                    source_name = source.relative_to(data_dir).as_posix()
                except ValueError:
                    source_name = source.name
                diagnostics.append(Diagnostic(
                    "warning",
                    f"Dialogue '{dialogue_id}' is unreachable from story start '{start_id}'.",
                    line,
                    source_name,
                ))
        return diagnostics

    def _finish_document_analysis(self, kind, editor, revision, diagnostics, error):
        if revision != self._analysis_revisions.get(kind):
            return
        if kind == "story" and editor not in self.story_editors.values():
            return
        if error is not None:
            diagnostics = [Diagnostic("error", f"Could not analyze {kind}: {error}")]
        self._document_analysis_cache[kind][id(editor)] = (revision, list(diagnostics or []))
        if kind == "story" and self.active_editor() is not editor:
            return
        self.live_diagnostics[kind] = diagnostics or []
        editor.highlight()
        if self.active_kind() == kind:
            self.render_diagnostics()

    def _story_context(self):
        variables = {}
        dialogue_ids = set()
        data_dir = self._story_data_dir().resolve()
        pending = [self.story_file.resolve()]
        visited = set()
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            editor = next(
                (candidate for candidate in self.story_editors.values()
                 if getattr(candidate, "story_path", path).resolve() == path),
                None,
            )
            try:
                source = editor.get_text() if editor is not None else path.read_text(encoding="utf-8")
                document = yaml.safe_load(source) if yaml is not None else None
            except Exception:
                continue
            if not isinstance(document, dict):
                continue
            local_variables = document.get("variables", {})
            if isinstance(local_variables, dict):
                variables.update(local_variables)
            dialogues = document.get("dialogues", {})
            if isinstance(dialogues, dict):
                dialogue_ids.update(key for key in dialogues if isinstance(key, str))
            includes = document.get("includes", [])
            if isinstance(includes, list):
                for include in includes:
                    if not isinstance(include, str):
                        continue
                    candidate = (path.parent / include.replace("\\", "/")).resolve()
                    try:
                        candidate.relative_to(data_dir)
                    except ValueError:
                        continue
                    pending.append(candidate)
        return variables, dialogue_ids

    def _load_story_graph(self):
        if yaml is None:
            return None
        data_dir = self._story_data_dir().resolve()
        pending = [self.story_file.resolve()]
        visited = set()
        dialogues = {}
        sources = {}
        start_id = None
        default_locale = "en"
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            editor = next(
                (candidate for candidate in self.story_editors.values()
                 if getattr(candidate, "story_path", self.story_file).resolve() == path),
                None,
            )
            try:
                source = editor.get_text() if editor is not None else path.read_text(encoding="utf-8")
                document = yaml.safe_load(source)
            except Exception:
                continue
            if not isinstance(document, dict):
                continue
            if path == self.story_file.resolve():
                start_id = document.get("start")
                localization = document.get("localization", {})
                if isinstance(localization, dict) and isinstance(localization.get("default_locale"), str):
                    default_locale = localization["default_locale"]
            local_dialogues = document.get("dialogues", {})
            if isinstance(local_dialogues, dict):
                for dialogue_id, dialogue in local_dialogues.items():
                    if isinstance(dialogue_id, str) and isinstance(dialogue, dict):
                        dialogues[dialogue_id] = dialogue
                        sources[dialogue_id] = path
            includes = document.get("includes", [])
            if isinstance(includes, list):
                for include in includes:
                    if not isinstance(include, str) or not include.strip():
                        continue
                    child_path = (path.parent / include.replace("\\", "/")).resolve()
                    try:
                        child_path.relative_to(data_dir)
                    except ValueError:
                        continue
                    pending.append(child_path)

        if not dialogues:
            return None
        edges = {dialogue_id: [] for dialogue_id in dialogues}
        for dialogue_id, dialogue in dialogues.items():
            next_id = dialogue.get("next")
            if isinstance(next_id, str) and next_id in dialogues:
                edges[dialogue_id].append((next_id, "next"))
            call_id = dialogue.get("call")
            if isinstance(call_id, str) and call_id in dialogues:
                edges[dialogue_id].append((call_id, "call"))
            options = dialogue.get("options", [])
            if isinstance(options, list):
                for option in options:
                    if isinstance(option, dict):
                        target = option.get("target")
                        if isinstance(target, str) and target in dialogues:
                            label = option.get("label", "choice")
                            if isinstance(label, dict):
                                label = label.get(default_locale, next(iter(label.values()), "choice"))
                            if option.get("condition") is not None:
                                label = f"{label} [conditional]"
                            edges[dialogue_id].append((target, str(label)))

        depth = {}
        if isinstance(start_id, str) and start_id in dialogues:
            depth[start_id] = 0
            pending_ids = [start_id]
            while pending_ids:
                current = pending_ids.pop(0)
                for target, _label in edges[current]:
                    if target not in depth:
                        depth[target] = depth[current] + 1
                        pending_ids.append(target)
        unreachable = sorted(set(dialogues) - set(depth))
        final_depth = max(depth.values(), default=0) + 1
        for dialogue_id in unreachable:
            depth[dialogue_id] = final_depth
        return {
            "start": start_id if isinstance(start_id, str) else "(missing)",
            "default_locale": default_locale,
            "dialogues": dialogues,
            "sources": sources,
            "edges": edges,
            "depth": depth,
            "unreachable": unreachable,
        }

    def open_story_graph(self):
        if not self.save_all():
            return
        graph = self._load_story_graph()
        if graph is None:
            messagebox.showerror("Story Graph", "The story files could not be read as YAML.", parent=self.root)
            return

        window = tk.Toplevel(self.root)
        window.title("Story Graph — Reachability and branches")
        window.geometry("1050x720")
        window.minsize(700, 480)
        toolbar = ttk.Frame(window, padding=(10, 8, 10, 5))
        toolbar.pack(fill="x")
        unreachable_count = len(graph["unreachable"])
        summary = f"Start: {graph['start']}  |  {len(graph['dialogues'])} dialogues  |  {unreachable_count} unreachable"
        ttk.Label(toolbar, text=summary).pack(side="left")
        ttk.Label(toolbar, text="Double-click a node to open its dialogue.", foreground="#687386").pack(side="right")

        body = ttk.Frame(window)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        canvas = tk.Canvas(body, background="#f5f7fb", highlightthickness=0)
        xbar = ttk.Scrollbar(body, orient="horizontal", command=canvas.xview)
        ybar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        columns = {}
        for dialogue_id, depth in graph["depth"].items():
            columns.setdefault(depth, []).append(dialogue_id)
        for values in columns.values():
            values.sort()
        box_width, box_height = 205, 76
        x_gap, y_gap = 85, 36
        positions = {}
        for depth, ids in columns.items():
            x = 60 + depth * (box_width + x_gap)
            for index, dialogue_id in enumerate(ids):
                y = 58 + index * (box_height + y_gap)
                positions[dialogue_id] = (x, y)
        for source_id, targets in graph["edges"].items():
            if source_id not in positions:
                continue
            sx, sy = positions[source_id]
            for target_id, label in targets:
                if target_id not in positions:
                    continue
                tx, ty = positions[target_id]
                canvas.create_line(
                    sx + box_width, sy + box_height / 2, tx, ty + box_height / 2,
                    fill="#718096", width=2, arrow="last", smooth=True,
                )
                if label != "next":
                    canvas.create_text(
                        (sx + box_width + tx) / 2,
                        (sy + ty + box_height) / 2 - 8,
                        text=label[:36], fill="#44546a",
                        font=("Segoe UI", 8),
                    )
        for dialogue_id, dialogue in graph["dialogues"].items():
            x, y = positions[dialogue_id]
            unreachable = dialogue_id in graph["unreachable"]
            ending = not graph["edges"].get(dialogue_id)
            fill = "#ffe4e6" if unreachable else "#fff1c7" if ending else "#e5efff"
            outline = "#d04a5a" if unreachable else "#bd8b22" if ending else "#5b82b8"
            tag = f"dialogue:{dialogue_id}"
            canvas.create_rectangle(
                x, y, x + box_width, y + box_height,
                fill=fill, outline=outline, width=2, tags=(tag,),
            )
            speaker = dialogue.get("speaker", "")
            canvas.create_text(
                x + 10, y + 9, anchor="nw", width=box_width - 20,
                text=f"{dialogue_id}\n{speaker}", fill="#1d2939",
                font=("Segoe UI", 10, "bold"), tags=(tag,),
            )
            canvas.tag_bind(
                tag,
                "<Double-1>",
                lambda _event, selected=dialogue_id: self._open_graph_dialogue(graph, selected),
            )
        width = max((x + box_width + 60 for x, _y in positions.values()), default=800)
        height = max((y + box_height + 60 for _x, y in positions.values()), default=600)
        canvas.configure(scrollregion=(0, 0, max(800, width), max(600, height)))

    def _open_graph_dialogue(self, graph, dialogue_id):
        path = graph["sources"].get(dialogue_id, self.story_file)
        editor = next(
            (candidate for editor_path, candidate in self.story_editors.items()
             if editor_path.resolve() == path.resolve()),
            None,
        )
        if editor is None:
            self._sync_included_story_tabs()
            editor = next(
                (candidate for editor_path, candidate in self.story_editors.items()
                 if editor_path.resolve() == path.resolve()),
                None,
            )
        if editor is None:
            return
        self.notebook.select(editor)
        source = editor.get_text()
        line = _line_of_key(source, dialogue_id, _line_of_key(source, "dialogues"))
        editor.text.mark_set("insert", f"{line}.0")
        editor.text.see(f"{line}.0")
        editor.text.focus_set()
        editor.redraw_gutter()

    def apply_diagnostic_marks(self, editor):
        editor.text.tag_remove("diagnostic_error", "1.0", "end")
        editor.text.tag_remove("diagnostic_warning", "1.0", "end")
        editor.text.tag_remove("diagnostic_hint", "1.0", "end")
        kind = editor.document_kind
        diagnostics = list(self.live_diagnostics.get(kind, []))
        if kind == "story":
            diagnostics.extend(self.engine_diagnostics)
            source_path = Path(getattr(editor, "story_path", self.story_file))
            try:
                active_source = source_path.resolve().relative_to(self._story_data_dir().resolve()).as_posix()
            except ValueError:
                active_source = source_path.name
        for diagnostic in diagnostics:
            if (
                kind == "story"
                and diagnostic.source not in {"Editor", "Engine", active_source, source_path.name}
            ):
                continue
            line = max(1, diagnostic.line)
            tag = {"error": "diagnostic_error", "warning": "diagnostic_warning", "hint": "diagnostic_hint"}.get(diagnostic.severity)
            if tag:
                editor.text.tag_add(tag, f"{line}.0", f"{line}.end")

    def render_diagnostics(self):
        for item in self.diagnostics_tree.get_children(""):
            self.diagnostics_tree.delete(item)
        items = list(self.live_diagnostics.get(self.active_kind(), [])) + self.engine_diagnostics
        items.sort(key=lambda item: (item.line, {"error": 0, "warning": 1, "hint": 2}.get(item.severity, 3)))
        for diagnostic in items:
            self.diagnostics_tree.insert("", "end", values=(diagnostic.source, diagnostic.severity.title(), diagnostic.line, diagnostic.message))
        errors = sum(item.severity == "error" for item in items)
        warnings = sum(item.severity in {"warning", "hint"} for item in items)
        self.set_status(f"{errors} error(s), {warnings} warning(s)  |  Ctrl+Space: suggestions  |  F5: engine validation")

    def _jump_to_diagnostic(self, _event=None):
        selection = self.diagnostics_tree.selection()
        if not selection:
            return
        values = self.diagnostics_tree.item(selection[0], "values")
        source = values[0]
        try:
            line = int(values[2])
        except (ValueError, IndexError):
            return
        if source == "Engine":
            self.notebook.select(self.story_editor)
            editor = self.story_editor
        else:
            editor = next(
                (
                    candidate for path, candidate in self.story_editors.items()
                    if self._story_source_label(path) == source
                ),
                None,
            )
            if editor is None:
                editor = next(
                    (candidate for path, candidate in self.story_editors.items() if path.name == source),
                    self.active_editor(),
                )
            if editor is not None:
                self.notebook.select(editor)
        editor.text.mark_set("insert", f"{line}.0")
        editor.text.see(f"{line}.0")
        editor.text.focus_set()
        editor.redraw_gutter()

    def update_cursor_status(self):
        if not hasattr(self, "status"):
            return
        editor = self.active_editor()
        if editor is None:
            return
        try:
            line, col = editor.text.index("insert").split(".")
        except tk.TclError:
            return
        editor.redraw_gutter()
        errors = sum(item.severity == "error" for item in self.live_diagnostics.get(self.active_kind(), []))
        self.set_status(f"Line {line}, column {int(col) + 1}  |  {errors} error(s)  |  Ctrl+Space: suggestions  |  F5: validate")

    def set_status(self, message):
        if hasattr(self, "status"):
            self.status.configure(text=message)

    def completions_for(self, editor: CodeEditor):
        before = editor.text.get("1.0", "insert")
        line_start_index = editor.text.index("insert linestart")
        line = editor.text.get(line_start_index, "insert")
        if editor.document_kind == "story":
            return self._story_completions(before, line, line_start_index)
        return self._project_completions(before, line, line_start_index, editor.document_kind)

    def _story_completions(self, before, line, line_start_index):
        catalog = self._catalog()
        try:
            story_data = yaml.safe_load(before) if yaml is not None else {}
        except Exception:
            story_data = {}
        if not isinstance(story_data, dict):
            story_data = {}
        variables, dialogue_ids = self._story_context()
        dialogues = {dialogue_id: None for dialogue_id in dialogue_ids}

        frame_item = re.match(r"^(\s*-\s*)(.*)$", line)
        if frame_item and self._current_yaml_action(before) == "animate_character":
            previous_lines = before.splitlines()
            frame_rows = [
                index for index, row in enumerate(previous_lines)
                if re.match(r"^\s*frames\s*:", row)
            ]
            if frame_rows:
                frames_index = frame_rows[-1]
                frames_indent = len(previous_lines[frames_index]) - len(previous_lines[frames_index].lstrip())
                still_in_frames = all(
                    not row.strip()
                    or len(row) - len(row.lstrip()) > frames_indent
                    for row in previous_lines[frames_index + 1:]
                )
                if still_in_frames:
                    name = self._current_yaml_value(before, "name")
                    look = self._current_yaml_value(before, "look")
                    candidates = [
                        (value, "PNG animation frame")
                        for value in catalog.expressions_for(name, look)
                    ]
                    prefix, current = frame_item.groups()
                    return candidates, f"{line_start_index}+{len(prefix)}c", current.strip().strip("'\"")

        include_item = re.match(r"^(\s*-\s*)(.*)$", line)
        if include_item and self._yaml_root_section(before) == "includes":
            catalog = self._catalog()
            active = self.active_editor()
            include_base = getattr(active, "story_path", self.story_file).parent
            try:
                candidates = [
                    (Path(os.path.relpath(path, include_base)).as_posix(), "included YAML story")
                    for path in catalog.data_dir.rglob("*.y*ml") if path.is_file()
                ]
            except OSError:
                candidates = []
            prefix, current = include_item.groups()
            return candidates, f"{line_start_index}+{len(prefix)}c", current.strip().strip("'\"")

        value_match = re.match(r"^(\s*(?:-\s*)?)([\w-]+)(\s*:\s*)(.*)$", line)
        if value_match:
            prefix, key, separator, current = value_match.groups()
            start_col = len(prefix) + len(key) + len(separator)
            current_value = current.lstrip()
            if current_value.startswith(("'", '"')):
                start_col += len(current) - len(current_value) + 1
                current_prefix = current_value[1:].strip().strip("'\"")
            else:
                current_prefix = current.strip().strip("'\"")
            field = key
            candidates = []
            action_type = self._current_yaml_action(before)
            character_name = self._current_yaml_character(before, key)
            if field == "type":
                candidates = [(value, "story action") for value in sorted(ACTION_TYPES)]
            elif field == "voice":
                candidates = [(value, "voice sound asset") for value in catalog.asset_suggestions("sound")]
            elif field == "op":
                candidates = [(value, "condition operator") for value in sorted(CONDITION_OPERATORS)]
            elif field == "direction":
                candidates = [(value, "fade direction") for value in ("in", "out")]
            elif field == "position":
                candidates = [(value, "portrait position") for value in sorted(CHARACTER_POSITIONS)]
            elif field == "var":
                candidates = [(value, "declared story variable") for value in variables]
            elif field in {"start", "next", "target"}:
                candidates = [(str(value), "dialogue ID") for value in dialogues]
            elif field in {"name", "speaker", "active_character"}:
                if action_type == "sound" or field == "name" and action_type == "sound":
                    candidates = [(value, "sound asset") for value in catalog.asset_suggestions("sound")]
                else:
                    candidates = [(value, "character asset") for value in catalog.character_names()]
                    if field == "speaker" or field == "active_character":
                        candidates.insert(0, ("Narrator", "no portrait required"))
            elif field == "look":
                candidates = [(value, "character look") for value in catalog.looks_for(character_name)]
            elif field == "expression":
                current_look = self._current_yaml_value(before, "look")
                candidates = [(value, "PNG expression") for value in catalog.expressions_for(character_name, current_look)]
            elif field == "frames":
                current_look = self._current_yaml_value(before, "look")
                candidates = [(value, "PNG animation frame") for value in catalog.expressions_for(character_name, current_look)]
            elif field == "image":
                candidates = [(value, "image asset") for value in catalog.asset_suggestions("image")]
            elif field == "track":
                candidates = [(value, "music file") for value in catalog.asset_suggestions("music")]
            elif field == "color":
                candidates = [("[0, 0, 0]", "black fade color (RGB)")]
            elif field == "duration":
                default = "0.6" if action_type == "fade" else "0.35"
                candidates = [(default, "default duration in seconds")]
            elif field == "intensity":
                candidates = [("8", "default shake intensity in pixels")]
            elif field == "frame_duration":
                candidates = [("0.25", "default animation frame duration in seconds")]
            elif field == "loop":
                candidates = [("true", "repeat animation"), ("false", "stop on the last frame")]
            elif field == "condition":
                candidates = [(value, "condition key") for value in ("var", "op", "value", "all", "any", "not")]
            else:
                return [], f"{line_start_index}+{start_col}c", current.strip().strip("'\"")
            return candidates, f"{line_start_index}+{start_col}c", current_prefix

        key_match = re.match(r"^(\s*(?:-\s*)?)([A-Za-z_][\w-]*)?$", line)
        if not key_match:
            return [], editor_index(line_start_index, len(line)), ""
        indent_text, partial = key_match.groups()
        partial = partial or ""
        indent = len(indent_text.replace("\t", "  "))
        section = self._yaml_root_section(before)
        keys = self._yaml_keys_for_context(before, indent, section)
        candidates = [(f"{key}:", "story field") for key in keys]
        start_col = len(indent_text)
        return candidates, f"{line_start_index}+{start_col}c", partial

    def _yaml_root_section(self, before):
        roots = re.findall(r"^([A-Za-z_][\w-]*)\s*:", before, re.M)
        return roots[-1] if roots else ""

    def _yaml_keys_for_context(self, before, indent, section):
        if indent == 0:
            return sorted(STORY_TOP_KEYS)
        if section == "character_defaults":
            return ["look", "position"] if indent >= 2 else []
        if section != "dialogues":
            return []
        tail = before.split("\n")
        last_dialogue = max((i for i, row in enumerate(tail) if re.match(r"^  [\w-]+\s*:", row)), default=0)
        dialogue_text = "\n".join(tail[last_dialogue:])
        if re.search(r"^\s{4}options\s*:", dialogue_text, re.M):
            option_pos = dialogue_text.rfind("options:")
            action_pos = dialogue_text.rfind("actions:")
            if option_pos > action_pos:
                if re.search(r"^\s{8}condition\s*:", dialogue_text[option_pos:], re.M):
                    return sorted(CONDITION_KEYS)
                return sorted(OPTION_KEYS)
        if re.search(r"^\s{4}actions\s*:", dialogue_text, re.M):
            action_pos = dialogue_text.rfind("actions:")
            after_actions = dialogue_text[action_pos:]
            kind_match = re.findall(r"^\s{6}-\s*type\s*:\s*([\w-]+)", after_actions, re.M)
            if kind_match:
                return sorted(ACTION_FIELDS.get(kind_match[-1], {"type"}))
            return sorted({"type"})
        if indent >= 4:
            return sorted(DIALOGUE_KEYS)
        return []

    def _current_yaml_action(self, before):
        actions_index = before.rfind("actions:")
        if actions_index < 0:
            return None
        dialogue_starts = [match.start() for match in re.finditer(r"^  [\w-]+\s*:", before, re.M)]
        if dialogue_starts and dialogue_starts[-1] > actions_index:
            return None
        matches = re.findall(r"^\s{6}-\s*type\s*:\s*([\w-]+)", before[actions_index:], re.M)
        return matches[-1] if matches else None

    def _current_yaml_character(self, before, field):
        if field in {"speaker", "active_character"}:
            return self._current_yaml_value(before, field)
        action_start = max(before.rfind("\n      - "), before.rfind("\n      type:"), before.rfind("\n    actions:"))
        block = before[action_start:] if action_start >= 0 else before
        names = re.findall(r"^\s*(?:-\s*)?name\s*:\s*['\"]?([^\s'\"]+)", block, re.M)
        if names:
            return names[-1]
        defaults = re.findall(r"^\s{2}([\w-]+)\s*:\s*$", before, re.M)
        return defaults[-1] if defaults else None

    @staticmethod
    def _current_yaml_value(before, key):
        matches = re.findall(r"^\s*(?:-\s*)?" + re.escape(key) + r"\s*:\s*['\"]?([^\s'\"]+)", before, re.M)
        return matches[-1] if matches else None

    def _project_completions(self, before, line, line_start_index, document_kind="project"):
        value_match = re.match(r'^(\s*)"([^"\n]+)"\s*:\s*(.*)$', line)
        if value_match:
            indent, key, current = value_match.groups()
            start_col = value_match.start(3)
            current_value = current.lstrip()
            quote_open = current_value.startswith('"')
            if quote_open:
                start_col += len(current) - len(current_value) + 1
                current_prefix = current_value[1:].strip().strip('"')
            else:
                current_prefix = current.strip().strip('"')
            catalog = self._catalog()
            context = self._json_context(before)
            values = []
            if key == "story":
                try:
                    data_dir = catalog.data_dir
                    values = [(path.name, "YAML story file") for path in data_dir.glob("*.y*ml")]
                except OSError:
                    values = []
            elif key == "action":
                values = [(value, "menu action") for value in sorted(MENU_ACTIONS - {"save_slot", "load_slot"})]
            elif key == "setting":
                values = [(value, "setting") for value in sorted(SETTING_NAMES)]
            elif key == "layout":
                values = [(value, "layout") for value in ("centered", "left", "right")]
            elif key == "label_alignment":
                values = [(value, "label alignment") for value in ("left", "center", "right")]
            elif key == "schema_version":
                values = [("1", "style schema version")]
            elif key in {"normal", "hovered"} and context[-1:] in {
                ("buttons",), ("choice_buttons",),
            }:
                values = [(value, "image asset") for value in catalog.asset_suggestions("image")]
            elif key == "image" and context[-1:] == ("pause_button",):
                values = [(value, "image asset") for value in catalog.asset_suggestions("image")]
            elif key == "background" and context[-1:] in {
                ("menu",), ("textbox",), ("main",), ("pause",), ("settings",), ("slots",), ("credits",),
            }:
                values = [(value, "image asset") for value in catalog.asset_suggestions("image")]
            elif key == "color" and context[-1:] == ("textbox",):
                values = [(json.dumps(DEFAULT_THEME.get("colors", {}).get("panel", [0, 0, 0, 128]), ensure_ascii=False), "default textbox color")]
            elif key in {"hover", "click", "cancel", "load"} and context[-1:] == ("sounds",):
                values = [(value, "sound asset") for value in catalog.asset_suggestions("sound")]
            elif key in {"menu", "title"} and context[-1:] == ("fonts",):
                values = [(value, "font file") for value in catalog.asset_suggestions("font")]
            elif key in {"text", "name", "button", "intro"} and context[-1:] == ("game_fonts",):
                values = [(value, "font file") for value in catalog.asset_suggestions("font")]
            elif key in {"data", "assets", "user_data"} and context[-1:] == ("paths",):
                values = [("data", "project folder"), ("assets", "project folder"), ("user_data", "writable folder")]
            elif key in {"warning_image", "headphones_image", "credit_image"} and context[-1:] == ("intro",):
                values = [(value, "image asset") for value in catalog.asset_suggestions("image")]
            elif context[-1:] == ("colors",) and key in DEFAULT_THEME.get("colors", {}):
                values = [(json.dumps(DEFAULT_THEME["colors"][key]), "default color value")]
            else:
                values = []
            json_values = [
                (label if label.startswith(("[", "{")) else json.dumps(label, ensure_ascii=False), detail)
                for label, detail in values
            ]
            if quote_open:
                unquoted = []
                for label, detail in json_values:
                    if label.startswith('"'):
                        try:
                            value = json.loads(label)
                            label = json.dumps(value, ensure_ascii=False)[1:-1]
                        except json.JSONDecodeError:
                            pass
                    unquoted.append((label, detail))
                json_values = unquoted
            return json_values, f"{line_start_index}+{start_col}c", current_prefix

        # Suggest project keys on a blank/object-key line based on the most recent object.
        key_match = re.match(r'^(\s*)"?([A-Za-z_][\w-]*)?$', line)
        if not key_match:
            return [], editor_index(line_start_index, len(line)), ""
        indent_text, partial = key_match.groups()
        partial = partial or ""
        context = self._json_context(before)
        keys = self._json_allowed_keys(context, document_kind)
        return [(f'"{key}":', f"{context or document_kind} setting") for key in keys], f"{line_start_index}+{len(indent_text)}c", partial

    @staticmethod
    def _json_context(before):
        stack = []
        in_string = False
        escaped = False
        string_start = 0
        last_key = None
        for index, char in enumerate(before):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
                string_start = index + 1
            elif char == ":" and stack and stack[-1][0] == "object":
                key_text = before[:index]
                match = re.search(r'"([^"\\]+)"\s*$', key_text)
                if match:
                    stack[-1] = (stack[-1][0], stack[-1][1], match.group(1))
            elif char == "{":
                if stack and stack[-1][0] == "array":
                    object_path = stack[-1][1] + ("[]",)
                elif stack and stack[-1][2]:
                    object_path = stack[-1][1] + (stack[-1][2],)
                else:
                    object_path = stack[-1][1] if stack else ()
                stack.append(("object", object_path, None))
            elif char == "[":
                stack.append(("array", stack[-1][1] + (stack[-1][2],) if stack and stack[-1][2] else (), None))
            elif char in "}]":
                if stack:
                    stack.pop()
        if not stack:
            return ()
        path = stack[-1][1]
        if stack[-1][0] == "array":
            return path + ("[]",)
        return path

    @staticmethod
    def _json_allowed_keys(context, document_kind="project"):
        if not context:
            return sorted(DEFAULT_STYLE if document_kind == "style" else DEFAULT_PROJECT)
        if context[0] == "characters":
            return ["scale"] if len(context) == 2 else []
        joined = ".".join(context)
        schemas = {
            "intro": (["credit_image", "warning_image", "headphones_image"] if document_kind == "style" else ["creator", "game_version", "warning_message"]),
            "paths": ["data", "assets", "user_data"],
            "window": ["width", "height", "caption"],
            "dialogue_buttons": list(DEFAULT_STYLE.get("dialogue_buttons", {})),
            **{
                f"dialogue_buttons.{button}": ["visible", "label", "label_alignment"]
                for button in DEFAULT_STYLE.get("dialogue_buttons", {})
            },
            "menus": ["main", "pause", "settings", "slots"],
            "menus.main": ["title", "items"],
            "menus.pause": ["title", "items"],
            "menus.settings": ["title", "items"],
            "menus.slots": ["title_save", "title_load", "labels", "delete", "back"],
            "menus.slots.labels": ["slot", "saved", "empty", "corrupt", "unknown_chapter", "unknown_time"],
            "menus.slots.delete": ["label", "action"],
            "menus.slots.back": ["label", "action"],
            "menus.main.items[]": ["label", "action", "setting", "detail"],
            "menus.pause.items[]": ["label", "action", "setting", "detail"],
            "menus.settings.items[]": ["label", "action", "setting", "detail"],
            "theme": list(DEFAULT_THEME),
            "theme.colors": list(DEFAULT_THEME.get("colors", {})),
            "theme.fonts": list(DEFAULT_THEME.get("fonts", {})),
            "theme.game_fonts": list(DEFAULT_THEME.get("game_fonts", {})),
            "theme.game_font_sizes": list(DEFAULT_THEME.get("game_font_sizes", {})),
            "theme.menu": list(DEFAULT_THEME.get("menu", {})) + ["right_margin"],
            "theme.menu.screens": list(DEFAULT_THEME.get("menu", {}).get("screens", {})),
            "theme.menu.screens.main": list(DEFAULT_THEME.get("menu", {}).get("screens", {}).get("main", {})) + ["label_alignment"],
            "theme.menu.screens.pause": list(DEFAULT_THEME.get("menu", {}).get("screens", {}).get("pause", {})) + ["label_alignment"],
            "theme.menu.screens.settings": list(DEFAULT_THEME.get("menu", {}).get("screens", {}).get("settings", {})) + ["label_alignment"],
            "theme.menu.screens.slots": list(DEFAULT_THEME.get("menu", {}).get("screens", {}).get("slots", {})) + ["label_alignment"],
            "theme.menu.screens.credits": list(DEFAULT_THEME.get("menu", {}).get("screens", {}).get("credits", {})) + ["label_alignment"],
            "theme.menu.screens.main.buttons": ["normal", "hovered"],
            "theme.menu.screens.pause.buttons": ["normal", "hovered"],
            "theme.menu.screens.settings.buttons": ["normal", "hovered"],
            "theme.menu.screens.slots.buttons": ["normal", "hovered"],
            "theme.menu.screens.credits.buttons": ["normal", "hovered"],
            "theme.textbox": list(DEFAULT_THEME.get("textbox", {})),
            "theme.choice_buttons": list(DEFAULT_THEME.get("choice_buttons", {})),
            "theme.pause_button": list(DEFAULT_THEME.get("pause_button", {})),
            "theme.sounds": list(DEFAULT_THEME.get("sounds", {})),
            "schema_version": [],
            "messages": list(DEFAULT_PROJECT.get("messages", {})),
            "credits[]": ["label", "url"],
        }
        return sorted(schemas.get(joined, []))

    def schedule_completion(self, editor, event):
        if event.keysym in {"space", "colon", "slash"} or len(event.char or "") == 1:
            old = self._completion_jobs.get(editor.document_kind)
            if old:
                self.root.after_cancel(old)
            self._completion_jobs[editor.document_kind] = self.root.after(
                80, lambda: self._auto_complete(editor)
            )

    def _auto_complete(self, editor):
        self._completion_jobs.pop(editor.document_kind, None)
        editor.show_completion(automatic=True)

    def _write_document(self, kind):
        if kind == "story":
            editor = self.active_editor() or self.story_editor
            return self._write_story_editor(editor)
        elif kind == "project":
            path, editor = self.project_file, self.project_editor
        else:
            path, editor = self.style_file, self.style_editor
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(editor.get_text(), encoding="utf-8", newline="\n")
        editor.dirty = False
        if kind == "project":
            self.project_buffer = editor.get_text()
        else:
            self.style_buffer = editor.get_text()
        self._update_tab_labels()
        return path

    def _write_story_editor(self, editor):
        path = getattr(editor, "story_path", self.story_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = editor.get_text()
        path.write_text(content, encoding="utf-8", newline="\n")
        editor.dirty = False
        if editor is self.story_editor:
            self.story_buffer = content
        self._update_tab_labels()
        return path

    def save_active(self):
        if self._project_load_pending:
            self.set_status("Wait for the project to finish loading before saving.")
            return
        kind = self.active_kind()
        if kind == "markdown":
            self.set_status("Documentation tabs are read-only.")
            return
        try:
            story_dirty = any(editor.dirty for editor in self.story_editors.values())
            if kind == "project" and story_dirty:
                new_story = self._pending_story_path()
                if new_story is not None and new_story != self.story_file:
                    answer = messagebox.askyesnocancel(
                        APP_TITLE,
                        f"The project now selects {new_story}. Save the current story before switching to it?\n\n"
                        "Choose No to discard the current story changes, or Cancel to stop the save.",
                        parent=self.root,
                    )
                    if answer is None:
                        return
                    if answer:
                        for story_editor in self.story_editors.values():
                            self._write_story_editor(story_editor)
            path = self._write_document(kind)
            if kind == "project":
                self._after_project_save()
                self._sync_included_story_tabs()
            elif kind == "story":
                self._sync_included_story_tabs()
            self.engine_diagnostics = []
            self.analyze_document(kind)
            self.set_status(f"Saved {path}")
        except OSError as error:
            messagebox.showerror(APP_TITLE, f"Could not save file:\n{error}", parent=self.root)

    def _pending_story_path(self):
        try:
            values = json.loads(self.project_editor.get_text())
        except json.JSONDecodeError:
            return None
        if not isinstance(values, dict):
            return None
        return self._story_path_from(values)

    def save_all(self, analyze=True):
        if self._project_load_pending:
            self.set_status("Wait for the project to finish loading before saving.")
            return False
        old_story = self.story_file
        try:
            for story_editor in list(self.story_editors.values()):
                self._write_story_editor(story_editor)
            self._write_document("project")
            self._write_document("style")
            self._after_project_save(old_story)
            self._sync_included_story_tabs()
            for story_editor in list(self.story_editors.values()):
                if story_editor.dirty:
                    self._write_story_editor(story_editor)
            self.engine_diagnostics = []
            self.refresh_asset_tree()
            if analyze:
                self.analyze_document("story")
                self.analyze_document("project")
                self.analyze_document("style")
            self._update_tab_labels()
            self.set_status("Saved story YAML files, project.json, and style.json.")
            return True
        except OSError as error:
            messagebox.showerror(APP_TITLE, f"Could not save project files:\n{error}", parent=self.root)
            return False

    def _after_project_save(self, old_story=None):
        old_story = old_story or self.story_file
        try:
            raw_values = json.loads(self.project_editor.get_text())
        except json.JSONDecodeError:
            self.project_file = self.project_root / "data" / "project.json"
            return
        if not isinstance(raw_values, dict):
            self.project_file = self.project_root / "data" / "project.json"
            return
        values = merge_defaults(DEFAULT_PROJECT, raw_values)
        new_story = self._story_path_from(values)
        self.project_file = self.project_root / "data" / "project.json"
        if new_story != old_story:
            self.story_file = new_story
            story_dirty = not new_story.is_file()
            try:
                content = new_story.read_text(encoding="utf-8") if new_story.is_file() else self._starter_story()
            except OSError:
                content = self._starter_story()
                story_dirty = True
            self.story_editor.set_text(content)
            self.story_editor.dirty = story_dirty
            self.story_editor.story_path = new_story
            self.story_buffer = content
        else:
            self.story_file = new_story
        self.story_editor.story_path = self.story_file
        self._update_tab_labels()
        self._sync_included_story_tabs()

    def _confirm_discard_or_save(self, action: str):
        if not (
            any(editor.dirty for editor in self.story_editors.values())
            or self.project_editor.dirty
            or self.style_editor.dirty
        ):
            return True
        answer = messagebox.askyesnocancel(APP_TITLE, f"Save your changes before {action}?", parent=self.root)
        if answer is None:
            return False
        if answer:
            self.save_all()
            return not (
                any(editor.dirty for editor in self.story_editors.values())
                or self.project_editor.dirty
                or self.style_editor.dirty
            )
        return True

    def validate_with_engine(self):
        if self.active_kind() != "story":
            self.notebook.select(self.story_editor)
            self.root.update_idletasks()
        if not self.save_all():
            return
        temporary = None
        workspace_root = self._workspace_source_root()
        if workspace_root is not None:
            runtime = workspace_root / "main.py"
            command = [sys.executable, str(runtime), "--validate"]
        else:
            runtime = self.project_root / "VN_Engine" / "engine.exe"
            if not runtime.is_file():
                runtime = self.project_root / "engine.exe"
            if runtime.is_file():
                command = (
                    [sys.executable, str(runtime), "--validate"]
                    if runtime.suffix.casefold() == ".py"
                    else [str(runtime), "--validate"]
                )
            else:
                source_main = self.project_root / "main.py"
                if source_main.is_file():
                    command = [sys.executable, str(source_main), "--validate"]
                else:
                    try:
                        temporary, _platform, _game_name, runtime = self._create_temporary_game()
                    except (OSError, ValueError, json.JSONDecodeError) as error:
                        self.engine_diagnostics = [Diagnostic(
                            "error", f"Could not prepare the engine template for validation: {error}", 1, "Engine"
                        )]
                        self.render_diagnostics()
                        return
                    command = (
                        [sys.executable, str(runtime), "--validate"]
                        if runtime.suffix.casefold() == ".py"
                        else [str(runtime), "--validate"]
                    )
        self.set_status("Running the engine story validator...")
        self.root.update_idletasks()
        environment = os.environ.copy()
        if workspace_root is not None and Path(command[1]).resolve() == workspace_root / "main.py":
            environment["VN_ENGINE_PROJECT_DIR"] = str(self.project_root)
        try:
            result = subprocess.run(
                command,
                cwd=self.project_root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            self.engine_diagnostics = [Diagnostic("error", f"Could not run engine validation: {error}", 1, "Engine")]
            self.render_diagnostics()
            return
        finally:
            if temporary is not None:
                temporary.cleanup()
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.returncode == 0:
            self.engine_diagnostics = [Diagnostic("hint", output or "Engine validation passed.", 1, "Engine")]
        else:
            lines = [line.strip().lstrip("- ") for line in output.splitlines() if line.strip()]
            if not lines:
                lines = [f"Engine validation exited with code {result.returncode}."]
            diagnostics = []
            for message in lines:
                match = re.search(r"dialogues\.([^\.\s]+)", message)
                line = _line_of_key(self.story_editor.get_text(), match.group(1), _line_of_key(self.story_editor.get_text(), "dialogues")) if match else 1
                diagnostics.append(Diagnostic("error", message, line, "Engine"))
            self.engine_diagnostics = diagnostics
        self.render_diagnostics()

    def _collect_export_errors(self):
        catalog = self._catalog()
        context_variables, context_dialogues = self._story_context()
        errors = []
        for path, editor in self.story_editors.items():
            diagnostics = analyze_story(
                editor.get_text(),
                catalog,
                fragment=editor is not self.story_editor,
                context_variables=context_variables,
                context_dialogues=context_dialogues,
                source_path=path,
            )
            errors.extend(
                f"{path.name}:{item.line}: {item.message}"
                for item in diagnostics if item.severity == "error"
            )
        project_diagnostics = analyze_project(self.project_editor.get_text(), catalog)
        errors.extend(
            f"project.json:{item.line}: {item.message}"
            for item in project_diagnostics if item.severity == "error"
        )
        style_diagnostics = analyze_style(
            self.style_editor.get_text(), catalog, self.project_editor.get_text()
        )
        errors.extend(
            f"style.json:{item.line}: {item.message}"
            for item in style_diagnostics if item.severity == "error"
        )
        return errors

    def _show_export_errors(self, title, errors):
        if not errors:
            return False
        messagebox.showerror(
            title,
            "Fix these errors before continuing:\n\n" + "\n".join(errors[:30]),
            parent=self.root,
        )
        return True

    def _template_directory(self):
        candidates = [
            self.editor_home / "templates",
            self.editor_home / "engine" / "templates",
            self.editor_home / "VN_Engine" / "engine" / "templates",
            self.project_root / "templates",
            self.project_root / "engine" / "templates",
        ]
        if len(self.editor_home.parents) >= 3:
            candidates.append(self.editor_home.parents[2] / "templates")
        return next(
            (path for path in candidates if path.is_dir() and any(path.glob("template-*.zip"))),
            next((path for path in candidates if path.is_dir()), candidates[0]),
        )

    def _editor_release_tag(self):
        candidates = (
            self.editor_home / "engine-version.txt",
            Path(__file__).resolve().parent / "engine" / "data" / "version.txt",
        )
        for version_file in candidates:
            if not version_file.is_file():
                continue
            version = version_file.read_text(encoding="utf-8").strip()
            return version if version.startswith("v") else f"v{version}"
        return None

    @staticmethod
    def _current_platform():
        if sys.platform == "win32":
            return "windows"
        if sys.platform == "darwin":
            return "macos"
        return "linux"

    @staticmethod
    def _test_play_executable(runtime_root, platform, game_name):
        if platform == "windows":
            return runtime_root / game_name / f"{game_name}.exe"
        if platform == "linux":
            return runtime_root / game_name / game_name
        return runtime_root / f"{game_name}.app" / "Contents" / "MacOS" / "Runner"

    def _uses_workspace_source_test_play(self, values=None):
        if values is None:
            try:
                values = json.loads(self.project_editor.get_text())
            except (json.JSONDecodeError, AttributeError):
                values = {}
        return isinstance(values, dict) and values.get("USER") == "admin"

    @staticmethod
    def _workspace_source_root():
        root = Path(__file__).resolve().parent
        return root if (root / "main.py").is_file() and (root / "engine").is_dir() else None

    def _create_source_test_play(self, temporary_root: Path, game_name: str):
        workspace_root = self._workspace_source_root()
        if workspace_root is None:
            raise RuntimeError("The workspace engine source is not available for Test Play.")
        source_main = workspace_root / "main.py"
        source_engine = workspace_root / "engine"
        if not source_engine.is_dir():
            raise RuntimeError("The workspace engine source is incomplete.")
        return workspace_root, source_main

    def _create_temporary_game(self):
        from export_pipeline import export_project, safe_project_name

        values = json.loads(self.project_editor.get_text())
        platform = self._current_platform()
        game_name = safe_project_name(values.get("name", "Visual Novel"))
        temporary = tempfile.TemporaryDirectory(prefix="vn_editor_test_play_")
        temporary_root = Path(temporary.name)
        runtime_root = temporary_root / "runtime"
        archive_path = temporary_root / f"{game_name}-{platform}.zip"
        try:
            source_root = self._workspace_source_root()
            use_source = source_root is not None
            if self._uses_workspace_source_test_play(values) and not use_source:
                raise RuntimeError("USER is set to 'admin', but workspace source files main.py and engine/ are unavailable.")
            if use_source:
                _source_root, executable = self._create_source_test_play(temporary_root, game_name)
            else:
                export_project(
                    self.project_root,
                    self.project_file,
                    self._template_directory(),
                    platform,
                    archive_path,
                )
                self._extract_test_play_archive(archive_path, runtime_root)
                executable = self._test_play_executable(runtime_root, platform, game_name)
                if not executable.is_file():
                    raise FileNotFoundError(f"Test-play executable was not found: {executable}")
            return temporary, platform, game_name, executable
        except Exception:
            temporary.cleanup()
            raise

    @staticmethod
    def _extract_test_play_archive(archive_path, destination):
        destination.mkdir(parents=True, exist_ok=True)
        destination_root = destination.resolve()
        with ZipFile(archive_path, "r") as archive:
            for item in archive.infolist():
                relative = PurePosixPath(item.filename.replace("\\", "/"))
                if relative.is_absolute() or ".." in relative.parts or (
                    relative.parts and relative.parts[0].endswith(":")
                ):
                    raise ValueError(f"Unsafe path in test-play archive: {item.filename!r}")
                target = destination.joinpath(*relative.parts)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    mode = item.external_attr >> 16
                    if os.name != "nt" and mode:
                        target.chmod(mode & 0o777)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                mode = item.external_attr >> 16 if item.create_system == 3 else 0
                if stat.S_ISLNK(mode):
                    link_target = archive.read(item).decode("utf-8")
                    if PurePosixPath(link_target).is_absolute():
                        raise ValueError(f"Absolute symlink in test-play archive: {item.filename!r}")
                    resolved_link = (target.parent / link_target).resolve()
                    try:
                        resolved_link.relative_to(destination_root)
                    except ValueError as error:
                        raise ValueError(f"Symlink escapes test-play folder: {item.filename!r}") from error
                    os.symlink(link_target, target)
                    continue
                target.write_bytes(archive.read(item))
                if os.name != "nt" and mode:
                    target.chmod(mode & 0o777)

    def _cleanup_test_play(self):
        temporary = self.test_play_tempdir
        self.test_play_tempdir = None
        if temporary is not None:
            try:
                temporary.cleanup()
            except OSError:
                pass

    def _poll_test_play(self):
        self.test_play_poll_job = None
        process = self.test_play_process
        if process is not None and process.poll() is None:
            self.test_play_poll_job = self.root.after(750, self._poll_test_play)
            return
        self.test_play_process = None
        exit_code = process.returncode if process is not None else None
        coverage = None
        coverage_path = self.test_play_coverage_path
        self.test_play_coverage_path = None
        if coverage_path is not None:
            try:
                coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                coverage = None
        log_path = self.test_play_log_path
        self.test_play_log_path = None
        log_excerpt = ""
        if exit_code not in (None, 0) and log_path is not None:
            try:
                with log_path.open("rb") as log_file:
                    log_file.seek(max(0, log_path.stat().st_size - 6000))
                    log_excerpt = log_file.read().decode("utf-8", errors="replace").strip()
            except OSError:
                pass
        self._cleanup_test_play()
        if exit_code not in (None, 0):
            self.set_status(f"Test Play exited with code {exit_code}.")
            detail = f"Test Play exited with code {exit_code}."
            if log_excerpt:
                detail += f"\n\n{log_excerpt}"
            messagebox.showerror("Test Play Failed", detail, parent=self.root)
        else:
            self.set_status("Test Play closed; temporary game files removed.")
        if isinstance(coverage, dict):
            self._show_coverage_report(coverage)

    def _stop_test_play(self):
        if self.test_play_poll_job is not None:
            try:
                self.root.after_cancel(self.test_play_poll_job)
            except tk.TclError:
                pass
            self.test_play_poll_job = None
        process = self.test_play_process
        self.test_play_process = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        self.test_play_coverage_path = None
        self.test_play_log_path = None
        self._cleanup_test_play()

    def test_from_dialogue(self):
        variables, dialogue_ids = self._story_context()
        if not dialogue_ids:
            messagebox.showerror("Test from Dialogue", "No dialogue IDs were found in the story files.", parent=self.root)
            return
        try:
            root_document = yaml.safe_load(self.story_editor.get_text()) if yaml is not None else {}
        except Exception:
            root_document = {}
        preferred_start = root_document.get("start") if isinstance(root_document, dict) else None
        if not isinstance(preferred_start, str) or preferred_start not in dialogue_ids:
            preferred_start = sorted(dialogue_ids)[0]

        window = tk.Toplevel(self.root)
        window.title("Test from Dialogue")
        window.transient(self.root)
        window.resizable(True, True)
        window.geometry("520x510")
        body = ttk.Frame(window, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Starting dialogue").pack(anchor="w")
        dialogue_var = tk.StringVar(value=preferred_start)
        dialogue_box = ttk.Combobox(
            body,
            textvariable=dialogue_var,
            values=sorted(dialogue_ids),
            state="readonly",
        )
        dialogue_box.pack(fill="x", pady=(4, 12))
        ttk.Label(
            body,
            text="Starting variable values (JSON object). Leave values at their story defaults or change them for this test.",
            wraplength=480,
        ).pack(anchor="w")
        variables_text = tk.Text(body, height=16, wrap="none", undo=True)
        variables_text.pack(fill="both", expand=True, pady=(5, 12))
        variables_text.insert("1.0", json.dumps(variables, ensure_ascii=False, indent=2))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x")

        def launch_test():
            dialogue_id = dialogue_var.get().strip()
            if dialogue_id not in dialogue_ids:
                messagebox.showerror("Test from Dialogue", "Choose an existing dialogue ID.", parent=window)
                return
            try:
                initial_variables = json.loads(variables_text.get("1.0", "end-1c"))
            except json.JSONDecodeError as error:
                messagebox.showerror("Test from Dialogue", f"Variables must be valid JSON: {error}", parent=window)
                return
            if not isinstance(initial_variables, dict):
                messagebox.showerror("Test from Dialogue", "Variables must be a JSON object.", parent=window)
                return
            unknown = set(initial_variables) - set(variables)
            if unknown:
                messagebox.showerror(
                    "Test from Dialogue",
                    "Unknown story variable(s): " + ", ".join(sorted(unknown)),
                    parent=window,
                )
                return
            for name, value in initial_variables.items():
                default = variables[name]
                numeric_pair = (
                    isinstance(default, (int, float)) and not isinstance(default, bool)
                    and isinstance(value, (int, float)) and not isinstance(value, bool)
                )
                if (
                    value is not None
                    and not isinstance(value, (str, int, float, bool))
                ) or (
                    default is not None
                    and value is not None
                    and type(default) is not type(value)
                    and not numeric_pair
                ):
                    messagebox.showerror(
                        "Test from Dialogue",
                        f"Value for '{name}' must be a scalar matching its declared type.",
                        parent=window,
                    )
                    return
            window.destroy()
            self.test_play(dialogue_id, initial_variables)

        ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="right")
        ttk.Button(buttons, text="Start Test", command=launch_test).pack(side="right", padx=(0, 7))
        dialogue_box.focus_set()

    def test_play(self, start_dialogue=None, initial_variables=None):
        if self.test_play_process is not None and self.test_play_process.poll() is None:
            messagebox.showinfo("Test Play", "A test game is already running.", parent=self.root)
            return
        if not self.save_all(analyze=False):
            return
        errors = self._collect_export_errors()
        if self._show_export_errors("Cannot Start Test Play", errors):
            return
        try:
            temporary, platform, _game_name, executable = self._create_temporary_game()
            self.test_play_tempdir = temporary
            self.test_play_coverage_path = Path(temporary.name) / "editor_coverage.json"
            self.test_play_log_path = Path(temporary.name) / "test_play.log"
            environment = os.environ.copy()
            environment["VN_ENGINE_USER_DATA_DIR"] = str(Path(temporary.name) / "user_data")
            environment["VN_EDITOR_TEST_MODE"] = "1"
            environment["VN_EDITOR_COVERAGE_FILE"] = str(self.test_play_coverage_path)
            environment.pop("VN_ENGINE_PROJECT_DIR", None)
            environment.pop("VN_EDITOR_TEST_START_DIALOGUE", None)
            environment.pop("VN_EDITOR_TEST_VARIABLES", None)
            if start_dialogue is not None:
                environment["VN_EDITOR_TEST_START_DIALOGUE"] = start_dialogue
                environment["VN_EDITOR_TEST_VARIABLES"] = json.dumps(
                    initial_variables or {}, ensure_ascii=False
                )
            workspace_root = self._workspace_source_root()
            source_runtime = workspace_root is not None and executable.resolve() == (workspace_root / "main.py").resolve()
            if source_runtime:
                environment["VN_ENGINE_PROJECT_DIR"] = str(self.project_root)
            command = (
                [sys.executable, str(executable)]
                if executable.suffix.casefold() == ".py"
                else [str(executable)]
            )
            with self.test_play_log_path.open("w", encoding="utf-8") as log_file:
                self.test_play_process = subprocess.Popen(
                    command,
                    cwd=self.project_root if source_runtime else executable.parent,
                    env=environment,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError, subprocess.SubprocessError) as error:
            self.test_play_coverage_path = None
            self.test_play_log_path = None
            self._cleanup_test_play()
            messagebox.showerror("Cannot Start Test Play", f"Could not prepare or start the game: {error}", parent=self.root)
            return

        if source_runtime:
            self.set_status("Test Play running with the workspace engine and isolated test saves. Press F3 in-game to inspect variables.")
        else:
            self.set_status(f"Test Play running in a temporary {platform} build. Press F3 in-game to inspect variables.")
        self.test_play_poll_job = self.root.after(750, self._poll_test_play)

    def _show_coverage_report(self, coverage):
        graph = self._load_story_graph()
        if graph is None:
            return
        visited = set(coverage.get("visited_dialogues", []))
        selected = {
            (item.get("dialogue"), item.get("target"))
            for item in coverage.get("choices", [])
            if isinstance(item, dict)
        }
        dialogues = graph["dialogues"]
        unreachable = set(graph["unreachable"])
        visited_count = len(visited & set(dialogues))
        choice_count = sum(
            len({
                option.get("target")
                for option in dialogue.get("options", [])
                if isinstance(option, dict)
            })
            for dialogue in dialogues.values()
            if isinstance(dialogue.get("options", []), list)
        )
        selected_count = len({
            (dialogue_id, option.get("target"))
            for dialogue_id, dialogue in dialogues.items()
            for option in dialogue.get("options", [])
            if isinstance(option, dict)
            and (dialogue_id, option.get("target")) in selected
        })

        window = tk.Toplevel(self.root)
        window.title("Test Play Coverage")
        window.geometry("820x600")
        window.minsize(620, 380)
        summary = ttk.Frame(window, padding=(10, 9))
        summary.pack(fill="x")
        ended = "story finished" if coverage.get("finished") else "session ended early"
        ttk.Label(
            summary,
            text=(
                f"Visited dialogues: {visited_count}/{len(dialogues)}    "
                f"Selected branches: {selected_count}/{choice_count}    "
                f"Unreachable: {len(unreachable)}    ({ended})"
            ),
        ).pack(anchor="w")

        body = ttk.Frame(window, padding=(10, 0, 10, 10))
        body.pack(fill="both", expand=True)
        tree = ttk.Treeview(body, columns=("kind", "item", "result"), show="headings")
        tree.heading("kind", text="Coverage")
        tree.heading("item", text="Dialogue / Branch")
        tree.heading("result", text="Result")
        tree.column("kind", width=115, stretch=False)
        tree.column("item", width=530, stretch=True)
        tree.column("result", width=135, stretch=False)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for dialogue_id, dialogue in dialogues.items():
            tree.insert(
                "", "end", values=(
                    "Dialogue", dialogue_id,
                    (
                        "Unreachable" if dialogue_id in unreachable
                        else "Visited" if dialogue_id in visited else "Not visited"
                    ),
                ),
            )
            options = dialogue.get("options", [])
            if (
                not dialogue.get("next")
                and not options
                and not dialogue.get("call")
                and not dialogue.get("return")
            ):
                tree.insert(
                    "", "end", values=(
                        "Ending / Return", dialogue_id,
                        "Reached" if dialogue_id in visited else "Not reached",
                    ),
                )
            if isinstance(options, list):
                for option in options:
                    if not isinstance(option, dict):
                        continue
                    label = option.get("label", "(unnamed choice)")
                    if isinstance(label, dict):
                        label = label.get(
                            graph["default_locale"],
                            next(iter(label.values()), "(unnamed choice)"),
                        )
                    target = option.get("target", "?")
                    was_selected = (dialogue_id, target) in selected
                    branch = f"{dialogue_id}: {label} -> {target}"
                    if option.get("condition") is not None:
                        branch += " [conditional]"
                    tree.insert(
                        "", "end", values=(
                            "Branch", branch,
                            "Selected" if was_selected else "Not selected",
                        ),
                    )
        ttk.Button(window, text="Close", command=window.destroy).pack(
            anchor="e", padx=10, pady=(0, 10)
        )

    def export_game(self):
        from export_pipeline import PLATFORMS, safe_project_name

        if not self.save_all():
            return
        errors = self._collect_export_errors()
        if self._show_export_errors("Cannot Export Project", errors):
            return
        try:
            values = json.loads(self.project_editor.get_text())
        except json.JSONDecodeError as error:
            messagebox.showerror("Cannot Export Project", f"Invalid project.json: {error}", parent=self.root)
            return
        game_name = safe_project_name(values.get("name", "Visual Novel"))
        template_dir = self._template_directory()

        dialog = tk.Toplevel(self.root)
        dialog.title("Export Game")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Target platform").grid(row=0, column=0, sticky="w", pady=(0, 7))
        platform_var = tk.StringVar(value="windows")
        platform_box = ttk.Combobox(
            body, textvariable=platform_var, values=sorted(PLATFORMS), state="readonly", width=18
        )
        platform_box.grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, 7))
        ttk.Label(body, text="Local templates folder").grid(row=1, column=0, sticky="w", pady=7)
        templates_var = tk.StringVar(value=str(template_dir))
        ttk.Entry(body, textvariable=templates_var, width=52).grid(row=1, column=1, sticky="ew", pady=7)
        ttk.Button(
            body,
            text="Browse…",
            command=lambda: self._browse_export_folder(dialog, templates_var),
        ).grid(row=1, column=2, padx=(6, 0), pady=7)
        ttk.Label(body, text="Output file").grid(row=2, column=0, sticky="w", pady=7)
        output_var = tk.StringVar(
            value=str(self.project_root / "exports" / f"{game_name}-{platform_var.get()}.zip")
        )
        ttk.Entry(body, textvariable=output_var, width=52).grid(row=2, column=1, sticky="ew", pady=7)
        ttk.Button(
            body,
            text="Browse…",
            command=lambda: self._browse_export_output(dialog, output_var, game_name, platform_var.get()),
        ).grid(row=2, column=2, padx=(6, 0), pady=7)
        ttk.Label(
            body,
            text="Templates download from GitHub Releases on demand and are cached. Android uses the selected release (the editor's version is recommended) to build a fresh project-specific archive; it requires Node.js/npm, a Java JDK, the Android SDK, and internet access.",
            foreground="#707987",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(2, 10))
        android_options = ttk.LabelFrame(body, text="Android options", padding=8)
        android_options.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        android_release_label = ttk.Label(android_options, text="Runtime release")
        android_release_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        android_release_var = tk.StringVar()
        android_release_box = ttk.Combobox(
            android_options,
            textvariable=android_release_var,
            values=(),
            state="readonly",
            width=24,
        )
        android_release_box.grid(row=0, column=1, sticky="ew")
        android_options.columnconfigure(1, weight=1)
        android_options.grid_remove()
        release_tags = None
        sign_release_var = tk.BooleanVar(value=False)
        sign_release_check = ttk.Checkbutton(
            body,
            text="Sign release package (uses signing credentials from the environment)",
            variable=sign_release_var,
        )
        sign_release_check.grid(row=5, column=0, columnspan=3, sticky="w", pady=(0, 8))

        def update_signing_option(*_args):
            supported = platform_var.get() in {"windows", "macos", "android"}
            sign_release_check.configure(state="normal" if supported else "disabled")
            if not supported:
                sign_release_var.set(False)

        def update_android_runtime_choices(*_args):
            nonlocal release_tags
            if platform_var.get() != "android":
                android_options.grid_remove()
                return
            android_options.grid()
            if release_tags is None:
                try:
                    from template_repository import list_template_release_tags

                    release_tags = list_template_release_tags()
                except (OSError, ValueError, RuntimeError) as error:
                    messagebox.showerror(
                        "Android Runtime Versions",
                        f"Could not load VN Engine releases from GitHub:\n{error}",
                        parent=dialog,
                    )
                    android_release_box.configure(values=())
                    android_release_var.set("")
                    return
            if not release_tags:
                android_release_box.configure(values=())
                android_release_var.set("")
                messagebox.showerror(
                    "Android Runtime Versions",
                    "No published GitHub release contains a Web runtime template.",
                    parent=dialog,
                )
                return
            android_release_box.configure(values=release_tags)
            editor_tag = self._editor_release_tag()
            recommended = editor_tag if editor_tag in release_tags else release_tags[0]
            android_release_label.configure(text=f"Runtime release (recommended: {recommended})")
            if android_release_var.get() not in release_tags:
                android_release_var.set(recommended)

        button_row = ttk.Frame(body)
        button_row.grid(row=6, column=0, columnspan=3, sticky="e")
        ttk.Button(button_row, text="Cancel", command=dialog.destroy).pack(side="right")

        def run_export():
            output_value = output_var.get().strip()
            template_value = templates_var.get().strip()
            platform = platform_var.get()
            if not output_value or not template_value:
                messagebox.showerror("Export Game", "Choose a templates folder and output file.", parent=dialog)
                return
            android_release_tag = android_release_var.get() if platform == "android" else None
            if platform == "android" and not android_release_tag:
                messagebox.showerror(
                    "Export Game",
                    "Select an available Android runtime release.",
                    parent=dialog,
                )
                return
            target = Path(output_value)
            output_extension = ".apk" if platform == "android" else ".zip"
            if target.suffix.casefold() != output_extension:
                target = target.with_suffix(output_extension)
            if target.exists() and not messagebox.askyesno(
                "Replace Export",
                f"Replace the existing export?\n{target}",
                parent=dialog,
            ):
                return
            try:
                from export_pipeline import export_project

                exported = export_project(
                    self.project_root,
                    self.project_file,
                    Path(template_value),
                    platform,
                    target,
                    android_release_tag,
                    sign_release=sign_release_var.get(),
                )
            except (OSError, ValueError, RuntimeError, json.JSONDecodeError, subprocess.SubprocessError) as error:
                messagebox.showerror("Export Game", str(error), parent=dialog)
                return
            dialog.destroy()
            self.set_status(f"Exported {platform} game: {exported}")
            output_description = "Android APK created" if platform == "android" else "Game ZIP created"
            messagebox.showinfo("Export Complete", f"{output_description}:\n{exported}", parent=self.root)

        ttk.Button(button_row, text="Export", command=run_export).pack(side="right", padx=(0, 7))

        def update_output_name(*_args):
            current = Path(output_var.get())
            extension = ".apk" if platform_var.get() == "android" else ".zip"
            output_var.set(str(current.with_name(f"{game_name}-{platform_var.get()}{extension}")))

        platform_var.trace_add("write", update_output_name)
        platform_var.trace_add("write", update_android_runtime_choices)
        platform_var.trace_add("write", update_signing_option)
        platform_box.bind("<<ComboboxSelected>>", update_output_name)
        dialog.bind("<Return>", lambda _event: run_export())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.columnconfigure(0, weight=0)
        dialog.columnconfigure(1, weight=1)
        dialog.grab_set()
        dialog.wait_visibility()
        dialog.focus_set()
        update_android_runtime_choices()
        update_signing_option()

    def _browse_export_folder(self, parent, variable):
        selected = filedialog.askdirectory(
            title="Choose local templates folder",
            initialdir=variable.get() or self.project_root,
            parent=parent,
        )
        if selected:
            variable.set(selected)

    def _browse_export_output(self, parent, variable, game_name, platform):
        extension = ".apk" if platform == "android" else ".zip"
        file_type = "Android APK" if platform == "android" else "ZIP archive"
        selected = filedialog.asksaveasfilename(
            title="Save exported game",
            initialdir=self.project_root,
            initialfile=f"{game_name}-{platform}{extension}",
            defaultextension=extension,
            filetypes=((file_type, f"*{extension}"),),
            parent=parent,
        )
        if selected:
            variable.set(selected)

    def close(self):
        if not self._confirm_discard_or_save("closing the editor"):
            return
        self._stop_test_play()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="VN Engine story and project editor")
    parser.add_argument("--project-dir", type=Path, help="Project folder containing data/ and assets/")
    args = parser.parse_args()
    package_root = editor_package_root(Path(sys.argv[0]))
    try:
        last_project = None if args.project_dir is not None else _load_last_project()
        root_path = _initial_project_root(args.project_dir, Path.cwd(), package_root, last_project)
    except (OSError, RuntimeError, ValueError) as error:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            APP_TITLE,
            f"Could not prepare the project:\n{error}",
            parent=root,
        )
        root.destroy()
        return 1
    root = tk.Tk()
    VNEditorApp(root, root_path)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


