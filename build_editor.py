"""Build the standalone VN_Editor executable for the current operating system."""

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
EDITOR_SOURCE = PROJECT_ROOT / "editor.py"


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
        "--include-module=export_pipeline",
        "--python-flag=no_docstrings",
    ]
    if platform == "windows":
        command.append("--windows-console-mode=disable")
    elif platform == "macos":
        command.append("--macos-app-name=VN_Editor")
    command.append("editor.py")

    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode:
        print(f"Nuitka failed with exit code {result.returncode}.", file=sys.stderr)
        return result.returncode

    expected = output_dir / ("VN_Editor.app" if platform == "macos" else output_name)
    if not expected.exists():
        print(f"Nuitka reported success, but the expected editor was not created: {expected}", file=sys.stderr)
        return 1
    print(f"Standalone {platform} editor built: {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
