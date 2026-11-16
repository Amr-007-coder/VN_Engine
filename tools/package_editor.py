"""Package a platform-native VN_Editor build."""

import argparse
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


PLATFORMS = {"windows", "linux", "macos"}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    (Path("docs/guide_vn-engine.md"), "docs/guide_vn-engine.md"),
    (Path("docs/project-config.md"), "docs/project-config.md"),
    (Path("docs/story-format.md"), "docs/story-format.md"),
)


def _find_editor_build(platform: str, build_root: Path) -> Path:
    if platform == "macos":
        direct = build_root / "VN_Editor.app"
        if direct.is_dir():
            return direct
        matches = [
            app_bundle
            for app_bundle in build_root.rglob("*.app")
            if (app_bundle / "Contents" / "MacOS" / "VN_Editor").is_file()
        ]
        if len(matches) != 1:
            raise FileNotFoundError(
                f"Expected one macOS app bundle containing Contents/MacOS/VN_Editor under {build_root}."
            )
        return matches[0]

    expected = {
        "windows": "VN_Editor.exe",
        "linux": "VN_Editor",
    }[platform]
    direct = build_root / expected
    if direct.exists():
        return direct
    matches = list(build_root.rglob(expected))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one {expected} editor build under {build_root}.")
    return matches[0]


def _copy_docs(root: Path) -> None:
    readme = Path("docs/README.md")
    if readme.is_file():
        shutil.copy2(readme, root / "readme.md")
    for source, destination in DOCUMENTS:
        if not source.is_file():
            raise FileNotFoundError(f"Required editor documentation is missing: {source}")
        target = root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _write_editor_version(root: Path) -> None:
    version_file = PROJECT_ROOT / "engine" / "data" / "version.txt"
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"Could not read the editor version from {version_file}: {error}") from error
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise ValueError(f"Invalid editor version in {version_file}: {version!r}")
    (root / "engine-version.txt").write_text(f"{version}\n", encoding="utf-8", newline="\n")


def _main_executable_path(platform: str) -> str:
    if platform == "windows":
        return "VN_Editor.exe"
    if platform == "linux":
        return "VN_Editor"
    return "VN_Editor.app/Contents/MacOS/VN_Editor"


def _write_zip_entry(archive: ZipFile, path: Path, root: Path, platform: str) -> None:
    relative = path.relative_to(root).as_posix()
    file_mode = path.lstat().st_mode
    is_symlink = stat.S_ISLNK(file_mode)
    is_directory = stat.S_ISDIR(file_mode)
    info = ZipInfo(relative + ("/" if is_directory else ""))
    info.compress_type = ZIP_DEFLATED
    if platform in {"linux", "macos"}:
        info.create_system = 3
        if is_symlink:
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, os.readlink(path).encode("utf-8"))
            return
        permission = stat.S_IMODE(file_mode)
        if is_directory:
            info.external_attr = (stat.S_IFDIR | permission) << 16
            archive.writestr(info, b"")
            return
        is_main = relative == _main_executable_path(platform)
        filename = PurePosixPath(relative).name.casefold()
        is_shared_library = filename.endswith((".so", ".dylib")) or ".so." in filename
        if is_main or is_shared_library:
            permission |= 0o111
        info.external_attr = (stat.S_IFREG | permission) << 16
    if is_directory:
        archive.writestr(info, b"")
        return
    with path.open("rb") as source:
        archive.writestr(info, source.read())


def package_editor(
    platform: str,
    build_root: Path,
    output: Path,
) -> Path:
    if platform not in PLATFORMS:
        raise ValueError(f"Platform must be one of: {', '.join(sorted(PLATFORMS))}.")
    build_root = build_root.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    editor_build = _find_editor_build(platform, build_root)

    with tempfile.TemporaryDirectory(prefix=f"vn_editor_{platform}_") as temporary:
        staging = Path(temporary) / "VN_Editor_Package"
        staging.mkdir()
        if platform == "macos":
            shutil.copytree(editor_build, staging / "VN_Editor.app", symlinks=True)
        else:
            shutil.copy2(editor_build, staging / editor_build.name)
        _write_editor_version(staging)
        _copy_docs(staging)

        temporary_output = output.with_name(f".{output.name}.tmp")
        try:
            with ZipFile(temporary_output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
                for path in sorted(staging.rglob("*"), key=lambda item: item.as_posix().casefold()):
                    _write_zip_entry(archive, path, staging, platform)
            os.replace(temporary_output, output)
        finally:
            temporary_output.unlink(missing_ok=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    parser.add_argument("--build-dir", type=Path, default=Path("dist/editor-build"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = package_editor(
        args.platform,
        args.build_dir,
        args.output,
    )
    print(f"Created {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
