"""Download VN Engine runtime templates and matching Android source from GitHub Releases."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile


REPOSITORY = "Amr-007-coder/VN_Engine"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
USER_AGENT = "VN-Engine-Editor"
PLATFORMS = ("windows", "linux", "macos", "web")
STARTER_PROJECT_ASSET = "VN_Engine-Starter-Project.zip"
_TAG_PATTERN = re.compile(r"[A-Za-z0-9._+-]+")


@dataclass(frozen=True)
class Release:
    tag: str
    assets: dict[str, dict]


def _validate_tag(tag: str) -> str:
    if not isinstance(tag, str) or tag in {".", ".."} or not _TAG_PATTERN.fullmatch(tag):
        raise ValueError(f"Invalid VN Engine release tag: {tag!r}")
    return tag


def _request_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"Could not download from GitHub: {url}\n{error}") from error


def _request_json(url: str):
    try:
        return json.loads(_request_bytes(url))
    except json.JSONDecodeError as error:
        raise ValueError(f"GitHub returned invalid release metadata for {url}.") from error


def _release_from_payload(payload) -> Release:
    if not isinstance(payload, dict):
        raise ValueError("GitHub returned an invalid release description.")
    tag = _validate_tag(payload.get("tag_name"))
    raw_assets = payload.get("assets")
    if not isinstance(raw_assets, list):
        raise ValueError(f"GitHub release {tag} has invalid asset metadata.")
    assets = {}
    for asset in raw_assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        url = asset.get("browser_download_url")
        if isinstance(name, str) and isinstance(url, str):
            assets[name] = asset
    return Release(tag=tag, assets=assets)


@lru_cache(maxsize=1)
def _latest_release() -> Release:
    return _release_from_payload(_request_json(f"{API_ROOT}/releases/latest"))


def latest_template_release_tag() -> str:
    latest = _latest_release()
    if "template-web.zip" in latest.assets:
        return latest.tag
    tags = list_template_release_tags("web")
    if not tags:
        raise FileNotFoundError("No VN Engine GitHub release contains template-web.zip.")
    return tags[0]


@lru_cache(maxsize=64)
def _release_for_tag(tag: str) -> Release:
    tag = _validate_tag(tag)
    return _release_from_payload(_request_json(f"{API_ROOT}/releases/tags/{quote(tag, safe='')}"))


@lru_cache(maxsize=4)
def list_template_release_tags(platform: str = "web") -> tuple[str, ...]:
    template_name = _template_name(platform)
    tags = []
    page = 1
    while True:
        payload = _request_json(f"{API_ROOT}/releases?per_page=100&page={page}")
        if not isinstance(payload, list):
            raise ValueError("GitHub returned an invalid list of VN Engine releases.")
        for item in payload:
            try:
                release = _release_from_payload(item)
            except ValueError:
                continue
            if template_name in release.assets:
                tags.append(release.tag)
        if len(payload) < 100:
            return tuple(tags)
        page += 1


@lru_cache(maxsize=1)
def _latest_release_with_asset(asset_name: str) -> Release:
    page = 1
    while True:
        payload = _request_json(f"{API_ROOT}/releases?per_page=100&page={page}")
        if not isinstance(payload, list):
            raise ValueError("GitHub returned an invalid list of VN Engine releases.")
        for item in payload:
            try:
                release = _release_from_payload(item)
            except ValueError:
                continue
            if asset_name in release.assets:
                return release
        if len(payload) < 100:
            raise FileNotFoundError(f"No VN Engine GitHub release contains {asset_name}.")
        page += 1


def _cache_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "VN_Engine" / "templates"


def _cached_template(release_tag: str, template_name: str) -> Path:
    return _cache_root() / _validate_tag(release_tag) / template_name


def _cached_starter_project(release_tag: str) -> Path:
    return _cache_root().parent / "starter-projects" / _validate_tag(release_tag) / STARTER_PROJECT_ASSET


def _cached_latest_tag(platform: str) -> str | None:
    latest_path = _cache_root() / f"latest-{platform}.txt"
    try:
        return _validate_tag(latest_path.read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        return None


def _remember_latest_tag(platform: str, release_tag: str) -> None:
    root = _cache_root()
    root.mkdir(parents=True, exist_ok=True)
    latest_path = root / f"latest-{platform}.txt"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".latest-{platform}.", dir=root)
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        temporary_path.write_text(f"{release_tag}\n", encoding="utf-8", newline="\n")
        os.replace(temporary_path, latest_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _template_name(platform: str) -> str:
    if platform not in PLATFORMS:
        raise ValueError(f"Template platform must be one of: {', '.join(PLATFORMS)}.")
    return f"template-{platform}.zip"


def _is_valid_zip(path: Path) -> bool:
    try:
        with ZipFile(path, "r") as archive:
            return bool(archive.infolist()) and archive.testzip() is None
    except (BadZipFile, OSError, EOFError):
        return False


def _copy_asset(response, destination: Path, expected_size: int | None) -> str:
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if expected_size is not None and size > expected_size:
                raise ValueError("GitHub release asset exceeded its declared size.")
            digest.update(chunk)
            output.write(chunk)
    if expected_size is not None and size != expected_size:
        raise ValueError(f"GitHub release asset size mismatch: expected {expected_size} bytes, got {size}.")
    return digest.hexdigest()


def _download_template_asset(asset: dict, template_name: str, destination: Path) -> None:
    url = asset.get("browser_download_url")
    if not isinstance(url, str):
        raise ValueError(f"GitHub release asset {template_name} has no download URL.")
    expected_size = asset.get("size")
    if not isinstance(expected_size, int) or expected_size < 0:
        expected_size = None

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, download_name = tempfile.mkstemp(
        prefix=f".{template_name}.", suffix=".download", dir=destination.parent
    )
    os.close(descriptor)
    downloaded = Path(download_name)
    nested = None
    direct_archive = False
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=120) as response:
                actual_digest = _copy_asset(response, downloaded, expected_size)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise RuntimeError(f"Could not download {template_name} from GitHub Releases.\n{error}") from error

        expected_digest = asset.get("digest")
        if isinstance(expected_digest, str) and expected_digest.startswith("sha256:"):
            if actual_digest.casefold() != expected_digest[7:].casefold():
                raise ValueError(f"SHA-256 verification failed for GitHub release asset {template_name}.")

        with ZipFile(downloaded, "r") as outer:
            if outer.testzip() is not None:
                raise ValueError(f"GitHub release asset {template_name} failed ZIP integrity checks.")
            files = [item for item in outer.infolist() if not item.is_dir()]
            if not files:
                raise ValueError(f"GitHub release asset {template_name} is empty.")
            if len(files) == 1 and PurePosixPath(files[0].filename).name.casefold() == template_name.casefold():
                descriptor, nested_name = tempfile.mkstemp(
                    prefix=f".{template_name}.", suffix=".nested", dir=destination.parent
                )
                os.close(descriptor)
                nested = Path(nested_name)
                with outer.open(files[0], "r") as source, nested.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if not _is_valid_zip(nested):
                    raise ValueError(f"The wrapped GitHub release asset {template_name} is not a valid template ZIP.")
            else:
                direct_archive = True
        if nested is not None:
            os.replace(nested, destination)
            nested = None
        elif direct_archive:
            os.replace(downloaded, destination)
    except BadZipFile as error:
        raise ValueError(f"GitHub release asset {template_name} is not a valid ZIP file.") from error
    finally:
        downloaded.unlink(missing_ok=True)
        if nested is not None:
            nested.unlink(missing_ok=True)


def ensure_template(platform: str, release_tag: str | None = None) -> Path:
    """Return a cached template, downloading it from the selected public release if needed."""
    template_name = _template_name(platform)
    if release_tag is None:
        try:
            release = _latest_release()
        except RuntimeError:
            cached_tag = _cached_latest_tag(platform)
            if cached_tag is not None:
                cached_template = _cached_template(cached_tag, template_name)
                if _is_valid_zip(cached_template):
                    return cached_template
            raise
        if template_name not in release.assets:
            release = next(
                (
                    candidate
                    for tag in list_template_release_tags(platform)
                    for candidate in (_release_for_tag(tag),)
                    if template_name in candidate.assets
                ),
                release,
            )
    else:
        release_tag = _validate_tag(release_tag)
        cached_template = _cached_template(release_tag, template_name)
        if _is_valid_zip(cached_template):
            return cached_template
        release = _release_for_tag(release_tag)

    asset = release.assets.get(template_name)
    if asset is None:
        raise FileNotFoundError(f"GitHub release {release.tag} does not contain {template_name}.")

    destination = _cached_template(release.tag, template_name)
    if destination.is_file() and _is_valid_zip(destination):
        if release_tag is None:
            _remember_latest_tag(platform, release.tag)
        return destination
    destination.unlink(missing_ok=True)
    _download_template_asset(asset, template_name, destination)
    if release_tag is None:
        _remember_latest_tag(platform, release.tag)
    return destination


def _validate_starter_project_archive(path: Path) -> None:
    try:
        with ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if not infos:
                raise ValueError("The starter-project archive is empty.")
            if sum(item.file_size for item in infos) > 64 * 1024 * 1024:
                raise ValueError("The starter-project archive is too large.")
            if archive.testzip() is not None:
                raise ValueError("The starter-project archive failed ZIP integrity checks.")

            names = set()
            files = set()
            for item in infos:
                name = item.filename
                relative = PurePosixPath(name)
                if (
                    not name
                    or "\\" in name
                    or relative.is_absolute()
                    or any(part in {"", ".", ".."} or ":" in part for part in relative.parts)
                    or relative.parts[0] not in {"assets", "data"}
                ):
                    raise ValueError(f"Unsafe path in starter-project archive: {name!r}.")
                if relative.as_posix().casefold() in names:
                    raise ValueError(f"Duplicate path in starter-project archive: {name!r}.")
                names.add(relative.as_posix().casefold())
                mode = item.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError(f"Symbolic links are not allowed in the starter-project archive: {name!r}.")
                if item.flag_bits & 0x1:
                    raise ValueError("Encrypted entries are not allowed in the starter-project archive.")
                if not item.is_dir():
                    files.add(relative.as_posix().casefold())

            required = {"data/project.json", "data/story.yaml"}
            missing = required - files
            if missing:
                raise ValueError(
                    "The starter-project archive is missing required files: "
                    + ", ".join(sorted(missing))
                )
    except BadZipFile as error:
        raise ValueError("The starter-project archive is not a valid ZIP file.") from error


def _is_valid_starter_project_archive(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        _validate_starter_project_archive(path)
    except (BadZipFile, ValueError, EOFError):
        return False
    return True


def ensure_starter_project_archive(release_tag: str | None = None) -> Path:
    """Return a cached starter-project archive from a release."""
    release = None
    if release_tag is not None:
        release = _release_for_tag(_validate_tag(release_tag))
        if STARTER_PROJECT_ASSET not in release.assets:
            release = None
    if release is None:
        release = _latest_release_with_asset(STARTER_PROJECT_ASSET)

    destination = _cached_starter_project(release.tag)
    if _is_valid_starter_project_archive(destination):
        return destination
    destination.unlink(missing_ok=True)
    _download_template_asset(release.assets[STARTER_PROJECT_ASSET], STARTER_PROJECT_ASSET, destination)
    if not _is_valid_starter_project_archive(destination):
        destination.unlink(missing_ok=True)
        raise ValueError(f"GitHub release asset {STARTER_PROJECT_ASSET} is not a valid starter project.")
    return destination


def install_starter_project(
    destination: Path,
    release_tag: str | None = None,
    project_template: dict | None = None,
) -> bool:
    """Create from a template, or install a legacy release archive when none is given."""
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        if not destination.is_dir():
            raise FileExistsError(f"The starter-project destination is not a directory: {destination}")
        return False

    if project_template is not None and not isinstance(project_template, dict):
        raise ValueError("The starter-project template must be an object.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".vn-engine-starter-", dir=destination.parent))
    try:
        if project_template is None:
            archive_path = ensure_starter_project_archive(release_tag)
            _validate_starter_project_archive(archive_path)
            with ZipFile(archive_path, "r") as archive:
                for item in archive.infolist():
                    relative = PurePosixPath(item.filename)
                    target = temporary.joinpath(*relative.parts)
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item, "r") as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
        else:
            _write_starter_project(temporary, project_template)
        try:
            os.rename(temporary, destination)
        except OSError:
            if destination.is_dir():
                return False
            raise
        return True
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _write_starter_project(root: Path, project_template: dict) -> None:
    assets = root / "assets"
    data = root / "data"
    assets.mkdir()
    data.mkdir()
    (data / "story.yaml").write_text(
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
    project = deepcopy(project_template)
    if not isinstance(project.get("menus"), dict) or not isinstance(
        project["menus"].get("main"), dict
    ):
        raise ValueError("The starter-project template must define menus.main.")
    project["name"] = "My Visual Novel"
    project["menus"]["main"]["title"] = "My Visual Novel"
    (data / "project.json").write_text(
        json.dumps(project, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def fetch_android_sources(release_tag: str) -> tuple[bytes, bytes, bytes]:
    """Fetch the Android entrypoint and platform runtime sources for one release."""
    tag = _validate_tag(release_tag)
    encoded_tag = quote(tag, safe="")
    source_files = (
        f"https://raw.githubusercontent.com/{REPOSITORY}/{encoded_tag}/web_main.py",
        f"https://raw.githubusercontent.com/{REPOSITORY}/{encoded_tag}/engine/engine.py",
        f"https://raw.githubusercontent.com/{REPOSITORY}/{encoded_tag}/engine/platform_runtime.py",
    )
    return tuple(_request_bytes(url) for url in source_files)
