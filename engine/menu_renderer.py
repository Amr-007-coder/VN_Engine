import pygame

from engine.theme import DEFAULT_THEME, validate_menu_grid
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
        self._image_cache = {}
        self._scaled_image_cache = {}

    def _screen_theme(self, menu):
        return self.theme.get("menu", {}).get("screens", {}).get(menu.kind, {})

    def _image(self, name):
        if not name:
            return None
        if name not in self._image_cache:
            try:
                self._image_cache[name] = self.assets.load_image(name).convert_alpha()
            except (FileNotFoundError, TypeError, pygame.error):
                self._image_cache[name] = None
        return self._image_cache[name]

    def _scaled_image(self, name, size):
        image = self._image(name)
        if image is None:
            return None
        key = (name, size)
        if key not in self._scaled_image_cache:
            self._scaled_image_cache[key] = pygame.transform.smoothscale(image, size)
        return self._scaled_image_cache[key]

    def _draw_background(self, screen, screen_theme):
        menu_theme = self.theme.get("menu", DEFAULT_THEME["menu"])
        name = screen_theme.get("background") or menu_theme.get("background")
        image = self._scaled_image(name, screen.get_size())
        if image is not None:
            screen.blit(image, (0, 0))

    def play_sound(self, name: str, volume: float = 1.0):
        sound_name = self.theme.get("sounds", {}).get(name)
        if not sound_name:
            return
        try:
            self.assets.play_sound(sound_name, volume)
        except (FileNotFoundError, pygame.error):
            return

    def render(self, screen, menu):
        menu_theme = self.theme.get("menu", DEFAULT_THEME["menu"])
        screen_theme = self._screen_theme(menu)
        self._draw_background(screen, screen_theme)
        width, height = screen.get_size()
        colors = self.theme.get("colors", DEFAULT_THEME["colors"])
        title = self.title_font.render(menu.title, True, self._color(colors, "text"))
        title_y = ui_size(menu_theme.get("title_y", 112))
        grid = screen_theme.get("grid")
        if grid is not None:
            menu.row_rects = self._grid_rectangles(grid, len(menu.items), screen.get_size(), screen_theme)
        else:
            menu.row_rects = self._vertical_rectangles(
                menu_theme, screen_theme, len(menu.items), screen.get_size()
            )
        if menu.row_rects:
            first_top = min(rect.top for rect in menu.row_rects)
            title_y = min(title_y, first_top - title.get_height() // 2 - ui_size(10))
        title_y = max(title.get_height() // 2 + ui_size(8), title_y)
        screen.blit(title, title.get_rect(center=(width // 2, title_y)))

        buttons = screen_theme.get("buttons", {})
        normal_name = buttons.get("normal") if isinstance(buttons, dict) else None
        hovered_name = buttons.get("hovered") if isinstance(buttons, dict) else None
        if normal_name is None:
            normal_name = hovered_name
        if hovered_name is None:
            hovered_name = normal_name
        radius = max(0, ui_size(menu_theme.get("border_radius", 8)))
        for index, (rect, item) in enumerate(zip(menu.row_rects, menu.items)):
            selected = index == menu.selected
            persistent = item.get("persistent_selected", False)
            image_name = hovered_name if selected else normal_name
            image = self._scaled_image(image_name, rect.size)
            if image is not None:
                screen.blit(image, rect)
            else:
                fill_key = "hover" if selected else "selected" if persistent else "normal"
                pygame.draw.rect(screen, self._color(colors, fill_key), rect, border_radius=radius)
                pygame.draw.rect(
                    screen,
                    self._color(colors, "border"),
                    rect,
                    width=ui_size(1),
                    border_radius=radius,
                )
            FallbackMenuRenderer._draw_item_text(
                screen,
                rect,
                item,
                selected,
                self.item_font,
                self.detail_font,
            )

    def _vertical_rectangles(self, menu_theme, screen_theme, item_count, screen_size):
        width, height = screen_size
        row_gap = max(
            0,
            ui_size(
                screen_theme.get("row_gap")
                if screen_theme.get("row_gap") is not None
                else menu_theme.get("row_gap", 9)
            ),
        )
        available_top = ui_size(78)
        available_bottom = max(available_top, height - ui_size(20))
        configured_height = screen_theme.get("button_height")
        row_height = max(
            1,
            ui_size(
                configured_height
                if configured_height is not None
                else menu_theme.get("row_height", 56)
            ),
        )
        max_row_height = max(
            1,
            (available_bottom - available_top - max(0, item_count - 1) * row_gap)
            // max(1, item_count),
        )
        row_height = min(row_height, max_row_height)
        total_height = item_count * row_height + max(0, item_count - 1) * row_gap
        configured_top = screen_theme.get("top")
        top = ui_size(
            configured_top if configured_top is not None else menu_theme.get("top", 190)
        )
        centered_y = available_top + max(0, (available_bottom - available_top - total_height) // 2)
        start_y = min(max(top, centered_y), max(available_top, available_bottom - total_height))

        configured_width = screen_theme.get("button_width")
        row_width = min(
            ui_size(
                configured_width
                if configured_width is not None
                else menu_theme.get("width", 860)
            ),
            max(ui_size(120), width - ui_size(96)),
        )
        alignment = screen_theme.get("alignment") or menu_theme.get("layout", "centered")
        if alignment == "left":
            left = ui_size(menu_theme.get("x", 48) or 48)
        elif alignment == "right":
            left = width - row_width - ui_size(menu_theme.get("right_margin", 48))
        else:
            configured_x = menu_theme.get("x")
            left = ui_size(configured_x) if configured_x is not None else (width - row_width) // 2
        return [
            pygame.Rect(left, start_y + index * (row_height + row_gap), row_width, row_height)
            for index in range(item_count)
        ]

    @staticmethod
    def _grid_rectangles(grid, item_count, screen_size, screen_theme):
        validate_menu_grid(grid, item_count)
        screen_width, screen_height = screen_size
        rows = len(grid)
        columns = max(len(row) for row in grid)
        configured_width = screen_theme.get("button_width")
        configured_height = screen_theme.get("button_height")
        button_width = ui_size(240 if configured_width is None else configured_width)
        button_height = ui_size(72 if configured_height is None else configured_height)
        rects = [pygame.Rect(0, 0, 0, 0) for _ in range(item_count)]
        for row_index, row in enumerate(grid):
            cell_top = row_index * screen_height // rows
            cell_bottom = (row_index + 1) * screen_height // rows
            for column_index, item_index in enumerate(row):
                if item_index in (None, 0):
                    continue
                cell_left = column_index * screen_width // columns
                cell_right = (column_index + 1) * screen_width // columns
                width = min(button_width, cell_right - cell_left)
                height = min(button_height, cell_bottom - cell_top)
                rects[item_index - 1] = pygame.Rect(
                    cell_left + (cell_right - cell_left - width) // 2,
                    cell_top + (cell_bottom - cell_top - height) // 2,
                    width,
                    height,
                )
        return rects

    @staticmethod
    def _color(colors, key):
        value = colors.get(key, DEFAULT_THEME["colors"][key])
        try:
            if len(value) < 3:
                raise ValueError("RGB color needs three channels")
            return tuple(max(0, min(255, int(channel))) for channel in value[:3])
        except (TypeError, ValueError):
            return tuple(DEFAULT_THEME["colors"][key])
