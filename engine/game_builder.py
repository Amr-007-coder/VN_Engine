from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from engine.embedded import PROJECT_BUNDLE_COMMENT, project_bundle_present
from engine.assets import AssetManager
from engine.loader import PATHS
from engine.project import ProjectConfig
from engine.validator import StoryValidator
if os.name == "nt":
    from engine.windows_shortcut import create_shortcut


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _game_name(name: str) -> str:
    result = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not result:
        result = "Visual Novel"
    if Path(result).suffix.casefold() == ".exe":
        result = result[:-4].rstrip(" .")
    if not result or result.casefold() == "engine":
        result = "Visual Novel"
    if result.split(".", 1)[0].upper() in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }:
        result = f"_{result}"
    return result


def _story_relative_path(project: ProjectConfig) -> Path:
    data_root = project.data_dir.resolve()
    story_path = Path(project.story_file)
    if story_path.is_absolute():
        try:
            relative = story_path.resolve().relative_to(data_root)
        except ValueError as error:
            raise ValueError("The configured story file must be inside the project's data folder.") from error
    else:
        relative = story_path
        if ".." in relative.parts:
            raise ValueError("The configured story file cannot use parent-directory references.")
    if not relative.parts or relative.suffix.casefold() not in {".yaml", ".yml"}:
        raise ValueError("The configured story file must be a YAML file inside the data folder.")
    return relative


def _write_resource_bundle(bundle_path: Path, project: ProjectConfig) -> int:
    data_root = project.data_dir.resolve()
    assets_root = project.assets_dir.resolve()
    if not data_root.is_dir():
        raise FileNotFoundError(f"Project data folder was not found: {data_root}")
    if not assets_root.is_dir():
        raise FileNotFoundError(f"Project assets folder was not found: {assets_root}")

    story_relative = _story_relative_path(project)
    assets = AssetManager(assets_root, project.user_data_dir / "mods")
    errors = StoryValidator.validate_file(
        story_relative.as_posix(),
        data_root,
        assets_root,
        asset_manager=assets,
    )
    if errors:
        raise ValueError("Story validation failed:\n" + "\n".join(f"- {error}" for error in errors))

    project_values = deepcopy(project.values)
    project_values["story"] = story_relative.as_posix()
    project_values["paths"]["data"] = "data"
    project_values["paths"]["assets"] = "assets"
    project_json = (json.dumps(project_values, ensure_ascii=True, indent=2) + "\n").encode("utf-8")

    count = 0
    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        archive.comment = PROJECT_BUNDLE_COMMENT
        for namespace, root in (("data", data_root), ("assets", assets_root)):
            for path in sorted(root.rglob("*")):
                if path.is_symlink() or not path.is_file() or "__pycache__" in path.parts:
                    continue
                relative = path.relative_to(root)
                if namespace == "data" and relative.as_posix().casefold() == "project.json":
                    continue
                archive.write(path, (Path(namespace) / relative).as_posix())
                count += 1
        archive.writestr("data/project.json", project_json)
    return count + 1


def build_game(output_dir: Path | None = None) -> Path:
    executable = Path(sys.argv[0]).resolve()
    if executable.suffix.casefold() in {".py", ".pyc"} or not executable.is_file():
        raise RuntimeError("Run --build-game from a compiled engine distribution for this operating system.")
    if project_bundle_present():
        raise RuntimeError("A game executable cannot be used as the engine for another build.")

    runtime_dir = executable.parent
    project = ProjectConfig.load()
    game_name = _game_name(project.name)
    project_root = PATHS.project.resolve()
    target_dir = output_dir or project_root / "output"
    if not target_dir.is_absolute():
        target_dir = (project_root / target_dir).resolve()
    else:
        target_dir = target_dir.resolve()

    if target_dir == project_root or _is_within(target_dir, runtime_dir):
        raise ValueError("The output folder must not be the project root or inside the engine runtime folder.")
    if _is_within(target_dir, project.data_dir.resolve()) or _is_within(
        target_dir,
        project.assets_dir.resolve(),
    ):
        raise ValueError("The output folder must not be inside the project's data or assets folder.")
    if target_dir.exists():
        raise FileExistsError(
            f"Output folder already exists: {target_dir}. Move it or choose another folder with --output-dir."
        )

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".vn_game_build_", dir=target_dir.parent) as temporary:
        staging_root = Path(temporary) / "output"
        runtime_output = staging_root / "VN_Engine"
        shutil.copytree(runtime_dir, runtime_output)

        game_executable = runtime_output / f"{game_name}{'.exe' if os.name == 'nt' else ''}"
        if game_executable.exists():
            raise FileExistsError(f"An engine support file conflicts with the game executable name: {game_executable}")
        copied_engine = runtime_output / executable.name
        if not copied_engine.is_file():
            raise FileNotFoundError(f"The engine executable was not copied into the output folder: {copied_engine}")
        copied_engine.replace(game_executable)

        bundle_path = Path(temporary) / "project_resources.zip"
        resource_count = _write_resource_bundle(bundle_path, project)
        with game_executable.open("ab") as destination, bundle_path.open("rb") as bundle:
            shutil.copyfileobj(bundle, destination)

        if os.name == "nt":
            shortcut_path = staging_root / f"{game_name}.lnk"
            shortcut_target = target_dir / "VN_Engine" / game_executable.name
            relative_link_path = target_dir / shortcut_path.name
            create_shortcut(shortcut_target, shortcut_path, runtime_output, relative_link_path)
        else:
            shortcut_path = staging_root / f"{game_name} Shortcut"
            shortcut_path.symlink_to(Path("VN_Engine") / game_executable.name)
        staging_root.rename(target_dir)

    print(f"Embedded {resource_count:,} project files.")
    return target_dir
