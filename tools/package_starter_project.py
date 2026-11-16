"""Create the starter-project ZIP published with VN Engine releases."""

import argparse
import json
import os
from pathlib import Path
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile


STARTER_PROJECT_NAME = "VN_Engine-Starter-Project.zip"


def _write_starter_project(root: Path) -> None:
    (root / "assets").mkdir(parents=True)
    data = root / "data"
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
    project = {
        "name": "My Visual Novel",
        "story": "story.yaml",
        "icon": None,
        "android": {
            "app_name": "VN Engine",
            "app_id": "com.example.vnengine",
            "orientation": "landscape",
        },
        "save_slots": 5,
        "paths": {"data": "data", "assets": "assets", "user_data": "user_data"},
    }
    (data / "project.json").write_text(
        json.dumps(project, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def package_starter_project(output: Path) -> Path:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_name(f".{output.name}.tmp")
    try:
        with tempfile.TemporaryDirectory(prefix="vn_starter_project_") as temporary:
            root = Path(temporary) / "starter-project"
            root.mkdir()
            _write_starter_project(root)
            with ZipFile(temporary_output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
                archive.writestr("assets/", b"")
                archive.writestr("data/", b"")
                for path in sorted((root / "data").iterdir(), key=lambda item: item.name):
                    archive.write(path, path.relative_to(root).as_posix())
        os.replace(temporary_output, output)
    finally:
        temporary_output.unlink(missing_ok=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist") / STARTER_PROJECT_NAME)
    args = parser.parse_args()
    output = package_starter_project(args.output)
    print(f"Created {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
