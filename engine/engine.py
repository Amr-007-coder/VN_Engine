import asyncio
import pygame
import math
import random
import sys
from datetime import datetime

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
    TapeSlotRenderer,
)
from engine.parser import parse
from engine.project import ProjectConfig
from engine.save_system import SaveSystem
from engine.settings import SettingsStore
from engine.story import StoryFlow
from engine.theme import resolve_theme
from engine.ui import Button, Textbox
from engine.validator import StoryValidator


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
        self.tape_slot_renderer = None

        self.settings = SettingsStore(self.project.user_data_dir)
        self.save_system = SaveSystem(
            slot_count=self.project.values["save_slots"],
            user_data_dir=self.project.user_data_dir,
        )
        self.textbox = None
        self.flow = None
        self.choice_buttons = []
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
        self.fade_effect = None
        self.shake_effect = None
        self.autosave_notice_until = 0

        self.mode = "main_menu"
        self.menu_origin = None
        self.return_mode = "main_menu"
        self.slot_context = "load"
        self.selected_slot = None
        self._slot_button_rects = {}
        self._slot_button_enabled = {}
        self.active_menu = None
        self.status_message = ""

        self.main_menu = self._make_menu("main")
        self.pause_menu = self._make_menu("pause")
        self.settings_menu = self._make_menu("settings")
        slot_config = self.project.menus["slots"]
        self.slot_menu = Menu(slot_config["title_load"], kind="slots")
        self.credits_menu = Menu("Credits", kind="credits")
        self.credits_entries = []
        self.credits_offset = 0
        self.credits_selected = 0

    def run(self):
        self.initialize()
        self.running = True
        try:
            self._play_intro()
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
        return Menu(config["title"], config["items"], kind=name)

    def _initialize(self):
        # Project files are resolved and validated before pygame opens a window.
        self.story_data = self.project.load_story(self.story_file)
        StoryValidator.validate_or_raise(
            self.story_data,
            self.project.assets_dir,
            PATHS.engine_assets,
        )
        self.settings.load()

        pygame.init()
        try:
            self.assets = AssetManager(self.project.assets_dir)
            self.character_layer = CharacterLayer(
                self.assets, self.story_data.get("character_defaults", {})
            )
            load_assets(self.assets, self.theme)
            textbox_theme = self.theme.get("textbox", {})
            textbox_image_name = textbox_theme.get("background")
            textbox_image = self.assets.load_image(textbox_image_name) if textbox_image_name else None
            textbox_color = textbox_theme.get("color")
            textbox_color = tuple(textbox_color) if textbox_color is not None else COLORS.panel
            flags = pygame.FULLSCREEN if self.settings.values["fullscreen"] else 0
            self.screen = pygame.display.set_mode(self.windowed_size, flags)
            self.window_size = self.screen.get_size()
            pygame.display.set_caption(self.caption)
            self.clock = pygame.time.Clock()
            self.textbox = Textbox(
                40,
                self.window_size[1] - 290,
                max(100, self.window_size[0] - 80),
                250,
                panel_color=textbox_color,
                panel_image=textbox_image,
            )
            self.menu_renderer = self.renderer_override or self._create_menu_renderer()
            self._apply_audio_settings()
            self._refresh_settings_menu()
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
        standard = DeclarativeMenuRenderer(self.assets, self.theme)
        if self.theme.get("slot", {}).get("layout") == "tape":
            self.tape_slot_renderer = TapeSlotRenderer(self.assets, self.theme)
        return standard

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
        font = self.assets.load_font("standard.ttf", max(22, screen_height // 30))
        small_font = self.assets.load_font("standard.ttf", max(16, screen_height // 55))
        cards = [
            {"image": logo, "kind": "logo", "hold": 3.0},
            {"image": self._intro_image(intro["credit_image"]), "kind": "credit", "hold": 2.5},
            {"image": self._intro_image(intro["warning_image"]), "extra_image": self._intro_image(intro["headphones_image"]), "kind": "warning", "hold": 2.5},
        ]
        sound_channel = None
        try:
            intro_sound = self.assets.load_sound("intro.wav")
            if intro_sound is not None:
                intro_sound.set_volume(self.settings.values["sfx_volume"])
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
                tm_rect = tm.get_rect(topright=(logo_rect.right - 5, logo_rect.top + 95))
                tm.set_alpha(round(255 * alpha))
                self.screen.blit(tm, tm_rect)
                lines = ["© 2026 Marpp. All rights reserved.", "Powered by Pygame-CE"]
                if engine_version:
                    lines.append(f"v{engine_version}")
                for index, line in enumerate(lines):
                    rendered = small_font.render(line, True, (190, 198, 215))
                    rendered.set_alpha(round(255 * alpha))
                    self.screen.blit(rendered, rendered.get_rect(center=(screen_width // 2, screen_height - 100 + index * 28)))
            else:
                image = card["image"]
                image_rect = None
                if image is not None:
                    image = pygame.transform.smoothscale(image, (min(image.get_width(), screen_width // 2), min(image.get_height(), screen_height // 2)))
                    image.set_alpha(round(255 * alpha))
                    image_y = screen_height // 2 - (150 if card.get("extra_image") else 90)
                    image_rect = image.get_rect(center=(screen_width // 2, image_y))
                    self.screen.blit(image, image_rect)
                extra_image = card.get("extra_image")
                if extra_image is not None:
                    extra = pygame.transform.smoothscale(extra_image, (min(extra_image.get_width(), screen_width // 3), min(extra_image.get_height(), screen_height // 3)))
                    extra.set_alpha(round(255 * alpha))
                    self.screen.blit(extra, extra.get_rect(center=(screen_width // 2, screen_height // 2 + 190)))
                message = f"A Game by {intro['creator']}" if card["kind"] == "credit" else intro["warning_message"]
                if card["kind"] == "credit" and intro.get("game_version"):
                    message += f"\nVersion {intro['game_version']}"
                text_top = image_rect.bottom + 24 if card["kind"] == "credit" and image_rect else screen_height // 2
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
            elif self.mode == "game":
                self._handle_game_event(event)
            else:
                self._handle_menu_event(event)

    def _handle_game_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self.history_visible:
                    self.history_visible = False
                else:
                    self._open_pause_menu()
            elif event.key == pygame.K_h:
                self.history_visible = not self.history_visible
                self.history_scroll = 0
            elif event.key == pygame.K_v:
                self._replay_voice()
            elif self.history_visible and event.key in (pygame.K_UP, pygame.K_PAGEUP):
                self.history_scroll += 1 if event.key == pygame.K_UP else 8
            elif self.history_visible and event.key in (pygame.K_DOWN, pygame.K_PAGEDOWN):
                self.history_scroll = max(0, self.history_scroll - (1 if event.key == pygame.K_DOWN else 8))
            elif event.key == pygame.K_SPACE:
                if not self.history_visible:
                    self._advance_story()
        elif event.type == pygame.MOUSEWHEEL and self.history_visible:
            self.history_scroll = max(0, self.history_scroll + event.y * 3)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.history_visible:
                self.history_visible = False
            else:
                self._handle_game_click(event.pos)

    def _handle_game_click(self, position):
        if self._fade_out_blocks_input():
            return
        if self.flow.choices_visible:
            for index, button in enumerate(self.choice_buttons):
                if button.update(True, position):
                    self.flow.choose(index)
                    self._enter_dialogue()
                    return
        elif not self.flow.finished:
            self._advance_story()

    def _handle_menu_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._play_menu_sound("cancel")
                self._go_back()
            elif event.key in (pygame.K_UP, pygame.K_w):
                if self.mode == "credits":
                    self._move_credit_selection(-1)
                    return
                if self.active_menu.move(-1):
                    self._play_menu_sound("hover")
                self._track_slot_selection()
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                if self.mode == "credits":
                    self._move_credit_selection(1)
                    return
                if self.active_menu.move(1):
                    self._play_menu_sound("hover")
                self._track_slot_selection()
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._play_menu_sound("click")
                if self.mode == "slots" and self.active_menu.selected_item and "slot" in self.active_menu.selected_item:
                    slot = self.active_menu.selected_item["slot"]
                    if self.selected_slot == slot:
                        self._load_selected_slot() if self.slot_context == "load" else self._save_selected_slot()
                    else:
                        self.selected_slot = slot
                        self._track_slot_selection()
                else:
                    self._activate_menu_item()
            elif event.key == pygame.K_DELETE and self.mode == "slots":
                self._play_menu_sound("click")
                if self.selected_slot is not None:
                    self._delete_selected_slot()
            elif event.key == pygame.K_PAGEUP and self.mode == "credits":
                self._scroll_credits(-1)
            elif event.key == pygame.K_PAGEDOWN and self.mode == "credits":
                self._scroll_credits(1)
            elif event.key == pygame.K_LEFT and self.mode == "settings":
                self._adjust_or_toggle_setting(-1)
            elif event.key == pygame.K_RIGHT and self.mode == "settings":
                self._adjust_or_toggle_setting(1)
        elif event.type == pygame.MOUSEMOTION:
            old_selection = self.active_menu.selected
            selected = self.active_menu.select_at(event.pos)
            if selected is not None and selected != old_selection:
                self._play_menu_sound("hover")
                if self.mode != "slots":
                    self._track_slot_selection()
                if self.mode == "credits":
                    self.credits_selected = min(len(self.credits_entries), self.credits_offset + selected)
        elif event.type == pygame.MOUSEWHEEL and self.mode == "credits":
            self._scroll_credits(-event.y)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.mode == "credits" and getattr(self, "_credits_scroll_track", pygame.Rect(0, 0, 0, 0)).collidepoint(event.pos):
                track = self._credits_scroll_track
                max_offset = max(0, len(self.credits_entries) - max(2, (self.screen.get_height() - 260) // 65 - 1))
                ratio = (event.pos[1] - track.top) / max(1, track.height)
                self.credits_offset = round(max_offset * max(0.0, min(1.0, ratio)))
                self._refresh_credits_window()
                return
            if self.mode == "slots" and self._handle_slot_button_click(event.pos):
                return
            selected = self.active_menu.select_at(event.pos)
            if selected is not None:
                self._track_slot_selection()
                if self.mode == "credits":
                    self.credits_selected = min(len(self.credits_entries), self.credits_offset + selected)
                self._play_menu_sound("click")
                if self.mode != "slots":
                    item = self.active_menu.selected_item
                    if self.mode == "settings" and item.get("action") == "adjust_setting":
                        self._adjust_selected_setting(1, item.get("setting"))
                    else:
                        self._activate_menu_item()

    def _update(self):
        if self.mode != "game":
            return
        self.textbox.update()
        if self.flow.options and self.textbox.complete and not self.flow.choices_visible:
            self.flow.show_choices()
            self._sync_choice_buttons()

    def _render(self):
        if self.mode == "game" or self._menu_over_game():
            self._render_game()
        else:
            self.screen.fill(COLORS.background)

        if self.mode != "game":
            if self._menu_over_game():
                shade = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
                shade.fill((0, 0, 0, 175))
                self.screen.blit(shade, (0, 0))
            if self.mode == "credits":
                self._draw_credits_panel()
            renderer = self._renderer_for_active_menu()
            renderer.render(self.screen, self.active_menu)
            if self.mode == "slots":
                self._render_slot_buttons()
            elif self.mode == "credits":
                self._draw_credits_scrollbar()
            self._render_status()
        else:
            self._render_status()
        pygame.display.flip()

    def _renderer_for_active_menu(self):
        if self.renderer_override is not None:
            return self.renderer_override
        if self.mode == "slots" and self.tape_slot_renderer is not None:
            return self.tape_slot_renderer
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
            for button, option in zip(self.choice_buttons, self.flow.options):
                button.render(option["label"])
                scene.blit(button.surface, button.rect)

        self.screen.fill(COLORS.background)
        shake_x, shake_y = self._shake_offset()
        self.screen.blit(scene, (shake_x, shake_y))
        self._render_fade()
        if self.history_visible:
            self._render_history()
        if pygame.time.get_ticks() < self.autosave_notice_until:
            notice = FONTS.button_text.render("Autosaved", True, COLORS.text)
            box = notice.get_rect(midtop=(self.screen.get_width() // 2, 18)).inflate(28, 16)
            pygame.draw.rect(self.screen, (0, 0, 0, 190), box, border_radius=8)
            self.screen.blit(notice, notice.get_rect(center=box.center))

    def _render_status(self):
        if not self.status_message:
            return
        status = FONTS.button_text.render(self.status_message, True, COLORS.text_highlight)
        self.screen.blit(status, status.get_rect(center=(self.screen.get_width() // 2, self.screen.get_height() - 40)))

    def _menu_over_game(self):
        return self.mode == "pause_menu" or self.menu_origin == "pause_menu"

    def _advance_story(self):
        if self.flow.finished:
            return
        if not self.textbox.complete:
            self.textbox.reveal_all()
            return
        if self._fade_out_blocks_input():
            return

        previous_id = self.flow.current_id
        self.flow.advance()
        if self.flow.current_id != previous_id:
            self._enter_dialogue()
        else:
            self._sync_choice_buttons()

    def _enter_dialogue(self, apply_actions=True):
        dialogue = self.flow.current
        self.active_character = dialogue.get("active_character", dialogue["speaker"])
        parsed = parse(dialogue["text"])
        if apply_actions:
            self._record_dialogue(dialogue, parsed)
            self._apply_story_actions(dialogue.get("actions", []), parsed)
        self._play_voice(dialogue.get("voice"))
        self.textbox.start_text(
            dialogue["speaker"],
            dialogue["text"],
            parsed=parsed,
            values=self.flow.variables,
        )
        self.textbox.ms_per_char = max(5, int(30 / self.settings.values["type_speed"]))
        if self.flow.choices_visible:
            self.textbox.reveal_all()
        self._sync_choice_buttons()

    def _apply_story_actions(self, actions, parsed_text):
        for action in actions:
            self._execute_story_action(action)
        # Preserve existing inline markers; explicit story actions are preferred.
        for word, style in parsed_text:
            if "set_image" in style:
                self._set_background(word)
            if "play_sound" in style:
                self._play_sound(word)

    def _execute_story_action(self, action):
        action_type = action["type"]
        if action_type in {"set", "add", "subtract"}:
            return  # StoryFlow has already applied variable assignments.
        if action_type == "background":
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
            self.character_layer.hide(action["name"])
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

    def _record_dialogue(self, dialogue, parsed_text):
        pieces = []
        for word, style in parsed_text:
            if "set_image" in style or "play_sound" in style:
                continue
            if "value" in style:
                word = str(self.flow.variables.get(word, "{" + word + "}"))
            pieces.append(word)
        self.dialogue_history.append({
            "dialogue": self.flow.current_id,
            "speaker": dialogue.get("speaker", ""),
            "text": "".join(pieces),
        })
        if len(self.dialogue_history) > 2000:
            del self.dialogue_history[:-2000]

    def _play_voice(self, voice):
        if self.voice_channel is not None:
            self.voice_channel.stop()
        self.current_voice = voice
        self.voice_sound = None
        self.voice_channel = None
        if not voice or not pygame.mixer.get_init():
            return
        self.voice_sound = self.assets.load_sound(voice)
        if self.voice_sound is not None:
            self.voice_sound.set_volume(self.settings.values["sfx_volume"])
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
        self.fade_effect = {
            "color": tuple(color[:3]),
            "from": start_alpha,
            "to": target_alpha,
            "started": now,
            "duration": round(float(action.get("duration", 0.6)) * 1000),
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
        now = pygame.time.get_ticks()
        self.shake_effect = {
            "started": now,
            "duration": round(float(action.get("duration", 0.35)) * 1000),
            "intensity": float(action.get("intensity", 8)),
        }

    def _shake_offset(self):
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
        width = min(self.screen.get_width() - 100, 1100)
        panel = pygame.Rect(0, 0, width, self.screen.get_height() - 120)
        panel.center = (self.screen.get_width() // 2, self.screen.get_height() // 2)
        pygame.draw.rect(self.screen, (24, 25, 38), panel, border_radius=10)
        pygame.draw.rect(self.screen, (112, 86, 101), panel, width=2, border_radius=10)
        heading = FONTS.char_name.render("Dialogue History", True, COLORS.text_highlight)
        self.screen.blit(heading, (panel.left + 24, panel.top + 18))
        help_text = FONTS.button_text.render("H or Esc: close   Up/Down or mouse wheel: scroll", True, COLORS.text)
        self.screen.blit(help_text, (panel.left + 24, panel.bottom - 34))
        font = FONTS.normal_text
        content_width = panel.width - 48
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
        line_height = font.get_linesize() + 3
        visible_count = max(1, (panel.height - 100) // line_height)
        max_scroll = max(0, len(lines) - visible_count)
        self.history_scroll = max(0, min(self.history_scroll, max_scroll))
        end = max(0, len(lines) - self.history_scroll)
        start = max(0, end - visible_count)
        for index, line in enumerate(lines[start:end]):
            if line:
                rendered = font.render(line, True, COLORS.text)
                self.screen.blit(rendered, (panel.left + 24, panel.top + 62 + index * line_height))

    def _set_background(self, image_id):
        self.background_id = image_id
        self.background_image = self.assets.load_image(image_id)

    def _play_sound(self, sound_id):
        self.assets.play_sound(sound_id, self.settings.values["sfx_volume"])

    def _play_music(self, track):
        if self.music_track == track:
            return
        self.assets.play_music(track, self.settings.values["music_volume"])
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
        play_sound(name, self.settings.values["sfx_volume"])

    def _sync_choice_buttons(self):
        options = self.flow.options if self.flow is not None and self.flow.choices_visible else []
        if len(options) == len(self.choice_buttons):
            return
        self.choice_buttons = []
        if not options:
            return

        count = len(options)
        gap = 12
        button_height = 56
        button_width = min(900, max(120, self.window_size[0] - 96))
        top = 40
        bottom = self.textbox.rect.top - 20
        available_height = max(1, bottom - top)
        total_height = count * button_height + (count - 1) * gap
        start_y = top + max(0, (available_height - total_height) // 2)
        start_x = (self.window_size[0] - button_width) // 2
        for index in range(count):
            y = start_y + index * (button_height + gap)
            self.choice_buttons.append(
                Button(start_x, y, button_width, button_height)
            )

    def _start_new_game(self):
        self.flow = StoryFlow(self.story_data, self.project.assets_dir, PATHS.engine_assets)
        self.dialogue_history = []
        self.history_visible = False
        self.history_scroll = 0
        self.fade_effect = None
        self.shake_effect = None
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
        self.mode = "pause_menu"
        self.menu_origin = "pause_menu"
        self.active_menu = self.pause_menu
        self.status_message = ""

    def _open_settings(self, origin):
        self.return_mode = origin
        self.menu_origin = "pause_menu" if origin == "pause_menu" else None
        self.mode = "settings"
        self.active_menu = self.settings_menu
        self._refresh_settings_menu()

    def _open_slots(self, context, origin):
        self.slot_context = context
        self.return_mode = origin
        self.menu_origin = "pause_menu" if origin == "pause_menu" else None
        self.mode = "slots"
        self.active_menu = self.slot_menu
        self.selected_slot = None
        self._refresh_slots_menu()
        self.slot_menu.selected = 0
        self._slot_button_rects = {}

    def _go_back(self):
        self.status_message = ""
        if self.mode == "pause_menu":
            self.mode = "game"
            self.menu_origin = None
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
        self.status_message = ""

        if action == "new_game":
            self._start_new_game()
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
            self._delete_selected_slot()
        else:
            self.status_message = self._message("unknown_menu_action", action=action)

    def _message(self, message_id, **values):
        template = self.project.values["messages"].get(message_id, message_id)
        try:
            return template.format(**values)
        except (KeyError, ValueError):
            return template

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
        visible = max(3, (self.screen.get_height() - 260) // 65)
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
        visible_rows = max(2, (self.screen.get_height() - 260) // 65 - 1)
        if self.credits_selected < self.credits_offset:
            self.credits_offset = self.credits_selected
        elif self.credits_selected >= self.credits_offset + visible_rows:
            self.credits_offset = self.credits_selected - visible_rows + 1
        self._refresh_credits_window()
        self._play_menu_sound("hover")

    def _scroll_credits(self, offset):
        visible_rows = max(2, (self.screen.get_height() - 260) // 65 - 1)
        max_offset = max(0, len(self.credits_entries) - visible_rows)
        self.credits_offset = max(0, min(max_offset, self.credits_offset + offset))
        self.credits_selected = max(
            self.credits_offset,
            min(self.credits_selected, self.credits_offset + visible_rows - 1),
        )
        self._refresh_credits_window()

    def _draw_credits_panel(self):
        width, height = self.screen.get_size()
        panel_width = min(1080, width - 64)
        self._credits_panel_rect = pygame.Rect((width - panel_width) // 2, 150, panel_width, height - 235)
        panel = pygame.Surface(self._credits_panel_rect.size, pygame.SRCALPHA)
        panel.fill((8, 8, 16, 210))
        self.screen.blit(panel, self._credits_panel_rect)
        pygame.draw.rect(self.screen, (95, 84, 112), self._credits_panel_rect, width=1, border_radius=10)

    def _draw_credits_scrollbar(self):
        if not self.credits_entries:
            return
        panel = self._credits_panel_rect
        track = pygame.Rect(panel.right - 25, panel.top + 18, 8, panel.height - 36)
        self._credits_scroll_track = track
        pygame.draw.rect(self.screen, (45, 43, 56), track, border_radius=4)
        visible_rows = max(2, (self.screen.get_height() - 260) // 65 - 1)
        ratio = min(1.0, visible_rows / len(self.credits_entries))
        thumb_height = max(28, int(track.height * ratio))
        max_offset = max(0, len(self.credits_entries) - visible_rows)
        travel = track.height - thumb_height
        thumb_y = track.top + (travel * self.credits_offset / max_offset if max_offset else 0)
        self._credits_scroll_thumb = pygame.Rect(track.x, int(thumb_y), track.width, thumb_height)
        pygame.draw.rect(self.screen, (170, 150, 192), self._credits_scroll_thumb, border_radius=4)

    def _render_slot_buttons(self):
        width, height = self.screen.get_size()
        labels = ("Delete", "Save" if self.slot_context == "save" else "Load", "Back")
        button_width, button_height, gap = 150, 46, 12
        total_width = button_width * 3 + gap * 2
        left = (width - total_width) // 2
        top = height - 82
        self._slot_button_rects = {}
        selected = self.selected_slot is not None
        exists = False
        if selected:
            entry = next((item for item in self.save_system.list_slots() if item["slot"] == self.selected_slot), None)
            exists = bool(entry and entry["save"] is not None and not entry["error"])
        enabled = (exists, selected if self.slot_context == "save" else exists, True)
        self._slot_button_enabled = dict(zip(("delete", "save" if self.slot_context == "save" else "load", "back"), enabled))
        for index, label in enumerate(labels):
            rect = pygame.Rect(left + index * (button_width + gap), top, button_width, button_height)
            self._slot_button_rects[label.lower()] = rect
            color = (73, 50, 65) if enabled[index] else (42, 42, 48)
            text_color = (238, 238, 242) if enabled[index] else (115, 115, 122)
            pygame.draw.rect(self.screen, color, rect, border_radius=7)
            pygame.draw.rect(self.screen, (112, 86, 101), rect, width=1, border_radius=7)
            font = FONTS.button_text
            text = font.render(label, True, text_color)
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
            elif self.selected_slot is not None:
                if action == "delete":
                    self._delete_selected_slot()
                elif action == "load" and self.slot_context == "load":
                    self._load_selected_slot()
                elif action == "save" and self.slot_context == "save":
                    self._save_selected_slot()
            return True
        return False

    def _save_selected_slot(self):
        if self.flow is None:
            self.status_message = self._message("no_active_game")
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

        flow = StoryFlow(self.story_data, self.project.assets_dir, PATHS.engine_assets)
        flow.restore(saved_game.get("state", {}))
        self.flow = flow
        self.choice_buttons = []
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
        self.status_message = ""
        self._enter_dialogue(apply_actions=False)
        self._play_menu_sound("load")

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
            )
            self.autosave_notice_until = pygame.time.get_ticks() + 2200
        except (OSError, ValueError) as error:
            self.status_message = self._message("save_error", error=error)

    def _delete_selected_slot(self):
        try:
            if self.save_system.delete_slot(self.selected_slot):
                self.status_message = self._message("delete_success", slot=self.selected_slot)
            else:
                self.status_message = self._message("delete_empty", slot=self.selected_slot)
            self._refresh_slots_menu()
        except (OSError, ValueError) as error:
            self.status_message = self._message("delete_error", error=error)

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
        for slot_info in self.save_system.list_slots():
            slot = slot_info["slot"]
            saved_game = slot_info["save"]
            if slot_info["error"]:
                label, detail = labels["slot"].format(slot=slot), labels["corrupt"]
            elif saved_game is None:
                label, detail = labels["slot"].format(slot=slot), labels["empty"]
            else:
                metadata = saved_game.get("metadata", {})
                chapter = metadata.get("chapter") or labels["unknown_chapter"]
                dialogue = metadata.get("dialogue", "?")
                saved_at = saved_game.get("saved_at", labels["unknown_time"])
                label = labels["saved"].format(slot=slot, chapter=chapter, dialogue=dialogue)
                detail = f"{dialogue} | {saved_at}"
            items.append({"label": label, "detail": detail, "action": slot_action, "slot": slot,
                          "persistent_selected": slot == self.selected_slot})

        title_key = "title_save" if self.slot_context == "save" else "title_load"
        self.slot_menu.set_items(items, title=slot_config[title_key])

    def _refresh_settings_menu(self):
        config = self.project.menus["settings"]
        items = []
        for configured_item in config["items"]:
            item = dict(configured_item)
            setting = item.get("setting")
            if setting in self.settings.values:
                value = self.settings.values[setting]
                if setting == "type_speed":
                    item["detail"] = f"{value:.2f}x"
                elif setting in {"music_volume", "sfx_volume"}:
                    item["detail"] = f"{round(value * 100)}%"
                elif setting == "fullscreen":
                    item["detail"] = "Fullscreen" if value else "Windowed"
            items.append(item)
        self.settings_menu.set_items(items, title=config["title"])

    def _adjust_selected_setting(self, direction, setting=None):
        if setting is None:
            item = self.settings_menu.selected_item or {}
            setting = item.get("setting")
        if setting not in self.settings.values or setting == "fullscreen":
            return
        current = self.settings.values[setting]
        if setting == "type_speed":
            self.settings.set(setting, round(current + direction * 0.25, 2))
        elif setting in {"music_volume", "sfx_volume"}:
            self.settings.set(setting, round(current + direction * 0.1, 2))
        self.settings.save()
        self._apply_audio_settings()
        self._sync_text_speed()
        self._refresh_settings_menu()

    def _adjust_or_toggle_setting(self, direction):
        item = self.settings_menu.selected_item or {}
        if item.get("action") == "toggle_setting":
            self._toggle_setting(item.get("setting"))
        else:
            self._adjust_selected_setting(direction, item.get("setting"))

    def _toggle_setting(self, setting):
        if setting not in self.settings.values or setting != "fullscreen":
            return
        self.settings.set(setting, not self.settings.values[setting])
        self.settings.save()
        self._apply_display_settings()
        self._refresh_settings_menu()

    def _sync_text_speed(self):
        if self.textbox is not None:
            self.textbox.ms_per_char = max(5, int(30 / self.settings.values["type_speed"]))

    def _apply_audio_settings(self):
        if pygame.mixer.get_init():
            pygame.mixer.music.set_volume(self.settings.values["music_volume"])

    def _apply_display_settings(self):
        if self.screen is None:
            return
        flags = pygame.FULLSCREEN if self.settings.values["fullscreen"] else 0
        self.screen = pygame.display.set_mode(self.windowed_size, flags)
        new_size = self.screen.get_size()
        if new_size != self.window_size:
            self.window_size = new_size
            if self.textbox is not None:
                old_textbox = self.textbox
                textbox = Textbox(
                    40,
                    self.window_size[1] - 290,
                    max(100, self.window_size[0] - 80),
                    250,
                    panel_color=tuple(self.theme.get("textbox", {}).get("color") or COLORS.panel),
                    panel_image=(
                        self.assets.load_image(self.theme["textbox"]["background"])
                        if self.theme.get("textbox", {}).get("background") else None
                    ),
                )
                textbox.current_speaker = old_textbox.current_speaker
                textbox.full_parsed_text = old_textbox.full_parsed_text
                textbox.visible_chars = old_textbox.visible_chars
                textbox.last_update_time = old_textbox.last_update_time
                textbox.ms_per_char = old_textbox.ms_per_char
                self.textbox = textbox
                self.choice_buttons = []
                if self.flow is not None:
                    self._sync_choice_buttons()

    def shutdown(self):
        self.running = False
        if self.initialized or pygame.get_init():
            pygame.quit()
        self.initialized = False
