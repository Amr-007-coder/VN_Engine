import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from editor import CodeEditor, VNEditorApp
from editor_qt import Notebook, QtWidgets, Text, ensure_application


class EditorTabResponsivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = ensure_application()

    def test_tab_labels_only_rebuild_the_tab_bar_when_changed(self):
        notebook = Notebook()
        first_page = QtWidgets.QWidget()
        second_page = QtWidgets.QWidget()
        notebook.add(first_page, text="Story")
        notebook.add(second_page, text="Include")
        rebuild = Mock()
        notebook._rebuild_tabs = rebuild

        notebook.tab(first_page, text="Story")
        rebuild.assert_not_called()

        notebook.tab(first_page, text="Story *")
        rebuild.assert_called_once_with()

        notebook.select(second_page)
        self.assertIn("#3b4d65", notebook._tab_widgets[second_page].styleSheet())
        self.assertIn("#252a33", notebook._tab_widgets[first_page].styleSheet())
        notebook.close()

    def test_line_info_does_not_repeat_the_last_document_line(self):
        text = Text(wrap="none")
        text.resize(500, 300)
        text.setPlainText("first\nsecond\n")
        text.show()
        self.qt_app.processEvents()

        self.assertIsNotNone(text.dlineinfo("3.0"))
        self.assertIsNone(text.dlineinfo("4.0"))

        text.close()

    def test_short_document_gutter_starts_at_the_text_viewport_top(self):
        window = QtWidgets.QMainWindow()
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        app_stub = type(
            "EditorAppStub",
            (),
            {
                "document_changed": lambda *_args: None,
                "schedule_analysis": lambda *_args: None,
                "schedule_completion": lambda *_args: None,
                "update_cursor_status": lambda *_args: None,
            },
        )()
        editor = CodeEditor(container, app_stub, "story")
        layout.addWidget(editor)
        window.setCentralWidget(container)
        window.resize(900, 600)
        window.show()
        editor.set_text("title: Example\nstart: opening\n")
        self.qt_app.processEvents()

        first_line_y = editor.text.dlineinfo("1.0")[1]
        gutter_line_y = editor.gutter.mapFromScene(0, first_line_y).y()
        self.assertEqual(gutter_line_y, first_line_y)

        window.close()

    def test_tab_change_defers_document_analysis(self):
        app = object.__new__(VNEditorApp)
        app.engine_diagnostics = []
        app._tab_change_analysis_job = None
        app._analysis_jobs = {}
        app._analysis_revisions = {"story": 0, "project": 0}
        app._document_analysis_cache = {"story": {}, "project": {}}
        app.root = Mock()
        app.root.after.return_value = "deferred-analysis"
        app.active_kind = Mock(return_value="story")
        app.active_editor = Mock(return_value=object())
        app.update_cursor_status = Mock()
        app.analyze_document = Mock()
        app._update_tab_labels = Mock()
        app._refresh_search_highlights = Mock()

        app._on_tab_changed()

        app.analyze_document.assert_not_called()
        app.root.after.assert_called_once_with(150, app._analyze_active_tab_after_change)
        self.assertEqual(app._tab_change_analysis_job, "deferred-analysis")
        app.update_cursor_status.assert_called_once_with()

        app._analyze_active_tab_after_change()
        app.analyze_document.assert_called_once_with("story")

    def test_tab_change_reuses_current_revision_diagnostics(self):
        app = object.__new__(VNEditorApp)
        editor = object()
        diagnostic = object()
        app._tab_change_analysis_job = "completed-analysis"
        app._analysis_revisions = {"story": 3, "project": 0}
        app._document_analysis_cache = {
            "story": {id(editor): (3, [diagnostic])},
            "project": {},
        }
        app.live_diagnostics = {"story": [], "project": []}
        app.active_kind = Mock(return_value="story")
        app.active_editor = Mock(return_value=editor)
        app.analyze_document = Mock()
        app.render_diagnostics = Mock()
        app.update_cursor_status = Mock()

        app._analyze_active_tab_after_change()

        app.analyze_document.assert_not_called()
        self.assertEqual(app.live_diagnostics["story"], [diagnostic])
        app.render_diagnostics.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
