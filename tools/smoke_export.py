"""Validate generated platform exports and launch desktop packages headlessly."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
from zipfile import BadZipFile, ZipFile


def _safe_extract(archive: ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for item in archive.infolist():
        relative = PurePosixPath(item.filename.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"Export contains an unsafe path: {item.filename!r}.")
        path = root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = item.external_attr >> 16
        if stat.S_ISLNK(mode):
            target = archive.read(item).decode("utf-8")
            if Path(target).is_absolute() or not (path.parent / target).resolve().is_relative_to(root):
                raise ValueError(f"Export contains an unsafe symbolic link: {item.filename!r}.")
            path.symlink_to(target)
        elif item.is_dir():
            path.mkdir(parents=True, exist_ok=True)
        else:
            with archive.open(item) as source, path.open("wb") as output:
                shutil.copyfileobj(source, output)
            if mode:
                path.chmod(mode & 0o777)


def smoke_desktop(platform: str, artifact: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="vn-export-smoke-") as temporary:
        root = Path(temporary)
        try:
            with ZipFile(artifact) as archive:
                bad_file = archive.testzip()
                if bad_file:
                    raise ValueError(f"Desktop export contains a corrupt file: {bad_file}")
                _safe_extract(archive, root)
        except BadZipFile as error:
            raise ValueError(f"Desktop export is not a valid ZIP: {artifact}") from error

        game_name = artifact.stem.removesuffix(f"-{platform}")
        if platform == "windows":
            executable = root / game_name / f"{game_name}.exe"
        elif platform == "linux":
            executable = root / game_name / game_name
        else:
            executable = root / f"{game_name}.app" / "Contents" / "MacOS" / "Runner"
        if not executable.is_file():
            raise FileNotFoundError(f"Export is missing its expected executable: {executable}")
        environment = os.environ.copy()
        environment.setdefault("SDL_VIDEODRIVER", "dummy")
        environment.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        result = subprocess.run(
            [str(executable), "--validate"],
            cwd=executable.parent,
            env=environment,
            timeout=90,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                f"Exported {platform} game failed its launch/validation smoke check "
                f"(exit {result.returncode}):\n{result.stdout[-5000:]}"
            )
        print(f"Desktop launch passed: {executable}")


def smoke_web(artifact: Path) -> None:
    try:
        with ZipFile(artifact) as archive:
            bad_file = archive.testzip()
            if bad_file:
                raise ValueError(f"Web export contains a corrupt file: {bad_file}")
            names = {item.filename for item in archive.infolist()}
            apps = [name for name in names if name.casefold().endswith(".apk")]
            if "index.html" not in names or len(apps) != 1:
                raise ValueError("Web export must contain index.html and one Pygbag app archive.")
            from io import BytesIO

            with ZipFile(BytesIO(archive.read(apps[0]))) as app:
                bad_app_file = app.testzip()
                if bad_app_file:
                    raise ValueError(f"Pygbag app archive contains a corrupt file: {bad_app_file}")
                app_names = set(app.namelist())
                if "assets/data/project.json" not in app_names:
                    raise ValueError("Pygbag app archive is missing the embedded project configuration.")
                project = json.loads(app.read("assets/data/project.json"))
                story = project.get("story", "story.yaml")
                if f"assets/data/{story}" not in app_names:
                    raise ValueError("Pygbag app archive is missing the configured story file.")
    except BadZipFile as error:
        raise ValueError(f"Web export is not a valid nested ZIP package: {artifact}") from error
    print(f"Web package passed: {artifact}")


def smoke_android(artifact: Path, app_id: str | None) -> None:
    try:
        with ZipFile(artifact) as archive:
            bad_file = archive.testzip()
            if bad_file:
                raise ValueError(f"Android package contains a corrupt file: {bad_file}")
            names = set(archive.namelist())
            required = {"AndroidManifest.xml", "classes.dex"}
            missing = required - names
            if missing:
                raise ValueError("Android APK is missing: " + ", ".join(sorted(missing)))
    except BadZipFile as error:
        raise ValueError(f"Android export is not a valid APK: {artifact}") from error
    apksigner = shutil.which("apksigner")
    if apksigner is None:
        sdk_root = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        if sdk_root:
            candidates = sorted((Path(sdk_root) / "build-tools").glob("*/apksigner*"), reverse=True)
            apksigner = str(candidates[0]) if candidates else None
    if apksigner:
        subprocess.run([apksigner, "verify", "--verbose", str(artifact)], check=True, timeout=60)
    print(f"Android package passed: {artifact}")

    serial = os.environ.get("ANDROID_SERIAL")
    if not serial:
        return
    adb = shutil.which("adb")
    if not adb:
        raise RuntimeError("ANDROID_SERIAL is set but adb is not available.")
    if not app_id:
        raise ValueError("Pass --app-id to install and launch the Android package.")
    subprocess.run([adb, "-s", serial, "install", "-r", str(artifact)], check=True, timeout=180)
    subprocess.run([adb, "-s", serial, "shell", "monkey", "-p", app_id, "1"], check=True, timeout=60)
    result = subprocess.run(
        [adb, "-s", serial, "shell", "pidof", app_id],
        check=True,
        timeout=30,
        stdout=subprocess.PIPE,
        text=True,
    )
    if not result.stdout.strip():
        raise RuntimeError(f"Android app {app_id!r} did not remain running after launch.")
    print(f"Android install and launch passed: {app_id}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("windows", "linux", "macos", "web", "android"), required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--app-id", help="Android package ID for optional adb install/launch")
    args = parser.parse_args(argv)
    try:
        if not args.artifact.is_file():
            raise FileNotFoundError(f"Export artifact not found: {args.artifact}")
        if args.platform in {"windows", "linux", "macos"}:
            smoke_desktop(args.platform, args.artifact)
        elif args.platform == "web":
            smoke_web(args.artifact)
        else:
            smoke_android(args.artifact, args.app_id)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Export smoke failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
