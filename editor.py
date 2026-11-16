"""Standalone authoring editor for VN Engine projects.

Run ``python editor.py`` from a project folder, or pass ``--project-dir``.
Without a project folder, the editor installs a starter project in Documents.
The interface uses Tkinter; PyYAML enables YAML parsing and live diagnostics.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from difflib import get_close_matches
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import queue
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any
from zipfile import ZipFile

from export_pipeline import PLATFORMS, export_project, safe_project_name
from template_repository import install_starter_project, list_template_release_tags

try:
    import yaml
except ImportError:
    yaml = None


APP_TITLE = "VN Engine Editor"
STORY_TOP_KEYS = {"title", "start", "includes", "variables", "character_defaults", "dialogues"}
DIALOGUE_KEYS = {"chapter", "speaker", "text", "next", "options", "actions", "active_character", "voice"}
OPTION_KEYS = {"label", "target", "condition"}
CONDITION_KEYS = {"var", "op", "value", "all", "any", "not"}
ACTION_TYPES = {
    "set", "add", "subtract", "background", "clear_background", "music", "stop_music",
    "sound", "show_character", "animate_character", "hide_character", "clear_characters", "fade", "shake", "autosave",
}
ACTION_FIELDS = {
    "set": {"type", "var", "value"},
    "add": {"type", "var", "value"},
    "subtract": {"type", "var", "value"},
    "background": {"type", "image"},
    "clear_background": {"type"},
    "music": {"type", "track"},
    "stop_music": {"type"},
    "sound": {"type", "name"},
    "show_character": {"type", "name", "look", "expression", "position"},
    "animate_character": {"type", "name", "frames", "look", "position", "frame_duration", "loop"},
    "hide_character": {"type", "name"},
    "clear_characters": {"type"},
    "fade": {"type", "direction", "duration", "color"},
    "shake": {"type", "duration", "intensity"},
    "autosave": {"type"},
}
REQUIRED_ACTION_FIELDS = {
    "set": {"var", "value"},
    "add": {"var", "value"},
    "subtract": {"var", "value"},
    "background": {"image"},
    "music": {"track"},
    "sound": {"name"},
    "show_character": {"name", "expression"},
    "animate_character": {"name", "frames"},
    "hide_character": {"name"},
    "fade": {"direction"},
}
CONDITION_OPERATORS = {"==", "!=", "<", "<=", ">", ">=", "in", "not_in"}
CHARACTER_POSITIONS = {"far_left", "left", "center", "right", "far_right"}
MENU_ACTIONS = {
    "new_game", "continue_game", "open_load_slots", "open_save_slots", "open_settings",
    "open_credits", "quit", "resume", "return_to_main_menu", "back", "adjust_setting",
    "toggle_setting", "save_slot", "load_slot", "delete_selected_slot",
}
SETTING_NAMES = {"type_speed", "music_volume", "sfx_volume", "fullscreen", "ui_scale"}
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


DEFAULT_PROJECT = _literal_from_engine("engine/project.py", "DEFAULT_PROJECT") or {
    "name": "Visual Novel",
    "story": "story.yaml",
    "icon": None,
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
    "menus": {
        "main": {"title": "Visual Novel", "items": [
            {"label": "New Game", "action": "new_game"},
            {"label": "Continue", "action": "continue_game"},
            {"label": "Load Game", "action": "open_load_slots"},
            {"label": "Settings", "action": "open_settings"},
            {"label": "Credits", "action": "open_credits"},
            {"label": "Quit", "action": "quit"},
        ]},
        "pause": {"title": "Paused", "items": [
            {"label": "Resume", "action": "resume"},
            {"label": "Save Game", "action": "open_save_slots"},
            {"label": "Load Game", "action": "open_load_slots"},
            {"label": "Settings", "action": "open_settings"},
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
    "theme": {},
}
DEFAULT_THEME = _literal_from_engine("engine/theme.py", "DEFAULT_THEME") or {
    "colors": {"background": [30, 30, 45], "text": [230, 230, 230], "muted": [170, 170, 180],
               "normal": [18, 18, 29], "hover": [73, 50, 65],
               "selected": [45, 92, 78], "border": [112, 86, 101],
               "accent": [233, 79, 88], "panel": [0, 0, 0, 128]},
    "fonts": {"menu": None, "title": None, "item_size": 20,
              "detail_size": 16, "title_size": 30},
    "menu": {"layout": "centered", "background": None, "width": 860,
             "x": None, "row_height": 56, "row_gap": 9, "title_y": 112,
             "top": 190, "border_radius": 8},
    "slot": {"layout": "list", "normal": None, "hovered": None,
             "width": 900, "row_height": 82, "row_gap": 8,
             "icon_width": 30, "icon_height": 72, "text_offset": 62},
    "sounds": {"hover": "sounds/hover_button.wav", "click": "sounds/click_button.wav",
               "cancel": "sounds/click_button.wav", "load": "sounds/click_button.wav"},
}
DEFAULT_THEME.setdefault("game_fonts", {"text": None, "name": None, "button": None})
DEFAULT_THEME.setdefault("menu", {}).setdefault("right_margin", 48)
DEFAULT_THEME.setdefault("textbox", {"background": None, "color": None})


def merge_defaults(defaults: Any, overrides: Any):
    if isinstance(defaults, dict) and isinstance(overrides, dict):
        result = dict(defaults)
        for key, value in overrides.items():
            result[key] = merge_defaults(result[key], value) if key in result else value
        return result
    return overrides


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


def _editor_release_tag(package_root: Path) -> str | None:
    version_files = (
        package_root / "engine-version.txt",
        Path(__file__).resolve().parent / "engine" / "data" / "version.txt",
    )
    for version_file in version_files:
        if not version_file.is_file():
            continue
        version = version_file.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
            raise ValueError(f"Invalid editor version in {version_file}: {version!r}")
        return f"v{version}"
    return None


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
        self._suggestion_cache = {}
        self._scan_characters()

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

    def character_names(self):
        return sorted((item["name"] for item in self.characters.values()), key=str.casefold)

    def find_character(self, name):
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
                    category = root / folder
                    if category.is_dir():
                        try:
                            for path in category.rglob("*"):
                                if path.is_file():
                                    rel = path.relative_to(category).as_posix()
                                    if path.stem.casefold() == wanted or Path(rel).with_suffix("").as_posix().casefold() == wanted:
                                        return True
                        except OSError:
                            pass
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
        for required in ("speaker", "text"):
            if not isinstance(dialogue.get(required), str):
                diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.{required} must be a string.", _line_of_key(source, required, line)))
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
            if not isinstance(option.get("label"), str) or not option.get("label"):
                diagnostics.append(Diagnostic("error", "Choice label must be a non-empty string.", _line_of_key(source, "label", option_line)))
            target = option.get("target")
            if not isinstance(target, str):
                diagnostics.append(Diagnostic("error", "Choice target must be a dialogue ID.", _line_of_key(source, "target", option_line)))
            else:
                targets.append((target, _line_of_key(source, "target", option_line), f"dialogues.{dialogue_id}.options"))
            if "condition" in option:
                diagnostics.extend(_validate_condition(option["condition"], variables, source, option_line, f"dialogues.{dialogue_id}.options.condition"))

        actions = dialogue.get("actions", [])
        if not isinstance(actions, list):
            diagnostics.append(Diagnostic("error", f"dialogues.{dialogue_id}.actions must be a list.", _line_of_key(source, "actions", line)))
            actions = []
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
            {"type", "var", "value", "image", "track", "name", "look", "expression", "frames", "position", "direction", "duration", "frame_duration", "loop", "color", "intensity"},
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
    elif kind in {"background", "sound", "music"}:
        field, category = {"background": ("image", "image"), "sound": ("name", "sound"), "music": ("track", "music")}[kind]
        asset_name = action.get(field)
        if not isinstance(asset_name, str) or not asset_name:
            result.append(Diagnostic("error", f"Action '{kind}' requires a non-empty '{field}'.", _line_of_key(source, field, action_line)))
        elif not catalog.asset_exists(category, asset_name):
            result.append(Diagnostic("error", f"Missing {category} asset '{asset_name}'. Check project assets and built-in engine assets.", _line_of_key(source, field, action_line)))
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
    values = merge_defaults(DEFAULT_PROJECT, raw)
    diagnostics: list[Diagnostic] = []
    _validate_project_object(values, raw, source, diagnostics)
    _validate_project_assets(values, catalog, source, diagnostics)
    story_name = values.get("story")
    if isinstance(story_name, str):
        story_path = Path(story_name)
        if not story_path.is_absolute():
            story_path = catalog.data_dir / story_path
        if not story_path.is_file():
            diagnostics.append(Diagnostic("error", f"Configured story file was not found: {story_path}.", _line_of_key(source, "story")))
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
    for key, child in raw.items():
        if key != "theme" and key in DEFAULT_PROJECT and isinstance(child, dict) and isinstance(DEFAULT_PROJECT[key], dict):
            check_unknown(child, DEFAULT_PROJECT[key], f"project.json.{key}", _line_of_key(source, key))
    theme = raw.get("theme", {})
    if isinstance(theme, dict):
        check_unknown(theme, DEFAULT_THEME, "theme", _line_of_key(source, "theme"))
        menu_theme = theme.get("menu")
        if isinstance(menu_theme, dict) and menu_theme.get("layout") not in (None, "centered", "left", "right"):
            diagnostics.append(Diagnostic("error", "theme.menu.layout must be centered, left, or right.", _line_of_key(source, "layout", _line_of_key(source, "menu"))))
        slot_theme = theme.get("slot")
        if isinstance(slot_theme, dict) and slot_theme.get("layout") not in (None, "list", "tape"):
            diagnostics.append(Diagnostic("error", "theme.slot.layout must be list or tape.", _line_of_key(source, "layout", _line_of_key(source, "slot"))))
        textbox_theme = theme.get("textbox")
        if isinstance(textbox_theme, dict):
            color = textbox_theme.get("color")
            if color is not None and (
                not isinstance(color, list) or len(color) not in {3, 4}
                or any(not isinstance(channel, int) or isinstance(channel, bool) or not 0 <= channel <= 255 for channel in color)
            ):
                diagnostics.append(Diagnostic("error", "theme.textbox.color must be an RGB or RGBA array with values from 0 to 255.", _line_of_key(source, "color", _line_of_key(source, "textbox"))))
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
                if action == "toggle_setting" and setting != "fullscreen":
                    diagnostics.append(Diagnostic("warning", "toggle_setting only changes fullscreen; use adjust_setting for speed, volume, or UI size.", _line_of_key(source, "action", item_line)))

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
    intro = values.get("intro", {})
    if isinstance(intro, dict):
        for key in ("credit_image", "warning_image", "headphones_image"):
            value = intro.get(key)
            if value and not catalog.asset_exists("image", value):
                diagnostics.append(Diagnostic("error", f"Missing intro image asset '{value}'.", _line_of_key(source, key, _line_of_key(source, "intro"))))

    theme = values.get("theme", {})
    if not isinstance(theme, dict):
        return
    for group, keys, kind in (
        ("fonts", ("menu", "title"), "font"),
        ("game_fonts", ("text", "name", "button"), "font"),
        ("menu", ("background",), "image"),
        ("slot", ("normal", "hovered"), "image"),
        ("textbox", ("background",), "image"),
        ("sounds", ("hover", "click", "cancel", "load"), "sound"),
    ):
        values_group = theme.get(group, {})
        if not isinstance(values_group, dict):
            continue
        for key in keys:
            name = values_group.get(key)
            if name and not catalog.asset_exists(kind, name):
                diagnostics.append(Diagnostic("error", f"Missing theme {kind} asset '{name}'.", _line_of_key(source, key, _line_of_key(source, group, _line_of_key(source, "theme")))))


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

        self.gutter = tk.Canvas(self, width=48, highlightthickness=0, background="#20242d")
        self.gutter.pack(side="left", fill="y")
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
        self.text.pack(side="top", fill="both", expand=True)
        self.vscroll.pack(side="right", fill="y")
        self.hscroll.pack(side="bottom", fill="x")

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
        return self.text.get("1.0", "end-1c")

    def set_text(self, content: str):
        self.text.delete("1.0", "end")
        if content:
            self.text.insert("1.0", content)
        self.text.edit_modified(False)
        self.dirty = False
        self.highlight()
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
        self._highlight_job = None
        for tag in ("yaml_key", "json_key", "string", "number", "keyword", "punctuation", "comment"):
            self.text.tag_remove(tag, "1.0", "end")
        for line_no, line in enumerate(self.get_text().splitlines(), 1):
            base = f"{line_no}.0"
            if self.document_kind == "story":
                self._highlight_yaml_line(line_no, line, base)
            else:
                self._highlight_json_line(line_no, line, base)
        self.app.apply_diagnostic_marks(self)

    def _highlight_yaml_line(self, line_no, line, base):
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
            start = key.start(1)
            end = key.end(1)
            self.text.tag_add("yaml_key", f"{line_no}.{start}", f"{line_no}.{end}")
        self._highlight_quoted(line_no, line, content_end)
        for match in re.finditer(r"(?<![\w./-])(?:true|false|null|yes|no|on|off)(?![\w./-])", line[:content_end], re.I):
            self.text.tag_add("keyword", f"{line_no}.{match.start()}", f"{line_no}.{match.end()}")
        for match in re.finditer(r"(?<![\w])[-+]?\d+(?:\.\d+)?(?![\w])", line[:content_end]):
            self.text.tag_add("number", f"{line_no}.{match.start()}", f"{line_no}.{match.end()}")
        for match in re.finditer(r"[\[\]{},:]", line[:content_end]):
            self.text.tag_add("punctuation", f"{line_no}.{match.start()}", f"{line_no}.{match.end()}")
        if comment_start is not None:
            self.text.tag_add("comment", f"{line_no}.{comment_start}", f"{line_no}.end")

    def _highlight_json_line(self, line_no, line, base):
        for match in re.finditer(r'"(?:\\.|[^"\\])*"(?=\s*:)', line):
            self.text.tag_add("json_key", f"{line_no}.{match.start()}", f"{line_no}.{match.end()}")
        self._highlight_quoted(line_no, line, len(line))
        for match in re.finditer(r'\b(?:true|false|null)\b', line):
            self.text.tag_add("keyword", f"{line_no}.{match.start()}", f"{line_no}.{match.end()}")
        for match in re.finditer(r"-?\b\d+(?:\.\d+)?\b", line):
            self.text.tag_add("number", f"{line_no}.{match.start()}", f"{line_no}.{match.end()}")
        for match in re.finditer(r"[\[\]{},:]", line):
            self.text.tag_add("punctuation", f"{line_no}.{match.start()}", f"{line_no}.{match.end()}")

    def _highlight_quoted(self, line_no, line, end):
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
                    self.text.tag_add("string", f"{line_no}.{start}", f"{line_no}.{index + 1}")
                    quote = None

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
        if self.document_kind == "project" and stripped.startswith(("}", "]")):
            indent = indent[:-2] if len(indent) >= 2 else ""
        elif line.rstrip().endswith(":") or line.rstrip().endswith("-") or (
            self.document_kind == "project" and line.rstrip().endswith(("{", "["))
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
        if self.document_kind == "project":
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
        self.story_file = self.project_root / "data" / "story.yaml"
        self.project_buffer = ""
        self.story_buffer = ""
        self.live_diagnostics: dict[str, list[Diagnostic]] = {"story": [], "project": []}
        self.engine_diagnostics: list[Diagnostic] = []
        self._analysis_jobs = {}
        self._completion_jobs = {}
        self._asset_catalog = None
        self._asset_catalog_key = None
        self._asset_refresh_job = None
        self._loading = False
        self.story_editors: dict[Path, CodeEditor] = {}
        self.markdown_texts = {}
        self.markdown_paths = {}
        self.find_window = None
        self.find_entry = None
        self.find_case_sensitive = None
        self.terminal_process = None
        self.terminal_entry = None
        self.terminal_location = str(self.project_root)
        self.terminal_name = self._available_terminal_name()
        self.terminal_queue = queue.Queue()
        self.terminal_generation = 0
        self.terminal_poll_job = None
        self.terminal_prompt = f"{self.terminal_name} {self.project_root}> "
        self.test_play_process = None
        self.test_play_tempdir = None
        self.test_play_poll_job = None

        self.root.title(f"{APP_TITLE} — {self.project_root.name}")
        self.root.geometry("1320x880")
        self.root.minsize(940, 620)
        self._build_ui()
        self.load_project(self.project_root)
        self.root.bind("<Control-s>", lambda _event: self.save_active())
        self.root.bind("<Control-Shift-S>", lambda _event: self.save_all())
        self.root.bind("<Control-f>", lambda _event: self.show_find())
        self.root.bind("<F5>", lambda _event: self.validate_with_engine())
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook.Tab", padding=(14, 7))
        style.configure("Treeview", rowheight=23)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

        toolbar = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        toolbar.pack(side="top", fill="x")
        ttk.Button(toolbar, text="Open Project…", command=self.choose_project).pack(side="left")
        ttk.Button(toolbar, text="Save", command=self.save_active).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Save All", command=self.save_all).pack(side="left", padx=(5, 0))
        ttk.Button(toolbar, text="Validate Story (F5)", command=self.validate_with_engine).pack(side="left", padx=(18, 0))
        ttk.Button(toolbar, text="Test Play", command=self.test_play).pack(side="left", padx=(5, 0))
        ttk.Button(toolbar, text="Export Game…", command=self.export_game).pack(side="left", padx=(5, 0))
        ttk.Button(toolbar, text="Refresh Assets", command=self.refresh_asset_tree).pack(side="left", padx=(5, 0))
        ttk.Button(toolbar, text="Find (Ctrl+F)", command=self.show_find).pack(side="left", padx=(5, 0))
        self.project_label = ttk.Label(toolbar, text="", anchor="e")
        self.project_label.pack(side="right", fill="x", expand=True, padx=(12, 4))

        main = ttk.Panedwindow(self.root, orient="horizontal")
        main.pack(side="top", fill="both", expand=True, padx=8, pady=(3, 4))
        left = ttk.Frame(main, width=300)
        right = ttk.Frame(main)
        main.add(left, weight=0)
        main.add(right, weight=1)

        right_split = ttk.Panedwindow(right, orient="vertical")
        right_split.pack(fill="both", expand=True)
        document_area = ttk.Frame(right_split)
        terminal_frame = ttk.LabelFrame(
            right_split, text=f"{self.terminal_name} — project folder", padding=5, height=190
        )
        right_split.add(document_area, weight=5)
        right_split.add(terminal_frame, weight=1)

        asset_header = ttk.Frame(left)
        asset_header.pack(fill="x", pady=(0, 4))
        ttk.Label(asset_header, text="Asset hierarchy", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Button(asset_header, text="Insert", width=7, command=self.insert_selected_asset).pack(side="right")
        ttk.Label(left, text="Double-click a file to insert its reference.", foreground="#707987").pack(anchor="w", pady=(0, 5))
        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill="both", expand=True)
        self.asset_tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.asset_tree.yview)
        self.asset_tree.configure(yscrollcommand=tree_scroll.set)
        self.asset_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.asset_tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.asset_tree.bind("<Double-1>", lambda _event: self.insert_selected_asset())
        self.asset_tree.bind("<Return>", lambda _event: self.insert_selected_asset())

        self.notebook = ttk.Notebook(document_area)
        self.notebook.pack(fill="both", expand=True)
        self.story_editor = CodeEditor(self.notebook, self, "story")
        self.project_editor = CodeEditor(self.notebook, self, "project")
        self.story_editor.story_path = self.story_file
        self.story_editors = {self.story_file: self.story_editor}
        self.notebook.add(self.story_editor, text="story.yaml")
        self.notebook.add(self.project_editor, text="project.json")
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

        terminal_toolbar = ttk.Frame(terminal_frame)
        terminal_toolbar.pack(side="top", fill="x", pady=(0, 4))
        ttk.Button(terminal_toolbar, text="Clear", command=self.clear_terminal).pack(side="right")
        ttk.Button(terminal_toolbar, text="Restart", command=self.restart_terminal).pack(side="right", padx=(0, 5))
        terminal_body = ttk.Frame(terminal_frame)
        terminal_body.pack(fill="both", expand=True)
        self.terminal_output = tk.Text(
            terminal_body,
            height=7,
            wrap="word",
            font=("Consolas", 10),
            background="#11151c",
            foreground="#d8dee9",
            insertbackground="#ffffff",
            relief="flat",
            padx=7,
            pady=5,
            state="disabled",
        )
        terminal_scroll = ttk.Scrollbar(terminal_body, orient="vertical", command=self.terminal_output.yview)
        self.terminal_output.configure(yscrollcommand=terminal_scroll.set)
        self.terminal_output.pack(side="left", fill="both", expand=True)
        terminal_scroll.pack(side="right", fill="y")
        self.terminal_output.bind("<Button-1>", self._focus_terminal_input)
        self.terminal_history = []
        self.terminal_history_index = 0

        self.status = ttk.Label(self.root, text="", anchor="w", relief="sunken", padding=(7, 4))
        self.status.pack(side="bottom", fill="x")

    def _refresh_markdown_tabs(self):
        for frame in list(self.markdown_texts):
            try:
                self.notebook.forget(frame)
                frame.destroy()
            except tk.TclError:
                pass
        self.markdown_texts.clear()
        self.markdown_paths.clear()

        paths = []
        seen = set()
        for folder in (self.editor_home, self.editor_home / "docs", self.project_root, self.project_root / "docs"):
            if not folder.is_dir():
                continue
            try:
                children = sorted(folder.iterdir(), key=lambda item: item.name.casefold())
            except OSError:
                continue
            for path in children:
                if path.is_file() and path.suffix.casefold() == ".md":
                    resolved = path.resolve()
                    if resolved not in seen:
                        paths.append(resolved)
                        seen.add(resolved)

        labels = [path.name for path in paths]
        for index, path in enumerate(paths):
            if labels.count(path.name) > 1:
                try:
                    labels[index] = path.relative_to(self.editor_home).as_posix()
                except ValueError:
                    labels[index] = path.relative_to(self.project_root).as_posix()

        for path, label in zip(paths, labels):
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            frame = ttk.Frame(self.notebook)
            body = ttk.Frame(frame)
            body.pack(fill="both", expand=True)
            text = tk.Text(
                body,
                wrap="word",
                font=("Consolas", 10),
                background="#171a21",
                foreground="#d8dee9",
                insertbackground="#f8f8f2",
                selectbackground="#3b4d65",
                relief="flat",
                padx=12,
                pady=10,
                state="normal",
            )
            scroll = ttk.Scrollbar(body, orient="vertical", command=text.yview)
            text.configure(yscrollcommand=scroll.set)
            text.insert("1.0", content)
            text.tag_configure("search_match", background="#5a4b22", foreground="#fff2b0")
            text.tag_configure("search_current", background="#b06d19", foreground="#ffffff")
            text.configure(state="disabled")
            text.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            self.notebook.add(frame, text=label)
            self.markdown_texts[frame] = text
            self.markdown_paths[frame] = path

    @staticmethod
    def _available_terminal_name():
        if os.name == "nt":
            return "PowerShell"
        configured = os.environ.get("SHELL", "")
        if Path(configured).name in {"bash", "zsh", "sh", "dash"} and Path(configured).is_file():
            return Path(configured).name
        for candidate in ("bash", "zsh", "sh"):
            if shutil.which(candidate):
                return candidate
        return "Shell"

    def _start_terminal(self):
        self._stop_terminal()
        self.terminal_generation += 1
        generation = self.terminal_generation

        if os.name == "nt":
            terminal = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
            if not terminal:
                windows_root = Path(os.environ.get("SystemRoot", "C:/Windows"))
                candidate = windows_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
                if candidate.is_file():
                    terminal = str(candidate)
            if not terminal:
                self._append_terminal("PowerShell was not found. The terminal requires Windows PowerShell or pwsh.\n")
                return
            self.terminal_name = "PowerShell"
            location = str(self.project_root).replace("'", "''")
            script = f"""
