from difflib import get_close_matches
from pathlib import Path, PurePosixPath

from engine.embedded import EMBEDDED_ENABLED, prefix_for_root, resources_under


class CharacterAssetError(ValueError):
    """Raised when a character, look, or expression cannot be resolved."""


class CharacterAssetCatalog:
    """Discovers character looks and expression PNGs from the asset folders."""

    def __init__(self, project_assets=None, fallback_assets=None, mod_character_assets=None):
        self._characters = {}
        roots = []
        for root in (project_assets, fallback_assets):
            if root is not None:
                path = Path(root) / "characters"
                if path not in roots:
                    roots.append(path)

        for root_priority, character_root in enumerate(roots):
            resource_prefix = prefix_for_root(character_root.parent) if EMBEDDED_ENABLED else None
            if resource_prefix is not None:
                character_prefix = PurePosixPath(resource_prefix, "characters").as_posix()
                image_files = []
                for key in resources_under(character_prefix):
                    relative = PurePosixPath(key).relative_to(character_prefix)
                    if relative.suffix.casefold() == ".png":
                        image_files.append(relative)
            else:
                if not character_root.is_dir():
                    continue
                image_files = [
                    path.relative_to(character_root)
                    for path in sorted(
                        (path for path in character_root.rglob("*") if path.is_file() and path.suffix.casefold() == ".png"),
                        key=lambda path: path.as_posix().casefold(),
                    )
                ]

            for relative in image_files:
                if len(relative.parts) < 2:
                    continue
                character_name = relative.parts[0]
                look_name = "/".join(relative.parts[1:-1])
                expression_name = relative.stem
                character_key = character_name.casefold()
                look_key = look_name.casefold()
                expression_key = expression_name.casefold()

                character = self._characters.setdefault(
                    character_key, {"name": character_name, "looks": {}}
                )
                look = character["looks"].setdefault(
                    look_key, {"name": look_name, "expressions": {}}
                )
                expressions = look["expressions"].setdefault(expression_key, [])

                # Earlier roots have priority over later roots.
                if any(record["root_priority"] < root_priority for record in expressions):
                    continue
                if any(
                    record["root_priority"] == root_priority
                    and record["expression"] == expression_name
                    for record in expressions
                ):
                    continue
                expressions.append(
                    {
                        "expression": expression_name,
                        "asset": f"characters/{relative.as_posix()}",
                        "root_priority": root_priority,
                    }
                )

        # Packaged character sprites sit between project and engine assets in
        # lookup priority. A package can add characters or replace engine art,
        # while project files remain authoritative.
        for asset_name in mod_character_assets or ():
            relative = PurePosixPath(asset_name)
            if len(relative.parts) < 2 or relative.suffix.casefold() != ".png":
                continue
            character_name = relative.parts[0]
            look_name = "/".join(relative.parts[1:-1])
            expression_name = relative.stem
            character_key = character_name.casefold()
            look_key = look_name.casefold()
            expression_key = expression_name.casefold()
            character = self._characters.setdefault(character_key, {"name": character_name, "looks": {}})
            look = character["looks"].setdefault(look_key, {"name": look_name, "expressions": {}})
            expressions = look["expressions"].setdefault(expression_key, [])
            if any(record["root_priority"] < 0.5 for record in expressions):
                continue
            expressions[:] = [record for record in expressions if record["root_priority"] < 0.5]
            if any(
                record["root_priority"] == 0.5 and record["expression"] == expression_name
                for record in expressions
            ):
                continue
            expressions.append({
                "expression": expression_name,
                "asset": f"characters/{relative.as_posix()}",
                "root_priority": 0.5,
            })

    @property
    def character_names(self) -> list[str]:
        return sorted((character["name"] for character in self._characters.values()), key=str.casefold)

    def has_character(self, name: str) -> bool:
        return isinstance(name, str) and name.casefold() in self._characters

    def character_name(self, name: str) -> str:
        return self._get_character(name)["name"]

    def available_looks(self, name: str) -> list[str]:
        character = self._get_character(name)
        return sorted((look["name"] for look in character["looks"].values()), key=str.casefold)

    def resolve_look(self, name: str, look: str) -> str:
        return self._get_look(self._get_character(name), look)["name"]

    def resolve(self, name: str, expression: str, look: str | None = None) -> dict:
        character = self._get_character(name)
        if not isinstance(expression, str) or not expression:
            raise CharacterAssetError("Expression must be a non-empty PNG filename without its extension.")

        if look is not None:
            selected_look = self._get_look(character, look)
            image = self._expression_in_look(character, selected_look, expression)
            return self._resolved_asset(character, selected_look, image)

        matches = []
        for candidate_look in character["looks"].values():
            images = candidate_look["expressions"].get(expression.casefold(), [])
            exact_images = [image for image in images if image["expression"] == expression]
            images = exact_images or images
            if len(images) > 1:
                options = ", ".join(image["expression"] for image in images)
                raise CharacterAssetError(
                    f"Expression {expression!r} has case-colliding files in look "
                    f"{candidate_look['name']!r}: {options}. Use the exact filename casing."
                )
            if images:
                matches.append((candidate_look, images[0]))

        if len(matches) == 1:
            selected_look, image = matches[0]
            return self._resolved_asset(character, selected_look, image)
        if len(matches) > 1:
            looks = ", ".join(look_data["name"] or "<root>" for look_data, _ in matches)
            raise CharacterAssetError(
                f"Expression {expression!r} exists in several looks for {character['name']}: "
                f"{looks}. Set 'look' in character_defaults or this action."
            )

        expression_names = self._all_expression_names(character)
        suggestions = self._suggest(expression, expression_names)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise CharacterAssetError(
            f"No expression {expression!r} was found for {character['name']}.{hint} "
            "Use --list-character-assets to browse the available looks and expressions."
        )

    def format_inventory(self, name: str | None = None, look: str | None = None) -> str:
        if look is not None and name is None:
            raise CharacterAssetError("Pass a character name when filtering by look.")
        if not self._characters:
            return "No character PNG assets were found under the configured asset folders."
        if name is None:
            return "Available characters: " + ", ".join(self.character_names)

        character = self._get_character(name)
        if look is not None:
            selected_look = self._get_look(character, look)
            expressions = self._expression_names(selected_look)
            return (
                f"{character['name']} / {selected_look['name'] or '<root>'}\n"
                f"Expressions ({len(expressions)}): {', '.join(expressions)}"
            )

        lines = [f"{character['name']} looks and expressions:"]
        for look_data in sorted(character["looks"].values(), key=lambda item: item["name"].casefold()):
            expressions = self._expression_names(look_data)
            label = look_data["name"] or "<root>"
            lines.append(f"  {label} ({len(expressions)}): {', '.join(expressions)}")
        return "\n".join(lines)

    def _get_character(self, name: str):
        if isinstance(name, str) and name.casefold() in self._characters:
            return self._characters[name.casefold()]
        available = self.character_names
        suggestions = self._suggest(name, available) if isinstance(name, str) else []
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        names = ", ".join(available) or "none found"
        raise CharacterAssetError(
            f"Unknown character {name!r}.{hint} Available character assets: {names}."
        )

    def _get_look(self, character: dict, requested_look: str):
        if not isinstance(requested_look, str) or not requested_look:
            raise CharacterAssetError("Look must be a non-empty folder path, such as 'Summer/Uniform/Normal'.")
        normalized = requested_look.replace("\\", "/")
        parts = normalized.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise CharacterAssetError(f"Invalid look path {requested_look!r}.")
        look = character["looks"].get(normalized.casefold())
        if look is not None:
            return look

        available = self.available_looks(character["name"])
        suggestions = self._suggest(normalized, available)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        names = ", ".join(available) or "none found"
        raise CharacterAssetError(
            f"Unknown look {requested_look!r} for {character['name']}.{hint} Available looks: {names}."
        )

    def _expression_in_look(self, character: dict, look: dict, expression: str):
        images = look["expressions"].get(expression.casefold(), [])
        exact_images = [image for image in images if image["expression"] == expression]
        images = exact_images or images
        if len(images) == 1:
            return images[0]
        if len(images) > 1:
            names = ", ".join(image["expression"] for image in images)
            raise CharacterAssetError(
                f"Expression {expression!r} is ambiguous in look {look['name']!r}; "
                f"use exact filename casing: {names}."
            )

        available = self._expression_names(look)
        suggestions = self._suggest(expression, available)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise CharacterAssetError(
            f"No expression {expression!r} was found for {character['name']} in "
            f"look {look['name']!r}.{hint} Available expressions: {', '.join(available)}."
        )

    @staticmethod
    def _resolved_asset(character: dict, look: dict, image: dict) -> dict:
        return {
            "name": character["name"],
            "look": look["name"],
            "expression": image["expression"],
            "asset": image["asset"],
        }

    @staticmethod
    def _expression_names(look: dict) -> list[str]:
        names = [
            image["expression"]
            for images in look["expressions"].values()
            for image in images
        ]
        return sorted(set(names), key=str.casefold)

    @classmethod
    def _all_expression_names(cls, character: dict) -> list[str]:
        names = {
            name
            for look in character["looks"].values()
            for name in cls._expression_names(look)
        }
        return sorted(names, key=str.casefold)

    @staticmethod
    def _suggest(value: str, candidates: list[str]) -> list[str]:
        if not value or not candidates:
            return []
        by_folded_name = {candidate.casefold(): candidate for candidate in candidates}
        matches = get_close_matches(
            value.casefold(), list(by_folded_name), n=5, cutoff=0.45
        )
        return [by_folded_name[match] for match in matches]
