"""Access project resources compiled into the executable as Python constants."""

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path, PurePosixPath
import sys
from zipfile import BadZipFile, ZipFile

try:
    from engine._embedded_payload import RESOURCE_MODULES
except ModuleNotFoundError as error:
    if error.name != "engine._embedded_payload":
        raise
    RESOURCE_MODULES = {}


PROJECT_BUNDLE_COMMENT = b"VN_ENGINE_GAME_BUNDLE_V1"


def _load_project_bundle():
    executable = Path(sys.argv[0]).resolve() if sys.argv else None
    if executable is None or executable.suffix.casefold() in {".py", ".pyc"} or not executable.is_file():
        return None, {}
    try:
        archive = ZipFile(executable)
    except BadZipFile:
        return None, {}
    if archive.comment != PROJECT_BUNDLE_COMMENT:
        archive.close()
        return None, {}

    resources = {}
    for name in archive.namelist():
        if name.endswith("/"):
            continue
        normalized = name.replace("\\", "/")
        relative = PurePosixPath(normalized)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or relative.parts[0] not in {"assets", "data"}
        ):
            archive.close()
            raise ValueError(f"Invalid path in embedded project resources: {name!r}")
        folded = normalized.casefold()
        if folded in resources:
            archive.close()
            raise ValueError(f"Duplicate embedded project resource: {name!r}")
        resources[folded] = normalized
    has_story = any(
        key.startswith("data/") and PurePosixPath(key).suffix.casefold() in {".yaml", ".yml"}
        for key in resources
    )
    if "data/project.json" not in resources or not has_story:
        archive.close()
        raise ValueError("The embedded game executable is missing its project configuration or story.")
    return archive, resources


_PROJECT_ARCHIVE, _PROJECT_RESOURCE_KEYS_BY_CASEFOLD = _load_project_bundle()
EMBEDDED_ENABLED = bool(RESOURCE_MODULES or _PROJECT_RESOURCE_KEYS_BY_CASEFOLD)
_RESOURCE_KEYS_BY_CASEFOLD = {}
for _resource_key in RESOURCE_MODULES:
    _RESOURCE_KEYS_BY_CASEFOLD.setdefault(_resource_key.casefold(), _resource_key)


def project_bundle_present() -> bool:
    return _PROJECT_ARCHIVE is not None


@dataclass(frozen=True)
class EmbeddedFile:
    key: str

    @property
    def name(self) -> str:
        return PurePosixPath(self.key).name

    @property
    def suffix(self) -> str:
        return PurePosixPath(self.key).suffix


def has_resource(key: str) -> bool:
    normalized = key.replace("\\", "/").lstrip("/")
    folded = normalized.casefold()
    return (
        normalized in RESOURCE_MODULES
        or folded in _RESOURCE_KEYS_BY_CASEFOLD
        or folded in _PROJECT_RESOURCE_KEYS_BY_CASEFOLD
    )


def read_resource(key: str) -> bytes:
    normalized = key.replace("\\", "/").lstrip("/")
    normalized = _RESOURCE_KEYS_BY_CASEFOLD.get(normalized.casefold(), normalized)
    module_name = RESOURCE_MODULES.get(normalized)
    if module_name is not None:
        module = import_module(f"engine._embedded_payload.{module_name}")
        return module.DATA
    project_key = _PROJECT_RESOURCE_KEYS_BY_CASEFOLD.get(normalized.casefold())
    if project_key is not None and _PROJECT_ARCHIVE is not None:
        return _PROJECT_ARCHIVE.read(project_key)
    raise FileNotFoundError(f"Embedded resource {normalized!r} was not found.")


def resources_under(prefix: str) -> tuple[str, ...]:
    normalized = prefix.replace("\\", "/").strip("/")
    start = f"{normalized}/" if normalized else ""
    keys = set(RESOURCE_MODULES)
    keys.update(_PROJECT_RESOURCE_KEYS_BY_CASEFOLD.values())
    return tuple(sorted(key for key in keys if key.startswith(start)))


def prefix_for_root(root) -> str | None:
    """Return the embedded namespace corresponding to one of the engine roots."""
    if not EMBEDDED_ENABLED or root is None:
        return None

    from engine.loader import PATHS

    requested = Path(root).resolve()
    for candidate, prefix in (
        (PATHS.project_assets, "assets"),
        (PATHS.engine_assets, "engine/assets"),
        (PATHS.project_data, "data"),
        (PATHS.engine_data, "engine/data"),
    ):
        if requested == Path(candidate).resolve():
            return prefix
    return None


def bytes_for_path(path, roots) -> bytes | None:
    """Read a path from the embedded bundle when it is under a known root."""
    if not EMBEDDED_ENABLED:
        return None

    target = Path(path)
    for root, prefix in roots:
        try:
            relative = target.relative_to(Path(root))
        except ValueError:
            continue
        key = PurePosixPath(prefix, relative.as_posix()).as_posix()
        if has_resource(key):
            return read_resource(key)
    return None


def path_exists(path, roots) -> bool:
    if Path(path).is_file():
        return True
    if not EMBEDDED_ENABLED:
        return False
    target = Path(path)
    for root, prefix in roots:
        try:
            relative = target.relative_to(Path(root))
        except ValueError:
            continue
        key = PurePosixPath(prefix, relative.as_posix()).as_posix()
        if has_resource(key):
            return True
    return False


def find_asset(root, category: str, name: str) -> EmbeddedFile | None:
    prefix = prefix_for_root(root)
    if prefix is None:
        return None

    requested = PurePosixPath(str(name).replace("\\", "/"))
    if requested.is_absolute() or ".." in requested.parts:
        return None

    direct_key = PurePosixPath(prefix, requested.as_posix()).as_posix()
    categorized_key = PurePosixPath(prefix, category, requested.as_posix()).as_posix()
    for candidate in (direct_key, categorized_key):
        if has_resource(candidate):
            canonical = _RESOURCE_KEYS_BY_CASEFOLD.get(candidate.casefold(), candidate)
            return EmbeddedFile(canonical)

    if requested.suffix:
        return None

    category_prefix = PurePosixPath(prefix, category).as_posix()
    wanted = requested.as_posix().casefold()
    for key in resources_under(category_prefix):
        relative = PurePosixPath(key).relative_to(category_prefix)
        if (
            relative.stem.casefold() == wanted
            or relative.with_suffix("").as_posix().casefold() == wanted
        ):
            return EmbeddedFile(key)
    return None
