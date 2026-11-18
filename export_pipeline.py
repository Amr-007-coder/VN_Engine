"""Package a project with a prebuilt VN Engine runtime template."""

from copy import copy, deepcopy
from contextlib import contextmanager
from io import BytesIO
import gzip
import html
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import tarfile
import xml.etree.ElementTree as ET
from uuid import UUID
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

from engine.icon_utils import make_icns, make_ico, update_windows_executable_icon
from template_repository import ensure_template, fetch_android_sources, latest_template_release_tag


PLATFORMS = {"windows", "linux", "macos", "web", "android"}
PROJECT_BUNDLE_COMMENT = b"VN_ENGINE_GAME_BUNDLE_V1"
ANDROID_APP_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")


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


def _project_icon_path(assets_root: Path, project_values: dict) -> Path | None:
    value = project_values.get("icon")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Project configuration 'icon' must be a relative PNG path or null.")
    relative = PurePosixPath(value.replace("\\", "/"))
    if (
        not value.strip()
        or relative.is_absolute()
        or re.match(r"^[A-Za-z]:", value) is not None
        or ".." in relative.parts
        or relative.suffix.casefold() != ".png"
    ):
        raise ValueError("Project configuration 'icon' must be a relative PNG path inside the project's assets folder.")

    root = assets_root.resolve()
    candidates = (root / Path(*relative.parts), root / "images" / Path(*relative.parts))
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_relative_to(root) and resolved.is_file():
            return resolved
    raise FileNotFoundError(f"Project icon image was not found in the assets folder: {value}")


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


def _resolve_template_file(
    templates_dir: Path,
    platform: str,
    release_tag: str | None = None,
) -> Path:
    if release_tag is not None:
        return ensure_template(platform, release_tag)
    template_file = Path(templates_dir) / f"template-{platform}.zip"
    if template_file.is_file():
        return template_file
    return ensure_template(platform)


def _main_executable_path(platform: str, game_name: str) -> str:
    if platform == "windows":
        return f"{game_name}/{game_name}.exe"
    if platform == "linux":
        return f"{game_name}/{game_name}"
    return f"{game_name}.app/Contents/MacOS/Runner"


def _is_shared_library(name: str) -> bool:
    filename = PurePosixPath(name).name.casefold()
    return filename.endswith((".so", ".dylib")) or ".so." in filename


def _rewrite_bundle_info(data: bytes, game_name: str, icon_filename: str | None = None) -> bytes:
    try:
        values = plistlib.loads(data)
    except (plistlib.InvalidFileException, ValueError, TypeError) as error:
        if icon_filename is not None:
            raise ValueError(f"Could not update the macOS app icon in its Info.plist: {error}") from error
        return data
    if not isinstance(values, dict):
        if icon_filename is not None:
            raise ValueError("The macOS app Info.plist must contain a dictionary to set a custom icon.")
        return data
    for key in ("CFBundleName", "CFBundleDisplayName"):
        if key in values:
            values[key] = game_name
    if icon_filename:
        values["CFBundleIconFile"] = icon_filename
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


