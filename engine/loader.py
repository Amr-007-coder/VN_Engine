import json
from io import BytesIO
import os
from pathlib import Path
import sys

import yaml

from engine.embedded import (
    EMBEDDED_ENABLED,
    EmbeddedFile,
    bytes_for_path,
    has_resource,
    path_exists,
)


NORMAL_ENGINE_DIR = Path(__file__).resolve().parent
NORMAL_PROJECT_ROOT = NORMAL_ENGINE_DIR.parent
MEIPASS_ROOT = getattr(sys, "_MEIPASS", None)
IS_FROZEN = getattr(sys, "frozen", False)
NUITKA_COMPILED = globals().get("__compiled__")
IS_NUITKA = "__compiled__" in globals()
IS_COMPILED = IS_NUITKA or IS_FROZEN


def _compiled_content_root() -> Path:
    """Find the folder containing loose project data beside a compiled engine."""
    executable_parent = Path(sys.executable).resolve().parent
    if (
        sys.platform == "darwin"
        and executable_parent.name.casefold() == "macos"
        and executable_parent.parent.name.casefold() == "contents"
    ):
        return executable_parent.parent / "Resources"
    return executable_parent


def _executable_roots() -> list[Path]:
    if not IS_COMPILED:
        return []

    # Exported templates keep project assets/data beside the executable on
    # Windows/Linux, and in Contents/Resources for a macOS app bundle.
    roots = [_compiled_content_root()]
    if IS_NUITKA:
        if sys.argv and Path(sys.argv[0]).suffix.casefold() not in {".py", ".pyc"}:
            roots.append(Path(sys.argv[0]).resolve().parent)
        containing_dir = getattr(NUITKA_COMPILED, "containing_dir", None)
        if containing_dir:
            roots.append(Path(containing_dir).resolve())
    roots.append(Path(sys.executable).resolve().parent)
    return list(dict.fromkeys(roots))


EXECUTABLE_ROOTS = _executable_roots()
EXECUTABLE_ROOT = EXECUTABLE_ROOTS[0] if EXECUTABLE_ROOTS else None

if EMBEDDED_ENABLED:
    # Embedded engine resources are keyed from the executable's directory;
    # project assets/data may still be supplied there as loose files.
    if IS_NUITKA:
        containing_dir = getattr(NUITKA_COMPILED, "containing_dir", None)
        EMBEDDED_ROOT = (
            EXECUTABLE_ROOT
            or (
                Path(containing_dir).resolve()
                if containing_dir
                else Path(sys.executable).resolve().parent
            )
        )
    else:
        EMBEDDED_ROOT = Path(sys.argv[0]).resolve().parent if sys.argv else NORMAL_PROJECT_ROOT
    PROJECT_ROOTS = list(dict.fromkeys((EMBEDDED_ROOT, EMBEDDED_ROOT.parent)))
    ENGINE_DIRS = [EMBEDDED_ROOT / "engine"]
else:
    EMBEDDED_ROOT = None


def _select_root(candidates: list[Path], markers: tuple[str, ...]) -> Path:
    roots = list(dict.fromkeys(candidates))
    for root in roots:
        if any((root / marker).exists() for marker in markers):
            return root
    for root in roots:
        if (root / "data").is_dir():
            return root
    return roots[0]


if not EMBEDDED_ENABLED:
    PROJECT_ROOTS = list(
        dict.fromkeys(
            candidate
            for executable_root in EXECUTABLE_ROOTS
            for candidate in (executable_root, executable_root.parent)
        )
    )
    ENGINE_DIRS = [root / "engine" for root in EXECUTABLE_ROOTS]
    if IS_NUITKA:
        containing_dir = getattr(NUITKA_COMPILED, "containing_dir", None)
        if containing_dir:
            compiled_root = Path(containing_dir).resolve()
            PROJECT_ROOTS.append(compiled_root)
            ENGINE_DIRS.append(compiled_root / "engine")
    PROJECT_ROOTS.append(NORMAL_PROJECT_ROOT)
    ENGINE_DIRS.append(NORMAL_ENGINE_DIR)
    if MEIPASS_ROOT is not None:
        meipass_root = Path(MEIPASS_ROOT).resolve()
        PROJECT_ROOTS.append(meipass_root)
        ENGINE_DIRS.append(meipass_root / "engine")

