from io import BytesIO
from dataclasses import dataclass
import json
from pathlib import Path
from pathlib import PurePosixPath
import sys
from zipfile import BadZipFile, ZipFile

from engine.embedded import EMBEDDED_ENABLED, EmbeddedFile, find_asset, read_resource, resources_under
from engine.loader import PATHS


@dataclass(frozen=True)
class ModAsset:
    archive: Path | EmbeddedFile
    member: str


class AssetManager:
    """Resolves project assets first, then falls back to engine assets."""

    FOLDERS = {
        "image": "images",
        "sound": "sounds",
        "music": "music",
        "font": "fonts",
        "characters": "characters",
    }

    def __init__(self, project_assets: Path | None = None, mod_directory: Path | None = None):
        self.project_assets = project_assets or PATHS.project_assets
        self.fallback_assets = PATHS.engine_assets
        self.mod_directory = Path(mod_directory or PATHS.user_data / "mods")
        self.mod_state_path = self.mod_directory.parent / "mods.json"
        self._mod_disabled = self._load_mod_state()
        self._mod_packages = []
        self._mod_conflicts = []
        self._mod_index = self._scan_mod_assets()
        self._images = {}
        self._sounds = {}
        self._fonts = {}
        self._filesystem_asset_indexes = {}

    def _load_mod_state(self):
        try:
            data = json.loads(self.mod_state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return set()
        disabled = data.get("disabled", []) if isinstance(data, dict) else []
        return {key for key in disabled if isinstance(key, str)}

    def mod_packages(self):
        return [
            {key: value for key, value in item.items() if key != "members"}
            for item in self._mod_packages
        ]

    def set_mod_enabled(self, package_key: str, enabled: bool):
        if not any(item["key"] == package_key for item in self._mod_packages):
            raise KeyError(f"Unknown mod package {package_key!r}.")
        if enabled:
            self._mod_disabled.discard(package_key)
        else:
            self._mod_disabled.add(package_key)
        self._save_mod_state()
        self._mod_index = self._scan_mod_assets()

    def _save_mod_state(self):
        self.mod_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.mod_state_path.write_text(
            json.dumps({"disabled": sorted(self._mod_disabled)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def remove_mod_package(self, package_key: str):
        package = next((item for item in self._mod_packages if item["key"] == package_key), None)
        if package is None:
            raise KeyError(f"Unknown mod package {package_key!r}.")
        path = package["path"]
        if package["source"] != "user" or not isinstance(path, Path):
            raise ValueError("Only packages installed in the user's mods folder can be removed here.")
        path.unlink()
        self._mod_disabled.discard(package_key)
        self._save_mod_state()
        self._mod_index = self._scan_mod_assets()

    def install_mod_package(self, source: Path):
        source = Path(source)
        if source.suffix.casefold() != ".vnmod" or not source.is_file():
            raise ValueError("Choose an existing .vnmod package.")
        with ZipFile(source) as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
                raise ValueError("This package has an unsupported manifest version.")
        self.mod_directory.mkdir(parents=True, exist_ok=True)
        destination = self.mod_directory / source.name
        if destination.exists() and destination.resolve() != source.resolve():
            raise FileExistsError(f"A package named {destination.name!r} is already installed.")
        if destination.resolve() != source.resolve():
            import shutil
            shutil.copy2(source, destination)
        self._mod_index = self._scan_mod_assets()
        return destination

    def find_path(self, kind: str, name: str):
        if kind not in self.FOLDERS:
            raise ValueError(f"Unknown asset category {kind!r}.")
        project_path = self._find_asset_path(kind, name, (self.project_assets,))
        if project_path is not None:
            return project_path
        path = Path(name)
        category = self.FOLDERS[kind]
        candidates = [path]
        if sys.platform == "emscripten" and path.suffix.casefold() in {".wav", ".mp3", ".aiff"}:
            candidates.append(path.with_suffix(".ogg"))
        for relative in candidates:
            for member in (relative.as_posix(), (PurePosixPath(category) / relative.as_posix()).as_posix()):
                mod_asset = self._mod_index.get(member.casefold())
                if mod_asset is not None:
                    return mod_asset
        if not path.suffix:
            wanted = path.as_posix().casefold()
            matches = []
            for member, asset in self._mod_index.items():
                pure = PurePosixPath(member)
                if pure.parts[0].casefold() != category.casefold():
                    continue
                relative = PurePosixPath(*pure.parts[1:])
                if relative.stem.casefold() == wanted or relative.with_suffix("").as_posix().casefold() == wanted:
                    matches.append(asset)
            if len(matches) == 1:
                return matches[0]
        return self._find_asset_path(kind, name, (self.fallback_assets,))

    def _find_asset_path(self, kind: str, name: str, roots):
        path = Path(name)
        if path.is_absolute():
            return path if path.is_file() else None
        category = self.FOLDERS[kind]
        names = [path]
        if sys.platform == "emscripten" and path.suffix.casefold() in {".wav", ".mp3", ".aiff"}:
            names.append(path.with_suffix(".ogg"))
        for root_value in roots:
            root = Path(root_value)
            if EMBEDDED_ENABLED:
                embedded = find_asset(root, category, name)
                if embedded is not None:
                    return embedded
            for relative_name in names:
                for candidate in (root / relative_name, root / category / relative_name):
                    if candidate.is_file():
                        return candidate
            if not path.suffix:
                category_dir = root / category
                if not category_dir.is_dir():
                    continue
                key = (root.resolve(), category)
                aliases = self._filesystem_asset_indexes.get(key)
                if aliases is None:
                    aliases = {}
                    try:
                        for candidate in category_dir.rglob("*"):
                            if not candidate.is_file():
                                continue
                            relative = candidate.relative_to(category_dir)
                            aliases.setdefault(candidate.stem.casefold(), candidate)
                            aliases.setdefault(relative.with_suffix("").as_posix().casefold(), candidate)
                    except OSError:
                        pass
                    self._filesystem_asset_indexes[key] = aliases
                found = aliases.get(path.as_posix().casefold())
                if found is not None:
                    return found
        return None

    def mod_asset_names(self, kind: str):
        category = self.FOLDERS.get(kind)
        if category is None:
            return []
        prefix = category.casefold() + "/"
        return sorted(
            "/".join(PurePosixPath(asset.member).parts[2:])
            for asset in self._mod_index.values()
            if len(PurePosixPath(asset.member).parts) >= 3
            and PurePosixPath(asset.member).parts[0].casefold() == "assets"
            and PurePosixPath(asset.member).parts[1].casefold() == category.casefold()
        )

    def _scan_mod_assets(self):
        index = {}
        self._mod_packages = []
        self._mod_conflicts = []
        directories = (self.mod_directory, self.project_assets / "mods")
        archive_paths = []
        for directory in directories:
            if directory.is_dir():
                archive_paths.extend(directory.glob("*.vnmod"))
        if EMBEDDED_ENABLED:
            archive_paths.extend(
                EmbeddedFile(key)
                for key in resources_under("assets/mods")
                if PurePosixPath(key).suffix.casefold() == ".vnmod"
            )
        archive_paths.sort(key=lambda item: (
            PurePosixPath(item.key).name.casefold(), "embedded"
        ) if isinstance(item, EmbeddedFile) else (item.name.casefold(), str(item.parent).casefold()))
        for archive_path in archive_paths:
            if isinstance(archive_path, EmbeddedFile):
                source_kind = "embedded"
                filename = PurePosixPath(archive_path.key).name
                package_key = f"embedded:{archive_path.key}"
            else:
                filename = archive_path.name
                source_kind = "user" if archive_path.parent.resolve() == self.mod_directory.resolve() else "project"
                package_key = f"{source_kind}:{filename}"
            record = {
                "key": package_key,
                "path": archive_path,
                "source": source_kind,
                "filename": filename,
                "id": None,
                "name": Path(filename).stem,
                "version": "",
                "enabled": package_key not in self._mod_disabled,
                "assets": [],
                "errors": [],
                "conflicts": [],
                "members": [],
            }
            self._mod_packages.append(record)
            try:
                package_bytes = read_resource(archive_path.key) if isinstance(archive_path, EmbeddedFile) else None
                source = BytesIO(package_bytes) if package_bytes is not None else archive_path
                with ZipFile(source) as archive:
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                    if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
                        record["errors"].append("Unsupported or invalid manifest format version.")
                        continue
                    record["id"] = manifest.get("id")
                    record["name"] = manifest.get("name") or manifest.get("id") or record["name"]
                    record["version"] = manifest.get("version", "")
                    if not isinstance(record["id"], str) or not record["id"].strip():
                        record["errors"].append("Manifest is missing a valid package id.")
                    if not isinstance(record["name"], str) or not isinstance(record["version"], str):
                        record["errors"].append("Manifest name and version must be strings.")
                        record["name"] = str(record["id"] or filename)
                    for info in archive.infolist():
                        if info.is_dir():
                            continue
                        relative = PurePosixPath(info.filename.replace("\\", "/"))
                        if (
                            relative.is_absolute()
                            or ".." in relative.parts
                            or len(relative.parts) < 3
                            or relative.parts[0] != "assets"
                            or relative.parts[1] not in self.FOLDERS.values()
                            or (info.external_attr >> 16) & 0o170000 == 0o120000
                        ):
                            if relative.parts and relative.parts[0] == "assets":
                                record["errors"].append(f"Ignored unsafe or unsupported member: {info.filename}")
                            continue
                        asset_member = PurePosixPath(*relative.parts[1:]).as_posix()
                        record["assets"].append(asset_member)
                        record["members"].append((asset_member, relative.as_posix()))
            except (OSError, BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
                record["errors"].append(f"Could not read package: {error}")
                continue
            if not record["members"] and not record["errors"]:
                record["errors"].append("Package contains no supported asset files.")

        winners = {}
        for record in self._mod_packages:
            if not record["enabled"] or record["errors"]:
                continue
            for asset_member, archive_member in record["members"]:
                normalized = asset_member.casefold()
                winner = winners.get(normalized)
                if winner is not None:
                    conflict = {
                        "asset": asset_member,
                        "winner": winner["key"],
                        "other": record["key"],
                    }
                    self._mod_conflicts.append(conflict)
                    record["conflicts"].append(conflict)
                    winner["conflicts"].append(conflict)
                    continue
                winners[normalized] = record
                index[normalized] = ModAsset(record["path"], archive_member)
        for record in self._mod_packages:
            if not record["enabled"] or record["errors"]:
                continue
            for asset_member, _archive_member in record["members"]:
                if (self.project_assets / asset_member).is_file():
                    conflict = {"asset": asset_member, "winner": "project assets", "other": record["key"]}
                    record["conflicts"].append(conflict)
                    self._mod_conflicts.append(conflict)
        return index

    @staticmethod
    def _mod_bytes(path: ModAsset):
        package_bytes = read_resource(path.archive.key) if isinstance(path.archive, EmbeddedFile) else None
        source = BytesIO(package_bytes) if package_bytes is not None else path.archive
        with ZipFile(source) as archive:
            return archive.read(path.member)

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
        import pygame

        path = self.find_path("image", name)
        if path is None:
            raise FileNotFoundError(f"Image asset {name!r} was not found in the project or engine assets.")
        if not cache:
            if isinstance(path, EmbeddedFile):
                return pygame.image.load(BytesIO(read_resource(path.key)), path.name)
            if isinstance(path, ModAsset):
                return pygame.image.load(BytesIO(self._mod_bytes(path)), PurePosixPath(path.member).name)
            return pygame.image.load(str(path))
        if path not in self._images:
            if isinstance(path, EmbeddedFile):
                image = pygame.image.load(BytesIO(read_resource(path.key)), path.name)
            elif isinstance(path, ModAsset):
                image = pygame.image.load(BytesIO(self._mod_bytes(path)), PurePosixPath(path.member).name)
            else:
                image = pygame.image.load(str(path))
            self._images[path] = image
        return self._images[path]

    def load_sound(self, name: str):
        import pygame

        if not pygame.mixer.get_init():
            return None
        path = self.find_path("sound", name)
        if path is None:
            raise FileNotFoundError(f"Sound asset {name!r} was not found in the project or engine assets.")
        if path not in self._sounds:
            if isinstance(path, EmbeddedFile):
                sound = pygame.mixer.Sound(file=BytesIO(read_resource(path.key)))
            elif isinstance(path, ModAsset):
                sound = pygame.mixer.Sound(file=BytesIO(self._mod_bytes(path)))
            else:
                sound = pygame.mixer.Sound(str(path))
            self._sounds[path] = sound
        return self._sounds[path]

    def load_font(self, name: str | None, size: int, system_fallback: bool = True):
        import pygame

        key = (name, size)
        if key in self._fonts:
            return self._fonts[key]
        path = self.find_path("font", name) if name else None
        if path is not None:
            try:
                if isinstance(path, EmbeddedFile):
                    font = pygame.font.Font(BytesIO(read_resource(path.key)), size)
                elif isinstance(path, ModAsset):
                    font = pygame.font.Font(BytesIO(self._mod_bytes(path)), size)
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
        import pygame

        if not pygame.mixer.get_init():
            return False
        path = self.find_path("music", name)
        if path is None:
            raise FileNotFoundError(f"Music asset {name!r} was not found in the project or engine assets.")
        if isinstance(path, EmbeddedFile):
            self._music_buffer = BytesIO(read_resource(path.key))
            pygame.mixer.music.load(self._music_buffer, path.suffix.lstrip("."))
        elif isinstance(path, ModAsset):
            self._music_buffer = BytesIO(self._mod_bytes(path))
            pygame.mixer.music.load(self._music_buffer, PurePosixPath(path.member).suffix.lstrip("."))
        else:
            self._music_buffer = None
            pygame.mixer.music.load(str(path))
        pygame.mixer.music.set_volume(max(0.0, min(1.0, volume)))
        pygame.mixer.music.play(-1)
        return True
