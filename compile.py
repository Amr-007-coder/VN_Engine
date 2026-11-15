"""Build a native desktop distribution with embedded engine or project resources.

Run with ``python compile.py`` to build the current project, or
``python compile.py --engine-only`` to build an engine that reads project
assets and data beside its executable. The source resources are read-only
inputs; generated Python payload modules live in temporary staging and are
removed when Nuitka finishes.

Nuitka compiles the Python modules to native code and removes the loose Python
sources from the distribution. This makes casual inspection harder, but it is
not cryptographic protection against reverse engineering.
"""

import argparse
import base64
from datetime import datetime
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zlib


PROJECT_ROOT = Path(__file__).resolve().parent
RESOURCE_ROOTS = (
    ("assets", PROJECT_ROOT / "assets"),
    ("data", PROJECT_ROOT / "data"),
    ("engine/assets", PROJECT_ROOT / "engine" / "assets"),
    ("engine/data", PROJECT_ROOT / "engine" / "data"),
)
ENGINE_RESOURCE_ROOTS = RESOURCE_ROOTS[2:]
WINDOWS_BUILD = sys.platform == "win32"
EXECUTABLE_SUFFIX = ".exe" if WINDOWS_BUILD else ""
OUTPUT_NAME = f"VisualNovel{EXECUTABLE_SUFFIX}"
ENGINE_OUTPUT_NAME = f"engine{EXECUTABLE_SUFFIX}"
CHUNK_SIZE = 8 * 1024


def _resource_files(engine_only: bool = False, project_dir: Path = PROJECT_ROOT):
    project_resource_roots = (
        ("assets", project_dir / "assets"),
        ("data", project_dir / "data"),
    )
    roots = ENGINE_RESOURCE_ROOTS if engine_only else project_resource_roots + ENGINE_RESOURCE_ROOTS
    for namespace, root in roots:
        if not root.is_dir():
            raise FileNotFoundError(f"Required project resource directory is missing: {root}")
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root).as_posix()
            yield f"{namespace}/{relative}", path


def _payload_module_source(data: bytes) -> str:
    compressed = zlib.compress(data, level=9)
    use_compression = len(compressed) < len(data)
    encoded = base64.b85encode(compressed if use_compression else data)
    parts = [encoded[offset : offset + CHUNK_SIZE] for offset in range(0, len(encoded), CHUNK_SIZE)]

    # Keep each generated C string modest in size. b''.join prevents Python
    # from folding the chunks into one very large constant at compile time.
    part_lines = "\n".join(f"        {part!r}," for part in parts)
    joined = "b''.join((\n" + part_lines + "\n    ))"
    lines = ["from base64 import b85decode as _b85decode"]
    if use_compression:
        lines.append("from zlib import decompress as _decompress")
    lines.append(f"_encoded = _b85decode({joined})")
    if use_compression:
        lines.append("DATA = _decompress(_encoded)")
    else:
        lines.append("DATA = _encoded")
    lines.append("del _encoded, _b85decode")
    if use_compression:
        lines.append("del _decompress")
    return "\n".join(lines) + "\n"


def _self_check_payload_generator() -> None:
    """Catch encoding/code-generation regressions before processing the assets."""
    payloads = (b"", b"small one-chunk payload", b"A" * 10_000, os.urandom(CHUNK_SIZE))
    for index, original in enumerate(payloads):
        namespace = {}
        source = _payload_module_source(original)
        exec(compile(source, f"<embedded-payload-check-{index}>", "exec"), namespace)
        if namespace.get("DATA") != original:
            raise RuntimeError(f"Generated payload module {index} did not round-trip exactly.")


def _generate_payload(
    stage_root: Path,
    engine_only: bool = False,
    project_dir: Path = PROJECT_ROOT,
) -> tuple[int, int, int]:
    payload_dir = stage_root / "engine" / "_embedded_payload"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "__init__.py").write_text(
        "\"\"\"Generated resource-module index.\"\"\"\n"
        "RESOURCE_MODULES = {\n",
        encoding="utf-8",
    )

    resources = []
    raw_total = 0
    generated_total = 0
    for key, source_path in _resource_files(engine_only, project_dir):
        data = source_path.read_bytes()
        module_name = "r_" + hashlib.sha256(key.encode("utf-8")).hexdigest()
        module_source = _payload_module_source(data)
        module_path = payload_dir / f"{module_name}.py"
        module_path.write_text(module_source, encoding="ascii", newline="\n")
        generated_total += module_path.stat().st_size
        raw_total += len(data)
        resources.append((key, module_name))
        del data

    index_path = payload_dir / "__init__.py"
    with index_path.open("a", encoding="utf-8", newline="\n") as index_file:
        for key, module_name in resources:
            index_file.write(f"    {key!r}: {module_name!r},\n")
        index_file.write("}\n")
    generated_total += index_path.stat().st_size
    return len(resources), raw_total, generated_total


