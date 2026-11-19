"""State-aware image skin helpers shared by built-in controls."""

import pygame


STATE_FALLBACKS = {
    "pressed": ("focus", "hover", "selected", "normal"),
    "disabled": ("normal",),
    "focus": ("selected", "hover", "normal"),
    "hover": ("normal",),
    "selected": ("focus", "hover", "normal"),
    "normal": (),
}


def alpha_surface(image):
    """Copy an image to a 32-bit alpha surface without needing a display mode."""
    result = pygame.Surface(image.get_size(), pygame.SRCALPHA, 32)
    result.blit(image, (0, 0))
    return result


def control_state(*, disabled=False, pressed=False, focused=False, hovered=False, selected=False):
    if disabled:
        return "disabled"
    if pressed:
        return "pressed"
    if focused:
        return "focus"
    if hovered:
        return "hover"
    if selected:
        return "selected"
    return "normal"


def state_skin(skin, state):
    skin = skin if isinstance(skin, dict) else {}
    states = skin.get("states", {})
    states = states if isinstance(states, dict) else {}
    entry = states.get(state)
    if entry is None:
        for fallback in STATE_FALLBACKS.get(state, ("normal",)):
            entry = states.get(fallback)
            if entry is not None:
                break
    if isinstance(entry, str):
        return {"image": entry}
    return entry if isinstance(entry, dict) else {}


def fit_surface(image, size, fit="stretch", nine_slice=None):
    """Fit a source image into a target size, optionally preserving nine-slice corners."""
    width, height = max(1, int(size[0])), max(1, int(size[1]))
    if image.get_size() == (width, height) and not nine_slice:
        return image
    if nine_slice:
        if isinstance(nine_slice, dict):
            left = int(nine_slice.get("left", 0))
            right = int(nine_slice.get("right", left))
            top = int(nine_slice.get("top", left))
            bottom = int(nine_slice.get("bottom", top))
        else:
            left = right = top = bottom = int(nine_slice)
        return _nine_slice(image, (width, height), left, top, right, bottom)
    if fit not in {"contain", "cover"}:
        return pygame.transform.smoothscale(image, (width, height))
    source_width, source_height = image.get_size()
    ratio = min(width / max(1, source_width), height / max(1, source_height))
    if fit == "cover":
        ratio = max(width / max(1, source_width), height / max(1, source_height))
    scaled_size = (max(1, round(source_width * ratio)), max(1, round(source_height * ratio)))
    scaled = pygame.transform.smoothscale(image, scaled_size)
    if fit == "contain":
        result = pygame.Surface((width, height), pygame.SRCALPHA)
        result.blit(scaled, scaled.get_rect(center=result.get_rect().center))
        return result
    crop = scaled.get_rect(center=(width // 2, height // 2))
    crop_rect = pygame.Rect(-crop.x, -crop.y, width, height)
    return scaled.subsurface(crop_rect).copy()


def _nine_slice(image, target_size, left, top, right, bottom):
    source_width, source_height = image.get_size()
    target_width, target_height = target_size
    left = max(0, min(left, source_width // 2, target_width // 2))
    right = max(0, min(right, source_width - left, target_width - left))
    top = max(0, min(top, source_height // 2, target_height // 2))
    bottom = max(0, min(bottom, source_height - top, target_height - top))
    sx = (0, left, source_width - right, source_width)
    sy = (0, top, source_height - bottom, source_height)
    dx = (0, left, target_width - right, target_width)
    dy = (0, top, target_height - bottom, target_height)
    result = pygame.Surface(target_size, pygame.SRCALPHA)
    for row in range(3):
        for column in range(3):
            source_rect = pygame.Rect(
                sx[column], sy[row], sx[column + 1] - sx[column], sy[row + 1] - sy[row]
            )
            dest_rect = pygame.Rect(
                dx[column], dy[row], dx[column + 1] - dx[column], dy[row + 1] - dy[row]
            )
            if source_rect.width <= 0 or source_rect.height <= 0 or dest_rect.width <= 0 or dest_rect.height <= 0:
                continue
            patch = image.subsurface(source_rect)
            if patch.get_size() != dest_rect.size:
                patch = pygame.transform.smoothscale(patch, dest_rect.size)
            result.blit(patch, dest_rect)
    return result


def draw_skin(target, rect, asset_manager, skin, state="normal", fallback_color=None):
    """Draw a state-specific skin and return whether an image was drawn."""
    skin = skin if isinstance(skin, dict) else {}
    state_config = state_skin(skin, state)
    image_name = state_config.get("image") or skin.get("image")
    if image_name and asset_manager is not None:
        try:
            # Keep skin rendering usable on off-screen Pygame Surfaces where
            # no display mode has been created yet.
            image = alpha_surface(asset_manager.load_image(image_name))
            rendered = fit_surface(image, rect.size, skin.get("fit", "stretch"), skin.get("nine_slice")).copy()
            opacity = state_config.get("opacity", skin.get("opacity", 1.0))
            try:
                rendered.set_alpha(round(255 * max(0.0, min(1.0, float(opacity)))))
            except (TypeError, ValueError):
                rendered.set_alpha(255)
            target.blit(rendered, rect)
            return True
        except (FileNotFoundError, TypeError, pygame.error, ValueError):
            pass
    color = state_config.get("color", fallback_color)
    if color is not None:
        opacity = state_config.get("opacity", skin.get("opacity", 1.0))
        try:
            opacity = max(0.0, min(1.0, float(opacity)))
        except (TypeError, ValueError):
            opacity = 1.0
        color = tuple(color)
        if len(color) == 3:
            color = (*color, round(255 * opacity))
        else:
            color = (*color[:3], round(color[3] * opacity))
        border = state_config.get("border_color", skin.get("border_color"))
        radius = max(0, int(state_config.get("radius", skin.get("radius", 0))))
        pygame.draw.rect(target, color, rect, border_radius=radius)
        if border:
            pygame.draw.rect(
                target,
                tuple(border),
                rect,
                width=max(1, int(state_config.get("border_width", skin.get("border_width", 1)))),
                border_radius=radius,
            )
        return True
    return False

