from copy import deepcopy

from engine.validator import StoryValidator


class StoryFlow:
    """Tracks the active dialogue, variables, and currently available choices."""

    def __init__(self, story_data: dict, project_assets_dir=None, fallback_assets_dir=None):
        StoryValidator.validate_or_raise(story_data, project_assets_dir, fallback_assets_dir)
        self.story_data = story_data
        self.dialogues = story_data["dialogues"]
        self.start_id = story_data["start"]
        self.variables = deepcopy(story_data.get("variables", {}))
        self.current_id = self.start_id
        self.choices_visible = False
        self.finished = False
        self._apply_assignments(self.current)

    @property
    def current(self) -> dict:
        return self.dialogues[self.current_id]

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

        target = self.current.get("next")
        if target is None:
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
        unknown_variables = set(variables) - set(self.variables)
        if unknown_variables:
            names = ", ".join(sorted(unknown_variables))
            raise ValueError(f"Save contains undeclared story variables: {names}.")

        self.current_id = dialogue_id
        self.variables.update(deepcopy(variables))
        self.choices_visible = bool(snapshot.get("choices_visible", False)) and bool(self.options)
        self.finished = bool(snapshot.get("finished", False))

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
