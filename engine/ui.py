import pygame

from engine.config import COLORS, FONTS
from engine.parser import parse
from engine.ui_scale import ui_size


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
    ):
        super().__init__(x, y, width, height)
        self.high_contrast = high_contrast
        self.subtitles_enabled = subtitles_enabled
        self.panel = Panel(0, 0, width, height)
        if high_contrast:
            self.panel.set_background((0, 0, 0, 255), opacity=1.0, base_color=(0, 0, 0, 255))
        else:
            self.panel.set_background(
                panel_image if panel_image is not None else (panel_color or COLORS.panel),
                opacity=panel_opacity,
                base_color=panel_color or COLORS.panel,
            )
        self.panel.fade_sides(steps=2, sides=0.15)

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

            color = COLORS.text_highlight if "highlight" in style else COLORS.text
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
            margin = ui_size(40)
            right_edge = self.rect.width - margin
            cursor_x = margin
            cursor_y = ui_size(55)
            line_height = font.get_linesize()
            content_height = max(0, self.rect.height - self.text_bottom_padding)

            for char, _, is_bold, is_italic, _ in self.full_parsed_text:
                font.set_bold(is_bold)
                font.set_italic(is_italic)
                if char == "\n":
                    cursor_x = margin
                    cursor_y += line_height
                    continue
                if char == " ":
                    cursor_x += font.size(" ")[0]
                    continue

                char_width = font.size(char)[0]
                if cursor_x + char_width > right_edge:
                    cursor_x = margin
                    cursor_y += line_height
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
                (255, 230, 96) if self.high_contrast else COLORS.text_highlight,
            )
            self.surface.blit(name_surf, (ui_size(40), ui_size(15)))

        font = FONTS.normal_text
        cursor_x = ui_size(40)
        cursor_y = ui_size(55)
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
                    cursor_x = ui_size(40)
                    cursor_y += line_height
                    continue
                if char == " ":
                    cursor_x += font.size(" ")[0]
                    continue

                char_surf = font.render(char, True, color)
                if cursor_x + char_surf.get_width() > self.rect.w - ui_size(40):
                    cursor_x = ui_size(40)
                    cursor_y += line_height

                if strike:
                    pygame.draw.line(
                        char_surf,
                        COLORS.text_highlight,
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

    def update(self, click: bool, position=None) -> bool:
        if not click or not self.active:
            return False
        if position is None:
            position = pygame.mouse.get_pos()
        return self.rect.collidepoint(position)

    def render(self, msg: str, hovered: bool = False):
        self.surface.fill(COLORS.blank)
        image = self.hovered_image if hovered else self.normal_image
        if image is not None:
            self.surface.blit(image, (0, 0))
        else:
            self.surface.blit(self.panel.surface, (0, 0))

        text_surf = FONTS.button_text.render(msg, True, COLORS.text)
        x = (self.rect.w - text_surf.get_width()) // 2
        y = (self.rect.h - text_surf.get_height()) // 2
        self.surface.blit(text_surf, (x, y))
