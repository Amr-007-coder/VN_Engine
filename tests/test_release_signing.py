import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from export_pipeline import (
    _android_signing_environment,
    _configure_android_release_signing,
    _sign_macos_export,
    _sign_windows_executable,
)


class ReleaseSigningTests(unittest.TestCase):
    def test_android_signing_requires_a_keystore_and_keeps_passwords_in_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            keystore = root / "release.keystore"
            keystore.write_bytes(b"keystore")
            environment = {
                "VN_ANDROID_KEYSTORE": str(keystore),
                "VN_ANDROID_KEY_ALIAS": "release",
                "VN_ANDROID_STORE_PASSWORD": "store-secret",
            }
            signing = _android_signing_environment(environment)
            self.assertEqual(signing["key_password"], "store-secret")

            gradle = root / "build.gradle"
            gradle.write_text("android { }\n", encoding="utf-8")
            with patch.dict(os.environ, environment, clear=True):
                _configure_android_release_signing(gradle)
            contents = gradle.read_text(encoding="utf-8")
            self.assertIn("System.getenv('VN_ANDROID_KEYSTORE')", contents)
            self.assertNotIn("store-secret", contents)

    def test_windows_signing_uses_signtool_and_certificate_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            certificate = root / "release.pfx"
            certificate.write_bytes(b"certificate")
            executable = root / "game.exe"
            executable.write_bytes(b"exe")
            environment = {
                "VN_WINDOWS_SIGN_CERT": str(certificate),
                "VN_WINDOWS_SIGN_PASSWORD": "secret",
            }
            with patch.dict(os.environ, environment, clear=True), \
                    patch("export_pipeline.shutil.which", return_value="signtool.exe"), \
                    patch("export_pipeline.subprocess.run") as run:
                _sign_windows_executable(executable)

            command = run.call_args.args[0]
            self.assertEqual(command[0:2], ["signtool.exe", "sign"])
            self.assertIn("secret", command)
            self.assertEqual(command[-1], str(executable))

    def test_macos_signing_repackages_the_signed_app_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "game.zip"
            with ZipFile(output, "w") as archive:
                archive.writestr("Game.app/Contents/MacOS/Runner", b"binary")
            with patch.dict(os.environ, {"VN_MACOS_SIGN_IDENTITY": "Developer ID Application: Test"}, clear=True), \
                    patch("export_pipeline.shutil.which", return_value="codesign"), \
                    patch("export_pipeline.subprocess.run") as run:
                _sign_macos_export(output, "Game")

            self.assertEqual(run.call_count, 2)
            with ZipFile(output) as archive:
                self.assertEqual(archive.read("Game.app/Contents/MacOS/Runner"), b"binary")


if __name__ == "__main__":
    unittest.main()