def _stage_sources(stage_root: Path) -> None:
    main_source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    # These old directives copy loose asset folders. The staged build embeds
    # them as Python constants instead, so omit the directives in this copy.
    main_lines = [
        line
        for line in main_source.splitlines()
        if not line.lstrip().startswith("# nuitka-project:")
    ]
    (stage_root / "main.py").write_text(
        "\n".join(main_lines) + "\n", encoding="utf-8", newline="\n"
    )
    shutil.copy2(PROJECT_ROOT / "export_pipeline.py", stage_root / "export_pipeline.py")

    engine_source = PROJECT_ROOT / "engine"
    engine_stage = stage_root / "engine"
    engine_stage.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(engine_source.rglob("*")):
        if not source_path.is_file():
            continue
        relative = source_path.relative_to(engine_source)
        if relative.parts[0] in {"assets", "data"}:
            continue
        if "__pycache__" in relative.parts or source_path.suffix.casefold() in {".pyc", ".pyo"}:
            continue
        target = engine_stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)

    # Make the generated payload a regular package, including in projects
    # where engine/ is normally an implicit namespace package.
    init_file = engine_stage / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""Visual novel engine package."""\n', encoding="utf-8")


def _preflight_staged_project(stage_root: Path, engine_only: bool = False) -> int:
    if engine_only:
        runtime_smoke = r'''from pathlib import Path
import pygame
from engine.assets import AssetManager
from engine.config import load_assets
from engine.engine import _read_engine_version

pygame.init()
try:
    assets = AssetManager(Path("missing-project-assets"))
    load_assets(assets)
    if not _read_engine_version():
        raise RuntimeError("The embedded engine version is empty.")
    if pygame.mixer.get_init():
        assets.load_sound("click_button.wav")
    print("Staged engine-only startup and embedded asset smoke check passed.")
finally:
    pygame.quit()
'''
    else:
        validation = subprocess.run(
            [sys.executable, "main.py", "--validate"],
            cwd=stage_root,
            check=False,
        )
        if validation.returncode != 0:
            print("The staged story validation failed; Nuitka was not started.", file=sys.stderr)
            return validation.returncode

        runtime_smoke = r'''from pathlib import PurePosixPath
import pygame
from engine.embedded import resources_under
from engine.engine import Engine, _read_engine_version

engine = Engine()
try:
    engine._initialize()
    if not _read_engine_version():
        raise RuntimeError("The embedded engine version is empty.")
    if pygame.mixer.get_init():
        sound_key = next((key for key in resources_under("assets/sounds")
                          if PurePosixPath(key).suffix.casefold() in {".wav", ".ogg"}), None)
        if sound_key:
            engine.assets.load_sound(PurePosixPath(sound_key).relative_to("assets").as_posix())
        music_key = next((key for key in resources_under("assets/music")
                          if PurePosixPath(key).suffix.casefold() in {".wav", ".ogg", ".mp3"}), None)
        if music_key:
            engine.assets.play_music(PurePosixPath(music_key).relative_to("assets").as_posix(), 0.0)
            pygame.mixer.music.stop()
    print("Staged engine startup and in-memory asset smoke check passed.")
finally:
    engine.shutdown()
'''

    environment = os.environ.copy()
    environment["SDL_VIDEODRIVER"] = "dummy"
    environment["SDL_AUDIODRIVER"] = "dummy"
    smoke = subprocess.run(
        [sys.executable, "-c", runtime_smoke],
        cwd=stage_root,
        env=environment,
        check=False,
    )
    if smoke.returncode != 0:
        print("The staged startup smoke check failed; Nuitka was not started.", file=sys.stderr)
    return smoke.returncode


def _default_output_dir() -> Path:
    parent = PROJECT_ROOT / "dist"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = parent / f"build-{timestamp}"
    suffix = 1
    while candidate.exists():
        candidate = parent / f"build-{timestamp}-{suffix}"
        suffix += 1
    return candidate


def _parse_args():
    parser = argparse.ArgumentParser(description="Compile this project with Nuitka for the current desktop OS.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (must not already contain files; default: a new timestamped folder in dist/).",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=max(1, min(4, os.cpu_count() or 1)),
        help="Number of parallel Nuitka compilation jobs (default: up to 4).",
    )
    parser.add_argument(
        "--engine-only",
        action="store_true",
        help="Build a native engine executable with engine resources only; load project assets/data beside it.",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        help="Project root containing assets/ and data/ to embed (default: this script's folder).",
    )
    parser.add_argument(
        "--output-name",
        help="Executable filename (default: the standard project or engine name for this OS).",
    )
    parser.add_argument(
        "--macos-app-bundle",
        action="store_true",
        help="Build the output as a macOS .app bundle (macOS only).",
    )
    parser.add_argument(
        "--windows-console-mode",
        choices=("attach", "disable", "force"),
        default="attach",
        help="Windows console behavior for the executable (default: attach).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not PROJECT_ROOT.joinpath("main.py").is_file():
        print(f"Could not find main.py under {PROJECT_ROOT}.", file=sys.stderr)
        return 2
    try:
        import importlib.util

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

    if args.jobs < 1:
        print("--jobs must be at least 1.", file=sys.stderr)
        return 2
    if args.engine_only and args.project_dir is not None:
        print("--project-dir cannot be used with --engine-only.", file=sys.stderr)
        return 2
    if args.macos_app_bundle and sys.platform != "darwin":
        print("--macos-app-bundle can only be used when compiling on macOS.", file=sys.stderr)
        return 2

    project_dir = args.project_dir or PROJECT_ROOT
    if not project_dir.is_absolute():
        project_dir = (PROJECT_ROOT / project_dir).resolve()
    else:
        project_dir = project_dir.resolve()

    try:
        _self_check_payload_generator()
    except Exception as error:
        print(f"Embedded-payload preflight failed: {error}", file=sys.stderr)
        return 1
    print("Embedded payload encoder self-check passed.")

    output_dir = (args.output_dir or _default_output_dir()).expanduser()
    output_name = args.output_name or (ENGINE_OUTPUT_NAME if args.engine_only else OUTPUT_NAME)
    if WINDOWS_BUILD and not output_name.casefold().endswith(".exe"):
        output_name += ".exe"
    elif not WINDOWS_BUILD and output_name.casefold().endswith(".exe"):
        print("Use an executable name without the .exe suffix on Linux and macOS.", file=sys.stderr)
        return 2
    if Path(output_name).name != output_name:
        print("--output-name must be a filename, not a path.", file=sys.stderr)
        return 2
    if not output_dir.is_absolute():
        output_dir = (PROJECT_ROOT / output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        print(f"Output directory is not empty: {output_dir}", file=sys.stderr)
        return 2
    try:
        with tempfile.TemporaryDirectory(prefix="visual_novel_nuitka_") as temporary:
            stage_root = Path(temporary) / "project"
            stage_root.mkdir()
            _stage_sources(stage_root)
            count, raw_total, generated_total = _generate_payload(
                stage_root,
                engine_only=args.engine_only,
                project_dir=project_dir,
            )
            print(
                f"Embedding {count:,} files ({raw_total / (1024 ** 3):.2f} GiB raw; "
                f"{generated_total / (1024 ** 3):.2f} GiB generated Python)."
            )
            print("Preflighting the staged project before Nuitka compilation.")
            preflight = _preflight_staged_project(
                stage_root,
                engine_only=args.engine_only,
            )
            if preflight != 0:
                return preflight

            output_dir.mkdir(parents=True, exist_ok=True)
            if args.engine_only:
                build_mode = "macOS app bundle mode" if args.macos_app_bundle else "standalone folder mode"
                print(f"Compiling engine-only in {build_mode}.")
            else:
                print("Compiling in standalone folder mode. The source data/assets remain unchanged.")
            command = [
                sys.executable,
                "-m",
                "nuitka",
                f"--mode={'app' if args.macos_app_bundle else 'standalone'}",
                "--assume-yes-for-downloads",
                f"--output-dir={output_dir}",
                f"--output-filename={output_name}",
                f"--jobs={args.jobs}",
                "--python-flag=no_docstrings",
                "--include-package=engine",
                "main.py",
            ]
            if args.macos_app_bundle:
                app_name = Path(output_name).stem
                command[-1:-1] = (f"--macos-app-name={app_name}",)
            if WINDOWS_BUILD:
                command.insert(
                    command.index(f"--output-dir={output_dir}"),
                    f"--windows-console-mode={args.windows_console_mode}",
                )
            result = subprocess.run(command, cwd=stage_root, check=False)
            if result.returncode != 0:
                print(f"Nuitka failed with exit code {result.returncode}.", file=sys.stderr)
                return result.returncode
    except (OSError, ValueError) as error:
        print(f"Build failed: {error}", file=sys.stderr)
        return 1

    if args.macos_app_bundle:
        app_name = Path(output_name).stem
        app_candidates = [
            executable
            for app_bundle in output_dir.rglob("*.app")
            for executable in [app_bundle / "Contents" / "MacOS" / app_name]
            if executable.is_file()
        ]
        if len(app_candidates) == 1:
            print(f"Build complete: {app_candidates[0].parent.parent.parent}")
            return 0
        executable_candidates = []
    else:
        executable_candidates = list(output_dir.glob(f"*.dist/{output_name}"))
    if len(executable_candidates) == 1:
        executable = executable_candidates[0]
        distribution = executable.parent
        print(f"Build complete: {executable}")
        print(f"Copy or distribute the complete folder: {distribution}")
        return 0
    print(
        "Nuitka reported success, but the expected executable was not found exactly once "
        f"under {output_dir}. Inspect the output directory.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
