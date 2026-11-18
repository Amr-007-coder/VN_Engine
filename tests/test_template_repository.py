import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from template_repository import Release, _download_template_asset, ensure_template


def _zip_bytes(filename: str, contents: bytes) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(filename, contents)
    return buffer.getvalue()


class TemplateRepositoryTests(unittest.TestCase):
    def test_download_accepts_direct_template_archive(self):
        template = _zip_bytes("index.html", b"<html></html>")
        asset = {
            "browser_download_url": "https://example.invalid/template-web.zip",
            "size": len(template),
            "digest": f"sha256:{hashlib.sha256(template).hexdigest()}",
        }

        with tempfile.TemporaryDirectory() as temporary, patch(
            "template_repository.urlopen", return_value=io.BytesIO(template)
        ):
            destination = Path(temporary) / "template-web.zip"
            _download_template_asset(asset, destination.name, destination)
            self.assertEqual(destination.read_bytes(), template)

    def test_download_unwraps_single_file_template_wrapper(self):
        template = _zip_bytes("index.html", b"<html></html>")
        wrapper = _zip_bytes("template-web.zip", template)
        asset = {
            "browser_download_url": "https://example.invalid/template-web.zip",
            "size": len(wrapper),
            "digest": f"sha256:{hashlib.sha256(wrapper).hexdigest()}",
        }

        with tempfile.TemporaryDirectory() as temporary, patch(
            "template_repository.urlopen", return_value=io.BytesIO(wrapper)
        ):
            destination = Path(temporary) / "template-web.zip"
            _download_template_asset(asset, destination.name, destination)
            self.assertEqual(destination.read_bytes(), template)

    def test_download_rejects_digest_mismatch(self):
        payload = _zip_bytes("index.html", b"<html></html>")
        asset = {
            "browser_download_url": "https://example.invalid/template-web.zip",
            "size": len(payload),
            "digest": "sha256:" + ("0" * 64),
        }

        with tempfile.TemporaryDirectory() as temporary, patch(
            "template_repository.urlopen", return_value=io.BytesIO(payload)
        ):
            destination = Path(temporary) / "template-web.zip"
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                _download_template_asset(asset, destination.name, destination)
            self.assertFalse(destination.exists())

    def test_selected_release_template_is_cached(self):
        template = _zip_bytes("index.html", b"<html></html>")
        release = Release(
            tag="v1.2.3",
            assets={"template-web.zip": {"browser_download_url": "https://example.invalid/template-web.zip"}},
        )

        def write_template(_asset, _name, destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(template)

        with tempfile.TemporaryDirectory() as temporary:
            with patch("template_repository._cache_root", return_value=Path(temporary)):
                with patch("template_repository._release_for_tag", return_value=release) as get_release:
                    with patch(
                        "template_repository._download_template_asset",
                        side_effect=write_template,
                    ) as download:
                        first = ensure_template("web", "v1.2.3")
                        second = ensure_template("web", "v1.2.3")
                        self.assertEqual(first, second)
                        get_release.assert_called_once_with("v1.2.3")
                        download.assert_called_once()


if __name__ == "__main__":
    unittest.main()
