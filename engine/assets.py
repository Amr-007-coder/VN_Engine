from io import BytesIO
from pathlib import Path
import sys

import pygame

from engine.embedded import EMBEDDED_ENABLED, EmbeddedFile, find_asset, read_resource
from engine.loader import PATHS


class AssetManager:
    """Resolves project assets first, then falls back to engine assets."""

    FOLDERS = {
        "image": "images",
        "sound": "sounds",
        "music": "music",
        "font": "fonts",
    }

    def __init__(self, project_assets: Path | None = None):
        self.project_assets = project_assets or PATHS.project_assets
        self.fallback_assets = PATHS.engine_assets
        self._images = {}
        self._sounds = {}
        self._fonts = {}

    def find_path(self, kind: str, name: str):
        return self.find_asset_path(
            kind,
            name,
            project_assets=self.project_assets,
            fallback_assets=self.fallback_assets,
        )

    @classmethod
    def find_asset_path(cls, kind: str, name: str, project_assets=None, fallback_assets=None):
        if kind not in cls.FOLDERS:
            raise ValueError(f"Unknown asset category {kind!r}.")
        path = Path(name)
        if path.is_absolute():
            return path if path.is_file() else None

        roots = [root for root in (project_assets, fallback_assets) if root is not None]
        category = cls.FOLDERS[kind]
        names = [path]
        if sys.platform == "emscripten" and path.suffix.casefold() in {".wav", ".mp3", ".aiff"}:
            names.append(path.with_suffix(".ogg"))
        for root in roots:
            if EMBEDDED_ENABLED:
                embedded = find_asset(root, category, name)
                if embedded is not None:
                    return embedded

            for relative_name in names:
                direct = root / relative_name
                categorized = root / category / relative_name
                for candidate in (direct, categorized):
                    if candidate.is_file():
                        return candidate

            if not path.suffix:
                category_dir = root / category
                if category_dir.exists():
                    wanted = path.as_posix().lower()
                    for candidate in category_dir.rglob("*"):
                        if candidate.is_file() and (
                            candidate.stem.lower() == wanted
                            or candidate.relative_to(category_dir).with_suffix("").as_posix().lower() == wanted
                        ):
                            return candidate
        return None

    def asset_exists(self, kind: str, name: str) -> bool:
        return self.find_path(kind, name) is not None

    def load_image(self, name: str, cache: bool = True):
        path = self.find_path("image", name)
        if path is None:
            raise FileNotFoundError(f"Image asset {name!r} was not found in the project or engine assets.")
        if not cache:
            if isinstance(path, EmbeddedFile):
                return pygame.image.load(BytesIO(read_resource(path.key)), path.name)
            return pygame.image.load(str(path))
        if path not in self._images:
            if isinstance(path, EmbeddedFile):
                image = pygame.image.load(BytesIO(read_resource(path.key)), path.name)
            else:
                image = pygame.image.load(str(path))
            self._images[path] = image
        return self._images[path]

    def load_sound(self, name: str):
        if not pygame.mixer.get_init():
            return None
        path = self.find_path("sound", name)
        if path is None:
            raise FileNotFoundError(f"Sound asset {name!r} was not found in the project or engine assets.")
        if path not in self._sounds:
            if isinstance(path, EmbeddedFile):
                sound = pygame.mixer.Sound(file=BytesIO(read_resource(path.key)))
            else:
                sound = pygame.mixer.Sound(str(path))
            self._sounds[path] = sound
        return self._sounds[path]

    def load_font(self, name: str | None, size: int, system_fallback: bool = True):
        key = (name, size)
        if key in self._fonts:
            return self._fonts[key]
        path = self.find_path("font", name) if name else None
        if path is not None:
            try:
                if isinstance(path, EmbeddedFile):
                    font = pygame.font.Font(BytesIO(read_resource(path.key)), size)
                else:
                    font = pygame.font.Font(str(path), size)
            except (OSError, pygame.error):
                font = pygame.font.SysFont(None, size) if system_fallback else None
        elif system_fallback:
            font = pygame.font.SysFont(None, size)
        else:
            font = None
        if font is None:
            raise FileNotFoundError(f"Font asset {name!r} was not found and fallback is disabled.")
        self._fonts[key] = font
        return font

    def play_sound(self, name: str, volume: float = 1.0):
        sound = self.load_sound(name)
        if sound is None:
            return
        sound.set_volume(max(0.0, min(1.0, volume)))
        sound.play()

    def play_music(self, name: str, volume: float = 1.0):
        if not pygame.mixer.get_init():
            return False
        path = self.find_path("music", name)
        if path is None:
            raise FileNotFoundError(f"Music asset {name!r} was not found in the project or engine assets.")
        if isinstance(path, EmbeddedFile):
            self._music_buffer = BytesIO(read_resource(path.key))
            pygame.mixer.music.load(self._music_buffer, path.suffix.lstrip("."))
        else:
            self._music_buffer = None
            pygame.mixer.music.load(str(path))
        pygame.mixer.music.set_volume(max(0.0, min(1.0, volume)))
        pygame.mixer.music.play(-1)
        return True
