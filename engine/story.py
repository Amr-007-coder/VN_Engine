from copy import deepcopy

from engine.validator import StoryValidator


class StoryFlow:
    """Tracks the active dialogue, variables, and currently available choices."""

    def __init__(
        self,
        story_data: dict,
        project_assets_dir=None,
        fallback_assets_dir=None,
        start_id: str | None = None,
        initial_variables: dict | None = None,
        locale: str | None = None,
        fallback_locale: str | None = None,
        asset_manager=None,
        translation_tables: dict | None = None,
    ):
        StoryValidator.validate_or_raise(
            story_data, project_assets_dir, fallback_assets_dir, asset_manager
        )
        self.story_data = story_data
        self.dialogues = story_data["dialogues"]
        localization = story_data.get("localization", {})
        self.fallback_locale = fallback_locale or localization.get("default_locale", "en")
        available_locales = localization.get("locales", {self.fallback_locale: self.fallback_locale})
        self.locale = locale if locale in available_locales else self.fallback_locale
        self.translation_tables = translation_tables or {}
        self.start_id = story_data["start"]
        if start_id is not None:
            if not isinstance(start_id, str) or start_id not in self.dialogues:
                raise ValueError(f"Test start refers to missing dialogue {start_id!r}.")
            self.start_id = start_id
        self.variables = deepcopy(story_data.get("variables", {}))
        if initial_variables is not None:
            if not isinstance(initial_variables, dict):
                raise ValueError("Initial story variables must be an object.")
            for name, value in initial_variables.items():
                if name not in self.variables:
                    raise ValueError(f"Initial story variables contain undeclared variable {name!r}.")
                if value is not None and not isinstance(value, (str, int, float, bool)):
                    raise ValueError(f"Initial story variable {name!r} must be a scalar value.")
                current = self.variables[name]
                if current is not None and value is not None:
                    numeric_pair = (
                        isinstance(current, (int, float)) and not isinstance(current, bool)
                        and isinstance(value, (int, float)) and not isinstance(value, bool)
                    )
                    if type(current) is not type(value) and not numeric_pair:
                        raise ValueError(
                            f"Initial story variable {name!r} must match its declared type."
                        )
            self.variables.update(deepcopy(initial_variables))
        self.current_id = self.start_id
        self.choices_visible = False
        self.finished = False
        self.call_stack = []
        self._apply_assignments(self.current)

    @property
    def current(self) -> dict:
        dialogue = dict(self.dialogues[self.current_id])
        dialogue["text"] = self._localized_value(
            dialogue.get("text", ""), f"dialogues.{self.current_id}.text"
        )
        dialogue["speaker_name"] = self._localized_value(
            dialogue.get("speaker_name", dialogue.get("speaker", "")),
            f"dialogues.{self.current_id}.speaker_name",
        )
        options = dialogue.get("options", [])
        if isinstance(options, list):
            dialogue["options"] = [
                {
                    **option,
                    "label": self._localized_value(
                        option.get("label", ""),
                        f"dialogues.{self.current_id}.options.{index}.label",
                    ),
                }
                if isinstance(option, dict) else option
                for index, option in enumerate(options)
            ]
        return dialogue

    def _localized_value(self, value, key=None):
        table = self.translation_tables.get(self.locale, {})
        external = table.get("strings", {}).get(key) if key else None
        if isinstance(value, dict):
            selected = value.get(self.locale)
            if isinstance(selected, str) and selected:
                return selected
        if isinstance(external, str) and external:
            return external
        if isinstance(value, str):
            return value
        if not isinstance(value, dict):
            return ""
        selected = value.get(self.fallback_locale)
        if not isinstance(selected, str) or not selected:
            selected = next((item for item in value.values() if isinstance(item, str) and item), "")
        return selected

    @property
    def options(self) -> list[dict]:
        return [
            option for option in self.current.get("options", [])
            if self._condition_is_true(option.get("condition"))
        ]

    def show_choices(self):
        if self.options and not self.finished:
            self.choices_visible = True

    def advance(self):
        if self.finished:
            return
        if self.options:
            self.show_choices()
            return

        if self.current.get("return") is True:
            if self.call_stack:
                self._enter(self.call_stack.pop())
            else:
                self.finished = True
            return

        call_target = self.current.get("call")
        if call_target is not None:
            self.call_stack.append(self.current["next"])
            self._enter(call_target)
            return

        target = self.current.get("next")
        if target is None:
            if self.call_stack:
                self._enter(self.call_stack.pop())
            else:
                self.finished = True
            return
        self._enter(target)

    def choose(self, option_index: int):
        if not self.choices_visible:
            raise RuntimeError("Choices are not currently visible.")
        available_options = self.options
        if option_index < 0 or option_index >= len(available_options):
            raise IndexError("Choice index is out of range.")
        self._enter(available_options[option_index]["target"])

    def snapshot(self) -> dict:
        return {
            "dialogue": self.current_id,
            "variables": deepcopy(self.variables),
            "choices_visible": self.choices_visible,
            "finished": self.finished,
            "call_stack": list(self.call_stack),
        }

    def restore(self, snapshot: dict):
        if not isinstance(snapshot, dict):
            raise ValueError("Saved story state must be an object.")
        dialogue_id = snapshot.get("dialogue")
        if not isinstance(dialogue_id, str) or dialogue_id not in self.dialogues:
            raise ValueError(f"Save refers to missing dialogue {dialogue_id!r}.")
        variables = snapshot.get("variables", {})
        if not isinstance(variables, dict):
            raise ValueError("Saved story variables must be an object.")
        call_stack = snapshot.get("call_stack", [])
        if not isinstance(call_stack, list) or any(
            not isinstance(target, str) or target not in self.dialogues
            for target in call_stack
        ):
            raise ValueError("Saved story call stack must contain existing dialogue IDs.")
        unknown_variables = set(variables) - set(self.variables)
        if unknown_variables:
            names = ", ".join(sorted(unknown_variables))
            raise ValueError(f"Save contains undeclared story variables: {names}.")

        self.current_id = dialogue_id
        self.variables.update(deepcopy(variables))
        self.choices_visible = bool(snapshot.get("choices_visible", False)) and bool(self.options)
        self.finished = bool(snapshot.get("finished", False))
        self.call_stack = list(call_stack)

    def _enter(self, dialogue_id: str):
        self.current_id = dialogue_id
        self.choices_visible = False
        self._apply_assignments(self.current)

    def _apply_assignments(self, dialogue: dict):
        for action in dialogue.get("actions", []):
            action_type = action["type"]
            if action_type not in {"set", "add", "subtract"}:
                continue
            name = action["var"]
            value = action["value"]
            if action_type == "set":
                self.variables[name] = value
            else:
                try:
                    if action_type == "add":
                        self.variables[name] += value
                    else:
                        self.variables[name] -= value
                except TypeError as error:
                    raise ValueError(
                        f"Cannot apply {action_type!r} to story variable {name!r}."
                    ) from error

    def _condition_is_true(self, condition) -> bool:
        if condition is None:
            return True
        if "all" in condition:
            return all(self._condition_is_true(child) for child in condition["all"])
        if "any" in condition:
            return any(self._condition_is_true(child) for child in condition["any"])
        if "not" in condition:
            return not self._condition_is_true(condition["not"])

        current = self.variables.get(condition["var"])
        expected = condition["value"]
        operator = condition["op"]
        comparisons = {
            "==": lambda: current == expected,
            "!=": lambda: current != expected,
            "<": lambda: current < expected,
            "<=": lambda: current <= expected,
            ">": lambda: current > expected,
            ">=": lambda: current >= expected,
            "in": lambda: current in expected,
            "not_in": lambda: current not in expected,
        }
        try:
            return bool(comparisons[operator]())
        except (KeyError, TypeError):
            return False