def _prepare_project_export(project_root: Path, project_file: Path):
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
        or not story_path.parts
        or story_path.suffix.casefold() not in {".yaml", ".yml"}
    ):
        raise ValueError("The configured story must be a YAML file inside the project's data folder.")
    project_values["story"] = story_path.as_posix()
    project_paths = project_values.setdefault("paths", {})
    if not isinstance(project_paths, dict):
        raise ValueError("Project configuration 'paths' must be an object.")
    project_paths.update({"data": "data", "assets": "assets", "user_data": "user_data"})
    project_json = (json.dumps(project_values, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    icon_path = _project_icon_path(assets_root, project_values)
    return name, data_root, assets_root, story_path, project_json, icon_path


def _replace_pygbag_project_files(apk_data: bytes, project_bundle: Path) -> bytes:
    with ZipFile(BytesIO(apk_data), "r") as source:
        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=6) as destination:
            for item in source.infolist():
                name = item.filename.replace("\\", "/")
                if name.startswith(("assets/assets/", "assets/data/")):
                    continue
                destination.writestr(item, source.read(item))
            with ZipFile(project_bundle, "r") as project_files:
                for item in project_files.infolist():
                    name = f"assets/{item.filename}"
                    info = ZipInfo(name, item.date_time)
                    info.compress_type = ZIP_DEFLATED
                    destination.writestr(info, project_files.read(item))
        return buffer.getvalue()


def export_web_project(
    project_root: Path,
    project_file: Path,
    templates_dir: Path,
    output_file: Path,
) -> Path:
    """Insert a project into the prebuilt Pygbag static-site template."""
    project_root = Path(project_root).resolve()
    project_file = Path(project_file).resolve()
    templates_dir = Path(templates_dir).resolve()
    output_file = Path(output_file).expanduser().resolve()
    template_file = _resolve_template_file(templates_dir, "web")
    if output_file == template_file:
        raise ValueError("The output ZIP cannot overwrite the web export template.")

    name, data_root, assets_root, story_path, project_json, icon_path = _prepare_project_export(project_root, project_file)
    unsupported_audio = sorted(
        path.relative_to(assets_root).as_posix()
        for path in assets_root.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".wav", ".mp3", ".aiff"}
    )
    if unsupported_audio:
        files = ", ".join(unsupported_audio[:8])
        more = "..." if len(unsupported_audio) > 8 else ""
        raise ValueError(
            "Pygbag browser builds require OGG audio. Convert these project assets to .ogg: "
            f"{files}{more}"
        )

    from engine.validator import StoryValidator

    from engine.assets import AssetManager

    assets = AssetManager(assets_root, assets_root / "mods")
    errors = StoryValidator.validate_file(
        story_path.as_posix(), data_root, assets_root, asset_manager=assets
    )
    if errors:
        raise ValueError("Story validation failed:\n" + "\n".join(f"- {error}" for error in errors))

    output_file.parent.mkdir(parents=True, exist_ok=True)
    for source_root in (data_root, assets_root):
        try:
            output_file.relative_to(source_root)
        except ValueError:
            pass
        else:
            raise ValueError("Choose an export ZIP outside the project's data and assets folders.")

    with tempfile.TemporaryDirectory(prefix=".vn_export_web_", dir=output_file.parent) as temporary:
        workspace = Path(temporary)
        project_bundle = workspace / "project_resources.zip"
        _write_project_resource_bundle(
            project_bundle,
            data_root,
            assets_root,
            project_json,
            story_path.as_posix(),
        )
        temporary_output = workspace / "web-export.zip"
        try:
            with ZipFile(template_file, "r") as template:
                app_archives = [
                    item for item in template.infolist()
                    if not item.is_dir() and item.filename.casefold().endswith(".apk")
                ]
                if len(app_archives) != 1:
                    raise ValueError("The web template must contain exactly one Pygbag .apk app archive.")
                app_item = app_archives[0]
                updated_app = _replace_pygbag_project_files(template.read(app_item), project_bundle)

                with ZipFile(temporary_output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
                    for item in template.infolist():
                        if item.is_dir():
                            continue
                        content = updated_app if item.filename == app_item.filename else template.read(item)
                        if item.filename.casefold() == "index.html":
                            page = content.decode("utf-8")
                            page, _ = re.subn(
                                r"<title>.*?</title>",
                                f"<title>{html.escape(name)}</title>",
                                page,
                                count=1,
                                flags=re.IGNORECASE | re.DOTALL,
                            )
                            content = page.encode("utf-8")
                        elif item.filename.casefold() == "favicon.png" and icon_path is not None:
                            content = icon_path.read_bytes()
                        archive.writestr(item, content)
            os.replace(temporary_output, output_file)
        except BadZipFile as error:
            raise ValueError(f"Web export template is not a valid ZIP file: {template_file}") from error
    return output_file


def _android_export_settings(project_values: dict) -> tuple[str, str, str]:
    settings = project_values.get("android", {})
    if not isinstance(settings, dict):
        raise ValueError("Project configuration 'android' must be an object.")

    app_name = settings.get("app_name", "VN Engine")
    if not isinstance(app_name, str) or not app_name.strip():
        raise ValueError("Project configuration 'android.app_name' must be a non-empty string.")

    app_id = settings.get("app_id", "com.example.vnengine")
    if not isinstance(app_id, str) or ANDROID_APP_ID_PATTERN.fullmatch(app_id) is None:
        raise ValueError(
            "Project configuration 'android.app_id' must be a lowercase reverse-DNS identifier, "
            "for example 'com.example.vnengine'."
        )

    orientation = settings.get("orientation", "landscape")
    if not isinstance(orientation, str) or orientation not in {"landscape", "portrait"}:
        raise ValueError("Project configuration 'android.orientation' must be 'landscape' or 'portrait'.")
    return app_name.strip(), app_id, orientation


def _android_sdk_directory() -> Path:
    candidates = [
        os.environ.get("ANDROID_HOME"),
        os.environ.get("ANDROID_SDK_ROOT"),
    ]
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(str(Path(local_app_data) / "Android" / "Sdk"))
    elif sys.platform == "darwin":
        candidates.append(str(Path.home() / "Library" / "Android" / "sdk"))
    else:
        candidates.append(str(Path.home() / "Android" / "Sdk"))

    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            return Path(candidate).resolve()
    raise RuntimeError(
        "Android export requires the Android SDK. Install it with Android Studio or set "
        "ANDROID_HOME/ANDROID_SDK_ROOT to its directory."
    )


def _android_tool(name: str) -> str:
    candidates = (f"{name}.cmd", name) if sys.platform == "win32" else (name,)
    for candidate in candidates:
        executable = shutil.which(candidate)
        if executable:
            return executable
    raise RuntimeError(f"Android export requires {name} on PATH.")


def _run_android_command(command: list[str], working_directory: Path) -> None:
    use_shell = sys.platform == "win32" and Path(command[0]).suffix.casefold() in {".bat", ".cmd"}
    invocation = subprocess.list2cmdline(command) if use_shell else command
    try:
        result = subprocess.run(
            invocation,
            cwd=working_directory,
            check=False,
            capture_output=True,
            text=True,
            shell=use_shell,
        )
    except OSError as error:
        raise RuntimeError(f"Could not run Android export command {command[0]!r}: {error}") from error
    if result.returncode:
        details = (result.stderr or result.stdout).strip()
        if len(details) > 4000:
            details = details[-4000:]
        message = f"Android export command failed: {Path(command[0]).name}"
        if details:
            message += f"\n{details}"
        raise RuntimeError(message)


def _extract_web_site(archive_path: Path, destination: Path) -> None:
    root = destination.resolve()
    try:
        with ZipFile(archive_path, "r") as archive:
            for item in archive.infolist():
                relative = PurePosixPath(item.filename.replace("\\", "/"))
                if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                    raise ValueError(f"Web export contains an unsafe path: {item.filename!r}.")
                target = (root / Path(*relative.parts)).resolve()
                if not target.is_relative_to(root):
                    raise ValueError(f"Web export contains an unsafe path: {item.filename!r}.")
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if (item.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                    raise ValueError(f"Web export contains an unsupported symbolic link: {item.filename!r}.")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item, "r") as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except BadZipFile as error:
        raise ValueError(f"Generated web export is not a valid ZIP file: {archive_path}") from error


def _adapt_android_runtime_archive(
    archive_contents: bytes,
    android_sources: tuple[bytes, bytes, bytes] | None = None,
) -> bytes:
    """Install runtime sources that expose the supported WebView hook API.

    Android sizing lives in Engine's platform hook. The exporter only swaps in
    source files for the matching release and checks that their hook version is
    supported; it does not rewrite Python statements in the template.
    """
    source_buffer = BytesIO(archive_contents)
    output_buffer = BytesIO()
    try:
        with tarfile.open(fileobj=source_buffer, mode="r:") as source:
            members = source.getmembers()
            main_files = [item for item in members if item.name == "assets/main.py" and item.isfile()]
            if len(main_files) != 1:
                raise ValueError("Pygbag runtime archive must contain exactly one assets/main.py entry.")
            engine_files = [
                item for item in members if item.name == "assets/engine/engine.py" and item.isfile()
            ]
            platform_runtime_files = [
                item for item in members
                if item.name == "assets/engine/platform_runtime.py" and item.isfile()
            ]
            if len(engine_files) > 1 or (android_sources is None and len(engine_files) != 1):
                raise ValueError("Pygbag runtime archive must contain exactly one assets/engine/engine.py entry.")
            main_file = source.extractfile(main_files[0])
            engine_file = source.extractfile(engine_files[0]) if engine_files else None
            if main_file is None or (android_sources is None and engine_file is None):
                raise ValueError("Could not read the Pygbag runtime entrypoint.")
            if android_sources is None:
                if engine_file is None:
                    raise ValueError("Could not read assets/engine/engine.py from the Pygbag runtime archive.")
                main_contents = main_file.read()
                engine_contents = engine_file.read()
                platform_runtime_contents = None
                if len(platform_runtime_files) != 1:
                    raise ValueError("Pygbag runtime archive must contain the WebView display hook module.")
            else:
                if len(android_sources) != 3:
                    raise ValueError("Android runtime source bundle must include entrypoint, engine, and display hook files.")
                main_contents, engine_contents, platform_runtime_contents = android_sources

            try:
                engine_source = engine_contents.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("Android runtime engine source must be UTF-8 text.") from error
            hook_version = re.search(
                r"(?m)^ANDROID_WEBVIEW_HOOK_VERSION\s*=\s*(\d+)\s*$",
                engine_source,
            )
            if hook_version is None:
                raise ValueError(
                    "Android runtime source does not declare ANDROID_WEBVIEW_HOOK_VERSION. "
                    "Choose an engine release with the WebView display hook."
                )
            if int(hook_version.group(1)) != 1:
                raise ValueError(
                    f"Unsupported Android WebView hook version {hook_version.group(1)}; "
                    "this exporter supports version 1."
                )

            with tarfile.open(fileobj=output_buffer, mode="w") as destination:
                engine_written = False
                platform_runtime_written = False
                for item in members:
                    bytecode_name = PurePosixPath(item.name).name
                    bytecode_stem = bytecode_name.split(".", 1)[0]
                    if (
                        android_sources is not None
                        and item.name.startswith("assets/")
                        and item.name.casefold().endswith(".pyc")
                        and bytecode_stem in {"_web_main", "web_main", "engine", "platform_runtime"}
                    ):
                        continue
                    member = copy(item)
                    if item.name == "assets/main.py":
                        member.size = len(main_contents)
                        destination.addfile(member, BytesIO(main_contents))
                    elif item.name == "assets/engine/engine.py":
                        member.size = len(engine_contents)
                        destination.addfile(member, BytesIO(engine_contents))
                        engine_written = True
                    elif item.name == "assets/engine/platform_runtime.py" and platform_runtime_contents is not None:
                        member.size = len(platform_runtime_contents)
                        destination.addfile(member, BytesIO(platform_runtime_contents))
                        platform_runtime_written = True
                    elif item.isfile():
                        contents = source.extractfile(item)
                        if contents is None:
                            raise ValueError(f"Could not read Pygbag runtime entry {item.name!r}.")
                        destination.addfile(member, contents)
                    else:
                        destination.addfile(member)
                if android_sources is not None and not engine_written:
                    engine_member = tarfile.TarInfo("assets/engine/engine.py")
                    engine_member.size = len(engine_contents)
                    engine_member.mode = 0o644
                    destination.addfile(engine_member, BytesIO(engine_contents))
                if android_sources is not None and not platform_runtime_written:
                    runtime_member = tarfile.TarInfo("assets/engine/platform_runtime.py")
                    runtime_member.size = len(platform_runtime_contents)
                    runtime_member.mode = 0o644
                    destination.addfile(runtime_member, BytesIO(platform_runtime_contents))
    except (OSError, EOFError, tarfile.TarError, UnicodeDecodeError) as error:
        raise ValueError("Android web export contains an invalid Pygbag runtime archive.") from error
    return output_buffer.getvalue()


def _prepare_android_web_site(
    web_directory: Path,
    window_size: tuple[int, int],
    android_sources: tuple[bytes, bytes, bytes] | None = None,
) -> None:
    width, height = window_size
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or width < 1
        or not isinstance(height, int)
        or isinstance(height, bool)
        or height < 1
    ):
        raise ValueError("Android export requires positive integer project window dimensions.")

    compressed_archive = web_directory / "vn-engine-web.tar.gz"
    tar_archive = web_directory / "vn-engine-web.tar"
    try:
        archive_contents = _adapt_android_runtime_archive(
            gzip.decompress(compressed_archive.read_bytes()),
            android_sources,
        )
        with tarfile.open(fileobj=BytesIO(archive_contents), mode="r:") as archive:
            archive.getmembers()
    except (OSError, EOFError, tarfile.TarError) as error:
        raise ValueError(f"Android web export contains an invalid Pygbag runtime archive: {compressed_archive}") from error
    tar_archive.write_bytes(archive_contents)
    compressed_archive.unlink()

    index_path = web_directory / "index.html"
    page = index_path.read_text(encoding="utf-8")
    viewport_pattern = re.compile(
        r"<meta\b(?=[^>]*\bname\s*=\s*[\"']viewport[\"'])[^>]*>",
        re.IGNORECASE | re.DOTALL,
    )
    viewport_matches = list(viewport_pattern.finditer(page))
    if not viewport_matches:
        raise ValueError(f"Could not adapt Android export: missing mobile viewport metadata in {index_path}.")
    android_viewport = (
        '<meta name="viewport" content="width=device-width, height=device-height, '
        'initial-scale=1.0, viewport-fit=cover">'
    )
    for index in range(len(viewport_matches) - 1, -1, -1):
        match = viewport_matches[index]
        replacement = android_viewport if index == 0 else ""
        page = page[:match.start()] + replacement + page[match.end():]

    canvas_pattern = re.compile(r"<canvas\b(?=[^>]*\bid=[\"']canvas[\"'])[^>]*>", re.IGNORECASE | re.DOTALL)
    canvas_matches = list(canvas_pattern.finditer(page))
    if len(canvas_matches) != 1:
        raise ValueError(f"Could not adapt Android export: expected one main game canvas in {index_path}.")
    canvas_tag = canvas_matches[0].group()
    for attribute, dimension in (("width", width), ("height", height)):
        attribute_pattern = re.compile(rf"(\b{attribute}\s*=\s*)([\"']).*?\2", re.IGNORECASE)
        if len(list(attribute_pattern.finditer(canvas_tag))) != 1:
            raise ValueError(
                f"Could not adapt Android export: expected one canvas {attribute} in {index_path}."
            )
        canvas_tag = attribute_pattern.sub(lambda match: f'{match.group(1)}"{dimension}"', canvas_tag, count=1)
    page = page[:canvas_matches[0].start()] + canvas_tag + page[canvas_matches[0].end():]
    framebuffer_settings = (
        (
            re.compile(r"(?m)^([ \t]*gui_divider[ \t]*:[ \t]*)\d+([ \t]*,?[ \t]*)$"),
            "1",
            "Pygbag initial canvas scale",
        ),
        (
            re.compile(r"(?m)^([ \t]*fb_ar[ \t]*:[ \t]*)\d+(?:\.\d+)?([ \t]*,?[ \t]*)$"),
            f"{width / height:.6g}",
            "Pygbag framebuffer aspect ratio",
        ),
        (
            re.compile(r'(?m)^([ \t]*fb_width[ \t]*:[ \t]*)"\d+"([ \t]*,?[ \t]*)$'),
            f'"{width}"',
            "Pygbag framebuffer width",
        ),
        (
            re.compile(r'(?m)^([ \t]*fb_height[ \t]*:[ \t]*)"\d+"([ \t]*,?[ \t]*)$'),
            f'"{height}"',
            "Pygbag framebuffer height",
        ),
    )
    for pattern, value, description in framebuffer_settings:
        if len(list(pattern.finditer(page))) != 1:
            raise ValueError(f"Could not adapt Android export: expected one {description} in {index_path}.")
        page = pattern.sub(lambda match: f"{match.group(1)}{value}{match.group(2)}", page, count=1)

    source_updates = (
        (
            r"platform\.fopen\s*\(\s*(['\"])vn-engine-web\.tar\.gz\1\s*,\s*(['\"])rb\2\s*\)",
            'platform.fopen("vn-engine-web.tar", "rb")',
            "Pygbag runtime archive path",
        ),
        (
            r"tarfile\.open\s*\(\s*fileobj\s*=\s*archive\s*,\s*mode\s*=\s*(['\"])r:gz\1\s*\)",
            'tarfile.open(fileobj=archive, mode="r:")',
            "Pygbag runtime archive mode",
        ),
        (
            r"(?m)^[ \t]*platform\.window\.transfer\.hidden\s*=\s*true[ \t]*\n",
            "",
            "Pygbag early loader hide",
        ),
        (
            r"(?m)^([ \t]*)platform\.window\.infobox\.style\.display\s*=\s*(['\"])none\2[ \t]*$",
            r'\1platform.window.transfer.hidden = true' + "\n" + r'\1platform.window.infobox.style.display = "none"',
            "Pygbag loader completion",
        ),
        (
            r"(?m)^[ \t]*transfer\.hidden\s*=\s*debug_hidden[ \t]*\n",
            "",
            "Pygbag debug loader toggle",
        ),
    )
    for pattern, replacement, description in source_updates:
        page, count = re.subn(pattern, replacement, page, count=1)
        if count != 1:
            raise ValueError(f"Could not adapt Android export: expected one {description} in {index_path}.")
    index_path.write_text(page, encoding="utf-8", newline="\n")


