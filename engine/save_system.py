import json
import math
import shutil
from datetime import datetime
from pathlib import Path

from engine.loader import PATHS


class SaveSystem:
    CURRENT_VERSION = 2

    def __init__(self, slot_count: int = 5, user_data_dir=None, autosave_slot_count: int = 3):
        self.slot_count = slot_count
        self.autosave_slot_count = autosave_slot_count
        self.user_data_dir = user_data_dir or PATHS.user_data
        self.directory = self.user_data_dir / "saves"
        self.legacy_directories = (
            PATHS.portable_user_data / "saves",
            PATHS.engine_data / "saves",
        )

    def list_slots(self) -> list[dict]:
        slots = []
        for slot in range(1, self.slot_count + 1):
            try:
                saved_game = self.read_slot(slot)
                error = None
            except (OSError, ValueError, json.JSONDecodeError) as exception:
                saved_game = None
                error = str(exception)
            slots.append({"slot": slot, "save": saved_game, "error": error})
        return slots

    def read_slot(self, slot: int):
        path = self._path_for(slot)
        if not path.exists():
            for legacy_path in self._legacy_paths_for(slot):
                if legacy_path.exists():
                    path = legacy_path
                    break
        return self._read_save(path, f"Save slot {slot}")

    def read_autosave(self):
        candidates = [
            self.directory / f"autosave_{slot}.json"
            for slot in range(1, self.autosave_slot_count + 1)
        ]
        # Keep reading the original single autosave created by version 1.
        candidates.append(self.directory / "autosave.json")
        saves = []
        for path in candidates:
            try:
                saved_game = self._read_save(path, "Autosave")
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if saved_game is not None:
                saves.append(saved_game)
        return max(saves, key=lambda save: _timestamp(save.get("saved_at")), default=None)

    def read_quick_save(self):
        return self._read_save(self.directory / "quick_save.json", "Quick save")

    @classmethod
    def _read_save(cls, path, label, allow_backup=True):
        if not path.exists():
            backup_path = path.with_suffix(path.suffix + ".bak")
            if allow_backup and backup_path.exists():
                with backup_path.open(encoding="utf-8") as save_file:
                    recovered = cls._validate_and_migrate(json.load(save_file), label)
                recovered["recovered_from_backup"] = True
                return recovered
            return None
        try:
            with path.open(encoding="utf-8") as save_file:
                return cls._validate_and_migrate(json.load(save_file), label)
        except (OSError, ValueError, json.JSONDecodeError) as primary_error:
            backup_path = path.with_suffix(path.suffix + ".bak")
            if not allow_backup or not backup_path.exists():
                raise
            try:
                with backup_path.open(encoding="utf-8") as save_file:
                    recovered = cls._validate_and_migrate(json.load(save_file), label)
            except (OSError, ValueError, json.JSONDecodeError):
                raise primary_error
            recovered["recovered_from_backup"] = True
            return recovered

    @classmethod
    def _validate_and_migrate(cls, data, label):
        if not isinstance(data, dict):
            raise ValueError(f"{label} is not a JSON object.")
        if not isinstance(data.get("story"), str):
            raise ValueError(f"{label} has no story filename.")
        if not isinstance(data.get("saved_at"), str):
            raise ValueError(f"{label} has no valid timestamp.")
        if not isinstance(data.get("state"), dict):
            raise ValueError(f"{label} has no valid story state.")
        if not isinstance(data.get("metadata", {}), dict):
            raise ValueError(f"{label} has invalid metadata.")
        version = data.get("version", 1)
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValueError(f"{label} has an invalid save version.")
        if version > cls.CURRENT_VERSION:
            raise ValueError(f"{label} uses a newer save format (version {version}).")

        if version == 1:
            history = data.get("history", [])
            seen = []
            if isinstance(history, list):
                seen = [
                    item["dialogue"] for item in history
                    if isinstance(item, dict) and isinstance(item.get("dialogue"), str)
                ]
            data.setdefault("play_time_seconds", 0.0)
            data.setdefault("seen_dialogues", seen)
            data.setdefault("choice_history", [])
            data.setdefault("metadata", {})
            data["metadata"].setdefault("name", "")
            data["version"] = 2
        for key in ("history", "seen_dialogues", "choice_history"):
            data.setdefault(key, [])
            if not isinstance(data[key], list):
                raise ValueError(f"{label} has invalid {key.replace('_', ' ')} data.")
        try:
            play_time = float(data.get("play_time_seconds", 0) or 0)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"{label} has invalid play-time data.") from error
        if not math.isfinite(play_time) or play_time < 0:
            raise ValueError(f"{label} has invalid play-time data.")
        data["play_time_seconds"] = play_time
        return data

    def save_slot(
        self,
        slot: int,
        story_file: str,
        flow,
        background_id=None,
        music_track=None,
        characters=None,
        dialogue_history=None,
        play_time_seconds=0,
        seen_dialogues=None,
        choice_history=None,
        custom_name="",
        preview=None,
    ):
        data = self._make_save(
            story_file, flow, background_id, music_track, characters, dialogue_history,
            play_time_seconds, seen_dialogues, choice_history, custom_name, preview,
        )
        self._write_save(self._path_for(slot), data)
        return data

    def save_autosave(
        self,
        story_file: str,
        flow,
        background_id=None,
        music_track=None,
        characters=None,
        dialogue_history=None,
        play_time_seconds=0,
        seen_dialogues=None,
        choice_history=None,
        preview=None,
    ):
        data = self._make_save(
            story_file, flow, background_id, music_track, characters, dialogue_history,
            play_time_seconds, seen_dialogues, choice_history, preview=preview,
        )
        slot = self._next_autosave_slot()
        self._write_save(self.directory / f"autosave_{slot}.json", data)
        return data

    def save_quick_save(
        self,
        story_file: str,
        flow,
        background_id=None,
        music_track=None,
        characters=None,
        dialogue_history=None,
        play_time_seconds=0,
        seen_dialogues=None,
        choice_history=None,
        custom_name="",
        preview=None,
    ):
        data = self._make_save(
            story_file, flow, background_id, music_track, characters, dialogue_history,
            play_time_seconds, seen_dialogues, choice_history, custom_name, preview,
        )
        self._write_save(self.directory / "quick_save.json", data)
        return data

    @staticmethod
    def _make_save(
        story_file, flow, background_id, music_track, characters, dialogue_history,
        play_time_seconds=0, seen_dialogues=None, choice_history=None,
        custom_name="", preview=None,
    ):
        dialogue = flow.current
        try:
            play_time_seconds = max(0.0, float(play_time_seconds or 0))
        except (TypeError, ValueError, OverflowError):
            play_time_seconds = 0.0
        data = {
            "version": SaveSystem.CURRENT_VERSION,
            "story": story_file,
            "saved_at": datetime.now().astimezone().isoformat(timespec="microseconds"),
            "state": flow.snapshot(),
            "metadata": {
                "chapter": dialogue.get("chapter", flow.story_data.get("title", "")),
                "dialogue": flow.current_id,
                "name": str(custom_name or ""),
            },
            "play_time_seconds": play_time_seconds,
            "background": background_id,
            "music": music_track,
            "characters": characters or {},
            "history": dialogue_history or [],
            "seen_dialogues": sorted(set(seen_dialogues or [])),
            "choice_history": choice_history or [],
            "preview": preview,
        }
        return data

    @staticmethod
    def _write_save(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(".tmp")
        with temporary_path.open("w", encoding="utf-8") as save_file:
            json.dump(data, save_file, ensure_ascii=True, indent=2)
            save_file.write("\n")
        backup_path = path.with_suffix(path.suffix + ".bak")
        if path.exists():
            try:
                SaveSystem._read_save(path, "Existing save", allow_backup=False)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
            else:
                shutil.copy2(path, backup_path)
        temporary_path.replace(path)

    def _next_autosave_slot(self):
        if self.autosave_slot_count < 1:
            raise ValueError("Autosave slot count must be a positive integer.")
        slots = []
        for slot in range(1, self.autosave_slot_count + 1):
            path = self.directory / f"autosave_{slot}.json"
            try:
                saved_game = self._read_save(path, f"Autosave slot {slot}")
            except (OSError, ValueError, json.JSONDecodeError):
                saved_game = None
            if saved_game is None:
                return slot
            slots.append((_timestamp(saved_game.get("saved_at")), slot))
        return min(slots)[1]

    def export_slot(self, slot: int, destination):
        """Write a numbered save to a user-selected JSON file."""
        saved_game = self.read_slot(slot)
        if saved_game is None:
            raise FileNotFoundError(f"Save slot {slot} is empty.")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as save_file:
            json.dump(saved_game, save_file, ensure_ascii=True, indent=2)
            save_file.write("\n")
        return destination

    def import_slot(self, source, slot: int, expected_story: str | None = None):
        """Load a save JSON file into a numbered slot after validating it."""
        with Path(source).open(encoding="utf-8") as save_file:
            data = self._validate_and_migrate(json.load(save_file), "Imported save")
        if expected_story is not None and data.get("story") != expected_story:
            raise ValueError("Imported save belongs to a different story.")
        self._write_save(self._path_for(slot), data)
        return data

    def copy_slot(self, source_slot: int, destination_slot: int):
        saved_game = self.read_slot(source_slot)
        if saved_game is None:
            raise FileNotFoundError(f"Save slot {source_slot} is empty.")
        self._write_save(self._path_for(destination_slot), saved_game)
        return saved_game

    def delete_slot(self, slot: int) -> bool:
        path = self._path_for(slot)
        removed = False
        candidates = [path, path.with_suffix(path.suffix + ".bak")]
        for legacy_path in self._legacy_paths_for(slot):
            candidates.extend((legacy_path, legacy_path.with_suffix(legacy_path.suffix + ".bak")))
        for candidate in candidates:
            if candidate.exists():
                candidate.unlink()
                removed = True
        return removed

    def latest_slot(self):
        populated = []
        for slot_info in self.list_slots():
            saved_game = slot_info["save"]
            if saved_game is not None:
                populated.append((_timestamp(saved_game.get("saved_at")), slot_info["slot"]))
        if not populated:
            return None
        return max(populated)[1]

    def _path_for(self, slot: int):
        if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= self.slot_count:
            raise ValueError(f"Save slot must be between 1 and {self.slot_count}.")
        return self.directory / f"slot_{slot}.json"

    def _legacy_paths_for(self, slot: int):
        if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= self.slot_count:
            raise ValueError(f"Save slot must be between 1 and {self.slot_count}.")
        return tuple(
            directory / f"slot_{slot}.json"
            for directory in dict.fromkeys(self.legacy_directories)
            if directory != self.directory
        )


def _timestamp(value):
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0
