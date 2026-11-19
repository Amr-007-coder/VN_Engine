import json
from copy import deepcopy

from engine.embedded import bytes_for_path
from engine.loader import PATHS
from engine.ui_scale import DEFAULT_UI_SCALE, MAX_UI_SCALE, MIN_UI_SCALE


DEFAULT_SETTINGS = {
    "type_speed": 1.0,
    "music_volume": 0.7,
    "sfx_volume": 0.8,
    "fullscreen": False,
    "ui_scale": DEFAULT_UI_SCALE,
    "auto_advance": False,
    "auto_wait": 1.5,
    "dialogue_font_scale": 1.0,
    "speaker_font_scale": 1.0,
    "high_contrast": False,
    "muted": False,
    "reduced_motion": False,
    "voice_enabled": True,
    "speech_enabled": False,
    "subtitles_enabled": True,
    "animated_text": True,
    "touch_advance_mode": "screen",
    "locale": "en",
    "theme_variant": "default",
    "key_bindings": {
        "advance": "space",
        "pause": "escape",
        "history": "h",
        "auto": "a",
        "mute": "m",
        "skip_read": "tab",
        "skip_all": "shift+tab",
        "back": "backspace",
        "voice": "v",
    },
    "controller_bindings": {
        "advance": 0,
        "pause": 1,
        "history": 2,
        "back": 3,
        "skip_read": 4,
        "skip_all": 5,
        "auto": 7,
        "mute": 9,
        "voice": 8,
    },
}


class SettingsStore:
    def __init__(self, user_data_dir=None):
        self.values = deepcopy(DEFAULT_SETTINGS)
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

        try:
            ui_scale = float(self.values.get("ui_scale", DEFAULT_UI_SCALE))
        except (TypeError, ValueError):
            ui_scale = DEFAULT_UI_SCALE
        self.values["ui_scale"] = round(min(MAX_UI_SCALE, max(MIN_UI_SCALE, ui_scale)), 2)

        try:
            auto_wait = float(self.values.get("auto_wait", DEFAULT_SETTINGS["auto_wait"]))
        except (TypeError, ValueError):
            auto_wait = DEFAULT_SETTINGS["auto_wait"]
        self.values["auto_wait"] = round(min(10.0, max(0.25, auto_wait)), 2)

        for key in ("dialogue_font_scale", "speaker_font_scale"):
            try:
                scale = float(self.values.get(key, DEFAULT_SETTINGS[key]))
            except (TypeError, ValueError):
                scale = DEFAULT_SETTINGS[key]
            self.values[key] = round(min(2.0, max(0.6, scale)), 2)

        for key in (
            "auto_advance", "high_contrast", "muted", "reduced_motion",
            "voice_enabled", "animated_text",
            "subtitles_enabled", "speech_enabled",
        ):
            value = self.values.get(key, DEFAULT_SETTINGS[key])
            if isinstance(value, str):
                value = value.strip().lower() in {"1", "true", "yes", "on"}
            self.values[key] = bool(value)

        touch_mode = self.values.get("touch_advance_mode", "screen")
        self.values["touch_advance_mode"] = (
            touch_mode if isinstance(touch_mode, str) and touch_mode in {"screen", "textbox"} else "screen"
        )
        locale = self.values.get("locale", DEFAULT_SETTINGS["locale"])
        self.values["locale"] = locale.strip() if isinstance(locale, str) and locale.strip() else DEFAULT_SETTINGS["locale"]
        variant = self.values.get("theme_variant", "default")
        self.values["theme_variant"] = variant.strip() if isinstance(variant, str) and variant.strip() else "default"

        configured_bindings = self.values.get("key_bindings", {})
        if not isinstance(configured_bindings, dict):
            configured_bindings = {}
        self.values["key_bindings"] = {
            action: (
                configured_bindings.get(action)
                if isinstance(configured_bindings.get(action), str)
                and configured_bindings[action].strip()
                else binding
            )
            for action, binding in DEFAULT_SETTINGS["key_bindings"].items()
        }

        configured_controller = self.values.get("controller_bindings", {})
        if not isinstance(configured_controller, dict):
            configured_controller = {}
        controller_bindings = {}
        for action, button in DEFAULT_SETTINGS["controller_bindings"].items():
            value = configured_controller.get(action, button)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                controller_bindings[action] = value
            else:
                controller_bindings[action] = button
        self.values["controller_bindings"] = controller_bindings
