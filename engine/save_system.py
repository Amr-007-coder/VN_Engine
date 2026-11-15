import json
from datetime import datetime

from engine.loader import PATHS


class SaveSystem:
    def __init__(self, slot_count: int = 5, user_data_dir=None):
        self.slot_count = slot_count
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
        return self._read_save(self.directory / "autosave.json", "Autosave")

    @staticmethod
    def _read_save(path, label):
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as save_file:
            data = json.load(save_file)
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
    ):
        data = self._make_save(
            story_file, flow, background_id, music_track, characters, dialogue_history
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
    ):
        data = self._make_save(
            story_file, flow, background_id, music_track, characters, dialogue_history
        )
        self._write_save(self.directory / "autosave.json", data)
        return data

    @staticmethod
    def _make_save(story_file, flow, background_id, music_track, characters, dialogue_history):
        dialogue = flow.current
        data = {
            "version": 1,
            "story": story_file,
            "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "state": flow.snapshot(),
            "metadata": {
                "chapter": dialogue.get("chapter", flow.story_data.get("title", "")),
                "dialogue": flow.current_id,
            },
            "background": background_id,
            "music": music_track,
            "characters": characters or {},
            "history": dialogue_history or [],
            "preview": None,
        }
        return data

    @staticmethod
    def _write_save(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(".tmp")
        with temporary_path.open("w", encoding="utf-8") as save_file:
            json.dump(data, save_file, ensure_ascii=True, indent=2)
            save_file.write("\n")
        temporary_path.replace(path)

    def delete_slot(self, slot: int) -> bool:
        path = self._path_for(slot)
        removed = False
        for candidate in (path, *self._legacy_paths_for(slot)):
            if candidate.exists():
                candidate.unlink()
                removed = True
        return removed

    def latest_slot(self):
        populated = []
        for slot_info in self.list_slots():
            saved_game = slot_info["save"]
            if saved_game is not None:
                try:
                    timestamp = datetime.fromisoformat(saved_game["saved_at"]).timestamp()
                except (TypeError, ValueError):
                    timestamp = 0
                populated.append((timestamp, slot_info["slot"]))
        if not populated:
            return None
        return max(populated)[1]

    def _path_for(self, slot: int):
        if not isinstance(slot, int) or not 1 <= slot <= self.slot_count:
            raise ValueError(f"Save slot must be between 1 and {self.slot_count}.")
        return self.directory / f"slot_{slot}.json"

    def _legacy_paths_for(self, slot: int):
        if not isinstance(slot, int) or not 1 <= slot <= self.slot_count:
            raise ValueError(f"Save slot must be between 1 and {self.slot_count}.")
        return tuple(
            directory / f"slot_{slot}.json"
            for directory in dict.fromkeys(self.legacy_directories)
            if directory != self.directory
        )
