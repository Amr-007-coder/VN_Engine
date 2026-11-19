import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtTest, QtWidgets

from editor import VNEditorApp
from editor_qt import Tk, ensure_application


class EditorShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = ensure_application()

    def _create_app(self, project_root):
        data_dir = project_root / "data"
        data_dir.mkdir()
        story_file = data_dir / "story.yaml"
        story_file.write_text("title: Test\nstart: intro\n", encoding="utf-8")
        (data_dir / "project.json").write_text(
            json.dumps({"story": "story.yaml"}), encoding="utf-8"
        )
        window = Tk()
        with patch("editor._save_last_project"):
            app = VNEditorApp(window, project_root)
        window.show()
        window.update()
        return window, app, story_file

    def test_ctrl_s_saves_active_story(self):
        with tempfile.TemporaryDirectory() as temporary:
            window, app, story_file = self._create_app(Path(temporary))
            try:
                editor = app.story_editor
                editor.text.insert("end-1c", "\n# saved by shortcut")
                window.update()
                editor.text.setFocus()

                QtTest.QTest.keyClick(
                    editor.text, QtCore.Qt.Key.Key_S, QtCore.Qt.KeyboardModifier.ControlModifier
                )
                window.update()

                self.assertIn("# saved by shortcut", story_file.read_text(encoding="utf-8"))
                self.assertFalse(editor.dirty)

                editor.text.insert("end-1c", "\n# saved all by shortcut")
                window.update()
                QtTest.QTest.keyClick(
                    editor.text,
                    QtCore.Qt.Key.Key_S,
                    QtCore.Qt.KeyboardModifier.ControlModifier
                    | QtCore.Qt.KeyboardModifier.ShiftModifier,
                )
                window.update()

                self.assertIn("# saved all by shortcut", story_file.read_text(encoding="utf-8"))
                self.assertFalse(editor.dirty)
            finally:
                window.destroy()

    def test_ctrl_f_opens_sized_find_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            window, app, _story_file = self._create_app(Path(temporary))
            try:
                app.story_editor.text.setFocus()

                QtTest.QTest.keyClick(
                    app.story_editor.text,
                    QtCore.Qt.Key.Key_F,
                    QtCore.Qt.KeyboardModifier.ControlModifier,
                )
                window.update()

                self.assertIsNotNone(app.find_window)
                self.assertTrue(app.find_window.isVisible())
                self.assertGreaterEqual(app.find_window.width(), 500)
                self.assertGreaterEqual(app.find_window.height(), 110)
            finally:
                window.destroy()

    def test_find_next_advances_across_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            window, app, _story_file = self._create_app(Path(temporary))
            try:
                editor = app.story_editor
                editor.set_text("hit one\nhit two\nhit three\n")
                editor.text.mark_set("insert", "1.0")
                app.show_find()
                app.find_entry.insert(0, "hit")
                window.update()
                next_button = next(
                    button
                    for button in app.find_window.findChildren(QtWidgets.QPushButton)
                    if button.text() == "Next"
                )

                QtTest.QTest.mouseClick(next_button, QtCore.Qt.MouseButton.LeftButton)
                window.update()
                self.assertEqual(editor.text.index("insert"), "1.3")

                QtTest.QTest.mouseClick(next_button, QtCore.Qt.MouseButton.LeftButton)
                window.update()
                self.assertEqual(editor.text.index("insert"), "2.3")
            finally:
                window.destroy()


if __name__ == "__main__":
    unittest.main()
