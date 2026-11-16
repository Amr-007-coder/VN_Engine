# nuitka-project: --include-data-dir={MAIN_DIRECTORY}/engine/data=engine/data
# nuitka-project: --include-data-dir={MAIN_DIRECTORY}/engine/assets=engine/assets

import sys
import argparse
from pathlib import Path
import subprocess

from engine.assets import AssetManager
from engine.character_assets import CharacterAssetCatalog, CharacterAssetError
from engine.engine import Engine
from engine.loader import PATHS
from engine.project import ProjectConfig
from engine.validator import StoryValidator


def main():
    argument_parser = argparse.ArgumentParser(description="Small visual novel engine")
    argument_parser.add_argument(
        "--build-game",
        action="store_true",
        help="Create a project executable in output/ using this engine distribution",
    )
    argument_parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Choose the output folder for --build-game (default: project-root/output); "
            "platform exports write their ZIP or APK here"
        ),
    )
    argument_parser.add_argument(
        "--platform",
        choices=("windows", "linux", "macos", "web", "android"),
        help=(
            "Export a ZIP for this platform using its prebuilt template, or build an Android APK "
            "from the web template (use --fresh-android-web with source builds). Without --platform, "
            "--build-game makes the existing native build."
        ),
    )
    argument_parser.add_argument(
        "--templates-dir",
        type=Path,
        help="Folder containing the selected platform template (default: engine/project templates folder)",
    )
    argument_parser.add_argument(
        "--fresh-android-web",
        action="store_true",
        help="Build Android from current Pygbag sources instead of template-web.zip (source builds only).",
    )
    argument_parser.add_argument("--story", help="Override the YAML story filename from data/project.json")
    argument_parser.add_argument("--validate", action="store_true", help="Validate the story and exit")
    argument_parser.add_argument(
        "--list-character-assets",
        metavar="CHARACTER",
        nargs="?",
        const="*",
        help="List available character looks and expression PNGs",
    )
    argument_parser.add_argument(
        "--look",
        help="Limit --list-character-assets to this character look folder",
    )
    args = argument_parser.parse_args()
    if args.build_game:
        if args.fresh_android_web and args.platform != "android":
            argument_parser.error("--fresh-android-web can only be used with --platform android")
        if args.story is not None or args.validate or args.list_character_assets is not None or args.look is not None:
            argument_parser.error("--build-game cannot be combined with story validation or asset-listing options")
        if args.platform is None:
            if args.templates_dir is not None:
                argument_parser.error("--templates-dir requires --platform")
            from engine.game_builder import build_game

            output = build_game(args.output_dir)
            print(f"Game package created: {output}")
            return 0

        from export_pipeline import export_project, safe_project_name

        project = ProjectConfig.load()
        errors = StoryValidator.validate_file(project.story_file, project.data_dir, project.assets_dir)
        textbox_theme = project.theme.get("textbox", {})
        textbox_image = textbox_theme.get("background") if isinstance(textbox_theme, dict) else None
        if textbox_image and not AssetManager.find_asset_path(
            "image", textbox_image, project.assets_dir, PATHS.engine_assets
        ):
            errors.append(f"Project theme textbox.background references missing image asset {textbox_image!r}.")
        if errors:
            print("Story validation failed:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1

        project_root = PATHS.project.resolve()
        output_dir = args.output_dir or project_root / "output"
        if not output_dir.is_absolute():
            output_dir = project_root / output_dir
        template_candidates = (
            PATHS.engine / "templates",
            project_root / "templates",
            project_root / "engine" / "templates",
        )
        templates_dir = args.templates_dir or next(
            (
                candidate
                for candidate in template_candidates
                if candidate.is_dir() and any(candidate.glob("template-*.zip"))
            ),
            template_candidates[0],
        )
        if args.templates_dir is not None and not templates_dir.is_absolute():
            templates_dir = project_root / templates_dir
        extension = ".apk" if args.platform == "android" else ".zip"
        output_file = output_dir / f"{safe_project_name(project.name)}-{args.platform}{extension}"
        try:
            output = export_project(
                project_root,
                PATHS.project_data / "project.json",
                templates_dir,
                args.platform,
                output_file,
                fresh_android_web=args.fresh_android_web,
            )
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            print(f"Game export failed: {error}", file=sys.stderr)
            return 1
        print(f"Game export created: {output}")
        return 0
    if args.platform is not None or args.templates_dir is not None:
        argument_parser.error("--platform and --templates-dir can only be used with --build-game")
    if args.fresh_android_web:
        argument_parser.error("--fresh-android-web can only be used with --build-game --platform android")
    if args.output_dir is not None:
        argument_parser.error("--output-dir can only be used with --build-game")
    if args.look is not None and args.list_character_assets is None:
        argument_parser.error("--look can only be used with --list-character-assets")
    project = ProjectConfig.load()

    if args.list_character_assets is not None:
        character = None if args.list_character_assets == "*" else args.list_character_assets
        catalog = CharacterAssetCatalog(project.assets_dir, PATHS.engine_assets)
        try:
            print(catalog.format_inventory(character, args.look))
        except CharacterAssetError as error:
            print(error)
            return 1
        return 0

    story_file = args.story or project.story_file

    if args.validate:
        errors = StoryValidator.validate_file(story_file, project.data_dir, project.assets_dir)
        textbox_theme = project.theme.get("textbox", {})
        textbox_image = textbox_theme.get("background") if isinstance(textbox_theme, dict) else None
        if textbox_image and not AssetManager.find_asset_path(
            "image", textbox_image, project.assets_dir, PATHS.engine_assets
        ):
            errors.append(f"Project theme textbox.background references missing image asset {textbox_image!r}.")
        if errors:
            print("Story validation failed:")
            for error in errors:
                print(f"- {error}")
            return 1
        print(f"Story '{story_file}' is valid.")
        return 0

    Engine(story_file=story_file, project_config=project).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
