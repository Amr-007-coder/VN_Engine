import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtTest

from editor import CodeEditor
from editor_qt import Text, Tk, ensure_application


class EditorTextUndoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = ensure_application()

    def test_syntax_tags_do_not_interfere_with_text_undo(self):
        window = Tk()
        text = Text(window)
        text.pack()
        window.show()
        window.update()
        text.setFocus()
        text.insert("1.0", "unsaved change")
        text.tag_configure("string", foreground="#ff0000")
        text.tag_add("string", "1.0", "1.end")
        self.qt_app.processEvents()

        formats = text.document().firstBlock().layout().formats()
        self.assertEqual(formats[0].format.foreground().color().name(), "#ff0000")

        QtTest.QTest.keyClick(
            text, QtCore.Qt.Key.Key_Z, QtCore.Qt.KeyboardModifier.ControlModifier
        )
        self.qt_app.processEvents()
        self.assertEqual(text.get("1.0", "end-1c"), "")

        QtTest.QTest.keyClick(
            text, QtCore.Qt.Key.Key_Y, QtCore.Qt.KeyboardModifier.ControlModifier
        )
        self.qt_app.processEvents()
        self.assertEqual(text.get("1.0", "end-1c"), "unsaved change")
        window.destroy()

    def test_undo_stops_at_programmatically_loaded_text(self):
        window = Tk()
        editor = CodeEditor(window, Mock(), "story")
        editor.pack(fill="both", expand=True)
        window.show()
        window.update()
        editor.set_text("initial story")
        editor.text.setFocus()
        editor.text.insert("end-1c", " with an edit")
        self.qt_app.processEvents()

        for _ in range(3):
            QtTest.QTest.keyClick(
                editor.text, QtCore.Qt.Key.Key_Z, QtCore.Qt.KeyboardModifier.ControlModifier
            )
            self.qt_app.processEvents()

        self.assertEqual(editor.get_text(), "initial story")
        window.destroy()


if __name__ == "__main__":
    unittest.main()
