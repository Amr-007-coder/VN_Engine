"""Build the self-contained Windows editor executable with Nuitka.

This is a maintainer build step. People using a released package only run
editor.exe; they do not need Python or Nuitka installed.
"""

import importlib.util
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
EDITOR_SOURCE = PROJECT_ROOT / "editor.py"
BUILT_EDITOR_OUTPUT = PROJECT_ROOT / "editor.exe"
EDITOR_OUTPUT = PROJECT_ROOT / "dist" / "editor.exe"


def _move_editor_to_dist() -> None:
    EDITOR_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    BUILT_EDITOR_OUTPUT.replace(EDITOR_OUTPUT)


def main() -> int:
    if sys.platform != "win32":
        print("The editor executable is a Windows application and must be built on Windows.", file=sys.stderr)
        return 2
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

    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--mode=onefile",
        "--assume-yes-for-downloads",
        "--windows-console-mode=disable",
        "--enable-plugin=tk-inter",
        f"--output-dir={PROJECT_ROOT}",
        "--output-filename=editor.exe",
        "--jobs=4",
        "--include-package=yaml",
        "--include-module=export_pipeline",
        "--python-flag=no_docstrings",
        "editor.py",
    ]
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode:
        print(f"Nuitka failed with exit code {result.returncode}.", file=sys.stderr)
        return result.returncode
    if not BUILT_EDITOR_OUTPUT.is_file():
        print(f"Nuitka reported success, but {BUILT_EDITOR_OUTPUT} was not created.", file=sys.stderr)
        return 1
    try:
        _move_editor_to_dist()
    except OSError as error:
        print(f"Could not move the editor executable to {EDITOR_OUTPUT}: {error}", file=sys.stderr)
        return 1
    print(f"Standalone editor built: {EDITOR_OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
