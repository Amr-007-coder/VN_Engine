import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from engine.assets import AssetManager


def make_package(path: Path, package_id: str, asset_name: str = "hero.png"):
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"format_version": 1, "id": package_id, "name": package_id, "version": "1.0"}),
        )
        archive.writestr(f"assets/images/{asset_name}", b"mod image")


class ModManagementTests(unittest.TestCase):
    def test_package_conflicts_enablement_and_removal_are_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_assets = root / "assets"
            (project_assets / "images").mkdir(parents=True)
            (project_assets / "images" / "hero.png").write_bytes(b"project image")
            user_mods = root / "user_data" / "mods"
            user_mods.mkdir(parents=True)
            package_path = user_mods / "story-art.vnmod"
            make_package(package_path, "story-art")

            manager = AssetManager(project_assets, user_mods)
            package = manager.mod_packages()[0]
            self.assertEqual(package["id"], "story-art")
            self.assertEqual(package["version"], "1.0")
            self.assertEqual(package["conflicts"][0]["winner"], "project assets")

            manager.set_mod_enabled(package["key"], False)
            self.assertFalse(manager.mod_packages()[0]["enabled"])
            self.assertEqual(json.loads((root / "user_data" / "mods.json").read_text())[
                "disabled"
            ], [package["key"]])

            manager.remove_mod_package(package["key"])
            self.assertFalse(package_path.exists())
            self.assertEqual(manager.mod_packages(), [])

    def test_install_rejects_unsupported_manifest_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "broken.vnmod"
            with ZipFile(source, "w") as archive:
                archive.writestr("manifest.json", json.dumps({"format_version": 2, "id": "broken"}))
            manager = AssetManager(root / "assets", root / "user_data" / "mods")

            with self.assertRaisesRegex(ValueError, "unsupported manifest version"):
                manager.install_mod_package(source)


if __name__ == "__main__":
    unittest.main()
