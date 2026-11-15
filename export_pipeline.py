"""Package a project with a prebuilt VN Engine runtime template."""

from copy import deepcopy
from contextlib import contextmanager
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import stat
import struct
import tempfile
from uuid import UUID
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo


PLATFORMS = {"windows", "linux", "macos"}
PROJECT_BUNDLE_COMMENT = b"VN_ENGINE_GAME_BUNDLE_V1"


@contextmanager
def _open_template_archive(template_file: Path):
    """Open a template ZIP, including the common one-file ZIP wrapper format."""
    archive = ZipFile(template_file, "r")
    try:
        files = [item for item in archive.infolist() if not item.is_dir()]
        if (
            len(files) == 1
            and files[0].filename.casefold() == template_file.name.casefold()
            and files[0].filename.casefold().endswith(".zip")
        ):
            nested_data = archive.read(files[0])
            archive.close()
            with ZipFile(BytesIO(nested_data), "r") as nested:
                yield nested
            return
        yield archive
    finally:
        archive.close()


def safe_project_name(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .")
    if Path(name).suffix.casefold() == ".exe":
        name = name[:-4].rstrip(" .")
    if not name:
        name = "Visual Novel"
    if name.split(".", 1)[0].upper() in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }:
        name = f"_{name}"
    return name


def _resolve_config_path(root: Path, value, fallback: str) -> Path:
    path = Path(value if isinstance(value, str) and value else fallback)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _validate_zip_name(name: str) -> PurePosixPath:
    relative = PurePosixPath(name.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"Template contains an unsafe path: {name!r}.")
    return relative


def _archive_name(relative: PurePosixPath, platform: str, game_name: str) -> str:
    parts = list(relative.parts)
    if platform in {"windows", "linux"}:
        if parts[0] != "Runner":
            raise ValueError("Desktop templates must contain a top-level Runner/ folder.")
        parts[0] = game_name
        if len(parts) == 2 and parts[1] == "Runner.exe":
            parts[1] = f"{game_name}.exe"
        elif len(parts) == 2 and parts[1] == "Runner":
            parts[1] = game_name
    else:
        if parts[0] != "Runner.app":
            raise ValueError("The macOS template must contain a top-level Runner.app bundle.")
        parts[0] = f"{game_name}.app"
    return PurePosixPath(*parts).as_posix()


def _main_executable_path(platform: str, game_name: str) -> str:
    if platform == "windows":
        return f"{game_name}/{game_name}.exe"
    if platform == "linux":
        return f"{game_name}/{game_name}"
    return f"{game_name}.app/Contents/MacOS/Runner"


def _is_shared_library(name: str) -> bool:
    filename = PurePosixPath(name).name.casefold()
    return filename.endswith((".so", ".dylib")) or ".so." in filename


def _rewrite_bundle_info(data: bytes, game_name: str) -> bytes:
    try:
        values = plistlib.loads(data)
    except Exception:
        return data
    if not isinstance(values, dict):
        return data
    for key in ("CFBundleName", "CFBundleDisplayName"):
        if key in values:
            values[key] = game_name
    return plistlib.dumps(values, fmt=plistlib.FMT_BINARY if data.startswith(b"bplist") else plistlib.FMT_XML)


def _template_info(source: ZipInfo, destination_name: str, platform: str) -> ZipInfo:
    name = destination_name.rstrip("/")
    if source.is_dir() or destination_name.endswith("/"):
        name += "/"
    destination = ZipInfo(name, source.date_time)
    destination.compress_type = ZIP_DEFLATED
    destination.comment = source.comment
    destination.internal_attr = source.internal_attr
    if platform in {"linux", "macos"}:
        destination.create_system = 3
        source_mode = source.external_attr >> 16 if source.create_system == 3 else 0
        file_type = source_mode & 0o170000
        if destination.is_dir():
            mode = 0o40755
        elif file_type == 0o120000:
            mode = source_mode or 0o120777
        elif name == _main_executable_path(platform, _game_name_from_archive(name)) or _is_shared_library(name):
            # Preserve Unix execute bits when this ZIP is later unpacked on macOS/Linux.
            mode = 0o755
        elif source_mode:
            mode = source_mode
        else:
            mode = 0o644
        destination.external_attr = mode << 16
    else:
        destination.create_system = source.create_system
        destination.external_attr = source.external_attr
    return destination


def _game_name_from_archive(name: str) -> str:
    first = PurePosixPath(name).parts[0]
    if first.endswith(".app"):
        return first[:-4]
    return first


def _iter_project_files(root: Path, prefix: str):
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink() or not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root)
        if prefix == "data" and relative.as_posix().casefold() == "project.json":
            continue
        yield PurePosixPath(prefix, relative.as_posix()).as_posix(), path


