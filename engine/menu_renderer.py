import pygame

from engine.theme import DEFAULT_THEME, validate_menu_grid
from engine.style import style_component
from engine.layout import component_layout, layout_children, resolve_rect, safe_area_rect
from engine.skin import alpha_surface, draw_skin, fit_surface
from engine.ui_scale import get_ui_scale, ui_size


def _draw_menu_panel(screen, menu, style=None):
    rect = getattr(menu, "panel_rect", None)
    if not isinstance(rect, pygame.Rect):
        return
    style = style if isinstance(style, dict) else {}
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    fill = tuple(style.get("panel_color", (8, 8, 16, 210)))
    opacity = max(0.0, min(1.0, float(style.get("opacity", 1.0))))
    if len(fill) == 3:
        fill = (*fill, round(255 * opacity))
    else:
        fill = (*fill[:3], round(fill[3] * opacity))
    panel.fill(fill)
    screen.blit(panel, rect)
    border_color = style.get("panel_border_color", (95, 84, 112))
    if border_color and style.get("panel_border_width", 1):
        pygame.draw.rect(
            screen, tuple(border_color), rect,
            width=max(1, ui_size(style.get("panel_border_width", 1))),
            border_radius=ui_size(style.get("panel_radius", 10)),
        )


class MenuRenderer:
    """Renderer interface. Implement render(screen, menu) for a custom layout."""

    def render(self, screen, menu):
        raise NotImplementedError

    def play_sound(self, name: str, volume: float = 1.0):
        return None


