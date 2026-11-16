"""Create a versioned Git release tag that selects the templates to build."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = ("windows", "linux", "macos", "web")
DEFAULT_PLATFORMS = PLATFORMS
PLATFORM_RUNNERS = {
    "windows": "windows-latest",
    "linux": "ubuntu-22.04",
    "macos": "macos-latest",
    "web": "ubuntu-22.04",
}


def _build_matrix(platforms: list[str]) -> str:
    return json.dumps(
        {
            "include": [
                {"os": PLATFORM_RUNNERS[platform], "platform": platform}
                for platform in platforms
            ]
        },
        separators=(",", ":"),
    )


def _git(*arguments: str, capture_output: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *arguments],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=capture_output,
        text=True,
    )


def _git_output(*arguments: str) -> str:
    result = _git(*arguments, capture_output=True)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Git command failed: git {' '.join(arguments)}\n{detail}")
    return result.stdout.strip()


def _version_tag() -> str:
    version_file = PROJECT_ROOT / "engine" / "data" / "version.txt"
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"Could not read the engine version from {version_file}: {error}") from error
    if not version or not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise ValueError(f"Invalid engine version in {version_file}: {version!r}")
    tag = f"v{version}"
    if _git("check-ref-format", f"refs/tags/{tag}").returncode:
        raise ValueError(f"Version does not form a valid Git tag: {tag}")
    return tag


def _ask_yes_no(prompt: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} [{suffix}] ").strip().casefold()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Enter y or n.")


def _select_builds() -> tuple[list[str], bool, bool]:
    print("Choose the game templates to build:")
    selected = [
        platform
        for platform in PLATFORMS
        if _ask_yes_no(f"  Build {platform}?", True)
    ]
    if not selected:
        raise ValueError("Select at least one game template.")
    include_editor = _ask_yes_no("Build editor packages for Windows, Linux, and macOS?", True)
    include_android_apk = _ask_yes_no("Build an Android APK for the starter project too?", False)
    return selected, include_editor, include_android_apk


def _tag_exists(tag: str) -> bool:
    return _git("show-ref", "--verify", "--quiet", f"refs/tags/{tag}").returncode == 0


def _remote_tag_exists(tag: str) -> bool:
    result = _git("ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}", capture_output=True)
    if result.returncode == 0:
        return True
    if result.returncode == 2:
        return False
    detail = result.stderr.strip() or result.stdout.strip()
    raise RuntimeError(f"Could not check the remote tag {tag}.\n{detail}")


def _release(dry_run: bool = False) -> int:
    tag = _version_tag()
    branch = _git_output("branch", "--show-current")
    if not branch:
        raise RuntimeError("The Git worktree is detached; check out a branch before releasing.")
    _git_output("remote", "get-url", "origin")
    if _tag_exists(tag):
        raise RuntimeError(f"Local tag {tag} already exists. Update engine/data/version.txt before releasing.")

    version = tag[1:]
    print(f"Preparing VN Engine release {version} from branch {branch}.")
    platforms, include_editor, include_android_apk = _select_builds()
    status = _git_output("status", "--short", "--untracked-files=all")
    commit_message = None
    if status:
        print("The worktree has changes:")
        print(status)
        if not _ask_yes_no("Commit all current changes? This stages tracked and untracked files.", False):
            raise RuntimeError("Commit or discard the worktree changes before releasing.")
        commit_message = input("Commit message: ").strip()
        if not commit_message:
            raise ValueError("A non-empty commit message is required.")

    if dry_run:
        print(f"Dry run: git add -A && git commit -m {commit_message!r}" if commit_message else "Dry run: no commit needed.")
        print(f"Dry run: git push -u origin {branch}")
        print(
            f"Dry run: create annotated tag {tag} with build_platforms={','.join(platforms)}, "
            f"build_editor={'true' if include_editor else 'false'}, "
            f"build_android_apk={'true' if include_android_apk else 'false'}"
        )
        print(f"Dry run: git push origin refs/tags/{tag}")
        return 0

    if _remote_tag_exists(tag):
        raise RuntimeError(f"Remote tag {tag} already exists. Update engine/data/version.txt before releasing.")
    if commit_message is not None:
        result = _git("add", "-A")
        if result.returncode:
            raise RuntimeError("Could not stage all changes with git add -A.")
        result = _git("commit", "-m", commit_message)
        if result.returncode:
            raise RuntimeError("Git could not create the release commit.")

    result = _git("push", "-u", "origin", branch)
    if result.returncode:
        raise RuntimeError(f"Could not push branch {branch} to origin.")

    tag_message = (
        f"build_platforms={','.join(platforms)}\n"
        f"build_editor={'true' if include_editor else 'false'}\n"
        f"build_android_apk={'true' if include_android_apk else 'false'}"
    )
    result = _git("tag", "-a", tag, "-m", tag_message)
    if result.returncode:
        raise RuntimeError(f"Could not create annotated release tag {tag}.")
    result = _git("push", "origin", f"refs/tags/{tag}")
    if result.returncode:
        raise RuntimeError(
            f"Could not push tag {tag}. The tag remains local; retry with "
            f"'git push origin refs/tags/{tag}'."
        )
    print(f"Release {tag} pushed. GitHub Actions will build: {', '.join(platforms)}.")
    if include_editor:
        print("The Windows, Linux, and macOS editor packages will include those selected templates.")
    if include_android_apk:
        print("A fresh Android APK will be built from the current engine source.")
    return 0


def _read_tag_options(tag: str) -> dict[str, str]:
    if _git("check-ref-format", f"refs/tags/{tag}").returncode:
        raise ValueError(f"Invalid release tag: {tag}")
    message = _git_output("for-each-ref", "--format=%(contents)", f"refs/tags/{tag}")
    metadata = {}
    for line in message.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            metadata[key.strip()] = value.strip()

    targets = metadata.get("build_platforms")
    editor = metadata.get("build_editor")
    android_apk = metadata.get("build_android_apk", "false")
    if targets is None and editor is None:
        print("::warning::Tag has no build selection metadata; building all templates and editors.", file=sys.stderr)
        selected = list(DEFAULT_PLATFORMS)
        include_editor = True
        include_android_apk = False
    else:
        if targets is None or editor not in {"true", "false"}:
            raise ValueError(f"Release tag {tag} has incomplete build selection metadata.")
        selected = targets.split(",")
        if (
            not selected
            or len(selected) != len(set(selected))
            or any(platform not in PLATFORMS for platform in selected)
        ):
            raise ValueError(f"Release tag {tag} has invalid build_platforms metadata.")
        include_editor = editor == "true"
        if android_apk not in {"true", "false"}:
            raise ValueError(f"Release tag {tag} has invalid build_android_apk metadata.")
        include_android_apk = android_apk == "true"

    return {
        "platforms": json.dumps(selected, separators=(",", ":")),
        "platform_csv": ",".join(selected),
        "build_editor": "true" if include_editor else "false",
        "build_android_apk": "true" if include_android_apk else "false",
        "matrix": _build_matrix(selected),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show the Git release actions without changing anything.")
    parser.add_argument("--read-tag", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.read_tag:
            for key, value in _read_tag_options(args.read_tag).items():
                print(f"{key}={value}")
            return 0
        return _release(args.dry_run)
    except (OSError, RuntimeError, ValueError, EOFError) as error:
        print(f"Release preparation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
