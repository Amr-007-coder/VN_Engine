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
    ):
        super().__init__(x, y, width, height)
        self.panel = Panel(0, 0, width, height)
        self.panel.set_background(
            panel_image if panel_image is not None else (panel_color or COLORS.panel),
            opacity=0.95,
            base_color=panel_color or COLORS.panel,
        )
        self.panel.fade_sides(steps=2, sides=0.15)

        # Each item is (character, color, bold, italic, strike).
        self.full_parsed_text = []
        self.visible_chars = 0
        self.current_speaker = ""
        self.ms_per_char = 30
        self.last_update_time = 0

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
            is_bold = "bold" in style
            is_italic = "italic" in style
            strike = "strike" in style
            for char in word:
                self.full_parsed_text.append((char, color, is_bold, is_italic, strike))

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
                f" {self.current_speaker} ", True, COLORS.text_highlight
            )
            self.surface.blit(name_surf, (ui_size(40), ui_size(15)))

        font = FONTS.normal_text
        cursor_x = ui_size(40)
        cursor_y = ui_size(55)
        line_height = font.get_linesize()

        old_bold = font.get_bold()
        old_italic = font.get_italic()
        for char, color, is_bold, is_italic, strike in self.full_parsed_text[:self.visible_chars]:
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

        font.set_bold(old_bold)
        font.set_italic(old_italic)


class Button(UIElement):
    def __init__(self, x: int, y: int, width: int, height: int):
        super().__init__(x, y, width, height)
        self.panel = Panel(0, 0, width, height)
        self.panel.set_background(COLORS.panel)
        self.panel.fade_sides(steps=2, sides=0.15)
        self.active = True

    def update(self, click: bool, position=None) -> bool:
        if not click or not self.active:
            return False
        if position is None:
            position = pygame.mouse.get_pos()
        return self.rect.collidepoint(position)

    def render(self, msg: str):
        self.surface.fill(COLORS.blank)
        self.surface.blit(self.panel.surface, (0, 0))

        text_surf = FONTS.button_text.render(msg, True, COLORS.text)
        x = (self.rect.w - text_surf.get_width()) // 2
        y = (self.rect.h - text_surf.get_height()) // 2
        self.surface.blit(text_surf, (x, y))