def _enable_android_fullscreen(android_directory: Path) -> None:
    activity_files = list(android_directory.rglob("MainActivity.java"))
    if len(activity_files) != 1:
        raise FileNotFoundError(
            f"Expected one generated MainActivity.java under {android_directory}; found {len(activity_files)}."
        )
    activity_path = activity_files[0]
    source = activity_path.read_text(encoding="utf-8")
    package_matches = re.findall(r"(?m)^package\s+([A-Za-z_][A-Za-z0-9_.]*)\s*;", source)
    if len(package_matches) != 1 or source.count("public class MainActivity extends BridgeActivity") != 1:
        raise ValueError(f"Could not adapt Capacitor's generated MainActivity at {activity_path}.")
    package_name = package_matches[0]
    activity_path.write_text(
        f"""package {package_name};

import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {{
    @Override
    public void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        hideSystemBars();
    }}

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {{
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {{
            hideSystemBars();
        }}
    }}

    private void hideSystemBars() {{
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {{
            getWindow().setDecorFitsSystemWindows(false);
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {{
                controller.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
                controller.setSystemBarsBehavior(
                    WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                );
            }}
            return;
        }}
        getWindow().getDecorView().setSystemUiVisibility(
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
        );
    }}
}}
""",
        encoding="utf-8",
        newline="\n",
    )


