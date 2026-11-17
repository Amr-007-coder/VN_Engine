import re

from engine.assets import AssetManager
from engine.character_assets import CharacterAssetCatalog, CharacterAssetError
from engine.loader import PATHS, loader


class StoryValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


class StoryValidator:
    CONDITION_OPERATORS = {"==", "!=", "<", "<=", ">", ">=", "in", "not_in"}
    ASSIGNMENT_ACTIONS = {"set", "add", "subtract"}
    ROOT_KEYS = {"title", "start", "variables", "character_defaults", "dialogues"}
    DIALOGUE_KEYS = {
        "chapter", "speaker", "text", "active_character", "voice", "next", "options", "actions"
    }
    ACTION_FIELDS = {
        "set": {"type", "var", "value"},
        "add": {"type", "var", "value"},
        "subtract": {"type", "var", "value"},
        "input": {"type", "var", "prompt", "input_type"},
        "background": {"type", "image"},
        "clear_background": {"type"},
        "music": {"type", "track"},
        "stop_music": {"type"},
        "sound": {"type", "name"},
        "show_character": {"type", "name", "expression", "position", "look"},
        "hide_character": {"type", "name"},
        "clear_characters": {"type"},
        "animate_character": {"type", "name", "frames", "look", "position", "frame_duration", "loop"},
        "fade": {"type", "direction", "duration", "color"},
        "shake": {"type", "duration", "intensity"},
        "autosave": {"type"},
    }
    STORY_ACTIONS = {
        "background", "clear_background", "music", "stop_music", "sound",
        "show_character", "animate_character", "hide_character", "clear_characters",
        "fade", "shake", "autosave", "input", *ASSIGNMENT_ACTIONS,
    }
    CHARACTER_POSITIONS = {"far_left", "left", "center", "right", "far_right"}

    @classmethod
    def validate(cls, story: dict, project_assets_dir=None, fallback_assets_dir=None) -> list[str]:
        errors = []
        project_assets_dir = project_assets_dir or PATHS.project_assets
        fallback_assets_dir = fallback_assets_dir or PATHS.engine_assets
        if not isinstance(story, dict):
            return ["Story root must be a YAML mapping."]
        unknown_root_keys = set(story) - cls.ROOT_KEYS
        if unknown_root_keys:
            errors.append(f"Unknown story field(s): {', '.join(sorted(map(str, unknown_root_keys)))}.")
        character_assets = CharacterAssetCatalog(project_assets_dir, fallback_assets_dir)
        character_defaults = story.get("character_defaults", {})
        if not isinstance(character_defaults, dict):
            errors.append("'character_defaults' must be a mapping of character IDs to defaults.")
            character_defaults = {}
        cls._validate_character_defaults(character_defaults, character_assets, errors)

        variables = story.get("variables", {})
        if not isinstance(variables, dict):
            errors.append("'variables' must be a mapping of names to starting values.")
            variables = {}
        for name, value in variables.items():
            if not isinstance(name, str) or not name:
                errors.append("Variable names must be non-empty strings.")
            if not cls._is_scalar(value):
                errors.append(f"Starting value for variable {name!r} must be a string, number, boolean, or null.")

        start = story.get("start")
        dialogues = story.get("dialogues")
        if "title" in story and not isinstance(story["title"], str):
            errors.append("'title' must be a string.")
        if not isinstance(dialogues, dict) or not dialogues:
            errors.append("'dialogues' must be a non-empty mapping.")
            return errors
        if not isinstance(start, str) or start not in dialogues:
            errors.append(f"'start' must name an existing dialogue; got {start!r}.")

        targets = []
        for dialogue_id, dialogue in dialogues.items():
            where = f"dialogues.{dialogue_id}"
            if not isinstance(dialogue_id, str) or not dialogue_id:
                errors.append("Dialogue IDs must be non-empty strings.")
            if not isinstance(dialogue, dict):
                errors.append(f"{where} must be a mapping.")
                continue
            unknown_dialogue_keys = set(dialogue) - cls.DIALOGUE_KEYS
            if unknown_dialogue_keys:
                errors.append(
                    f"{where} has unknown field(s): {', '.join(sorted(map(str, unknown_dialogue_keys)))}."
                )
            if not isinstance(dialogue.get("speaker"), str):
                errors.append(f"{where}.speaker must be a string.")
            if not isinstance(dialogue.get("text"), str):
                errors.append(f"{where}.text must be a string.")
            else:
                cls._validate_inline_assets(
                    dialogue["text"], where, errors, project_assets_dir, fallback_assets_dir
                )
            if "chapter" in dialogue and not isinstance(dialogue["chapter"], str):
                errors.append(f"{where}.chapter must be a string.")
            if "voice" in dialogue:
                voice = dialogue["voice"]
                if not isinstance(voice, str) or not voice:
                    errors.append(f"{where}.voice must be a non-empty sound asset path.")
                else:
                    cls._validate_asset_name(
                        "sound", voice, where, errors, project_assets_dir, fallback_assets_dir
                    )
            if "active_character" in dialogue:
                active_character = dialogue["active_character"]
                if active_character is not None and (
                    not isinstance(active_character, str) or not active_character
                ):
                    errors.append(f"{where}.active_character must be a character ID or null.")

            next_target = dialogue.get("next")
            if next_target is not None:
                if not isinstance(next_target, str):
                    errors.append(f"{where}.next must be a dialogue ID.")
                else:
                    targets.append((where, next_target))

            options = dialogue.get("options", [])
            if not isinstance(options, list):
                errors.append(f"{where}.options must be a list.")
                options = []
            if options and next_target is not None:
                errors.append(f"{where} cannot define both 'next' and 'options'.")
            for index, option in enumerate(options):
                option_where = f"{where}.options[{index}]"
                if not isinstance(option, dict):
                    errors.append(f"{option_where} must be a mapping.")
                    continue
                if not isinstance(option.get("label"), str) or not option.get("label"):
                    errors.append(f"{option_where}.label must be a non-empty string.")
                target = option.get("target")
                if not isinstance(target, str):
                    errors.append(f"{option_where}.target must be a dialogue ID.")
                else:
                    targets.append((option_where, target))
                if "condition" in option:
                    cls._validate_condition(option["condition"], variables, option_where, errors)

            actions = dialogue.get("actions", [])
            if not isinstance(actions, list):
                errors.append(f"{where}.actions must be a list.")
                actions = []
            input_actions = [
                action for action in actions
                if isinstance(action, dict) and action.get("type") == "input"
            ]
            if len(input_actions) > 1:
                errors.append(f"{where} may contain at most one input action.")
            if input_actions and any(
                isinstance(action, dict) and action.get("type") == "autosave"
                for action in actions
            ):
                errors.append(f"{where} cannot combine an input action with autosave.")
            for index, action in enumerate(actions):
                cls._validate_action(
                    action,
                    variables,
                    f"{where}.actions[{index}]",
                    errors,
                    project_assets_dir,
                    fallback_assets_dir,
                    character_assets,
                    character_defaults,
                )

        for where, target in targets:
            if target not in dialogues:
                errors.append(f"{where} points to missing dialogue {target!r}.")
        return errors

    @classmethod
    def validate_or_raise(cls, story: dict, project_assets_dir=None, fallback_assets_dir=None):
        errors = cls.validate(story, project_assets_dir, fallback_assets_dir)
        if errors:
            raise StoryValidationError(errors)

    @classmethod
    def validate_file(cls, filename: str, data_dir=None, project_assets_dir=None) -> list[str]:
        try:
            story = loader.load_project_yaml(filename, data_dir)
        except (OSError, ValueError) as error:
            return [f"Could not read story {filename!r}: {error}"]
        return cls.validate(story, project_assets_dir)

    @classmethod
    def _validate_condition(cls, condition, variables, where, errors):
        if not isinstance(condition, dict) or not condition:
            errors.append(f"{where}.condition must be a mapping.")
            return
        if len(condition) == 1 and "all" in condition:
            children = condition["all"]
            if not isinstance(children, list) or not children:
                errors.append(f"{where}.condition.all must be a non-empty list.")
                return
            for child in children:
                cls._validate_condition(child, variables, where, errors)
            return
        if len(condition) == 1 and "any" in condition:
            children = condition["any"]
            if not isinstance(children, list) or not children:
                errors.append(f"{where}.condition.any must be a non-empty list.")
                return
            for child in children:
                cls._validate_condition(child, variables, where, errors)
            return
        if len(condition) == 1 and "not" in condition:
            cls._validate_condition(condition["not"], variables, where, errors)
            return

        name = condition.get("var")
        operator = condition.get("op")
        if not isinstance(name, str) or name not in variables:
            errors.append(f"{where}.condition references undeclared variable {name!r}.")
        if not isinstance(operator, str) or operator not in cls.CONDITION_OPERATORS:
            errors.append(f"{where}.condition.op must be one of {sorted(cls.CONDITION_OPERATORS)}.")
        elif "value" not in condition:
            errors.append(f"{where}.condition requires a 'value'.")
        elif isinstance(name, str) and name in variables:
            current = variables[name]
            expected = condition["value"]
            if operator in {"<", "<=", ">", ">="}:
                numeric_pair = (
                    isinstance(current, (int, float)) and not isinstance(current, bool)
                    and isinstance(expected, (int, float)) and not isinstance(expected, bool)
                )
                if not numeric_pair and not (
                    isinstance(current, str) and isinstance(expected, str)
                ):
                    errors.append(f"{where}.condition compares incompatible value types.")
            elif operator in {"in", "not_in"}:
                if not isinstance(expected, (str, list)):
                    errors.append(f"{where}.condition.value must be a string or list for {operator!r}.")
                elif isinstance(expected, str) and not isinstance(current, str):
                    errors.append(f"{where}.condition requires a string variable for {operator!r}.")

    @classmethod
    def _validate_action(
        cls,
        action,
        variables,
        where,
        errors,
        project_assets_dir,
        fallback_assets_dir,
        character_assets,
        character_defaults,
    ):
        if not isinstance(action, dict):
            errors.append(f"{where} must be a mapping.")
            return
        action_type = action.get("type")
        if not isinstance(action_type, str) or action_type not in cls.STORY_ACTIONS:
            errors.append(f"{where}.type must be one of {sorted(cls.STORY_ACTIONS)}.")
            return
        unknown_fields = set(action) - cls.ACTION_FIELDS[action_type]
        if unknown_fields:
            errors.append(f"{where} has unknown field(s): {', '.join(sorted(map(str, unknown_fields)))}.")

        if action_type in cls.ASSIGNMENT_ACTIONS:
            name = action.get("var")
            if not isinstance(name, str) or name not in variables:
                errors.append(f"{where} references undeclared variable {name!r}.")
            if "value" not in action or not cls._is_scalar(action.get("value")):
                errors.append(f"{where}.value must be a string, number, boolean, or null.")
            if action_type in {"add", "subtract"}:
                initial = variables.get(name) if isinstance(name, str) else None
                value = action.get("value")
                if not isinstance(initial, (int, float)) or isinstance(initial, bool):
                    errors.append(f"{where} uses {action_type!r} on a non-numeric variable.")
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    errors.append(f"{where}.value must be numeric for {action_type!r}.")
        elif action_type == "input":
            name = action.get("var")
            if not isinstance(name, str) or name not in variables:
                errors.append(f"{where} references undeclared variable {name!r}.")
            prompt = action.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                errors.append(f"{where}.prompt must be a non-empty string.")
            input_type = action.get("input_type", "text")
            if not isinstance(input_type, str) or input_type not in {"text", "integer"}:
                errors.append(f"{where}.input_type must be 'text' or 'integer'.")
            elif isinstance(name, str) and name in variables:
                initial = variables[name]
                if input_type == "text" and initial is not None and not isinstance(initial, str):
                    errors.append(f"{where} requires variable {name!r} to start as a string or null.")
                elif input_type == "integer" and initial is not None and (
                    not isinstance(initial, int) or isinstance(initial, bool)
                ):
                    errors.append(f"{where} requires variable {name!r} to start as an integer or null.")
        elif action_type in {"background", "music", "sound"}:
            field = {"background": "image", "music": "track", "sound": "name"}[action_type]
            if not isinstance(action.get(field), str) or not action[field]:
                errors.append(f"{where}.{field} must be a non-empty string.")
            elif action_type == "background":
                cls._validate_asset_name(
                    "image", action[field], where, errors, project_assets_dir, fallback_assets_dir
                )
            elif action_type == "sound":
                cls._validate_asset_name(
                    "sound", action[field], where, errors, project_assets_dir, fallback_assets_dir
                )
            elif not AssetManager.find_asset_path(
                "music", action[field], project_assets_dir, fallback_assets_dir
            ):
                errors.append(f"{where}.track points to missing music file {action[field]!r}.")
        elif action_type in {"show_character", "hide_character"}:
            name = action.get("name")
            if not isinstance(name, str) or not name:
                errors.append(f"{where}.name must be a character ID with available PNG assets.")
                return
            if action_type == "show_character":
                expression = action.get("expression")
                if not isinstance(expression, str) or not expression:
                    errors.append(f"{where}.expression must be a PNG filename without its extension.")
                    return
                position = action.get("position")
                if position is not None and (
                    not isinstance(position, str) or position not in cls.CHARACTER_POSITIONS
                ):
                    errors.append(f"{where}.position must be one of {sorted(cls.CHARACTER_POSITIONS)}.")
                look = action.get("look")
                if look is not None and (not isinstance(look, str) or not look):
                    errors.append(f"{where}.look must be a folder path such as 'Summer/Uniform/Normal'.")
                    return
                defaults = cls._character_default(character_defaults, name)
                selected_look = look or defaults.get("look")
                try:
                    character_assets.resolve(name, expression, selected_look)
                except CharacterAssetError as error:
                    errors.append(f"{where}: {error}")
            else:
                try:
                    character_assets.character_name(name)
                except CharacterAssetError as error:
                    errors.append(f"{where}: {error}")
        elif action_type == "animate_character":
            name = action.get("name")
            if not isinstance(name, str) or not name:
                errors.append(f"{where}.name must be a character ID with available PNG assets.")
                return
            frames = action.get("frames")
            if not isinstance(frames, list) or len(frames) < 2:
                errors.append(f"{where}.frames must be a list of at least two expression names.")
                return
            look = action.get("look")
            if look is not None and (not isinstance(look, str) or not look):
                errors.append(f"{where}.look must be a non-empty character look path.")
            position = action.get("position")
            if position is not None and (
                not isinstance(position, str) or position not in cls.CHARACTER_POSITIONS
            ):
                errors.append(f"{where}.position must be one of {sorted(cls.CHARACTER_POSITIONS)}.")
            frame_duration = action.get("frame_duration", 0.25)
            if (not isinstance(frame_duration, (int, float)) or isinstance(frame_duration, bool)
                    or not 0 < frame_duration <= 60):
                errors.append(f"{where}.frame_duration must be greater than 0 and at most 60 seconds.")
            if "loop" in action and not isinstance(action["loop"], bool):
                errors.append(f"{where}.loop must be true or false.")
            defaults = cls._character_default(character_defaults, name)
            selected_look = look or defaults.get("look")
            resolved_look = selected_look
            for index, expression in enumerate(frames):
                if not isinstance(expression, str) or not expression:
                    errors.append(f"{where}.frames[{index}] must be a PNG expression name.")
                    continue
                try:
                    resolved = character_assets.resolve(name, expression, resolved_look)
                    resolved_look = resolved["look"]
                except CharacterAssetError as error:
                    errors.append(f"{where}.frames[{index}]: {error}")
        elif action_type == "fade":
            direction = action.get("direction")
            if not isinstance(direction, str) or direction not in {"in", "out"}:
                errors.append(f"{where}.direction must be 'in' or 'out'.")
            duration = action.get("duration", 0.6)
            if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not 0 < duration <= 120:
                errors.append(f"{where}.duration must be a number greater than 0 and at most 120 seconds.")
            color = action.get("color", [0, 0, 0])
            if (not isinstance(color, list) or len(color) not in {3, 4}
                    or any(not isinstance(channel, int) or isinstance(channel, bool) or not 0 <= channel <= 255
                           for channel in color)):
                errors.append(f"{where}.color must be an RGB or RGBA list with values from 0 to 255.")
        elif action_type == "shake":
            duration = action.get("duration", 0.35)
            intensity = action.get("intensity", 8)
            if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not 0 < duration <= 120:
                errors.append(f"{where}.duration must be a number greater than 0 and at most 120 seconds.")
            if not isinstance(intensity, (int, float)) or isinstance(intensity, bool) or not 0 < intensity <= 100:
                errors.append(f"{where}.intensity must be greater than 0 and at most 100.")

    @classmethod
    def _validate_character_defaults(cls, defaults, character_assets, errors):
        for name, values in defaults.items():
            where = f"character_defaults.{name}"
            if not isinstance(name, str) or not name:
                errors.append("'character_defaults' keys must be non-empty character IDs.")
                continue
            if not isinstance(values, dict):
                errors.append(f"{where} must be a mapping.")
                continue
            try:
                character_assets.character_name(name)
            except CharacterAssetError as error:
                errors.append(f"{where}: {error}")
                continue
            look = values.get("look")
            if look is not None:
                if not isinstance(look, str) or not look:
                    errors.append(f"{where}.look must be a folder path such as 'Summer/Uniform/Normal'.")
                else:
                    try:
                        character_assets.resolve_look(name, look)
                    except CharacterAssetError as error:
                        errors.append(f"{where}.look: {error}")
            position = values.get("position")
            if position is not None and (
                not isinstance(position, str) or position not in cls.CHARACTER_POSITIONS
            ):
                errors.append(f"{where}.position must be one of {sorted(cls.CHARACTER_POSITIONS)}.")

    @staticmethod
    def _character_default(defaults, name):
        name_key = name.casefold()
        return next(
            (
                values
                for key, values in defaults.items()
                if isinstance(key, str) and key.casefold() == name_key and isinstance(values, dict)
            ),
            {},
        )

    @classmethod
    def _validate_inline_assets(cls, text, where, errors, project_assets_dir, fallback_assets_dir):
        for image_name in re.findall(r"%([^%]+)%", text):
            cls._validate_asset_name(
                "image", image_name, where, errors, project_assets_dir, fallback_assets_dir
            )
        section = "\u00a7"
        for sound_name in re.findall(f"{section}([^{section}]+){section}", text):
            cls._validate_asset_name(
                "sound", sound_name, where, errors, project_assets_dir, fallback_assets_dir
            )

    @staticmethod
    def _validate_asset_name(kind, name, where, errors, project_assets_dir, fallback_assets_dir):
        if not AssetManager.find_asset_path(kind, name, project_assets_dir, fallback_assets_dir):
            errors.append(f"{where} references missing {kind} asset {name!r}.")

    @staticmethod
    def _is_scalar(value):
        return value is None or isinstance(value, (str, int, float, bool))
