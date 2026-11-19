import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from editor import VNEditorApp
from editor_qt import QtCore, Treeview, _WidgetMixin, ensure_application


class EditorAssetTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = ensure_application()

    def test_asset_tree_preserves_hidden_values_to_populate_hierarchy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root_path = Path(temporary)
            (root_path / "images").mkdir()
            (root_path / "images" / "scene.png").write_bytes(b"image")

            tree = Treeview(show="tree")
            root = tree.insert(
                "", "end", text="Project assets",
                values=("root", str(root_path), str(root_path)),
            )
            tree.insert(root, "end", text="", values=("placeholder", "", str(root_path)))

            app = object.__new__(VNEditorApp)
            app.asset_tree = tree
            app._populate_tree_node(root)

            self.assertEqual(tree.item(root, "values")[0], "root")
            children = tree.get_children(root)
            self.assertEqual(len(children), 1)
            folder = children[0]
            self.assertEqual(tree.item(folder)["text"], "images")
            self.assertEqual(tree.item(folder, "values")[0], "directory")
            app._populate_tree_node(folder)
            self.assertEqual(len(tree.get_children(folder)), 1)
            file_item = tree.get_children(folder)[0]
            self.assertEqual(tree.item(file_item)["text"], "scene.png")
            self.assertEqual(tree.item(file_item, "values")[0], "file")
            tree.close()

    def test_expanding_tree_nodes_loads_files_and_subfolders(self):
        with tempfile.TemporaryDirectory() as temporary:
            root_path = Path(temporary)
            nested = root_path / "images"
            nested.mkdir()
            (root_path / "root.png").write_bytes(b"image")
            (nested / "scene.png").write_bytes(b"image")

            tree = Treeview(show="tree")
            root = tree.insert(
                "", "end", text="Project assets",
                values=("root", str(root_path), str(root_path)),
            )
            tree.insert(root, "end", text="", values=("placeholder", "", str(root_path)))

            app = object.__new__(VNEditorApp)
            app.asset_tree = tree
            tree.bind("<<TreeviewOpen>>", app._on_tree_open)
            tree.expandItem(tree._item(root))

            children = tree.get_children(root)
            self.assertEqual(
                {tree.item(child)["text"] for child in children},
                {"images", "root.png"},
            )
            root_file = next(child for child in children if tree.item(child)["text"] == "root.png")
            folder = next(child for child in children if tree.item(child)["text"] == "images")
            tree.expandItem(tree._item(folder))
            self.assertEqual(
                tree.item(tree.get_children(folder)[0])["text"],
                "scene.png",
            )
            self.assertEqual(tree.item(root_file)["text"], "root.png")
            tree.close()

    def test_modified_virtual_event_notifies_editor_of_text_changes(self):
        class SignalSource(QtCore.QObject):
            textChanged = QtCore.Signal()

        source = SignalSource()
        events = []
        _WidgetMixin._bind_virtual(
            source, "<<Modified>>", lambda event: events.append(event.widget)
        )
        source.textChanged.emit()

        self.assertEqual(events, [source])


if __name__ == "__main__":
    unittest.main()