PROJECT_ROOT_OVERRIDE = os.environ.get("VN_ENGINE_PROJECT_DIR")
if PROJECT_ROOT_OVERRIDE:
    PROJECT_ROOT = Path(PROJECT_ROOT_OVERRIDE).expanduser().resolve()
    PROJECT_ASSETS_ROOT = PROJECT_ROOT
else:
    PROJECT_ROOT = _select_root(
        PROJECT_ROOTS,
        ("data/project.json", "data/story.yaml"),
    )
    PROJECT_ASSETS_ROOT = _select_root(PROJECT_ROOTS, ("assets",))
ENGINE_DIR = _select_root(
    ENGINE_DIRS,
    ("data/settings.json", "assets", "data"),
)
USER_DATA_ROOT = EMBEDDED_ROOT or EXECUTABLE_ROOT or PROJECT_ROOT
if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
    USER_DATA_ROOT = Path(os.environ["LOCALAPPDATA"]) / "Visual Novel Engine"
    USE_LOCAL_APP_DATA = True
elif sys.platform == "win32":
    USER_DATA_ROOT = EMBEDDED_ROOT or EXECUTABLE_ROOT or PROJECT_ROOT
    USE_LOCAL_APP_DATA = False
elif sys.platform == "darwin":
    USER_DATA_ROOT = Path.home() / "Library" / "Application Support" / "Visual Novel Engine"
    USE_LOCAL_APP_DATA = True
else:
    USER_DATA_ROOT = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "visual-novel-engine"
    USE_LOCAL_APP_DATA = True
PORTABLE_USER_DATA = (EXECUTABLE_ROOT or PROJECT_ROOT) / "user_data"


class PATHS:
    engine = ENGINE_DIR
    project = PROJECT_ROOT
    engine_data = ENGINE_DIR / "data"
    project_data = PROJECT_ROOT / "data"
    project_assets = PROJECT_ASSETS_ROOT / "assets"
    engine_assets = ENGINE_DIR / "assets"
    user_data_root = USER_DATA_ROOT
    user_data = USER_DATA_ROOT / "user_data"
    portable_user_data = PORTABLE_USER_DATA
    use_local_app_data = USE_LOCAL_APP_DATA

    # Compatibility names for the engine's own resources and internal data.
    data = engine_data
    images = engine_assets / "images"
    sounds = engine_assets / "sounds"
    music = engine_assets / "music"
    fonts = engine_assets / "fonts"


