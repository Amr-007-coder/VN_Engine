"""Build a reusable Pygbag static-site template for VN Engine projects."""

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BROWSERFS_SCRIPT_URL = "https://cdnjs.cloudflare.com/ajax/libs/BrowserFS/1.4.3/browserfs.min.js"
PYGBAG_BROWSERFS_SCRIPT_URL = "https://pygame-web.github.io/cdn/0.9.3//browserfs.min.js"
LOADER_STYLE = """
<style id="vn-engine-loader">
    html, body {
        min-height: 100%;
        margin: 0;
        background: #000 !important;
        color: #e7edf7;
    }
    #transfer {
        position: fixed;
        inset: 0;
        z-index: 999998;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 18px;
        padding: 24px;
        background: #000 !important;
    }
    #transfer[hidden] {
        display: none !important;
    }
    #transfer::before {
        content: "";
        display: block;
        width: min(220px, 48vw, 48vh);
        aspect-ratio: 1;
        margin-bottom: 12px;
        background: url("logo.png") center / contain no-repeat;
    }
    #status {
        display: block;
        margin: 0;
        color: #b8c2d2;
        font-size: 14px;
        font-weight: 400;
        text-align: center;
    }
    #progress {
        display: block;
        width: min(340px, 72vw);
        height: 6px;
        overflow: hidden;
        border: 0;
        border-radius: 999px;
        appearance: none;
        -webkit-appearance: none;
        background: #202633;
    }
    #progress::-webkit-progress-bar {
        border-radius: 999px;
        background: #202633;
    }
    #progress::-webkit-progress-value {
        border-radius: 999px;
        background: #278cff;
        transition: width 0.2s ease;
    }
    #progress::-moz-progress-bar {
        border-radius: 999px;
        background: #278cff;
    }
    #infobox {
        position: fixed !important;
        top: auto !important;
        left: 50% !important;
        bottom: 24px !important;
        transform: translateX(-50%);
        max-width: calc(100vw - 32px);
        background: #000 !important;
        color: #d5dce7;
        font-weight: 400;
        text-align: center;
    }
</style>
"""


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "templates" / "template-web.zip",
        help="Output browser template ZIP (default: templates/template-web.zip)",
    )
    return parser.parse_args()


def _copy_python_package(package_name: str, destination: Path) -> None:
    spec = importlib.util.find_spec(package_name)
    if spec is None or spec.origin is None:
        raise RuntimeError(f"Required Python package {package_name!r} is not installed.")
    package_root = Path(spec.origin).resolve().parent
    destination.mkdir(parents=True, exist_ok=True)
    for source in package_root.rglob("*.py"):
        if "__pycache__" in source.parts:
            continue
        target = destination / source.relative_to(package_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _convert_engine_audio(app_root: Path) -> None:
    wav_files = sorted(app_root.rglob("*.wav"))
    if not wav_files:
        return
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("Install ffmpeg to convert the built-in WAV sounds to browser-compatible OGG files.")
    for source in wav_files:
        destination = source.with_suffix(".ogg")
        subprocess.run(
            [ffmpeg, "-y", "-i", str(source), "-c:a", "libvorbis", "-q:a", "5", str(destination)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        source.unlink()


def _write_starter_project(app_root: Path) -> None:
    assets_root = app_root / "assets"
    data_root = app_root / "data"
    assets_root.mkdir()
    data_root.mkdir()
    (data_root / "story.yaml").write_text(
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
    (data_root / "project.json").write_text(
        '{\n'
        '  "name": "My Visual Novel",\n'
        '  "story": "story.yaml",\n'
        '  "icon": null,\n'
        '  "save_slots": 5,\n'
        '  "paths": {"data": "data", "assets": "assets", "user_data": "user_data"}\n'
        '}\n',
        encoding="utf-8",
        newline="\n",
    )


def build_template(output: Path) -> Path:
    if importlib.util.find_spec("pygbag") is None:
        raise RuntimeError("Pygbag is not installed. Install requirements.txt first.")
    output = output.expanduser()
    if not output.is_absolute():
        output = PROJECT_ROOT / output
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="vn_web_template_") as temporary:
        app_root = Path(temporary) / "vn-engine-web"
        app_root.mkdir()
        shutil.copytree(PROJECT_ROOT / "engine", app_root / "engine", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        # Pygbag requires its async browser entry point to be named main.py.
        shutil.copy2(PROJECT_ROOT / "web_main.py", app_root / "main.py")
        shutil.copy2(PROJECT_ROOT / "engine" / "assets" / "images" / "logo.png", app_root / "favicon.png")
        _copy_python_package("yaml", app_root / "yaml")
        _write_starter_project(app_root)
        _convert_engine_audio(app_root)

        subprocess.run(
            [
                sys.executable,
                "-m",
                "pygbag",
                "--build",
                "--PYBUILD=3.12",
                "--title=VN Engine",
                f"--icon={app_root / 'favicon.png'}",
                str(app_root),
            ],
            cwd=PROJECT_ROOT,
            check=True,
        )

        web_root = app_root / "build" / "web"
        if not (web_root / "index.html").is_file():
            raise FileNotFoundError(f"Pygbag did not create index.html under {web_root}.")
        shutil.copy2(PROJECT_ROOT / "engine" / "assets" / "images" / "logo.png", web_root / "logo.png")
        index_path = web_root / "index.html"
        index_html = index_path.read_text(encoding="utf-8")
        if index_html.count(PYGBAG_BROWSERFS_SCRIPT_URL) != 1:
            raise RuntimeError("Pygbag's expected BrowserFS script reference was not found exactly once.")
        index_html = index_html.replace(PYGBAG_BROWSERFS_SCRIPT_URL, BROWSERFS_SCRIPT_URL)
        if index_html.count("</head>") != 1:
            raise RuntimeError("Pygbag's expected closing head tag was not found exactly once.")
        index_path.write_text(
            index_html.replace("</head>", f"{LOADER_STYLE}\n</head>", 1),
            encoding="utf-8",
            newline="\n",
        )
        app_archives = list(web_root.glob("*.apk"))
        if len(app_archives) != 1:
            raise FileNotFoundError(f"Expected one Pygbag .apk archive under {web_root}; found {len(app_archives)}.")

        temporary_output = output.with_name(f".{output.name}.tmp")
        try:
            with ZipFile(temporary_output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
                for source in sorted(web_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
                    if source.is_file():
                        archive.write(source, source.relative_to(web_root).as_posix())
            os.replace(temporary_output, output)
        finally:
            temporary_output.unlink(missing_ok=True)
    return output


def main() -> int:
    args = _parse_args()
    try:
        output = build_template(args.output)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Web template build failed: {error}", file=sys.stderr)
        return 1
    print(f"Created browser export template: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
