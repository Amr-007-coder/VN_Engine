"""Visual editor for portable, declarative VN Engine style presets."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pygame

from editor_qt import QtCore, QtGui, QtWidgets
from engine.layout import component_layout, layout_children, resolve_rect, safe_area_rect, select_profile
from engine.style import DEFAULT_STYLE, apply_style_variant, resolve_style
from engine.theme_preview import OffscreenThemeRenderer


SCREEN_COMPONENTS = {
    "Dialogue": ("dialogue", ("textbox", "speaker", "dialogue_text", "choices", "controls", "pause_control")),
    "Menu": ("menu", ("panel", "title", "items")),
    "History": ("history", ("panel",)),
    "Save slots": ("save_slots", ("title", "items", "actions")),
    "Overlays": ("overlays", ("confirmation", "story_input", "variable_inspector")),
}

VIEWPORTS = {
    "Desktop 16:9": (1280, 720),
    "Tablet 4:3": (1024, 768),
    "Mobile portrait": (390, 844),
}


def _get_path(value, path, fallback=None):
    current = value
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and isinstance(key, int) and 0 <= key < len(current):
            current = current[key]
        else:
            return fallback
    return current


def _set_path(value, path, new_value):
    current = value
    for key in path[:-1]:
        if isinstance(current, list) and isinstance(key, int) and 0 <= key < len(current):
            child = current[key]
            if not isinstance(child, dict):
                child = {}
                current[key] = child
            current = child
            continue
        child = current.get(key) if isinstance(current, dict) else None
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    if isinstance(current, list) and isinstance(path[-1], int):
        current[path[-1]] = new_value
    else:
        current[path[-1]] = new_value


def _style_path(screen, component, key):
    if key in {"anchor", "x", "y", "left", "right", "top", "bottom", "width", "height", "constraints", "type", "direction", "columns", "rows", "gap", "item_size", "align", "justify", "layout_padding"}:
        layout_component = "textbox" if screen == "dialogue" and component in {"textbox", "dialogue_text"} else component
        layout_key = "padding" if key == "layout_padding" else key
        return ("layouts", "screens", screen, "components", layout_component, layout_key)
    if component == "title" and key == "title_alignment":
        return ("components", "menu", key)
    owner = {"dialogue": "textbox" if component == "textbox" else "dialogue_controls" if component == "controls" else "pause_control" if component == "pause_control" else component,
             "menu": "menu", "history": "history", "save_slots": "save_slots", "overlays": "overlays"}.get(screen, "overlays")
    if key == "fit" and screen == "menu":
        key = "button_fit"
    elif key == "fit" and screen == "save_slots":
        key = "thumbnail_fit"
    return ("components", owner, key)


class ThemePreview(QtWidgets.QWidget):
    """Clickable preview canvas whose rectangles are resolved by the runtime layout model."""

    componentSelected = QtCore.Signal(str)
    componentMoved = QtCore.Signal(str, int, int)
    diagnosticsChanged = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(460, 320)
        self.style_values = resolve_style()
        self.screen_name = "dialogue"
        self.viewport = VIEWPORTS["Desktop 16:9"]
        self.selected_component = "textbox"
        self.selected_state = "normal"
        self.project_root = None
        self._renderer = None
        self._qimage = None
        self._rendered_regions = {}
        self._hit_rects = []
        self._drag_component = None
        self._drag_start = None

    def set_preview(self, style_values, screen_name, viewport, selected_component, selected_state="normal"):
        self.style_values = style_values
        self.screen_name = screen_name
        self.viewport = viewport
        self.selected_component = selected_component
        self.selected_state = selected_state
        if self._renderer is None or self._renderer.project_root != (Path(self.project_root).resolve() if self.project_root else None):
            self._renderer = OffscreenThemeRenderer(self.project_root)
        frame = self._renderer.render(
            self.style_values, self.screen_name, self.viewport,
            self.selected_component, self.selected_state,
        )
        raw = pygame.image.tobytes(frame.surface, "RGBA")
        self._qimage = QtGui.QImage(
            raw, frame.surface.get_width(), frame.surface.get_height(),
            frame.surface.get_width() * 4, QtGui.QImage.Format.Format_RGBA8888,
        ).copy()
        self._rendered_regions = frame.regions
        if frame.diagnostics:
            summary = "Preview asset notices: " + "; ".join(frame.diagnostics[:4])
            if len(frame.diagnostics) > 4:
                summary += f"; and {len(frame.diagnostics) - 4} more"
        else:
            summary = ""
        self.diagnosticsChanged.emit(summary)
        self.update()

    def _scaled_canvas(self):
        width, height = self.viewport
        scale = min(self.width() / max(1, width), self.height() / max(1, height))
        draw_width, draw_height = width * scale, height * scale
        origin = ((self.width() - draw_width) / 2, (self.height() - draw_height) / 2)
        return scale, origin, QtCore.QRectF(origin[0], origin[1], draw_width, draw_height)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("#151821"))
        scale, origin, canvas = self._scaled_canvas()
        self._hit_rects = []
        if self._qimage is not None:
            painter.drawImage(canvas, self._qimage)
        selected_rects = []
        for component, rects in self._rendered_regions.items():
            for logical in rects:
                actual = QtCore.QRectF(
                    origin[0] + logical.x * scale,
                    origin[1] + logical.y * scale,
                    logical.width * scale,
                    logical.height * scale,
                )
                self._hit_rects.append((actual, component))
                if component == self.selected_component:
                    selected_rects.append(actual)
        for actual in selected_rects:
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.setPen(QtGui.QPen(QtGui.QColor("#f0bd6f"), 2))
            painter.drawRect(actual)
            handle_size = 8
            painter.setBrush(QtGui.QColor("#f0bd6f"))
            painter.setPen(QtGui.QPen(QtGui.QColor("#151821"), 1))
            for point in (actual.topLeft(), actual.topRight(), actual.bottomLeft(), actual.bottomRight()):
                handle = QtCore.QRectF(
                    point.x() - handle_size / 2, point.y() - handle_size / 2,
                    handle_size, handle_size,
                )
                painter.drawRect(handle)
        painter.end()

    @staticmethod
    def _label(component):
        return {
            "textbox": "Dialogue textbox", "choices": "Choice", "controls": "Controls",
            "pause_control": "Pause", "title": "Screen title", "items": "Menu item",
            "actions": "Action button", "panel": "Panel", "confirmation": "Confirmation",
            "story_input": "Story input", "variable_inspector": "Variable inspector",
        }.get(component, component.replace("_", " ").title())

    def mousePressEvent(self, event):
        for rect, component in reversed(self._hit_rects):
            if rect.contains(event.position()):
                self.componentSelected.emit(component)
                self._drag_component = component
                self._drag_start = event.position()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_component is None or self._drag_start is None:
            super().mouseMoveEvent(event)
            return
        delta = event.position() - self._drag_start
        scale, _origin, _canvas = self._scaled_canvas()
        if scale > 0 and abs(delta.x()) + abs(delta.y()) >= 3:
            self.componentMoved.emit(self._drag_component, round(delta.x() / scale), round(delta.y() / scale))
            self._drag_start = event.position()

    def mouseReleaseEvent(self, event):
        self._drag_component = None
        self._drag_start = None
        super().mouseReleaseEvent(event)


class VisualThemeEditor(QtWidgets.QDialog):
    """Edit commonly used component and layout properties with a responsive preview."""

    def __init__(self, parent, style_values, project_root=None):
        super().__init__(parent)
        self.setWindowTitle("Visual Theme Editor")
        self.resize(1180, 760)
        self.style_values = resolve_style(deepcopy(style_values))
        self.project_root = Path(project_root).resolve() if project_root else None
        self._updating = False
        self._fields = {}
        self._build_ui()
        self._refresh_components()
        self._refresh_preview()

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Screen"))
        self.screen_picker = QtWidgets.QComboBox()
        for label, (name, _components) in SCREEN_COMPONENTS.items():
            self.screen_picker.addItem(label, name)
        self.screen_picker.currentIndexChanged.connect(self._refresh_components)
        top.addWidget(self.screen_picker)
        top.addWidget(QtWidgets.QLabel("Preview size"))
        self.viewport_picker = QtWidgets.QComboBox()
        for label, size in VIEWPORTS.items():
            self.viewport_picker.addItem(label, size)
        self.viewport_picker.currentIndexChanged.connect(self._viewport_changed)
        top.addWidget(self.viewport_picker)
        top.addWidget(QtWidgets.QLabel("Theme variant"))
        self.variant_picker = QtWidgets.QComboBox()
        self.variant_picker.currentIndexChanged.connect(self._variant_changed)
        top.addWidget(self.variant_picker)
        add_variant = QtWidgets.QPushButton("Add variant…")
        add_variant.clicked.connect(self._add_variant)
        top.addWidget(add_variant)
        top.addStretch(1)
        outer.addLayout(top)

        body = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        preview_container = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)
        self.preview = ThemePreview()
        self.preview.project_root = self.project_root
        self.preview.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(self.preview, 1)
        self.preview_diagnostics = QtWidgets.QLabel("")
        self.preview_diagnostics.setWordWrap(True)
        self.preview_diagnostics.setStyleSheet("color: #e6bd83; padding: 2px 6px;")
        preview_layout.addWidget(self.preview_diagnostics)
        self.preview.diagnosticsChanged.connect(self.preview_diagnostics.setText)
        body.addWidget(preview_container)
        self.preview.componentSelected.connect(self._select_component)
        self.preview.componentMoved.connect(self._move_component)

        inspector = QtWidgets.QWidget()
        inspector_layout = QtWidgets.QVBoxLayout(inspector)
        self.component_picker = QtWidgets.QComboBox()
        self.component_picker.currentIndexChanged.connect(self._select_component_from_picker)
        inspector_layout.addWidget(QtWidgets.QLabel("Component"))
        inspector_layout.addWidget(self.component_picker)
        self.state_picker = QtWidgets.QComboBox()
        self.state_picker.addItems(["normal", "hover", "focus", "pressed", "disabled", "selected"])
        self.state_picker.currentTextChanged.connect(self._state_changed)
        inspector_layout.addWidget(QtWidgets.QLabel("Preview control state"))
        inspector_layout.addWidget(self.state_picker)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        self.form = QtWidgets.QWidget()
        self.form_layout = QtWidgets.QFormLayout(self.form)
        self.form_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        scroll.setWidget(self.form)
        inspector_layout.addWidget(scroll, 1)
        body.addWidget(inspector)
        body.setSizes([700, 400])
        outer.addWidget(body, 1)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save).setText("Apply to style.json")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self._refresh_variants()

    def _refresh_variants(self, selected=None):
        current = selected or (self.variant_picker.currentData() if hasattr(self, "variant_picker") else "default")
        variants = self.style_values.get("variants", {})
        self.variant_picker.blockSignals(True)
        self.variant_picker.clear()
        self.variant_picker.addItem("Base creator style", "default")
        if isinstance(variants, dict):
            for name, value in variants.items():
                if isinstance(name, str):
                    label = value.get("label", name.replace("_", " ").title()) if isinstance(value, dict) else name
                    self.variant_picker.addItem(str(label), name)
        index = self.variant_picker.findData(current)
        self.variant_picker.setCurrentIndex(max(0, index))
        self.variant_picker.blockSignals(False)

    def _effective_style(self):
        return apply_style_variant(self.style_values, self.variant_picker.currentData() or "default")

    def _variant_path(self, path):
        variant = self.variant_picker.currentData() or "default"
        return path if variant == "default" else ("variants", variant, *path)

    def _variant_changed(self, *_args):
        self._rebuild_form()
        self._refresh_preview()

    def _add_variant(self):
        name, accepted = QtWidgets.QInputDialog.getText(self, "New theme variant", "Variant id:")
        if not accepted:
            return
        label = name.strip()
        key = "_".join(label.casefold().split())
        if not key:
            return
        variants = self.style_values.setdefault("variants", {})
        if key in variants:
            QtWidgets.QMessageBox.warning(self, "New theme variant", f"A variant named {key!r} already exists.")
            return
        variants[key] = {"label": label}
        self._refresh_variants(key)
        self._rebuild_form()
        self._refresh_preview()

    def _refresh_components(self, *_args):
        screen = self.screen_picker.currentData()
        components = SCREEN_COMPONENTS[self.screen_picker.currentText()][1]
        previous = self.component_picker.currentData()
        self.component_picker.blockSignals(True)
        self.component_picker.clear()
        for component in components:
            self.component_picker.addItem(ThemePreview._label(component), component)
        index = self.component_picker.findData(previous)
        self.component_picker.setCurrentIndex(max(0, index))
        self.component_picker.blockSignals(False)
        self._rebuild_form()
        self._refresh_preview()

    def _select_component(self, component):
        index = self.component_picker.findData(component)
        if index >= 0:
            self.component_picker.setCurrentIndex(index)

    def _select_component_from_picker(self, *_args):
        self._rebuild_form()
        self._refresh_preview()

    def _move_component(self, component, dx, dy):
        screen = self.screen_picker.currentData()
        if screen == "dialogue" and component == "speaker":
            return
        viewport = self.viewport_picker.currentData() or VIEWPORTS["Desktop 16:9"]
        layout_component = "textbox" if screen == "dialogue" and component == "dialogue_text" else component
        base_path = ("layouts", "screens", screen, "components", layout_component)
        base_path = self._responsive_path(base_path, screen, component)
        path = self._variant_path(base_path)
        effective_style = self._effective_style()
        layouts = effective_style.get("layouts", {})
        spec = component_layout(layouts, screen, layout_component, viewport)
        safe_bounds = safe_area_rect(layouts, viewport)
        anchor = str(spec.get("anchor", "top_left")).replace("-", "_").casefold()
        horizontal, vertical = {
            "top_left": ("left", "top"), "top_center": ("center", "top"), "top_right": ("right", "top"),
            "center_left": ("left", "center"), "center": ("center", "center"), "center_right": ("right", "center"),
            "bottom_left": ("left", "bottom"), "bottom_center": ("center", "bottom"), "bottom_right": ("right", "bottom"),
            "top": ("center", "top"), "bottom": ("center", "bottom"), "left": ("left", "center"), "right": ("right", "center"),
        }.get(anchor, ("left", "top"))

        def pixel_offset(value, extent):
            if isinstance(value, str) and value.strip().endswith("%"):
                try:
                    return float(value.strip()[:-1]) * extent / 100
                except ValueError:
                    return 0
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0

        current_x = spec.get("x", spec.get("right" if horizontal == "right" else "left", 0))
        current_y = spec.get("y", spec.get("bottom" if vertical == "bottom" else "top", 0))
        x = round(pixel_offset(current_x, safe_bounds[2]) + (-dx if horizontal == "right" else dx))
        y = round(pixel_offset(current_y, safe_bounds[3]) + (-dy if vertical == "bottom" else dy))
        _set_path(self.style_values, path + ("x",), x)
        _set_path(self.style_values, path + ("y",), y)
        parent = _get_path(self.style_values, path, {})
        if isinstance(parent, dict):
            for key in ("left", "right", "top", "bottom"):
                parent.pop(key, None)
        self._rebuild_form()
        self._refresh_preview()

    def _viewport_changed(self, *_args):
        self._rebuild_form()
        self._refresh_preview()

    def _current(self):
        return self.screen_picker.currentData(), self.component_picker.currentData()

    def _rebuild_form(self):
        while self.form_layout.rowCount():
            self.form_layout.removeRow(0)
        self._fields.clear()
        screen, component = self._current()
        if not component:
            return
        screen_name = screen
        layout_component = "textbox" if screen_name == "dialogue" and component == "dialogue_text" else component
        effective_style = self._effective_style()
        layout_spec = component_layout(effective_style.get("layouts", {}), screen_name, layout_component, self.viewport_picker.currentData() or VIEWPORTS["Desktop 16:9"])
        component_map = {"dialogue": "textbox" if component == "textbox" else component,
                         "menu": "menu", "history": "history", "save_slots": "save_slots", "overlays": "overlays"}
        owner = component_map.get(screen_name, "overlays")
        component_path = ("components", owner)
        properties = []
        layout_component_enabled = component not in {"dialogue_text", "speaker"}
        button_component = component in {"choices", "controls", "pause_control", "items", "actions"}
        if layout_component_enabled:
            properties.extend([
                ("Anchor", "anchor", "combo", ["top_left", "top_center", "top_right", "center_left", "center", "center_right", "bottom_left", "bottom_center", "bottom_right"]),
                ("X / left", "x", "text", None), ("Y / top", "y", "text", None),
                ("Width", "width", "text", None), ("Height", "height", "text", None),
                ("Constraints (JSON)", "constraints_json", "text", None),
            ])
        if component in {"choices", "items", "actions"}:
            properties.extend([
                ("Layout", "type", "combo", ["flex", "grid"]),
                ("Direction", "direction", "combo", ["row", "column"]),
                ("Columns", "columns", "int", None), ("Gap", "gap", "int", None),
                ("Item size", "item_size", "int", None),
            ])
        if screen_name == "dialogue" and component in {"dialogue_text", "speaker"}:
            properties.extend([
                ("Font size", "font_size", "int", None), ("Font asset", "font", "text", None),
                ("Left margin", "margin_left", "int", None), ("Top margin", "margin_top", "int", None),
            ])
            if component == "dialogue_text":
                properties.append(("Line gap", "line_gap", "int", None))
        elif component in {"choices", "controls", "items", "actions"} or screen_name == "history":
            properties.extend([("Font size", "font_size", "int", None), ("Font asset", "font", "text", None)])
        elif component == "title":
            properties.extend([("Font size", "font_size", "int", None), ("Font asset", "font", "text", None),
                               ("Title alignment", "title_alignment", "combo", ["left", "center", "right"])])
        if button_component or component in {"textbox", "panel", "confirmation", "story_input", "variable_inspector"}:
            properties.extend([
                ("Label alignment", "label_alignment", "combo", ["left", "center", "right"]),
                ("Padding", "padding", "int", None), ("Corner radius", "radius", "int", None),
                ("Border width", "border_width", "int", None), ("Opacity", "opacity", "float", None),
                ("Image fit", "fit", "combo", ["stretch", "contain", "cover"]),
                ("Nine-slice", "nine_slice", "text", None),
            ])
        if component in {"textbox", "panel", "pause_control"}:
            properties.append(("Image asset", "image_path", "asset", None))
        for label, key, kind, choices in properties:
            if key in {"font_size", "font", "line_gap", "margin_left", "margin_top"}:
                base_path = self._typography_path(screen_name, component, key)
            elif key == "image_path":
                base_path = self._image_path(screen_name, component)
            elif key == "constraints_json":
                base_path = _style_path(screen_name, component, "constraints")
            else:
                base_path = _style_path(screen_name, component, key)
            base_path = self._responsive_path(base_path, screen_name, component)
            path = self._variant_path(base_path)
            if key in {"anchor", "x", "y", "width", "height", "type", "direction", "columns", "gap", "item_size", "layout_padding"}:
                value = layout_spec.get(key)
            elif key == "constraints_json":
                value = json.dumps(layout_spec.get("constraints", {}), ensure_ascii=False)
            else:
                value = _get_path(effective_style, base_path, None)
            if value is None:
                if key == "anchor": value = "center"
                elif key in {"type", "direction", "fit"}: value = {"type": "flex", "direction": "column", "fit": "stretch"}[key]
                elif key in {"width", "height"}: value = "80%"
                elif key == "columns": value = 2
                elif key == "opacity": value = 1.0
                elif key == "font_size": value = 20
                elif key == "font": value = "standard.ttf"
                elif key == "label_alignment": value = "center"
                elif key == "constraints_json": value = "{}"
                elif key == "nine_slice": value = ""
                else: value = 0
            widget = self._make_asset_field(path, value) if kind == "asset" else self._make_field(kind, choices, value)
            self.form_layout.addRow(label, widget)
            if kind != "asset":
                self._fields[key] = (widget, path, kind)
        primary_path = self._variant_path(self._primary_color_path(screen_name, component))
        text_path = self._variant_path(self._text_color_path(screen_name, component))
        self._add_color_field("Title color" if component == "title" else "Primary color", primary_path)
        if component != "title":
            self._add_color_field("Text color", text_path)
        if component in {"choices", "controls", "pause_control", "items", "actions"}:
            self._add_state_editor(screen_name, component)

    def _component_owner(self, screen, component):
        return {"dialogue": "dialogue_controls" if component == "controls" else component,
                "menu": "menu", "history": "history", "save_slots": "save_slots", "overlays": "overlays"}.get(screen, component)

    @staticmethod
    def _image_path(screen, component):
        if screen == "dialogue" and component == "textbox":
            return ("components", "textbox", "background_image")
        if screen == "dialogue" and component == "pause_control":
            return ("components", "pause_control", "image")
        if screen == "menu" and component == "panel":
            return ("components", "menu", "background_image")
        return ("components", "overlays", "background_image")

    def _make_asset_field(self, path, value):
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QtWidgets.QLineEdit(str(value or ""))
        edit.editingFinished.connect(lambda: (_set_path(self.style_values, path, edit.text().strip() or None), self._refresh_preview()))
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(lambda: self._choose_asset(edit, path))
        layout.addWidget(edit, 1)
        layout.addWidget(browse)
        return row

    def _choose_asset(self, edit, path):
        start = self.project_root / "assets" / "images" if self.project_root else Path.cwd()
        selected, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose a project image", str(start), "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if not selected:
            return
        image_path = Path(selected).resolve()
        if self.project_root:
            try:
                value = image_path.relative_to(self.project_root / "assets").as_posix()
            except ValueError:
                QtWidgets.QMessageBox.warning(self, "Theme image", "Choose an image inside this project's assets folder.")
                return
        else:
            value = image_path.name
        edit.setText(value)
        _set_path(self.style_values, path, value)
        self._refresh_preview()

    def _add_state_editor(self, screen, component):
        owner = self._component_owner(screen, component)
        state_name = self.state_picker.currentText() or "normal"
        base_path = self._variant_path(("components", owner, "states", state_name))
        state = _get_path(self._effective_style(), base_path[2:] if base_path[:1] == ("variants",) else base_path, {})
        state = state if isinstance(state, dict) else {}
        color = state.get("color", [45, 50, 65])
        if not isinstance(color, list) or len(color) < 3:
            color = [45, 50, 65]
        color_button = QtWidgets.QPushButton(QtGui.QColor(*color[:3]).name())
        qcolor = QtGui.QColor(*color[:3])
        color_button.setStyleSheet(f"background: {qcolor.name()}; color: {'#000' if qcolor.lightness() > 128 else '#fff'}")
        def choose_color():
            selected = QtWidgets.QColorDialog.getColor(qcolor, self, f"Choose {state_name} color")
            if selected.isValid():
                value = [selected.red(), selected.green(), selected.blue()]
                if len(color) > 3:
                    value.append(color[3])
                _set_path(self.style_values, base_path + ("color",), value)
                self._refresh_preview()
                self._rebuild_form()
        color_button.clicked.connect(choose_color)
        self.form_layout.addRow("State color", color_button)

        image_row = QtWidgets.QWidget()
        image_layout = QtWidgets.QHBoxLayout(image_row)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_edit = QtWidgets.QLineEdit(str(state.get("image") or ""))
        image_edit.editingFinished.connect(lambda: (_set_path(self.style_values, base_path + ("image",), image_edit.text().strip() or None), self._refresh_preview()))
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse_state_image(image_edit, base_path))
        image_layout.addWidget(image_edit, 1)
        image_layout.addWidget(browse)
        self.form_layout.addRow("State image", image_row)
        opacity = self._make_field("float", None, state.get("opacity", 1.0))
        opacity.valueChanged.connect(lambda value: _set_path(self.style_values, base_path + ("opacity",), value))
        self.form_layout.addRow("State opacity", opacity)

    def _browse_state_image(self, field, base_path):
        start = self.project_root / "assets" / "images" if self.project_root else Path.cwd()
        selected, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose a button image", str(start), "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if not selected:
            return
        image_path = Path(selected).resolve()
        if self.project_root:
            try:
                relative = image_path.relative_to(self.project_root / "assets")
            except ValueError:
                QtWidgets.QMessageBox.warning(self, "Theme image", "Choose an image inside this project's assets folder.")
                return
            value = relative.as_posix()
        else:
            value = image_path.name
        field.setText(value)
        _set_path(self.style_values, base_path + ("image",), value)
        self._refresh_preview()

    def _state_changed(self, *_args):
        self.preview.selected_state = self.state_picker.currentText()
        self._rebuild_form()
        self._refresh_preview()

    @staticmethod
    def _typography_path(screen, component, key):
        if component == "title":
            return ("components", "menu", "title_" + key)
        if screen == "dialogue" and component == "dialogue_text":
            return ("components", "dialogue_text", "text", key)
        if screen == "dialogue" and component == "speaker":
            return ("components", "dialogue_text", "speaker", key)
        if screen == "dialogue" and component == "textbox":
            return ("components", "dialogue_text", "text", key)
        if screen == "dialogue" and component == "choices":
            return ("components", "choices", key)
        if screen == "dialogue" and component == "controls":
            return ("components", "dialogue_controls", key)
        if screen == "menu" and component == "items":
            return ("components", "menu", "item_" + key)
        if screen == "history":
            return ("components", "history", key)
        if screen == "save_slots":
            return ("components", "save_slots", key)
        return ("components", "overlays", "body_font_size" if key == "font_size" else key)

    @staticmethod
    def _primary_color_path(screen, component):
        if component == "title":
            return ("components", "menu", "title_color")
        if screen == "dialogue" and component == "textbox":
            return ("components", "textbox", "background_color")
        if screen == "dialogue" and component == "speaker":
            return ("components", "dialogue_text", "speaker", "color")
        if screen == "dialogue" and component == "dialogue_text":
            return ("components", "dialogue_text", "text", "color")
        if screen == "dialogue" and component in {"choices", "controls"}:
            owner = "choices" if component == "choices" else "dialogue_controls"
            return ("components", owner, "states", "normal", "color")
        if screen == "menu" and component == "items":
            return ("components", "menu", "states", "normal", "color")
        if screen == "save_slots" and component == "items":
            return ("components", "save_slots", "normal_color")
        if component == "actions":
            owner = "save_slots" if screen == "save_slots" else "overlays"
            return ("components", owner, "states", "normal", "color")
        owner = "history" if screen == "history" else "menu" if component == "panel" and screen == "menu" else "overlays"
        return ("components", owner, "panel_color")

    @staticmethod
    def _text_color_path(screen, component):
        if component == "title":
            return ("components", "menu", "title_color")
        if screen == "dialogue" and component == "speaker":
            return ("components", "dialogue_text", "speaker", "color")
        if screen == "dialogue" and component in {"textbox", "dialogue_text"}:
            return ("components", "dialogue_text", "text", "color")
        if screen == "dialogue" and component in {"choices", "controls"}:
            owner = "choices" if component == "choices" else "dialogue_controls"
            return ("components", owner, "text_color")
        if screen == "menu":
            return ("components", "menu", "item_color")
        if screen == "history":
            return ("components", "history", "text_color")
        if screen == "save_slots":
            return ("components", "save_slots", "text_color")
        return ("components", "overlays", "text_color")

    def _make_field(self, kind, choices, value):
        if kind == "combo":
            widget = QtWidgets.QComboBox()
            widget.addItems(choices)
            index = widget.findText(str(value))
            widget.setCurrentIndex(max(0, index))
            widget.currentTextChanged.connect(lambda _value: self._commit_fields())
            return widget
        if kind == "int":
            widget = QtWidgets.QSpinBox()
            widget.setRange(0, 10000)
            widget.setValue(int(value) if isinstance(value, (int, float)) else 0)
            widget.valueChanged.connect(self._commit_fields)
            return widget
        if kind == "float":
            widget = QtWidgets.QDoubleSpinBox()
            widget.setRange(0, 1)
            widget.setSingleStep(0.05)
            widget.setValue(float(value))
            widget.valueChanged.connect(self._commit_fields)
            return widget
        widget = QtWidgets.QLineEdit(str(value))
        widget.editingFinished.connect(self._commit_fields)
        return widget

    def _add_color_field(self, label, path):
        effective_path = path[2:] if path[:1] == ("variants",) else path
        value = _get_path(self._effective_style(), effective_path, [45, 50, 65])
        if not isinstance(value, list) or len(value) < 3:
            value = [45, 50, 65]
        color = QtGui.QColor(*value[:3])
        button = QtWidgets.QPushButton(color.name())
        button.setStyleSheet(f"background: {color.name()}; color: {'#000' if color.lightness() > 128 else '#fff'}")
        def choose():
            selected = QtWidgets.QColorDialog.getColor(color, self, f"Choose {label.casefold()}")
            if not selected.isValid():
                return
            chosen = [selected.red(), selected.green(), selected.blue()]
            if len(value) > 3:
                chosen.append(value[3])
            _set_path(self.style_values, path, chosen)
            self._rebuild_form()
            self._refresh_preview()
        button.clicked.connect(choose)
        self.form_layout.addRow(label, button)

    def _commit_fields(self, *_args):
        if self._updating:
            return
        for key, (widget, path, kind) in self._fields.items():
            if isinstance(widget, QtWidgets.QComboBox):
                value = widget.currentText()
            elif isinstance(widget, QtWidgets.QSpinBox):
                value = widget.value()
            elif isinstance(widget, QtWidgets.QDoubleSpinBox):
                value = widget.value()
            else:
                value = widget.text()
                if key == "nine_slice":
                    if not value.strip():
                        value = None
                    else:
                        try:
                            value = json.loads(value)
                        except json.JSONDecodeError:
                            try:
                                value = int(value)
                            except ValueError:
                                continue
                elif key == "constraints_json":
                    try:
                        value = json.loads(value)
                        if not isinstance(value, dict):
                            continue
                    except json.JSONDecodeError:
                        continue
                elif key in {"width", "height", "x", "y", "left", "right", "top", "bottom"}:
                    try:
                        if not value.strip().endswith("%"):
                            value = float(value) if "." in value else int(value)
                    except ValueError:
                        continue
                elif kind == "int":
                    try: value = int(value)
                    except ValueError: continue
            _set_path(self.style_values, path, value)
        self._refresh_preview()

    def _responsive_path(self, path, screen, component):
        if path[:2] != ("layouts", "screens"):
            return path
        viewport = self.viewport_picker.currentData() or VIEWPORTS["Desktop 16:9"]
        layouts = self._effective_style().get("layouts", {})
        profile = select_profile(layouts, viewport)
        profiles = layouts.get("profiles", [])
        if profile is None or not isinstance(profiles, list):
            return path
        index = next((i for i, value in enumerate(profiles) if value is profile), None)
        if index is None:
            return path
        layout_component = "textbox" if screen == "dialogue" and component == "dialogue_text" else component
        return ("layouts", "profiles", index, "screens", screen, "components", layout_component, *path[5:])

    def _refresh_preview(self, *_args):
        if not hasattr(self, "preview"):
            return
        screen = self.screen_picker.currentData()
        viewport = self.viewport_picker.currentData() or VIEWPORTS["Desktop 16:9"]
        component = self.component_picker.currentData() or SCREEN_COMPONENTS[self.screen_picker.currentText()][1][0]
        self.preview.set_preview(self._effective_style(), screen, viewport, component, self.state_picker.currentText())
