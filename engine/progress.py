"""Persistent, cloud-independent optional story unlocks."""

import json
import os
from pathlib import Path
import tempfile


EMPTY_PROGRESS = {
    "version": 1,
    "cgs": {},
    "music": {},
    "achievements": {},
    "routes": {},
}


class ProgressStore:
    def __init__(self, user_data_dir):
        self.path = Path(user_data_dir) / "progress.json"
        self.values = {key: dict(value) if isinstance(value, dict) else value for key, value in EMPTY_PROGRESS.items()}

    def load(self):
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            loaded = {}
        if not isinstance(loaded, dict) or loaded.get("version") != 1:
            loaded = {}
        self.values = {key: dict(value) if isinstance(value, dict) else value for key, value in EMPTY_PROGRESS.items()}
        for key in ("cgs", "music", "achievements", "routes"):
            value = loaded.get(key)
            if isinstance(value, dict):
                self.values[key].update({str(name): item for name, item in value.items() if isinstance(item, dict)})
        return self.values

    def unlock(self, category, identifier, value):
        if category not in {"cgs", "music", "achievements", "routes"}:
            raise ValueError(f"Unknown progress category {category!r}.")
        key = str(identifier)
        if not key:
            raise ValueError("Progress IDs cannot be empty.")
        normalized = {str(name): item for name, item in value.items()}
        if self.values[category].get(key) == normalized:
            return False
        self.values[category][key] = normalized
        self.save()
        return True

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(self.values, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
