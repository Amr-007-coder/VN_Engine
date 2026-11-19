"""Off-screen Pygame rendering for the editor's visual theme preview."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pygame

from engine.assets import AssetManager
from engine.config import COLORS, FONTS, load_assets, load_ui_fonts
from engine.layout import component_layout, layout_children, resolve_rect, safe_area_rect
from engine.menu import Menu
from engine.menu_renderer import DeclarativeMenuRenderer
from engine.skin import control_state, draw_skin, fit_surface
from engine.style import style_component
from engine.theme import resolve_theme
from engine.ui import (
    Button, Textbox, dialogue_textbox_rect, draw_dialogue_control,
    draw_style_panel, layout_dialogue_controls, render_history_panel,
)
from engine.ui_scale import DEFAULT_UI_SCALE, get_ui_scale, set_ui_scale, ui_size


@dataclass
class PreviewFrame:
    surface: pygame.Surface
    regions: dict[str, list[pygame.Rect]]
    diagnostics: list[str]


class _PreviewAssets(AssetManager):
    def __init__(self, project_assets):
        project_assets = Path(project_assets) if project_assets else None
        mod_directory = project_assets / ".theme-preview-mods" if project_assets else Path.cwd() / ".theme-preview-mods"
        super().__init__(project_assets=project_assets, mod_directory=mod_directory)
        self.diagnostics = []
        self._diagnostic_keys = set()

    def _report(self, kind, name):
        key = (kind, str(name))
        if key not in self._diagnostic_keys:
            self._diagnostic_keys.add(key)
            self.diagnostics.append(f"Missing {kind} asset: {name}")

    def load_image(self, name, cache=True):
        try:
            return super().load_image(name, cache=cache)
        except (FileNotFoundError, pygame.error):
            self._report("image (missing or unreadable)", name)
            raise

    def load_font(self, name, size, system_fallback=True):
        if name and self.find_path("font", name) is None:
            self._report("font (using system fallback)", name)
        return super().load_font(name, size, system_fallback=system_fallback)


class OffscreenThemeRenderer:
    """Render representative themed screens without opening a Pygame window."""

    def __init__(self, project_root=None):
        self.project_root = Path(project_root).resolve() if project_root else None
        assets_root = self.project_root / "assets" if self.project_root else None
        self.assets = _PreviewAssets(assets_root)

    def render(self, style, screen_name, viewport, selected_component, selected_state="normal"):
        pygame.font.init()
        viewport = tuple(max(1, int(value)) for value in viewport)
        self.assets.diagnostics.clear()
        self.assets._diagnostic_keys.clear()
        saved_scale = get_ui_scale()
        saved_fonts = {name: getattr(FONTS, name) for name in ("normal_text", "char_name", "button_text", "dialogue_controls")}
        saved_colors = {name: getattr(COLORS, name) for name in ("background", "text", "text_highlight", "panel")}
        try:
            set_ui_scale(DEFAULT_UI_SCALE)
            theme = resolve_theme(style.get("theme", {}))
            load_assets(self.assets, theme)
            load_ui_fonts(
                self.assets, theme, style,
                {"dialogue_font_scale": 1.0, "speaker_font_scale": 1.0},
            )
            frame = pygame.Surface(viewport, pygame.SRCALPHA)
            self._draw_scene_background(frame, style, theme)
            regions = {}
            if screen_name == "menu":
                self._render_menu(frame, style, theme, selected_component, selected_state, regions)
            elif screen_name == "save_slots":
                self._render_save_slots(frame, style, theme, selected_component, selected_state, regions)
            elif screen_name == "dialogue":
                self._render_dialogue(frame, style, theme, selected_component, selected_state, regions)
            elif screen_name == "history":
                self._render_history(frame, style, selected_component, regions)
            elif screen_name == "overlays":
                self._render_overlay(frame, style, selected_component, selected_state, regions)
            return PreviewFrame(frame, regions, list(self.assets.diagnostics))
        except Exception as error:
            return PreviewFrame(self._error_surface(viewport, error), {}, list(self.assets.diagnostics))
        finally:
            set_ui_scale(saved_scale)
            for name, font in saved_fonts.items():
                setattr(FONTS, name, font)
            for name, color in saved_colors.items():
                setattr(COLORS, name, color)

    @staticmethod
    def _rect(style, screen_name, component, viewport):
        layouts = style.get("layouts", {})
        spec = component_layout(layouts, screen_name, component, viewport)
        bounds = safe_area_rect(layouts, viewport)
        return pygame.Rect(resolve_rect(spec, bounds, scale=get_ui_scale()))

    def _draw_scene_background(self, surface, style, theme):
        scene = style_component(style, "scene")
        surface.fill(tuple(scene.get("background_color", theme.get("colors", {}).get("background", (30, 30, 45)))))
        image_name = scene.get("background_image")
        if not image_name:
            return
        try:
            image = self.assets.load_image(image_name)
        except (FileNotFoundError, pygame.error):
            return
        surface.blit(fit_surface(image, surface.get_size(), scene.get("background_fit", "cover")), (0, 0))

    def _render_menu(self, surface, style, theme, selected_component, selected_state, regions):
        items = [
            {"label": "Dialogue speed", "detail": "Normal", "action": "dialogue_speed"},
            {"label": "Auto advance", "detail": "Off", "action": "auto_advance"},
            {"label": "Text size", "detail": "100%", "action": "text_size"},
            {"label": "Interface size", "detail": "100%", "action": "ui_size"},
            {"label": "High contrast", "detail": "Off", "action": "high_contrast"},
            {"label": "Screen reader", "detail": "Off", "action": "speech"},
            {"label": "Back", "action": "back"},
        ]
        menu = Menu("Settings", items, kind="settings")
        menu.selected = min(1, len(menu.items) - 1)
        menu.preview_state = selected_state if selected_component == "items" else "focus"
        panel_spec = component_layout(style.get("layouts", {}), "menu", "panel", surface.get_size())
        if panel_spec:
            menu.panel_rect = pygame.Rect(resolve_rect(panel_spec, safe_area_rect(style.get("layouts", {}), surface.get_size()), scale=get_ui_scale()))
        renderer = DeclarativeMenuRenderer(self.assets, theme, style)
        renderer.render(surface, menu)
        regions.update({"title": [pygame.Rect(getattr(menu, "title_rect", (0, 0, 1, 1)))],
                        "items": list(menu.row_rects)})
        if hasattr(menu, "panel_rect"):
            regions["panel"] = [menu.panel_rect.copy()]

    def _render_save_slots(self, surface, style, theme, selected_component, selected_state, regions):
        menu = Menu("Save Slots", [
            {"label": "Autosave", "detail": "Empty", "action": "slot_0"},
            {"label": "Slot 1", "detail": "Empty", "action": "slot_1"},
            {"label": "Slot 2", "detail": "Empty", "action": "slot_2"},
            {"label": "Slot 3", "detail": "Empty", "action": "slot_3"},
        ], kind="slots")
        menu.selected = 1
        menu.preview_state = selected_state if selected_component == "items" else "focus"
        renderer = DeclarativeMenuRenderer(self.assets, theme, style)
        renderer.render(surface, menu)
        regions["title"] = [pygame.Rect(getattr(menu, "title_rect", (0, 0, 1, 1)))]
        regions["items"] = list(menu.row_rects)
        spec = component_layout(style.get("layouts", {}), "save_slots", "actions", surface.get_size())
        if spec:
            bounds = safe_area_rect(style.get("layouts", {}), surface.get_size())
            action_region = pygame.Rect(resolve_rect(spec, bounds, scale=get_ui_scale()))
            child_spec = {key: value for key, value in spec.items() if key not in {
                "anchor", "x", "y", "left", "right", "top", "bottom", "width", "height", "constraints"
            }}
            action_rects = [pygame.Rect(rect) for rect in layout_children(child_spec, action_region, 3, scale=get_ui_scale())]
            component = style_component(style, "save_slots")
            skin_base = style.get("skins", {}).get("button", {})
            states = dict(skin_base.get("states", {})) if isinstance(skin_base, dict) else {}
            states.update(component.get("states", {}))
            skin = {**skin_base, "states": states}
            skin.update({"radius": component.get("radius", 5), "border_width": component.get("border_width", 1),
                         "fit": component.get("fit", skin.get("fit", "stretch")),
                         "nine_slice": component.get("nine_slice", skin.get("nine_slice")),
                         "opacity": component.get("opacity", 1.0)})
            font = self.assets.load_font(component.get("font", "standard.ttf"), ui_size(component.get("font_size", 18)))
            labels = ("Load", "Save", "Delete")
            for index, (rect, label) in enumerate(zip(action_rects, labels)):
                state = selected_state if selected_component == "actions" and index == 0 else "normal"
                draw_skin(surface, rect, self.assets, skin, state, component.get("normal_color", (18, 18, 29)))
                text = font.render(label, True, component.get("text_color", COLORS.text))
                surface.blit(text, text.get_rect(center=rect.center))
            regions["actions"] = action_rects

    def _render_dialogue(self, surface, style, theme, selected_component, selected_state, regions):
        controls = style.get("dialogue_buttons", {})
        controls_visible = any(isinstance(value, dict) and value.get("visible", False) for value in controls.values())
        textbox_rect = dialogue_textbox_rect(style.get("layouts", {}), surface.get_size(), controls_visible)
        textbox_style = style_component(style, "textbox")
        dialogue_style = style_component(style, "dialogue_text")
        image_name = textbox_style.get("background_image") or theme.get("textbox", {}).get("background")
        image = None
        if image_name:
            try:
                image = self.assets.load_image(image_name)
            except FileNotFoundError:
                image = None
        color = textbox_style.get("background_color") or theme.get("textbox", {}).get("color")
        textbox = Textbox(
            *textbox_rect,
            panel_color=tuple(color) if color is not None else COLORS.panel,
            panel_image=image,
            panel_opacity=textbox_style.get("opacity", theme.get("textbox", {}).get("opacity", 0.95)),
            style={**textbox_style, **dialogue_style},
        )
        textbox.start_text("Ari", "I thought the old observatory would be empty. The stars seem much closer from here.")
        textbox.reveal_all()
        textbox.render()
        surface.blit(textbox.surface, textbox.rect)
        regions["textbox"] = [textbox.rect.copy()]
        name_rect = FONTS.char_name.render(" Ari ", True, COLORS.text_highlight).get_rect(
            topleft=(textbox.rect.left + ui_size(dialogue_style.get("speaker", {}).get("margin_left", 40)),
                     textbox.rect.top + ui_size(dialogue_style.get("speaker", {}).get("margin_top", 15)))
        )
        regions["speaker"] = [name_rect]
        text_style = dialogue_style.get("text", {})
        regions["dialogue_text"] = [pygame.Rect(
            textbox.rect.left + ui_size(text_style.get("margin_left", 40)),
            textbox.rect.top + ui_size(text_style.get("margin_top", 55)),
            max(1, textbox.rect.width - ui_size(text_style.get("margin_left", 40)) * 2),
            max(1, textbox.rect.height - ui_size(text_style.get("margin_top", 55))),
        )]
        self._render_choices(surface, style, theme, textbox, selected_component, selected_state, regions)
        self._render_dialogue_controls(surface, style, theme, textbox, selected_component, selected_state, regions)
        self._render_pause_control(surface, style, theme, selected_component, selected_state, regions)

    def _render_choices(self, surface, style, theme, textbox, selected_component, selected_state, regions):
        viewport = surface.get_size()
        layouts = style.get("layouts", {})
        spec = component_layout(layouts, "dialogue", "choices", viewport)
        bounds = safe_area_rect(layouts, viewport)
        region = pygame.Rect(resolve_rect(spec, bounds, scale=get_ui_scale()))
        region.bottom = min(region.bottom, textbox.rect.top - ui_size(20))
        child_spec = {key: value for key, value in spec.items() if key not in {
            "anchor", "x", "y", "left", "right", "top", "bottom", "width", "height", "constraints"
        }}
        rects = [pygame.Rect(rect) for rect in layout_children(child_spec, region, 3, scale=get_ui_scale())]
        choice_style = dict(style_component(style, "choices"))
        skin_base = style.get("skins", {}).get("button", {})
        states = dict(skin_base.get("states", {})) if isinstance(skin_base, dict) else {}
        states.update(choice_style.get("states", {}))
        skin = {**skin_base, "states": states} if isinstance(skin_base, dict) else {"states": states}
        skin["radius"] = choice_style.get("radius", skin.get("radius", 6))
        skin["border_width"] = choice_style.get("border_width", skin.get("border_width", 0))
        skin["border_color"] = choice_style.get("border_color", skin.get("border_color"))
        skin["fit"] = choice_style.get("fit", skin.get("fit", "stretch"))
        skin["nine_slice"] = choice_style.get("nine_slice", skin.get("nine_slice"))
        skin["opacity"] = choice_style.get("opacity", skin.get("opacity", 1.0))
        labels = ("Ask about the observatory", "Tell Ari about the letter", "Leave before it gets dark")
        for index, (rect, label) in enumerate(zip(rects, labels)):
            button = Button(*rect, style=choice_style, skin=skin, asset_manager=self.assets)
            active = selected_component == "choices" and index == 0
            state = selected_state if active else "focus" if index == 0 else "normal"
            button.active = state != "disabled"
            button.render(label, hovered=state == "hover", focused=state == "focus",
                          pressed=state == "pressed", selected=state == "selected")
            if state == "focus":
                pygame.draw.rect(button.surface, choice_style.get("focus_border_color", theme.get("colors", {}).get("accent", COLORS.text_highlight)),
                                 button.surface.get_rect(), width=max(1, ui_size(choice_style.get("focus_border_width", 3))),
                                 border_radius=ui_size(choice_style.get("radius", 6)))
            surface.blit(button.surface, button.rect)
        regions["choices"] = rects

    def _render_dialogue_controls(self, surface, style, theme, textbox, selected_component, selected_state, regions):
        config = style.get("dialogue_buttons", {})
        component = style_component(style, "dialogue_controls")
        entries = layout_dialogue_controls(
            textbox.rect, surface.get_size(), component, style.get("layouts", {}), config,
            can_go_back=True,
        )
        skin_base = style.get("skins", {}).get("button", {})
        selected_control = "auto" if any(name == "auto" for name, *_rest in entries) else (entries[0][0] if entries else None)
        for name, label, rect, enabled in entries:
            active = selected_component == "controls" and name == selected_control
            selected = False
            state = selected_state if active else control_state(disabled=not enabled, selected=selected)
            draw_dialogue_control(surface, rect, label, state, enabled, component,
                                  config.get(name, {}), skin_base, self.assets,
                                  theme.get("colors", {}), style)
        regions["controls"] = [entry[2] for entry in entries]

    def _render_pause_control(self, surface, style, theme, selected_component, selected_state, regions):
        rect = self._rect(style, "dialogue", "pause_control", surface.get_size())
        component = style_component(style, "pause_control")
        skin_base = style.get("skins", {}).get("pause_control", {})
        states = dict(skin_base.get("states", {})) if isinstance(skin_base, dict) else {}
        states.update(component.get("states", {}))
        skin = {**skin_base, "states": states} if isinstance(skin_base, dict) else {"states": states}
        image_name = component.get("image") or theme.get("pause_button", {}).get("image") or "pause.png"
        state = selected_state if selected_component == "pause_control" else "normal"
        draw_skin(surface, rect, self.assets, skin, state, component.get("background_color"))
        if image_name:
            try:
                image = self.assets.load_image(image_name)
                surface.blit(fit_surface(image, rect.size, component.get("fit", "contain"), component.get("nine_slice")), rect)
            except FileNotFoundError:
                pass
        regions["pause_control"] = [rect]

    def _render_history(self, surface, style, selected_component, regions):
        panel = self._rect(style, "history", "panel", surface.get_size())
        history = style_component(style, "history")
        heading_font = self.assets.load_font(history.get("font", "standard.ttf"), ui_size(history.get("heading_font_size", 28)))
        body_font = self.assets.load_font(history.get("font", "standard.ttf"), ui_size(history.get("font_size", 20)))
        footer_font = FONTS.button_text
        entries = [
            {"speaker": "Ari", "text": "I did not expect anyone else to find this place."},
            {"speaker": "Mika", "text": "The map in the letter led me here. I think it belonged to your grandmother."},
            {"speaker": "Ari", "text": "Then we should find out what she wanted us to see."},
        ]
        render_history_panel(surface, panel, entries, 0, history, heading_font, body_font, footer_font)
        regions["panel"] = [panel]

    def _render_overlay(self, surface, style, selected_component, selected_state, regions):
        component_name = selected_component if selected_component in {"confirmation", "story_input", "variable_inspector"} else "confirmation"
        rect = self._rect(style, "overlays", component_name, surface.get_size())
        overlay = style_component(style, "overlays")
        shade = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        shade.fill(tuple(overlay.get("scrim_color", (0, 0, 0, 190))))
        surface.blit(shade, (0, 0))
        draw_style_panel(surface, rect, style, "overlays")
        heading_font = self.assets.load_font(overlay.get("font", "standard.ttf"), ui_size(overlay.get("title_font_size", 28)))
        body_font = self.assets.load_font(overlay.get("font", "standard.ttf"), ui_size(overlay.get("body_font_size", 20)))
        title = {"confirmation": "Are you sure?", "story_input": "Story Input", "variable_inspector": "Test Variables"}[component_name]
        heading = heading_font.render(title, True, overlay.get("title_color", COLORS.text_highlight))
        surface.blit(heading, heading.get_rect(midtop=(rect.centerx, rect.top + ui_size(overlay.get("heading_top", 18)))))
        if component_name == "confirmation":
            body = "Overwrite the current save with this progress?"
            lines = []
            current = ""
            for word in body.split():
                candidate = f"{current} {word}".strip()
                if current and body_font.size(candidate)[0] > rect.width - ui_size(overlay.get("padding", 24)) * 2:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                lines.append(current)
            action_spec = component_layout(style.get("layouts", {}), "overlays", "confirmation_actions", surface.get_size())
            action_rects = [pygame.Rect(value) for value in layout_children(action_spec, rect, 2, scale=get_ui_scale())]
            message_top = min(rect.top + ui_size(60), min((value.top for value in action_rects), default=rect.bottom - ui_size(54)) - body_font.get_linesize())
            for index, line in enumerate(lines):
                text = body_font.render(line, True, overlay.get("text_color", COLORS.text))
                surface.blit(text, text.get_rect(center=(rect.centerx, message_top + index * body_font.get_linesize())))
            labels = ("Yes", "Cancel")
        elif component_name == "story_input":
            body = body_font.render("What should Ari call the place?", True, overlay.get("text_color", COLORS.text))
            surface.blit(body, body.get_rect(midtop=(rect.centerx, rect.top + ui_size(62))))
            field_spec = component_layout(style.get("layouts", {}), "overlays", "story_input_field", surface.get_size())
            field = pygame.Rect(resolve_rect(field_spec, rect, scale=get_ui_scale()))
            pygame.draw.rect(surface, tuple(overlay.get("field_color", (8, 9, 16))), field, border_radius=ui_size(overlay.get("field_radius", 5)))
            pygame.draw.rect(surface, tuple(overlay.get("field_border_color", (112, 86, 101))), field, width=max(1, ui_size(overlay.get("field_border_width", 1))), border_radius=ui_size(overlay.get("field_radius", 5)))
            help_text = body_font.render("Type your answer, then press Enter", True, overlay.get("text_color", COLORS.text))
            surface.blit(help_text, help_text.get_rect(midbottom=(rect.centerx, rect.bottom - ui_size(14))))
            action_rects, labels = [], ()
            regions["story_input"] = [field]
        else:
            for index, line in enumerate(("chapter = 'observatory'", "trust = 2", "found_letter = True")):
                body = body_font.render(line, True, overlay.get("value_color", (205, 214, 228)))
                surface.blit(body, body.get_rect(midtop=(rect.centerx, rect.top + ui_size(72) + index * body_font.get_linesize())))
            action_rects, labels = [], ()
        if action_rects:
            skin_base = style.get("skins", {}).get("button", {})
            states = dict(skin_base.get("states", {})) if isinstance(skin_base, dict) else {}
            states.update(overlay.get("states", {}))
            skin = {**skin_base, "states": states}
            skin.update({"radius": overlay.get("radius", 10), "opacity": overlay.get("opacity", 1.0), "nine_slice": overlay.get("nine_slice")})
            button_font = self.assets.load_font(overlay.get("font", "standard.ttf"), ui_size(overlay.get("button_font_size", 18)))
            for index, (button_rect, label) in enumerate(zip(action_rects, labels)):
                state = selected_state if selected_component == component_name and index == 0 else "normal"
                draw_skin(surface, button_rect, self.assets, skin, state, overlay.get("button_color", (73, 50, 65)))
                rendered = button_font.render(label, True, overlay.get("text_color", COLORS.text))
                surface.blit(rendered, rendered.get_rect(center=button_rect.center))
            regions[component_name] = [rect, *regions.get(component_name, []), *action_rects]
        else:
            regions[component_name] = [rect, *regions.get(component_name, [])]

    @staticmethod
    def _error_surface(viewport, error):
        surface = pygame.Surface(viewport, pygame.SRCALPHA)
        surface.fill((24, 20, 28, 255))
        pygame.draw.rect(surface, (138, 63, 71), surface.get_rect().inflate(-24, -24), width=2, border_radius=8)
        if pygame.font.get_init():
            font = pygame.font.Font(None, 24)
            lines = ["Theme preview could not render", str(error)]
            for index, line in enumerate(lines):
                rendered = font.render(line[:120], True, (245, 220, 220))
                surface.blit(rendered, (36, 36 + index * 32))
        return surface
