"""Package the latest engine-only Nuitka build and its authoring documentation."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from engine.windows_shortcut import create_shortcut


PROJECT_ROOT = Path(__file__).resolve().parent
DIST_ROOT = PROJECT_ROOT / "dist"
VERSION_FILE = PROJECT_ROOT / "engine" / "data" / "version.txt"
DOCUMENTS = (
    (PROJECT_ROOT / "docs" / "README.md", "readme.md"),
    (PROJECT_ROOT / "docs" / "guide_vn-engine.md", "guide_vn-engine.md"),
    (PROJECT_ROOT / "docs" / "project-config.md", "project-config.md"),
    (PROJECT_ROOT / "docs" / "story-format.md", "story-format.md"),
)
EDITOR_EXECUTABLE = DIST_ROOT / "editor-build" / "VN_Editor.exe"
EXPORT_TEMPLATE_DIRS = (PROJECT_ROOT / "templates", PROJECT_ROOT / "engine" / "templates")
VERSION_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]*")


def _read_version() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Invalid version in {VERSION_FILE}: {version!r}")
    return version


def _latest_engine_distribution() -> Path:
    candidates = []
    for build_dir in DIST_ROOT.glob("build-*"):
        distribution = build_dir / "main.dist"
        executable = distribution / "engine.exe"
        if build_dir.is_dir() and executable.is_file():
            candidates.append((executable.stat().st_mtime_ns, build_dir.name, distribution))
    if not candidates:
        raise FileNotFoundError(
            f"No engine-only build was found under {DIST_ROOT}. "
            "Build one first with 'python compile.py --engine-only'."
        )
    return max(candidates)[2]


def _create_shortcuts(package_root: Path) -> None:
    executables = sorted(path for path in package_root.rglob("*.exe") if path.is_file())
    if not executables:
        raise FileNotFoundError(f"No executable was found under {package_root}.")
    for executable in executables:
        executable_folder = executable.parent
        parent_folder = executable_folder.parent
        if parent_folder == executable_folder:
            continue
        shortcut_path = parent_folder / f"{executable.name}.lnk"
        create_shortcut(executable, shortcut_path, executable_folder)


def _copy_documentation(package_root: Path) -> None:
    for source, destination_name in DOCUMENTS:
        if not source.is_file():
            raise FileNotFoundError(f"Required package documentation is missing: {source}")
        shutil.copy2(source, package_root / destination_name)


def _copy_editor(package_root: Path) -> None:
    if not EDITOR_EXECUTABLE.is_file():
        raise FileNotFoundError(
            f"The standalone VN Engine editor is missing: {EDITOR_EXECUTABLE}. "
            "Build it first with 'python build_editor.py'."
        )
    shutil.copy2(EDITOR_EXECUTABLE, package_root / "VN_Editor.exe")


def _copy_export_templates(package_root: Path) -> None:
    available = {}
    missing = []
    for platform in ("windows", "linux", "macos"):
        filename = f"template-{platform}.zip"
        source = next(
            (directory / filename for directory in EXPORT_TEMPLATE_DIRS if (directory / filename).is_file()),
            None,
        )
        if source is None:
            missing.append(filename)
        else:
            available[filename] = source
    if missing:
        raise FileNotFoundError(
            "Required cross-platform game templates are missing: " + ", ".join(missing)
        )
    destination = package_root / "templates"
    destination.mkdir(parents=True, exist_ok=True)
    for filename, source in available.items():
        shutil.copy2(source, destination / filename)


def _create_example_project(package_root: Path) -> None:
    (package_root / "assets").mkdir()
    data_dir = package_root / "data"
    data_dir.mkdir()
    (data_dir / "story.yaml").write_text(
        "title: My Visual Novel\n"
        "start: opening\n"
        "dialogues:\n"
        "  opening:\n"
        "    chapter: Chapter 1\n"
        "    speaker: Narrator\n"
        "    active_character: null\n"
        "    text: Replace this line with your opening dialogue.\n",
        encoding="utf-8",
        newline="\n",
    )
    project_config = {
        "name": "My Visual Novel",
        "story": "story.yaml",
        "icon": None,
        "save_slots": 5,
        "paths": {"data": "data", "assets": "assets", "user_data": "user_data"},
    }
    (data_dir / "project.json").write_text(
        json.dumps(project_config, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_archive(package_root: Path, archive_path: Path) -> None:
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{archive_path.stem}_",
        suffix=".tmp",
        dir=DIST_ROOT,
        delete=False,
    )
    temporary_archive = Path(handle.name)
    handle.close()
    try:
        with ZipFile(temporary_archive, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(package_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(package_root).as_posix())
                elif path.is_dir() and not any(path.iterdir()):
                    directory_name = path.relative_to(package_root).as_posix().rstrip("/") + "/"
                    directory_info = ZipInfo(directory_name)
                    directory_info.external_attr = (0o40775 << 16) | 0x10
                    archive.writestr(directory_info, b"")
        os.replace(temporary_archive, archive_path)
    finally:
        if temporary_archive.exists():
            temporary_archive.unlink()


def create_package() -> Path:
    if sys.platform != "win32":
        raise OSError("Packaging requires Windows because it creates Windows .lnk shortcuts.")
    if not DIST_ROOT.is_dir():
        raise FileNotFoundError(f"Build output folder does not exist: {DIST_ROOT}")

    version = _read_version()
    source_distribution = _latest_engine_distribution()
    archive_path = DIST_ROOT / f"VN_Engine_v{version}.zip"

    with tempfile.TemporaryDirectory(prefix="VN_Engine_package_", dir=DIST_ROOT) as temporary:
        temporary_root = Path(temporary)
        package_root = temporary_root / "package"
        package_root.mkdir()

        shutil.copytree(source_distribution, package_root / "VN_Engine")
        _create_example_project(package_root)
        _create_shortcuts(package_root)
        _copy_documentation(package_root)
        _copy_editor(package_root)
        _copy_export_templates(package_root)
        _write_archive(package_root, archive_path)

    return archive_path


def main() -> int:
    try:
        archive_path = create_package()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Packaging failed: {error}", file=sys.stderr)
        return 1
    print(f"Package created: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
