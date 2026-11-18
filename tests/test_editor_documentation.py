from pathlib import Path
import tempfile
import unittest

from editor import _editor_markdown_paths


class EditorDocumentationTests(unittest.TestCase):
    def test_only_packaged_editor_docs_are_listed(self):
        with tempfile.TemporaryDirectory() as temporary:
            editor_home = Path(temporary)
            docs = editor_home / "docs"
            docs.mkdir()
            (editor_home / "readme.md").write_text("Packaged readme\n", encoding="utf-8")
            (docs / "README.md").write_text("Source readme\n", encoding="utf-8")
            for name in (
                "guide_vn-engine.md",
                "project-config.md",
                "story-format.md",
                "releasing.md",
                "internal-notes.md",
            ):
                (docs / name).write_text(name, encoding="utf-8")

            paths = _editor_markdown_paths(editor_home)

            self.assertEqual(
                [path.name for path in paths],
                [
                    "readme.md",
                    "guide_vn-engine.md",
                    "project-config.md",
                    "story-format.md",
                ],
            )

    def test_source_tree_readme_is_used_when_no_packaged_readme_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            editor_home = Path(temporary)
            docs = editor_home / "docs"
            docs.mkdir()
            readme = docs / "README.md"
            readme.write_text("Source readme\n", encoding="utf-8")

            self.assertEqual(_editor_markdown_paths(editor_home), [readme.resolve()])


if __name__ == "__main__":
    unittest.main()
