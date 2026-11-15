"""Package a project with a prebuilt VN Engine runtime template."""

from copy import deepcopy
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import tempfile
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo


PLATFORMS = {"windows", "linux", "macos"}


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

    temporary_handle = tempfile.NamedTemporaryFile(
        prefix=f".{output_file.stem}_", suffix=".tmp", dir=output_file.parent, delete=False
    )
    temporary_zip = Path(temporary_handle.name)
    temporary_handle.close()
    seen_names = set()
    found_main = False
    try:
        with ZipFile(template_file, "r") as template, ZipFile(
            temporary_zip, "w", compression=ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for item in template.infolist():
                relative = _validate_zip_name(item.filename)
                destination_name = _archive_name(relative, platform, name)
                info = _template_info(item, destination_name, platform)
                if destination_name in seen_names:
                    raise ValueError(f"Template has duplicate paths after renaming: {destination_name}")
                seen_names.add(destination_name)
                content = b"" if item.is_dir() else template.read(item)
                if platform == "macos" and destination_name.endswith(".app/Contents/Info.plist"):
                    content = _rewrite_bundle_info(content, name)
                if destination_name == _main_executable_path(platform, name):
                    found_main = True
                archive.writestr(info, content)

            if not found_main:
                raise ValueError(
                    f"Template is missing its main executable at {_main_executable_path(platform, name)!r}."
                )

            project_base = f"{name}.app/Contents/Resources" if platform == "macos" else name
            for directory in (project_base, f"{project_base}/assets", f"{project_base}/data"):
                directory_name = directory.rstrip("/") + "/"
                if directory_name in seen_names:
                    continue
                seen_names.add(directory_name)
                info = ZipInfo(directory_name)
                if platform in {"linux", "macos"}:
                    info.create_system = 3
                    info.external_attr = 0o755 << 16
                archive.writestr(info, b"")

            for prefix, source_root in (("assets", assets_root), ("data", data_root)):
                for archive_name, source_path in _iter_project_files(source_root, prefix):
                    destination_name = (
                        f"{name}.app/Contents/Resources/{archive_name}"
                        if platform == "macos"
                        else f"{name}/{archive_name}"
                    )
                    if destination_name in seen_names:
                        raise ValueError(f"Template path conflicts with project file: {destination_name}")
                    seen_names.add(destination_name)
                    info = ZipInfo(destination_name)
                    info.compress_type = ZIP_DEFLATED
                    if platform in {"linux", "macos"}:
                        info.create_system = 3
                        info.external_attr = (0o755 if _is_shared_library(destination_name) else 0o644) << 16
                    archive.writestr(info, source_path.read_bytes())

            config_name = (
                f"{name}.app/Contents/Resources/data/project.json"
                if platform == "macos"
                else f"{name}/data/project.json"
            )
            info = ZipInfo(config_name)
            info.compress_type = ZIP_DEFLATED
            if platform in {"linux", "macos"}:
                info.create_system = 3
                info.external_attr = 0o644 << 16
            archive.writestr(info, project_json)
        os.replace(temporary_zip, output_file)
    except BadZipFile as error:
        temporary_zip.unlink(missing_ok=True)
        raise ValueError(f"Export template is not a valid ZIP file: {template_file}") from error
    except Exception:
        temporary_zip.unlink(missing_ok=True)
        raise
    return output_file
