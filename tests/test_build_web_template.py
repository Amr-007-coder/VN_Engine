import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from tools import build_web_template


class BuildWebTemplateTests(unittest.TestCase):
    def test_starter_project_uses_complete_default_theme(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_root = Path(temporary)
            build_web_template._write_starter_project(app_root)
            project = json.loads((app_root / "data" / "project.json").read_text(encoding="utf-8"))

        self.assertEqual(project["theme"]["menu"]["screens"]["main"]["grid"], None)
        self.assertEqual(project["theme"]["textbox"]["opacity"], 0.95)
        self.assertEqual(
            project["theme"]["pause_button"],
            {"image": None, "size": 78, "margin": 16},
        )

    def test_keeps_pygbag_gzip_runtime_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "template.zip"

            def create_fake_build(command, **_kwargs):
                web_root = Path(command[-1]) / "build" / "web"
                web_root.mkdir(parents=True)
                (web_root / "index.html").write_text(
                    '<script src="https://pygame-web.github.io/cdn/0.9.3//browserfs.min.js"></script>',
                    encoding="utf-8",
                )
                (web_root / "vn-engine-web.apk").write_bytes(b"apk")
                (web_root / "vn-engine-web.tar.gz").write_bytes(b"runtime")

            with (
                patch.object(build_web_template.importlib.util, "find_spec", return_value=object()),
                patch.object(build_web_template.shutil, "copytree"),
                patch.object(build_web_template, "_copy_python_package"),
                patch.object(build_web_template, "_convert_engine_audio"),
                patch.object(subprocess, "run", side_effect=create_fake_build),
            ):
                build_web_template.build_template(output)

            with ZipFile(output) as archive:
                self.assertEqual(archive.read("vn-engine-web.tar.gz"), b"runtime")
                index = archive.read("index.html").decode("utf-8")
                self.assertIn(build_web_template.BROWSERFS_SCRIPT_URL, index)
                self.assertNotIn(build_web_template.PYGBAG_BROWSERFS_SCRIPT_URL, index)


if __name__ == "__main__":
    unittest.main()
