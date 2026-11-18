import asyncio
import base64
from io import BytesIO
import json
import os
import pygame
import math
import random
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from engine.assets import AssetManager
from engine.character_layer import CharacterLayer
from engine.config import COLORS, FONTS, load_assets
from engine.embedded import bytes_for_path
from engine.loader import PATHS, loader
from engine.menu import Menu
from engine.menu_renderer import (
    DeclarativeMenuRenderer,
    FallbackMenuRenderer,
    MenuRenderer,
)
from engine.parser import parse
from engine.platform_runtime import (
    centered_window_position,
    configure_webview_viewport,
    fit_window_size,
    primary_display_size,
    set_process_dpi_awareness,
    sync_webview_canvas,
)
from engine.progress import ProgressStore
from engine.project import ProjectConfig
from engine.save_system import SaveSystem
from engine.settings import SettingsStore
from engine.speech import SpeechAnnouncer
from engine.story import StoryFlow
from engine.theme import resolve_theme
from engine.ui_text import translate_label, translate_ui
from engine.ui import Button, Textbox
from engine.ui_scale import set_ui_scale, ui_size
from engine.validator import StoryValidator


ANDROID_WEBVIEW_HOOK_VERSION = 1


def _read_engine_version() -> str:
    path = PATHS.engine_data / "version.txt"
    data = bytes_for_path(path, ((PATHS.engine_data, "engine/data"),))
    if data is None:
        data = path.read_bytes()
    return data.decode("utf-8").strip()


