import pygame

from engine.character_assets import CharacterAssetCatalog


class CharacterLayer:
    """Tracks and draws character sprites above backgrounds and below dialogue UI."""

    POSITIONS = {"far_left", "left", "center", "right", "far_right"}
    POSITION_X = {
        "far_left": ("left", 0.02),
        "left": ("left", 0.08),
        "center": ("center", 0.5),
        "right": ("right", 0.08),
        "far_right": ("right", 0.02),
    }
    DIM_COLOR = (150, 150, 165)

    def __init__(self, assets, defaults=None, scale_settings=None):
        self.assets = assets
        self.catalog = CharacterAssetCatalog(assets.project_assets, assets.fallback_assets)
        self.defaults = defaults or {}
        self.scale_percentages = {
            name.casefold(): settings.get("scale", 100)
            for name, settings in (scale_settings or {}).items()
        }
        self.characters = {}
        self._surface_cache = {}

    def show(
        self,
        name: str,
        expression: str,
        position: str | None = None,
        look: str | None = None,
    ):
        previous_name = self._existing_name(name)
        previous = self.characters.get(previous_name, {})
        defaults = self._defaults_for(name)
        selected_look = look or previous.get("look") or defaults.get("look")
        resolved = self.catalog.resolve(name, expression, selected_look)
        if position is not None and position not in self.POSITIONS:
            raise ValueError(f"Character position must be one of {sorted(self.POSITIONS)}.")

        position = position or previous.get("position") or defaults.get("position", "center")
        if previous.get("look") == resolved["look"] and previous.get("expression") == resolved["expression"]:
            source = previous["image"]
        else:
            source = self.assets.load_image(resolved["asset"], cache=False)
            self._discard_cached_sprites(resolved["name"])
        self.characters[resolved["name"]] = {
            "look": resolved["look"],
            "expression": resolved["expression"],
            "position": position,
            "image": source,
            "animation": None,
        }

    def animate(
        self,
        name: str,
        expressions: list[str],
        position: str | None = None,
        look: str | None = None,
        frame_duration: float = 0.25,
        loop: bool = True,
    ):
        previous_name = self._existing_name(name)
        previous = self.characters.get(previous_name, {})
        defaults = self._defaults_for(name)
        selected_look = look or previous.get("look") or defaults.get("look")
        if not expressions:
            raise ValueError("Character animation needs at least one expression frame.")
        resolved_frames = [self.catalog.resolve(name, expressions[0], selected_look)]
        selected_look = resolved_frames[0]["look"]
        resolved_frames.extend(
            self.catalog.resolve(name, expression, selected_look)
            for expression in expressions[1:]
        )
        if position is not None and position not in self.POSITIONS:
            raise ValueError(f"Character position must be one of {sorted(self.POSITIONS)}.")

        first = resolved_frames[0]
        position = position or previous.get("position") or defaults.get("position", "center")
        images = [self.assets.load_image(frame["asset"], cache=False) for frame in resolved_frames]
        self.characters[first["name"]] = {
            "look": first["look"],
            "expression": first["expression"],
            "position": position,
            "image": images[0],
            "animation": {
                "expressions": [frame["expression"] for frame in resolved_frames],
                "images": images,
                "frame_duration": float(frame_duration),
                "loop": bool(loop),
                "started_at": pygame.time.get_ticks(),
            },
        }
        self._discard_cached_sprites(first["name"])

    def hide(self, name: str):
        existing_name = self._existing_name(name)
        if existing_name is not None:
            self.characters.pop(existing_name, None)
            self._discard_cached_sprites(existing_name)

    def clear(self):
        self.characters.clear()
        self._surface_cache.clear()

    def snapshot(self) -> dict:
        for name, character in self.characters.items():
            self._select_animation_frame(name, character)
        return {
            name: {
                "look": character["look"],
                "expression": character["expression"],
                "position": character["position"],
                "animation": (
                    {
                        "frames": list(character["animation"]["expressions"]),
                        "frame_duration": character["animation"]["frame_duration"],
                        "loop": character["animation"]["loop"],
                    }
                    if character.get("animation") else None
                ),
            }
            for name, character in self.characters.items()
        }

    def restore(self, characters):
        if not isinstance(characters, dict):
            raise ValueError("Saved character layer must be a mapping.")

        restored = {}
        for name, character in characters.items():
            if not isinstance(character, dict):
                raise ValueError(f"Saved character {name!r} must be a mapping.")
            expression = character.get("expression")
            look = character.get("look") or self._defaults_for(name).get("look")
            position = character.get("position")
            if not isinstance(expression, str) or not isinstance(position, str):
                raise ValueError(f"Saved character {name!r} needs an expression and position.")
            if position not in self.POSITIONS:
                raise ValueError(f"Saved character {name!r} has an invalid position.")
            resolved = self.catalog.resolve(name, expression, look)
            restored[resolved["name"]] = {
                "look": resolved["look"],
                "expression": resolved["expression"],
                "position": position,
                "image": self.assets.load_image(resolved["asset"], cache=False),
                "animation": None,
            }
        self.characters = restored
        self._surface_cache.clear()
        for name, character in characters.items():
            animation = character.get("animation") if isinstance(character, dict) else None
            if isinstance(animation, dict):
                self.animate(
                    name,
                    animation.get("frames", []),
                    position=character.get("position"),
                    look=character.get("look"),
                    frame_duration=animation.get("frame_duration", 0.25),
                    loop=animation.get("loop", True),
                )

    def render(self, surface: pygame.Surface, active_character: str | None = None):
        if not self.characters:
            return

        active_key = active_character.casefold() if isinstance(active_character, str) else None
        ordered = sorted(
            self.characters.items(),
            key=lambda item: item[0].casefold() == active_key,
        )
        for name, character in ordered:
            self._select_animation_frame(name, character)
            is_active = name.casefold() == active_key
            sprite = self._prepared_sprite(name, character, surface.get_size(), is_active)
            x = self._position_x(character["position"], surface.get_width(), sprite.get_width())
            y = surface.get_height() - sprite.get_height()
            surface.blit(sprite, (x, y))

    def _select_animation_frame(self, name, character):
        animation = character.get("animation")
        if not animation:
            return
        duration_ms = max(1, round(animation["frame_duration"] * 1000))
        frame = (pygame.time.get_ticks() - animation["started_at"]) // duration_ms
        if animation["loop"]:
            frame %= len(animation["expressions"])
        else:
            frame = min(frame, len(animation["expressions"]) - 1)
        frame = int(frame)
        if character["expression"] != animation["expressions"][frame]:
            character["expression"] = animation["expressions"][frame]
            character["image"] = animation["images"][frame]
            self._discard_cached_sprites(name)

    def _prepared_sprite(self, name: str, character: dict, screen_size: tuple[int, int], active: bool):
        expression = character["expression"]
        scale_percentage = self.scale_percentages.get(name.casefold(), 100)
        key = (name, character["look"], expression, screen_size, active, scale_percentage)
        if key in self._surface_cache:
            return self._surface_cache[key]

        source = character["image"]
        screen_width, screen_height = screen_size
        scale = (
            min(screen_height / source.get_height(), (screen_width * 0.45) / source.get_width())
            * scale_percentage
            / 100
        )
        sprite_size = (
            max(1, round(source.get_width() * scale)),
            max(1, round(source.get_height() * scale)),
        )
        sprite = pygame.transform.smoothscale(source, sprite_size)
        if not active:
            sprite = sprite.copy()
            sprite.fill((*self.DIM_COLOR, 255), special_flags=pygame.BLEND_RGBA_MULT)
        self._surface_cache[key] = sprite
        return sprite

    @classmethod
    def _position_x(cls, position: str, screen_width: int, sprite_width: int) -> int:
        side, margin = cls.POSITION_X[position]
        if side == "center":
            return (screen_width - sprite_width) // 2
        if side == "left":
            return round(screen_width * margin)
        return screen_width - round(screen_width * margin) - sprite_width

    def _existing_name(self, name):
        folded = name.casefold() if isinstance(name, str) else None
        return next((existing for existing in self.characters if existing.casefold() == folded), None)

    def _defaults_for(self, name):
        folded = name.casefold() if isinstance(name, str) else None
        return next(
            (values for key, values in self.defaults.items() if isinstance(key, str) and key.casefold() == folded),
            {},
        )

    def _discard_cached_sprites(self, name: str):
        for key in [key for key in self._surface_cache if key[0] == name]:
            del self._surface_cache[key]
