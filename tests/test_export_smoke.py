from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import os
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from tools.smoke_export import smoke_android, smoke_desktop, smoke_web


class ExportSmokeTests(unittest.TestCase):
    def test_desktop_smoke_extracts_and_launches_the_exported_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "Demo-linux.zip"
            executable = ZipInfo("Demo/Demo")
            executable.create_system = 3
            executable.external_attr = 0o100755 << 16
            with ZipFile(artifact, "w", ZIP_DEFLATED) as archive:
                archive.writestr(executable, b"runtime")
            with patch("tools.smoke_export.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = ""
                smoke_desktop("linux", artifact)
            self.assertEqual(run.call_args.args[0][-1], "--validate")

    def test_web_smoke_checks_project_files_inside_nested_app_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "Demo-web.zip"
            app_buffer = BytesIO()
            with ZipFile(app_buffer, "w", ZIP_DEFLATED) as app:
                app.writestr("assets/data/project.json", '{"story":"story.yaml"}')
                app.writestr("assets/data/story.yaml", "title: Demo")
            with ZipFile(artifact, "w", ZIP_DEFLATED) as web:
                web.writestr("index.html", "<html></html>")
                web.writestr("app.apk", app_buffer.getvalue())

            smoke_web(artifact)

    def test_android_smoke_checks_apk_structure(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "Demo.apk"
            with ZipFile(artifact, "w", ZIP_DEFLATED) as apk:
                apk.writestr("AndroidManifest.xml", b"manifest")
                apk.writestr("classes.dex", b"dex")
            with patch.dict(os.environ, {"ANDROID_HOME": "", "ANDROID_SDK_ROOT": ""}), \
                    patch("tools.smoke_export.shutil.which", return_value=None):
                smoke_android(artifact, "com.example.demo")


if __name__ == "__main__":
    unittest.main()