def _write_project_resource_bundle(
    bundle_path: Path,
    data_root: Path,
    assets_root: Path,
    project_json: bytes,
    story_name: str,
) -> None:
    """Store editable project files in the appended executable resource archive."""
    story_path = PurePosixPath(story_name.replace("\\", "/"))
    if (
        story_path.is_absolute()
        or (story_path.parts and story_path.parts[0].endswith(":"))
        or ".." in story_path.parts
        or not story_path.parts
        or story_path.suffix.casefold() not in {".yaml", ".yml"}
    ):
        raise ValueError("The configured story must be a YAML file inside the project's data folder.")

    seen = set()
    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED, compresslevel=6) as bundle:
        bundle.comment = PROJECT_BUNDLE_COMMENT
        for prefix, source_root in (("data", data_root), ("assets", assets_root)):
            for relative_name, source_path in _iter_project_files(source_root, prefix):
                folded_name = relative_name.casefold()
                if folded_name in seen:
                    raise ValueError(f"Project contains case-colliding resource paths: {relative_name!r}.")
                seen.add(folded_name)
                bundle.write(source_path, relative_name)
        story_key = PurePosixPath("data", story_path.as_posix()).as_posix().casefold()
        if story_key not in seen:
            raise FileNotFoundError(f"Configured story file was not found in the project's data folder: {story_name}")
        config_key = "data/project.json"
        if config_key in seen:
            raise ValueError("The project data folder has an ambiguous project.json path.")
        bundle.writestr(config_key, project_json)


def _windows_shortcut_bytes(relative_target: str, executable_size: int) -> bytes:
    """Create a minimal Unicode Windows Shell Link with a portable relative target."""
    encoded_target = relative_target.encode("utf-16-le")
    character_count = len(encoded_target) // 2
    if character_count > 260:
        raise ValueError("The game name is too long for a Windows shortcut.")

    # ShellLinkHeader, RelativePath StringData, and the required terminal block.
    header = struct.pack(
        "<I16sIIQQQIiIHHII",
        0x4C,
        UUID("00021401-0000-0000-C000-000000000046").bytes_le,
        0x00000008 | 0x00000080,  # HasRelativePath | IsUnicode
        0x00000020,  # FILE_ATTRIBUTE_ARCHIVE
        0,
        0,
        0,
        min(executable_size, 0xFFFFFFFF),
        0,
        1,  # SW_SHOWNORMAL
        0,
        0,
        0,
        0,
    )
    return header + struct.pack("<H", character_count) + encoded_target + struct.pack("<I", 0)


def _shortcut_entry(platform: str, game_name: str, executable_size: int) -> tuple[str, bytes, bool]:
    """Return the platform-native relative shortcut name, payload, and symlink flag."""
    if platform == "windows":
        return (
            f"{game_name}/Shortcut.lnk",
            _windows_shortcut_bytes(f"{game_name}.exe", executable_size),
            False,
        )
    if platform == "linux":
        return f"{game_name}/Shortcut", game_name.encode("utf-8"), True
    return f"{game_name} Shortcut.app", f"{game_name}.app".encode("utf-8"), True


