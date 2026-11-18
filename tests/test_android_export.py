import gzip
from io import BytesIO
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pygame

from engine.icon_utils import install_android_launcher_icons
from engine.project import ProjectConfig
from export_pipeline import (
    _add_status_bar_hide_script,
    _android_export_settings,
    _enable_android_fullscreen,
    _extract_web_site,
    _prepare_android_web_site,
    _set_android_orientation,
)


class AndroidExportTests(unittest.TestCase):
    def test_android_project_defaults_and_settings(self):
        project = ProjectConfig()

        self.assertEqual(
            _android_export_settings(project.values),
            ("VN Engine", "com.example.vnengine", "landscape"),
        )

        project = ProjectConfig({
            "android": {
                "app_name": "Moonlight",
                "app_id": "com.example.moonlight",
                "orientation": "portrait",
            }
        })
        self.assertEqual(
            _android_export_settings(project.values),
            ("Moonlight", "com.example.moonlight", "portrait"),
        )

    def test_android_project_rejects_invalid_package_identifier(self):
        with self.assertRaisesRegex(ValueError, "android.app_id"):
            ProjectConfig({"android": {"app_id": "com.example.1game"}})

    def test_manifest_orientation_and_project_launcher_icon_are_applied(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "AndroidManifest.xml"
            manifest.write_text(
                '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
                '<application><activity android:name=".MainActivity" /></application></manifest>',
                encoding="utf-8",
            )
            _set_android_orientation(manifest, "portrait")
            self.assertIn('android:screenOrientation="portrait"', manifest.read_text(encoding="utf-8"))

            source_icon = root / "project-icon.png"
            surface = pygame.Surface((32, 32), pygame.SRCALPHA, 32)
            surface.fill((10, 20, 30, 255))
            pygame.image.save(surface, str(source_icon))
            resources = root / "res"
            install_android_launcher_icons(source_icon, resources)
            launcher = pygame.image.load(str(resources / "mipmap-mdpi" / "ic_launcher.png"))
            foreground = pygame.image.load(
                str(resources / "mipmap-mdpi" / "ic_launcher_foreground.png")
            )
            self.assertEqual(launcher.get_size(), (48, 48))
            self.assertEqual(foreground.get_size(), (96, 96))
            self.assertEqual(foreground.get_at((0, 0)).a, 0)

    def test_status_bar_hide_script_is_bundled_into_web_page(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            web_directory = root / "www"
            web_directory.mkdir()
            (web_directory / "index.html").write_text(
                "<html><body></body></html>",
                encoding="utf-8",
            )
            with patch("export_pipeline._run_android_command") as run_command:
                _add_status_bar_hide_script(web_directory, root, "npx")

            entry = (root / "vn-statusbar-entry.js").read_text(encoding="utf-8")
            page = (web_directory / "index.html").read_text(encoding="utf-8")
            self.assertIn("StatusBar.hide()", entry)
            self.assertIn("window.addEventListener('load'", entry)
            self.assertIn('<script src="./vn-statusbar.js"></script>', page)
            run_command.assert_called_once()

    def test_web_archive_extraction_rejects_parent_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "site.zip"
            with ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", "unsafe")

            with self.assertRaisesRegex(ValueError, "unsafe path"):
                _extract_web_site(archive_path, root / "www")

    def test_android_web_site_uses_uncompressed_runtime_and_keeps_loader_visible(self):
        with tempfile.TemporaryDirectory() as temporary:
            web_directory = Path(temporary) / "www"
            web_directory.mkdir()
            tar_contents = BytesIO()
            with tarfile.open(fileobj=tar_contents, mode="w") as archive:
                contents = b"story data"
                item = tarfile.TarInfo("assets/story.yaml")
                item.size = len(contents)
                archive.addfile(item, BytesIO(contents))
                main_source = (
                    "import asyncio\n"
                    "import pygame\n"
                    "import pygame.surface\n"
                    "from engine.engine import Engine\n"
                    "from engine.project import ProjectConfig\n"
                    "project = ProjectConfig.load()\n"
                    "engine = Engine(project_config=project)\n"
                    "engine.initialize()\n"
                )
                main_item = tarfile.TarInfo("assets/main.py")
                main_contents = main_source.encode("utf-8")
                main_item.size = len(main_contents)
                archive.addfile(main_item, BytesIO(main_contents))
                engine_source = (
                    "import pygame\n"
                    "ANDROID_WEBVIEW_HOOK_VERSION = 1\n"
                    "class Engine:\n"
                    "    def initialize(self):\n"
                    '        flags = pygame.FULLSCREEN if self.settings.values["fullscreen"] else 0\n'
                    "        self.screen = pygame.display.set_mode(self.windowed_size, flags)\n"
                    "    def apply_display_settings(self):\n"
                    '        flags = pygame.FULLSCREEN if self.settings.values["fullscreen"] else 0\n'
                    "        self.screen = pygame.display.set_mode(self.windowed_size, flags)\n"
                )
                engine_item = tarfile.TarInfo("assets/engine/engine.py")
                engine_contents = engine_source.encode("utf-8")
                engine_item.size = len(engine_contents)
                archive.addfile(engine_item, BytesIO(engine_contents))
                hook_source = b"def configure_webview_viewport(project, platform): return None\n"
                hook_item = tarfile.TarInfo("assets/engine/platform_runtime.py")
                hook_item.size = len(hook_source)
                archive.addfile(hook_item, BytesIO(hook_source))
            (web_directory / "vn-engine-web.tar.gz").write_bytes(gzip.compress(tar_contents.getvalue()))
            index_path = web_directory / "index.html"
            index_path.write_text(
                '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
                '<canvas class="emscripten" id="canvas"\n'
                'width="1px"\n'
                'height="1px"></canvas>\n'
                'gui_divider : 4,\n'
                'fb_ar : 1.0,\n'
                'fb_width : "1",\n'
                'fb_height : "1",\n'
                '    platform.window.transfer.hidden = true\n'
                '        transfer.hidden = debug_hidden\n'
                "    platform.fopen ( 'vn-engine-web.tar.gz' , 'rb' )\n"
                "    tarfile.open ( fileobj = archive , mode = 'r:gz' )\n"
                '    await shell.source(main, callback=ui_callback)\n'
                '    platform.window.infobox.style.display = "none"',
                encoding="utf-8",
            )

            _prepare_android_web_site(web_directory, (1920, 1200))

            with tarfile.open(web_directory / "vn-engine-web.tar", mode="r:") as archive:
                self.assertEqual(archive.extractfile("assets/story.yaml").read(), b"story data")
                main_source = archive.extractfile("assets/main.py").read().decode("utf-8")
                engine_source = archive.extractfile("assets/engine/engine.py").read().decode("utf-8")
            self.assertFalse((web_directory / "vn-engine-web.tar.gz").exists())
            compile(main_source, "assets/main.py", "exec")
            compile(engine_source, "assets/engine/engine.py", "exec")
            self.assertIn("ANDROID_WEBVIEW_HOOK_VERSION = 1", engine_source)
            self.assertIn("engine = Engine(project_config=project)", main_source)
            self.assertNotIn("platform.window.innerWidth", main_source)
            self.assertEqual(engine_source.count('pygame.FULLSCREEN if self.settings.values["fullscreen"] else 0'), 2)
            page = index_path.read_text(encoding="utf-8")
            self.assertIn('platform.fopen("vn-engine-web.tar", "rb")', page)
            self.assertIn('mode="r:"', page)
            self.assertNotIn("transfer.hidden = debug_hidden", page)
            self.assertRegex(page, r'id="canvas"\s+width="1920"\s+height="1200"')
            self.assertGreater(
                page.index("platform.window.transfer.hidden = true"),
                page.index("await shell.source(main, callback=ui_callback)"),
            )

    def test_android_main_activity_hides_system_bars(self):
        with tempfile.TemporaryDirectory() as temporary:
            android_directory = Path(temporary) / "android"
            source_directory = android_directory / "app" / "src" / "main" / "java"
            source_directory.mkdir(parents=True)
            activity_path = source_directory / "MainActivity.java"
            activity_path.write_text(
                "package com.example.vnengine;\n"
                "import com.getcapacitor.BridgeActivity;\n"
                "public class MainActivity extends BridgeActivity {}\n",
                encoding="utf-8",
            )

            _enable_android_fullscreen(android_directory)

            source = activity_path.read_text(encoding="utf-8")
            self.assertIn("WindowInsets.Type.navigationBars()", source)
            self.assertIn("WindowInsets.Type.statusBars()", source)
            self.assertIn("WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE", source)
            self.assertIn("View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY", source)


if __name__ == "__main__":
    unittest.main()
