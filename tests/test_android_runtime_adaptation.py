from io import BytesIO
import tarfile
import unittest

from export_pipeline import _adapt_android_runtime_archive


class AndroidRuntimeAdaptationTests(unittest.TestCase):
    def test_release_source_installs_webview_hook_sources_and_removes_bytecode(self):
        source_buffer = BytesIO()
        with tarfile.open(fileobj=source_buffer, mode="w") as archive:
            for name, contents in (
                ("assets/main.py", b"legacy entrypoint"),
                ("assets/engine/_web_main.pyc", b"legacy bytecode"),
                ("assets/engine/engine.pyc", b"legacy bytecode"),
                ("assets/engine/platform_runtime.pyc", b"legacy bytecode"),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(contents)
                archive.addfile(info, BytesIO(contents))

        main_source = (
            b"import asyncio\n"
            b"import pygame\n"
            b"import pygame.surface\n"
            b"engine = Engine(project_config=project)\n"
            b"engine.initialize()\n"
        )
        engine_source = b"ANDROID_WEBVIEW_HOOK_VERSION = 1\n"
        display_source = b"def configure_webview_viewport(project, platform): return (1, 1)\n"
        adapted = _adapt_android_runtime_archive(
            source_buffer.getvalue(),
            (main_source, engine_source, display_source),
        )

        with tarfile.open(fileobj=BytesIO(adapted), mode="r:") as archive:
            members = {member.name: member for member in archive.getmembers()}
            main_file = archive.extractfile(members["assets/main.py"])
            engine_file = archive.extractfile(members["assets/engine/engine.py"])
            self.assertIsNotNone(main_file)
            self.assertIsNotNone(engine_file)
            self.assertNotIn("assets/engine/_web_main.pyc", members)
            self.assertNotIn("assets/engine/engine.pyc", members)
            self.assertNotIn("assets/engine/platform_runtime.pyc", members)
            self.assertEqual(main_file.read(), main_source)
            self.assertEqual(engine_file.read(), engine_source)
            self.assertEqual(archive.extractfile("assets/engine/platform_runtime.py").read(), display_source)

    def test_unsupported_webview_hook_version_is_rejected(self):
        source_buffer = BytesIO()
        with tarfile.open(fileobj=source_buffer, mode="w") as archive:
            for name, contents in (
                ("assets/main.py", b"main = True\n"),
                ("assets/engine/engine.py", b"ANDROID_WEBVIEW_HOOK_VERSION = 2\n"),
                ("assets/engine/platform_runtime.py", b""),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(contents)
                archive.addfile(info, BytesIO(contents))

        with self.assertRaisesRegex(ValueError, "supports version 1"):
            _adapt_android_runtime_archive(source_buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
