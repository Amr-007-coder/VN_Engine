"""Normalize a Nuitka standalone build as a platform export template ZIP."""

import argparse
import os
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import stat
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


PLATFORMS = {"windows", "linux", "macos"}


def _find_dist(build_root: Path) -> Path:
    candidates = [path for path in build_root.glob("*.dist") if path.is_dir()]
    if len(candidates) == 1:
        return candidates[0]
    for expected in ("Runner.exe", "Runner", "main.exe", "main"):
        matches = [path for path in build_root.rglob(expected) if path.is_file()]
        if len(matches) == 1:
            return matches[0].parent
    raise FileNotFoundError(f"Could not identify one Nuitka standalone folder under {build_root}.")


def _write_zip_entry(archive: ZipFile, path: Path, root: Path, platform: str):
    relative = path.relative_to(root).as_posix()
    info = ZipInfo(relative + ("/" if path.is_dir() else ""))
    info.compress_type = ZIP_DEFLATED
    if platform in {"linux", "macos"}:
        info.create_system = 3
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, os.readlink(path).encode("utf-8"))
            return
        permission = stat.S_IMODE(mode)
        if path.is_dir():
            info.external_attr = (stat.S_IFDIR | permission) << 16
            archive.writestr(info, b"")
            return
        is_main = path.name in {"Runner", "Runner.exe"}
        is_library = path.name.casefold().endswith((".so", ".dylib")) or ".so." in path.name.casefold()
        if is_main or is_library:
            permission |= 0o111
        info.external_attr = (stat.S_IFREG | permission) << 16
    if path.is_dir():
        archive.writestr(info, b"")
    else:
        with path.open("rb") as source:
            archive.writestr(info, source.read())


def _rewrite_app_name(app_path: Path):
    info_path = app_path / "Contents" / "Info.plist"
    if not info_path.is_file():
        return
    try:
        values = plistlib.loads(info_path.read_bytes())
    except Exception:
        return
    if not isinstance(values, dict):
        return
    values["CFBundleExecutable"] = "Runner"
    values["CFBundleName"] = "Runner"
    values["CFBundleDisplayName"] = "Runner"
    info_path.write_bytes(plistlib.dumps(values, fmt=plistlib.FMT_BINARY))


def package_template(platform: str, build_root: Path, output: Path):
    if platform not in PLATFORMS:
        raise ValueError(f"Platform must be one of {', '.join(sorted(PLATFORMS))}.")
    build_root = build_root.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="vn_template_") as temporary:
        staging = Path(temporary) / "template"
        if platform == "macos":
            apps = list(build_root.rglob("Runner.app"))
            if not apps:
                apps = list(build_root.rglob("*.app"))
            if len(apps) != 1:
                raise FileNotFoundError(f"Expected one Nuitka .app bundle under {build_root}.")
            app_root = staging / "Runner.app"
            app_root.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(apps[0], app_root, symlinks=True)
            executable = app_root / "Contents" / "MacOS" / "Runner"
            if not executable.is_file():
                binaries = [path for path in (app_root / "Contents" / "MacOS").iterdir() if path.is_file()]
                if len(binaries) != 1:
                    raise FileNotFoundError("Could not identify the macOS app's main executable.")
                binaries[0].rename(executable)
            executable.chmod(executable.stat().st_mode | 0o111)
            _rewrite_app_name(app_root)
        else:
            dist_root = _find_dist(build_root)
            runner_root = staging / "Runner"
            shutil.copytree(dist_root, runner_root, symlinks=True)
            if platform == "windows":
                candidates = [path for path in runner_root.glob("*.exe") if path.is_file()]
                expected = runner_root / "Runner.exe"
                if not expected.is_file():
                    if len(candidates) != 1:
                        raise FileNotFoundError("Could not identify the Windows engine executable in the Nuitka output.")
                    candidates[0].rename(expected)
            else:
                expected = runner_root / "Runner"
                if not expected.is_file():
                    candidates = [path for path in runner_root.iterdir() if path.is_file() and not path.suffix]
                    if not candidates:
                        candidates = [path for path in runner_root.iterdir() if path.is_file() and path.name.startswith("main")]
                    if len(candidates) != 1:
                        raise FileNotFoundError("Could not identify the Linux engine executable in the Nuitka output.")
                    candidates[0].rename(expected)
                expected.chmod(expected.stat().st_mode | 0o111)

        if output.exists():
            output.unlink()
        with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(staging.rglob("*"), key=lambda item: item.as_posix().casefold()):
                _write_zip_entry(archive, path, staging, platform)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    parser.add_argument("--build-dir", type=Path, default=Path("build"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package_template(args.platform, args.build_dir, args.output)
    print(f"Created {args.output}")


if __name__ == "__main__":
    main()