class FallbackMenuRenderer(MenuRenderer):
    """Asset-free menu drawn with Pygame shapes and system fonts."""

    def __init__(self, asset_manager=None, theme=None, style=None, player_preferences=None):
        self.assets = asset_manager
        self.theme = theme or DEFAULT_THEME
        self.style = style if isinstance(style, dict) else {}
        self.player_preferences = player_preferences if isinstance(player_preferences, dict) else {}
        component = style_component(self.style, "menu")
        title_scale = float(self.player_preferences.get("speaker_font_scale", 1.0))
        item_scale = float(self.player_preferences.get("dialogue_font_scale", 1.0))
        self.title_font = pygame.font.SysFont(None, ui_size(component.get("title_font_size", 34) * title_scale))
        self.item_font = pygame.font.SysFont(None, ui_size(component.get("item_font_size", 24) * item_scale))
        self.detail_font = pygame.font.SysFont(None, ui_size(component.get("detail_font_size", 18) * item_scale))

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
        component = style_component(self.style, "menu")
        high_contrast = bool(getattr(self, "player_preferences", {}).get("high_contrast", False))
        if high_contrast:
            component = {**component, "panel_color": [0, 0, 0, 255], "panel_border_color": [255, 255, 255], "panel_border_width": max(2, component.get("panel_border_width", 1))}
        _draw_menu_panel(screen, menu, component)
        menu_theme = self.theme.get("menu", DEFAULT_THEME["menu"])
        screen_theme = menu_theme.get("screens", {}).get(menu.kind, {})
        label_alignment = screen_theme.get("label_alignment") or component.get("label_alignment", menu_theme.get("label_alignment", "left"))
        title_color = (255, 255, 255) if high_contrast else tuple(component.get("title_color", (238, 238, 242)))
        title = self.title_font.render(menu.title, True, title_color)
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
            fill = (42, 36, 20) if high_contrast and (persistent or selected) else (0, 0, 0) if high_contrast else self.theme.get("colors", {}).get("selected", (45, 92, 78)) if persistent and not selected else (73, 50, 65) if selected else (18, 18, 29)
            border = (255, 224, 120) if high_contrast and selected else (255, 255, 255) if high_contrast else (112, 86, 101)
            pygame.draw.rect(screen, fill, rect, border_radius=ui_size(component.get("radius", 8)))
            pygame.draw.rect(screen, border, rect, width=max(1, ui_size(component.get("border_width", 1))), border_radius=ui_size(component.get("radius", 8)))
            self._draw_menu_item(
                screen, rect, item, selected, self.item_font, self.detail_font,
                label_alignment=label_alignment,
                text_color=(255, 255, 255) if high_contrast else component.get("item_color", (238, 238, 242)),
                detail_color=(255, 255, 255) if high_contrast else component.get("detail_color", (178, 178, 188)),
                padding=component.get("padding", 8),
                preview_fit=style_component(self.style, "save_slots").get("thumbnail_fit", "contain"),
            )

    @classmethod
    def _draw_menu_item(cls, screen, rect, item, selected, item_font, detail_font, label_alignment="left", text_color=(238, 238, 242), detail_color=(178, 178, 188), padding=8, preview_fit="contain"):
        text_rect = rect
        preview = item.get("preview_surface")
        if isinstance(preview, pygame.Surface):
            height = max(1, min(rect.height - ui_size(padding), ui_size(48)))
            width = max(1, round(height * preview.get_width() / max(1, preview.get_height())))
            thumb = fit_surface(preview, (width, height), preview_fit)
            thumb_rect = thumb.get_rect(midleft=(rect.left + ui_size(padding), rect.centery))
            screen.blit(thumb, thumb_rect)
            pygame.draw.rect(screen, (210, 210, 220), thumb_rect, width=max(1, ui_size(1)))
            text_rect = rect.copy()
            text_rect.left += width + ui_size(padding * 2.5)
        cls._draw_item_text(
            screen,
            text_rect,
            item,
            selected,
            item_font,
            detail_font,
            left_offset=ui_size(padding),
            label_alignment=label_alignment,
            text_color=text_color,
            detail_color=detail_color,
            padding=padding,
        )

    @staticmethod
    def _draw_item_text(screen, rect, item, selected, item_font, detail_font, left_offset=None, label_alignment="left", text_color=(238, 238, 242), detail_color=(178, 178, 188), padding=8):
        left_offset = ui_size(padding * 3) if left_offset is None else left_offset
        label = item.get("label", "")
        detail = item.get("detail", "")
        text = item_font.render(str(label), True, text_color)
        left = rect.x + left_offset
        right = rect.right - ui_size(padding * 2.5)
        if detail:
            detail_text = detail_font.render(str(detail), True, detail_color)
            detail_x = rect.right - detail_text.get_width() - ui_size(padding * 2.5)
            screen.blit(
                detail_text,
                (detail_x, rect.centery - detail_text.get_height() // 2),
            )
            right = min(right, detail_x - ui_size(padding))
        if item.get("label_alignment", label_alignment) == "right":
            text_x = max(left, right - text.get_width())
        elif item.get("label_alignment", label_alignment) == "center":
            text_x = left + max(0, right - left - text.get_width()) // 2
        else:
            text_x = left
        screen.blit(text, (text_x, rect.centery - text.get_height() // 2))


class DeclarativeMenuRenderer(MenuRenderer):
    """Theme-driven standard renderer with engine defaults for missing values."""

    def __init__(self, asset_manager, theme, style=None, player_preferences=None):
        self.assets = asset_manager
        self.theme = theme
        self.style = style if isinstance(style, dict) else {}
        self.player_preferences = player_preferences if isinstance(player_preferences, dict) else {}
        fonts = theme.get("fonts", DEFAULT_THEME["fonts"])
        component = style_component(self.style, "menu")
        title_scale = float(self.player_preferences.get("speaker_font_scale", 1.0))
        item_scale = float(self.player_preferences.get("dialogue_font_scale", 1.0))
        self.title_font = asset_manager.load_font(component.get("title_font", fonts.get("title")), ui_size(component.get("title_font_size", fonts.get("title_size", 30)) * title_scale))
        self.item_font = asset_manager.load_font(component.get("item_font", fonts.get("menu")), ui_size(component.get("item_font_size", fonts.get("item_size", 20)) * item_scale))
        self.detail_font = asset_manager.load_font(component.get("detail_font", fonts.get("menu")), ui_size(component.get("detail_font_size", fonts.get("detail_size", 16)) * item_scale))
        self._image_cache = {}
        self._scaled_image_cache = {}

    def _screen_theme(self, menu):
        return self.theme.get("menu", {}).get("screens", {}).get(menu.kind, {})

    def _image(self, name):
        if not name:
            return None
        if name not in self._image_cache:
            try:
                # Image loads must also work for editor previews rendered to a
                # Surface before a display mode exists.
                self._image_cache[name] = alpha_surface(self.assets.load_image(name))
            except (FileNotFoundError, TypeError, pygame.error):
                self._image_cache[name] = None
        return self._image_cache[name]

    def _scaled_image(self, name, size, fit="stretch", nine_slice=None):
        image = self._image(name)
        if image is None:
            return None
        key = (name, size, fit, repr(nine_slice))
        if key not in self._scaled_image_cache:
            self._scaled_image_cache[key] = fit_surface(image, size, fit, nine_slice)
        return self._scaled_image_cache[key]

    def _draw_background(self, screen, screen_theme):
        menu_theme = self.theme.get("menu", DEFAULT_THEME["menu"])
        component = style_component(self.style, "menu")
        name = screen_theme.get("background") or component.get("background_image") or menu_theme.get("background")
        image = self._scaled_image(name, screen.get_size(), component.get("background_fit", "cover"))
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
        component = style_component(self.style, "menu")
        item_component = style_component(self.style, "save_slots") if menu.kind == "slots" else component
        label_alignment = screen_theme.get("label_alignment") or component.get("label_alignment", menu_theme.get("label_alignment", "left"))
        self._draw_background(screen, screen_theme)
        width, height = screen.get_size()
        colors = self.theme.get("colors", DEFAULT_THEME["colors"])
        item_font = self.item_font
        detail_font = self.detail_font
        if menu.kind == "slots":
            fonts = self.theme.get("fonts", DEFAULT_THEME["fonts"])
            font_name = item_component.get("font", fonts.get("menu"))
            font_size = ui_size(item_component.get("font_size", fonts.get("item_size", 18)))
            item_scale = float(self.player_preferences.get("dialogue_font_scale", 1.0))
            item_font = self.assets.load_font(font_name, max(1, round(font_size * item_scale)))
            detail_font = self.assets.load_font(item_component.get("detail_font", font_name), max(1, ui_size(item_component.get("detail_font_size", 14) * item_scale)))
        high_contrast = bool(getattr(self, "player_preferences", {}).get("high_contrast", False))
        if high_contrast:
            component = {**component, "panel_color": [0, 0, 0, 255], "panel_border_color": [255, 255, 255], "panel_border_width": max(2, component.get("panel_border_width", 1))}
        _draw_menu_panel(screen, menu, component)
        grid = screen_theme.get("grid")
        if grid is not None:
            menu.row_rects = self._grid_rectangles(grid, len(menu.items), screen.get_size(), screen_theme)
        else:
            menu.row_rects = self._layout_rectangles(menu, screen_theme, screen.get_size())
        title = self.title_font.render(menu.title, True, (255, 255, 255) if high_contrast else tuple(component.get("title_color", self._color(colors, "text"))))
        layout_screen = "save_slots" if menu.kind == "slots" else "menu"
        title_spec = component_layout(
            self.style.get("layouts", {}), layout_screen, "title", screen.get_size()
        )
        if title_spec:
            title_rect = pygame.Rect(
                resolve_rect(
                    title_spec,
                    safe_area_rect(self.style.get("layouts", {}), screen.get_size()),
                    scale=get_ui_scale(),
                )
            )
            title_alignment = screen_theme.get("title_alignment") or component.get("title_alignment", "center")
            padding = ui_size(component.get("title_padding", 8))
            if title_alignment == "left":
                title_rect.left += padding
                title_box = title.get_rect(midleft=(title_rect.left, title_rect.centery))
            elif title_alignment == "right":
                title_rect.right -= padding
                title_box = title.get_rect(midright=(title_rect.right, title_rect.centery))
            else:
                title_box = title.get_rect(center=title_rect.center)
            menu.title_rect = title_rect.copy()
            screen.blit(title, title_box)
        else:
            title_y = ui_size(menu_theme.get("title_y", 112))
            if menu.row_rects:
                first_top = min(rect.top for rect in menu.row_rects)
                title_y = min(title_y, first_top - title.get_height() // 2 - ui_size(10))
            title_y = max(title.get_height() // 2 + ui_size(8), title_y)
            title_box = title.get_rect(center=(width // 2, title_y))
            menu.title_rect = title_box.copy()
            screen.blit(title, title_box)
        buttons = screen_theme.get("buttons", {})
        normal_name = buttons.get("normal") if isinstance(buttons, dict) else None
        hovered_name = buttons.get("hovered") if isinstance(buttons, dict) else None
        if normal_name is None:
            normal_name = hovered_name
        if hovered_name is None:
            hovered_name = normal_name
        radius = max(0, ui_size(component.get("radius", menu_theme.get("border_radius", 8))))
        skin_base = self.style.get("skins", {}).get("button", {})
        states = dict(skin_base.get("states", {})) if isinstance(skin_base, dict) else {}
        menu_states = item_component.get("states", {})
        if isinstance(menu_states, dict):
            states.update(menu_states)
        skin = {**skin_base, "states": states} if isinstance(skin_base, dict) else {"states": states}
        skin["fit"] = item_component.get("button_fit", skin.get("fit", "stretch"))
        skin["nine_slice"] = item_component.get("nine_slice", skin.get("nine_slice"))
        skin["radius"] = item_component.get("radius", skin.get("radius", radius))
        skin["border_width"] = item_component.get("border_width", skin.get("border_width", 1))
        skin["opacity"] = item_component.get("opacity", skin.get("opacity", 1.0))
        if high_contrast:
            skin["image"] = None
            for state_name, color in (("normal", [0, 0, 0, 255]), ("hover", [30, 30, 30, 255]),
                                      ("focus", [50, 45, 20, 255]), ("selected", [50, 45, 20, 255]),
                                      ("pressed", [50, 45, 20, 255]), ("disabled", [45, 45, 45, 255])):
                current = states.get(state_name)
                current = dict(current) if isinstance(current, dict) else {}
                current.update({"color": color, "image": None, "border_color": [255, 255, 255]})
                states[state_name] = current
        buttons = screen_theme.get("buttons", {})
        if isinstance(buttons, dict):
            if states.get("normal") is None and buttons.get("normal"):
                states["normal"] = {"image": buttons.get("normal")}
            if states.get("hover") is None and buttons.get("hovered"):
                states["hover"] = {"image": buttons.get("hovered")}
        for index, (rect, item) in enumerate(zip(menu.row_rects, menu.items)):
            selected = index == menu.selected
            persistent = item.get("persistent_selected", False)
            image_name = (hovered_name if selected else normal_name) if not high_contrast else None
            if image_name:
                current = dict(skin.get("states", {}))
                current["focus" if selected else "normal"] = {"image": image_name}
                skin["states"] = current
            fill_key = "hover" if selected else "selected" if persistent else "normal"
            fallback_color = (
                item_component.get("selected_color" if fill_key == "selected" else "normal_color", self._color(colors, fill_key))
                if menu.kind == "slots" else self._color(colors, fill_key)
            )
            if selected and hasattr(menu, "preview_state"):
                button_state = menu.preview_state
            else:
                button_state = "selected" if persistent else "focus" if selected else "normal"
            draw_skin(screen, rect, self.assets, skin, button_state, fallback_color)
            FallbackMenuRenderer._draw_menu_item(
                screen,
                rect,
                item,
                selected,
                item_font,
                detail_font,
                label_alignment=label_alignment,
                text_color=(255, 255, 255) if high_contrast else item_component.get("item_color", self._color(colors, "text")),
                detail_color=(255, 255, 255) if high_contrast else item_component.get("detail_color", self._color(colors, "muted")),
                padding=item_component.get("padding", 8),
                preview_fit=style_component(self.style, "save_slots").get("thumbnail_fit", "contain"),
            )

    def _layout_rectangles(self, menu, screen_theme, screen_size):
        layouts = self.style.get("layouts", {})
        screen_name = "save_slots" if menu.kind == "slots" else "menu"
        spec = component_layout(layouts, screen_name, "items", screen_size)
        if not spec:
            return self._vertical_rectangles(
                self.theme.get("menu", DEFAULT_THEME["menu"]), screen_theme,
                len(menu.items), screen_size,
            )
        component = style_component(self.style, "menu")
        bounds = safe_area_rect(layouts, screen_size)
        region = resolve_rect(spec, bounds, scale=get_ui_scale())
        child_spec = {
            key: value for key, value in spec.items()
            if key not in {"anchor", "x", "y", "left", "right", "top", "bottom", "width", "height", "constraints"}
        }
        menu_theme = self.theme.get("menu", DEFAULT_THEME["menu"])
        child_spec.setdefault("item_size", component.get("row_height", menu_theme.get("row_height", 56)))
        child_spec.setdefault("gap", component.get("row_gap", menu_theme.get("row_gap", 9)))
        if screen_theme.get("button_height") is not None:
            child_spec["item_size"] = screen_theme["button_height"]
        if screen_theme.get("row_gap") is not None:
            child_spec["gap"] = screen_theme["row_gap"]
        rectangles = layout_children(
            child_spec, region, len(menu.items), scale=get_ui_scale()
        )
        if child_spec.get("type") == "grid" and screen_theme.get("grid") is not None:
            return self._grid_rectangles(screen_theme["grid"], len(menu.items), screen_size, screen_theme)
        return [pygame.Rect(rect) for rect in rectangles]

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
