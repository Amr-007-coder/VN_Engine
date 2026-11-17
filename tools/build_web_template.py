"""Build a reusable Pygbag static-site template for VN Engine projects."""

import argparse
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.project import DEFAULT_PROJECT


PYGBAG_RUNTIME_VERSION = "0.9.3"
PYGBAG_CDN_URL = f"https://pygame-web.github.io/cdn/{PYGBAG_RUNTIME_VERSION}/"
PYGBAG_PACKAGE_INDEX = f"index-{PYGBAG_RUNTIME_VERSION}-cp312.json"
PYGBAG_PYGAME_WHEEL = "cp312/pygame_ce-2.5.7-cp312-cp312-wasm32_bi_emscripten.whl"
BROWSERFS_SCRIPT_URL = "https://cdnjs.cloudflare.com/ajax/libs/BrowserFS/1.4.3/browserfs.min.js"
PYGBAG_BROWSERFS_SCRIPT_URL = f"{PYGBAG_CDN_URL}/browserfs.min.js"
LOCAL_RUNTIME_ROOT = f"./runtime/{PYGBAG_RUNTIME_VERSION}/"
SERVICE_WORKER_BLOCK = f"""    <script>
/*
        if (navigator.serviceWorker)
            navigator.serviceWorker.register("{PYGBAG_CDN_URL}pygbag{PYGBAG_RUNTIME_VERSION}.js")
        else
            console.warn("Service workers not supported")
*/
    </script>"""
PYGBAG_VERSIONED_RUNTIME_FILES = (
    "cpython312/main.data",
    "cpython312/main.js",
    "cpython312/main.wasm",
    "cpythonrc.py",
    "empty.html",
    "empty.ogg",
    "pythons.js",
)
PYGBAG_SHARED_RUNTIME_FILES = (
    "vt.js",
    "vtx.js",
    "vt/xterm-addon-image.js",
    "vt/xterm.css",
    "vt/xterm.js",
    "lib/dlfcn.js",
    "lib/enginesound/engine.js",
    "lib/enginesound/engine.ogg",
    "lib/enginesound/index.html",
    "lib/espeak/index.html",
    "lib/espeak/speakClient.js",
    "lib/espeak/speakGenerator.js",
    "lib/espeak/speakWorker.js",
    "lib/index.html",
    "lib/main.html",
    "lib/sub.html",
)
RUNTIME_LICENSES = {
    "pygbag-cdn-MIT.txt": "https://raw.githubusercontent.com/pygame-web/cdn/main/LICENSE",
    "browserfs-MIT.txt": "https://raw.githubusercontent.com/jvilk/BrowserFS/master/license.md",
    "cpython-PSF.txt": "https://raw.githubusercontent.com/python/cpython/3.12/LICENSE",
    "pygame-ce-LGPL-2.1.txt": "https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt",
}
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


