import pygame

from engine.config import COLORS, FONTS
from engine.layout import component_layout, layout_children, resolve_rect, safe_area_rect
from engine.parser import parse
from engine.skin import control_state, draw_skin
from engine.skin import fit_surface
from engine.style import style_component
from engine.ui_scale import get_ui_scale, ui_size


def dialogue_textbox_rect(layouts, viewport, controls_visible=False):
    """Resolve the dialogue box using the same control clearance as gameplay."""
    bounds = safe_area_rect(layouts, viewport)
    spec = component_layout(layouts, "dialogue", "textbox", viewport)
    if controls_visible and "bottom" in spec and not isinstance(spec.get("bottom"), str):
        spec = dict(spec)
        spec["bottom"] = max(38, spec.get("bottom", 0))
    elif controls_visible and "bottom" not in spec and "y" not in spec:
        spec = dict(spec)
        spec["bottom"] = 38
    return pygame.Rect(resolve_rect(spec, bounds, scale=get_ui_scale()))


def layout_dialogue_controls(textbox_rect, viewport, component, layouts, config, label_resolver=None, can_go_back=True):
    """Return the standard dialogue control labels and rectangles."""
    config = config if isinstance(config, dict) else {}
    component = component if isinstance(component, dict) else {}
    layouts = layouts if isinstance(layouts, dict) else {}
    names = ("back", "auto", "history", "quick_save", "quick_load", "mute")
    visible = [
        (name, button)
        for name in names
        if isinstance((button := config.get(name)), dict) and button.get("visible", True)
    ]
    if not visible:
        return []
    label_resolver = label_resolver or (lambda value: value)
    scale = get_ui_scale()
    gap = max(0, ui_size(component.get("gap", 8)))
    height = max(1, ui_size(component.get("height", 22)))
    available_width = max(1, textbox_rect.width - ui_size(24))
    max_button_width = max(1, (available_width - gap * (len(visible) - 1)) // len(visible))
    min_width = max(1, ui_size(component.get("min_width", 58)))
    padding = max(0, ui_size(component.get("padding", 14)))
    labels = [(name, label_resolver(button.get("label", name))) for name, button in visible]
    widths = [
        min(max_button_width, max(min_width, FONTS.dialogue_controls.size(label)[0] + padding))
        for _name, label in labels
    ]
    if sum(widths) + gap * (len(widths) - 1) > available_width:
        widths = [max_button_width] * len(visible)
    spec = component_layout(layouts, "dialogue", "controls", viewport)
    parent_bounds = (textbox_rect.left, textbox_rect.bottom, textbox_rect.width, height + ui_size(16))
    design_widths = [max(1, round(width / max(0.1, scale))) for width in widths]
    rects = layout_children(spec, parent_bounds, len(visible), item_sizes=design_widths, scale=scale)
    return [
        (name, label, pygame.Rect(rect), name != "back" or can_go_back)
        for (name, label), rect in zip(labels, rects)
    ]


def draw_dialogue_control(surface, rect, label, state, enabled, component, button_config, skin_base, assets, theme_colors, style_values=None):
    """Draw a dialogue control using the runtime skin, state, and text rules."""
    button_config = button_config if isinstance(button_config, dict) else {}
    skin = dict(skin_base) if isinstance(skin_base, dict) else {}
    states = dict(skin.get("states", {}))
    states.update(component.get("states", {}))
    skin["states"] = states
    per_button_skin = button_config.get("skin")
    if isinstance(per_button_skin, str):
        configured_skins = (style_values or {}).get("skins", {})
        skin = configured_skins.get(per_button_skin, skin)
    skin["fit"] = component.get("fit", skin.get("fit", "stretch"))
    skin["nine_slice"] = component.get("nine_slice", skin.get("nine_slice"))
    skin["radius"] = component.get("radius", skin.get("radius", 4))
    skin["border_width"] = component.get("border_width", skin.get("border_width", 0))
    skin["opacity"] = component.get("opacity", skin.get("opacity", 1.0))
    fallback = None
    if state in {"hover", "focus"}:
        fallback = component.get("states", {}).get(state, {}).get("color")
    elif state == "selected":
        fallback = component.get("states", {}).get("selected", {}).get("color")
    elif state == "disabled":
        fallback = component.get("states", {}).get("disabled", {}).get("color")
    draw_skin(surface, rect, assets, skin, state, fallback)
    if not enabled:
        text_color = component.get("disabled_color", (130, 130, 138))
    elif state in {"hover", "focus", "selected", "pressed"}:
        text_color = component.get("focus_color", theme_colors.get("accent", COLORS.text_highlight))
    else:
        text_color = component.get("text_color", COLORS.text)
    text = FONTS.dialogue_controls.render(label, True, text_color)
    previous_clip = surface.get_clip()
    surface.set_clip(rect)
    alignment = component.get("label_alignment", button_config.get("label_alignment", "center"))
    if alignment == "left":
        text_rect = text.get_rect(midleft=(rect.left + ui_size(6), rect.centery))
    elif alignment == "right":
        text_rect = text.get_rect(midright=(rect.right - ui_size(6), rect.centery))
    else:
        text_rect = text.get_rect(center=rect.center)
    surface.blit(text, text_rect)
    surface.set_clip(previous_clip)


def draw_style_panel(surface, rect, style_values, component_name="menu", high_contrast=False):
    """Draw the common themed panel used by menus, history, and overlays."""
    component = style_component(style_values, component_name)
    if component_name == "menu":
        fill = component.get("panel_color", (8, 8, 16, 210))
        border = component.get("panel_border_color", (95, 84, 112))
        border_width = component.get("panel_border_width", 1)
        radius = component.get("panel_radius", 10)
    else:
        fill = component.get("panel_color", (8, 8, 16, 210))
        border = component.get("border_color", (95, 84, 112))
        border_width = component.get("border_width", 1)
        radius = component.get("radius", 10)
    if high_contrast:
        fill, border, border_width = (0, 0, 0, 255), (255, 255, 255), max(2, border_width)
    else:
        fill = tuple(fill)
        opacity = max(0.0, min(1.0, float(component.get("opacity", 1.0))))
        fill = (*fill[:3], round((fill[3] if len(fill) > 3 else 255) * opacity))
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    panel.fill(fill)
    surface.blit(panel, rect)
    if border and border_width:
        pygame.draw.rect(surface, tuple(border), rect, width=max(1, ui_size(border_width)), border_radius=ui_size(radius))


def render_history_panel(surface, panel_rect, history, scroll, history_style, heading_font, body_font, footer_font,
                         heading_text="Dialogue History", footer_text="H or Esc: close   Up/Down or mouse wheel: scroll",
                         high_contrast=False):
    """Render the history overlay and return its clamped scroll offset."""
    shade = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    shade.fill(tuple(history_style.get("scrim_color", (0, 0, 0, 190))))
    surface.blit(shade, (0, 0))
    panel_color = (0, 0, 0, 255) if high_contrast else history_style.get("panel_color", (24, 25, 38))
    if not high_contrast:
        opacity = max(0.0, min(1.0, float(history_style.get("opacity", 1.0))))
        panel_color = tuple(panel_color)
        panel_color = (*panel_color[:3], round((panel_color[3] if len(panel_color) > 3 else 255) * opacity))
    border_color = (255, 255, 255) if high_contrast else history_style.get("border_color", (112, 86, 101))
    radius = ui_size(history_style.get("radius", 10))
    pygame.draw.rect(surface, tuple(panel_color), panel_rect, border_radius=radius)
    pygame.draw.rect(surface, tuple(border_color), panel_rect,
                     width=max(ui_size(history_style.get("border_width", 2)), 2 if high_contrast else 1),
                     border_radius=radius)
    padding = ui_size(history_style.get("padding", 24))
    heading_color = (255, 255, 255) if high_contrast else history_style.get("heading_color", COLORS.text_highlight)
    heading = heading_font.render(heading_text, True, heading_color)
    surface.blit(heading, (panel_rect.left + padding, panel_rect.top + ui_size(history_style.get("heading_top", 18))))
    footer_color = (255, 255, 255) if high_contrast else history_style.get("footer_color", COLORS.text)
    footer = footer_font.render(footer_text, True, footer_color)
    surface.blit(footer, (panel_rect.left + padding, panel_rect.bottom - ui_size(history_style.get("footer_bottom", 34))))
    content_width = panel_rect.width - padding * 2
    lines = []
    for item in history:
        source = f"{item['speaker']}: {item['text']}"
        words = source.split()
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and body_font.size(candidate)[0] > content_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
        lines.append("")
    text_color = (255, 255, 255) if high_contrast else tuple(history_style.get("text_color", COLORS.text))
    line_height = body_font.get_linesize() + ui_size(history_style.get("line_gap", 3))
    visible_count = max(1, (panel_rect.height - padding * 4) // line_height)
    max_scroll = max(0, len(lines) - visible_count)
    scroll = max(0, min(scroll, max_scroll))
    end = max(0, len(lines) - scroll)
    start = max(0, end - visible_count)
    for index, line in enumerate(lines[start:end]):
        if line:
            rendered = body_font.render(line, True, text_color)
            surface.blit(rendered, (panel_rect.left + padding, panel_rect.top + ui_size(62) + index * line_height))
    return scroll


class UIElement:
    def __init__(self, x: int, y: int, width: int, height: int):
        self.surface = pygame.Surface((width, height), pygame.SRCALPHA)
        self.rect = self.surface.get_rect(topleft=(x, y))


class Panel(UIElement):
    def set_background(
        self,
        bg: tuple[int, ...] | pygame.Surface,
        opacity: float = 1.0,
        base_color: tuple[int, ...] | None = None,
    ):
        self.surface.fill(base_color or COLORS.blank)
        if isinstance(bg, tuple):
            self.surface.fill(bg)
        elif isinstance(bg, pygame.Surface):
            self.surface.blit(pygame.transform.scale(bg, self.rect.size), (0, 0))
        self.surface.set_alpha(int(255 * opacity))

    def fade_sides(self, steps: int = 2, sides: float = 0.15):
        surface_alpha = self.surface.get_alpha()
        self.surface.set_alpha(255)
        temp_surf = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        temp_surf.fill(COLORS.blank)
        space = min(int(self.rect.w * sides), self.rect.w // 2)
        if space <= 0:
            return

        for x in range(0, space, max(1, steps)):
            width = min(max(1, steps), space - x)
            alpha = int(255 * (x / space))
            left = self.surface.subsurface((x, 0, width, self.rect.h)).copy()
            left.set_alpha(alpha)
            temp_surf.blit(left, (x, 0))

            right_x = self.rect.w - x - width
            right = self.surface.subsurface((right_x, 0, width, self.rect.h)).copy()
            right.set_alpha(alpha)
            temp_surf.blit(right, (right_x, 0))

        middle_width = self.rect.w - 2 * space
        if middle_width > 0:
            middle = self.surface.subsurface((space, 0, middle_width, self.rect.h))
            temp_surf.blit(middle, (space, 0))
        temp_surf.set_alpha(surface_alpha)
        self.surface = temp_surf


class Textbox(UIElement):
    def __init__(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        panel_color: tuple[int, ...] | None = None,
        panel_image: pygame.Surface | None = None,
        panel_opacity: float = 0.95,
        high_contrast: bool = False,
        subtitles_enabled: bool = True,
        style: dict | None = None,
    ):
        super().__init__(x, y, width, height)
        self.style = style if isinstance(style, dict) else {}
        self.text_style = self.style.get("text", {}) if isinstance(self.style.get("text", {}), dict) else {}
        self.speaker_style = self.style.get("speaker", {}) if isinstance(self.style.get("speaker", {}), dict) else {}
        self.high_contrast = high_contrast
        self.subtitles_enabled = subtitles_enabled
        if panel_image is not None:
            panel_image = fit_surface(
                panel_image,
                (width, height),
                self.style.get("fit", "stretch"),
                self.style.get("nine_slice"),
            )
        self.panel = Panel(0, 0, width, height)
        if high_contrast:
            self.panel.set_background((0, 0, 0, 255), opacity=1.0, base_color=(0, 0, 0, 255))
        else:
            self.panel.set_background(
                panel_image if panel_image is not None else (panel_color or COLORS.panel),
                opacity=panel_opacity,
                base_color=panel_color or COLORS.panel,
            )
        self.panel.fade_sides(
            steps=max(1, int(self.style.get("fade_steps", 2))),
            sides=max(0.0, min(0.5, float(self.style.get("fade_sides", 0.15)))),
        )
        border_color = self.style.get("border_color")
        if border_color:
            pygame.draw.rect(
                self.surface,
                tuple(border_color),
                self.surface.get_rect(),
                width=max(1, ui_size(self.style.get("border_width", 1))),
                border_radius=ui_size(self.style.get("radius", 0)),
            )

        # Each item is (character, color, bold, italic, strike).
        self.full_parsed_text = []
        self.visible_chars = 0
        self.current_speaker = ""
        self.ms_per_char = 30
        self.last_update_time = 0
        self.text_bottom_padding = 0
        font = FONTS.normal_text
        get_point_size = getattr(font, "get_point_size", None)
        self.base_font_size = get_point_size() if callable(get_point_size) else None
        self.message_font_size = self.base_font_size

    @property
    def complete(self) -> bool:
        return self.visible_chars >= len(self.full_parsed_text)

    def start_text(self, speaker: str, message: str, parsed=None, values=None):
        self.current_speaker = speaker
        self.full_parsed_text = []
        self.visible_chars = 0
        self.last_update_time = pygame.time.get_ticks()

        parsed_words = parsed if parsed is not None else parse(message)
        values = values or {}
        for word, style in parsed_words:
            if "value" in style:
                word = str(values.get(word, f"{{{word}}}"))

            # Image and sound markers are flow actions. The textbox only lays
            # out their surrounding text and never executes those actions.
            if "set_image" in style or "play_sound" in style:
                continue

            color = self.text_style.get("highlight_color", COLORS.text_highlight) if "highlight" in style else self.text_style.get("color", COLORS.text)
            if self.high_contrast:
                color = (255, 230, 96) if "highlight" in style else (255, 255, 255)
            is_bold = "bold" in style
            is_italic = "italic" in style
            strike = "strike" in style
            for char in word:
                self.full_parsed_text.append((char, color, is_bold, is_italic, strike))
        self._fit_font_to_message()

    def _fit_font_to_message(self):
        font = FONTS.normal_text
        if font is None or self.base_font_size is None:
            return

        base_size = max(1, int(self.base_font_size))
        self.message_font_size = base_size
        if self._message_fits_at_size(base_size):
            return

        minimum_size = 1
        if not self._message_fits_at_size(minimum_size):
            self.message_font_size = minimum_size
            return

        lower = minimum_size
        upper = base_size - 1
        while lower <= upper:
            candidate = (lower + upper) // 2
            if self._message_fits_at_size(candidate):
                self.message_font_size = candidate
                lower = candidate + 1
            else:
                upper = candidate - 1

    def _message_fits_at_size(self, size: int) -> bool:
        font = FONTS.normal_text
        get_point_size = getattr(font, "get_point_size", None)
        set_point_size = getattr(font, "set_point_size", None)
        original_size = get_point_size() if callable(get_point_size) else None
        old_bold = font.get_bold()
        old_italic = font.get_italic()
        try:
            if callable(set_point_size):
                set_point_size(size)
            margin = ui_size(self.text_style.get("margin_left", 40))
            right_edge = self.rect.width - margin
            cursor_x = margin
            cursor_y = ui_size(self.text_style.get("margin_top", 55))
            line_height = font.get_linesize()
            content_height = max(0, self.rect.height - self.text_bottom_padding)

            for char, _, is_bold, is_italic, _ in self.full_parsed_text:
                font.set_bold(is_bold)
                font.set_italic(is_italic)
                if char == "\n":
                    cursor_x = margin
                    cursor_y += line_height + ui_size(self.text_style.get("line_gap", 0))
                    continue
                if char == " ":
                    cursor_x += font.size(" ")[0]
                    continue

                char_width = font.size(char)[0]
                if cursor_x + char_width > right_edge:
                    cursor_x = margin
                    cursor_y += line_height + ui_size(self.text_style.get("line_gap", 0))
                if cursor_y + line_height > content_height:
                    return False
                cursor_x += char_width
            return True
        finally:
            font.set_bold(old_bold)
            font.set_italic(old_italic)
            if original_size is not None and callable(set_point_size):
                set_point_size(original_size)

    def reveal_all(self):
        self.visible_chars = len(self.full_parsed_text)

    def update(self):
        if self.complete:
            return

        now = pygame.time.get_ticks()
        elapsed = now - self.last_update_time
        if elapsed >= self.ms_per_char:
            chars_to_add = max(1, elapsed // self.ms_per_char)
            self.visible_chars = min(len(self.full_parsed_text), self.visible_chars + chars_to_add)
            self.last_update_time = now

    def render(self):
        self.surface.fill(COLORS.blank)
        self.surface.blit(self.panel.surface, (0, 0))

        if self.current_speaker:
            name_surf = FONTS.char_name.render(
                f" {self.current_speaker} ",
                True,
                (255, 230, 96) if self.high_contrast else self.speaker_style.get("color", COLORS.text_highlight),
            )
            self.surface.blit(name_surf, (
                ui_size(self.speaker_style.get("margin_left", 40)),
                ui_size(self.speaker_style.get("margin_top", 15)),
            ))

        font = FONTS.normal_text
        margin_left = ui_size(self.text_style.get("margin_left", 40))
        cursor_x = margin_left
        cursor_y = ui_size(self.text_style.get("margin_top", 55))
        original_size = font.get_point_size() if hasattr(font, "get_point_size") else None
        if self.message_font_size is not None and hasattr(font, "set_point_size"):
            font.set_point_size(self.message_font_size)
        line_height = font.get_linesize()
        original_clip = self.surface.get_clip()
        content_height = max(0, self.rect.height - self.text_bottom_padding)
        self.surface.set_clip(pygame.Rect(0, 0, self.rect.width, content_height))

        old_bold = font.get_bold()
        old_italic = font.get_italic()
        try:
            visible_text = self.full_parsed_text[:self.visible_chars] if self.subtitles_enabled else ()
            for char, color, is_bold, is_italic, strike in visible_text:
                if self.high_contrast:
                    color = (255, 230, 96) if color == COLORS.text_highlight else (255, 255, 255)
                font.set_bold(is_bold)
                font.set_italic(is_italic)

                if char == "\n":
                    cursor_x = margin_left
                    cursor_y += line_height + ui_size(self.text_style.get("line_gap", 0))
                    continue
                if char == " ":
                    cursor_x += font.size(" ")[0]
                    continue

                char_surf = font.render(char, True, color)
                if cursor_x + char_surf.get_width() > self.rect.w - margin_left:
                    cursor_x = margin_left
                    cursor_y += line_height + ui_size(self.text_style.get("line_gap", 0))

                if strike:
                    pygame.draw.line(
                        char_surf,
                        (255, 230, 96) if self.high_contrast else self.text_style.get("highlight_color", COLORS.text_highlight),
                        (0, char_surf.get_height() // 2),
                        (char_surf.get_width(), char_surf.get_height() // 2),
                    )
                self.surface.blit(char_surf, (cursor_x, cursor_y))
                cursor_x += char_surf.get_width()
        finally:
            font.set_bold(old_bold)
            font.set_italic(old_italic)
            if original_size is not None and hasattr(font, "set_point_size"):
                font.set_point_size(original_size)
            self.surface.set_clip(original_clip)


class Button(UIElement):
    def __init__(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        normal_image: pygame.Surface | None = None,
        hovered_image: pygame.Surface | None = None,
        style: dict | None = None,
        skin: dict | None = None,
        asset_manager=None,
    ):
        super().__init__(x, y, width, height)
        self.panel = Panel(0, 0, width, height)
        self.panel.set_background(COLORS.panel)
        self.panel.fade_sides(steps=2, sides=0.15)
        if normal_image is None:
            normal_image = hovered_image
        if hovered_image is None:
            hovered_image = normal_image
        self.normal_image = (
            pygame.transform.smoothscale(normal_image, self.rect.size)
            if normal_image is not None else None
        )
        self.hovered_image = (
            pygame.transform.smoothscale(hovered_image, self.rect.size)
            if hovered_image is not None else None
        )
        self.active = True
        self.style = style if isinstance(style, dict) else {}
        self.skin = skin if isinstance(skin, dict) else {}
        self.assets = asset_manager

    def update(self, click: bool, position=None) -> bool:
        if not click or not self.active:
            return False
        if position is None:
            position = pygame.mouse.get_pos()
        return self.rect.collidepoint(position)

    def render(self, msg: str, hovered: bool = False, focused: bool = False, pressed: bool = False, selected: bool = False):
        self.surface.fill(COLORS.blank)
        state = control_state(
            disabled=not self.active,
            pressed=pressed,
            focused=focused,
            hovered=hovered,
            selected=selected,
        )
        fallback = None
        if state == "hover":
            fallback = self.style.get("hover_color")
        elif state in {"focus", "selected", "pressed"}:
            fallback = self.style.get("focus_color", self.style.get("selected_color"))
        elif state == "disabled":
            fallback = self.style.get("disabled_color")
        if not draw_skin(self.surface, self.surface.get_rect(), self.assets, self.skin, state, fallback):
            image = self.hovered_image if state in {"hover", "focus", "pressed", "selected"} else self.normal_image
            if image is not None:
                self.surface.blit(image, (0, 0))
            else:
                self.surface.blit(self.panel.surface, (0, 0))

        text_color = self.style.get("disabled_text_color", COLORS.text) if state == "disabled" else self.style.get("text_color", COLORS.text)
        text_surf = FONTS.button_text.render(msg, True, text_color)
        alignment = self.style.get("label_alignment", "center")
        padding = ui_size(self.style.get("padding", 8))
        if alignment == "left":
            x = padding
        elif alignment == "right":
            x = self.rect.w - padding - text_surf.get_width()
        else:
            x = (self.rect.w - text_surf.get_width()) // 2
        y = (self.rect.h - text_surf.get_height()) // 2
        self.surface.blit(text_surf, (x, y))
