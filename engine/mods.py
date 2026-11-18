"""Build safe, data-only VN asset packages (.vnmod files)."""

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import sys
from zipfile import ZIP_DEFLATED, ZipFile


ASSET_FOLDERS = {"images", "sounds", "music", "fonts", "characters"}
MOD_EXTENSION = ".vnmod"


def build_asset_package(source_dir, destination, mod_id=None, name=None, version="1.0.0"):
    source = Path(source_dir).resolve()
    output = Path(destination)
    if not source.is_dir():
        raise FileNotFoundError(f"Asset source folder was not found: {source}")
    if output.suffix.casefold() != MOD_EXTENSION:
        output = output.with_suffix(MOD_EXTENSION)
    normalized_id = mod_id or re.sub(r"[^a-z0-9-]+", "-", source.name.casefold()).strip("-") or "asset-pack"
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", normalized_id):
        raise ValueError("Mod ID must use 1-64 lowercase letters, numbers, dots, underscores, or hyphens.")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}", version):
        raise ValueError("Mod version must be a short identifier using letters, numbers, dots, underscores, or hyphens.")

    files = []
    for folder in sorted(ASSET_FOLDERS):
        folder_path = source / folder
        if not folder_path.is_dir():
            continue
        for item in sorted(folder_path.rglob("*"), key=lambda path: path.as_posix().casefold()):
            if not item.is_file() or item.is_symlink() or "__pycache__" in item.parts:
                continue
            try:
                item.resolve().relative_to(source)
            except ValueError:
                continue
            relative = item.relative_to(source).as_posix()
            pure = PurePosixPath(relative)
            if pure.is_absolute() or ".." in pure.parts or pure.parts[0] not in ASSET_FOLDERS:
                continue
            files.append((item, f"assets/{relative}"))
    if not files:
        raise ValueError("No files were found in images/, sounds/, music/, fonts/, or characters/.")

    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format_version": 1,
        "id": normalized_id,
        "name": name or source.name,
        "version": version,
        "asset_count": len(files),
    }
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for file_path, member in files:
            archive.write(file_path, member)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="Package VN asset folders into a .vnmod file.")
    parser.add_argument("source", help="Folder containing images/, sounds/, music/, fonts/, or characters/")
    parser.add_argument("-o", "--output", required=True, help="Output .vnmod path")
    parser.add_argument("--id", dest="mod_id", help="Stable package ID (defaults to the source folder name)")
    parser.add_argument("--name", help="Display name (defaults to the source folder name)")
    parser.add_argument("--version", default="1.0.0", help="Package version (default: 1.0.0)")
    args = parser.parse_args(argv)
    try:
        output = build_asset_package(args.source, args.output, args.mod_id, args.name, args.version)
    except (OSError, ValueError) as error:
        print(f"Could not build asset package: {error}", file=sys.stderr)
        return 1
    print(f"Asset package created: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
