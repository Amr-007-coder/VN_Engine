import unittest

from engine.playthrough import run_playthrough


class PlaythroughTests(unittest.TestCase):
    def test_choices_variables_endings_and_unlocks_are_asserted(self):
        story = {
            "start": "opening",
            "variables": {"trust": 0},
            "dialogues": {
                "opening": {
                    "speaker": "Narrator",
                    "text": "Choose",
                    "options": [{"label": "Take the road", "target": "ending"}],
                },
                "ending": {
                    "speaker": "Narrator",
                    "text": "Arrival",
                    "actions": [
                        {"type": "add", "var": "trust", "value": 1},
                        {"type": "achievement", "id": "first-route", "title": "First route"},
                        {"type": "complete_route", "id": "road"},
                    ],
                },
            },
        }
        result = run_playthrough(story, {
            "choices": [{"dialogue": "opening", "label": "Take the road"}],
            "expect": {
                "ending": "ending",
                "finished": True,
                "variables": {"trust": 1},
                "unlocks": {"achievements": ["first-route"], "routes": ["road"]},
            },
        })

        self.assertTrue(result["finished"])
        self.assertEqual(result["variables"]["trust"], 1)
        self.assertEqual(result["unlocks"]["routes"], ["road"])

    def test_integer_inputs_reject_fractional_values(self):
        story = {
            "start": "ask",
            "variables": {"age": 0},
            "dialogues": {
                "ask": {
                    "speaker": "Narrator",
                    "text": "Age?",
                    "actions": [{"type": "input", "var": "age", "prompt": "Enter age", "input_type": "integer"}],
                },
            },
        }

        with self.assertRaisesRegex(ValueError, "whole number"):
            run_playthrough(story, {"inputs": {"age": 4.5}})


if __name__ == "__main__":
    unittest.main()
