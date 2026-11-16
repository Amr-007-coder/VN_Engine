"""Build the standalone VN_Editor executable for the current operating system."""

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from engine.icon_utils import make_icns

PROJECT_ROOT = Path(__file__).resolve().parent
EDITOR_SOURCE = PROJECT_ROOT / "editor.py"
BUILT_EDITOR_OUTPUT = PROJECT_ROOT / "dist" / "editor-build" / ("VN_Editor.exe" if sys.platform == "win32" else "VN_Editor")
EDITOR_OUTPUT = PROJECT_ROOT / "dist" / ("VN_Editor.exe" if sys.platform == "win32" else "VN_Editor")


def _current_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "dist" / "editor-build",
        help="Nuitka output folder (default: dist/editor-build)",
    )
    return parser.parse_args()


def _move_editor_to_dist() -> None:
    if not BUILT_EDITOR_OUTPUT.exists():
        raise FileNotFoundError(f"Built editor output was not found: {BUILT_EDITOR_OUTPUT}")
    EDITOR_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    os.replace(BUILT_EDITOR_OUTPUT, EDITOR_OUTPUT)


def main() -> int:
    args = _parse_args()
    platform = _current_platform()
    if not EDITOR_SOURCE.is_file():
        print(f"Could not find editor.py under {PROJECT_ROOT}.", file=sys.stderr)
        return 2
    try:
        if importlib.util.find_spec("nuitka") is None:
            print(
                "Nuitka is not installed for this Python interpreter. Install it with "
                f'"{sys.executable}" -m pip install nuitka, then run this script again.',
                file=sys.stderr,
            )
            return 2
    except (ImportError, ValueError):
        print("Could not check whether Nuitka is installed.", file=sys.stderr)
        return 2

    output_dir = args.output_dir.expanduser()
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    output_name = "VN_Editor.exe" if platform == "windows" else "VN_Editor"
    mode = "app" if platform == "macos" else "onefile"
    command = [
        sys.executable,
        "-m",
        "nuitka",
        f"--mode={mode}",
        "--assume-yes-for-downloads",
        "--enable-plugin=tk-inter",
        f"--output-dir={output_dir}",
        f"--output-filename={output_name}",
        "--jobs=4",
        "--include-package=yaml",
        "--include-package=pygbag",
        "--include-package-data=pygbag",
        "--include-module=export_pipeline",
        "--include-module=engine.validator",
        "--python-flag=no_docstrings",
    ]
    if platform == "windows":
        command.append("--windows-console-mode=disable")
        command.append(
            f"--windows-icon-from-ico={PROJECT_ROOT / 'engine' / 'assets' / 'images' / 'editor_logo.ico'}"
        )
    elif platform == "macos":
        command.append("--macos-app-name=VN_Editor")
    command.append("editor.py")

    if platform == "macos":
        with tempfile.TemporaryDirectory(prefix="vn_editor_icon_") as temporary:
            icon_path = Path(temporary) / "editor.icns"
            icon_path.write_bytes(
                make_icns(PROJECT_ROOT / "engine" / "assets" / "images" / "editor_logo.png")
            )
            command.insert(command.index("editor.py"), f"--macos-app-icon={icon_path}")
            result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    else:
        result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode:
        print(f"Nuitka failed with exit code {result.returncode}.", file=sys.stderr)
        return result.returncode

    if platform == "macos":
        expected_binary = "VN_Editor"
        app_bundles = [
            app_bundle
            for app_bundle in output_dir.rglob("*.app")
            if (app_bundle / "Contents" / "MacOS" / expected_binary).is_file()
        ]
        if len(app_bundles) != 1:
            print(
                "Nuitka reported success, but an app bundle containing "
                f"Contents/MacOS/{expected_binary} was not found exactly once under {output_dir}.",
                file=sys.stderr,
            )
            return 1
        expected = app_bundles[0]
    else:
        expected = output_dir / output_name
        if not expected.is_file():
            print(f"Nuitka reported success, but the expected editor was not created: {expected}", file=sys.stderr)
            return 1
    print(f"Standalone {platform} editor built: {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
