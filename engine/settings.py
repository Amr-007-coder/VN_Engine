import json

from engine.embedded import bytes_for_path
from engine.loader import PATHS


DEFAULT_SETTINGS = {
    "type_speed": 1.0,
    "music_volume": 0.7,
    "sfx_volume": 0.8,
    "fullscreen": False,
}


class SettingsStore:
    def __init__(self, user_data_dir=None):
        self.values = dict(DEFAULT_SETTINGS)
        self.user_data_dir = user_data_dir or PATHS.user_data

    def load(self):
        path = self.user_data_dir / "settings.json"
        portable_path = PATHS.portable_user_data / "settings.json"
        legacy_path = PATHS.engine_data / "settings.json"
        raw = None
        if path.exists():
            with path.open(encoding="utf-8") as settings_file:
                raw = json.load(settings_file)
        elif portable_path != path and portable_path.exists():
            with portable_path.open(encoding="utf-8") as settings_file:
                raw = json.load(settings_file)
        elif legacy_path.exists():
            with legacy_path.open(encoding="utf-8") as settings_file:
                raw = json.load(settings_file)
        else:
            legacy_data = bytes_for_path(
                legacy_path,
                ((PATHS.engine_data, "engine/data"),),
            )
            if legacy_data is not None:
                raw = json.loads(legacy_data.decode("utf-8"))

        if raw is not None:
            if not isinstance(raw, dict):
                raise ValueError("settings.json must contain a JSON object.")
            self.values.update(raw)
            # Read the previous on/off settings format as volume 0 or 1.
            if "music_volume" not in raw:
                self.values["music_volume"] = raw.get("bgm", 0.7)
            if "sfx_volume" not in raw:
                self.values["sfx_volume"] = raw.get("sfx", 0.8)
            self.values = {key: self.values[key] for key in DEFAULT_SETTINGS}
        self._normalize()
        return self.values

    def save(self):
        self._normalize()
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        with (self.user_data_dir / "settings.json").open("w", encoding="utf-8") as settings_file:
            json.dump(self.values, settings_file, ensure_ascii=True, indent=2)
            settings_file.write("\n")

    def set(self, name: str, value):
        if name not in DEFAULT_SETTINGS:
            raise KeyError(f"Unknown setting: {name}")
        self.values[name] = value
        self._normalize()

    def _normalize(self):
        try:
            speed = float(self.values.get("type_speed", 1.0))
        except (TypeError, ValueError):
            speed = DEFAULT_SETTINGS["type_speed"]
        self.values["type_speed"] = min(4.0, max(0.25, speed))

        for key in ("music_volume", "sfx_volume"):
            try:
                volume = float(self.values.get(key, DEFAULT_SETTINGS[key]))
            except (TypeError, ValueError):
                volume = DEFAULT_SETTINGS[key]
            self.values[key] = min(1.0, max(0.0, volume))

        fullscreen = self.values.get("fullscreen", False)
        if isinstance(fullscreen, str):
            fullscreen = fullscreen.strip().lower() in {"1", "true", "yes", "on"}
        self.values["fullscreen"] = bool(fullscreen)