def _save_time(saved_game):
    try:
        return datetime.fromisoformat(saved_game["saved_at"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return 0


def _intro_warning_card_needed(message: str, warning_image, headphones_image) -> bool:
    return bool(message.strip()) or warning_image is not None or headphones_image is not None


class Engine:
    """Owns game state and actions; project config and renderers own presentation."""

    def __init__(
        self,
        story_file: str | None = None,
        window_size: tuple[int, int] | None = None,
        caption: str | None = None,
        fps: int = 60,
        project_config: ProjectConfig | None = None,
        menu_renderer: MenuRenderer | None = None,
        menu_renderer_factory=None,
    ):
        self.project = project_config or ProjectConfig.load()
        self.story_file = story_file or self.project.story_file
        self.allow_fullscreen = sys.platform != "emscripten"
        self.webview_platform = None
        if not self.allow_fullscreen:
            try:
                import platform as webview_platform

                self.webview_platform = webview_platform
                viewport_size = configure_webview_viewport(self.project, webview_platform)
                if viewport_size is not None:
                    window_size = viewport_size
            except (AttributeError, ImportError, TypeError, ValueError):
                self.webview_platform = None
        window = self.project.window
        self.window_size = window_size or (int(window["width"]), int(window["height"]))
        self.windowed_size = self.window_size
        self.caption = caption or window["caption"]
        self.fps = fps

        self.running = False
        self.initialized = False
        self.screen = None
        self.clock = None
        self.story_data = None
        self.assets = None
        self.theme = resolve_theme(self.project.theme)
        self.has_project_theme = any(key != "textbox" for key in self.project.theme)
        self.renderer_override = menu_renderer
        self.renderer_factory = menu_renderer_factory
        self.menu_renderer = None

        self.settings = SettingsStore(self.project.user_data_dir)
        self.save_system = SaveSystem(
            slot_count=self.project.values["save_slots"],
            autosave_slot_count=self.project.values["autosave_slots"],
            user_data_dir=self.project.user_data_dir,
        )
        self.progress_store = ProgressStore(self.project.user_data_dir)
        self.translation_tables = {}
        self.speech_announcer = None
        self._speech_unavailable_reported = False
        self.textbox = None
        self.pause_button_rect = pygame.Rect(0, 0, 0, 0)
        self.pause_button_image = None
        self.scaled_pause_button_image = None
        self.flow = None
        self.choice_buttons = []
        self.focused_choice_index = 0
        self.background_id = None
        self.background_image = None
        self.character_layer = None
        self.active_character = None
        self.music_track = None
        self.voice_sound = None
        self.voice_channel = None
        self.current_voice = None
        self.dialogue_history = []
        self.history_visible = False
        self.history_scroll = 0
        self.dialogue_back_stack = []
        self.choice_history = []
        self.visited_choices = set()
        self.seen_dialogues = set()
        self.visited_dialogues = set()
        self._current_dialogue_was_seen = False
        self.auto_mode = False
        self.skip_mode = None
        self._auto_advance_deadline = None
        self._choice_timeout_deadline = None
        self._choice_timeout_paused_remaining = None
        self._controller_axis_state = {}
        self.play_time_seconds = 0.0
        self._play_started_at = None
        self._last_autosave_at = None
        self.dialogue_button_rects = {}
        self.confirmation = None
        self.confirmation_button_rects = {}
        self.save_name_prompt = None
        self.story_input = None
        self.fade_effect = None
        self.shake_effect = None
        self.autosave_notice_until = 0
        self._preview_surface = None
        self.editor_test_context = None
        self.variable_inspector_visible = False
        self.variable_inspector_index = 0
        self.variable_inspector_edit = None

        self.mode = "main_menu"
        self.menu_origin = None
        self.return_mode = "main_menu"
        self.slot_context = "load"
        self.selected_slot = None
        self.copy_source_slot = None
        self._slot_button_rects = {}
        self._slot_button_enabled = {}
        self._slot_preview_cache = {}
        self._slot_infos = []
        self.active_menu = None
        self.status_message = ""

        self.main_menu = self._make_menu("main")
        self.pause_menu = self._make_menu("pause")
        self.settings_menu = self._make_menu("settings")
        self._settings_all_items = []
        self.settings_offset = 0
        self.settings_selected = 0
        self._settings_panel_rect = pygame.Rect(0, 0, 0, 0)
        self._settings_scroll_track = pygame.Rect(0, 0, 0, 0)
        self._settings_scroll_thumb = pygame.Rect(0, 0, 0, 0)
        slot_config = self.project.menus["slots"]
        self.slot_menu = Menu(slot_config["title_load"], kind="slots")
        self.credits_menu = Menu("Credits", kind="credits")
        self.credits_entries = []
        self.credits_offset = 0
        self.credits_selected = 0
        self.extras_menu = Menu("Extras", kind="extras")
        self.gallery_menu = Menu("CG Gallery", kind="gallery")
        self.music_gallery_menu = Menu("Music Room", kind="music_gallery")
        self.achievement_menu = Menu("Achievements", kind="achievements")
        self.routes_menu = Menu("Routes", kind="routes")
        self.mods_menu = Menu("Installed Mods", kind="mods")
        self.mod_details_menu = Menu("Mod Details", kind="mod_details")
        self.mod_records = []
        self.selected_mod_key = None
        self.mod_origin = "extras"
        self._mod_detail_buttons = []
        self.gallery_entries = []
        self.gallery_offset = 0
        self.gallery_selected = 0
        self.gallery_image = None
        self.gallery_image_label = ""
        self.progress_entries = []
        self.progress_offset = 0
        self.progress_selected = 0
        self.progress_title = ""
        self.progress_category = ""
        self._progress_scroll_track = pygame.Rect(0, 0, 0, 0)
        self._progress_scroll_thumb = pygame.Rect(0, 0, 0, 0)
        self.extras_origin = "main_menu"

    def run(self):
        self.initialize()
        self.running = True
        try:
            if self.editor_test_context is None:
                self._play_intro()
            else:
                start_id, initial_variables = self.editor_test_context
                self._start_new_game(start_id, initial_variables)
            while self.running:
                self.step()
                self.clock.tick(self.fps)
        finally:
            self.shutdown()

    def step(self):
        """Advance and draw one frame; async hosts should yield after each call."""
        self._handle_events()
        self._update()
        self._render()

    def initialize(self):
        """Load the project and open Pygame before starting a desktop or async loop."""
        if not self.initialized:
            self._initialize()

    def _make_menu(self, name):
        config = self.project.menus[name]
        items = [
            {**item, "_ui_translation_key": f"project.menus.{name}.items.{index}.label"}
            for index, item in enumerate(config["items"])
        ]
        for index, item in enumerate(items):
            if "detail" in item:
                item["_ui_detail_translation_key"] = f"project.menus.{name}.items.{index}.detail"
        if name in {"main", "pause"} and not any(item.get("action") == "open_extras" for item in items):
            back_index = next((index for index, item in enumerate(items) if item.get("action") in {"quit", "return_to_main_menu"}), len(items))
            items.insert(back_index, {"label": "Extras", "action": "open_extras"})
        menu = Menu(config["title"], items, kind=name)
        menu._ui_translation_key = f"project.menus.{name}.title"
        return menu

    def _initialize(self):
        # Project files are resolved and validated before pygame opens a window.
        self.assets = AssetManager(self.project.assets_dir, self.project.user_data_dir / "mods")
        self.progress_store.load()
        self.story_data = self.project.load_story(self.story_file)
        self.translation_tables = self.project.load_translation_tables(self.story_data)
        StoryValidator.validate_or_raise(
            self.story_data,
            self.project.assets_dir,
            PATHS.engine_assets,
            self.assets,
        )
        localization = self.story_data.get("localization", {})
        self.default_locale = localization.get("default_locale", "en")
        self.available_locales = localization.get("locales", {self.default_locale: self.default_locale})
        if os.environ.get("VN_EDITOR_TEST_MODE") == "1":
            start_id = os.environ.get("VN_EDITOR_TEST_START_DIALOGUE", self.story_data["start"])
            try:
                initial_variables = json.loads(os.environ.get("VN_EDITOR_TEST_VARIABLES", "{}"))
            except json.JSONDecodeError as error:
                raise ValueError("Editor test variables are not valid JSON.") from error
            if not isinstance(initial_variables, dict):
                raise ValueError("Editor test variables must be a JSON object.")
            if start_id not in self.story_data.get("dialogues", {}):
                raise ValueError(f"Editor test start refers to missing dialogue {start_id!r}.")
            self.editor_test_context = (start_id, initial_variables)
        self.settings.load()
        if self.settings.values.get("locale") not in self.available_locales:
            self.settings.set("locale", self.default_locale)
            self.settings.save()
        set_ui_scale(self.settings.values["ui_scale"])
        self.auto_mode = self.settings.values["auto_advance"]

        set_process_dpi_awareness()
        pygame.init()
        try:
            if self.allow_fullscreen:
                display_size = primary_display_size(pygame.display)
                if display_size:
                    self.windowed_size = fit_window_size(self.windowed_size, display_size)
                    self.window_size = self.windowed_size
            self.controllers = []
            try:
                pygame.joystick.init()
                for index in range(pygame.joystick.get_count()):
                    controller = pygame.joystick.Joystick(index)
                    controller.init()
                    self.controllers.append(controller)
            except pygame.error:
                self.controllers = []
            self.character_layer = CharacterLayer(
                self.assets,
                self.story_data.get("character_defaults", {}),
                self.project.values.get("characters", {}),
            )
            load_assets(self.assets, self.theme)
            self._apply_comfort_font_sizes()
            flags = pygame.FULLSCREEN if self.allow_fullscreen and self.settings.values["fullscreen"] else 0
            self.screen = pygame.display.set_mode(self.windowed_size, flags)
            if self.allow_fullscreen and not flags:
                display_size = primary_display_size(pygame.display)
                if display_size:
                    pygame.display.set_window_position(
                        *centered_window_position(self.screen.get_size(), display_size)
                    )
            window_icon = self.assets.load_image(self.project.icon) if self.project.icon else loader.load_image("logo.png")
            pygame.display.set_icon(window_icon)
            self.window_size = self.screen.get_size()
            sync_webview_canvas(self.webview_platform, self.window_size)
            pygame.display.set_caption(self.caption)
            self.clock = pygame.time.Clock()
            self.textbox = self._create_textbox()
            self._apply_comfort_settings()
            pause_image = self.theme.get("pause_button", {}).get("image")
            if pause_image:
                self.pause_button_image = self.assets.load_image(pause_image).convert_alpha()
            else:
                try:
                    self.pause_button_image = loader.load_image("pause.png").convert_alpha()
                except (FileNotFoundError, pygame.error):
                    self.pause_button_image = None
            self._layout_pause_button()
            self.menu_renderer = self.renderer_override or self._create_menu_renderer()
            self._apply_audio_settings()
            self._refresh_settings_menu()
            if self.settings.values.get("speech_enabled"):
                self._ensure_speech()
            self.active_menu = self.main_menu
            self.initialized = True
        except Exception:
            pygame.quit()
            self.initialized = False
            raise

    def _create_menu_renderer(self):
        if self.renderer_factory is not None:
            return self.renderer_factory(self.assets, self.theme)
        if not self.has_project_theme:
            return FallbackMenuRenderer(self.assets, self.theme)
        return DeclarativeMenuRenderer(self.assets, self.theme)

    def _play_intro(self):
        for _ in self._intro_frames():
            self.clock.tick(self.fps)

    async def play_intro_async(self):
        for _ in self._intro_frames():
            self.clock.tick(self.fps)
            await asyncio.sleep(0)

    def _intro_frames(self):
        """Yield frames while showing the logo, creator credit, and content notice."""
        try:
            logo = loader.load_image("logo.png").convert_alpha()
        except (FileNotFoundError, pygame.error):
            return
        screen_width, screen_height = self.screen.get_size()
        max_side = int(min(screen_width, screen_height) * 0.45)
        scale = min(1.0, max_side / max(logo.get_width(), logo.get_height()))
        if scale < 1.0:
            logo = pygame.transform.smoothscale(
                logo,
                (max(1, int(logo.get_width() * scale)), max(1, int(logo.get_height() * scale))),
            )
        logo_rect = logo.get_rect(center=(screen_width // 2, screen_height // 2 - 20))
        intro = self.project.values["intro"]
        engine_version = _read_engine_version()
        game_fonts = self.theme.get("game_fonts", {})
        font_sizes = self.theme.get("game_font_sizes", {})
        intro_font = game_fonts.get("intro", "standard.ttf")
        font = self.assets.load_font(
            intro_font, ui_size(font_sizes.get("intro", 40))
        )
        small_font = self.assets.load_font(
            intro_font, ui_size(font_sizes.get("intro_small", 21))
        )
        cards = [
            {"image": logo, "kind": "logo", "hold": 3.0},
            {"image": self._intro_image(intro["credit_image"]), "kind": "credit", "hold": 2.5},
        ]
        warning_image = self._intro_image(intro["warning_image"])
        headphones_image = self._intro_image(intro["headphones_image"])
        if _intro_warning_card_needed(intro["warning_message"], warning_image, headphones_image):
            cards.append(
                {
                    "image": warning_image,
                    "extra_image": headphones_image,
                    "kind": "warning",
                    "hold": 2.5,
                }
            )
        sound_channel = None
        try:
            intro_sound = self.assets.load_sound("intro.wav")
            if intro_sound is not None:
                intro_sound.set_volume(self._effective_sfx_volume())
                sound_channel = intro_sound.play()
        except (FileNotFoundError, pygame.error):
            pass
        fade_seconds = 0.75
        stars = [(random.randrange(screen_width), random.randrange(screen_height), random.uniform(0.2, 1.0), random.random() * math.tau) for _ in range(36)]
        card_start = pygame.time.get_ticks()
        card_index = 0
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
            if not self.running:
                if sound_channel is not None:
                    sound_channel.stop()
                break
            now = pygame.time.get_ticks()
            elapsed = (now - card_start) / 1000
            card = cards[card_index]
            if elapsed >= card["hold"] + 2 * fade_seconds:
                card_index += 1
                if card_index >= len(cards):
                    break
                card_start = now
                continue
            alpha = self._smoothstep(min(1.0, elapsed / fade_seconds))
            if elapsed > card["hold"] + fade_seconds:
                alpha *= 1.0 - self._smoothstep((elapsed - card["hold"] - fade_seconds) / fade_seconds)
            self.screen.fill((0, 0, 0))
            if card["kind"] == "logo":
                self._draw_intro_stars(stars, now)
                card["image"].set_alpha(round(255 * alpha))
                self.screen.blit(card["image"], logo_rect)
                tm = small_font.render("TM", True, (238, 238, 245))
                tm_rect = tm.get_rect(topright=(logo_rect.right - ui_size(5), logo_rect.top + ui_size(95)))
                tm.set_alpha(round(255 * alpha))
                self.screen.blit(tm, tm_rect)
                lines = ["© 2026 Marpp. All rights reserved.", "Powered by Pygame-CE"]
                if engine_version:
                    lines.append(f"v{engine_version}")
                for index, line in enumerate(lines):
                    rendered = small_font.render(line, True, (190, 198, 215))
                    rendered.set_alpha(round(255 * alpha))
                    self.screen.blit(rendered, rendered.get_rect(center=(screen_width // 2, screen_height - ui_size(100) + index * ui_size(28))))
            else:
                image = card["image"]
                image_rect = None
                if image is not None:
                    image = pygame.transform.smoothscale(image, (min(image.get_width(), screen_width // 2), min(image.get_height(), screen_height // 2)))
                    image.set_alpha(round(255 * alpha))
                    image_y = screen_height // 2 - ui_size(150 if card.get("extra_image") else 90)
                    image_rect = image.get_rect(center=(screen_width // 2, image_y))
                    self.screen.blit(image, image_rect)
                extra_image = card.get("extra_image")
                if extra_image is not None:
                    extra = pygame.transform.smoothscale(extra_image, (min(extra_image.get_width(), screen_width // 3), min(extra_image.get_height(), screen_height // 3)))
                    extra.set_alpha(round(255 * alpha))
                    self.screen.blit(extra, extra.get_rect(center=(screen_width // 2, screen_height // 2 + ui_size(190))))
                message = f"A Game by {intro['creator']}" if card["kind"] == "credit" else intro["warning_message"]
                if card["kind"] == "credit" and intro.get("game_version"):
                    message += f"\nVersion {intro['game_version']}"
                text_top = image_rect.bottom + ui_size(24) if card["kind"] == "credit" and image_rect else screen_height // 2
                for line_index, line in enumerate(message.splitlines()):
                    text = font.render(line, True, (238, 238, 245))
                    text.set_alpha(round(255 * alpha))
                    y = text_top + line_index * font.get_linesize()
                    self.screen.blit(text, text.get_rect(center=(screen_width // 2, y)))
            pygame.display.flip()
            yield None
        self.screen.fill((0, 0, 0))
        pygame.display.flip()

    @staticmethod
    def _smoothstep(progress):
        progress = max(0.0, min(1.0, progress))
        return progress * progress * (3 - 2 * progress)

    def _intro_image(self, path):
        if not path:
            return None
        try:
            return self.assets.load_image(path).convert_alpha()
        except (FileNotFoundError, pygame.error):
            return None

    def _draw_intro_stars(self, stars, now):
        for x, y, brightness, phase in stars:
            twinkle = (math.sin(now / 520 + phase) + 1) / 2
            shade = int(75 + 100 * twinkle * brightness)
            pygame.draw.circle(self.screen, (shade, shade, min(255, shade + 12)), (x, y), 1)

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif (
                event.type == pygame.KEYDOWN
                and event.key == pygame.K_HOME
                and (event.mod & (pygame.KMOD_CTRL | pygame.KMOD_SHIFT))
                == (pygame.KMOD_CTRL | pygame.KMOD_SHIFT)
            ):
                self._recover_window_position()
            elif event.type in {
                getattr(pygame, "VIDEORESIZE", -1),
                getattr(pygame, "WINDOWRESIZED", -2),
                getattr(pygame, "WINDOWSIZECHANGED", -3),
            }:
                self._sync_window_size()
            elif self.mode == "game":
                self._handle_game_event(event)
            else:
                self._handle_menu_event(event)

    def _sync_window_size(self):
        screen = pygame.display.get_surface()
        if screen is None:
            return
        new_size = screen.get_size()
        if not self.settings.values.get("fullscreen", False):
            self.windowed_size = new_size
        if new_size != self.window_size:
            self.window_size = new_size
            if self.textbox is not None:
                self.textbox = self._create_textbox(self.textbox)
                self.choice_buttons = []
                if self.flow is not None:
                    self._sync_choice_buttons()
            self._layout_pause_button()
        sync_webview_canvas(self.webview_platform, new_size)

    def _recover_window_position(self):
        if not self.allow_fullscreen or self.settings.values.get("fullscreen", False):
            return
        display_size = primary_display_size(pygame.display)
        if not display_size:
            return
        self.windowed_size = fit_window_size(self.windowed_size, display_size)
        self.screen = pygame.display.set_mode(self.windowed_size)
        pygame.display.set_window_position(
            *centered_window_position(self.screen.get_size(), display_size)
        )
        self._sync_window_size()

    def _handle_game_event(self, event):
        if self.editor_test_context is not None and self._handle_variable_inspector_event(event):
            return
        if getattr(self, "story_input", None) is not None:
            if self.story_input["active"]:
                self._handle_story_input_event(event)
            elif self.textbox.complete:
                self._activate_story_input()
            elif event.type == pygame.KEYDOWN and self._keyboard_game_control(event) == "advance":
                self._perform_game_control("advance")
            elif (
                event.type == pygame.JOYBUTTONDOWN
                and self.settings.values.get("controller_bindings", {}).get("advance") == event.button
            ):
                self._perform_game_control("advance")
            elif (
                event.type == pygame.MOUSEBUTTONDOWN
                and event.button == 1
                and not getattr(event, "touch", False)
            ):
                self._advance_story()
            elif event.type == pygame.FINGERDOWN:
                self._advance_story()
            return
        if self.confirmation is not None:
            self._handle_confirmation_event(event)
            return
        if event.type == pygame.JOYBUTTONDOWN:
            bindings = self.settings.values.get("controller_bindings", {})
            for action in ("skip_all", "skip_read", "back", "history", "auto", "mute", "voice", "pause", "advance"):
                if bindings.get(action) == event.button:
                    self._perform_game_control(action)
                    return
        if event.type == pygame.JOYHATMOTION:
            vertical = event.value[1]
            if vertical and self.history_visible:
                self.history_scroll = max(0, self.history_scroll - vertical * 3)
                return
            if vertical and self.flow.choices_visible:
                count = len(self.choice_buttons)
                if count:
                    self.focused_choice_index = (self.focused_choice_index + (-1 if vertical > 0 else 1)) % count
                return
        if event.type == pygame.JOYAXISMOTION:
            direction = self._controller_axis_direction(event)
            if direction and event.axis == 1 and self.history_visible:
                self.history_scroll = max(0, self.history_scroll + direction * 3)
            elif direction and event.axis == 1 and self.flow.choices_visible:
                count = len(self.choice_buttons)
                if count:
                    self.focused_choice_index = (self.focused_choice_index + direction) % count
            return
        if event.type == pygame.KEYDOWN:
            if not self.history_visible and self.flow.choices_visible and event.key in (pygame.K_UP, pygame.K_DOWN):
                count = len(self.choice_buttons)
                if count:
                    step = -1 if event.key == pygame.K_UP else 1
                    self.focused_choice_index = (self.focused_choice_index + step) % count
                return
            if not self.history_visible and self.flow.choices_visible and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._perform_game_control("advance")
                return
            action = self._keyboard_game_control(event)
            if action is not None:
                self._perform_game_control(action)
            elif self.history_visible and event.key in (pygame.K_UP, pygame.K_PAGEUP, pygame.K_HOME):
                if event.key == pygame.K_HOME:
                    self.history_scroll = max(0, len(self.dialogue_history) * 3)
                else:
                    self.history_scroll += 1 if event.key == pygame.K_UP else 8
            elif self.history_visible and event.key in (pygame.K_DOWN, pygame.K_PAGEDOWN, pygame.K_END):
                if event.key == pygame.K_END:
                    self.history_scroll = 0
                else:
                    self.history_scroll = max(0, self.history_scroll - (1 if event.key == pygame.K_DOWN else 8))
        elif event.type == pygame.MOUSEWHEEL and self.history_visible:
            self.history_scroll = max(0, self.history_scroll + event.y * 3)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            self._go_back_dialogue()
        elif event.type == pygame.FINGERDOWN:
            position = (round(event.x * self.screen.get_width()), round(event.y * self.screen.get_height()))
            self._handle_touch_click(position)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if getattr(event, "touch", False):
                return
            if self.history_visible:
                self.history_visible = False
                self._resume_choice_timeout()
            else:
                self._layout_dialogue_buttons()
                if self._handle_dialogue_button_click(event.pos):
                    return
                if self.pause_button_rect.collidepoint(event.pos):
                    self._open_pause_menu()
                else:
                    self._handle_game_click(event.pos)

    def _handle_touch_click(self, position):
        if self.history_visible:
            self.history_visible = False
            self._resume_choice_timeout()
            return
        self._layout_dialogue_buttons()
        if self._handle_dialogue_button_click(position):
            return
        if self.pause_button_rect.collidepoint(position):
            self._open_pause_menu()
            return
        if self.flow.choices_visible:
            self._handle_game_click(position)
            return
        mode = self.settings.values.get("touch_advance_mode", "screen")
        if mode == "screen" or self.textbox.rect.collidepoint(position):
            self._advance_story()

    def _keyboard_game_control(self, event):
        bindings = self.settings.values.get("key_bindings", {})
        for action in ("skip_all", "skip_read", "back", "history", "auto", "mute", "voice", "pause", "advance"):
            binding = bindings.get(action, "")
            parts = [part.strip().lower() for part in binding.split("+") if part.strip()]
            if not parts:
                continue
            key_name = parts[-1]
            try:
                key = pygame.key.key_code(key_name)
            except (KeyError, ValueError, pygame.error):
                continue
            if event.key != key:
                continue
            modifiers = {
                "shift": bool(event.mod & pygame.KMOD_SHIFT),
                "ctrl": bool(event.mod & pygame.KMOD_CTRL),
                "control": bool(event.mod & pygame.KMOD_CTRL),
                "alt": bool(event.mod & pygame.KMOD_ALT),
            }
            requested = {part for part in parts[:-1] if part in {"shift", "ctrl", "control", "alt"}}
            if any(not modifiers[name] for name in requested):
                continue
            if modifiers["shift"] != ("shift" in requested):
                continue
            if modifiers["ctrl"] != bool(requested & {"ctrl", "control"}):
                continue
            if modifiers["alt"] != ("alt" in requested):
                continue
            return action
        return None

    def _perform_game_control(self, action):
        if action == "pause":
            if self.history_visible:
                self.history_visible = False
            else:
                self._open_pause_menu()
        elif action == "history":
            self.history_visible = not self.history_visible
            self.history_scroll = 0
            self._pause_choice_timeout() if self.history_visible else self._resume_choice_timeout()
        elif action == "voice":
            self._replay_voice()
        elif action == "back":
            if self.history_visible:
                self.history_visible = False
                self._resume_choice_timeout()
            else:
                self._go_back_dialogue()
        elif action == "advance":
            if self.history_visible:
                self.history_visible = False
                self._resume_choice_timeout()
            elif self.flow.choices_visible:
                self._choose_story_option(self.focused_choice_index)
            else:
                self._advance_story()
        elif action == "auto":
            self._toggle_setting("auto_advance")
        elif action == "mute":
            self._toggle_setting("muted")
        elif action in {"skip_read", "skip_all"}:
            selected = "read" if action == "skip_read" else "all"
            self.skip_mode = None if self.skip_mode == selected else selected
            if self.skip_mode is not None:
                self.auto_mode = False
                self.settings.set("auto_advance", False)
                self.settings.save()
            self._refresh_settings_menu()

    def _handle_game_click(self, position):
        if self._fade_out_blocks_input():
            return
        if self.flow.choices_visible:
            for index, button in enumerate(self.choice_buttons):
                if button.update(True, position):
                    self._choose_story_option(index)
                    return
        elif not self.flow.finished:
            self._advance_story()

    def _choose_story_option(self, index):
        if (
            self._fade_out_blocks_input()
            or not self.flow.choices_visible
            or not 0 <= index < len(self.flow.options)
        ):
            return False
        option = self.flow.options[index]
        self._choice_timeout_deadline = None
        self._choice_timeout_paused_remaining = None
        self.choice_history.append({
            "dialogue": self.flow.current_id,
            "label": option["label"],
            "target": option["target"],
        })
        self.visited_choices.add((self.flow.current_id, option["target"]))
        if len(self.choice_history) > 500:
            del self.choice_history[:-500]
        self._remember_dialogue_state()
        self.flow.choose(index)
        self._enter_dialogue()
        return True

    def _handle_menu_event(self, event):
        if self.save_name_prompt is not None:
            self._handle_save_name_event(event)
            return
        if self.confirmation is not None:
            self._handle_confirmation_event(event)
            return
        if self.mode == "mod_details" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for index, rect in enumerate(self._mod_detail_buttons):
                if rect.collidepoint(event.pos):
                    self.mod_details_menu.selected = index
                    self._activate_menu_item()
                    return
        if event.type == pygame.JOYBUTTONDOWN:
            bindings = self.settings.values.get("controller_bindings", {})
            for action in ("pause", "back", "advance"):
                if bindings.get(action) != event.button:
                    continue
                if action in {"pause", "back"}:
                    self._go_back()
                else:
                    self._activate_controller_menu_item()
                return
        elif event.type == pygame.JOYHATMOTION:
            horizontal, vertical = event.value
            if vertical:
                if self.mode == "credits":
                    self._move_credit_selection(-1 if vertical > 0 else 1)
                elif self.mode == "settings":
                    self._move_settings_selection(-1 if vertical > 0 else 1)
                else:
                    self._move_menu_selection(-1 if vertical > 0 else 1)
            if horizontal and self.mode == "settings":
                self._adjust_or_toggle_setting(1 if horizontal > 0 else -1)
        elif event.type == pygame.JOYAXISMOTION:
            direction = self._controller_axis_direction(event)
            if direction:
                if event.axis == 1:
                    self._move_menu_selection(direction)
                elif event.axis == 0 and self.mode == "settings":
                    self._adjust_or_toggle_setting(direction)
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._play_menu_sound("cancel")
                self._go_back()
            elif event.key in (pygame.K_UP, pygame.K_w):
                if self.mode == "credits":
                    self._move_credit_selection(-1)
                    return
                if self.mode == "settings":
                    self._move_settings_selection(-1)
                    return
                if self.mode in {"gallery", "music_gallery", "achievements", "routes"}:
                    self._move_progress_selection(-1)
                    return
                if self.active_menu.move(-1):
                    self._play_menu_sound("hover")
                    if self.active_menu.selected_item:
                        self._announce(self.active_menu.selected_item.get("label", ""))
                self._track_slot_selection()
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                if self.mode == "credits":
                    self._move_credit_selection(1)
                    return
                if self.mode == "settings":
                    self._move_settings_selection(1)
                    return
                if self.mode in {"gallery", "music_gallery", "achievements", "routes"}:
                    self._move_progress_selection(1)
                    return
                if self.active_menu.move(1):
                    self._play_menu_sound("hover")
                    if self.active_menu.selected_item:
                        self._announce(self.active_menu.selected_item.get("label", ""))
                self._track_slot_selection()
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._play_menu_sound("click")
                self._activate_controller_menu_item()
            elif event.key == pygame.K_DELETE and self.mode == "slots":
                self._play_menu_sound("click")
                if self.selected_slot is not None:
                    self._request_confirmation(
                        "delete_slot", f"Delete the save in slot {self.selected_slot}?"
                    )
            elif event.key == pygame.K_PAGEUP and self.mode == "credits":
                self._scroll_credits(-1)
            elif event.key == pygame.K_PAGEDOWN and self.mode == "credits":
                self._scroll_credits(1)
            elif event.key == pygame.K_PAGEUP and self.mode == "settings":
                self._scroll_settings(-1)
            elif event.key == pygame.K_PAGEDOWN and self.mode == "settings":
                self._scroll_settings(1)
            elif event.key == pygame.K_PAGEUP and self.mode in {"gallery", "music_gallery", "achievements", "routes"}:
                self._scroll_progress(-1)
            elif event.key == pygame.K_PAGEDOWN and self.mode in {"gallery", "music_gallery", "achievements", "routes"}:
                self._scroll_progress(1)
            elif event.key == pygame.K_LEFT and self.mode == "settings":
                self._adjust_or_toggle_setting(-1)
            elif event.key == pygame.K_RIGHT and self.mode == "settings":
                self._adjust_or_toggle_setting(1)
        elif event.type == pygame.MOUSEMOTION:
            if self.mode == "mod_details":
                hovered = next((index for index, rect in enumerate(self._mod_detail_buttons) if rect.collidepoint(event.pos)), None)
                if hovered is not None and hovered != self.mod_details_menu.selected:
                    self.mod_details_menu.selected = hovered
                    item = self.mod_details_menu.selected_item
                    if item:
                        self._announce(item.get("label", ""))
            old_selection = self.active_menu.selected
            selected = self.active_menu.select_at(event.pos)
            if selected is not None and selected != old_selection:
                self._play_menu_sound("hover")
                if self.active_menu.selected_item:
                    self._announce(self.active_menu.selected_item.get("label", ""))
                if self.mode != "slots":
                    self._track_slot_selection()
                if self.mode == "credits":
                    self.credits_selected = min(len(self.credits_entries), self.credits_offset + selected)
                elif self.mode == "settings":
                    self.settings_selected = min(
                        len(self._settings_all_items) - 1,
                        self.settings_offset + selected,
                    )
                elif self.mode in {"gallery", "music_gallery", "achievements", "routes"}:
                    self.progress_selected = min(
                        len(self.progress_entries), self.progress_offset + selected
                    )
        elif event.type == pygame.MOUSEWHEEL and self.mode == "credits":
            self._scroll_credits(-event.y)
        elif event.type == pygame.MOUSEWHEEL and self.mode == "settings":
            self._scroll_settings(-event.y)
        elif event.type == pygame.MOUSEWHEEL and self.mode in {"gallery", "music_gallery", "achievements", "routes"}:
            self._scroll_progress(-event.y)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.mode == "credits" and getattr(self, "_credits_scroll_track", pygame.Rect(0, 0, 0, 0)).collidepoint(event.pos):
                track = self._credits_scroll_track
                max_offset = max(0, len(self.credits_entries) - max(2, (self.screen.get_height() - ui_size(260)) // ui_size(65) - 1))
                ratio = (event.pos[1] - track.top) / max(1, track.height)
                self.credits_offset = round(max_offset * max(0.0, min(1.0, ratio)))
                self._refresh_credits_window()
                return
            if self.mode == "settings" and self._settings_scroll_track.collidepoint(event.pos):
                track = self._settings_scroll_track
                max_offset = max(0, len(self._settings_all_items) - self._settings_visible_rows())
                ratio = (event.pos[1] - track.top) / max(1, track.height)
                self._set_settings_offset(round(max_offset * max(0.0, min(1.0, ratio))))
                return
            if self.mode in {"gallery", "music_gallery", "achievements", "routes"} and self._progress_scroll_track.collidepoint(event.pos):
                track = self._progress_scroll_track
                max_offset = max(0, len(self.progress_entries) - self._progress_visible_rows())
                ratio = (event.pos[1] - track.top) / max(1, track.height)
                self._set_progress_offset(round(max_offset * max(0.0, min(1.0, ratio))))
                return
            if self.mode == "slots" and self._handle_slot_button_click(event.pos):
                return
            selected = self.active_menu.select_at(event.pos)
            if selected is not None:
                self._track_slot_selection()
                if self.mode == "credits":
                    self.credits_selected = min(len(self.credits_entries), self.credits_offset + selected)
                elif self.mode == "settings":
                    self.settings_selected = min(
                        len(self._settings_all_items) - 1,
                        self.settings_offset + selected,
                    )
                elif self.mode in {"gallery", "music_gallery", "achievements", "routes"}:
                    self.progress_selected = min(
                        len(self.progress_entries), self.progress_offset + selected
                    )
                self._play_menu_sound("click")
                if self.mode != "slots":
                    item = self.active_menu.selected_item
                    if self.mode == "settings" and item.get("action") == "adjust_setting":
                        row = self.active_menu.row_rects[selected]
                        direction = 1 if event.pos[0] >= row.centerx else -1
                        self._adjust_selected_setting(direction, item.get("setting"))
                    else:
                        self._activate_menu_item()

    def _activate_controller_menu_item(self):
        item = self.active_menu.selected_item if self.active_menu is not None else None
        if self.mode == "slots" and item and "slot" in item:
            slot = item["slot"]
            if self.slot_context == "copy":
                if self.selected_slot == slot and slot != self.copy_source_slot:
                    self._request_confirmation(
                        "copy_slot",
                        f"Copy slot {self.copy_source_slot} over slot {slot}?",
                    )
                else:
                    self.selected_slot = slot
                    self._track_slot_selection()
                return
            if self.selected_slot == slot:
                self._load_selected_slot() if self.slot_context == "load" else self._save_selected_slot()
            else:
                self.selected_slot = slot
                self._track_slot_selection()
        else:
            self._activate_menu_item()

    def _controller_axis_direction(self, event):
        if event.axis not in (0, 1):
            return 0
        value = float(event.value)
        direction = 1 if value >= 0.62 else -1 if value <= -0.62 else 0
        key = (getattr(event, "joy", 0), event.axis)
        previous_direction, previous_at = self._controller_axis_state.get(key, (0, 0))
        now = pygame.time.get_ticks()
        if not direction:
            self._controller_axis_state[key] = (0, now)
            return 0
        if direction != previous_direction or now - previous_at >= 240:
            self._controller_axis_state[key] = (direction, now)
            return direction
        return 0

    def _move_menu_selection(self, direction):
        if self.mode == "credits":
            self._move_credit_selection(direction)
        elif self.mode == "settings":
            self._move_settings_selection(direction)
        elif self.mode in {"gallery", "music_gallery", "achievements", "routes"}:
            self._move_progress_selection(direction)
        elif self.active_menu is not None and self.active_menu.move(direction):
            self._play_menu_sound("hover")
            self._track_slot_selection()
            if self.active_menu.selected_item:
                self._announce(self.active_menu.selected_item.get("label", ""))

    def _update(self):
        if (
            self.settings.values.get("speech_enabled")
            and self.speech_announcer is not None
            and self.speech_announcer.available is False
            and not self._speech_unavailable_reported
        ):
            self.status_message = self._ui_text(
                "speech.unavailable",
                "Speech output is unavailable. Install pyttsx3 or enable a system speech service.",
            )
            self._speech_unavailable_reported = True
        if self.mode != "game":
            return
        if self.variable_inspector_visible:
            return
        self.textbox.update()
        if self.story_input is not None:
            if not self.story_input["active"] and self.textbox.complete:
                self._activate_story_input()
            return
        if self.textbox.complete:
            self.seen_dialogues.add(self.flow.current_id)
        if self.history_visible or self.confirmation is not None:
            return
        if self.flow.options and self.textbox.complete and not self.flow.choices_visible:
            self.flow.show_choices()
            self._sync_choice_buttons()
        if self.flow.finished:
            self.skip_mode = None
            self._auto_advance_deadline = None
        elif self.flow.choices_visible:
            self._auto_advance_deadline = None
            self._update_choice_timeout()
        elif self.skip_mode is not None:
            if self.skip_mode == "read" and not self._current_dialogue_was_seen:
                if self.textbox.complete:
                    self.skip_mode = None
            else:
                self.textbox.reveal_all()
                if self.textbox.complete:
                    self._advance_story()
        elif self.auto_mode and self.textbox.complete and not self._fade_out_blocks_input():
            now = pygame.time.get_ticks()
            if self._auto_advance_deadline is None:
                self._auto_advance_deadline = now + round(self.settings.values["auto_wait"] * 1000)
            elif now >= self._auto_advance_deadline:
                self._advance_story()

        interval = float(self.project.values["autosave_interval_seconds"])
        now = pygame.time.get_ticks()
        if (
            interval > 0
            and self.flow is not None
            and self.story_input is None
            and self._last_autosave_at is not None
            and now - self._last_autosave_at >= round(interval * 1000)
        ):
            self._last_autosave_at = now
            self._save_autosave()

    def _update_choice_timeout(self):
        if self.flow is None or not self.flow.choices_visible:
            return
        dialogue = self.flow.current
        timeout = dialogue.get("choice_timeout")
        if timeout is None:
            self._choice_timeout_deadline = None
            self._choice_timeout_paused_remaining = None
            return
        if self._choice_timeout_paused_remaining is not None:
            return
        now = pygame.time.get_ticks()
        if self._choice_timeout_deadline is None:
            self._choice_timeout_deadline = now + round(float(timeout) * 1000)
            return
        if now < self._choice_timeout_deadline:
            return
        target = dialogue.get("choice_timeout_target")
        options = self.flow.options
        selected = next(
            (index for index, option in enumerate(options) if option.get("target") == target),
            0,
        )
        self._choose_story_option(selected)

    def _render(self):
        if self.mode == "game" or self._menu_over_game():
            self._render_game()
        else:
            self.screen.fill(COLORS.background)

        if self.mode != "game":
            self._translate_menu_labels(self.active_menu)
            if self._menu_over_game():
                shade = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
                shade.fill((0, 0, 0, 175))
                self.screen.blit(shade, (0, 0))
            if self.mode == "credits":
                self._draw_credits_panel()
            elif self.mode == "settings":
                self._draw_settings_panel()
            elif self.mode in {"gallery", "music_gallery", "achievements", "routes"}:
                self._draw_progress_panel()
            elif self.mode in {"mods", "mod_details"}:
                self._draw_mod_panel()
            elif self.mode == "cg_viewer" and self.gallery_image is not None:
                available = pygame.Rect(
                    ui_size(40), ui_size(40),
                    self.screen.get_width() - ui_size(80),
                    self.screen.get_height() - ui_size(80),
                )
                source_width, source_height = self.gallery_image.get_size()
                scale = min(available.width / max(1, source_width), available.height / max(1, source_height))
                image_size = (max(1, round(source_width * scale)), max(1, round(source_height * scale)))
                image = pygame.transform.smoothscale(self.gallery_image, image_size)
                self.screen.blit(image, image.get_rect(center=available.center))
            if self.mode == "mod_details":
                self._draw_mod_details()
            else:
                renderer = self._renderer_for_active_menu()
                renderer.render(self.screen, self.active_menu)
            if self.mode == "slots":
                self._render_slot_buttons()
            elif self.mode == "credits":
                self._draw_credits_scrollbar()
            elif self.mode == "settings":
                self._draw_settings_scrollbar()
            elif self.mode in {"gallery", "music_gallery", "achievements", "routes"}:
                self._draw_progress_scrollbar()
            self._render_status()
        else:
            self._render_status()
            self._draw_pause_button()
        if self.confirmation is not None:
            self._render_confirmation()
        if self.save_name_prompt is not None:
            self._render_save_name_prompt()
        if (
            getattr(self, "story_input", None) is not None
            and self.story_input["active"]
        ):
            self._render_story_input()
        pygame.display.flip()

    def _renderer_for_active_menu(self):
        if self.renderer_override is not None:
            return self.renderer_override
        return self.menu_renderer

    def _render_game(self):
        scene = pygame.Surface(self.screen.get_size())
        scene.fill(COLORS.background)
        if self.background_image is not None:
            background = pygame.transform.smoothscale(
                self.background_image, scene.get_size()
            )
            scene.blit(background, (0, 0))

        if self.character_layer is not None:
            self.character_layer.render(scene, self.active_character)

        if self.flow is None:
            self.screen.blit(scene, (0, 0))
            return
        self.textbox.render()
        scene.blit(self.textbox.surface, self.textbox.rect)
        if self.flow.choices_visible:
            for index, (button, option) in enumerate(zip(self.choice_buttons, self.flow.options)):
                hovered = button.rect.collidepoint(pygame.mouse.get_pos())
                if hovered:
                    self.focused_choice_index = index
                button.render(
                    option["label"],
                    hovered=hovered,
                )
                if index == self.focused_choice_index:
                    pygame.draw.rect(
                        button.surface,
                        self.theme.get("colors", {}).get("accent", COLORS.text_highlight),
                        button.surface.get_rect(),
                        width=max(1, ui_size(3)),
                        border_radius=ui_size(6),
                    )
                scene.blit(button.surface, button.rect)

        if self._choice_timeout_deadline is not None and self.flow.choices_visible:
            remaining = max(0.0, (self._choice_timeout_deadline - pygame.time.get_ticks()) / 1000)
            countdown = FONTS.dialogue_controls.render(
                f"Auto-selecting in {remaining:.1f}s",
                True,
                COLORS.text,
            )
            countdown_rect = countdown.get_rect(midtop=(self.screen.get_width() // 2, ui_size(12)))
            countdown_back = countdown_rect.inflate(ui_size(20), ui_size(10))
            badge = pygame.Surface(countdown_back.size, pygame.SRCALPHA)
            pygame.draw.rect(badge, (0, 0, 0, 190), badge.get_rect(), border_radius=ui_size(6))
            scene.blit(badge, countdown_back)
            scene.blit(countdown, countdown_rect)

        self._draw_dialogue_buttons(scene)
        preview_scale = min(320 / scene.get_width(), 180 / scene.get_height())
        preview_size = (
            max(1, round(scene.get_width() * preview_scale)),
            max(1, round(scene.get_height() * preview_scale)),
        )
        self._preview_surface = pygame.transform.smoothscale(scene, preview_size)
        self.screen.fill(COLORS.background)
        shake_x, shake_y = self._shake_offset()
        self.screen.blit(scene, (shake_x, shake_y))
        self._render_fade()
        if self.history_visible:
            self._render_history()
        if pygame.time.get_ticks() < self.autosave_notice_until:
            notice = FONTS.button_text.render("Autosaved", True, COLORS.text)
            box = notice.get_rect(midtop=(self.screen.get_width() // 2, ui_size(18))).inflate(ui_size(28), ui_size(16))
            pygame.draw.rect(self.screen, (0, 0, 0, 190), box, border_radius=ui_size(8))
            self.screen.blit(notice, notice.get_rect(center=box.center))
        if self.skip_mode is not None or self.auto_mode:
            mode = f"SKIP: {self.skip_mode.upper()}" if self.skip_mode else "AUTO"
            status = FONTS.dialogue_controls.render(mode, True, COLORS.text_highlight)
            box = status.get_rect(topright=(self.screen.get_width() - ui_size(20), ui_size(18))).inflate(ui_size(20), ui_size(12))
            pygame.draw.rect(self.screen, (0, 0, 0, 190), box, border_radius=ui_size(6))
            self.screen.blit(status, status.get_rect(center=box.center))
        if self.variable_inspector_visible:
            self._render_variable_inspector()
        elif self.editor_test_context is not None:
            hint = FONTS.dialogue_controls.render("F3 | Test Variables", True, COLORS.text)
            hint_box = hint.get_rect(topleft=(ui_size(18), ui_size(18))).inflate(ui_size(18), ui_size(10))
            pygame.draw.rect(self.screen, (0, 0, 0, 175), hint_box, border_radius=ui_size(5))
            self.screen.blit(hint, hint.get_rect(center=hint_box.center))

    def _handle_variable_inspector_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F3:
            if self.variable_inspector_visible:
                self._close_variable_inspector()
            else:
                self.variable_inspector_visible = True
                self._auto_advance_deadline = None
                self._pause_choice_timeout()
            return True
        if not self.variable_inspector_visible:
            return False

        names = sorted(self.flow.variables) if self.flow is not None else []
        if event.type == pygame.TEXTINPUT and self.variable_inspector_edit is not None:
            self.variable_inspector_edit["text"] += event.text
            return True
        if event.type == pygame.JOYBUTTONDOWN:
            bindings = self.settings.values.get("controller_bindings", {})
            if event.button == bindings.get("advance"):
                if self.variable_inspector_edit is not None:
                    self._commit_variable_inspector_edit()
                elif names:
                    name = names[self.variable_inspector_index % len(names)]
                    self.variable_inspector_edit = {"name": name, "text": str(self.flow.variables[name])}
                    pygame.key.start_text_input()
            elif event.button in {bindings.get("back"), bindings.get("pause")}:
                if self.variable_inspector_edit is not None:
                    self.variable_inspector_edit = None
                    pygame.key.stop_text_input()
                else:
                    self._close_variable_inspector()
            return True
        if event.type == pygame.JOYHATMOTION:
            horizontal, vertical = event.value
            if names and vertical:
                self.variable_inspector_index = (
                    self.variable_inspector_index + (-1 if vertical > 0 else 1)
                ) % len(names)
            elif names and horizontal and self.variable_inspector_edit is None:
                self._adjust_inspector_value(1 if horizontal > 0 else -1)
            return True
        if event.type == pygame.JOYAXISMOTION:
            direction = self._controller_axis_direction(event)
            if direction and event.axis == 1 and names:
                self.variable_inspector_index = (self.variable_inspector_index + direction) % len(names)
            elif direction and event.axis == 0 and names and self.variable_inspector_edit is None:
                self._adjust_inspector_value(direction)
            return True
        if event.type != pygame.KEYDOWN:
            return True
        if self.variable_inspector_edit is not None:
            if event.key == pygame.K_ESCAPE:
                self.variable_inspector_edit = None
                pygame.key.stop_text_input()
            elif event.key == pygame.K_BACKSPACE:
                self.variable_inspector_edit["text"] = self.variable_inspector_edit["text"][:-1]
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._commit_variable_inspector_edit()
            return True
        if event.key == pygame.K_ESCAPE:
            self._close_variable_inspector()
        elif names and event.key in (pygame.K_UP, pygame.K_DOWN):
            step = -1 if event.key == pygame.K_UP else 1
            self.variable_inspector_index = (self.variable_inspector_index + step) % len(names)
        elif names and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            name = names[self.variable_inspector_index % len(names)]
            self.variable_inspector_edit = {"name": name, "text": str(self.flow.variables[name])}
            pygame.key.start_text_input()
        elif names and event.key in (pygame.K_SPACE, pygame.K_TAB):
            name = names[self.variable_inspector_index % len(names)]
            value = self.flow.variables[name]
            if isinstance(value, bool):
                self.flow.variables[name] = not value
        elif names and event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS, pygame.K_MINUS, pygame.K_KP_MINUS):
            self._adjust_inspector_value(
                -1 if event.key in (pygame.K_MINUS, pygame.K_KP_MINUS) else 1
            )
        return True

    def _close_variable_inspector(self):
        self.variable_inspector_visible = False
        self.variable_inspector_edit = None
        pygame.key.stop_text_input()
        self._resume_choice_timeout()

    def _adjust_inspector_value(self, direction):
        if self.flow is None:
            return
        names = sorted(self.flow.variables)
        if not names:
            return
        name = names[self.variable_inspector_index % len(names)]
        value = self.flow.variables[name]
        if isinstance(value, bool):
            self.flow.variables[name] = not value
        elif isinstance(value, (int, float)):
            self.flow.variables[name] = value + direction

    def _commit_variable_inspector_edit(self):
        edit = self.variable_inspector_edit
        if edit is None or self.flow is None:
            return
        name = edit["name"]
        original = self.flow.variables.get(name)
        raw = edit["text"]
        try:
            if isinstance(original, bool):
                normalized = raw.strip().lower()
                if normalized not in {"true", "false"}:
                    raise ValueError("Enter true or false.")
                value = normalized == "true"
            elif isinstance(original, int) and not isinstance(original, bool):
                value = int(raw)
            elif isinstance(original, float):
                value = float(raw)
                if not math.isfinite(value):
                    raise ValueError("Enter a finite number.")
            elif original is None:
                value = json.loads(raw)
                if value is not None and not isinstance(value, (str, int, float, bool)):
                    raise ValueError("Enter a scalar JSON value.")
            else:
                value = raw
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            self.status_message = f"Variable unchanged: {error}"
            self.variable_inspector_edit = None
            pygame.key.stop_text_input()
            return
        self.flow.variables[name] = value
        self.variable_inspector_edit = None
        pygame.key.stop_text_input()
        self.status_message = f"Changed {name} for this test run."

    def _render_variable_inspector(self):
        if self.flow is None:
            return
        names = sorted(self.flow.variables)
        panel_width = min(ui_size(540), self.screen.get_width() - ui_size(32))
        panel_height = min(ui_size(520), self.screen.get_height() - ui_size(32))
        panel = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
        pygame.draw.rect(panel, (12, 18, 30, 238), panel.get_rect(), border_radius=ui_size(12))
        pygame.draw.rect(panel, (110, 160, 230, 255), panel.get_rect(), width=ui_size(2), border_radius=ui_size(12))
        title = FONTS.char_name.render("Test Variables", True, (240, 245, 255))
        panel.blit(title, (ui_size(18), ui_size(14)))
        hint = FONTS.dialogue_controls.render("F3 close | Up/Down select | Enter edit", True, (195, 208, 226))
        hint_more = FONTS.dialogue_controls.render("+/- adjust numbers | Space toggles bool", True, (195, 208, 226))
        panel.blit(hint, (ui_size(18), ui_size(52)))
        panel.blit(hint_more, (ui_size(18), ui_size(72)))
        line_height = ui_size(30)
        visible_rows = max(1, (panel_height - ui_size(125)) // line_height)
        start = max(0, min(self.variable_inspector_index - visible_rows + 1, max(0, len(names) - visible_rows)))
        for row, name in enumerate(names[start:start + visible_rows]):
            index = start + row
            y = ui_size(105) + row * line_height
            selected = index == self.variable_inspector_index
            if selected:
                pygame.draw.rect(panel, (42, 62, 91, 235), (ui_size(10), y - ui_size(2), panel_width - ui_size(20), line_height), border_radius=ui_size(5))
            value = self.flow.variables[name]
            shown = self.variable_inspector_edit["text"] if selected and self.variable_inspector_edit is not None else repr(value)
            if len(shown) > 48:
                shown = shown[:45] + "..."
            rendered = FONTS.button_text.render(f"{name} = {shown}", True, (250, 250, 250) if selected else (205, 214, 228))
            panel.blit(rendered, (ui_size(18), y + ui_size(2)))
        if not names:
            empty = FONTS.button_text.render("This story declares no variables.", True, (205, 214, 228))
            panel.blit(empty, (ui_size(18), ui_size(105)))
        if self.variable_inspector_edit is not None:
            footer_text = "Editing value - Enter applies, Esc cancels"
        else:
            footer_text = "Changes apply to the current test run only"
        footer = FONTS.button_text.render(footer_text, True, (195, 208, 226))
        panel.blit(footer, (ui_size(18), panel_height - ui_size(30)))
        rect = panel.get_rect(center=self.screen.get_rect().center)
        self.screen.blit(panel, rect)

    def _render_status(self):
        if not self.status_message:
            return
        status = FONTS.button_text.render(self.status_message, True, COLORS.text_highlight)
        self.screen.blit(status, status.get_rect(center=(self.screen.get_width() // 2, self.screen.get_height() - ui_size(40))))

    def _create_textbox(self, previous=None):
        textbox_theme = self.theme.get("textbox", {})
        image_name = textbox_theme.get("background")
        image = self.assets.load_image(image_name) if image_name else None
        color = textbox_theme.get("color")
        screen_width, screen_height = self.window_size
        x = round(screen_width * textbox_theme.get("x", 0.02))
        bottom = round(screen_height * textbox_theme.get("bottom", 0.0))
        dialogue_buttons = self.project.values.get("dialogue_buttons", {})
        if any(isinstance(button, dict) and button.get("visible", False) for button in dialogue_buttons.values()):
            bottom = max(bottom, ui_size(38))
        width = max(1, round(screen_width * textbox_theme.get("width", 0.96)))
        height = max(1, round(screen_height * textbox_theme.get("height", 0.21)))
        textbox = Textbox(
            x,
            screen_height - bottom - height,
            width,
            height,
            panel_color=tuple(color) if color is not None else COLORS.panel,
            panel_image=image,
            panel_opacity=textbox_theme.get("opacity", 0.95),
            high_contrast=self.settings.values.get("high_contrast", False),
            subtitles_enabled=self.settings.values.get("subtitles_enabled", True),
        )
        if previous is not None:
            textbox.current_speaker = previous.current_speaker
            textbox.full_parsed_text = previous.full_parsed_text
            textbox.visible_chars = previous.visible_chars
            textbox.last_update_time = previous.last_update_time
            textbox.ms_per_char = previous.ms_per_char
            textbox._fit_font_to_message()
        return textbox

    def _apply_comfort_font_sizes(self):
        sizes = self.theme.get("game_font_sizes", {})
        for font, setting, theme_key in (
            (FONTS.normal_text, "dialogue_font_scale", "text"),
            (FONTS.char_name, "speaker_font_scale", "name"),
        ):
            set_point_size = getattr(font, "set_point_size", None)
            if not callable(set_point_size):
                continue
            base_size = ui_size(sizes.get(theme_key, 24 if theme_key == "text" else 28))
            scale = self.settings.values.get(setting, 1.0)
            set_point_size(max(1, round(base_size * scale)))

    def _apply_comfort_settings(self):
        self._apply_comfort_font_sizes()
        if self.textbox is not None:
            self.textbox = self._create_textbox(self.textbox)

    def _layout_pause_button(self):
        if self.screen is None:
            self.pause_button_rect = pygame.Rect(0, 0, 0, 0)
            return
        pause_theme = self.theme.get("pause_button", {})
        side = max(1, ui_size(pause_theme.get("size", 78)))
        margin = max(0, ui_size(pause_theme.get("margin", 16)))
        self.pause_button_rect = pygame.Rect(margin, margin, side, side)
        if self.pause_button_image is not None:
            icon_side = max(1, side - ui_size(10))
            self.scaled_pause_button_image = pygame.transform.smoothscale(
                self.pause_button_image, (icon_side, icon_side)
            )
        else:
            self.scaled_pause_button_image = None

    def _draw_pause_button(self):
        if self.pause_button_image is None or self.mode != "game" or self.history_visible:
            return
        rect = self.pause_button_rect
        disk_side = max(1, rect.width - ui_size(16))
        pygame.draw.circle(self.screen, (242, 242, 247), rect.center, disk_side // 2)
        self.screen.blit(self.scaled_pause_button_image, self.scaled_pause_button_image.get_rect(center=rect.center))

    def _layout_dialogue_buttons(self):
        self.dialogue_button_rects = {}
        if self.textbox is None:
            return []

        config = self.project.values.get("dialogue_buttons", {})
        visible = [
            (name, button)
            for name in ("back", "auto", "history", "quick_save", "quick_load", "mute")
            if isinstance((button := config.get(name)), dict) and button.get("visible", True)
        ]
        if not visible:
            return []
        locale = self.settings.values.get("locale", "en")
        ui_table = self.translation_tables.get(locale, {}).get("ui", {})

        gap = ui_size(8)
        height = ui_size(22)
        available_width = max(1, self.textbox.rect.width - ui_size(24))
        max_button_width = max(
            1, (available_width - gap * (len(visible) - 1)) // len(visible)
        )
        widths = [
            min(
                max_button_width,
                max(
                    ui_size(58),
                    FONTS.dialogue_controls.size(translate_label(locale, button["label"], ui_table))[0] + ui_size(14),
                ),
            )
            for _, button in visible
        ]
        if sum(widths) + gap * (len(widths) - 1) > available_width:
            widths = [max_button_width] * len(visible)
        total_width = sum(widths) + gap * (len(widths) - 1)
        left = self.textbox.rect.centerx - total_width // 2
        top = self.textbox.rect.bottom + ui_size(8)

        buttons = []
        for (name, button), width in zip(visible, widths):
            rect = pygame.Rect(left, top, width, height)
            self.dialogue_button_rects[name] = rect
            buttons.append(
                (name, translate_label(locale, button["label"], ui_table), rect, name != "back" or bool(self.dialogue_back_stack))
            )
            left += width + gap
        return buttons

    def _draw_dialogue_buttons(self, surface):
        colors = self.theme.get("colors", {})
        for name, label, rect, enabled in self._layout_dialogue_buttons():
            hovered = enabled and rect.collidepoint(pygame.mouse.get_pos())
            if not enabled:
                text_color = (130, 130, 138)
            elif hovered:
                text_color = colors.get("accent", COLORS.text_highlight)
            elif name == "auto" and self.auto_mode:
                text_color = colors.get("accent", COLORS.text_highlight)
            elif name == "mute" and self.settings.values.get("muted", False):
                text_color = colors.get("accent", COLORS.text_highlight)
            else:
                text_color = COLORS.text
            text = FONTS.dialogue_controls.render(label, True, text_color)
            previous_clip = surface.get_clip()
            surface.set_clip(rect)
            surface.blit(text, text.get_rect(center=rect.center))
            surface.set_clip(previous_clip)

    def _handle_dialogue_button_click(self, position):
        for name, _, rect, enabled in self._layout_dialogue_buttons():
            if not rect.collidepoint(position):
                continue
            if not enabled:
                return True
            if name == "back":
                self._go_back_dialogue()
            elif name == "history":
                self.history_visible = True
                self.history_scroll = 0
                self._pause_choice_timeout()
            elif name == "quick_save":
                self._request_confirmation(
                    "quick_save", "Overwrite Quick Save with current progress?"
                )
            elif name == "quick_load":
                self._request_confirmation(
                    "quick_load",
                    "Load Quick Save if available, otherwise the most recent save?",
                )
            elif name == "auto":
                self._toggle_setting("auto_advance")
            elif name == "mute":
                self._toggle_setting("muted")
            return True
        return False

    def _remember_dialogue_state(self):
        if self.flow is None:
            return
        state = {
            "flow": self.flow.snapshot(),
            "background": self.background_id,
            "music": self.music_track,
            "characters": (
                self.character_layer.snapshot()
                if self.character_layer is not None
                else {}
            ),
            "dialogue_history": deepcopy(self.dialogue_history),
            "choice_history": deepcopy(self.choice_history),
            "seen_dialogues": set(self.seen_dialogues),
            "fade_effect": deepcopy(self.fade_effect),
            "shake_effect": deepcopy(self.shake_effect),
        }
        self.dialogue_back_stack.append(state)
        if len(self.dialogue_back_stack) > 2000:
            del self.dialogue_back_stack[:-2000]

    def _go_back_dialogue(self):
        if not self.dialogue_back_stack:
            return False

        state = self.dialogue_back_stack.pop()
        flow = StoryFlow(
            self.story_data,
            self.project.assets_dir,
            PATHS.engine_assets,
            locale=self.settings.values.get("locale"),
            fallback_locale=self.default_locale,
            asset_manager=self.assets,
            translation_tables=self.translation_tables,
        )
        flow.restore(state["flow"])
        self.flow = flow
        self.choice_buttons = []
        self.dialogue_history = state["dialogue_history"]
        self.choice_history = state["choice_history"]
        self.seen_dialogues = state["seen_dialogues"]
        self.background_id = state["background"]
        self.background_image = None
        if self.background_id is not None:
            self._set_background(self.background_id)
        if self.character_layer is not None:
            self.character_layer.restore(state["characters"])
        if self.music_track != state["music"]:
            self._stop_music()
            if state["music"]:
                self._play_music(state["music"])
        self.fade_effect = state["fade_effect"]
        self.shake_effect = state["shake_effect"]
        self.history_visible = False
        self.history_scroll = 0
        self.status_message = ""
        self._enter_dialogue(apply_actions=False)
        return True

    def _request_confirmation(self, action, message):
        self.confirmation = {"action": action, "message": message}
        self.confirmation_button_rects = {}
        if self.mode == "game":
            self._pause_choice_timeout()

    def _begin_story_input(self, action, prompt=None):
        if self.flow is None or action["var"] not in self.flow.variables:
            raise RuntimeError(
                f"Input action references unavailable story variable {action['var']!r}."
            )
        self.story_input = {
            "var": action["var"],
            "prompt": prompt if isinstance(prompt, str) else action["prompt"],
            "input_type": action.get("input_type", "text"),
            "text": "",
            "error": "",
            "active": False,
        }

    def _activate_story_input(self):
        if self.story_input is None or self.story_input["active"]:
            return
        self.story_input["active"] = True
        pygame.key.start_text_input()
        screen = getattr(self, "screen", None)
        if screen is not None and hasattr(pygame.key, "set_text_input_rect"):
            pygame.key.set_text_input_rect(self._story_input_geometry()[1])

    def _end_story_input(self):
        if getattr(self, "story_input", None) is None:
            return
        active = self.story_input["active"]
        self.story_input = None
        if active:
            pygame.key.stop_text_input()

    def _handle_story_input_event(self, event):
        if event.type == pygame.TEXTINPUT:
            self.story_input["text"] += event.text
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.story_input["text"] = self.story_input["text"][:-1]
                self.story_input["error"] = ""
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._submit_story_input()

    def _submit_story_input(self):
        answer = self.story_input["text"].strip()
        if not answer:
            self.story_input["error"] = "An answer is required."
            return
        if self.story_input["input_type"] == "integer":
            try:
                answer = int(answer)
            except ValueError:
                self.story_input["error"] = "Enter a whole number."
                return
        self.flow.variables[self.story_input["var"]] = answer
        self._end_story_input()

    def _story_input_geometry(self):
        screen_rect = self.screen.get_rect()
        width = max(1, min(ui_size(720), screen_rect.width - ui_size(32)))
        prompt_width = max(1, width - ui_size(48))
        font = FONTS.normal_text
        prompt_lines = []
        for paragraph in self.story_input["prompt"].splitlines() or [""]:
            line = ""
            for word in paragraph.split():
                candidate = f"{line} {word}".strip()
                if line and font.size(candidate)[0] > prompt_width:
                    prompt_lines.append(line)
                    line = word
                else:
                    line = candidate
            prompt_lines.append(line)
        line_height = font.get_linesize()
        fixed_height = ui_size(174)
        height = max(
            1,
            min(
                max(ui_size(230), fixed_height + len(prompt_lines) * line_height),
                screen_rect.height - ui_size(32),
            ),
        )
        panel = pygame.Rect(0, 0, width, height)
        panel.center = screen_rect.center
        max_prompt_lines = max(1, (panel.height - fixed_height) // line_height)
        prompt_lines = prompt_lines[:max_prompt_lines]
        field = pygame.Rect(
            panel.left + ui_size(24),
            panel.top + ui_size(76) + len(prompt_lines) * line_height,
            max(1, panel.width - ui_size(48)),
            ui_size(46),
        )
        return panel, field, prompt_lines

    def _render_story_input(self):
        panel, field, prompt_lines = self._story_input_geometry()
        pygame.draw.rect(self.screen, (24, 25, 38), panel, border_radius=ui_size(10))
        pygame.draw.rect(
            self.screen,
            self.theme.get("colors", {}).get("border", (112, 86, 101)),
            panel,
            width=max(1, ui_size(2)),
            border_radius=ui_size(10),
        )
        heading = FONTS.char_name.render("Story Input", True, COLORS.text_highlight)
        self.screen.blit(heading, heading.get_rect(midtop=(panel.centerx, panel.top + ui_size(18))))

        font = FONTS.normal_text
        for index, line in enumerate(prompt_lines):
            rendered = font.render(line, True, COLORS.text)
            self.screen.blit(
                rendered,
                rendered.get_rect(midtop=(panel.centerx, panel.top + ui_size(62) + index * font.get_linesize())),
            )

        pygame.draw.rect(self.screen, (12, 13, 22), field, border_radius=ui_size(5))
        pygame.draw.rect(
            self.screen,
            self.theme.get("colors", {}).get("border", (112, 86, 101)),
            field,
            width=max(1, ui_size(1)),
            border_radius=ui_size(5),
        )
        answer = self.story_input["text"]
        while answer and font.size(answer)[0] > field.width - ui_size(20):
            answer = answer[1:]
        rendered_answer = font.render(answer, True, COLORS.text)
        self.screen.blit(
            rendered_answer,
            rendered_answer.get_rect(midleft=(field.left + ui_size(10), field.centery)),
        )
        if self.story_input["error"]:
            error = FONTS.button_text.render(self.story_input["error"], True, COLORS.text_highlight)
            self.screen.blit(error, error.get_rect(midtop=(panel.centerx, field.bottom + ui_size(6))))
        help_text = FONTS.button_text.render("Type your answer, then press Enter", True, COLORS.text)
        self.screen.blit(help_text, help_text.get_rect(midbottom=(panel.centerx, panel.bottom - ui_size(14))))

    def _handle_confirmation_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_y):
                self._confirm_dialogue_action()
            elif event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_n):
                self.confirmation = None
                self.confirmation_button_rects = {}
                if self.mode == "game":
                    self._resume_choice_timeout()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.confirmation_button_rects.get("confirm", pygame.Rect(0, 0, 0, 0)).collidepoint(event.pos):
                self._confirm_dialogue_action()
            else:
                self.confirmation = None
                self.confirmation_button_rects = {}
                if self.mode == "game":
                    self._resume_choice_timeout()

    def _render_confirmation(self):
        shade = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 190))
        self.screen.blit(shade, (0, 0))
        width = max(1, min(ui_size(560), self.screen.get_width() - ui_size(32)))
        height = max(1, min(ui_size(190), self.screen.get_height() - ui_size(32)))
        panel = pygame.Rect(0, 0, width, height)
        panel.center = self.screen.get_rect().center
        pygame.draw.rect(self.screen, (24, 25, 38), panel, border_radius=ui_size(10))
        pygame.draw.rect(
            self.screen,
            self.theme.get("colors", {}).get("border", (112, 86, 101)),
            panel,
            width=max(1, ui_size(2)),
            border_radius=ui_size(10),
        )
        locale = self.settings.values.get("locale", "en")
        ui_table = self.translation_tables.get(locale, {}).get("ui", {})
        heading_text = translate_label(locale, "Are you sure?", ui_table)
        heading = FONTS.char_name.render(heading_text, True, COLORS.text_highlight)
        self.screen.blit(heading, heading.get_rect(midtop=(panel.centerx, panel.top + ui_size(18))))

        message_width = max(1, panel.width - ui_size(32))
        message_lines = []
        current_line = ""
        for word in self.confirmation["message"].split():
            candidate = f"{current_line} {word}".strip()
            if current_line and FONTS.button_text.size(candidate)[0] > message_width:
                message_lines.append(current_line)
                current_line = word
            else:
                current_line = candidate
        if current_line:
            message_lines.append(current_line)
        buttons_top = panel.bottom - ui_size(54)
        line_height = FONTS.button_text.get_linesize()
        message_top = min(panel.top + ui_size(60), buttons_top - line_height)
        for index, line in enumerate(message_lines):
            message = FONTS.button_text.render(line, True, COLORS.text)
            self.screen.blit(
                message,
                message.get_rect(
                    center=(panel.centerx, message_top + index * line_height)
                ),
            )

        button_height = ui_size(38)
        buttons_top = panel.bottom - button_height - ui_size(16)
        gap = ui_size(16)
        button_width = min(
            ui_size(110), max(1, (panel.width - ui_size(32) - gap) // 2)
        )
        total_width = button_width * 2 + gap
        left = panel.centerx - total_width // 2
        self.confirmation_button_rects = {
            "confirm": pygame.Rect(left, buttons_top, button_width, button_height),
            "cancel": pygame.Rect(left + button_width + gap, buttons_top, button_width, button_height),
        }
        for action, label in (("confirm", "Yes"), ("cancel", "Cancel")):
            rect = self.confirmation_button_rects[action]
            hovered = rect.collidepoint(pygame.mouse.get_pos())
            color = self.theme.get("colors", {}).get(
                "hover" if hovered else "normal", (18, 18, 29)
            )
            pygame.draw.rect(self.screen, color, rect, border_radius=ui_size(5))
            pygame.draw.rect(
                self.screen,
                self.theme.get("colors", {}).get("border", (112, 86, 101)),
                rect,
                width=max(1, ui_size(1)),
                border_radius=ui_size(5),
            )
            text = FONTS.button_text.render(translate_label(locale, label, ui_table), True, COLORS.text)
            self.screen.blit(text, text.get_rect(center=rect.center))

    def _confirm_dialogue_action(self):
        confirmation = self.confirmation
        action = confirmation["action"]
        self.confirmation = None
        self.confirmation_button_rects = {}
        if action == "quick_save":
            self._quick_save()
        elif action == "quick_load":
            self._quick_load()
        elif action == "delete_slot":
            self._delete_selected_slot()
        elif action == "copy_slot":
            self._copy_selected_slot()
        elif action == "remove_mod":
            package = self._selected_mod()
            if package is not None:
                try:
                    name = package["name"]
                    self.assets.remove_mod_package(package["key"])
                    self.status_message = f"Removed {name}."
                    self._open_mod_manager(self.mod_origin)
                except (OSError, ValueError, KeyError) as error:
                    self.status_message = f"Could not remove mod: {error}"
        elif action == "import_slot":
            try:
                self.save_system.import_slot(
                    confirmation["import_path"],
                    self.selected_slot,
                    expected_story=self.story_file,
                )
                self.status_message = f"Imported save into slot {self.selected_slot}."
                self._refresh_slots_menu()
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                self.status_message = f"Could not import save: {error}"
        if self.mode == "game":
            self._resume_choice_timeout()

    def _handle_save_name_event(self, event):
        if event.type == pygame.TEXTINPUT:
            self.save_name_prompt["text"] = (self.save_name_prompt["text"] + event.text)[:48]
        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                custom_name = self.save_name_prompt["text"].strip()
                self.save_name_prompt = None
                pygame.key.stop_text_input()
                self._save_selected_slot(custom_name)
            elif event.key == pygame.K_BACKSPACE:
                self.save_name_prompt["text"] = self.save_name_prompt["text"][:-1]
            elif event.key == pygame.K_ESCAPE:
                self.save_name_prompt = None
                pygame.key.stop_text_input()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.save_name_prompt.get("confirm_rect", pygame.Rect(0, 0, 0, 0)).collidepoint(event.pos):
                custom_name = self.save_name_prompt["text"].strip()
                self.save_name_prompt = None
                pygame.key.stop_text_input()
                self._save_selected_slot(custom_name)
            elif self.save_name_prompt.get("cancel_rect", pygame.Rect(0, 0, 0, 0)).collidepoint(event.pos):
                self.save_name_prompt = None
                pygame.key.stop_text_input()

    def _render_save_name_prompt(self):
        shade = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 190))
        self.screen.blit(shade, (0, 0))
        width = max(1, min(ui_size(620), self.screen.get_width() - ui_size(32)))
        height = max(1, min(ui_size(220), self.screen.get_height() - ui_size(32)))
        panel = pygame.Rect(0, 0, width, height)
        panel.center = self.screen.get_rect().center
        pygame.draw.rect(self.screen, (24, 25, 38), panel, border_radius=ui_size(10))
        pygame.draw.rect(self.screen, self.theme.get("colors", {}).get("border", (112, 86, 101)),
                         panel, width=max(1, ui_size(2)), border_radius=ui_size(10))
        heading = FONTS.char_name.render("Name this save", True, COLORS.text_highlight)
        self.screen.blit(heading, heading.get_rect(midtop=(panel.centerx, panel.top + ui_size(18))))
        field = pygame.Rect(panel.left + ui_size(22), panel.top + ui_size(72), panel.width - ui_size(44), ui_size(48))
        pygame.draw.rect(self.screen, (8, 9, 16), field, border_radius=ui_size(5))
        text_value = self.save_name_prompt["text"] or "Leave blank to use the chapter name"
        color = COLORS.text if self.save_name_prompt["text"] else (145, 145, 155)
        text = FONTS.button_text.render(text_value, True, color)
        self.screen.blit(text, text.get_rect(midleft=(field.left + ui_size(10), field.centery)))
        button_width = ui_size(130)
        button_height = ui_size(38)
        gap = ui_size(16)
        left = panel.centerx - button_width - gap // 2
        top = panel.bottom - button_height - ui_size(18)
        self.save_name_prompt["confirm_rect"] = pygame.Rect(left, top, button_width, button_height)
        self.save_name_prompt["cancel_rect"] = pygame.Rect(left + button_width + gap, top, button_width, button_height)
        for rect, label in (
            (self.save_name_prompt["confirm_rect"], "Save"),
            (self.save_name_prompt["cancel_rect"], "Cancel"),
        ):
            pygame.draw.rect(self.screen, (73, 50, 65), rect, border_radius=ui_size(5))
            label_surface = FONTS.button_text.render(label, True, COLORS.text)
            self.screen.blit(label_surface, label_surface.get_rect(center=rect.center))

    def _quick_save(self):
        if self.flow is None:
            self.status_message = self._message("no_active_game")
            return
        try:
            self.save_system.save_quick_save(
                self.story_file,
                self.flow,
                self.background_id,
                self.music_track,
                self.character_layer.snapshot(),
                self.dialogue_history,
                **self._save_context(),
                custom_name="Quick Save",
            )
            self.status_message = self._message("save_success", slot="Quick Save")
        except (OSError, ValueError) as error:
            self.status_message = self._message("save_error", error=error)

    def _quick_load(self):
        try:
            saved_game = self.save_system.read_quick_save()
        except (OSError, ValueError, TypeError) as error:
            self.status_message = self._message("load_error", error=error)
            return
        if saved_game is not None and saved_game.get("story") == self.story_file:
            try:
                self._apply_saved_game(saved_game)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError, pygame.error) as error:
                self.status_message = self._message("load_error", error=error)
            return
        self._continue_game()

    def _menu_over_game(self):
        return self.mode == "pause_menu" or self.menu_origin == "pause_menu"

    def _advance_story(self):
        if self.flow.finished:
            return
        if not self.textbox.complete:
            self.textbox.reveal_all()
            return
        self.seen_dialogues.add(self.flow.current_id)
        if self.story_input is not None:
            self._activate_story_input()
            return
        if self._fade_out_blocks_input():
            return

        previous_id = self.flow.current_id
        had_choices = self.flow.choices_visible
        if not self.flow.options:
            self._remember_dialogue_state()
        self.flow.advance()
        if self.flow.current_id != previous_id:
            self._enter_dialogue()
        else:
            self._sync_choice_buttons()
            if self.flow.choices_visible and not had_choices:
                self._announce(self._ui_text("speech.choices", "Choices") + ". " + ". ".join(option["label"] for option in self.flow.options))

    def _enter_dialogue(self, apply_actions=True):
        dialogue = self.flow.current
        self.visited_dialogues.add(self.flow.current_id)
        self._current_dialogue_was_seen = self.flow.current_id in self.seen_dialogues
        self._auto_advance_deadline = None
        self._choice_timeout_deadline = None
        self._choice_timeout_paused_remaining = None
        self.active_character = dialogue.get("active_character", dialogue["speaker"])
        parsed = parse(dialogue["text"])
        if apply_actions:
            self._record_dialogue(dialogue, parsed)
            self._apply_story_actions(dialogue.get("actions", []), parsed)
        self._play_voice(dialogue.get("voice"))
        self.textbox.start_text(
            dialogue.get("speaker_name", dialogue["speaker"]),
            dialogue["text"],
            parsed=parsed,
            values=self.flow.variables,
        )
        speaker_name = dialogue.get("speaker_name", dialogue.get("speaker", ""))
        spoken_text = self._plain_dialogue_text(parsed)
        self._announce(". ".join(part for part in (speaker_name, spoken_text) if part))
        if self.story_input is not None:
            self._announce(self.story_input["prompt"])
        if self.flow.choices_visible:
            self._announce(self._ui_text("speech.choices", "Choices") + ". " + ". ".join(option["label"] for option in self.flow.options))
        self.textbox.ms_per_char = max(5, int(30 / self.settings.values["type_speed"]))
        if self.flow.choices_visible or not self.settings.values["animated_text"]:
            self.textbox.reveal_all()
        self._sync_choice_buttons()

    def _apply_story_actions(self, actions, parsed_text):
        dialogue_id = self.flow.current_id if self.flow is not None else ""
        for index, action in enumerate(actions):
            self._execute_story_action(action, f"dialogues.{dialogue_id}.actions.{index}")
        # Preserve existing inline markers; explicit story actions are preferred.
        for word, style in parsed_text:
            if "set_image" in style:
                self._set_background(word)
            if "play_sound" in style:
                self._play_sound(word)

    def _execute_story_action(self, action, localization_prefix=None):
        action_type = action["type"]
        if action_type in {"set", "add", "subtract"}:
            return  # StoryFlow has already applied variable assignments.
        if action_type == "input":
            prompt = self._localized_action_text(action["prompt"], f"{localization_prefix}.prompt")
            self._begin_story_input(action, prompt)
        elif action_type == "background":
            self._set_background(action["image"])
        elif action_type == "clear_background":
            self.background_id = None
            self.background_image = None
        elif action_type == "show_character":
            self.character_layer.show(
                action["name"],
                action["expression"],
                action.get("position"),
                action.get("look"),
                "none" if self.settings.values.get("reduced_motion", False) else action.get("transition", "none"),
                action.get("duration", 0.35),
                action.get("easing", "ease_out"),
            )
        elif action_type == "animate_character":
            self.character_layer.animate(
                action["name"],
                action["frames"],
                action.get("position"),
                action.get("look"),
                action.get("frame_duration", 0.25),
                action.get("loop", True),
            )
        elif action_type == "hide_character":
            transition = "none" if self.settings.values.get("reduced_motion", False) else action.get("transition", "none")
            self.character_layer.hide_with_transition(
                action["name"],
                transition,
                action.get("duration", 0.35),
                action.get("easing", "ease_out"),
            )
        elif action_type == "clear_characters":
            self.character_layer.clear()
        elif action_type == "sound":
            self._play_sound(action["name"])
        elif action_type == "music":
            self._play_music(action["track"])
        elif action_type == "stop_music":
            self._stop_music()
        elif action_type == "fade":
            self._start_fade(action)
        elif action_type == "shake":
            self._start_shake(action)
        elif action_type == "autosave":
            self._save_autosave()
        elif action_type == "unlock_cg":
            label = self._localized_action_text(action.get("label", action["id"]), f"{localization_prefix}.label")
            self.progress_store.unlock("cgs", action["id"], {"image": action["image"], "label": label})
        elif action_type == "unlock_music":
            label = self._localized_action_text(action.get("label", action["id"]), f"{localization_prefix}.label")
            self.progress_store.unlock("music", action["id"], {"track": action["track"], "label": label})
        elif action_type == "achievement":
            title = self._localized_action_text(action.get("title", action["id"]), f"{localization_prefix}.title")
            description = self._localized_action_text(action.get("description", ""), f"{localization_prefix}.description")
            if self.progress_store.unlock("achievements", action["id"], {"title": title, "description": description}):
                self.status_message = f"Achievement unlocked: {title}"
        elif action_type == "complete_route":
            title = self._localized_action_text(action.get("title", action["id"]), f"{localization_prefix}.title")
            self.progress_store.unlock("routes", action["id"], {"title": title})

    def _localized_action_text(self, value, key=None):
        if self.flow is not None and isinstance(value, (str, dict)):
            return self.flow._localized_value(value, key)
        return value if isinstance(value, str) else str(value)

    def _record_dialogue(self, dialogue, parsed_text):
        plain_text = self._plain_dialogue_text(parsed_text)
        self.dialogue_history.append({
            "dialogue": self.flow.current_id,
            "speaker": dialogue.get("speaker_name", dialogue.get("speaker", "")),
            "text": plain_text,
        })
        if len(self.dialogue_history) > 2000:
            del self.dialogue_history[:-2000]

    def _plain_dialogue_text(self, parsed_text):
        pieces = []
        for word, style in parsed_text:
            if "set_image" in style or "play_sound" in style:
                continue
            if "value" in style:
                word = str(self.flow.variables.get(word, "{" + word + "}"))
            pieces.append(word)
        return "".join(pieces)

    def _play_voice(self, voice):
        if self.voice_channel is not None:
            self.voice_channel.stop()
        self.current_voice = voice
        self.voice_sound = None
        self.voice_channel = None
        if not voice or not self.settings.values.get("voice_enabled", True) or not pygame.mixer.get_init():
            return
        self.voice_sound = self.assets.load_sound(voice)
        if self.voice_sound is not None:
            self.voice_sound.set_volume(self._effective_sfx_volume())
            self.voice_channel = self.voice_sound.play()

    def _replay_voice(self):
        if self.current_voice:
            self._play_voice(self.current_voice)

    def _start_fade(self, action):
        now = pygame.time.get_ticks()
        start_alpha = self._current_fade_alpha(now)
        color = action.get("color", [0, 0, 0])
        max_alpha = color[3] if len(color) == 4 else 255
        target_alpha = max_alpha if action["direction"] == "out" else 0
        if action["direction"] == "in" and self.fade_effect is None:
            start_alpha = max_alpha
        duration = round(float(action.get("duration", 0.6)) * 1000)
        if self.settings.values.get("reduced_motion", False):
            duration = 0
        self.fade_effect = {
            "color": tuple(color[:3]),
            "from": start_alpha,
            "to": target_alpha,
            "started": now,
            "duration": duration,
        }

    def _current_fade_alpha(self, now=None):
        effect = self.fade_effect
        if effect is None:
            return 0
        now = pygame.time.get_ticks() if now is None else now
        progress = max(0.0, min(1.0, (now - effect["started"]) / max(1, effect["duration"])))
        return round(effect["from"] + (effect["to"] - effect["from"]) * progress)

    def _fade_out_blocks_input(self):
        effect = self.fade_effect
        if effect is None or effect["to"] <= effect["from"]:
            return False
        return pygame.time.get_ticks() - effect["started"] < effect["duration"]

    def _render_fade(self):
        if self.fade_effect is None:
            return
        alpha = self._current_fade_alpha()
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((*self.fade_effect["color"], alpha))
        self.screen.blit(overlay, (0, 0))

    def _start_shake(self, action):
        if self.settings.values.get("reduced_motion", False):
            self.shake_effect = None
            return
        now = pygame.time.get_ticks()
        self.shake_effect = {
            "started": now,
            "duration": round(float(action.get("duration", 0.35)) * 1000),
            "intensity": float(action.get("intensity", 8)),
        }

    def _shake_offset(self):
        if self.settings.values.get("reduced_motion", False):
            self.shake_effect = None
            return 0, 0
        effect = self.shake_effect
        if effect is None:
            return 0, 0
        elapsed = pygame.time.get_ticks() - effect["started"]
        if elapsed >= effect["duration"]:
            self.shake_effect = None
            return 0, 0
        remaining = 1.0 - elapsed / max(1, effect["duration"])
        strength = max(1, round(effect["intensity"] * remaining))
        return random.randint(-strength, strength), random.randint(-strength, strength)

    def _render_history(self):
        shade = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 190))
        self.screen.blit(shade, (0, 0))
        width = min(self.screen.get_width() - ui_size(100), ui_size(1100))
        panel = pygame.Rect(0, 0, width, self.screen.get_height() - ui_size(120))
        panel.center = (self.screen.get_width() // 2, self.screen.get_height() // 2)
        pygame.draw.rect(self.screen, (24, 25, 38), panel, border_radius=ui_size(10))
        pygame.draw.rect(self.screen, (112, 86, 101), panel, width=ui_size(2), border_radius=ui_size(10))
        locale = self.settings.values.get("locale", "en")
        ui_table = self.translation_tables.get(locale, {}).get("ui", {})
        heading = FONTS.char_name.render(
            translate_label(locale, "Dialogue History", ui_table), True, COLORS.text_highlight
        )
        self.screen.blit(heading, (panel.left + ui_size(24), panel.top + ui_size(18)))
        help_text = FONTS.button_text.render("H or Esc: close   Up/Down or mouse wheel: scroll", True, COLORS.text)
        self.screen.blit(help_text, (panel.left + ui_size(24), panel.bottom - ui_size(34)))
        font = FONTS.normal_text
        content_width = panel.width - ui_size(48)
        lines = []
        for item in self.dialogue_history:
            source = f"{item['speaker']}: {item['text']}"
            words = source.split()
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and font.size(candidate)[0] > content_width:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            lines.append(current)
            lines.append("")
        line_height = font.get_linesize() + ui_size(3)
        visible_count = max(1, (panel.height - ui_size(100)) // line_height)
        max_scroll = max(0, len(lines) - visible_count)
        self.history_scroll = max(0, min(self.history_scroll, max_scroll))
        end = max(0, len(lines) - self.history_scroll)
        start = max(0, end - visible_count)
        for index, line in enumerate(lines[start:end]):
            if line:
                rendered = font.render(line, True, COLORS.text)
                self.screen.blit(rendered, (panel.left + ui_size(24), panel.top + ui_size(62) + index * line_height))

    def _set_background(self, image_id):
        self.background_id = image_id
        self.background_image = self.assets.load_image(image_id)

    def _play_sound(self, sound_id):
        self.assets.play_sound(sound_id, self._effective_sfx_volume())

    def _play_music(self, track):
        if self.music_track == track:
            return
        self.assets.play_music(track, self._effective_music_volume())
        self.music_track = track

    def _stop_music(self):
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
        self.music_track = None

    def _play_menu_sound(self, name):
        renderer = self._renderer_for_active_menu() if self.menu_renderer is not None else None
        play_sound = getattr(renderer, "play_sound", None)
        if not callable(play_sound):
            return
        play_sound(name, self._effective_sfx_volume())

    def _sync_choice_buttons(self):
        options = self.flow.options if self.flow is not None and self.flow.choices_visible else []
        if len(options) == len(self.choice_buttons):
            return
        self.choice_buttons = []
        self.focused_choice_index = 0
        if not options:
            return

        count = len(options)
        button_theme = self.theme.get("choice_buttons", {})
        gap = max(0, ui_size(button_theme.get("gap", 12)))
        button_width = min(
            ui_size(button_theme.get("width", 900)),
            max(1, self.window_size[0] - ui_size(96)),
        )
        top = ui_size(40)
        bottom = self.textbox.rect.top - ui_size(20)
        available_height = max(1, bottom - top)
        max_button_height = max(1, (available_height - (count - 1) * gap) // count)
        button_height = min(ui_size(button_theme.get("height", 56)), max_button_height)
        total_height = count * button_height + (count - 1) * gap
        start_y = top + max(0, (available_height - total_height) // 2)
        start_x = (self.window_size[0] - button_width) // 2
        normal_name = button_theme.get("normal")
        hovered_name = button_theme.get("hovered")
        normal_image = self.assets.load_image(normal_name).convert_alpha() if normal_name else None
        hovered_image = self.assets.load_image(hovered_name).convert_alpha() if hovered_name else None
        for index in range(count):
            y = start_y + index * (button_height + gap)
            self.choice_buttons.append(
                Button(
                    start_x,
                    y,
                    button_width,
                    button_height,
                    normal_image,
                    hovered_image,
                )
            )

    def _start_new_game(self, start_id=None, initial_variables=None):
        self._end_story_input()
        self.flow = StoryFlow(
            self.story_data,
            self.project.assets_dir,
            PATHS.engine_assets,
            start_id=start_id,
            initial_variables=initial_variables,
            locale=self.settings.values.get("locale"),
            fallback_locale=self.default_locale,
            asset_manager=self.assets,
            translation_tables=self.translation_tables,
        )
        self.dialogue_history = []
        self.choice_history = []
        self.visited_choices = set()
        self.seen_dialogues = set()
        self.history_visible = False
        self.history_scroll = 0
        self.dialogue_back_stack = []
        self.visited_dialogues = set()
        self.fade_effect = None
        self.shake_effect = None
        self._preview_surface = None
        self.play_time_seconds = 0.0
        self._play_started_at = pygame.time.get_ticks()
        self._last_autosave_at = pygame.time.get_ticks()
        self.auto_mode = self.settings.values["auto_advance"]
        self.skip_mode = None
        self.background_id = None
        self.background_image = None
        self.character_layer.clear()
        self.active_character = None
        self._stop_music()
        self.mode = "game"
        self.menu_origin = None
        self.status_message = ""
        self._enter_dialogue()

    def _open_pause_menu(self):
        self._pause_play_time()
        self.mode = "pause_menu"
        self.menu_origin = "pause_menu"
        self.active_menu = self.pause_menu
        self.status_message = ""

    def _open_settings(self, origin):
        self.return_mode = origin
        self.menu_origin = "pause_menu" if origin == "pause_menu" else None
        self.mode = "settings"
        self.active_menu = self.settings_menu
        self.settings_offset = 0
        self.settings_selected = 0
        self._refresh_settings_menu()
        self._announce("Settings")

    def _open_slots(self, context, origin):
        self.slot_context = context
        self.return_mode = origin
        self.menu_origin = "pause_menu" if origin == "pause_menu" else None
        self.mode = "slots"
        self.active_menu = self.slot_menu
        self.selected_slot = None
        self.copy_source_slot = None
        self._refresh_slots_menu()
        self.slot_menu.selected = 0
        self._slot_button_rects = {}

    def _open_extras(self, origin):
        self.extras_origin = origin
        self.menu_origin = "pause_menu" if origin == "pause_menu" else None
        self.mode = "extras"
        self.active_menu = self.extras_menu
        self.extras_menu.set_items([
            {"label": "CG Gallery", "detail": str(len(self.progress_store.values["cgs"])), "action": "open_gallery"},
            {"label": "Music Room", "detail": str(len(self.progress_store.values["music"])), "action": "open_music_gallery"},
            {"label": "Achievements", "detail": str(len(self.progress_store.values["achievements"])), "action": "open_achievements"},
            {"label": "Routes", "detail": str(len(self.progress_store.values["routes"])), "action": "open_routes"},
            {"label": "Mods", "detail": str(len(self.assets.mod_packages())), "action": "open_mod_manager"},
            {"label": "Back", "action": "back"},
        ], title="Extras")
        self._announce("Extras")

    def _open_mod_manager(self, origin=None):
        if origin is not None:
            self.mod_origin = origin
        self.mode = "mods"
        return_to_pause = (
            self.extras_origin == "pause_menu" if self.mod_origin == "extras"
            else self.mod_origin == "pause_menu"
        )
        self.menu_origin = "pause_menu" if return_to_pause else None
        self.mod_records = self.assets.mod_packages()
        items = []
        for package in self.mod_records:
            warning = "! " if package["errors"] else ""
            locale = self.settings.values.get("locale", "en")
            ui_table = self.translation_tables.get(locale, {}).get("ui", {})
            state = translate_label(locale, "Enabled" if package["enabled"] else "Disabled", ui_table)
            if package["conflicts"]:
                conflicts_label = translate_label(locale, "Conflicts", ui_table)
                state += f" · {len(package['conflicts'])} {conflicts_label}"
            items.append({
                "label": f"{warning}{package['name']}",
                "detail": f"{state} · {package['version'] or 'unknown version'}",
                "action": "inspect_mod",
                "package_key": package["key"],
            })
        if not self.mod_records:
            items.append({"label": "No packages installed", "action": ""})
        items.extend([
            {"label": translate_label(self.settings.values.get("locale", "en"), "Install Package...", self.translation_tables.get(self.settings.values.get("locale", "en"), {}).get("ui", {})), "action": "install_mod"},
            {"label": "Back", "action": "back"},
        ])
        self.mods_menu.set_items(items, title="Installed Mods")
        self.active_menu = self.mods_menu
        self.status_message = self._ui_text(
            "mods.install_note",
            "Install .vnmod files here. Mod changes take effect after restarting the game.",
        )
        self._announce("Installed Mods")

    def _selected_mod(self):
        return next((item for item in self.mod_records if item["key"] == self.selected_mod_key), None)

    def _open_mod_details(self, package_key):
        self.selected_mod_key = package_key
        package = self._selected_mod()
        if package is None:
            self._open_mod_manager(self.mod_origin)
            return
        actions = []
        if not package["errors"]:
            actions.append({"label": "Disable" if package["enabled"] else "Enable", "action": "toggle_mod"})
        if package["source"] == "user":
            actions.append({"label": "Remove", "action": "remove_mod"})
        actions.append({"label": "Back", "action": "back"})
        self.mod_details_menu.set_items(actions, title="Mod Details")
        self.mode = "mod_details"
        self.active_menu = self.mod_details_menu
        self._announce(f"{package['name']}. {package['source']} package")

    def _draw_mod_panel(self):
        width, height = self.screen.get_size()
        panel_width = min(ui_size(1080), width - ui_size(64))
        self._mod_panel_rect = pygame.Rect((width - panel_width) // 2, ui_size(130), panel_width, height - ui_size(205))
        panel = pygame.Surface(self._mod_panel_rect.size, pygame.SRCALPHA)
        panel.fill((8, 8, 16, 210))
        self.screen.blit(panel, self._mod_panel_rect)
        pygame.draw.rect(self.screen, (95, 84, 112), self._mod_panel_rect, width=ui_size(1), border_radius=ui_size(10))

    def _draw_mod_details(self):
        package = self._selected_mod()
        if package is None:
            return
        panel = self._mod_panel_rect
        title = FONTS.char_name.render(package["name"], True, COLORS.text_highlight)
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.top + ui_size(58))))
        locale = self.settings.values.get("locale", "en")
        ui_table = self.translation_tables.get(locale, {}).get("ui", {})
        tr = lambda key, fallback: translate_label(locale, fallback, ui_table)
        lines = [
            f"ID: {package['id'] or 'unavailable'}   Version: {package['version'] or 'unknown'}",
            f"{tr('mods.source', 'Source')}: {package['source']}   {tr('mods.state', 'State')}: {tr('mods.enabled' if package['enabled'] else 'mods.disabled', 'Enabled' if package['enabled'] else 'Disabled')}",
            f"{tr('mods.assets', 'Assets')}: {len(package['assets'])}",
        ]
        detail_lines = []
        for conflict in package["conflicts"][:4]:
            detail_lines.append(f"{tr('mods.conflict', 'Conflict')}: {conflict['asset']} — {tr('mods.winner', 'uses')}: {conflict['winner']}")
        if len(package["conflicts"]) > 4:
            detail_lines.append(f"... and {len(package['conflicts']) - 4} more conflicts")
        for error in package["errors"][:4]:
            detail_lines.append(f"{tr('mods.load_issue', 'Load issue')}: {error}")
        if len(package["errors"]) > 4:
            detail_lines.append(f"... and {len(package['errors']) - 4} more load issues")
        if not package["conflicts"] and not package["errors"]:
            detail_lines.append(tr('mods.clean', 'No package errors or asset conflicts.'))
        visible_lines = max(1, (self._mod_panel_rect.height - ui_size(210)) // max(1, FONTS.button_text.get_linesize()))
        detail_capacity = max(0, visible_lines - len(lines))
        lines.extend(detail_lines[:detail_capacity])
        if len(detail_lines) > detail_capacity and len(lines) < visible_lines:
            lines.append("Additional conflict or load details are available in the Asset Diagnostics report.")
        slots_left = max(0, visible_lines - len(lines))
        asset_slots = max(0, min(4, slots_left - (1 if len(package["assets"]) > 0 else 0)))
        asset_preview = package["assets"][:asset_slots]
        lines.extend(f"  {tr('mods.asset', 'Asset')}: {asset}" for asset in asset_preview)
        remaining_assets = len(package["assets"]) - len(asset_preview)
        if remaining_assets > 0 and len(lines) < visible_lines:
            lines.append(f"... and {remaining_assets} more assets")
        font = FONTS.button_text
        y = panel.top + ui_size(100)
        max_lines = max(1, (panel.height - ui_size(210)) // max(1, font.get_linesize()))
        for line in lines[:max_lines]:
            rendered = font.render(line, True, COLORS.text)
            self.screen.blit(rendered, rendered.get_rect(midtop=(panel.centerx, y)))
            y += font.get_linesize() + ui_size(5)
        labels = [item["label"] for item in self.mod_details_menu.items]
        gap = ui_size(14)
        button_height = ui_size(44)
        button_width = min(ui_size(190), max(ui_size(100), (panel.width - ui_size(40) - gap * max(0, len(labels) - 1)) // max(1, len(labels))))
        total_width = button_width * len(labels) + gap * max(0, len(labels) - 1)
        left = panel.centerx - total_width // 2
        top = panel.bottom - button_height - ui_size(26)
        self._mod_detail_buttons = []
        for index, label in enumerate(labels):
            rect = pygame.Rect(left + index * (button_width + gap), top, button_width, button_height)
            selected = index == self.mod_details_menu.selected
            color = self.theme.get("colors", {}).get("selected" if selected else "normal", (18, 18, 29))
            pygame.draw.rect(self.screen, color, rect, border_radius=ui_size(5))
            pygame.draw.rect(self.screen, self.theme.get("colors", {}).get("border", (112, 86, 101)), rect, width=ui_size(1), border_radius=ui_size(5))
            rendered = FONTS.button_text.render(translate_label(locale, label, ui_table), True, COLORS.text)
            self.screen.blit(rendered, rendered.get_rect(center=rect.center))
            self._mod_detail_buttons.append(rect)

    def _toggle_selected_mod(self):
        package = self._selected_mod()
        if package is None or package["errors"]:
            return
        try:
            package_key = package["key"]
            self.assets.set_mod_enabled(package_key, not package["enabled"])
            self._open_mod_manager(self.mod_origin)
            self._open_mod_details(package_key)
            self.status_message = self._ui_text(
                "mods.restart_note",
                "Mod state saved. Restart the game for asset changes to take effect.",
            )
        except (OSError, ValueError, KeyError) as error:
            self.status_message = f"Could not update mod state: {error}"

    def _install_mod_package(self):
        chooser = None
        try:
            import tkinter as tk
            from tkinter import filedialog

            chooser = tk.Tk()
            chooser.withdraw()
            selected = filedialog.askopenfilename(
                title="Install VN asset package",
                filetypes=(("VN asset packages", "*.vnmod"),),
                parent=chooser,
            )
            if not selected:
                return
            output = self.assets.install_mod_package(Path(selected))
            self._open_mod_manager(self.mod_origin)
            self.status_message = f"Installed {output.name}. Restart the game to load it."
        except Exception as error:
            self.status_message = f"Could not install mod package: {error}"
        finally:
            if chooser is not None:
                try:
                    chooser.destroy()
                except Exception:
                    pass

    def _open_progress_list(self, mode, category, title):
        self.return_mode = "extras"
        self.menu_origin = "pause_menu" if self.extras_origin == "pause_menu" else None
        self.mode = mode
        self.progress_category = category
        self.progress_title = title
        self.progress_offset = 0
        self.progress_selected = 0
        records = self.progress_store.values[category]
        entries = []
        for identifier, record in records.items():
            if category == "cgs":
                entry = {"label": record.get("label", identifier), "action": "view_cg", "progress_id": identifier}
                try:
                    entry["preview_surface"] = self.assets.load_image(record["image"])
                except (KeyError, FileNotFoundError, pygame.error):
                    pass
                entries.append(entry)
            elif category == "music":
                entries.append({"label": record.get("label", identifier), "action": "play_gallery_track", "progress_id": identifier})
            elif category == "achievements":
                entries.append({"label": record.get("title", identifier), "detail": record.get("description", ""), "action": "", "progress_id": identifier})
            else:
                entries.append({"label": record.get("title", identifier), "detail": "Completed", "action": "", "progress_id": identifier})
        entries.sort(key=lambda item: item["label"].casefold())
        self.progress_entries = entries or [{"label": "Nothing unlocked yet", "action": ""}]
        self._refresh_progress_window()

    def _progress_menu(self):
        return {
            "gallery": self.gallery_menu,
            "music_gallery": self.music_gallery_menu,
            "achievements": self.achievement_menu,
            "routes": self.routes_menu,
        }.get(self.mode)

    def _progress_visible_rows(self):
        return max(2, (self.screen.get_height() - ui_size(260)) // ui_size(65) - 1)

    def _refresh_progress_window(self):
        visible = self._progress_visible_rows()
        max_offset = max(0, len(self.progress_entries) - visible)
        self.progress_offset = max(0, min(self.progress_offset, max_offset))
        items = [dict(item) for item in self.progress_entries[self.progress_offset:self.progress_offset + visible]]
        items.append({"label": "Back", "action": "back"})
        menu = self._progress_menu()
        menu.set_items(items, title=self.progress_title)
        menu.selected = max(0, min(self.progress_selected - self.progress_offset, len(items) - 1))
        self.active_menu = menu

    def _move_progress_selection(self, offset):
        self.progress_selected = max(0, min(len(self.progress_entries), self.progress_selected + offset))
        visible = self._progress_visible_rows()
        if self.progress_selected < self.progress_offset:
            self.progress_offset = self.progress_selected
        elif self.progress_selected < len(self.progress_entries) and self.progress_selected >= self.progress_offset + visible:
            self.progress_offset = self.progress_selected - visible + 1
        self._refresh_progress_window()
        self._play_menu_sound("hover")
        if self.active_menu.selected_item:
            self._announce(self.active_menu.selected_item.get("label", ""))

    def _scroll_progress(self, offset):
        max_offset = max(0, len(self.progress_entries) - self._progress_visible_rows())
        self.progress_offset = max(0, min(max_offset, self.progress_offset + offset))
        self.progress_selected = max(self.progress_offset, min(
            self.progress_selected, min(len(self.progress_entries), self.progress_offset + self._progress_visible_rows() - 1)
        ))
        self._refresh_progress_window()

    def _set_progress_offset(self, offset):
        max_offset = max(0, len(self.progress_entries) - self._progress_visible_rows())
        self.progress_offset = max(0, min(max_offset, offset))
        self.progress_selected = max(self.progress_offset, min(
            self.progress_selected, min(len(self.progress_entries), self.progress_offset + self._progress_visible_rows() - 1)
        ))
        self._refresh_progress_window()

    def _draw_progress_panel(self):
        width, height = self.screen.get_size()
        panel_width = min(ui_size(1080), width - ui_size(64))
        self._progress_panel_rect = pygame.Rect((width - panel_width) // 2, ui_size(150), panel_width, height - ui_size(235))
        panel = pygame.Surface(self._progress_panel_rect.size, pygame.SRCALPHA)
        panel.fill((8, 8, 16, 210))
        self.screen.blit(panel, self._progress_panel_rect)
        pygame.draw.rect(self.screen, (95, 84, 112), self._progress_panel_rect, width=ui_size(1), border_radius=ui_size(10))

    def _draw_progress_scrollbar(self):
        if not self.progress_entries:
            return
        panel = self._progress_panel_rect
        track = pygame.Rect(panel.right - ui_size(25), panel.top + ui_size(18), ui_size(8), panel.height - ui_size(36))
        self._progress_scroll_track = track
        pygame.draw.rect(self.screen, (45, 43, 56), track, border_radius=4)
        visible = self._progress_visible_rows()
        thumb_height = max(ui_size(28), int(track.height * min(1.0, visible / len(self.progress_entries))))
        max_offset = max(0, len(self.progress_entries) - visible)
        travel = track.height - thumb_height
        thumb_y = track.top + (travel * self.progress_offset / max_offset if max_offset else 0)
        self._progress_scroll_thumb = pygame.Rect(track.x, int(thumb_y), track.width, thumb_height)
        pygame.draw.rect(self.screen, (170, 150, 192), self._progress_scroll_thumb, border_radius=ui_size(4))

    def _go_back(self):
        self.status_message = ""
        if self.mode == "slots" and self.slot_context == "copy":
            self._cancel_copy_mode()
        elif self.mode == "cg_viewer":
            self.gallery_image = None
            self.mode = "gallery"
            self._refresh_progress_window()
        elif self.mode in {"gallery", "music_gallery", "achievements", "routes"}:
            self.mode = "extras"
            self.menu_origin = "pause_menu" if self.extras_origin == "pause_menu" else None
            self.active_menu = self.extras_menu
        elif self.mode == "mod_details":
            self._open_mod_manager(self.mod_origin)
        elif self.mode == "mods":
            self.mode = self.mod_origin
            self.menu_origin = "pause_menu" if (
                self.mode == "pause_menu" or (self.mode == "extras" and self.extras_origin == "pause_menu")
            ) else None
            self.active_menu = self.extras_menu if self.mode == "extras" else (
                self.pause_menu if self.mode == "pause_menu" else self.main_menu
            )
        elif self.mode == "extras":
            self.mode = self.extras_origin
            self.menu_origin = "pause_menu" if self.mode == "pause_menu" else None
            self.active_menu = self.pause_menu if self.mode == "pause_menu" else self.main_menu
        elif self.mode == "pause_menu":
            self.mode = "game"
            self.menu_origin = None
            self._resume_play_time()
        elif self.mode in {"settings", "slots", "credits"}:
            self.mode = self.return_mode
            self.menu_origin = "pause_menu" if self.mode == "pause_menu" else None
            self.active_menu = self.pause_menu if self.mode == "pause_menu" else self.main_menu
        elif self.mode == "main_menu":
            self.running = False

    def _activate_menu_item(self):
        item = self.active_menu.selected_item
        if item is None:
            return
        action = item.get("action", "")
        if not action:
            return
        if item.get("label"):
            self._announce(item["label"])
        self.status_message = ""

        if action == "new_game":
            self._start_new_game()
        elif action == "open_extras":
            self._open_extras(self.mode)
        elif action == "open_mod_manager":
            self._open_mod_manager(self.mode)
        elif action == "inspect_mod":
            self._open_mod_details(item.get("package_key"))
        elif action == "toggle_mod":
            self._toggle_selected_mod()
        elif action == "remove_mod":
            package = self._selected_mod()
            if package is not None:
                self._request_confirmation("remove_mod", f"Remove installed mod {package['name']}?")
        elif action == "install_mod":
            self._install_mod_package()
        elif action == "open_gallery":
            self._open_progress_list("gallery", "cgs", "CG Gallery")
        elif action == "open_music_gallery":
            self._open_progress_list("music_gallery", "music", "Music Room")
        elif action == "open_achievements":
            self._open_progress_list("achievements", "achievements", "Achievements")
        elif action == "open_routes":
            self._open_progress_list("routes", "routes", "Routes")
        elif action == "view_cg":
            identifier = item.get("progress_id")
            record = self.progress_store.values["cgs"].get(identifier, {})
            try:
                self.gallery_image = self.assets.load_image(record["image"])
                self.gallery_image_label = record.get("label", identifier or "")
                self.return_mode = "gallery"
                self.mode = "cg_viewer"
                self.active_menu = Menu("CG Gallery", [{"label": "Back", "action": "back"}], kind="gallery")
            except (KeyError, FileNotFoundError, pygame.error) as error:
                self.status_message = f"Could not open CG: {error}"
        elif action == "play_gallery_track":
            identifier = item.get("progress_id")
            record = self.progress_store.values["music"].get(identifier, {})
            try:
                self._play_music(record["track"])
                self.status_message = f"Now playing: {record.get('label', identifier)}"
            except (KeyError, FileNotFoundError, pygame.error) as error:
                self.status_message = f"Could not play track: {error}"
        elif action == "continue_game":
            self._continue_game()
        elif action == "open_load_slots":
            self._open_slots("load", self.mode)
        elif action == "open_save_slots":
            self._open_slots("save", self.mode)
        elif action == "open_settings":
            self._open_settings(self.mode)
        elif action == "open_credits":
            self._open_credits(self.mode)
        elif action == "open_credit_link":
            url = item.get("url")
            if url:
                if sys.platform == "emscripten":
                    import platform

                    platform.window.open(url)
                else:
                    import webbrowser

                    webbrowser.open(url)
        elif action == "quit":
            self.running = False
        elif action == "resume":
            self.mode = "game"
            self.menu_origin = None
            self._resume_play_time()
        elif action == "return_to_main_menu":
            self._stop_music()
            self.mode = "main_menu"
            self.menu_origin = None
            self.active_menu = self.main_menu
        elif action == "back":
            self._go_back()
        elif action == "adjust_setting":
            self._adjust_selected_setting(1, item.get("setting"))
        elif action == "toggle_setting":
            self._toggle_setting(item.get("setting"))
        elif action == "save_slot":
            self.selected_slot = item["slot"]
            self._save_selected_slot()
        elif action == "load_slot":
            self.selected_slot = item["slot"]
            self._load_selected_slot()
        elif action == "delete_selected_slot":
            self._request_confirmation(
                "delete_slot", f"Delete the save in slot {self.selected_slot}?"
            )
        else:
            self.status_message = self._message("unknown_menu_action", action=action)

    def _message(self, message_id, **values):
        template = self.project.values["messages"].get(message_id, message_id)
        locale = self.settings.values.get("locale", "en")
        table = self.translation_tables.get(locale, {}).get("ui", {})
        template = translate_ui(locale, f"message.{message_id}", template, table)
        try:
            return template.format(**values)
        except (KeyError, ValueError):
            return template

    def _ui_text(self, key, fallback, **values):
        locale = self.settings.values.get("locale", "en")
        table = self.translation_tables.get(locale, {}).get("ui", {})
        template = table.get(key) if isinstance(table, dict) else None
        if not isinstance(template, str) or not template:
            template = translate_label(locale, fallback, table)
        try:
            return template.format(**values)
        except (KeyError, ValueError):
            return template

    def _translate_menu_labels(self, menu):
        if menu is None:
            return
        locale = self.settings.values.get("locale", "en")
        table = self.translation_tables.get(locale, {}).get("ui", {})
        last_title = getattr(menu, "_ui_last_translated_title", None)
        if last_title is None or menu.title != last_title:
            menu._ui_source_title = menu.title
        menu.title = self._ui_text(
            getattr(menu, "_ui_translation_key", ""),
            getattr(menu, "_ui_source_title", menu.title),
        )
        menu._ui_last_translated_title = menu.title
        for item in menu.items:
            item.setdefault("_ui_source_label", item.get("label", ""))
            item["label"] = self._ui_text(
                item.get("_ui_translation_key", ""), item["_ui_source_label"]
            )
            if "detail" in item:
                item.setdefault("_ui_source_detail", item.get("detail", ""))
                item["detail"] = self._ui_text(
                    item.get("_ui_detail_translation_key", ""), item["_ui_source_detail"]
                )

    def _ensure_speech(self):
        if self.speech_announcer is None:
            self.speech_announcer = SpeechAnnouncer()
        return self.speech_announcer

    def _announce(self, text):
        if not self.settings.values.get("speech_enabled") or not text:
            return
        announcer = self._ensure_speech()
        if announcer.available is False:
            if not self._speech_unavailable_reported:
                self.status_message = self._ui_text(
                    "speech.unavailable",
                    "Speech output is unavailable. Install pyttsx3 or enable a system speech service.",
                )
                self._speech_unavailable_reported = True
            return
        locale = self.settings.values.get("locale", "en")
        ui_table = self.translation_tables.get(locale, {}).get("ui", {})
        text = translate_label(locale, str(text), ui_table)
        announcer.speak(text, locale)

    def _continue_game(self):
        slot = self.save_system.latest_slot()
        try:
            autosave = self.save_system.read_autosave()
        except (OSError, ValueError):
            autosave = None
        slot_save = None
        if slot is not None:
            try:
                slot_save = self.save_system.read_slot(slot)
            except (OSError, ValueError):
                slot_save = None
        if slot_save is not None and slot_save.get("story") != self.story_file:
            slot_save = None
        if autosave is not None and autosave.get("story") == self.story_file and (
            slot_save is None
            or _save_time(autosave) > _save_time(slot_save)
        ):
            self._load_autosave()
            return
        if slot is None:
            self.status_message = self._message("no_continue_save")
            return
        self._load_slot(slot)

    def _open_credits(self, origin):
        self.return_mode = origin
        self.menu_origin = "pause_menu" if origin == "pause_menu" else None
        self.mode = "credits"
        self.credits_entries = [self._normalize_credit(entry) for entry in self.project.values.get("credits", [])]
        self.credits_entries.append({"label": "Marpp: Creator of the VN Engine", "url": "https://marpp.itch.io/"})
        self.credits_offset = 0
        self.credits_selected = 0
        self._refresh_credits_window()
        self.active_menu = self.credits_menu

    @staticmethod
    def _normalize_credit(entry):
        if isinstance(entry, str):
            return {"label": entry, "url": None}
        return {"label": entry["label"], "url": entry.get("url")}

    def _refresh_credits_window(self):
        visible = max(3, (self.screen.get_height() - ui_size(260)) // ui_size(65))
        content_rows = visible - 1
        max_offset = max(0, len(self.credits_entries) - content_rows)
        self.credits_offset = max(0, min(self.credits_offset, max_offset))
        entries = self.credits_entries[self.credits_offset:self.credits_offset + content_rows]
        items = [{"label": item["label"], "action": "open_credit_link" if item["url"] else "", "url": item["url"]}
                 for item in entries]
        items.append({"label": "Back", "action": "back"})
        self.credits_menu.set_items(items, title="Credits")
        self.credits_menu.selected = max(0, min(self.credits_selected - self.credits_offset, len(items) - 1))

    def _move_credit_selection(self, offset):
        self.credits_selected = max(0, min(len(self.credits_entries), self.credits_selected + offset))
        visible_rows = max(2, (self.screen.get_height() - ui_size(260)) // ui_size(65) - 1)
        if self.credits_selected < self.credits_offset:
            self.credits_offset = self.credits_selected
        elif self.credits_selected >= self.credits_offset + visible_rows:
            self.credits_offset = self.credits_selected - visible_rows + 1
        self._refresh_credits_window()
        self._play_menu_sound("hover")
        if self.active_menu.selected_item:
            self._announce(self.active_menu.selected_item.get("label", ""))

    def _scroll_credits(self, offset):
        visible_rows = max(2, (self.screen.get_height() - ui_size(260)) // ui_size(65) - 1)
        max_offset = max(0, len(self.credits_entries) - visible_rows)
        self.credits_offset = max(0, min(max_offset, self.credits_offset + offset))
        self.credits_selected = max(
            self.credits_offset,
            min(self.credits_selected, self.credits_offset + visible_rows - 1),
        )
        self._refresh_credits_window()

    def _draw_credits_panel(self):
        width, height = self.screen.get_size()
        panel_width = min(ui_size(1080), width - ui_size(64))
        self._credits_panel_rect = pygame.Rect((width - panel_width) // 2, ui_size(150), panel_width, height - ui_size(235))
        panel = pygame.Surface(self._credits_panel_rect.size, pygame.SRCALPHA)
        panel.fill((8, 8, 16, 210))
        self.screen.blit(panel, self._credits_panel_rect)
        pygame.draw.rect(self.screen, (95, 84, 112), self._credits_panel_rect, width=ui_size(1), border_radius=ui_size(10))

    def _draw_credits_scrollbar(self):
        if not self.credits_entries:
            return
        panel = self._credits_panel_rect
        track = pygame.Rect(panel.right - ui_size(25), panel.top + ui_size(18), ui_size(8), panel.height - ui_size(36))
        self._credits_scroll_track = track
        pygame.draw.rect(self.screen, (45, 43, 56), track, border_radius=4)
        visible_rows = max(2, (self.screen.get_height() - ui_size(260)) // ui_size(65) - 1)
        ratio = min(1.0, visible_rows / len(self.credits_entries))
        thumb_height = max(ui_size(28), int(track.height * ratio))
        max_offset = max(0, len(self.credits_entries) - visible_rows)
        travel = track.height - thumb_height
        thumb_y = track.top + (travel * self.credits_offset / max_offset if max_offset else 0)
        self._credits_scroll_thumb = pygame.Rect(track.x, int(thumb_y), track.width, thumb_height)
        pygame.draw.rect(self.screen, (170, 150, 192), self._credits_scroll_thumb, border_radius=ui_size(4))

    def _render_slot_buttons(self):
        width, height = self.screen.get_size()
        if self.slot_context == "save":
            buttons = (
                ("delete", "Delete"), ("import", "Import"), ("export", "Export"),
                ("save", "Save"), ("back", "Back"),
            )
        elif self.slot_context == "copy":
            buttons = (("cancel_copy", "Cancel Copy"), ("copy", "Copy Here"), ("back", "Back"))
        else:
            buttons = (
                ("delete", "Delete"), ("start_copy", "Copy"), ("import", "Import"),
                ("export", "Export"), ("load", "Load"), ("back", "Back"),
            )
        gap = ui_size(12)
        button_count = len(buttons)
        button_width = min(
            ui_size(150),
            max(ui_size(48), (width - ui_size(48) - gap * (button_count - 1)) // button_count),
        )
        button_height = ui_size(46)
        total_width = button_width * button_count + gap * (button_count - 1)
        left = (width - total_width) // 2
        top = height - ui_size(82)
        self._slot_button_rects = {}
        selected = self.selected_slot is not None
        exists = False
        if selected:
            entry = next((item for item in self._slot_infos if item["slot"] == self.selected_slot), None)
            exists = bool(entry and entry["save"] is not None and not entry["error"])
        if self.slot_context == "save":
            enabled = {
                "delete": exists, "import": selected, "export": exists,
                "save": selected, "back": True,
            }
        elif self.slot_context == "copy":
            enabled = {
                "cancel_copy": True,
                "copy": selected and self.selected_slot != self.copy_source_slot,
                "back": True,
            }
        else:
            enabled = {
                "delete": exists, "start_copy": exists, "import": selected,
                "export": exists, "load": exists, "back": True,
            }
        self._slot_button_enabled = enabled
        locale = self.settings.values.get("locale", "en")
        ui_table = self.translation_tables.get(locale, {}).get("ui", {})
        for index, (action, label) in enumerate(buttons):
            rect = pygame.Rect(left + index * (button_width + gap), top, button_width, button_height)
            self._slot_button_rects[action] = rect
            color = (73, 50, 65) if enabled[action] else (42, 42, 48)
            text_color = (238, 238, 242) if enabled[action] else (115, 115, 122)
            pygame.draw.rect(self.screen, color, rect, border_radius=ui_size(7))
            pygame.draw.rect(self.screen, (112, 86, 101), rect, width=ui_size(1), border_radius=ui_size(7))
            font = FONTS.button_text
            text = font.render(translate_label(locale, label, ui_table), True, text_color)
            self.screen.blit(text, text.get_rect(center=rect.center))

    def _handle_slot_button_click(self, position):
        for action, rect in self._slot_button_rects.items():
            if not rect.collidepoint(position):
                continue
            self._play_menu_sound("click")
            if not self._slot_button_enabled.get(action, False):
                return True
            if action == "back":
                self._go_back()
            elif action == "delete":
                self._request_confirmation(
                    "delete_slot", f"Delete the save in slot {self.selected_slot}?"
                )
            elif action == "import":
                self._import_selected_slot()
            elif action == "export":
                self._export_selected_slot()
            elif action == "start_copy":
                self.copy_source_slot = self.selected_slot
                self.slot_context = "copy"
                self.selected_slot = None
                self._refresh_slots_menu()
                self.slot_menu.selected = 0
            elif action == "cancel_copy":
                self._cancel_copy_mode()
            elif action == "copy" and self.selected_slot is not None:
                self._request_confirmation(
                    "copy_slot",
                    f"Copy slot {self.copy_source_slot} over slot {self.selected_slot}?",
                )
            elif action == "load" and self.slot_context == "load":
                self._load_selected_slot()
            elif action == "save" and self.slot_context == "save":
                self._save_selected_slot()
            return True
        return False

    def _save_selected_slot(self, custom_name=None):
        if self.flow is None:
            self.status_message = self._message("no_active_game")
            return
        if custom_name is None:
            self.save_name_prompt = {"text": ""}
            pygame.key.start_text_input()
            return
        try:
            self.save_system.save_slot(
                self.selected_slot,
                self.story_file,
                self.flow,
                self.background_id,
                self.music_track,
                self.character_layer.snapshot(),
                self.dialogue_history,
                **self._save_context(),
                custom_name=custom_name,
            )
            self.status_message = self._message("save_success", slot=self.selected_slot)
            self._refresh_slots_menu()
            self.mode = self.return_mode
            self.menu_origin = "pause_menu" if self.mode == "pause_menu" else None
            self.active_menu = self.pause_menu if self.mode == "pause_menu" else self.main_menu
        except (OSError, ValueError) as error:
            self.status_message = self._message("save_error", error=error)

    def _load_selected_slot(self):
        self._load_slot(self.selected_slot)

    def _select_save_file(self, *, export=False):
        if sys.platform in {"emscripten", "android"}:
            self.status_message = "Save file dialogs are unavailable on this platform."
            return None
        owner = None
        try:
            import tkinter as tk
            from tkinter import filedialog

            owner = tk.Tk()
            owner.withdraw()
            try:
                owner.attributes("-topmost", True)
            except tk.TclError:
                pass
            if export:
                selected = filedialog.asksaveasfilename(
                    parent=owner,
                    title="Export Save",
                    initialfile=f"slot_{self.selected_slot}.vnsave.json",
                    defaultextension=".vnsave.json",
                    filetypes=(("VN Save Files", "*.vnsave.json"), ("JSON files", "*.json")),
                )
            else:
                selected = filedialog.askopenfilename(
                    parent=owner,
                    title="Import Save",
                    filetypes=(("VN Save Files", "*.vnsave.json"), ("JSON files", "*.json")),
                )
            return selected or None
        except Exception as error:
            self.status_message = f"Could not open a save file dialog: {error}"
            return None
        finally:
            if owner is not None:
                try:
                    owner.destroy()
                except Exception:
                    pass

    def _export_selected_slot(self):
        if self.selected_slot is None:
            return
        destination = self._select_save_file(export=True)
        if destination is None:
            return
        try:
            self.save_system.export_slot(self.selected_slot, destination)
            self.status_message = f"Exported save slot {self.selected_slot}."
        except (OSError, ValueError, FileNotFoundError) as error:
            self.status_message = f"Could not export save: {error}"

    def _import_selected_slot(self):
        if self.selected_slot is None:
            return
        source = self._select_save_file()
        if source is None:
            return
        self.confirmation = {
            "action": "import_slot",
            "message": f"Import this save into slot {self.selected_slot}, replacing its current contents?",
            "import_path": source,
        }
        self.confirmation_button_rects = {}

    def _load_slot(self, slot):
        try:
            saved_game = self.save_system.read_slot(slot)
            if saved_game is None:
                self.status_message = self._message("slot_empty", slot=slot)
                return
            self._apply_saved_game(saved_game)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, pygame.error) as error:
            self.status_message = self._message("load_error", error=error)

    def _load_autosave(self):
        try:
            saved_game = self.save_system.read_autosave()
            if saved_game is None:
                self.status_message = self._message("no_continue_save")
                return
            self._apply_saved_game(saved_game)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, pygame.error) as error:
            self.status_message = self._message("load_error", error=error)

    def _apply_saved_game(self, saved_game):
        if saved_game.get("story") != self.story_file:
            self.status_message = self._message("different_story")
            return

        saved_game = self._migrate_story_save(saved_game)
        self._end_story_input()
        flow = StoryFlow(
            self.story_data,
            self.project.assets_dir,
            PATHS.engine_assets,
            locale=self.settings.values.get("locale"),
            fallback_locale=self.default_locale,
            asset_manager=self.assets,
            translation_tables=self.translation_tables,
        )
        flow.restore(saved_game.get("state", {}))
        self.flow = flow
        self.choice_buttons = []
        self.dialogue_back_stack = []
        self.choice_history = [
            item for item in saved_game.get("choice_history", []) if isinstance(item, dict)
        ]
        self.seen_dialogues = {
            dialogue_id for dialogue_id in saved_game.get("seen_dialogues", [])
            if isinstance(dialogue_id, str) and dialogue_id in flow.dialogues
        }
        self.play_time_seconds = max(0.0, float(saved_game.get("play_time_seconds", 0) or 0))
        self._play_started_at = pygame.time.get_ticks()
        self._last_autosave_at = pygame.time.get_ticks()
        self.auto_mode = self.settings.values["auto_advance"]
        self.skip_mode = None
        self.dialogue_history = [
            item for item in saved_game.get("history", [])
            if isinstance(item, dict) and isinstance(item.get("speaker"), str) and isinstance(item.get("text"), str)
        ]
        self.history_visible = False
        self.history_scroll = 0
        self.fade_effect = None
        self.shake_effect = None
        self.background_id = saved_game.get("background")
        self.background_image = None
        if self.background_id is not None:
            self._set_background(self.background_id)
        self.character_layer.restore(saved_game.get("characters", {}))
        self.music_track = None
        saved_music = saved_game.get("music")
        if saved_music:
            self._play_music(saved_music)
        else:
            self._stop_music()

        self.mode = "game"
        self.menu_origin = None
        self.status_message = (
            "Recovered progress from a save backup."
            if saved_game.get("recovered_from_backup") else ""
        )
        self._enter_dialogue(apply_actions=False)
        self._play_menu_sound("load")

    def _migrate_story_save(self, saved_game):
        migrated = deepcopy(saved_game)
        migrations = self.project.values.get("save_migrations", {})
        dialogue_mapping = migrations.get("dialogues", {})
        variable_mapping = migrations.get("variables", {})
        state = migrated.get("state", {})
        if not isinstance(state, dict):
            return migrated

        dialogue_id = state.get("dialogue")
        if isinstance(dialogue_id, str):
            state["dialogue"] = dialogue_mapping.get(dialogue_id, dialogue_id)
        call_stack = state.get("call_stack", [])
        dialogue_ids = set(self.story_data.get("dialogues", {}))
        if isinstance(call_stack, list):
            state["call_stack"] = [
                new_id for old_id in call_stack
                if isinstance(old_id, str)
                for new_id in [dialogue_mapping.get(old_id, old_id)]
                if new_id in dialogue_ids
            ]

        variables = state.get("variables", {})
        declared_variables = self.story_data.get("variables", {})
        if isinstance(variables, dict):
            remapped = {}
            for old_name, value in variables.items():
                new_name = variable_mapping.get(old_name, old_name)
                if new_name is None:
                    continue
                if new_name not in declared_variables:
                    # Variables removed from a later story version no longer
                    # affect its state and are safe to discard.
                    continue
                if new_name not in remapped or new_name == old_name:
                    remapped[new_name] = value
            state["variables"] = remapped

        migrated["seen_dialogues"] = [
            new_id for old_id in migrated.get("seen_dialogues", [])
            if isinstance(old_id, str)
            for new_id in [dialogue_mapping.get(old_id, old_id)]
            if new_id in dialogue_ids
        ]
        remapped_choices = []
        for item in migrated.get("choice_history", []):
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            for key in ("dialogue", "target"):
                value = entry.get(key)
                if isinstance(value, str):
                    entry[key] = dialogue_mapping.get(value, value)
            remapped_choices.append(entry)
        migrated["choice_history"] = remapped_choices
        return migrated

    def _save_autosave(self):
        if self.flow is None:
            return
        try:
            self.save_system.save_autosave(
                self.story_file,
                self.flow,
                self.background_id,
                self.music_track,
                self.character_layer.snapshot(),
                self.dialogue_history,
                **self._save_context(),
            )
            self.autosave_notice_until = pygame.time.get_ticks() + 2200
            self._last_autosave_at = pygame.time.get_ticks()
        except (OSError, ValueError) as error:
            self.status_message = self._message("save_error", error=error)

    def _current_play_time(self):
        elapsed = 0.0
        if self._play_started_at is not None:
            elapsed = max(0, pygame.time.get_ticks() - self._play_started_at) / 1000
        return self.play_time_seconds + elapsed

    def _pause_play_time(self):
        if self._play_started_at is not None:
            self.play_time_seconds = self._current_play_time()
            self._play_started_at = None
        self._auto_advance_deadline = None
        self._pause_choice_timeout()
        self._last_autosave_at = pygame.time.get_ticks()

    def _resume_play_time(self):
        if self.flow is not None and self._play_started_at is None:
            self._play_started_at = pygame.time.get_ticks()
        self._resume_choice_timeout()
        self._last_autosave_at = pygame.time.get_ticks()

    def _pause_choice_timeout(self):
        if self._choice_timeout_deadline is not None:
            self._choice_timeout_paused_remaining = max(
                0,
                self._choice_timeout_deadline - pygame.time.get_ticks(),
            )
            self._choice_timeout_deadline = None

    def _resume_choice_timeout(self):
        if (
            self._choice_timeout_paused_remaining is not None
            and self.flow is not None
            and self.flow.choices_visible
        ):
            self._choice_timeout_deadline = (
                pygame.time.get_ticks() + self._choice_timeout_paused_remaining
            )
            self._choice_timeout_paused_remaining = None

    def _capture_preview(self):
        if self._preview_surface is None:
            return None
        image_data = BytesIO()
        pygame.image.save(self._preview_surface, image_data, "preview.png")
        return base64.b64encode(image_data.getvalue()).decode("ascii")

    def _save_context(self):
        return {
            "play_time_seconds": self._current_play_time(),
            "seen_dialogues": sorted(self.seen_dialogues),
            "choice_history": self.choice_history,
            "preview": self._capture_preview(),
        }

    def _delete_selected_slot(self):
        try:
            if self.save_system.delete_slot(self.selected_slot):
                self.status_message = self._message("delete_success", slot=self.selected_slot)
            else:
                self.status_message = self._message("delete_empty", slot=self.selected_slot)
            self._refresh_slots_menu()
        except (OSError, ValueError) as error:
            self.status_message = self._message("delete_error", error=error)

    def _copy_selected_slot(self):
        try:
            self.save_system.copy_slot(self.copy_source_slot, self.selected_slot)
            self.status_message = self._message(
                "copy_success", source=self.copy_source_slot, slot=self.selected_slot
            )
            copied_slot = self.selected_slot
            self.slot_context = "load"
            self.copy_source_slot = None
            self._refresh_slots_menu()
            self.slot_menu.selected = max(0, min(len(self.slot_menu.items) - 1, copied_slot - 1))
            self._track_slot_selection()
        except (OSError, ValueError, FileNotFoundError) as error:
            self.status_message = self._message("copy_error", error=error)

    def _cancel_copy_mode(self):
        source_slot = self.copy_source_slot
        self.slot_context = "load"
        self.selected_slot = source_slot
        self.copy_source_slot = None
        self._refresh_slots_menu()
        if source_slot is not None:
            self.slot_menu.selected = max(0, min(len(self.slot_menu.items) - 1, source_slot - 1))
            self._track_slot_selection()

    def _track_slot_selection(self):
        if self.mode != "slots":
            return
        item = self.active_menu.selected_item
        if item and "slot" in item:
            self.selected_slot = item["slot"]
            for slot_item in self.active_menu.items:
                slot_item["persistent_selected"] = slot_item.get("slot") == self.selected_slot

    def _refresh_slots_menu(self):
        slot_config = self.project.menus["slots"]
        labels = slot_config["labels"]
        items = []
        slot_action = "save_slot" if self.slot_context == "save" else "load_slot"
        self._slot_infos = self.save_system.list_slots()
        for slot_info in self._slot_infos:
            slot = slot_info["slot"]
            saved_game = slot_info["save"]
            if slot_info["error"]:
                label = self._ui_text("project.menus.slots.labels.slot", labels["slot"], slot=slot)
                detail = self._ui_text("project.menus.slots.labels.corrupt", labels["corrupt"])
            elif saved_game is None:
                label = self._ui_text("project.menus.slots.labels.slot", labels["slot"], slot=slot)
                detail = self._ui_text("project.menus.slots.labels.empty", labels["empty"])
            else:
                metadata = saved_game.get("metadata", {})
                chapter = metadata.get("chapter") or self._ui_text(
                    "project.menus.slots.labels.unknown_chapter", labels["unknown_chapter"]
                )
                dialogue = metadata.get("dialogue", "?")
                unknown_time = self._ui_text(
                    "project.menus.slots.labels.unknown_time", labels["unknown_time"]
                )
                saved_at = saved_game.get("saved_at", unknown_time)
                name_value = metadata.get("name", "")
                custom_name = name_value.strip() if isinstance(name_value, str) else ""
                label = (
                    self._ui_text(
                        "project.menus.slots.labels.slot_custom", "Slot {slot}: {name}",
                        slot=slot, name=custom_name,
                    )
                    if custom_name
                    else self._ui_text(
                        "project.menus.slots.labels.saved", labels["saved"],
                        slot=slot, chapter=chapter, dialogue=dialogue,
                    )
                )
                try:
                    time_label = datetime.fromisoformat(saved_at).astimezone().strftime("%Y-%m-%d %H:%M")
                except (TypeError, ValueError, OverflowError):
                    time_label = unknown_time
                try:
                    seconds = max(0, int(float(saved_game.get("play_time_seconds", 0) or 0)))
                except (TypeError, ValueError, OverflowError):
                    seconds = 0
                duration = f"{seconds // 3600:02}:{(seconds // 60) % 60:02}"
                detail = f"{dialogue} | {time_label} | {duration}"
                if saved_game.get("recovered_from_backup"):
                    recovered = translate_label(
                        self.settings.values.get("locale", "en"), "Recovered backup",
                        self.translation_tables.get(self.settings.values.get("locale", "en"), {}).get("ui", {}),
                    )
                    detail = f"{recovered} | {detail}"
            item = {
                "label": label,
                "detail": detail,
                "action": slot_action,
                "slot": slot,
                "persistent_selected": slot == self.selected_slot,
            }
            preview = saved_game.get("preview") if saved_game else None
            if isinstance(preview, str) and preview:
                item["_preview_data"] = preview
            items.append(item)

        title_key = "title_save" if self.slot_context == "save" else "title_load"
        if self.slot_context == "copy":
            title_key = "title_copy"
        self.slot_menu.set_items(items, title=slot_config[title_key])
        self.slot_menu._ui_translation_key = f"project.menus.slots.{title_key}"
        for item in self.slot_menu.items:
            preview_data = item.pop("_preview_data", None)
            if not preview_data:
                continue
            surface = self._slot_preview_cache.get(preview_data)
            if surface is None:
                try:
                    raw = base64.b64decode(preview_data, validate=True)
                    surface = pygame.image.load(BytesIO(raw)).convert()
                    self._slot_preview_cache[preview_data] = surface
                except (ValueError, pygame.error):
                    continue
            item["preview_surface"] = surface

    def _refresh_settings_menu(self):
        config = self.project.menus["settings"]
        items = []
        configured_items = [
            {
                **item,
                "_ui_translation_key": f"project.menus.settings.items.{index}.label",
                **({"_ui_detail_translation_key": f"project.menus.settings.items.{index}.detail"} if "detail" in item else {}),
            }
            for index, item in enumerate(config["items"])
        ]
        configured_items = [
            item for item in configured_items
            if item.get("setting") not in {"auto_advance", "muted"}
            and (self.allow_fullscreen or item.get("setting") != "fullscreen")
        ]
        if not any(item.get("setting") == "ui_scale" for item in configured_items):
            ui_item = {"label": "UI Size", "action": "adjust_setting", "setting": "ui_scale"}
            back_index = next(
                (index for index, item in enumerate(configured_items) if item.get("action") == "back"),
                len(configured_items),
            )
            configured_items.insert(back_index, ui_item)
        if not any(item.get("setting") == "speech_enabled" for item in configured_items):
            speech_item = {
                "label": "Speech Announcements",
                "action": "toggle_setting",
                "setting": "speech_enabled",
            }
            back_index = next(
                (index for index, item in enumerate(configured_items) if item.get("action") == "back"),
                len(configured_items),
            )
            configured_items.insert(back_index, speech_item)
        if len(getattr(self, "available_locales", {})) > 1 and not any(
            item.get("setting") == "locale" for item in configured_items
        ):
            locale_item = {"label": "Language", "action": "adjust_setting", "setting": "locale"}
            back_index = next(
                (index for index, item in enumerate(configured_items) if item.get("action") == "back"),
                len(configured_items),
            )
            configured_items.insert(back_index, locale_item)
        for configured_item in configured_items:
            item = dict(configured_item)
            setting = item.get("setting")
            if setting in self.settings.values:
                value = self.settings.values[setting]
                if setting == "type_speed":
                    item["detail"] = f"{value:.2f}x"
                elif setting in {"music_volume", "sfx_volume"}:
                    item["detail"] = f"{round(value * 100)}%"
                elif setting == "auto_wait":
                    item["detail"] = f"{value:.2f}s"
                elif setting == "touch_advance_mode":
                    item["detail"] = "Whole Screen" if value == "screen" else "Textbox Only"
                elif setting in {"dialogue_font_scale", "speaker_font_scale"}:
                    item["detail"] = f"{round(value * 100)}%"
                elif setting == "fullscreen":
                    item["detail"] = "Fullscreen" if value else "Windowed"
                elif setting == "ui_scale":
                    item["detail"] = f"< {round(value * 100)}% >"
                elif setting == "locale":
                    item["detail"] = self.available_locales.get(value, value)
                elif isinstance(value, bool):
                    item["detail"] = "On" if value else "Off"
            items.append(item)
        self._settings_all_items = items
        self.settings_selected = min(self.settings_selected, max(0, len(items) - 1))
        self._refresh_settings_window(config["title"])

    def _settings_visible_rows(self):
        return max(3, (self.screen.get_height() - ui_size(280)) // max(1, ui_size(65)))

    def _refresh_settings_window(self, title=None):
        if not self._settings_all_items:
            self.settings_menu.set_items([], title=title)
            self.settings_offset = 0
            self.settings_selected = 0
            return
        visible_rows = self._settings_visible_rows()
        max_offset = max(0, len(self._settings_all_items) - visible_rows)
        self.settings_offset = max(0, min(self.settings_offset, max_offset))
        if self.settings_selected < self.settings_offset:
            self.settings_offset = self.settings_selected
        elif self.settings_selected >= self.settings_offset + visible_rows:
            self.settings_offset = self.settings_selected - visible_rows + 1
        window_items = self._settings_all_items[
            self.settings_offset:self.settings_offset + visible_rows
        ]
        self.settings_menu.set_items(window_items, title=title)
        self.settings_menu.selected = max(
            0,
            min(self.settings_selected - self.settings_offset, len(window_items) - 1),
        )

    def _move_settings_selection(self, direction):
        if not self._settings_all_items:
            return
        old_selection = self.settings_selected
        self.settings_selected = max(
            0,
            min(len(self._settings_all_items) - 1, self.settings_selected + direction),
        )
        if self.settings_selected != old_selection:
            self._refresh_settings_window(self.settings_menu.title)
            self._play_menu_sound("hover")
            if self.settings_menu.selected_item:
                self._announce(self.settings_menu.selected_item.get("label", ""))

    def _set_settings_offset(self, offset):
        visible_rows = self._settings_visible_rows()
        max_offset = max(0, len(self._settings_all_items) - visible_rows)
        self.settings_offset = max(0, min(max_offset, offset))
        self.settings_selected = max(
            self.settings_offset,
            min(self.settings_selected, self.settings_offset + visible_rows - 1),
        )
        self._refresh_settings_window(self.settings_menu.title)

    def _scroll_settings(self, offset):
        self._set_settings_offset(self.settings_offset + offset)

    def _draw_settings_panel(self):
        width, height = self.screen.get_size()
        panel_width = min(ui_size(1080), width - ui_size(64))
        rect = pygame.Rect(
            (width - panel_width) // 2,
            ui_size(132),
            panel_width,
            max(ui_size(220), height - ui_size(220)),
        )
        self._settings_panel_rect = rect
        self.settings_menu.panel_rect = rect

    def _draw_settings_scrollbar(self):
        visible_rows = self._settings_visible_rows()
        if len(self._settings_all_items) <= visible_rows:
            self._settings_scroll_track = pygame.Rect(0, 0, 0, 0)
            self._settings_scroll_thumb = pygame.Rect(0, 0, 0, 0)
            return
        panel = self._settings_panel_rect
        track = pygame.Rect(
            panel.right - ui_size(25),
            panel.top + ui_size(18),
            ui_size(8),
            max(1, panel.height - ui_size(36)),
        )
        self._settings_scroll_track = track
        pygame.draw.rect(self.screen, (45, 43, 56), track, border_radius=ui_size(4))
        ratio = min(1.0, visible_rows / len(self._settings_all_items))
        thumb_height = max(ui_size(28), int(track.height * ratio))
        max_offset = max(1, len(self._settings_all_items) - visible_rows)
        travel = max(0, track.height - thumb_height)
        thumb_y = track.top + travel * self.settings_offset / max_offset
        self._settings_scroll_thumb = pygame.Rect(
            track.x, int(thumb_y), track.width, thumb_height
        )
        pygame.draw.rect(
            self.screen,
            (170, 150, 192),
            self._settings_scroll_thumb,
            border_radius=ui_size(4),
        )

    def _adjust_selected_setting(self, direction, setting=None):
        if setting is None:
            item = self.settings_menu.selected_item or {}
            setting = item.get("setting")
        if setting not in self.settings.values or setting in {
            "fullscreen", "auto_advance", "muted", "high_contrast", "reduced_motion",
            "voice_enabled", "subtitles_enabled", "animated_text",
        }:
            return
        current = self.settings.values[setting]
        if setting == "type_speed":
            self.settings.set(setting, round(current + direction * 0.25, 2))
        elif setting in {"music_volume", "sfx_volume"}:
            self.settings.set(setting, round(current + direction * 0.1, 2))
        elif setting == "ui_scale":
            self.settings.set(setting, round(current + direction * 0.1, 2))
        elif setting == "auto_wait":
            self.settings.set(setting, round(current + direction * 0.25, 2))
        elif setting in {"dialogue_font_scale", "speaker_font_scale"}:
            self.settings.set(setting, round(current + direction * 0.1, 2))
        elif setting == "touch_advance_mode":
            modes = ("screen", "textbox")
            self.settings.set(setting, modes[(modes.index(current) + direction) % len(modes)])
        elif setting == "locale":
            locales = list(self.available_locales)
            if not locales:
                return
            current_locale = current if current in locales else self.default_locale
            index = locales.index(current_locale)
            selected_locale = locales[(index + direction) % len(locales)]
            self.settings.set(setting, selected_locale)
            if self.flow is not None:
                self.flow.locale = selected_locale
                if self.return_mode == "pause_menu":
                    self._enter_dialogue(apply_actions=False)
        self.settings.save()
        self._apply_audio_settings()
        self._sync_text_speed()
        if setting == "ui_scale":
            self._apply_ui_scale()
        elif setting in {"dialogue_font_scale", "speaker_font_scale"}:
            self._apply_comfort_settings()
        if setting == "auto_wait":
            self._auto_advance_deadline = None
        self._refresh_settings_menu()

    def _adjust_or_toggle_setting(self, direction):
        item = self.settings_menu.selected_item or {}
        if item.get("action") == "toggle_setting":
            self._toggle_setting(item.get("setting"))
        else:
            self._adjust_selected_setting(direction, item.get("setting"))

    def _toggle_setting(self, setting):
        toggle_settings = {
            "fullscreen", "auto_advance", "muted", "high_contrast", "reduced_motion",
            "voice_enabled", "subtitles_enabled", "animated_text", "speech_enabled",
        }
        if setting not in self.settings.values or setting not in toggle_settings:
            return
        self.settings.set(setting, not self.settings.values[setting])
        self.settings.save()
        if setting == "fullscreen":
            self._apply_display_settings()
        elif setting == "auto_advance":
            self.auto_mode = self.settings.values[setting]
            self.skip_mode = None if self.auto_mode else self.skip_mode
            self._auto_advance_deadline = None
        elif setting == "muted":
            self._apply_audio_settings()
        elif setting in {"high_contrast", "subtitles_enabled", "dialogue_font_scale", "speaker_font_scale"}:
            self._apply_comfort_settings()
        elif setting == "reduced_motion" and self.settings.values[setting]:
            self.fade_effect = None
            self.shake_effect = None
        elif setting == "voice_enabled" and not self.settings.values[setting]:
            if self.voice_channel is not None:
                self.voice_channel.stop()
                self.voice_channel = None
        elif setting == "animated_text" and not self.settings.values[setting] and self.textbox is not None:
            self.textbox.reveal_all()
        elif setting == "speech_enabled":
            if self.settings.values[setting]:
                self._speech_unavailable_reported = False
                self._announce(self._ui_text("speech.enabled", "Speech announcements enabled"))
            elif self.speech_announcer is not None:
                self.speech_announcer.stop()
                self.speech_announcer = None
        self._refresh_settings_menu()

    def _sync_text_speed(self):
        if self.textbox is not None:
            self.textbox.ms_per_char = max(5, int(30 / self.settings.values["type_speed"]))

    def _apply_ui_scale(self):
        set_ui_scale(self.settings.values["ui_scale"])
        if self.assets is None:
            return
        load_assets(self.assets, self.theme)
        self._apply_comfort_font_sizes()
        if self.renderer_override is None:
            self.menu_renderer = self._create_menu_renderer()
        if self.textbox is not None:
            self.textbox = self._create_textbox(self.textbox)
        self.choice_buttons = []
        self._sync_choice_buttons()
        self._layout_pause_button()
        if self.mode == "credits":
            self._refresh_credits_window()

    def _apply_audio_settings(self):
        if pygame.mixer.get_init():
            pygame.mixer.music.set_volume(self._effective_music_volume())
            channel_volume = 0.0 if self.settings.values.get("muted", False) else 1.0
            for channel_index in range(pygame.mixer.get_num_channels()):
                pygame.mixer.Channel(channel_index).set_volume(channel_volume)

    def _effective_music_volume(self):
        if self.settings.values.get("muted", False):
            return 0.0
        return self.settings.values["music_volume"]

    def _effective_sfx_volume(self):
        if self.settings.values.get("muted", False):
            return 0.0
        return self.settings.values["sfx_volume"]

    def _apply_display_settings(self):
        if self.screen is None:
            return
        flags = pygame.FULLSCREEN if self.allow_fullscreen and self.settings.values["fullscreen"] else 0
        self.screen = pygame.display.set_mode(self.windowed_size, flags)
        new_size = self.screen.get_size()
        if new_size != self.window_size:
            self.window_size = new_size
            if self.textbox is not None:
                old_textbox = self.textbox
                self.textbox = self._create_textbox(old_textbox)
                self.choice_buttons = []
                if self.flow is not None:
                    self._sync_choice_buttons()
        self._layout_pause_button()

    def shutdown(self):
        self.running = False
        self._end_story_input()
        self._write_editor_coverage()
        if self.speech_announcer is not None:
            self.speech_announcer.stop()
        if self.initialized or pygame.get_init():
            pygame.quit()
        self.initialized = False

    def _write_editor_coverage(self):
        coverage_path = os.environ.get("VN_EDITOR_COVERAGE_FILE")
        if self.editor_test_context is None or not coverage_path:
            return
        result = {
            "visited_dialogues": sorted(self.visited_dialogues),
            "choices": [
                {"dialogue": dialogue_id, "target": target}
                for dialogue_id, target in sorted(self.visited_choices)
            ],
            "finished": bool(self.flow and self.flow.finished),
        }
        try:
            os.makedirs(os.path.dirname(coverage_path), exist_ok=True)
            with open(coverage_path, "w", encoding="utf-8") as coverage_file:
                json.dump(result, coverage_file, ensure_ascii=False, indent=2)
        except (OSError, TypeError, ValueError):
            return
