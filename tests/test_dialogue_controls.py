import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pygame

from engine.engine import Engine
from engine.project import ProjectConfig
from engine.save_system import SaveSystem
from engine.story import StoryFlow


class DialogueControlsTests(unittest.TestCase):
    def test_dialogue_button_options_are_configurable_and_validated(self):
        project = ProjectConfig({
            "dialogue_buttons": {
                "history": {"visible": False, "label": "Log"},
            }
        })

        self.assertFalse(project.values["dialogue_buttons"]["history"]["visible"])
        self.assertEqual(project.values["dialogue_buttons"]["history"]["label"], "Log")
        self.assertTrue(project.values["dialogue_buttons"]["back"]["visible"])

        with self.assertRaisesRegex(ValueError, "visible.*boolean"):
            ProjectConfig({
                "dialogue_buttons": {
                    "back": {"visible": "yes"},
                }
            })

    def test_quick_save_uses_a_separate_non_numbered_save_file(self):
        class Flow:
            current = {"chapter": "Chapter 1"}
            current_id = "opening"
            story_data = {"title": "Test"}

            @staticmethod
            def snapshot():
                return {"dialogue": "opening", "variables": {}}

        with tempfile.TemporaryDirectory() as temporary:
            saves = SaveSystem(slot_count=1, user_data_dir=Path(temporary))
            saved = saves.save_quick_save("story.yaml", Flow())

            self.assertEqual(saved["story"], "story.yaml")
            self.assertEqual(saves.read_quick_save(), saved)
            self.assertFalse((Path(temporary) / "saves" / "slot_1.json").exists())

    def test_back_restores_previous_dialogue_variables_and_history(self):
        story = {
            "title": "Test",
            "start": "first",
            "variables": {"count": 0},
            "dialogues": {
                "first": {
                    "speaker": "Narrator",
                    "text": "First",
                    "next": "second",
                    "actions": [{"type": "set", "var": "count", "value": 1}],
                },
                "second": {
                    "speaker": "Narrator",
                    "text": "Second",
                    "actions": [{"type": "set", "var": "count", "value": 2}],
                },
            },
        }
        engine = Engine.__new__(Engine)
        engine.story_data = story
        engine.project = SimpleNamespace(assets_dir=None)
        engine.settings = SimpleNamespace(values={"locale": "en"})
        engine.default_locale = "en"
        engine.translation_tables = {}
        engine.assets = None
        engine.flow = StoryFlow(story)
        engine.background_id = None
        engine.music_track = None
        engine.character_layer = None
        engine.dialogue_history = [{"dialogue": "first", "speaker": "Narrator", "text": "First"}]
        engine.dialogue_back_stack = []
        engine.choice_buttons = []
        engine.choice_history = []
        engine.seen_dialogues = set()
        engine.history_visible = False
        engine.history_scroll = 0
        engine.fade_effect = None
        engine.shake_effect = None
        engine.status_message = ""
        engine._enter_dialogue = Mock()

        engine._remember_dialogue_state()
        engine.flow.advance()
        self.assertEqual(engine.flow.variables["count"], 2)

        self.assertTrue(engine._go_back_dialogue())

        self.assertEqual(engine.flow.current_id, "first")
        self.assertEqual(engine.flow.variables["count"], 1)
        self.assertEqual(engine.dialogue_history[0]["dialogue"], "first")
        engine._enter_dialogue.assert_called_once_with(apply_actions=False)

    def test_back_restores_a_choice_dialogue_before_branching(self):
        story = {
            "title": "Test",
            "start": "choice",
            "variables": {"route": "unset"},
            "dialogues": {
                "choice": {
                    "speaker": "Narrator",
                    "text": "Choose",
                    "options": [
                        {"label": "A", "target": "route_a"},
                        {"label": "B", "target": "route_b"},
                    ],
                },
                "route_a": {
                    "speaker": "Narrator",
                    "text": "A",
                    "actions": [{"type": "set", "var": "route", "value": "a"}],
                },
                "route_b": {"speaker": "Narrator", "text": "B"},
            },
        }
        engine = Engine.__new__(Engine)
        engine.story_data = story
        engine.project = SimpleNamespace(assets_dir=None)
        engine.settings = SimpleNamespace(values={"locale": "en"})
        engine.default_locale = "en"
        engine.translation_tables = {}
        engine.assets = None
        engine.flow = StoryFlow(story)
        engine.flow.show_choices()
        engine.background_id = None
        engine.music_track = None
        engine.character_layer = None
        engine.dialogue_history = []
        engine.dialogue_back_stack = []
        engine.choice_buttons = []
        engine.choice_history = []
        engine.seen_dialogues = set()
        engine.history_visible = False
        engine.history_scroll = 0
        engine.fade_effect = None
        engine.shake_effect = None
        engine.status_message = ""
        engine._enter_dialogue = Mock()

        engine._remember_dialogue_state()
        engine.flow.choose(0)
        self.assertEqual(engine.flow.variables["route"], "a")

        self.assertTrue(engine._go_back_dialogue())

        self.assertEqual(engine.flow.current_id, "choice")
        self.assertTrue(engine.flow.choices_visible)
        self.assertEqual(engine.flow.variables["route"], "unset")

    def test_confirmation_cancel_does_not_run_quick_save(self):
        engine = Engine.__new__(Engine)
        engine.confirmation = {"action": "quick_save", "message": "Save?"}
        engine.confirmation_button_rects = {}
        engine.editor_test_context = None
        engine.mode = "game"
        engine._choice_timeout_paused_remaining = None
        engine._quick_save = Mock()

        engine._handle_game_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))

        self.assertIsNone(engine.confirmation)
        engine._quick_save.assert_not_called()

    def test_confirmation_accept_runs_the_requested_action(self):
        engine = Engine.__new__(Engine)
        engine.confirmation = {"action": "quick_save", "message": "Save?"}
        engine.confirmation_button_rects = {}
        engine.editor_test_context = None
        engine.mode = "game"
        engine._choice_timeout_paused_remaining = None
        engine._quick_save = Mock()

        engine._handle_game_event(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)
        )

        self.assertIsNone(engine.confirmation)
        engine._quick_save.assert_called_once_with()

    def test_quick_load_falls_back_when_quick_save_is_missing(self):
        engine = Engine.__new__(Engine)
        engine.save_system = SimpleNamespace(read_quick_save=Mock(return_value=None))
        engine._continue_game = Mock()

        engine._quick_load()

        engine.save_system.read_quick_save.assert_called_once_with()
        engine._continue_game.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