def _set_android_orientation(manifest_path: Path, orientation: str) -> None:
    android_namespace = "http://schemas.android.com/apk/res/android"
    ET.register_namespace("android", android_namespace)
    try:
        tree = ET.parse(manifest_path)
    except ET.ParseError as error:
        raise ValueError(f"Capacitor generated an invalid Android manifest at {manifest_path}: {error}") from error
    activity = next(
        (
            element for element in tree.getroot().iter("activity")
            if element.get(f"{{{android_namespace}}}name", "").endswith(".MainActivity")
        ),
        None,
    )
    if activity is None:
        raise ValueError(f"Could not find Capacitor's MainActivity in {manifest_path}.")
    activity.set(f"{{{android_namespace}}}screenOrientation", orientation)
    tree.write(manifest_path, encoding="utf-8", xml_declaration=True)


def _add_status_bar_hide_script(web_directory: Path, wrapper_directory: Path, npx: str) -> None:
    entry = wrapper_directory / "vn-statusbar-entry.js"
    entry.write_text(
        "import { Capacitor } from '@capacitor/core';\n"
        "import { StatusBar } from '@capacitor/status-bar';\n"
        "const hideStatusBar = () => {\n"
        "  if (Capacitor.isNativePlatform()) {\n"
        "    StatusBar.hide().catch((error) => console.error('Could not hide the Android status bar.', error));\n"
        "  }\n"
        "};\n"
        "if (document.readyState === 'complete') hideStatusBar();\n"
        "else window.addEventListener('load', hideStatusBar, { once: true });\n",
        encoding="utf-8",
    )
    _run_android_command(
        [
            npx, "esbuild", entry.name, "--bundle", "--platform=browser",
            "--format=iife", "--outfile=www/vn-statusbar.js",
        ],
        wrapper_directory,
    )

    index_path = web_directory / "index.html"
    page = index_path.read_text(encoding="utf-8")
    script_tag = '<script src="./vn-statusbar.js"></script>'
    closing_body = re.search(r"</body\s*>", page, flags=re.IGNORECASE)
    if closing_body is None:
        raise ValueError("Web export index.html is missing its closing </body> tag.")
    if "vn-statusbar.js" not in page:
        page = page[:closing_body.start()] + script_tag + page[closing_body.start():]
        index_path.write_text(page, encoding="utf-8")


