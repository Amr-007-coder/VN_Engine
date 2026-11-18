"""Deterministic, non-rendering story playthrough assertions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from engine.assets import AssetManager
from engine.loader import PATHS, loader
from engine.project import ProjectConfig
from engine.story import StoryFlow
from engine.validator import StoryValidator


UNLOCK_ACTIONS = {
    "unlock_cg": "cgs", "unlock_music": "music",
    "achievement": "achievements", "complete_route": "routes",
}


def _action_unlocks(dialogue):
    result = {name: set() for name in ("cgs", "music", "achievements", "routes")}
    for action in dialogue.get("actions", []):
        category = UNLOCK_ACTIONS.get(action.get("type"))
        if category and isinstance(action.get("id"), str):
            result[category].add(action["id"])
    return result


def run_playthrough(story: dict, scenario: dict, *, project_assets=None, fallback_assets=None, asset_manager=None, translation_tables=None):
    if not isinstance(scenario, dict):
        raise ValueError("Each playthrough scenario must be an object.")
    flow = StoryFlow(
        story,
        project_assets_dir=project_assets,
        fallback_assets_dir=fallback_assets,
        asset_manager=asset_manager,
        start_id=scenario.get("start"),
        initial_variables=scenario.get("variables", {}),
        locale=scenario.get("locale"),
        translation_tables=translation_tables,
    )
    choices = scenario.get("choices", [])
    if not isinstance(choices, list):
        raise ValueError("Scenario 'choices' must be a list.")
    choice_cursor = 0
    seen = set()
    inputs = scenario.get("inputs", {})
    if not isinstance(inputs, dict):
        raise ValueError("Scenario 'inputs' must be an object keyed by story variable.")
    unlocks = {name: set() for name in ("cgs", "music", "achievements", "routes")}
    max_steps = scenario.get("max_steps", 10000)
    if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
        raise ValueError("Scenario 'max_steps' must be a positive integer.")

    for _ in range(max_steps):
        dialogue = flow.dialogues[flow.current_id]
        for action in dialogue.get("actions", []):
            if action.get("type") != "input":
                continue
            variable = action["var"]
            if variable not in inputs:
                raise ValueError(f"Scenario needs an input value for variable {variable!r} at {flow.current_id!r}.")
            value = inputs[variable]
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(f"Input value for {variable!r} must be a scalar.")
            if action.get("input_type", "text") == "integer":
                if isinstance(value, bool):
                    raise ValueError(f"Integer input for {variable!r} cannot be a boolean.")
                try:
                    if isinstance(value, float) and not value.is_integer():
                        raise ValueError
                    value = int(value)
                except (TypeError, ValueError, OverflowError) as error:
                    raise ValueError(f"Input value for {variable!r} must be a whole number.") from error
            elif value is not None and not isinstance(value, str):
                value = str(value)
            flow.variables[variable] = value
        if flow.current_id not in seen:
            seen.add(flow.current_id)
            found = _action_unlocks(dialogue)
            for category, identifiers in found.items():
                unlocks[category].update(identifiers)
        if flow.finished:
            break
        options = flow.options
        if options:
            if choice_cursor >= len(choices):
                raise ValueError(f"Scenario needs a choice at dialogue {flow.current_id!r}.")
            step = choices[choice_cursor]
            choice_cursor += 1
            if isinstance(step, str):
                selector = step
            elif isinstance(step, dict):
                expected_dialogue = step.get("dialogue")
                if expected_dialogue is not None and expected_dialogue != flow.current_id:
                    raise ValueError(
                        f"Choice {choice_cursor} expected dialogue {expected_dialogue!r}, got {flow.current_id!r}."
                    )
                selector = step.get("label", step.get("target", step.get("index")))
            else:
                raise ValueError(f"Choice {choice_cursor} must be a label, target, index, or object.")
            if isinstance(selector, int) and not isinstance(selector, bool):
                selected = selector
            else:
                matches = [
                    index for index, option in enumerate(options)
                    if option.get("label") == selector or option.get("target") == selector
                ]
                if len(matches) != 1:
                    raise ValueError(
                        f"Choice {selector!r} at {flow.current_id!r} matched {len(matches)} available choices."
                    )
                selected = matches[0]
            flow.show_choices()
            flow.choose(selected)
        else:
            flow.advance()
    else:
        raise ValueError(f"Scenario exceeded max_steps={max_steps}; possible story loop.")

    if choice_cursor < len(choices):
        raise ValueError(f"Scenario supplied {len(choices) - choice_cursor} unused choice step(s).")
    expected = scenario.get("expect", {})
    if not isinstance(expected, dict):
        raise ValueError("Scenario 'expect' must be an object.")
    actual = {"dialogue": flow.current_id, "finished": flow.finished, "variables": flow.variables}
    expected_ending = expected.get("ending", expected.get("dialogue"))
    if expected_ending is not None and actual["dialogue"] != expected_ending:
        raise AssertionError(f"Expected final dialogue/ending {expected_ending!r}, got {actual['dialogue']!r}.")
    if "finished" in expected and actual["finished"] != expected["finished"]:
        raise AssertionError(f"Expected finished={expected['finished']!r}, got {actual['finished']!r}.")
    for name, value in expected.get("variables", {}).items():
        if flow.variables.get(name) != value:
            raise AssertionError(f"Expected variable {name!r}={value!r}, got {flow.variables.get(name)!r}.")
    for category, identifiers in expected.get("unlocks", {}).items():
        if category not in unlocks or not isinstance(identifiers, list):
            raise ValueError(f"Unknown or malformed unlock category {category!r}.")
        missing = set(identifiers) - unlocks[category]
        if missing:
            raise AssertionError(f"Expected {category} unlock(s) were not reached: {', '.join(sorted(missing))}.")
    return {**actual, "unlocks": {category: sorted(values) for category, values in unlocks.items()}, "visited": sorted(seen)}


def run_suite(project_dir: Path, suite_path: Path):
    project_dir = Path(project_dir).resolve()
    project_values_path = project_dir / "data" / "project.json"
    project_values = json.loads(project_values_path.read_text(encoding="utf-8"))
    project = ProjectConfig(project_values)
    paths = project.values["paths"]
    data_dir = Path(paths.get("data", "data"))
    assets_dir = Path(paths.get("assets", "assets"))
    if not data_dir.is_absolute():
        data_dir = project_dir / data_dir
    if not assets_dir.is_absolute():
        assets_dir = project_dir / assets_dir
    story = loader.load_project_yaml(project.values["story"], data_dir)
    tables = {}
    locales = story.get("localization", {}).get("locales", {})
    locale_dir = data_dir / "locales"
    for locale in locales:
        catalog_path = locale_dir / f"{locale}.json"
        if catalog_path.is_file():
            from engine.localization import load_catalog
            tables[locale] = load_catalog(catalog_path, locale)
    mod_directory = project_dir / "user_data" / "mods"
    manager = AssetManager(assets_dir, mod_directory)
    StoryValidator.validate_or_raise(story, assets_dir, PATHS.engine_assets, manager)
    suite = json.loads(Path(suite_path).read_text(encoding="utf-8"))
    scenarios = suite.get("scenarios") if isinstance(suite, dict) else None
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("Playthrough suite needs a non-empty 'scenarios' list.")
    results = []
    for index, scenario in enumerate(scenarios, 1):
        name = scenario.get("name", f"Scenario {index}") if isinstance(scenario, dict) else f"Scenario {index}"
        locale = scenario.get("locale") if isinstance(scenario, dict) else None
        try:
            outcome = run_playthrough(
                story, scenario, project_assets=assets_dir, fallback_assets=PATHS.engine_assets,
                asset_manager=manager, translation_tables=tables,
            )
            results.append({"name": name, "passed": True, "outcome": outcome})
        except Exception as error:
            results.append({"name": name, "passed": False, "error": str(error)})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run deterministic VN playthrough scenarios.")
    parser.add_argument("suite", type=Path, help="JSON playthrough suite")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help="Project containing data/project.json")
    args = parser.parse_args(argv)
    try:
        results = run_suite(args.project_dir, args.suite)
    except Exception as error:
        print(f"Playthrough suite could not run: {error}", file=sys.stderr)
        return 2
    for result in results:
        state = "PASS" if result["passed"] else "FAIL"
        detail = result.get("error", result.get("outcome", {}).get("dialogue", ""))
        print(f"{state}: {result['name']} — {detail}")
    print(f"{sum(item['passed'] for item in results)}/{len(results)} scenarios passed")
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