def _download_runtime_file(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "VN-Engine web template builder"})
    with urlopen(request, timeout=120) as response:
        contents = response.read()
    if not contents:
        raise RuntimeError(f"Downloaded runtime file is empty: {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(contents)


def _vendor_web_runtime(web_root: Path) -> None:
    versioned_root = web_root / LOCAL_RUNTIME_ROOT
    for relative_path in PYGBAG_VERSIONED_RUNTIME_FILES:
        _download_runtime_file(
            f"{PYGBAG_CDN_URL}{relative_path}",
            versioned_root / relative_path,
        )

    shared_root = web_root / "runtime"
    for relative_path in PYGBAG_SHARED_RUNTIME_FILES:
        destination_root = web_root / "cdn" if relative_path.startswith("lib/") else shared_root
        _download_runtime_file(
            f"https://pygame-web.github.io/cdn/{relative_path}",
            destination_root / relative_path,
        )

    _download_runtime_file(
        BROWSERFS_SCRIPT_URL,
        versioned_root / "browserfs.min.js",
    )
    _download_runtime_file(
        f"https://pygame-web.github.io/cdn/{PYGBAG_PACKAGE_INDEX}",
        web_root / "cdn" / PYGBAG_PACKAGE_INDEX,
    )
    package_index_path = web_root / "cdn" / PYGBAG_PACKAGE_INDEX
    try:
        package_index = json.loads(package_index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError("The downloaded Pygbag package index is invalid.") from error
    if not isinstance(package_index, dict):
        raise RuntimeError("The downloaded Pygbag package index is not a JSON object.")
    indexed_pygame_wheel = package_index.get("pygame", "")
    indexed_pygame_wheel = indexed_pygame_wheel.replace("<abi>", "cp312").replace(
        "<api>",
        "wasm32_bi_emscripten",
    )
    if indexed_pygame_wheel != PYGBAG_PYGAME_WHEEL:
        raise RuntimeError("The Pygbag package index does not match the bundled Pygame wheel.")
    package_index["-CDN-"] = "./cdn/"
    package_index_path.write_text(
        json.dumps(package_index, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )
    _download_runtime_file(
        f"https://pygame-web.github.io/cdn/{PYGBAG_PYGAME_WHEEL}",
        web_root / "cdn" / PYGBAG_PYGAME_WHEEL,
    )
    license_root = web_root / "runtime" / "licenses"
    for filename, url in RUNTIME_LICENSES.items():
        _download_runtime_file(url, license_root / filename)
    (license_root / "THIRD_PARTY_NOTICES.txt").write_text(
        "Pygbag CDN runtime 0.9.3: MIT License (pygbag-cdn-MIT.txt).\n"
        "BrowserFS 1.4.3: MIT License (browserfs-MIT.txt).\n"
        "CPython 3.12: PSF License (cpython-PSF.txt).\n"
        "pygame-ce 2.5.7: LGPL v2.1 (pygame-ce-LGPL-2.1.txt); source: "
        "https://github.com/pygame-community/pygame-ce/tree/2.5.7\n",
        encoding="utf-8",
        newline="\n",
    )

    cpythonrc_path = versioned_root / "cpythonrc.py"
    cpythonrc_path.write_text(
        'import os\nos.environ["PYGPI"] = "./cdn/"\n'
        + cpythonrc_path.read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )

    vtx_path = shared_root / "vtx.js"
    vtx_script = vtx_path.read_text(encoding="utf-8")
    remote_configured_base = 'xterm_cdn = window.Module.config.cdn+"../vt/"'
    if vtx_script.count(remote_configured_base) != 1:
        raise RuntimeError("Pygbag's expected terminal CDN path was not found exactly once.")
    vtx_script = vtx_script.replace(
        remote_configured_base,
        'xterm_cdn = new URL(window.Module.config.cdn+"../vt/", document.baseURI).href',
        1,
    )
    remote_terminal_fallback = 'xterm_cdn = xterm_cdn || "https://pygame-web.github.io/cdn/vt/"'
    if vtx_script.count(remote_terminal_fallback) != 1:
        raise RuntimeError("Pygbag's expected terminal fallback URL was not found exactly once.")
    vtx_path.write_text(
        vtx_script.replace(
            remote_terminal_fallback,
            'xterm_cdn = xterm_cdn || new URL("./runtime/vt/", document.baseURI).href',
            1,
        ),
        encoding="utf-8",
        newline="\n",
    )

    if not (versioned_root / "cpython312" / "main.wasm").read_bytes().startswith(b"\0asm"):
        raise RuntimeError("The downloaded Pygbag WebAssembly runtime is invalid.")


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
    project = deepcopy(DEFAULT_PROJECT)
    project["name"] = "My Visual Novel"
    project["menus"]["main"]["title"] = "My Visual Novel"
    (data_root / "project.json").write_text(
        json.dumps(project, ensure_ascii=True, indent=2) + "\n",
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

        runtime_archive = web_root / "vn-engine-web.tar.gz"
        if runtime_archive.is_file():
            # Pygbag's packaged runtime archive is already in place; keep it and avoid re-downloading
            # or rewriting the generated runtime URLs unless the build actually needs local runtime assets.
            pass
        else:
            _vendor_web_runtime(web_root)

        index_path = web_root / "index.html"
        index_html = index_path.read_text(encoding="utf-8")
        if SERVICE_WORKER_BLOCK in index_html:
            if index_html.count(SERVICE_WORKER_BLOCK) != 1:
                raise RuntimeError("Pygbag's expected disabled service-worker block was not found exactly once.")
            index_html = index_html.replace(SERVICE_WORKER_BLOCK, "", 1)
        if runtime_archive.is_file():
            if PYGBAG_BROWSERFS_SCRIPT_URL in index_html:
                index_html = index_html.replace(PYGBAG_BROWSERFS_SCRIPT_URL, BROWSERFS_SCRIPT_URL, 1)
        else:
            if index_html.count(PYGBAG_BROWSERFS_SCRIPT_URL) != 1:
                raise RuntimeError("Pygbag's expected BrowserFS script reference was not found exactly once.")
            index_html = index_html.replace(
                PYGBAG_BROWSERFS_SCRIPT_URL,
                f"{LOCAL_RUNTIME_ROOT}browserfs.min.js",
            )
            if PYGBAG_CDN_URL not in index_html:
                raise RuntimeError("Pygbag's expected CDN base URL was not found.")
            index_html = index_html.replace(PYGBAG_CDN_URL, LOCAL_RUNTIME_ROOT)
            if "https://" in index_html or "http://" in index_html:
                raise RuntimeError("The generated web page still contains an external URL.")
        if "</head>" in index_html:
            if index_html.count("</head>") != 1:
                raise RuntimeError("Pygbag's expected closing head tag was not found exactly once.")
            index_html = index_html.replace("</head>", f"{LOADER_STYLE}\n</head>", 1)
        else:
            index_html += f"\n{LOADER_STYLE}\n"
        index_path.write_text(index_html, encoding="utf-8", newline="\n")
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