$utf8 = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath '{location}'
[Console]::Out.WriteLine('__VN_EDITOR_PROMPT__' + (Get-Location).Path)
while ($true) {{
    $commandLine = [Console]::In.ReadLine()
    if ($null -eq $commandLine -or $commandLine -eq '__VN_EDITOR_EXIT__') {{ break }}
    try {{
        $result = Invoke-Expression $commandLine 2>&1
        if ($null -ne $result) {{ [Console]::Out.Write(($result | Out-String -Width 200)) }}
    }} catch {{
        $errorText = $_ | Out-String -Width 200
        [Console]::Out.WriteLine($errorText)
    }}
    [Console]::Out.WriteLine('__VN_EDITOR_PROMPT__' + (Get-Location).Path)
}}
"""
            command = [terminal, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
        else:
            configured = os.environ.get("SHELL", "")
            if Path(configured).name in {"bash", "zsh", "sh", "dash"} and Path(configured).is_file():
                terminal = configured
            else:
                terminal = next((shutil.which(name) for name in ("bash", "zsh", "sh") if shutil.which(name)), None)
            if not terminal:
                self._append_terminal("No bash, zsh, or sh shell was found for the command pane.\n")
                return
            self.terminal_name = Path(terminal).name
            script = (
                f"cd -- {shlex.quote(str(self.project_root))}\n"
                "printf '__VN_EDITOR_PROMPT__%s\\n' \"$PWD\"\n"
                "while IFS= read -r commandLine; do\n"
                "    [ \"$commandLine\" = '__VN_EDITOR_EXIT__' ] && break\n"
                "    eval \"$commandLine\" 2>&1\n"
                "    printf '__VN_EDITOR_PROMPT__%s\\n' \"$PWD\"\n"
                "done\n"
            )
            if self.terminal_name == "bash":
                command = [terminal, "--noprofile", "--norc", "-c", script]
            elif self.terminal_name == "zsh":
                command = [terminal, "-f", "-c", script]
            else:
                command = [terminal, "-c", script]

        try:
            self.terminal_process = subprocess.Popen(
                command,
                cwd=self.project_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            self.terminal_process = None
            self._append_terminal(f"Could not start {self.terminal_name}: {error}\n")
            return
        self.terminal_prompt = f"{self.terminal_name} {self.project_root}> "
        self._append_terminal(f"\n{self.terminal_name} started in {self.project_root}\n")
        reader = threading.Thread(
            target=self._read_terminal_output,
            args=(self.terminal_process, generation),
            name="VNEditorShellReader",
            daemon=True,
        )
        reader.start()
        self._schedule_terminal_poll()

    def _stop_terminal(self):
        process = self.terminal_process
        self.terminal_process = None
        self.terminal_generation += 1
        if self.terminal_entry is not None:
            self.terminal_entry.destroy()
            self.terminal_entry = None
        if process is None:
            return
        try:
            if process.stdin and process.poll() is None:
                process.stdin.write("__VN_EDITOR_EXIT__\n")
                process.stdin.flush()
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.terminate()
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass

    def _read_terminal_output(self, process, generation):
        try:
            if process.stdout:
                for line in process.stdout:
                    self.terminal_queue.put((generation, line.rstrip("\r\n")))
        except (OSError, ValueError) as error:
            self.terminal_queue.put((generation, f"Shell output error: {error}"))
        finally:
            if process.stdout:
                process.stdout.close()
        self.terminal_queue.put((generation, None))

    def _schedule_terminal_poll(self):
        if self.terminal_poll_job is None:
            self.terminal_poll_job = self.root.after(80, self._drain_terminal_output)

    def _drain_terminal_output(self):
        self.terminal_poll_job = None
        while True:
            try:
                generation, line = self.terminal_queue.get_nowait()
            except queue.Empty:
                break
            if generation != self.terminal_generation:
                continue
            if line is None:
                if self.terminal_process is not None and self.terminal_process.poll() is not None:
                    self.terminal_process = None
                    if self.terminal_entry is not None:
                        self.terminal_entry.destroy()
                        self.terminal_entry = None
                    self._append_terminal("\nShell exited. Use Restart to open it again.\n")
                continue
            if line.startswith("__VN_EDITOR_PROMPT__"):
                location = line[len("__VN_EDITOR_PROMPT__"):]
                self._show_terminal_prompt(location)
            else:
                self._append_terminal(line + "\n")
        if self.terminal_process is not None:
            self._schedule_terminal_poll()

    def _append_terminal(self, text):
        if not hasattr(self, "terminal_output"):
            return
        self.terminal_output.configure(state="normal")
        self.terminal_output.insert("end-1c", text)
        self.terminal_output.see("end")
        self.terminal_output.configure(state="disabled")

    def _show_terminal_prompt(self, location: str):
        self.terminal_location = location
        self.terminal_prompt = f"{self.terminal_name} {location}> "
        self.terminal_output.configure(state="normal")
        self.terminal_output.insert("end-1c", self.terminal_prompt)
        entry = tk.Entry(
            self.terminal_output,
            font=("Consolas", 10),
            background="#11151c",
            foreground="#d8dee9",
            insertbackground="#ffffff",
            selectbackground="#3b4d65",
            selectforeground="#ffffff",
            relief="flat",
            borderwidth=0,
        )
        entry.bind("<Return>", self._send_terminal_command)
        entry.bind("<Up>", self._terminal_history_up)
        entry.bind("<Down>", self._terminal_history_down)
        self.terminal_output.window_create("end-1c", window=entry)
        self.terminal_entry = entry
        self.terminal_output.see("end")
        self.terminal_output.configure(state="disabled")
        entry.focus_set()

    def clear_terminal(self):
        pending_command = self.terminal_entry.get() if self.terminal_entry is not None else None
        if self.terminal_entry is not None:
            self.terminal_entry.destroy()
            self.terminal_entry = None
        self.terminal_output.configure(state="normal")
        self.terminal_output.delete("1.0", "end")
        self.terminal_output.configure(state="disabled")
        if pending_command is not None and self.terminal_process is not None:
            self._show_terminal_prompt(self.terminal_location)
            self.terminal_entry.insert(0, pending_command)

    def _focus_terminal_input(self, _event=None):
        if self.terminal_entry is not None:
            self.terminal_entry.focus_set()
        return "break"

    def restart_terminal(self):
        self._start_terminal()

    def _send_terminal_command(self, _event=None):
        if self.terminal_entry is None:
            return "break"
        command = self.terminal_entry.get().strip()
        process = self.terminal_process
        if process is None or process.poll() is not None:
            self.terminal_entry.destroy()
            self.terminal_entry = None
            self._append_terminal("\nThe shell is not running. Use Restart to open it again.\n")
            return "break"
        if process.stdin is None:
            return "break"
        self.terminal_entry.destroy()
        self.terminal_entry = None
        self._append_terminal(command + "\n")
        try:
            process.stdin.write(command + "\n")
            process.stdin.flush()
        except (OSError, BrokenPipeError) as error:
            self._append_terminal(f"Could not send command: {error}\n")
        self.terminal_history.append(command)
        self.terminal_history_index = len(self.terminal_history)
        return "break"

    def _terminal_history_up(self, _event=None):
        if self.terminal_entry is None or not self.terminal_history:
            return "break"
        self.terminal_history_index = max(0, self.terminal_history_index - 1)
        self.terminal_entry.delete(0, "end")
        self.terminal_entry.insert(0, self.terminal_history[self.terminal_history_index])
        return "break"

    def _terminal_history_down(self, _event=None):
        if self.terminal_entry is None or not self.terminal_history:
            return "break"
        self.terminal_history_index = min(len(self.terminal_history), self.terminal_history_index + 1)
        self.terminal_entry.delete(0, "end")
        if self.terminal_history_index < len(self.terminal_history):
            self.terminal_entry.insert(0, self.terminal_history[self.terminal_history_index])
        return "break"

    def choose_project(self):
        selected = filedialog.askdirectory(title="Choose VN Engine project folder", initialdir=self.project_root)
        if selected:
            if not self._confirm_discard_or_save("switching projects"):
                return
            self.load_project(Path(selected))

    def load_project(self, root: Path):
        self._loading = True
        self._clear_included_story_tabs()
        self.project_root = project_root_from(root)
        self.project_file = self.project_root / "data" / "project.json"
        self.project_root.joinpath("data").mkdir(parents=True, exist_ok=True)
        self.project_label.configure(text=str(self.project_root))
        raw_project = None
        project_dirty = False
        if self.project_file.is_file():
            try:
                raw_text = self.project_file.read_text(encoding="utf-8")
                raw_project = json.loads(raw_text)
                self.project_buffer = raw_text
            except json.JSONDecodeError:
                self.project_buffer = raw_text
            except OSError as error:
                raw_project = DEFAULT_PROJECT
                self.project_buffer = json.dumps(DEFAULT_PROJECT, ensure_ascii=False, indent=2) + "\n"
                project_dirty = True
                self.set_status(f"Could not read project.json: {error}")
        else:
            raw_project = DEFAULT_PROJECT
            self.project_buffer = json.dumps(DEFAULT_PROJECT, ensure_ascii=False, indent=2) + "\n"
            project_dirty = True
        values = raw_project if isinstance(raw_project, dict) else DEFAULT_PROJECT
        self.story_file = self._story_path_from(values)
        story_dirty = not self.story_file.is_file()
        try:
            self.story_buffer = self.story_file.read_text(encoding="utf-8") if self.story_file.is_file() else self._starter_story()
        except OSError as error:
            self.story_buffer = self._starter_story()
            story_dirty = True
            self.set_status(f"Could not read {self.story_file}: {error}")
        self.story_editor.set_text(self.story_buffer)
        self.story_editor.dirty = story_dirty
        self.story_editor.story_path = self.story_file
        self.story_editors = {self.story_file: self.story_editor}
        self.project_editor.set_text(self.project_buffer)
        self.project_editor.dirty = project_dirty
        self._sync_included_story_tabs()
        self._loading = False
        self._update_tab_labels()
        self._refresh_markdown_tabs()
        self.refresh_asset_tree()
        self.analyze_document("story")
        self.analyze_document("project")
        self._refresh_search_highlights()
        self._start_terminal()
        if project_dirty:
            self.set_status("Default project values were filled in memory. Save project.json to write them.")
        else:
            self.set_status("Ready. Ctrl+Space shows suggestions; F5 runs the engine validator.")
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
        catalog = self._catalog()
        roots = [("Project assets", catalog.assets_dir), ("Engine built-in assets", catalog.engine_assets_dir)]
        for label, path in roots:
            iid = self.asset_tree.insert("", "end", text=label, open=False, values=("root", str(path), str(path)))
            if path.is_dir():
                self.asset_tree.insert(iid, "end", text="", values=("placeholder", "", str(path)))
                self.asset_tree.item(iid, open=True)
                self._populate_tree_node(iid)
            elif label == "Engine built-in assets":
                self._populate_builtin_tree(iid)
        self.asset_tree.tag_configure("folder", foreground="#b7c7e0")
        self.asset_tree.tag_configure("file", foreground="#d1d7df")

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
            self.set_status("Select story.yaml or project.json before inserting an asset reference.")
            return
        editor.text.insert("insert", reference)
        editor.text.focus_set()
        self.set_status(f"Inserted asset reference: {reference}")

    def _on_tab_changed(self, _event=None):
        self.engine_diagnostics = []
        kind = self.active_kind()
        if kind in {"story", "project"}:
            self.analyze_document(kind)
            self.update_cursor_status()
        else:
            self.render_diagnostics()
            path = self.markdown_paths.get(self.notebook.nametowidget(self.notebook.select()))
            self.set_status(f"Viewing {path.name if path else 'documentation'} (read-only). Ctrl+F searches this file.")
        self._update_tab_labels()
        self._refresh_search_highlights()

    def active_kind(self):
        selected = self.notebook.select()
        if selected == str(self.project_editor):
            return "project"
        if any(selected == str(editor) for editor in self.story_editors.values()):
            return "story"
        return "markdown"

    def active_editor(self):
        if self.active_kind() == "project":
            return self.project_editor
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
        ttk.Button(controls, text="Close", command=self.close_find).pack(side="right", padx=(0, 5))
        window.protocol("WM_DELETE_WINDOW", self.close_find)
        self.find_entry.focus_set()
        self._refresh_search_highlights()
        return "break"

    def _all_text_widgets(self):
        widgets = [editor.text for editor in self.story_editors.values()]
        widgets.extend((self.project_editor.text, *self.markdown_texts.values()))
        return widgets

    def _refresh_search_highlights(self):
        for widget in self._all_text_widgets():
            widget.tag_remove("search_match", "1.0", "end")
            widget.tag_remove("search_current", "1.0", "end")
        if self.find_window is None or not self.find_window.winfo_exists() or self.find_entry is None:
            return
        query = self.find_entry.get()
        text = self.active_text()
        if not query or text is None:
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
        else:
            self.project_buffer = self.project_editor.get_text()
        self.engine_diagnostics = []
        self._update_tab_labels()
        if kind == "project":
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
        for path, editor in self.story_editors.items():
            try:
                self.notebook.tab(editor, text=self._story_tab_label(path, editor.dirty))
            except tk.TclError:
                pass
        self.notebook.tab(self.project_editor, text=project_name)
        marker = " *" if any(editor.dirty for editor in self.story_editors.values()) or self.project_editor.dirty else ""
        self.root.title(f"{APP_TITLE} — {self.project_root.name}{marker}")

    def schedule_analysis(self, kind):
        old = self._analysis_jobs.get(kind)
        if old:
            self.root.after_cancel(old)
        self._analysis_jobs[kind] = self.root.after(350, lambda: self.analyze_document(kind))

    def analyze_document(self, kind):
        self._analysis_jobs.pop(kind, None)
        catalog = self._catalog()
        if kind == "story":
            editor = self.active_editor() or self.story_editor
            variables, dialogue_ids = self._story_context()
            self.live_diagnostics[kind] = analyze_story(
                editor.get_text(), catalog,
                fragment=editor is not self.story_editor,
                context_variables=variables,
                context_dialogues=dialogue_ids,
                source_path=getattr(editor, "story_path", self.story_file),
            )
            for diagnostic in self.live_diagnostics[kind]:
                diagnostic.source = Path(getattr(editor, "story_path", self.story_file)).name
        else:
            self.live_diagnostics[kind] = analyze_project(self.project_editor.get_text(), catalog)
            editor = self.project_editor
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

    def apply_diagnostic_marks(self, editor):
        editor.text.tag_remove("diagnostic_error", "1.0", "end")
        editor.text.tag_remove("diagnostic_warning", "1.0", "end")
        editor.text.tag_remove("diagnostic_hint", "1.0", "end")
        kind = editor.document_kind
        diagnostics = list(self.live_diagnostics.get(kind, []))
        if kind == "story":
            diagnostics.extend(self.engine_diagnostics)
        for diagnostic in diagnostics:
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
            editor = self.active_editor()
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
        return self._project_completions(before, line, line_start_index)

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

    def _project_completions(self, before, line, line_start_index):
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
                options = ("list", "tape") if context[-1:] == ("slot",) else ("centered", "left", "right")
                values = [(value, "layout") for value in options]
            elif key in {"normal", "hovered"} and context[-1:] == ("slot",):
                values = [(value, "image asset") for value in catalog.asset_suggestions("image")]
            elif key == "background" and context[-1:] == ("menu",):
                values = [(value, "image asset") for value in catalog.asset_suggestions("image")]
            elif key == "background" and context[-1:] == ("textbox",):
                values = [(value, "textbox image asset") for value in catalog.asset_suggestions("image")]
            elif key == "color" and context[-1:] == ("textbox",):
                values = [(json.dumps(DEFAULT_THEME.get("colors", {}).get("panel", [0, 0, 0, 128]), ensure_ascii=False), "default textbox color")]
            elif key in {"hover", "click", "cancel", "load"} and context[-1:] == ("sounds",):
                values = [(value, "sound asset") for value in catalog.asset_suggestions("sound")]
            elif key in {"menu", "title"} and context[-1:] == ("fonts",):
                values = [(value, "font file") for value in catalog.asset_suggestions("font")]
            elif key in {"text", "name", "button"} and context[-1:] == ("game_fonts",):
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
        keys = self._json_allowed_keys(context)
        return [(f'"{key}":', f"{context or 'project'} setting") for key in keys], f"{line_start_index}+{len(indent_text)}c", partial

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
    def _json_allowed_keys(context):
        if not context:
            return sorted(DEFAULT_PROJECT)
        joined = ".".join(context)
        schemas = {
            "intro": ["creator", "game_version", "warning_message", "credit_image", "warning_image", "headphones_image"],
            "paths": ["data", "assets", "user_data"],
            "window": ["width", "height", "caption"],
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
            "theme.game_fonts": ["text", "name", "button"],
            "theme.menu": list(DEFAULT_THEME.get("menu", {})) + ["right_margin"],
            "theme.slot": list(DEFAULT_THEME.get("slot", {})),
            "theme.textbox": list(DEFAULT_THEME.get("textbox", {})),
            "theme.sounds": list(DEFAULT_THEME.get("sounds", {})),
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
        else:
            path, editor = self.project_file, self.project_editor
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(editor.get_text(), encoding="utf-8", newline="\n")
        editor.dirty = False
        self.project_buffer = editor.get_text()
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

    def save_all(self):
        old_story = self.story_file
        try:
            for story_editor in list(self.story_editors.values()):
                self._write_story_editor(story_editor)
            self._write_document("project")
            self._after_project_save(old_story)
            self._sync_included_story_tabs()
            for story_editor in list(self.story_editors.values()):
                if story_editor.dirty:
                    self._write_story_editor(story_editor)
            self.engine_diagnostics = []
            self.refresh_asset_tree()
            self.analyze_document("story")
            self.analyze_document("project")
            self._update_tab_labels()
            self.set_status("Saved all story YAML files and project.json.")
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
        if not (any(editor.dirty for editor in self.story_editors.values()) or self.project_editor.dirty):
            return True
        answer = messagebox.askyesnocancel(APP_TITLE, f"Save your changes before {action}?", parent=self.root)
        if answer is None:
            return False
        if answer:
            self.save_all()
            return not (any(editor.dirty for editor in self.story_editors.values()) or self.project_editor.dirty)
        return True

    def validate_with_engine(self):
        if self.active_kind() != "story":
            self.notebook.select(self.story_editor)
            self.root.update_idletasks()
        if not self.save_all():
            return
        runtime = self.project_root / "VN_Engine" / "engine.exe"
        if not runtime.is_file():
            runtime = self.project_root / "engine.exe"
        temporary = None
        if runtime.is_file():
            command = [str(runtime), "--validate"]
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
                command = [str(runtime), "--validate"]
        self.set_status("Running the engine story validator...")
        self.root.update_idletasks()
        try:
            result = subprocess.run(
                command,
                cwd=self.project_root,
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

    def _create_temporary_game(self):
        values = json.loads(self.project_editor.get_text())
        platform = self._current_platform()
        game_name = safe_project_name(values.get("name", "Visual Novel"))
        temporary = tempfile.TemporaryDirectory(prefix="vn_editor_test_play_")
        temporary_root = Path(temporary.name)
        runtime_root = temporary_root / "runtime"
        archive_path = temporary_root / f"{game_name}-{platform}.zip"
        try:
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
        self._cleanup_test_play()
        self.set_status("Test Play closed; temporary game files removed.")

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
        self._cleanup_test_play()

    def test_play(self):
        if self.test_play_process is not None and self.test_play_process.poll() is None:
            messagebox.showinfo("Test Play", "A test game is already running.", parent=self.root)
            return
        if not self.save_all():
            return
        errors = self._collect_export_errors()
        if self._show_export_errors("Cannot Start Test Play", errors):
            return
        try:
            temporary, platform, _game_name, executable = self._create_temporary_game()
            self.test_play_tempdir = temporary
            environment = os.environ.copy()
            environment["VN_ENGINE_USER_DATA_DIR"] = str(Path(temporary.name) / "user_data")
            self.test_play_process = subprocess.Popen(
                [str(executable)], cwd=executable.parent, env=environment
            )
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError, subprocess.SubprocessError) as error:
            self._cleanup_test_play()
            messagebox.showerror("Cannot Start Test Play", f"Could not prepare or start the game: {error}", parent=self.root)
            return

        self.set_status(f"Test Play running from a temporary {platform} game build.")
        self.test_play_poll_job = self.root.after(750, self._poll_test_play)

    def export_game(self):
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

        def update_android_runtime_choices(*_args):
            nonlocal release_tags
            if platform_var.get() != "android":
                android_options.grid_remove()
                return
            android_options.grid()
            if release_tags is None:
                try:
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
        button_row.grid(row=5, column=0, columnspan=3, sticky="e")
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
                exported = export_project(
                    self.project_root,
                    self.project_file,
                    Path(template_value),
                    platform,
                    target,
                    android_release_tag,
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
        platform_box.bind("<<ComboboxSelected>>", update_output_name)
        dialog.bind("<Return>", lambda _event: run_export())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.columnconfigure(0, weight=0)
        dialog.columnconfigure(1, weight=1)
        dialog.grab_set()
        dialog.wait_visibility()
        dialog.focus_set()
        update_android_runtime_choices()

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
        self._stop_terminal()
        if self.terminal_poll_job is not None:
            try:
                self.root.after_cancel(self.terminal_poll_job)
            except tk.TclError:
                pass
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="VN Engine story and project editor")
    parser.add_argument("--project-dir", type=Path, help="Project folder containing data/ and assets/")
    args = parser.parse_args()
    package_root = editor_package_root(Path(sys.argv[0]))
    try:
        last_project = None if args.project_dir is not None else _load_last_project()
        root_path = _initial_project_root(args.project_dir, Path.cwd(), package_root, last_project)
        if args.project_dir is None and not _contains_project(root_path):
            install_starter_project(root_path, _editor_release_tag(package_root))
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


