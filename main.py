# nuitka-project: --include-data-dir={MAIN_DIRECTORY}/engine/data=engine/data
# nuitka-project: --include-data-dir={MAIN_DIRECTORY}/engine/assets=engine/assets

import argparse
from pathlib import Path

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
        help="Choose the output folder for --build-game (default: project-root/output)",
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
        if args.story is not None or args.validate or args.list_character_assets is not None or args.look is not None:
            argument_parser.error("--build-game cannot be combined with story validation or asset-listing options")
        from engine.game_builder import build_game

        output = build_game(args.output_dir)
        print(f"Game package created: {output}")
        return 0
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
