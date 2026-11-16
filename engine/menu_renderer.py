import pygame

from engine.theme import DEFAULT_THEME
from engine.ui_scale import ui_size


class MenuRenderer:
    """Renderer interface. Implement render(screen, menu) for a custom layout."""

    def render(self, screen, menu):
        raise NotImplementedError

    def play_sound(self, name: str, volume: float = 1.0):
        return None


class FallbackMenuRenderer(MenuRenderer):
    """Asset-free menu drawn with Pygame shapes and system fonts."""

    def __init__(self, asset_manager=None, theme=None):
        self.assets = asset_manager
        self.theme = theme or DEFAULT_THEME
        self.title_font = pygame.font.SysFont(None, ui_size(34))
        self.item_font = pygame.font.SysFont(None, ui_size(24))
        self.detail_font = pygame.font.SysFont(None, ui_size(18))

    def play_sound(self, name: str, volume: float = 1.0):
        sound_name = self.theme.get("sounds", {}).get(name)
        if not sound_name or self.assets is None:
            return
        try:
            self.assets.play_sound(sound_name, volume)
        except (FileNotFoundError, pygame.error):
            return

    def render(self, screen, menu):
        width, height = screen.get_size()
        title = self.title_font.render(menu.title, True, (238, 238, 242))
        row_gap = ui_size(9)
        available_top = ui_size(78)
        available_bottom = max(available_top, height - ui_size(20))
        max_row_height = max(1, (available_bottom - available_top - max(0, len(menu.items) - 1) * row_gap) // max(1, len(menu.items)))
        row_height = min(ui_size(56), max_row_height)
        total_height = len(menu.items) * row_height + max(0, len(menu.items) - 1) * row_gap
        centered_y = available_top + max(0, (available_bottom - available_top - total_height) // 2)
        start_y = min(max(ui_size(190), centered_y), max(available_top, available_bottom - total_height))
        title_y = min(ui_size(112), start_y - title.get_height() // 2 - ui_size(10))
        title_y = max(title.get_height() // 2 + ui_size(8), title_y)
        screen.blit(title, title.get_rect(center=(width // 2, title_y)))

        row_width = min(ui_size(860), max(ui_size(120), width - ui_size(96)))
        left = (width - row_width) // 2
        menu.row_rects = []
        for index, item in enumerate(menu.items):
            rect = pygame.Rect(left, start_y + index * (row_height + row_gap), row_width, row_height)
            menu.row_rects.append(rect)
            selected = index == menu.selected
            persistent = item.get("persistent_selected", False)
            fill = self.theme.get("colors", {}).get("selected", (45, 92, 78)) if persistent and not selected else (73, 50, 65) if selected else (18, 18, 29)
            pygame.draw.rect(screen, fill, rect, border_radius=ui_size(8))
            pygame.draw.rect(screen, (112, 86, 101), rect, width=ui_size(1), border_radius=ui_size(8))
            self._draw_item_text(screen, rect, item, selected, self.item_font, self.detail_font)

    @staticmethod
    def _draw_item_text(screen, rect, item, selected, item_font, detail_font, left_offset=None):
        left_offset = ui_size(24) if left_offset is None else left_offset
        label = item.get("label", "")
        detail = item.get("detail", "")
        color = (238, 238, 242) if selected else (220, 220, 226)
        text = item_font.render(str(label), True, color)
        screen.blit(text, (rect.x + left_offset, rect.centery - text.get_height() // 2))
        if detail:
            detail_text = detail_font.render(str(detail), True, (178, 178, 188))
            screen.blit(
                detail_text,
                (rect.right - detail_text.get_width() - ui_size(20), rect.centery - detail_text.get_height() // 2),
            )


class DeclarativeMenuRenderer(MenuRenderer):
    """Theme-driven standard renderer with engine defaults for missing values."""

    def __init__(self, asset_manager, theme):
        self.assets = asset_manager
        self.theme = theme
        fonts = theme.get("fonts", DEFAULT_THEME["fonts"])
        self.title_font = asset_manager.load_font(fonts.get("title"), ui_size(fonts.get("title_size", 30)))
        self.item_font = asset_manager.load_font(fonts.get("menu"), ui_size(fonts.get("item_size", 20)))
        self.detail_font = asset_manager.load_font(fonts.get("menu"), ui_size(fonts.get("detail_size", 16)))
        background_name = theme.get("menu", {}).get("background")
        try:
            self.background_image = asset_manager.load_image(background_name) if background_name else None
        except (FileNotFoundError, TypeError, pygame.error):
            self.background_image = None

    def _draw_background(self, screen):
        if self.background_image is not None:
            scaled = pygame.transform.smoothscale(self.background_image, screen.get_size())
            screen.blit(scaled, (0, 0))

    def play_sound(self, name: str, volume: float = 1.0):
        sound_name = self.theme.get("sounds", {}).get(name)
        if not sound_name:
            return
        try:
            self.assets.play_sound(sound_name, volume)
        except (FileNotFoundError, pygame.error):
            return

    def render(self, screen, menu):
        self._draw_background(screen)
        width, height = screen.get_size()
        layout = self.theme.get("menu", DEFAULT_THEME["menu"])
        colors = self.theme.get("colors", DEFAULT_THEME["colors"])
        title = self.title_font.render(menu.title, True, self._color(colors, "text"))
        title_y = ui_size(layout.get("title_y", 112))
        row_height = max(1, ui_size(layout.get("row_height", 56)))
        row_gap = max(0, ui_size(layout.get("row_gap", 9)))
        available_top = ui_size(78)
        available_bottom = max(available_top, height - ui_size(20))
        max_row_height = max(1, (available_bottom - available_top - max(0, len(menu.items) - 1) * row_gap) // max(1, len(menu.items)))
        row_height = min(row_height, max_row_height)
        total_height = len(menu.items) * row_height + max(0, len(menu.items) - 1) * row_gap
        top = ui_size(layout.get("top", 190))
        centered_y = available_top + max(0, (available_bottom - available_top - total_height) // 2)
        start_y = min(max(top, centered_y), max(available_top, available_bottom - total_height))
        title_y = min(title_y, start_y - title.get_height() // 2 - ui_size(10))
        title_y = max(title.get_height() // 2 + ui_size(8), title_y)
        screen.blit(title, title.get_rect(center=(width // 2, title_y)))

        row_width = min(ui_size(layout.get("width", 860)), max(ui_size(120), width - ui_size(96)))
        alignment = layout.get("layout", "centered")
        if alignment == "left":
            left = ui_size(layout.get("x", 48) or 48)
        elif alignment == "right":
            left = width - row_width - ui_size(layout.get("right_margin", 48))
        else:
            configured_x = layout.get("x")
            left = ui_size(configured_x) if configured_x is not None else (width - row_width) // 2
        radius = max(0, ui_size(layout.get("border_radius", 8)))
        menu.row_rects = []

        for index, item in enumerate(menu.items):
            rect = pygame.Rect(left, start_y + index * (row_height + row_gap), row_width, row_height)
            menu.row_rects.append(rect)
            selected = index == menu.selected
            persistent = item.get("persistent_selected", False)
            fill_key = "hover" if selected else "selected" if persistent else "normal"
            pygame.draw.rect(screen, self._color(colors, fill_key), rect, border_radius=radius)
            pygame.draw.rect(screen, self._color(colors, "border"), rect, width=ui_size(1), border_radius=radius)
            FallbackMenuRenderer._draw_item_text(
                screen,
                rect,
                item,
                selected,
                self.item_font,
                self.detail_font,
            )

    @staticmethod
    def _color(colors, key):
        value = colors.get(key, DEFAULT_THEME["colors"][key])
        try:
            if len(value) < 3:
                raise ValueError("RGB color needs three channels")
            return tuple(max(0, min(255, int(channel))) for channel in value[:3])
        except (TypeError, ValueError):
            return tuple(DEFAULT_THEME["colors"][key])


class TapeSlotRenderer(DeclarativeMenuRenderer):
    """Alternative slot layout using project-provided tape sprites."""

    def __init__(self, asset_manager, theme):
        super().__init__(asset_manager, theme)
        slot_theme = theme.get("slot", DEFAULT_THEME["slot"])
        self.slot_theme = slot_theme
        try:
            self.normal_tape = asset_manager.load_image(slot_theme.get("normal"))
        except (FileNotFoundError, TypeError, pygame.error):
            self.normal_tape = None
        try:
            self.hovered_tape = asset_manager.load_image(slot_theme.get("hovered"))
        except (FileNotFoundError, TypeError, pygame.error):
            self.hovered_tape = None
        self.has_tape_art = self.normal_tape is not None and self.hovered_tape is not None

    def render(self, screen, menu):
        if not self.has_tape_art:
            return super().render(screen, menu)

        self._draw_background(screen)
        width, height = screen.get_size()
        colors = self.theme.get("colors", DEFAULT_THEME["colors"])
        title = self.title_font.render(menu.title, True, self._color(colors, "text"))
        title_y = ui_size(self.theme["menu"].get("title_y", 112))

        slot_theme = self.slot_theme
        gap = max(0, ui_size(slot_theme.get("row_gap", 8)))
        configured_height = max(1, ui_size(slot_theme.get("row_height", 82)))
        max_height = max(ui_size(42), (height - ui_size(110) - gap * max(0, len(menu.items) - 1)) // max(1, len(menu.items)))
        row_height = min(configured_height, max_height)
        total_height = len(menu.items) * row_height + max(0, len(menu.items) - 1) * gap
        start_y = min(max(ui_size(150), (height - total_height) // 2), max(ui_size(72), height - ui_size(20) - total_height))
        title_y = min(title_y, start_y - title.get_height() // 2 - ui_size(10))
        title_y = max(title.get_height() // 2 + ui_size(8), title_y)
        screen.blit(title, title.get_rect(center=(width // 2, title_y)))
        row_width = min(ui_size(slot_theme.get("width", 900)), max(ui_size(120), width - ui_size(96)))
        left = (width - row_width) // 2
        icon_width = max(1, ui_size(slot_theme.get("icon_width", 30)))
        icon_height = min(row_height - ui_size(8), ui_size(slot_theme.get("icon_height", 72)))
        text_offset = max(icon_width + ui_size(20), ui_size(slot_theme.get("text_offset", 62)))
        radius = max(0, ui_size(self.theme["menu"].get("border_radius", 8)))
        menu.row_rects = []

        for index, item in enumerate(menu.items):
            rect = pygame.Rect(left, start_y + index * (row_height + gap), row_width, row_height)
            menu.row_rects.append(rect)
            selected = index == menu.selected
            persistent = item.get("persistent_selected", False)
            fill = self._color(colors, "hover" if selected else "selected" if persistent else "normal")
            pygame.draw.rect(screen, fill, rect, border_radius=radius)
            pygame.draw.rect(screen, self._color(colors, "border"), rect, width=ui_size(1), border_radius=radius)

            tape = self.hovered_tape if selected else self.normal_tape
            scaled = pygame.transform.smoothscale(tape, (icon_width, icon_height))
            screen.blit(scaled, (rect.x + ui_size(16), rect.centery - icon_height // 2))
            FallbackMenuRenderer._draw_item_text(
                screen,
                rect,
                item,
                selected,
                self.item_font,
                self.detail_font,
                left_offset=text_offset,
            )
