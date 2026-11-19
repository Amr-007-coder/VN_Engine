"""PySide6 widgets used by the existing VN editor workflows.

The editor has a large amount of project and story logic that is independent of
its window toolkit.  This module provides a small Tk-shaped API over Qt Widgets
so those workflows can move to PySide6 without changing the story model.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from types import SimpleNamespace

from PySide6 import QtCore, QtGui, QtWidgets


TclError = RuntimeError
END = "end"


def ensure_application():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
        app.setStyle("Fusion")
        app.setStyleSheet(
            "QWidget { background: #20242d; color: #d8dee9; }"
            "QMenuBar, QMenu { background: #252a33; color: #d8dee9; }"
            "QMenu::item:selected { background: #3b4d65; }"
            "QPushButton, QToolButton { background: #303744; border: 1px solid #465160;"
            " border-radius: 4px; padding: 5px 9px; }"
            "QPushButton:hover, QToolButton:hover { background: #3c4a5c; }"
            "QLineEdit, QComboBox, QPlainTextEdit, QTextEdit, QTreeWidget {"
            " background: #171a21; border: 1px solid #3a414d; selection-background-color: #3b4d65; }"
            "QHeaderView::section { background: #303744; padding: 4px; border: 0; }"
            "QTabBar::tab { background: #252a33; padding: 6px 10px; }"
            "QTabBar::tab:selected { background: #3b4d65; }"
            "QToolTip { background: #303744; color: #ffffff; border: 1px solid #657080; }"
        )
    return app


class _BackgroundTask(QtCore.QRunnable):
    def __init__(self, dispatcher, callback, function):
        super().__init__()
        self.dispatcher = dispatcher
        self.callback = callback
        self.function = function

    def run(self):
        try:
            result = self.function()
        except Exception as error:
            self.dispatcher.completed.emit(self.callback, None, error)
        else:
            self.dispatcher.completed.emit(self.callback, result, None)


class _BackgroundTaskDispatcher(QtCore.QObject):
    completed = QtCore.Signal(object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QtCore.QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.completed.connect(self._deliver, QtCore.Qt.ConnectionType.QueuedConnection)

    @QtCore.Slot(object, object, object)
    def _deliver(self, callback, result, error):
        callback(result, error)

    def submit(self, function, callback):
        task = _BackgroundTask(self, callback, function)
        self.pool.start(task)


def _qt_font(value):
    if isinstance(value, QtGui.QFont):
        return value
    if isinstance(value, (tuple, list)) and value:
        font = QtGui.QFont(str(value[0]))
        if len(value) > 1 and isinstance(value[1], (int, float)):
            font.setPointSizeF(float(value[1]))
        if len(value) > 2:
            styles = " ".join(str(item).casefold() for item in value[2:])
            font.setBold("bold" in styles)
            font.setItalic("italic" in styles)
        return font
    return QtGui.QFont(str(value))


def _qt_color(value):
    return QtGui.QColor(str(value))


def _event_key_name(key):
    names = {
        QtCore.Qt.Key.Key_Up: "Up", QtCore.Qt.Key.Key_Down: "Down",
        QtCore.Qt.Key.Key_Left: "Left", QtCore.Qt.Key.Key_Right: "Right",
        QtCore.Qt.Key.Key_Return: "Return", QtCore.Qt.Key.Key_Enter: "Return",
        QtCore.Qt.Key.Key_Escape: "Escape", QtCore.Qt.Key.Key_Tab: "Tab",
        QtCore.Qt.Key.Key_Backtab: "Tab", QtCore.Qt.Key.Key_Space: "space",
        QtCore.Qt.Key.Key_Shift: "Shift_L", QtCore.Qt.Key.Key_Control: "Control_L",
        QtCore.Qt.Key.Key_Alt: "Alt_L", QtCore.Qt.Key.Key_Home: "Home",
        QtCore.Qt.Key.Key_End: "End", QtCore.Qt.Key.Key_Delete: "Delete",
        QtCore.Qt.Key.Key_Backspace: "BackSpace",
    }
    return names.get(key, QtGui.QKeySequence(key).toString() or "")


def _event_sequence_parts(sequence):
    value = sequence.strip("<>")
    if value.startswith("<<"):
        return None
    parts = value.split("-")
    key = parts[-1]
    modifiers = {part.casefold() for part in parts[:-1]}
    return key, modifiers


def _sequence_matches(sequence, event):
    parts = _event_sequence_parts(sequence)
    if parts is None:
        return False
    key_name, required = parts
    if isinstance(event, QtGui.QKeyEvent):
        actual = _event_key_name(event.key())
        actual_casefold = actual.casefold()
        expected = key_name.casefold()
        if expected == "control-space":
            expected = "space"
            required.add("control")
        if expected in {"slash", "control/slash"}:
            expected = "/"
        if actual_casefold != expected and event.text().casefold() != expected:
            return False
        mods = event.modifiers()
        if bool(mods & QtCore.Qt.KeyboardModifier.ControlModifier) != ("control" in required):
            return False
        if bool(mods & QtCore.Qt.KeyboardModifier.ShiftModifier) != ("shift" in required):
            return False
        if bool(mods & QtCore.Qt.KeyboardModifier.AltModifier) != ("alt" in required):
            return False
        return True
    if isinstance(event, QtGui.QMouseEvent):
        if "Double" in sequence:
            event_type = QtCore.QEvent.Type.MouseButtonDblClick
        else:
            event_type = QtCore.QEvent.Type.MouseButtonRelease
        match = re.search(r"-(\d+)>$", sequence)
        button_number = int(match.group(1)) if match else 1
        expected_button = {
            1: QtCore.Qt.MouseButton.LeftButton,
            2: QtCore.Qt.MouseButton.MiddleButton,
            3: QtCore.Qt.MouseButton.RightButton,
        }.get(button_number)
        return event.type() == event_type and (expected_button is None or event.button() == expected_button)
    return False


class _EventProxy(QtCore.QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.widget = widget

    def eventFilter(self, watched, event):
        widget = self.widget
        event_type = event.type()
        for sequence, callback in list(getattr(widget, "_bindings", [])):
            if sequence == "<Configure>" and event_type == QtCore.QEvent.Type.Resize:
                result = callback(SimpleNamespace(widget=widget))
            elif sequence.startswith("<KeyPress-") and event_type == QtCore.QEvent.Type.KeyPress and _sequence_matches(sequence, event):
                result = callback(_make_key_event(widget, event))
            elif sequence in {"<KeyPress>", "<Key>"} and event_type == QtCore.QEvent.Type.KeyPress:
                result = callback(_make_key_event(widget, event))
            elif event_type == QtCore.QEvent.Type.KeyPress and sequence.startswith("<") and _sequence_matches(sequence, event):
                result = callback(_make_key_event(widget, event))
            elif sequence in {"<KeyRelease>", "<KeyRelease-Any>"} and event_type == QtCore.QEvent.Type.KeyRelease:
                result = callback(_make_key_event(widget, event))
            elif sequence.startswith("<KeyRelease-") and event_type == QtCore.QEvent.Type.KeyRelease and _sequence_matches(sequence, event):
                result = callback(_make_key_event(widget, event))
            elif sequence.startswith("<ButtonRelease-") and event_type == QtCore.QEvent.Type.MouseButtonRelease and _sequence_matches(sequence, event):
                result = callback(_make_mouse_event(widget, event))
            elif sequence.startswith("<Double-") and event_type == QtCore.QEvent.Type.MouseButtonDblClick and _sequence_matches(sequence, event):
                result = callback(_make_mouse_event(widget, event))
            elif sequence in {"<MouseWheel>", "<Button-4>", "<Button-5>"} and event_type == QtCore.QEvent.Type.Wheel:
                result = callback(_make_mouse_event(widget, event))
            else:
                continue
            if result == "break":
                event.accept()
                return True
        return False


def _make_key_event(widget, event):
    return SimpleNamespace(
        widget=widget,
        keysym=_event_key_name(event.key()),
        key=event.key(),
        state=int(event.modifiers().value),
        char=event.text(),
    )


def _make_mouse_event(widget, event):
    point = event.position().toPoint() if hasattr(event, "position") else QtCore.QPoint()
    delta = event.angleDelta().y() if isinstance(event, QtGui.QWheelEvent) else 0
    return SimpleNamespace(widget=widget, x=point.x(), y=point.y(), delta=delta, num=1)


class _WidgetMixin:
    def _init_tk(self, tk_parent=None):
        self._tk_parent = tk_parent
        self._bindings = []
        self._shortcuts = []
        self._tk_timers = {}
        self._tk_timer_id = 0
        self._last_grid_options = None
        self._event_proxy = _EventProxy(self)
        self.installEventFilter(self._event_proxy)
        if isinstance(self, QtWidgets.QAbstractScrollArea):
            self.viewport().installEventFilter(self._event_proxy)

    def bind(self, sequence, callback, add=None):
        if sequence.startswith("<<"):
            self._bind_virtual(sequence, callback)
            return
        if sequence.startswith("<Control-") or sequence.startswith("<Alt-") or re.fullmatch(r"<F\d+>", sequence):
            key = sequence.strip("<>").replace("Control-", "Ctrl+").replace("Alt-", "Alt+").replace("Shift-", "Shift+")
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), self)
            shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda cb=callback: cb(SimpleNamespace(widget=self, keysym="", state=0, char="")))
            self._shortcuts.append(shortcut)
            return
        if add:
            self._bindings.append((sequence, callback))
        else:
            self._bindings = [(sequence, callback)]

    def _bind_virtual(self, sequence, callback):
        signal_name = sequence.strip("<>")
        signal = {
            "<NotebookTabChanged>": getattr(self, "currentChanged", None),
            "<<Modified>>": getattr(self, "textChanged", None),
            "<<TreeviewOpen>>": getattr(self, "itemExpanded", None),
            "<ComboboxSelected>": getattr(self, "activated", None),
        }.get(sequence)
        if signal is not None:
            if sequence == "<<TreeviewOpen>>":
                def on_treeview_open(item):
                    self.setCurrentItem(item)
                    callback(SimpleNamespace(widget=self))

                signal.connect(on_treeview_open)
            elif sequence == "<<NotebookTabChanged>>":
                signal.connect(lambda _index: callback(SimpleNamespace(widget=self)))
            else:
                signal.connect(lambda *_args: callback(SimpleNamespace(widget=self)))

    def pack(self, **options):
        parent = self._tk_parent if self._tk_parent is not None else self.parentWidget()
        if isinstance(parent, Tk):
            parent = parent.centralWidget()
        if parent is None:
            return self
        layout = parent.layout()
        if layout is None:
            direction = QtWidgets.QBoxLayout.Direction.LeftToRight if options.get("side") in {"left", "right"} else QtWidgets.QBoxLayout.Direction.TopToBottom
            layout = QtWidgets.QBoxLayout(direction)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(5)
            parent.setLayout(layout)
        if not isinstance(layout, QtWidgets.QBoxLayout):
            # Tk UI groups do not mix pack and grid within one parent. Keep a
            # predictable fallback if a later plugin does so.
            holder = QtWidgets.QWidget(parent)
            holder_layout = QtWidgets.QVBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.addWidget(self)
            layout.addWidget(holder)
            return self
        side = options.get("side", "top")
        if side in {"left", "right"} and layout.direction() != QtWidgets.QBoxLayout.Direction.LeftToRight:
            layout.setDirection(QtWidgets.QBoxLayout.Direction.LeftToRight)
        elif side in {"top", "bottom"} and layout.direction() != QtWidgets.QBoxLayout.Direction.TopToBottom:
            layout.setDirection(QtWidgets.QBoxLayout.Direction.TopToBottom)
        if options.get("fill") == "both" or options.get("expand"):
            self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        elif options.get("fill") == "x":
            self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        elif options.get("fill") == "y":
            self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Expanding)
        stretch = 1 if options.get("expand") else 0
        if side == "right":
            right_start = getattr(parent, "_qt_right_pack_start", layout.count())
            layout.insertWidget(right_start, self, stretch)
            parent._qt_right_pack_start = right_start
        else:
            layout.addWidget(self, stretch)
        return self

    def grid(self, **options):
        parent = self._tk_parent if self._tk_parent is not None else self.parentWidget()
        if isinstance(parent, Tk):
            parent = parent.centralWidget()
        if parent is None:
            return self
        layout = parent.layout()
        if layout is None:
            layout = QtWidgets.QGridLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setHorizontalSpacing(5)
            layout.setVerticalSpacing(5)
            parent.setLayout(layout)
        if not isinstance(layout, QtWidgets.QGridLayout):
            layout.addWidget(self)
            return self
        row, column = int(options.get("row", 0)), int(options.get("column", 0))
        layout.removeWidget(self)
        self._last_grid_options = dict(options)
        sticky = options.get("sticky", "")
        alignment = QtCore.Qt.AlignmentFlag(0)
        if "w" in sticky:
            alignment |= QtCore.Qt.AlignmentFlag.AlignLeft
        if "e" in sticky:
            alignment |= QtCore.Qt.AlignmentFlag.AlignRight
        if "n" in sticky:
            alignment |= QtCore.Qt.AlignmentFlag.AlignTop
        if "s" in sticky:
            alignment |= QtCore.Qt.AlignmentFlag.AlignBottom
        layout.addWidget(
            self,
            row,
            column,
            max(1, int(options.get("rowspan", 1))),
            max(1, int(options.get("columnspan", 1))),
            alignment,
        )
        if any(letter in sticky for letter in "we"):
            layout.setColumnStretch(column, 1)
            self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        if any(letter in sticky for letter in "ns"):
            layout.setRowStretch(row, 1)
        return self

    def grid_remove(self):
        self.hide()

    def pack_forget(self):
        self.hide()

    def after(self, milliseconds, callback):
        self._tk_timer_id += 1
        identifier = str(self._tk_timer_id)
        timer = QtCore.QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.timeout.connect(lambda key=identifier: self._tk_timers.pop(key, None))
        self._tk_timers[identifier] = timer
        timer.start(max(0, int(milliseconds)))
        return identifier

    def after_cancel(self, identifier):
        timer = self._tk_timers.pop(str(identifier), None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def columnconfigure(self, column, weight=0):
        layout = self.layout()
        if isinstance(layout, QtWidgets.QGridLayout):
            layout.setColumnStretch(int(column), int(weight))

    def rowconfigure(self, row, weight=0):
        layout = self.layout()
        if isinstance(layout, QtWidgets.QGridLayout):
            layout.setRowStretch(int(row), int(weight))

    def destroy(self):
        self._tk_destroyed = True
        self.close()
        self.deleteLater()

    def winfo_exists(self):
        return not getattr(self, "_tk_destroyed", False)

    def winfo_height(self):
        return self.height()

    def winfo_width(self):
        return self.width()

    def winfo_rootx(self):
        return self.mapToGlobal(QtCore.QPoint(0, 0)).x()

    def winfo_rooty(self):
        return self.mapToGlobal(QtCore.QPoint(0, 0)).y()

    def focus_set(self):
        self.setFocus()


class Tk(QtWidgets.QMainWindow, _WidgetMixin):
    def __init__(self):
        ensure_application()
        super().__init__()
        self._init_tk()
        content = QtWidgets.QWidget(self)
        self.setCentralWidget(content)
        self._timers = {}
        self._timer_id = 0
        self._protocol_callback = None
        self._background_tasks = _BackgroundTaskDispatcher(self)
        self.setMinimumSize(940, 620)

    def title(self, value=None):
        if value is not None:
            self.setWindowTitle(str(value))
        return self.windowTitle()

    def geometry(self, value=None):
        if value:
            match = re.match(r"(\d+)x(\d+)(?:([+-]\d+)([+-]\d+))?", value)
            if match:
                self.resize(int(match.group(1)), int(match.group(2)))
                if match.group(3) is not None:
                    self.move(int(match.group(3)), int(match.group(4)))
        return f"{self.width()}x{self.height()}"

    def minsize(self, width=None, height=None):
        if width is not None and height is not None:
            self.setMinimumSize(int(width), int(height))

    def configure(self, **options):
        menu = options.get("menu")
        if menu is not None:
            if isinstance(menu, QtWidgets.QMenuBar):
                self.setMenuBar(menu)
            elif isinstance(menu, QtWidgets.QMenu):
                menu_bar = QtWidgets.QMenuBar(self)
                for action in menu.actions():
                    menu_bar.addAction(action)
                self.setMenuBar(menu_bar)

    config = configure

    def destroy(self):
        self._tk_destroyed = True
        self._protocol_callback = None
        self.close()
        self.deleteLater()

    def withdraw(self):
        self.hide()

    def protocol(self, _name, callback):
        self._protocol_callback = callback

    def closeEvent(self, event):
        if self._protocol_callback is not None:
            self._protocol_callback()
            event.accept() if getattr(self, "_tk_destroyed", False) else event.ignore()
        else:
            event.accept()

    def bind(self, sequence, callback, add=None):
        is_shortcut = (
            sequence.startswith("<Control-")
            or sequence.startswith("<Alt-")
            or re.fullmatch(r"<F\d+>", sequence)
            or isinstance(self, (Tk, Toplevel)) and sequence in {"<Return>", "<Escape>"}
        )
        if is_shortcut:
            key = sequence.strip("<>").replace("Control-", "Ctrl+").replace("Alt-", "Alt+").replace("Shift-", "Shift+")
            key = key.replace("space", "Space").replace("slash", "/")
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), self)
            shortcut.setContext(QtCore.Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda cb=callback: cb(SimpleNamespace(widget=self, keysym="", state=0, char="")))
            self._shortcuts.append(shortcut)
        else:
            super().bind(sequence, callback, add)

    def after(self, milliseconds, callback):
        self._timer_id += 1
        identifier = str(self._timer_id)
        timer = QtCore.QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.timeout.connect(lambda key=identifier: self._timers.pop(key, None))
        self._timers[identifier] = timer
        timer.start(max(0, int(milliseconds)))
        return identifier

    def after_cancel(self, identifier):
        timer = self._timers.pop(str(identifier), None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def update(self):
        ensure_application().processEvents()

    update_idletasks = update

    def run_in_background(self, function, callback):
        self._background_tasks.submit(function, callback)

    def mainloop(self):
        if not self.isVisible():
            self.show()
        return ensure_application().exec()

    def clipboard_clear(self):
        ensure_application().clipboard().clear()

    def clipboard_append(self, text):
        ensure_application().clipboard().setText(str(text))

    def clipboard_get(self):
        return ensure_application().clipboard().text()


class Toplevel(QtWidgets.QDialog, _WidgetMixin):
    def __init__(self, parent=None):
        ensure_application()
        native_parent = parent if isinstance(parent, QtWidgets.QWidget) else None
        super().__init__(native_parent)
        self._init_tk(parent)
        self._protocol_callback = None
        self._timer_id = 0
        self._timers = {}
        QtCore.QTimer.singleShot(0, self.show)

    def title(self, value=None):
        if value is not None:
            self.setWindowTitle(str(value))
        return self.windowTitle()

    def geometry(self, value=None):
        if value:
            size_match = re.match(r"^(\d+)x(\d+)", value)
            if size_match:
                self.resize(int(size_match.group(1)), int(size_match.group(2)))
            position_match = re.search(r"([+-]\d+)([+-]\d+)$", value)
            if position_match:
                self.move(int(position_match.group(1)), int(position_match.group(2)))

    def minsize(self, width, height):
        self.setMinimumSize(int(width), int(height))

    def resizable(self, width=True, height=True):
        self.setMinimumWidth(0 if width else self.width())
        self.setMaximumWidth(16777215 if width else self.width())
        self.setMinimumHeight(0 if height else self.height())
        self.setMaximumHeight(16777215 if height else self.height())

    def transient(self, parent=None):
        if parent is not None and isinstance(parent, QtWidgets.QWidget):
            self.setParent(parent, self.windowFlags())

    def grab_set(self):
        self.setModal(True)
        self.show()

    def wait_visibility(self):
        self.show()
        ensure_application().processEvents()

    def withdraw(self):
        self.hide()

    def deiconify(self):
        self.showNormal()

    def lift(self):
        self.raise_()

    def overrideredirect(self, enabled):
        if enabled:
            self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.FramelessWindowHint)

    def configure(self, **options):
        color = options.get("background")
        if color:
            self.setStyleSheet(f"background: {color};")

    config = configure

    def destroy(self):
        self._tk_destroyed = True
        self._protocol_callback = None
        self.close()
        self.deleteLater()

    def protocol(self, _name, callback):
        self._protocol_callback = callback

    def closeEvent(self, event):
        if self._protocol_callback is not None:
            self._protocol_callback()
            event.accept() if getattr(self, "_tk_destroyed", False) else event.ignore()
        else:
            event.accept()

    def columnconfigure(self, column, weight=0):
        layout = self.layout()
        if isinstance(layout, QtWidgets.QGridLayout):
            layout.setColumnStretch(int(column), int(weight))

    def rowconfigure(self, row, weight=0):
        layout = self.layout()
        if isinstance(layout, QtWidgets.QGridLayout):
            layout.setRowStretch(int(row), int(weight))

    def after(self, milliseconds, callback):
        self._timer_id += 1
        identifier = str(self._timer_id)
        timer = QtCore.QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.timeout.connect(lambda key=identifier: self._timers.pop(key, None))
        self._timers[identifier] = timer
        timer.start(max(0, int(milliseconds)))
        return identifier

    def after_cancel(self, identifier):
        timer = self._timers.pop(str(identifier), None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()


class Frame(QtWidgets.QFrame, _WidgetMixin):
    def __init__(self, parent=None, **options):
        ensure_application()
        native_parent = parent.centralWidget() if isinstance(parent, Tk) else parent
        super().__init__(native_parent)
        self._init_tk(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        if options.get("width"):
            self.setMinimumWidth(int(options["width"]))


class LabelFrame(QtWidgets.QGroupBox, _WidgetMixin):
    def __init__(self, parent=None, text="", padding=None, **options):
        ensure_application()
        super().__init__(str(text), parent)
        self._init_tk(parent)


class Label(QtWidgets.QLabel, _WidgetMixin):
    def __init__(self, parent=None, text="", **options):
        ensure_application()
        super().__init__(str(text), parent)
        self._init_tk(parent)
        self.configure(**options)

    def configure(self, **options):
        if "text" in options:
            self.setText(str(options["text"]))
        if "foreground" in options:
            self.setStyleSheet(f"color: {options['foreground']};")
        if "background" in options:
            self.setStyleSheet(f"background: {options['background']};")
        if "font" in options:
            self.setFont(_qt_font(options["font"]))
        if "anchor" in options:
            self.setAlignment({"w": QtCore.Qt.AlignmentFlag.AlignLeft, "e": QtCore.Qt.AlignmentFlag.AlignRight, "center": QtCore.Qt.AlignmentFlag.AlignCenter}.get(options["anchor"], QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter))
        if "padding" in options:
            padding = options["padding"]
            if isinstance(padding, (tuple, list)):
                self.setContentsMargins(*(list(padding) + [0] * (4 - len(padding))))
            elif isinstance(padding, int):
                self.setContentsMargins(padding, padding, padding, padding)

    config = configure


class Button(QtWidgets.QPushButton, _WidgetMixin):
    def __init__(self, parent=None, text="", command=None, **options):
        ensure_application()
        super().__init__(str(text), parent)
        self._init_tk(parent)
        self._command = command
        self.clicked.connect(lambda _checked=False: self._command() if self._command else None)
        self.configure(**options)

    def configure(self, **options):
        if "text" in options:
            self.setText(str(options["text"]))
        if "state" in options:
            self.setEnabled(options["state"] != "disabled")
        if "width" in options:
            self.setMinimumWidth(max(1, int(options["width"]) * 8))
        if "command" in options:
            self._command = options["command"]

    config = configure


class Entry(QtWidgets.QLineEdit, _WidgetMixin):
    def __init__(self, parent=None, width=None, textvariable=None, **options):
        ensure_application()
        super().__init__(parent)
        self._init_tk(parent)
        self._variable = textvariable
        if width:
            self.setMinimumWidth(int(width) * 8)
        if textvariable is not None:
            self.setText(str(textvariable.get()))
            self.textChanged.connect(textvariable.set)
            textvariable.trace_add("write", lambda *_args: self.setText(str(textvariable.get())))
        self.configure(**options)

    def configure(self, **options):
        if "state" in options:
            self.setReadOnly(options["state"] == "disabled")
        if "width" in options:
            self.setMinimumWidth(int(options["width"]) * 8)
        if "textvariable" in options:
            self._variable = options["textvariable"]

    config = configure

    def get(self):
        return self.text()

    def insert(self, index, value):
        position = self.cursorPosition() if index == "insert" else (0 if index == 0 else len(self.text()))
        self.setCursorPosition(position)
        super().insert(str(value))

    def delete(self, first, last=None):
        start = 0 if first == 0 or first == "0" else self.cursorPosition() if first == "insert" else len(self.text())
        end = len(self.text()) if last in {None, END} else int(last) if isinstance(last, int) else start + 1
        self.setSelection(start, max(0, end - start))
        super().insert("")

    def index(self, value):
        return self.cursorPosition() if value == "insert" else len(self.text())

    def search(self, *_args, **_kwargs):
        return ""

    def select_range(self, start, end):
        start = int(start)
        end = len(self.text()) if end == END else int(end)
        self.setSelection(start, end - start)


class Checkbutton(QtWidgets.QCheckBox, _WidgetMixin):
    def __init__(self, parent=None, text="", variable=None, command=None, **options):
        ensure_application()
        super().__init__(str(text), parent)
        self._init_tk(parent)
        self._variable = variable
        if variable is not None:
            self.setChecked(bool(variable.get()))
            self.toggled.connect(variable.set)
            variable.trace_add("write", lambda *_args: self.setChecked(bool(variable.get())))
        if command:
            self.toggled.connect(lambda _value: command())

    def configure(self, **options):
        if "state" in options:
            self.setEnabled(options["state"] != "disabled")
        if "text" in options:
            self.setText(str(options["text"]))

    config = configure


class ComboBox(QtWidgets.QComboBox, _WidgetMixin):
    def __init__(self, parent=None, values=(), state=None, textvariable=None, **options):
        ensure_application()
        super().__init__(parent)
        self._init_tk(parent)
        self._variable = textvariable
        self.addItems([str(value) for value in values])
        if state == "readonly":
            self.setEditable(False)
        if textvariable is not None:
            current = str(textvariable.get())
            index = self.findText(current)
            if index >= 0:
                self.setCurrentIndex(index)
            elif current:
                self.setEditText(current)
            self.currentTextChanged.connect(textvariable.set)
            textvariable.trace_add("write", lambda *_args: self._set_from_variable())
        self.configure(**options)

    def _set_from_variable(self):
        value = str(self._variable.get())
        index = self.findText(value)
        if index >= 0:
            self.setCurrentIndex(index)
        elif self.isEditable():
            self.setEditText(value)

    def configure(self, **options):
        if "values" in options:
            self.clear()
            self.addItems([str(value) for value in options["values"]])
        if "state" in options:
            self.setEditable(options["state"] != "readonly")
        if "textvariable" in options:
            self._variable = options["textvariable"]

    config = configure

    def get(self):
        return self.currentText()

    def set(self, value):
        index = self.findText(str(value))
        if index >= 0:
            self.setCurrentIndex(index)
        elif self.isEditable():
            self.setEditText(str(value))


class Scrollbar(QtWidgets.QScrollBar, _WidgetMixin):
    def __init__(self, parent=None, orient="vertical", command=None, **options):
        ensure_application()
        orientation = QtCore.Qt.Orientation.Horizontal if orient == "horizontal" else QtCore.Qt.Orientation.Vertical
        super().__init__(orientation, parent)
        self._init_tk(parent)
        self._command = command
        self.valueChanged.connect(self._emit_command)
        self.configure(**options)

    def _emit_command(self, value):
        if self._command is not None:
            maximum = max(1, self.maximum() - self.minimum())
            self._command("moveto", float(value - self.minimum()) / maximum)

    def configure(self, **options):
        if "command" in options:
            self._command = options["command"]

    config = configure

    def set(self, first, last=None):
        try:
            fraction = float(first)
        except (TypeError, ValueError):
            return
        self.blockSignals(True)
        self.setRange(0, 1000)
        self.setPageStep(max(1, round((float(last or first) - fraction) * 1000)))
        self.setValue(round(fraction * max(0, self.maximum())))
        self.blockSignals(False)


class Panedwindow(QtWidgets.QSplitter, _WidgetMixin):
    def __init__(self, parent=None, orient="horizontal", **options):
        ensure_application()
        orientation = QtCore.Qt.Orientation.Horizontal if orient == "horizontal" else QtCore.Qt.Orientation.Vertical
        super().__init__(orientation, parent)
        self._init_tk(parent)

    def add(self, widget, weight=1):
        self.addWidget(widget)
        self.setStretchFactor(self.count() - 1, int(weight))


class Variable:
    def __init__(self, master=None, value=None):
        self._value = value
        self._callbacks = []

    def get(self):
        return self._value

    def set(self, value):
        if self._value == value:
            return
        self._value = value
        for callback in list(self._callbacks):
            callback("", "", "write")

    def trace_add(self, _mode, callback):
        self._callbacks.append(callback)


class StringVar(Variable):
    def __init__(self, master=None, value=""):
        super().__init__(master, str(value))

    def set(self, value):
        super().set(str(value))


class BooleanVar(Variable):
    def __init__(self, master=None, value=False):
        super().__init__(master, bool(value))

    def set(self, value):
        super().set(bool(value))


class IntVar(Variable):
    def __init__(self, master=None, value=0):
        super().__init__(master, int(value))

    def set(self, value):
        super().set(int(value))


class Style:
    def __init__(self, *_args, **_kwargs):
        ensure_application()

    def theme_use(self, *_args):
        return "fusion"

    def configure(self, *_args, **_kwargs):
        return None


class Menu(QtWidgets.QMenu, _WidgetMixin):
    def __init__(self, parent=None, tearoff=False, **options):
        ensure_application()
        super().__init__(parent if isinstance(parent, QtWidgets.QWidget) else None)
        self._init_tk(parent)

    def add_command(self, label="", command=None, accelerator=None, state=None, **_options):
        action = self.addAction(str(label))
        if accelerator:
            action.setShortcut(QtGui.QKeySequence(str(accelerator)))
        if state == "disabled":
            action.setEnabled(False)
        if command:
            action.triggered.connect(lambda _checked=False: command())
        return action

    def add_cascade(self, label="", menu=None, **_options):
        if menu is None:
            menu = Menu(self)
        self.addMenu(menu)
        menu.setTitle(str(label))
        return menu

    def add_separator(self):
        return self.addSeparator()

    def grab_release(self):
        return None

    def tk_popup(self, x, y):
        self.popup(QtCore.QPoint(int(x), int(y)))


class Listbox(QtWidgets.QListWidget, _WidgetMixin):
    def __init__(self, parent=None, height=8, width=40, **options):
        ensure_application()
        super().__init__(parent)
        self._init_tk(parent)
        self.setFixedHeight(max(1, int(height)) * 22)
        self.setMinimumWidth(max(1, int(width)) * 8)
        if "background" in options or "foreground" in options:
            self.setStyleSheet(f"background: {options.get('background', '#171a21')}; color: {options.get('foreground', '#d8dee9')};")

    def insert(self, index, value):
        if index in {"end", END}:
            self.addItem(str(value))
        else:
            self.insertItem(int(index), str(value))

    def selection_set(self, index):
        self.setCurrentRow(int(index))

    def selection_clear(self, _first=0, _last=END):
        self.clearSelection()

    def curselection(self):
        return tuple(self.row(item) for item in self.selectedItems())

    def see(self, index):
        item = self.item(int(index))
        if item is not None:
            self.scrollToItem(item)


class _CompactLeafDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, tree, values_role):
        super().__init__(tree)
        self._values_role = values_role
        self._left_adjustment = tree.indentation() + 3

    def paint(self, painter, option, index):
        values = index.data(self._values_role) or ()
        if values and values[0] in {"file", "builtin-file"}:
            option = QtWidgets.QStyleOptionViewItem(option)
            option.rect.adjust(-self._left_adjustment, 0, 0, 0)
        super().paint(painter, option, index)


class Treeview(QtWidgets.QTreeWidget, _WidgetMixin):
    _values_role = QtCore.Qt.ItemDataRole.UserRole + 1

    def __init__(
        self, parent=None, columns=(), show="tree headings", selectmode="browse",
        height=10, compact_files=False, **options,
    ):
        ensure_application()
        super().__init__(parent)
        self._init_tk(parent)
        self._tree_columns = tuple(columns)
        self._show_tree = "tree" in show
        self._value_offset = 1 if self._show_tree else 0
        self._tree_iid_counter = 0
        self.setColumnCount(self._value_offset + len(self._tree_columns))
        self.setHeaderLabels(([""] if self._show_tree else []) + list(self._tree_columns))
        self.setHeaderHidden("headings" not in show)
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
            if selectmode == "browse"
            else QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.setUniformRowHeights(True)
        self.setMinimumHeight(int(height) * 22)
        self._tree_tags = {}
        self._tree_iids = {}
        if compact_files:
            self.setItemDelegate(_CompactLeafDelegate(self, self._values_role))

    def configure(self, **options):
        if "yscrollcommand" in options and options["yscrollcommand"] is not None:
            def send_yview(value):
                bar = self.verticalScrollBar()
                span = max(1, bar.maximum() + bar.pageStep())
                options["yscrollcommand"](value / span, min(1.0, (value + bar.pageStep()) / span))
            self.verticalScrollBar().valueChanged.connect(send_yview)
        if "show" in options:
            self.setHeaderHidden("headings" not in options["show"])
        if "columns" in options:
            self._tree_columns = tuple(options["columns"])
            self.setColumnCount(self._value_offset + len(self._tree_columns))
            self.setHeaderLabels(([""] if self._show_tree else []) + list(self._tree_columns))

    config = configure

    def insert(self, parent, index, iid=None, text="", values=(), tags=(), **_options):
        parent_item = self._tree_iids.get(str(parent)) if parent else None
        owner = parent_item or self.invisibleRootItem()
        item = QtWidgets.QTreeWidgetItem()
        if index in {"end", END}:
            owner.addChild(item)
        else:
            owner.insertChild(int(index), item)
        if self._show_tree:
            item.setText(0, str(text))
        values = tuple(str(value) for value in values)
        item.setData(0, self._values_role, values)
        for column, value in enumerate(values, start=self._value_offset):
            if column < self.columnCount():
                item.setText(column, value)
        if iid is None:
            self._tree_iid_counter += 1
            key = f"I{self._tree_iid_counter:06d}"
        else:
            key = str(iid)
        self._tree_iids[key] = item
        item.setData(0, QtCore.Qt.ItemDataRole.UserRole, key)
        for tag in tags if isinstance(tags, (tuple, list)) else (tags,):
            color = self._tree_tags.get(str(tag))
            if color is not None:
                item.setForeground(0, color)
        return key

    def _iid_for_item(self, item):
        if item is None:
            return ""
        return str(item.data(0, QtCore.Qt.ItemDataRole.UserRole) or "")

    def _item(self, iid):
        if isinstance(iid, QtWidgets.QTreeWidgetItem):
            return iid
        return self._tree_iids.get(str(iid))

    def delete(self, *items):
        if len(items) == 1 and isinstance(items[0], (tuple, list)):
            items = tuple(items[0])
        for iid in items:
            item = self._item(iid)
            if item is None:
                continue
            parent = item.parent()
            if parent is None:
                self.invisibleRootItem().removeChild(item)
            else:
                parent.removeChild(item)
            self._forget_item(item)

    def _forget_item(self, item):
        for index in range(item.childCount()):
            self._forget_item(item.child(index))
        self._tree_iids.pop(self._iid_for_item(item), None)

    def get_children(self, item=""):
        owner = self._item(item) if item else self.invisibleRootItem()
        if owner is None:
            return ()
        return tuple(self._iid_for_item(owner.child(index)) for index in range(owner.childCount()))

    def item(self, iid, option=None, **options):
        item = self._item(iid)
        if item is None:
            return {} if option is None else ""
        if "text" in options and self._show_tree:
            item.setText(0, str(options["text"]))
        if "values" in options:
            values = tuple(str(value) for value in options["values"])
            item.setData(0, self._values_role, values)
            for column in range(self._value_offset, self.columnCount()):
                item.setText(column, "")
            for column, value in enumerate(values, start=self._value_offset):
                if column < self.columnCount():
                    item.setText(column, value)
        if "tags" in options:
            for tag in options["tags"]:
                color = self._tree_tags.get(str(tag))
                if color is not None:
                    item.setForeground(0, color)
        if "open" in options:
            item.setExpanded(bool(options["open"]))
        if option == "text":
            return item.text(0) if self._show_tree else ""
        if option == "values":
            return tuple(item.data(0, self._values_role) or ())
        return {
            "text": item.text(0) if self._show_tree else "",
            "values": tuple(item.data(0, self._values_role) or ()),
        }

    def heading(self, column, text=None, **_options):
        if text is not None:
            index = self._column_index(column)
            self.headerItem().setText(index, str(text))

    def column(self, column, width=None, stretch=None, anchor=None, **_options):
        index = self._column_index(column)
        if width is not None:
            self.setColumnWidth(index, int(width))
        if stretch is False:
            self.header().setSectionResizeMode(index, QtWidgets.QHeaderView.ResizeMode.Fixed)
        elif stretch is True:
            self.header().setSectionResizeMode(index, QtWidgets.QHeaderView.ResizeMode.Stretch)
        if anchor == "center":
            self.headerItem().setTextAlignment(index, QtCore.Qt.AlignmentFlag.AlignCenter)

    def _column_index(self, column):
        if column in {"#0", 0, "0"}:
            return 0 if self._show_tree else 0
        try:
            return self._tree_columns.index(column) + self._value_offset
        except ValueError:
            return int(column)

    def tag_configure(self, tag, foreground=None, **_options):
        if foreground:
            color = _qt_color(foreground)
            self._tree_tags[str(tag)] = color
            for item in self._tree_iids.values():
                item.setForeground(0, color)

    def selection(self):
        return tuple(self._iid_for_item(item) for item in self.selectedItems())

    def focus(self, iid=None):
        if iid is not None:
            item = self._item(iid)
            if item is not None:
                self.setCurrentItem(item)
            return str(iid)
        return self._iid_for_item(self.currentItem())

    def exists(self, iid):
        return str(iid) in self._tree_iids

    def parent(self, iid):
        item = self._item(iid)
        return self._iid_for_item(item.parent()) if item is not None else ""

    def see(self, iid):
        item = self._item(iid)
        if item is not None:
            self.scrollToItem(item)

    def yview(self, *args):
        bar = self.verticalScrollBar()
        if args:
            if args[0] == "moveto" and len(args) > 1:
                bar.setValue(round(float(args[1]) * bar.maximum()))
            elif args[0] == "scroll" and len(args) > 1:
                bar.setValue(bar.value() + int(args[1]) * 3)
        return (bar.value(), bar.maximum())


class Notebook(QtWidgets.QWidget, _WidgetMixin):
    """Closable document tabs that wrap into two rows when the bar fills."""

    def __init__(self, parent=None, **_options):
        ensure_application()
        super().__init__(parent)
        self._init_tk(parent)
        self._pages = []
        self._current = None
        self._tab_widgets = {}
        self.close_callback = None
        self._outer = QtWidgets.QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(1)
        self._rows = []
        for _ in range(2):
            scroll = QtWidgets.QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            strip = QtWidgets.QWidget(scroll)
            layout = QtWidgets.QHBoxLayout(strip)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(2)
            scroll.setWidget(strip)
            self._outer.addWidget(scroll)
            self._rows.append((scroll, strip, layout))
        self._stack = QtWidgets.QStackedWidget(self)
        self._outer.addWidget(self._stack, 1)
        self._rows[1][0].hide()

    def add(self, widget, text=""):
        self.insert(END, widget, text)

    def insert(self, index, widget, text=""):
        if widget in self._pages:
            self.tab(widget, text=text)
            return
        position = len(self._pages) if index in {END, "end"} else int(index)
        self._pages.insert(position, widget)
        widget.setParent(self._stack)
        self._stack.insertWidget(position, widget)
        widget._notebook_label = str(text)
        if self._current is None:
            self.select(widget)
        elif position <= self._stack.currentIndex():
            self._stack.setCurrentIndex(self._stack.currentIndex() + 1)
        self._rebuild_tabs()

    def tabs(self):
        return tuple(str(page) for page in self._pages)

    def nametowidget(self, name):
        return next((page for page in self._pages if str(page) == str(name)), None)

    def tab(self, widget, option=None, **options):
        page = self.nametowidget(widget) if isinstance(widget, str) else widget
        if page is None:
            return "" if option == "text" else {}
        if "text" in options:
            label = str(options["text"])
            if label != page._notebook_label:
                page._notebook_label = label
                self._rebuild_tabs()
        if option == "text":
            return page._notebook_label
        return {"text": page._notebook_label}

    def select(self, widget=None):
        if widget is None:
            return str(self._current) if self._current is not None else ""
        page = self.nametowidget(widget) if isinstance(widget, str) else widget
        if page in self._pages:
            previous = self._current
            self._current = page
            self._set_tab_selected(previous, False)
            self._set_tab_selected(page, True)
            self._stack.setCurrentWidget(page)
        return str(self._current) if self._current is not None else ""

    def forget(self, widget):
        page = self.nametowidget(widget) if isinstance(widget, str) else widget
        if page not in self._pages:
            return
        index = self._pages.index(page)
        self._pages.remove(page)
        self._stack.removeWidget(page)
        if self._current is page:
            self._current = self._pages[min(index, len(self._pages) - 1)] if self._pages else None
            if self._current is not None:
                self._stack.setCurrentWidget(self._current)
        page.setParent(None)
        self._rebuild_tabs()

    def _rebuild_tabs(self):
        self._tab_widgets = {}
        for _scroll, _strip, layout in self._rows:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
        available = max(300, self.width())
        rows = [[], []]
        used = 0
        for page in self._pages:
            label = getattr(page, "_notebook_label", "")
            width = max(98, min(260, len(label) * 8 + 48))
            if rows[0] and used + width > available:
                rows[1].append(page)
            else:
                rows[0].append(page)
                used += width
        if not rows[0] and rows[1]:
            rows[0], rows[1] = rows[1], []
        for row_index, pages in enumerate(rows):
            scroll, _strip, layout = self._rows[row_index]
            scroll.setVisible(bool(pages))
            for page in pages:
                tab = QtWidgets.QWidget()
                tab_layout = QtWidgets.QHBoxLayout(tab)
                tab_layout.setContentsMargins(4, 2, 3, 2)
                tab_layout.setSpacing(3)
                select_button = QtWidgets.QPushButton(getattr(page, "_notebook_label", ""), tab)
                select_button.setFlat(True)
                select_button.clicked.connect(lambda _checked=False, target=page: self.select(target))
                close_button = QtWidgets.QToolButton(tab)
                close_button.setText("×")
                close_button.setAutoRaise(True)
                close_button.setToolTip("Close tab")
                close_button.setVisible(getattr(page, "_tab_closable", True))
                close_button.clicked.connect(lambda _checked=False, target=page: self._close_page(target))
                if page is self._current:
                    tab.setStyleSheet("background: #3b4d65; border-radius: 3px;")
                else:
                    tab.setStyleSheet("background: #252a33; border-radius: 3px;")
                self._tab_widgets[page] = tab
                tab_layout.addWidget(select_button)
                tab_layout.addWidget(close_button)
                layout.addWidget(tab)
            layout.addStretch(1)
        if not rows[1]:
            self._rows[1][0].hide()

    def _set_tab_selected(self, page, selected):
        tab = self._tab_widgets.get(page)
        if tab is not None:
            color = "#3b4d65" if selected else "#252a33"
            tab.setStyleSheet(f"background: {color}; border-radius: 3px;")

    def _close_page(self, page):
        if self.close_callback is not None:
            self.close_callback(page)
        else:
            self.forget(page)

    def _bind_virtual(self, sequence, callback):
        if sequence == "<<NotebookTabChanged>>":
            self._stack.currentChanged.connect(lambda _index: callback(SimpleNamespace(widget=self)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_outer"):
            self._rebuild_tabs()


class _TagHighlighter(QtGui.QSyntaxHighlighter):
    def __init__(self, document, widget):
        self._widget = widget
        super().__init__(document)

    def highlightBlock(self, text):
        block_number = self.currentBlock().blockNumber()
        callback = self._widget._syntax_callback
        if callback is not None:
            for start, length, tag in callback(text):
                if length > 0:
                    self.setFormat(start, min(length, len(text) - start), self._widget._format_for_tag(tag))
        for start, length, char_format in self._widget._block_tag_formats.get(block_number, ()):
            self.setFormat(start, min(length, len(text) - start), char_format)


class Text(QtWidgets.QPlainTextEdit, _WidgetMixin):
    def __init__(self, parent=None, wrap="none", undo=True, font=None, **options):
        ensure_application()
        super().__init__(parent)
        self._init_tk(parent)
        self._tag_styles = {}
        self._tag_ranges = {}
        self._tag_order = []
        self._tag_apply_pending = False
        self._block_tag_formats = {}
        self._syntax_callback = None
        self._syntax_format_cache = {}
        self._tag_highlighter = _TagHighlighter(self.document(), self)
        self._modified_flag = False
        self._last_text = self.toPlainText()
        self._yscrollcommand = None
        self._xscrollcommand = None
        self.setUndoRedoEnabled(bool(undo))
        self.setLineWrapMode(
            QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth
            if wrap != "none" else QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap
        )
        if font:
            self.setFont(_qt_font(font))
        self.textChanged.connect(self._text_changed)
        self.verticalScrollBar().valueChanged.connect(self._sync_yview)
        self.horizontalScrollBar().valueChanged.connect(self._sync_xview)
        self.configure(**options)

    def set_text_silently(self, value):
        self._syntax_callback = None
        self._block_tag_formats = {}
        self._tag_ranges = {tag: [] for tag in self._tag_order}
        self.blockSignals(True)
        try:
            super().setPlainText(str(value))
        finally:
            self.blockSignals(False)
        self._last_text = self.toPlainText()
        self._modified_flag = False
        self.document().setModified(False)

    def get_all_text(self):
        return self._last_text

    def set_syntax_callback(self, callback):
        self._syntax_callback = callback

    def rehighlight_block(self, block):
        self._tag_highlighter.rehighlightBlock(block)

    def _format_for_tag(self, tag):
        char_format = self._syntax_format_cache.get(tag)
        if char_format is None:
            style = self._tag_styles.get(tag, {})
            char_format = QtGui.QTextCharFormat()
            if "foreground" in style:
                char_format.setForeground(_qt_color(style["foreground"]))
            if "background" in style:
                char_format.setBackground(_qt_color(style["background"]))
            if style.get("underline"):
                char_format.setFontUnderline(True)
            if "font" in style:
                char_format.setFont(_qt_font(style["font"]))
            self._syntax_format_cache[tag] = char_format
        return char_format

    def _text_changed(self):
        current = self.toPlainText()
        if current != self._last_text:
            self._last_text = current
            self._modified_flag = True
            self.document().setModified(True)
            self._queue_tag_apply()

    def configure(self, **options):
        if "font" in options:
            self.setFont(_qt_font(options["font"]))
        if "background" in options or "foreground" in options:
            bg = options.get("background", "#171a21")
            fg = options.get("foreground", "#d8dee9")
            self.setStyleSheet(f"QPlainTextEdit {{ background: {bg}; color: {fg}; selection-background-color: {options.get('selectbackground', '#3b4d65')}; border: 0; }}")
        if "insertbackground" in options:
            self.setStyleSheet(self.styleSheet() + f" QPlainTextEdit {{ qproperty-cursorWidth: 2; }}")
        if "state" in options:
            self.setReadOnly(options["state"] == "disabled")
        if "wrap" in options:
            self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth if options["wrap"] != "none" else QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        if "yscrollcommand" in options:
            self._yscrollcommand = options["yscrollcommand"]
        if "xscrollcommand" in options:
            self._xscrollcommand = options["xscrollcommand"]

    config = configure

    def _sync_yview(self, _value=None):
        bar = self.verticalScrollBar()
        if self._yscrollcommand:
            maximum = max(1, bar.maximum() + bar.pageStep())
            first = bar.value() / maximum
            last = min(1.0, (bar.value() + bar.pageStep()) / maximum)
            self._yscrollcommand(first, last)

    def _sync_xview(self, _value=None):
        bar = self.horizontalScrollBar()
        if self._xscrollcommand:
            maximum = max(1, bar.maximum() + bar.pageStep())
            first = bar.value() / maximum
            last = min(1.0, (bar.value() + bar.pageStep()) / maximum)
            self._xscrollcommand(first, last)

    def _position(self, index):
        text = self.toPlainText()
        if isinstance(index, int):
            return max(0, min(len(text), index))
        value = str(index).strip()
        if value == "insert":
            return self.textCursor().position()
        if value in {"end", "end-1c"}:
            return len(text) + (1 if value == "end" else 0)
        if value in {"sel.first", "sel.last"}:
            cursor = self.textCursor()
            if not cursor.hasSelection():
                raise TclError("text index is not in a selection")
            return cursor.selectionStart() if value.endswith("first") else cursor.selectionEnd()
        if value.startswith("@"):
            match = re.match(r"@(\-?\d+),(\-?\d+)", value)
            if match:
                cursor = self.cursorForPosition(QtCore.QPoint(int(match.group(1)), int(match.group(2))))
                return cursor.position()
        line_adjust = None
        base = value
        match = re.fullmatch(r"(.+?)\s+line(start|end)", value)
        if match:
            base, line_adjust = match.group(1), match.group(2)
        offset_match = re.fullmatch(r"(.+?)([+-])(\d+)c", base)
        extra = 0
        if offset_match:
            base = offset_match.group(1)
            extra = int(offset_match.group(3)) * (1 if offset_match.group(2) == "+" else -1)
        line_match = re.fullmatch(r"(\d+)\.(\d+|end)", base)
        if base in {"insert", "end", "end-1c"}:
            position = self._position(base)
        elif line_match:
            line = max(1, int(line_match.group(1)))
            lines = text.split("\n")
            line_index = min(line - 1, len(lines) - 1)
            before = sum(len(item) + 1 for item in lines[:line_index])
            column = len(lines[line_index]) if line_match.group(2) == "end" else int(line_match.group(2))
            position = before + min(column, len(lines[line_index]))
        else:
            try:
                position = int(base)
            except ValueError:
                position = self.textCursor().position()
        position = max(0, min(len(text), position + extra))
        if line_adjust:
            cursor = self.textCursor()
            cursor.setPosition(position)
            if line_adjust == "start":
                cursor.movePosition(QtGui.QTextCursor.MoveOperation.StartOfLine)
            else:
                cursor.movePosition(QtGui.QTextCursor.MoveOperation.EndOfLine)
            position = cursor.position()
        return position

    def index(self, index):
        text = self.toPlainText()
        position = max(0, min(len(text), self._position(index)))
        prefix = text[:position]
        line = prefix.count("\n") + 1
        column = len(prefix.rsplit("\n", 1)[-1])
        return f"{line}.{column}"

    def get(self, first, last=None):
        text = self.toPlainText()
        start = max(0, min(len(text), self._position(first)))
        if last is None:
            end = min(len(text), start + 1)
        elif str(last) == "end":
            end = len(text) + 1
        else:
            end = max(0, min(len(text), self._position(last)))
        result = text[start:min(len(text), end)]
        if str(last) == "end" and end > len(text):
            result += "\n"
        return result

    def insert(self, index, value, *_tags):
        cursor = self.textCursor()
        cursor.setPosition(max(0, min(len(self.toPlainText()), self._position(index))))
        cursor.insertText(str(value))
        self.setTextCursor(cursor)

    def delete(self, first, last=None):
        start = max(0, min(len(self.toPlainText()), self._position(first)))
        end = min(len(self.toPlainText()), self._position(last)) if last is not None else min(len(self.toPlainText()), start + 1)
        if end < start:
            start, end = end, start
        cursor = self.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QtGui.QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.setTextCursor(cursor)

    def mark_set(self, mark, index):
        if mark == "insert":
            cursor = self.textCursor()
            cursor.setPosition(max(0, min(len(self.toPlainText()), self._position(index))))
            self.setTextCursor(cursor)

    def see(self, index):
        current_cursor = self.textCursor()
        scroll_cursor = QtGui.QTextCursor(self.document())
        scroll_cursor.setPosition(max(0, min(len(self.toPlainText()), self._position(index))))
        self.setTextCursor(scroll_cursor)
        self.ensureCursorVisible()
        self.setTextCursor(current_cursor)

    def edit_modified(self, value=None):
        if value is not None:
            self._modified_flag = bool(value)
            self.document().setModified(bool(value))
        return self._modified_flag

    def edit_undo(self):
        if not self.document().isUndoAvailable():
            raise TclError("nothing to undo")
        self.undo()

    def edit_redo(self):
        if not self.document().isRedoAvailable():
            raise TclError("nothing to redo")
        self.redo()

    def edit_separator(self):
        return None

    def bbox(self, index):
        cursor = self.textCursor()
        cursor.setPosition(max(0, min(len(self.toPlainText()), self._position(index))))
        rect = self.cursorRect(cursor)
        return rect.x(), rect.y(), max(1, self.fontMetrics().horizontalAdvance(" ")), rect.height()

    def dlineinfo(self, index):
        try:
            line_number = int(str(index).split(".", 1)[0])
        except ValueError:
            return None
        if line_number < 1 or line_number > self.document().blockCount():
            return None
        cursor = self.textCursor()
        cursor.setPosition(max(0, min(len(self.toPlainText()), self._position(index))))
        rect = self.cursorRect(cursor)
        if rect.bottom() < 0 or rect.top() > self.viewport().height():
            return None
        return 0, rect.y(), self.viewport().width(), rect.height(), rect.height()

    def compare(self, first, operation, second):
        left, right = self._position(first), self._position(second)
        return {"<": left < right, "<=": left <= right, "==": left == right, ">=": left >= right, ">": left > right, "!=": left != right}.get(operation, False)

    def search(self, pattern, index, stopindex=None, nocase=False, backwards=False, count=None, **_options):
        text = self.toPlainText()
        start = self._position(index)
        stop = self._position(stopindex) if stopindex is not None else (0 if backwards else len(text))
        haystack = text.casefold() if nocase else text
        needle = str(pattern).casefold() if nocase else str(pattern)
        found = haystack.rfind(needle, max(0, stop), min(len(haystack), start)) if backwards else haystack.find(needle, max(0, start), min(len(haystack), stop))
        if count is not None:
            count.set(len(pattern) if found >= 0 else 0)
        return self.index(found) if found >= 0 else ""

    def tag_configure(self, tag, **options):
        if tag not in self._tag_styles:
            self._tag_order.append(tag)
            self._tag_ranges[tag] = []
        self._tag_styles[tag] = {**self._tag_styles.get(tag, {}), **options}
        self._syntax_format_cache.pop(tag, None)
        self._queue_tag_apply()

    tag_config = tag_configure

    def tag_add(self, tag, first, last):
        start = max(0, min(len(self.toPlainText()), self._position(first)))
        end = max(0, min(len(self.toPlainText()), self._position(last)))
        if end > start:
            self._tag_ranges.setdefault(tag, []).append((start, end))
            if tag not in self._tag_order:
                self._tag_order.append(tag)
            self._queue_tag_apply()

    def tag_remove(self, tag, first, last):
        if tag == "sel":
            cursor = self.textCursor()
            cursor.clearSelection()
            self.setTextCursor(cursor)
            return
        start = max(0, min(len(self.toPlainText()), self._position(first)))
        end = max(0, min(len(self.toPlainText()), self._position(last)))
        remaining = []
        for begin, finish in self._tag_ranges.get(tag, []):
            if finish <= start or begin >= end:
                remaining.append((begin, finish))
            else:
                if begin < start:
                    remaining.append((begin, start))
                if finish > end:
                    remaining.append((end, finish))
        self._tag_ranges[tag] = remaining
        self._queue_tag_apply()

    def clear_tag_ranges(self, tags):
        for tag in tags:
            self._tag_ranges[tag] = []
        self._queue_tag_apply()

    def tag_bind(self, *_args, **_kwargs):
        return None

    def _queue_tag_apply(self):
        if self._tag_apply_pending:
            return
        self._tag_apply_pending = True
        QtCore.QTimer.singleShot(0, self._apply_all_tags)

    def _apply_all_tags(self):
        self._tag_apply_pending = False
        document = self.document()
        previous_block_numbers = set(self._block_tag_formats)
        block_spans = {}
        justify_tags = []
        for tag in self._tag_order:
            style = self._tag_styles.get(tag, {})
            char_format = QtGui.QTextCharFormat()
            if "foreground" in style:
                char_format.setForeground(_qt_color(style["foreground"]))
            if "background" in style:
                char_format.setBackground(_qt_color(style["background"]))
            if style.get("underline"):
                char_format.setFontUnderline(True)
            if "font" in style:
                char_format.setFont(_qt_font(style["font"]))
            if "justify" in style:
                justify_tags.append((tag, style["justify"]))

            for start, end in self._tag_ranges.get(tag, []):
                if start >= end:
                    continue
                if not char_format.isEmpty():
                    block = document.findBlock(start)
                    while block.isValid() and block.position() < end:
                        block_start = block.position()
                        block_end = block_start + len(block.text())
                        overlap_start = max(start, block_start) - block_start
                        overlap_end = min(end, block_end) - block_start
                        if overlap_end > overlap_start:
                            block_spans.setdefault(block.blockNumber(), []).append(
                                (overlap_start, overlap_end, char_format)
                            )
                        block = block.next()

        self._block_tag_formats = {}
        for block_number, spans in block_spans.items():
            boundaries = sorted(
                {position for start, end, _format in spans for position in (start, end)}
            )
            formats = []
            for start, end in zip(boundaries, boundaries[1:]):
                merged = QtGui.QTextCharFormat()
                for span_start, span_end, char_format in spans:
                    if span_start <= start and span_end >= end:
                        merged.merge(char_format)
                if not merged.isEmpty():
                    formats.append((start, end - start, merged))
            self._block_tag_formats[block_number] = formats
        for block_number in previous_block_numbers | set(self._block_tag_formats):
            block = document.findBlockByNumber(block_number)
            if block.isValid():
                self._tag_highlighter.rehighlightBlock(block)

        if justify_tags:
            cursor = QtGui.QTextCursor(document)
            cursor.select(QtGui.QTextCursor.SelectionType.Document)
            cursor.setBlockFormat(QtGui.QTextBlockFormat())
            text_length = len(self.toPlainText())
            for tag, alignment in justify_tags:
                for start, end in self._tag_ranges.get(tag, []):
                    if start >= text_length:
                        continue
                    selection = QtGui.QTextCursor(document)
                    selection.setPosition(start)
                    selection.setPosition(
                        min(end, text_length), QtGui.QTextCursor.MoveMode.KeepAnchor
                    )
                    block_format = QtGui.QTextBlockFormat()
                    block_format.setAlignment(
                        QtCore.Qt.AlignmentFlag.AlignRight
                        if alignment == "right"
                        else QtCore.Qt.AlignmentFlag.AlignLeft
                    )
                    selection.mergeBlockFormat(block_format)

    def yview(self, *args):
        bar = self.verticalScrollBar()
        if args:
            if args[0] == "moveto" and len(args) > 1:
                bar.setValue(round(float(args[1]) * bar.maximum()))
            elif args[0] == "scroll" and len(args) > 1:
                multiplier = bar.singleStep() if len(args) < 3 or args[2] == "units" else bar.pageStep()
                bar.setValue(bar.value() + int(args[1]) * multiplier)
        return (bar.value(), bar.maximum())

    def xview(self, *args):
        bar = self.horizontalScrollBar()
        if args:
            if args[0] == "moveto" and len(args) > 1:
                bar.setValue(round(float(args[1]) * bar.maximum()))
            elif args[0] == "scroll" and len(args) > 1:
                multiplier = bar.singleStep() if len(args) < 3 or args[2] == "units" else bar.pageStep()
                bar.setValue(bar.value() + int(args[1]) * multiplier)
        return (bar.value(), bar.maximum())


class Canvas(QtWidgets.QGraphicsView, _WidgetMixin):
    def __init__(self, parent=None, background="#20242d", **options):
        ensure_application()
        self._scene = QtWidgets.QGraphicsScene()
        super().__init__(self._scene, parent)
        self._init_tk(parent)
        self._canvas_tags = {}
        self._tag_callbacks = []
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setBackgroundBrush(_qt_color(background))
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def configure(self, **options):
        if "background" in options:
            self.setBackgroundBrush(_qt_color(options["background"]))
        if "scrollregion" in options:
            x0, y0, x1, y1 = options["scrollregion"]
            self._scene.setSceneRect(float(x0), float(y0), float(x1) - float(x0), float(y1) - float(y0))
        if "xscrollcommand" in options:
            def send_xview(value):
                bar = self.horizontalScrollBar()
                span = max(1, bar.maximum() + bar.pageStep())
                options["xscrollcommand"](value / span, min(1.0, (value + bar.pageStep()) / span))
            self.horizontalScrollBar().valueChanged.connect(send_xview)
        if "yscrollcommand" in options:
            def send_yview(value):
                bar = self.verticalScrollBar()
                span = max(1, bar.maximum() + bar.pageStep())
                options["yscrollcommand"](value / span, min(1.0, (value + bar.pageStep()) / span))
            self.verticalScrollBar().valueChanged.connect(send_yview)

    config = configure

    def delete(self, target):
        if target == "all":
            self._scene.clear()
            self._canvas_tags.clear()

    def create_line(self, x0, y0, x1, y1, fill="#ffffff", width=1, tags=(), **options):
        item = self._scene.addLine(float(x0), float(y0), float(x1), float(y1), QtGui.QPen(_qt_color(fill), float(width)))
        self._remember_tags(item, tags)
        if options.get("arrow") == "last":
            angle = math.atan2(float(y1) - float(y0), float(x1) - float(x0))
            length = 12
            arrow_left = QtCore.QPointF(
                float(x1) - length * math.cos(angle - math.pi / 6),
                float(y1) - length * math.sin(angle - math.pi / 6),
            )
            arrow_right = QtCore.QPointF(
                float(x1) - length * math.cos(angle + math.pi / 6),
                float(y1) - length * math.sin(angle + math.pi / 6),
            )
            self._scene.addPolygon(
                QtGui.QPolygonF([QtCore.QPointF(float(x1), float(y1)), arrow_left, arrow_right]),
                QtGui.QPen(_qt_color(fill)),
                QtGui.QBrush(_qt_color(fill)),
            )
        return id(item)

    def create_rectangle(self, x0, y0, x1, y1, fill="transparent", outline="#ffffff", width=1, tags=(), **_options):
        pen = QtGui.QPen(_qt_color(outline), float(width))
        brush = QtGui.QBrush(_qt_color(fill)) if fill not in {None, "", "transparent"} else QtCore.Qt.BrushStyle.NoBrush
        item = self._scene.addRect(float(x0), float(y0), float(x1) - float(x0), float(y1) - float(y0), pen, brush)
        self._remember_tags(item, tags)
        return id(item)

    def create_text(self, x, y, text="", fill="#ffffff", font=None, anchor="center", tags=(), **_options):
        item = self._scene.addText(str(text), _qt_font(font) if font else self.font())
        if "width" in _options and _options["width"]:
            item.setTextWidth(float(_options["width"]))
        item.setDefaultTextColor(_qt_color(fill))
        rect = item.boundingRect()
        if anchor in {"nw", "w", "sw"}:
            px = float(x)
        elif anchor in {"ne", "e", "se"}:
            px = float(x) - rect.width()
        else:
            px = float(x) - rect.width() / 2
        if anchor in {"nw", "n", "ne"}:
            py = float(y)
        elif anchor in {"sw", "s", "se"}:
            py = float(y) - rect.height()
        else:
            py = float(y) - rect.height() / 2
        item.setPos(px, py)
        self._remember_tags(item, tags)
        return id(item)

    def _remember_tags(self, item, tags):
        if isinstance(tags, str):
            tags = (tags,)
        for tag in tags or ():
            self._canvas_tags.setdefault(str(tag), set()).add(item)

    def tag_bind(self, tag, sequence, callback):
        self._tag_callbacks.append((str(tag), sequence, callback))

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is not None:
            for tag, sequence, callback in self._tag_callbacks:
                if sequence == "<Double-1>" and item in self._canvas_tags.get(tag, set()):
                    result = callback(_make_mouse_event(self, event))
                    if result == "break":
                        event.accept()
                        return
        super().mouseDoubleClickEvent(event)

    def xview(self, *args):
        bar = self.horizontalScrollBar()
        if args and args[0] == "moveto":
            bar.setValue(round(float(args[1]) * bar.maximum()))
        elif args and args[0] == "scroll":
            bar.setValue(bar.value() + int(args[1]) * 30)
        return (bar.value(), bar.maximum())

    def yview(self, *args):
        bar = self.verticalScrollBar()
        if args and args[0] == "moveto":
            bar.setValue(round(float(args[1]) * bar.maximum()))
        elif args and args[0] == "scroll":
            bar.setValue(bar.value() + int(args[1]) * 30)
        return (bar.value(), bar.maximum())


def _file_filter(filetypes, defaultextension=None):
    filters = []
    for item in filetypes or ():
        if len(item) < 2:
            continue
        label, patterns = item[0], item[1]
        if isinstance(patterns, (tuple, list)):
            patterns = " ".join(patterns)
        filters.append(f"{label} ({patterns})")
    if defaultextension and "All files" not in " ".join(filters):
        filters.append("All files (*)")
    return ";;".join(filters)


class filedialog:
    @staticmethod
    def askdirectory(title="Choose folder", initialdir=None, parent=None, **_options):
        return QtWidgets.QFileDialog.getExistingDirectory(parent, str(title), str(initialdir or ""))

    @staticmethod
    def askopenfilename(title="Open file", initialdir=None, filetypes=(), parent=None, **_options):
        path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(parent, str(title), str(initialdir or ""), _file_filter(filetypes))
        return path

    @staticmethod
    def asksaveasfilename(title="Save file", initialdir=None, initialfile="", defaultextension=None, filetypes=(), parent=None, **_options):
        start = str(initialdir or "")
        if initialfile:
            start = QtCore.QDir(start).filePath(str(initialfile)) if start else str(initialfile)
        path, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(parent, str(title), start, _file_filter(filetypes, defaultextension))
        if path and defaultextension and not QtCore.QFileInfo(path).suffix:
            path += str(defaultextension)
        return path


class messagebox:
    @staticmethod
    def showinfo(title, message, parent=None, **_options):
        return QtWidgets.QMessageBox.information(parent, str(title), str(message))

    @staticmethod
    def showwarning(title, message, parent=None, **_options):
        return QtWidgets.QMessageBox.warning(parent, str(title), str(message))

    @staticmethod
    def showerror(title, message, parent=None, **_options):
        return QtWidgets.QMessageBox.critical(parent, str(title), str(message))

    @staticmethod
    def askyesno(title, message, parent=None, **_options):
        answer = QtWidgets.QMessageBox.question(parent, str(title), str(message), QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        return answer == QtWidgets.QMessageBox.StandardButton.Yes

    @staticmethod
    def askyesnocancel(title, message, parent=None, **_options):
        answer = QtWidgets.QMessageBox.question(parent, str(title), str(message), QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No | QtWidgets.QMessageBox.StandardButton.Cancel)
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            return True
        if answer == QtWidgets.QMessageBox.StandardButton.No:
            return False
        return None


class simpledialog:
    @staticmethod
    def askstring(title, prompt, parent=None, initialvalue=None, **_options):
        value, accepted = QtWidgets.QInputDialog.getText(parent, str(title), str(prompt), text=str(initialvalue or ""))
        return value if accepted else None


def show_markdown(parent, title, content):
    dialog = Toplevel(parent)
    dialog.setWindowTitle(str(title))
    dialog.resize(920, 720)
    layout = QtWidgets.QVBoxLayout(dialog)
    browser = QtWidgets.QTextBrowser(dialog)
    browser.setOpenExternalLinks(True)
    browser.setMarkdown(str(content))
    layout.addWidget(browser)
    dialog.show()
    return dialog


class _TtkNamespace:
    Frame = Frame
    LabelFrame = LabelFrame
    Label = Label
    Button = Button
    Entry = Entry
    Checkbutton = Checkbutton
    Combobox = ComboBox
    Scrollbar = Scrollbar
    Panedwindow = Panedwindow
    Notebook = Notebook
    Treeview = Treeview
    Style = Style


ttk = _TtkNamespace()

Button = Button
Canvas = Canvas
Checkbutton = Checkbutton
Combobox = ComboBox
Entry = Entry
Frame = Frame
Label = Label
LabelFrame = LabelFrame
Listbox = Listbox
Menu = Menu
Notebook = Notebook
Panedwindow = Panedwindow
Scrollbar = Scrollbar
StringVar = StringVar
BooleanVar = BooleanVar
IntVar = IntVar
Text = Text
Tk = Tk
Toplevel = Toplevel
Treeview = Treeview
Style = Style
QtWidgets = QtWidgets
QtCore = QtCore
QtGui = QtGui