def _android_signing_environment(environ=None) -> dict[str, str]:
    environ = os.environ if environ is None else environ
    names = {
        "keystore": "VN_ANDROID_KEYSTORE",
        "alias": "VN_ANDROID_KEY_ALIAS",
        "store_password": "VN_ANDROID_STORE_PASSWORD",
        "key_password": "VN_ANDROID_KEY_PASSWORD",
    }
    values = {key: environ.get(name, "").strip() for key, name in names.items()}
    missing = [names[key] for key, value in values.items() if not value and key != "key_password"]
    if missing:
        raise ValueError("Android release signing needs these environment variables: " + ", ".join(missing))
    keystore = Path(values["keystore"]).expanduser().resolve()
    if not keystore.is_file():
        raise FileNotFoundError(f"Android signing keystore was not found: {keystore}")
    values["keystore"] = str(keystore)
    if not values["key_password"]:
        values["key_password"] = values["store_password"]
    return values


def _configure_android_release_signing(app_gradle: Path) -> None:
    if not app_gradle.is_file():
        raise FileNotFoundError(f"Capacitor did not create the Android app Gradle file: {app_gradle}")
    if app_gradle.suffix != ".gradle":
        raise ValueError("Android release signing currently requires the generated Groovy build.gradle file.")
    _android_signing_environment()
    gradle = app_gradle.read_text(encoding="utf-8")
    if "signingConfigs.vnRelease" in gradle:
        raise ValueError("The generated Android project already defines the vnRelease signing configuration.")
    gradle += (
        "\n\n// Signing values are read from the export process environment; secrets stay out of the project.\n"
        "android {\n"
        "    signingConfigs {\n"
        "        vnRelease {\n"
        "            storeFile file(System.getenv('VN_ANDROID_KEYSTORE'))\n"
        "            storePassword System.getenv('VN_ANDROID_STORE_PASSWORD')\n"
        "            keyAlias System.getenv('VN_ANDROID_KEY_ALIAS')\n"
        "            keyPassword System.getenv('VN_ANDROID_KEY_PASSWORD') ?: System.getenv('VN_ANDROID_STORE_PASSWORD')\n"
        "        }\n"
        "    }\n"
        "    buildTypes {\n"
        "        release { signingConfig signingConfigs.vnRelease }\n"
        "    }\n"
        "}\n"
    )
    app_gradle.write_text(gradle, encoding="utf-8", newline="\n")