class loader:
    @staticmethod
    def load_image(name: Path | str):
        import pygame

        path = PATHS.images / name
        data = bytes_for_path(path, ((PATHS.engine_assets, "engine/assets"),))
        if data is not None:
            return pygame.image.load(BytesIO(data), Path(name).name)
        return pygame.image.load(str(path))

    @staticmethod
    def load_sound(name: Path | str):
        import pygame

        path = PATHS.sounds / name
        data = bytes_for_path(path, ((PATHS.engine_assets, "engine/assets"),))
        if data is not None:
            return pygame.mixer.Sound(file=BytesIO(data))
        return pygame.mixer.Sound(str(path))

    @staticmethod
    def music_path(name: Path | str) -> Path | EmbeddedFile:
        path = PATHS.music / name
        key = (Path("engine/assets/music") / name).as_posix()
        if has_resource(key):
            return EmbeddedFile(key)
        return path

    @staticmethod
    def load_font(name: Path | str, size: int):
        import pygame

        path = PATHS.fonts / name
        data = bytes_for_path(path, ((PATHS.engine_assets, "engine/assets"),))
        if data is not None:
            return pygame.font.Font(BytesIO(data), size)
        return pygame.font.Font(path, size)

    @staticmethod
    def load_json(name: Path | str):
        return loader._load_json(PATHS.engine_data / name)

    @staticmethod
    def load_project_json(name: Path | str, data_dir: Path | None = None):
        root = data_dir or PATHS.project_data
        return loader._load_json(root / name)

    @staticmethod
    def load_project_yaml(name: Path | str, data_dir: Path | None = None):
        root = data_dir or PATHS.project_data
        root = Path(root).resolve()
        story_path = Path(name)
        if not story_path.is_absolute():
            story_path = root / story_path
        return loader._load_story_tree(story_path, root)

    @staticmethod
    def _load_story_tree(path: Path, data_root: Path, stack=(), is_root=True):
        """Load a YAML story and merge its explicitly included dialogue files."""
        path = path.resolve()
        try:
            relative = path.relative_to(data_root)
        except ValueError as error:
            raise ValueError(f"Story include must stay inside the data folder: {path}") from error
        if path.suffix.casefold() not in {".yaml", ".yml"}:
            raise ValueError(f"Story files must use .yaml or .yml: {path}")
        if path in stack:
            cycle = " -> ".join(item.name for item in (*stack, path))
            raise ValueError(f"Story include cycle detected: {cycle}")

        document = loader._load_yaml(path)
        if not isinstance(document, dict):
            raise ValueError(f"Story file {relative.as_posix()!r} must contain a YAML mapping.")
        includes = document.pop("includes", [])
        if not isinstance(includes, list) or any(not isinstance(item, str) or not item.strip() for item in includes):
            raise ValueError(f"{relative.as_posix()}: 'includes' must be a list of YAML paths.")

        merged = {"dialogues": {}, "variables": {}, "character_defaults": {}}
        next_stack = (*stack, path)
        for include in includes:
            include_path = Path(include.replace("\\", "/"))
            if include_path.is_absolute():
                raise ValueError(f"{relative.as_posix()}: include paths must be relative to the data folder.")
            child = loader._load_story_tree(path.parent / include_path, data_root, next_stack, is_root=False)
            for key in merged:
                values = child.get(key, {})
                if not isinstance(values, dict):
                    raise ValueError(f"{include!r}: '{key}' must be a YAML mapping.")
                overlap = set(merged[key]).intersection(values)
                if overlap:
                    names = ", ".join(sorted(map(str, overlap)))
                    raise ValueError(f"Duplicate {key} IDs/names across included stories: {names}.")
                merged[key].update(values)

        if not is_root:
            illegal = set(document) - set(merged)
            if illegal:
                names = ", ".join(sorted(illegal))
                raise ValueError(
                    f"Included story {relative.as_posix()!r} may define only includes, dialogues, "
                    f"variables, and character_defaults; found: {names}."
                )

        for key in merged:
            values = document.get(key, {})
            if not isinstance(values, dict):
                raise ValueError(f"{relative.as_posix()}: '{key}' must be a YAML mapping.")
            overlap = set(merged[key]).intersection(values)
            if overlap:
                names = ", ".join(sorted(map(str, overlap)))
                raise ValueError(f"Duplicate {key} IDs/names across included stories: {names}.")
            merged[key].update(values)

        if not is_root:
            return merged
        result = {key: value for key, value in document.items() if key not in merged}
        result.update(merged)
        return result

    @staticmethod
    def _load_json(path: Path):
        data = bytes_for_path(
            path,
            (
                (PATHS.project_data, "data"),
                (PATHS.engine_data, "engine/data"),
            ),
        )
        if data is not None:
            return json.loads(data.decode("utf-8"))
        with path.open(encoding="utf-8") as data_file:
            return json.load(data_file)

    @staticmethod
    def _load_yaml(path: Path):
        try:
            data = bytes_for_path(
                path,
                (
                    (PATHS.project_data, "data"),
                    (PATHS.engine_data, "engine/data"),
                ),
            )
            if data is not None:
                return yaml.safe_load(data.decode("utf-8"))
            with path.open(encoding="utf-8") as data_file:
                return yaml.safe_load(data_file)
        except yaml.YAMLError as error:
            raise ValueError(f"Invalid YAML in {path}: {error}") from error

    @staticmethod
    def project_file_exists(name: Path | str, data_dir: Path | None = None) -> bool:
        root = data_dir or PATHS.project_data
        return path_exists(
            root / name,
            (
                (PATHS.project_data, "data"),
                (PATHS.engine_data, "engine/data"),
            ),
        )
