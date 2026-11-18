import unittest

from engine.localization import catalog_report, translation_template
from engine.story import StoryFlow


class LocalizationTests(unittest.TestCase):
    def setUp(self):
        self.story = {
            "start": "opening",
            "localization": {
                "default_locale": "en",
                "locales": {"en": "English", "de": "Deutsch"},
            },
            "dialogues": {
                "opening": {
                    "speaker": "Narrator",
                    "text": "Welcome",
                    "options": [{"label": "Continue", "target": "ending"}],
                    "actions": [{"type": "achievement", "id": "first", "title": "First steps"}],
                },
                "ending": {"speaker": "Narrator", "text": "The end"},
            },
        }

    def test_template_extracts_story_fields_and_ui_sources(self):
        template = translation_template(self.story, "de", {"menu.back": "Back"})

        self.assertEqual(template["source_locale"], "en")
        self.assertEqual(template["sources"]["dialogues.opening.text"], "Welcome")
        self.assertEqual(template["sources"]["dialogues.opening.options.0.label"], "Continue")
        self.assertEqual(template["sources"]["dialogues.opening.actions.0.title"], "First steps")
        self.assertEqual(template["ui_sources"]["menu.back"], "Back")
        self.assertEqual(template["strings"]["dialogues.opening.text"], "")

    def test_external_catalog_translates_story_fields_and_reports_missing_strings(self):
        catalog = {
            "de": {
                "strings": {
                    "dialogues.opening.text": "Willkommen",
                    "dialogues.opening.options.0.label": "Weiter",
                },
                "ui": {"menu.back": "Zurück"},
            }
        }
        flow = StoryFlow(self.story, locale="de", translation_tables=catalog)
        self.assertEqual(flow.current["text"], "Willkommen")
        self.assertEqual(flow.options[0]["label"], "Weiter")

        rows = catalog_report(self.story, "de", catalog["de"])
        self.assertFalse(next(row for row in rows if row["key"] == "dialogues.opening.text")["missing"])
        self.assertTrue(next(row for row in rows if row["key"] == "dialogues.ending.text")["missing"])


if __name__ == "__main__":
    unittest.main()