def _windows_signing_settings() -> tuple[Path, str, str]:
    certificate = os.environ.get("VN_WINDOWS_SIGN_CERT", "").strip()
    password = os.environ.get("VN_WINDOWS_SIGN_PASSWORD", "")
    if not certificate:
        raise ValueError("Windows release signing needs VN_WINDOWS_SIGN_CERT (a PFX file).")
    certificate_path = Path(certificate).expanduser().resolve()
    if not certificate_path.is_file():
        raise FileNotFoundError(f"Windows signing certificate was not found: {certificate_path}")
    sign_tool = os.environ.get("VN_WINDOWS_SIGNTOOL") or shutil.which("signtool")
    if not sign_tool:
        raise RuntimeError("Windows release signing needs signtool.exe on PATH or VN_WINDOWS_SIGNTOOL.")
    return certificate_path, password, sign_tool


def _sign_windows_executable(executable: Path) -> None:
    certificate_path, password, sign_tool = _windows_signing_settings()
    command = [
        sign_tool, "sign", "/fd", "SHA256", "/f", str(certificate_path),
        "/tr", os.environ.get("VN_WINDOWS_TIMESTAMP_URL", "http://timestamp.digicert.com"),
        "/td", "SHA256",
    ]
    if password:
        command.extend(["/p", password])
    command.append(str(executable))
    subprocess.run(command, check=True, timeout=180, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _macos_signing_environment() -> tuple[str, tuple[str, str, str] | None]:
    identity = os.environ.get("VN_MACOS_SIGN_IDENTITY", "").strip()
    if not identity:
        raise ValueError("macOS release signing needs VN_MACOS_SIGN_IDENTITY.")
    names = ("VN_MACOS_NOTARY_APPLE_ID", "VN_MACOS_NOTARY_TEAM_ID", "VN_MACOS_NOTARY_PASSWORD")
    values = tuple(os.environ.get(name, "").strip() for name in names)
    if any(values) and not all(values):
        missing = [name for name, value in zip(names, values) if not value]
        raise ValueError("macOS notarization needs these environment variables: " + ", ".join(missing))
    return identity, values if all(values) else None


def _extract_export_zip(archive_path: Path, destination: Path) -> None:
    root = destination.resolve()
    with ZipFile(archive_path, "r") as archive:
        for info in archive.infolist():
            relative = _validate_zip_name(info.filename)
            path = root.joinpath(*relative.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                target = archive.read(info).decode("utf-8")
                if Path(target).is_absolute() or not _is_within((path.parent / target).resolve(), root):
                    raise ValueError(f"Export contains an unsafe symbolic link: {info.filename!r}.")
                path.symlink_to(target)
            elif info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                with archive.open(info, "r") as source, path.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if mode:
                    path.chmod(mode & 0o777)


def _write_export_zip(root: Path, archive_path: Path) -> None:
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
            relative = path.relative_to(root).as_posix()
            info_name = relative + ("/" if path.is_dir() and not path.is_symlink() else "")
            info = ZipInfo(info_name)
            info.create_system = 3
            mode = path.lstat().st_mode
            if path.is_symlink():
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                content = os.readlink(path).encode("utf-8")
            elif path.is_dir():
                info.external_attr = (stat.S_IFDIR | (stat.S_IMODE(mode) or 0o755)) << 16
                content = b""
            else:
                info.external_attr = (stat.S_IFREG | stat.S_IMODE(mode)) << 16
                content = path.read_bytes()
            archive.writestr(info, content)


def _sign_macos_export(output_file: Path, app_name: str) -> None:
    identity, notarization = _macos_signing_environment()
    codesign = shutil.which("codesign")
    if not codesign:
        raise RuntimeError("macOS release signing needs codesign from Xcode Command Line Tools.")
    with tempfile.TemporaryDirectory(prefix=".vn_macos_sign_", dir=output_file.parent) as temporary:
        workspace = Path(temporary)
        contents = workspace / "contents"
        contents.mkdir()
        _extract_export_zip(output_file, contents)
        app = contents / f"{app_name}.app"
        if not app.is_dir():
            raise FileNotFoundError(f"macOS export is missing its app bundle: {app}")
        subprocess.run(
            [codesign, "--force", "--deep", "--options", "runtime", "--timestamp", "--sign", identity, str(app)],
            check=True, timeout=600, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        subprocess.run(
            [codesign, "--verify", "--deep", "--strict", "--verbose=2", str(app)],
            check=True, timeout=180, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if notarization is not None:
            ditto = shutil.which("ditto")
            xcrun = shutil.which("xcrun")
            if not ditto or not xcrun:
                raise RuntimeError("macOS notarization needs ditto and xcrun from Xcode Command Line Tools.")
            notarization_zip = workspace / "notarization.zip"
            subprocess.run(
                [ditto, "-c", "-k", "--keepParent", str(app), str(notarization_zip)],
                check=True, timeout=600, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            apple_id, team_id, password = notarization
            subprocess.run(
                [
                    xcrun, "notarytool", "submit", str(notarization_zip), "--wait",
                    "--apple-id", apple_id, "--team-id", team_id, "--password", password,
                ],
                check=True, timeout=3600, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            subprocess.run(
                [xcrun, "stapler", "staple", str(app)],
                check=True, timeout=600, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        signed_zip = workspace / "signed-export.zip"
        _write_export_zip(contents, signed_zip)
        os.replace(signed_zip, output_file)


def _local_android_runtime_sources() -> tuple[bytes, bytes, bytes] | None:
    roots = (Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent)
    for root in roots:
        paths = (root / "web_main.py", root / "engine" / "engine.py", root / "engine" / "platform_runtime.py")
        if all(path.is_file() for path in paths):
            return tuple(path.read_bytes() for path in paths)
    return None


def export_android_project(
    project_root: Path,
    project_file: Path,
    templates_dir: Path,
    output_file: Path,
    release_tag: str | None = None,
    sign_release: bool = False,
) -> Path:
    """Build a Capacitor APK from a new project-specific archive and web template."""
    project_root = Path(project_root).resolve()
    project_file = Path(project_file).resolve()
    templates_dir = Path(templates_dir).resolve()
    output_file = Path(output_file).expanduser().resolve().with_suffix(".apk")

    project_values = json.loads(project_file.read_text(encoding="utf-8"))
    if not isinstance(project_values, dict):
        raise ValueError("Project configuration must be a JSON object.")
    app_name, app_id, orientation = _android_export_settings(project_values)
    if sign_release:
        _android_signing_environment()
    window = project_values.get("window", {})
    if not isinstance(window, dict):
        raise ValueError("Project configuration 'window' must be an object.")
    window_size = (window.get("width", 1920), window.get("height", 1200))
    project_icon = _prepare_project_export(project_root, project_file)[-1]
    _android_tool("node")
    npm = _android_tool("npm")
    npx = _android_tool("npx")
    java = shutil.which("java")
    if java is None:
        java_home = os.environ.get("JAVA_HOME")
        java_name = "java.exe" if sys.platform == "win32" else "java"
        if java_home and (Path(java_home) / "bin" / java_name).is_file():
            java = str(Path(java_home) / "bin" / java_name)
    if java is None:
        raise RuntimeError("Android export requires a Java JDK on PATH or configured with JAVA_HOME.")
    sdk_directory = _android_sdk_directory()
    local_template = templates_dir / "template-web.zip"
    local_sources = _local_android_runtime_sources()
    if release_tag is None and local_template.is_file() and local_sources is not None:
        template_file = local_template
        android_sources = local_sources
    else:
        release_tag = release_tag or latest_template_release_tag()
        template_file = _resolve_template_file(templates_dir, "web", release_tag)
        android_sources = fetch_android_sources(release_tag)
    if output_file == template_file.resolve():
        raise ValueError("The Android APK cannot overwrite the web export template.")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".vn_android_export_", dir=output_file.parent) as temporary:
        workspace = Path(temporary)
        wrapper = workspace / "capacitor-wrapper"
        web_directory = wrapper / "www"
        web_directory.mkdir(parents=True)
        web_archive = workspace / "web-export.zip"
        export_web_project(project_root, project_file, template_file.parent, web_archive)
        _extract_web_site(web_archive, web_directory)
        _prepare_android_web_site(web_directory, window_size, android_sources)

        _run_android_command([npm, "init", "-y"], wrapper)
        _run_android_command(
            [
                npm, "install",
                "@capacitor/core@^8.6.2",
                "@capacitor/cli@^8.6.2",
                "@capacitor/android@^8.6.2",
                "@capacitor/status-bar@^8.0.4",
                "esbuild",
            ],
            wrapper,
        )
        (wrapper / "capacitor.config.json").write_text(
            json.dumps(
                {"appId": app_id, "appName": app_name, "webDir": "www"},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        _run_android_command([npx, "cap", "add", "android"], wrapper)
        _enable_android_fullscreen(wrapper / "android")
        _add_status_bar_hide_script(web_directory, wrapper, npx)
        _set_android_orientation(
            wrapper / "android" / "app" / "src" / "main" / "AndroidManifest.xml",
            orientation,
        )
        app_gradle = wrapper / "android" / "app" / "build.gradle"
        if sign_release:
            _configure_android_release_signing(app_gradle)
        (wrapper / "android" / "local.properties").write_text(
            f"sdk.dir={sdk_directory.as_posix()}\n",
            encoding="utf-8",
        )

        from engine.icon_utils import install_android_launcher_icons

        engine_icon = workspace / "engine-logo.png"
        with _open_template_archive(template_file) as template:
            try:
                engine_icon.write_bytes(template.read("logo.png"))
            except KeyError as error:
                raise ValueError("The Web runtime template does not contain its default logo.png icon.") from error
        install_android_launcher_icons(
            project_icon or engine_icon,
            wrapper / "android" / "app" / "src" / "main" / "res",
        )

        _run_android_command([npx, "cap", "sync", "android"], wrapper)
        gradle_name = "gradlew.bat" if sys.platform == "win32" else "gradlew"
        gradle_wrapper = wrapper / "android" / gradle_name
        build_variant = "release" if sign_release else "debug"
        _run_android_command([str(gradle_wrapper), f"assemble{build_variant.title()}"], gradle_wrapper.parent)
        built_apk = (
            wrapper / "android" / "app" / "build" / "outputs" / "apk"
            / build_variant / f"app-{build_variant}.apk"
        )
        if not built_apk.is_file():
            raise FileNotFoundError(f"Android build completed without producing the expected APK: {built_apk}")
        temporary_apk = workspace / output_file.name
        shutil.copy2(built_apk, temporary_apk)
        os.replace(temporary_apk, output_file)
    return output_file


def export_project(
    project_root: Path,
    project_file: Path,
    templates_dir: Path,
    platform: str,
    output_file: Path,
    android_release_tag: str | None = None,
    sign_release: bool = False,
) -> Path:
    """Create a standalone desktop/web ZIP or Android APK for the project."""
    if platform not in PLATFORMS:
        raise ValueError(f"Platform must be one of: {', '.join(sorted(PLATFORMS))}.")

    if sign_release and platform not in {"windows", "macos", "android"}:
        raise ValueError("Release signing is supported for Windows, macOS, and Android exports.")
    if sign_release and platform == "windows":
        _windows_signing_settings()
    elif sign_release and platform == "macos":
        _macos_signing_environment()

    if platform == "web":
        return export_web_project(project_root, project_file, templates_dir, output_file)
    if platform == "android":
        return export_android_project(
            project_root,
            project_file,
            templates_dir,
            output_file,
            android_release_tag,
            sign_release,
        )

    project_root = Path(project_root).resolve()
    project_file = Path(project_file).resolve()
    templates_dir = Path(templates_dir).resolve()
    output_file = Path(output_file).expanduser().resolve()
    template_file = _resolve_template_file(templates_dir, platform)
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
    icon_path = _project_icon_path(assets_root, project_values)

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
        if platform == "windows" and icon_path is not None and sys.platform != "win32":
            raise RuntimeError("Export a Windows game with a custom icon from Windows so its executable icon can be updated.")
        windows_icon = make_ico(icon_path) if platform == "windows" and icon_path is not None else None
        macos_icon = make_icns(icon_path) if platform == "macos" and icon_path is not None else None
        macos_icon_path = f"{name}.app/Contents/Resources/AppIcon.icns"
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
                if windows_icon is not None:
                    update_windows_executable_icon(staged_executable, windows_icon)
                with staged_executable.open("ab") as target, bundle_path.open("rb") as bundle:
                    shutil.copyfileobj(bundle, target)
                if platform == "windows" and sign_release:
                    _sign_windows_executable(staged_executable)
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
                        with staged_executable.open("rb") as source, archive.open(info, "w") as target:
                            shutil.copyfileobj(source, target)
                    else:
                        content = b"" if item.is_dir() else template.read(item)
                        if platform == "macos" and destination_name.endswith(".app/Contents/Info.plist"):
                            content = _rewrite_bundle_info(
                                content,
                                name,
                                "AppIcon.icns" if macos_icon is not None else None,
                            )
                        if destination_name == macos_icon_path and macos_icon is not None:
                            content = macos_icon
                        archive.writestr(info, content)

                if not found_main:
                    raise ValueError(f"Template is missing its main executable at {executable_path!r}.")

                if macos_icon is not None and macos_icon_path not in seen_names:
                    icon_info = ZipInfo(macos_icon_path)
                    icon_info.compress_type = ZIP_DEFLATED
                    archive.writestr(icon_info, macos_icon)
                    seen_names.add(macos_icon_path)

                shortcut_info = ZipInfo(shortcut_name)
                shortcut_info.compress_type = ZIP_DEFLATED
                if shortcut_is_symlink:
                    shortcut_info.create_system = 3
                    shortcut_info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(shortcut_info, shortcut_content)
                else:
                    archive.writestr(shortcut_info, (workspace / shortcut_name).read_bytes())

            os.replace(temporary_zip, output_file)
            if platform == "macos" and sign_release:
                _sign_macos_export(output_file, name)
        except BadZipFile as error:
            raise ValueError(f"Export template is not a valid ZIP file: {template_file}") from error
    return output_file