def export_project(
    project_root: Path,
    project_file: Path,
    templates_dir: Path,
    platform: str,
    output_file: Path,
) -> Path:
    """Create a standalone game ZIP using the precompiled template for a target OS."""
    if platform not in PLATFORMS:
        raise ValueError(f"Platform must be one of: {', '.join(sorted(PLATFORMS))}.")

    project_root = Path(project_root).resolve()
    project_file = Path(project_file).resolve()
    templates_dir = Path(templates_dir).resolve()
    output_file = Path(output_file).expanduser().resolve()
    template_file = templates_dir / f"template-{platform}.zip"
    if not template_file.is_file():
        raise FileNotFoundError(f"Export template not found: {template_file}")
    if output_file == template_file:
        raise ValueError("The output ZIP cannot overwrite the export template.")

    try:
        project_values = json.loads(project_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read project configuration {project_file}: {error}") from error
    if not isinstance(project_values, dict):
        raise ValueError("Project configuration must be a JSON object.")

    name = safe_project_name(project_values.get("name", "Visual Novel"))
    paths = project_values.get("paths", {})
    if not isinstance(paths, dict):
        paths = {}
    data_root = _resolve_config_path(project_root, paths.get("data"), "data")
    assets_root = _resolve_config_path(project_root, paths.get("assets"), "assets")
    if not data_root.is_dir():
        raise FileNotFoundError(f"Project data folder not found: {data_root}")
    if not assets_root.is_dir():
        raise FileNotFoundError(f"Project assets folder not found: {assets_root}")
    if not project_file.is_file():
        raise FileNotFoundError(f"Project configuration not found: {project_file}")

    project_values = deepcopy(project_values)
    story_name = project_values.get("story", "story.yaml")
    if not isinstance(story_name, str):
        raise ValueError("Project configuration 'story' must be a YAML filename.")
    story_path = PurePosixPath(story_name.replace("\\", "/"))
    if (
        story_path.is_absolute()
        or (story_path.parts and story_path.parts[0].endswith(":"))
        or ".." in story_path.parts
    ):
        raise ValueError("The configured story must stay inside the project's data folder.")
    project_values["story"] = story_path.as_posix()
    project_paths = project_values.setdefault("paths", {})
    if not isinstance(project_paths, dict):
        raise ValueError("Project configuration 'paths' must be an object.")
    project_paths.update({"data": "data", "assets": "assets", "user_data": "user_data"})
    project_json = (json.dumps(project_values, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    for source_root in (data_root, assets_root):
        try:
            output_file.relative_to(source_root)
        except ValueError:
            pass
        else:
            raise ValueError("Choose an export ZIP outside the project's data and assets folders.")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".vn_export_{platform}_", dir=output_file.parent) as temporary:
        workspace = Path(temporary)
        bundle_path = workspace / "project_resources.zip"
        _write_project_resource_bundle(
            bundle_path,
            data_root,
            assets_root,
            project_json,
            story_path.as_posix(),
        )

        executable_path = _main_executable_path(platform, name)
        try:
            with _open_template_archive(template_file) as template:
                executable_items = [
                    item
                    for item in template.infolist()
                    if not item.is_dir()
                    and _archive_name(_validate_zip_name(item.filename), platform, name) == executable_path
                ]
                if len(executable_items) != 1:
                    raise ValueError(f"Template must contain one main executable at {executable_path!r}.")
                executable_item = executable_items[0]
                staged_executable = workspace.joinpath(*PurePosixPath(executable_path).parts)
                staged_executable.parent.mkdir(parents=True, exist_ok=True)
                with template.open(executable_item, "r") as source, staged_executable.open("wb") as target:
                    shutil.copyfileobj(source, target)
                    with bundle_path.open("rb") as bundle:
                        shutil.copyfileobj(bundle, target)
                if platform in {"linux", "macos"}:
                    staged_executable.chmod(staged_executable.stat().st_mode | 0o111)
        except BadZipFile as error:
            raise ValueError(f"Export template is not a valid ZIP file: {template_file}") from error

        shortcut_name, shortcut_content, shortcut_is_symlink = _shortcut_entry(
            platform, name, staged_executable.stat().st_size
        )
        if not shortcut_is_symlink:
            shortcut_path = workspace / shortcut_name
            shortcut_path.parent.mkdir(parents=True, exist_ok=True)
            shortcut_path.write_bytes(shortcut_content)

        temporary_zip = workspace / "export.zip"
        seen_names = set()
        found_main = False
        try:
            with _open_template_archive(template_file) as template, ZipFile(
                temporary_zip, "w", compression=ZIP_DEFLATED, compresslevel=6
            ) as archive:
                for item in template.infolist():
                    relative = _validate_zip_name(item.filename)
                    if (
                        platform == "macos"
                        and relative.parts[:3] == ("Runner.app", "Contents", "_CodeSignature")
                    ):
                        # Renaming the bundle and changing its executable invalidates the template seal.
                        continue
                    destination_name = _archive_name(relative, platform, name)
                    if item.is_dir() and not destination_name.endswith("/"):
                        destination_name += "/"
                    info = _template_info(item, destination_name, platform)
                    if destination_name in seen_names:
                        raise ValueError(f"Template has duplicate paths after renaming: {destination_name}")
                    seen_names.add(destination_name)
                    if destination_name == executable_path:
                        found_main = True
                        with template.open(item, "r") as source, archive.open(info, "w") as target:
                            shutil.copyfileobj(source, target)
                            with bundle_path.open("rb") as bundle:
                                shutil.copyfileobj(bundle, target)
                    else:
                        content = b"" if item.is_dir() else template.read(item)
                        if platform == "macos" and destination_name.endswith(".app/Contents/Info.plist"):
                            content = _rewrite_bundle_info(content, name)
                        archive.writestr(info, content)

                if not found_main:
                    raise ValueError(f"Template is missing its main executable at {executable_path!r}.")

                shortcut_info = ZipInfo(shortcut_name)
                shortcut_info.compress_type = ZIP_DEFLATED
                if shortcut_is_symlink:
                    shortcut_info.create_system = 3
                    shortcut_info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(shortcut_info, shortcut_content)
                else:
                    archive.writestr(shortcut_info, (workspace / shortcut_name).read_bytes())

            os.replace(temporary_zip, output_file)
        except BadZipFile as error:
            raise ValueError(f"Export template is not a valid ZIP file: {template_file}") from error
    return output_file
