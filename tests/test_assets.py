import importlib.util
import json
from pathlib import Path
import sys
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "import_icons.py"
SPEC = importlib.util.spec_from_file_location("arknights_icon_import", SCRIPT)
IMPORTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = IMPORTER
SPEC.loader.exec_module(IMPORTER)


class IconAssetTests(unittest.TestCase):
    def test_url_encoded_source_names_decode_deterministically(self):
        self.assertEqual(
            IMPORTER.decode_asset_name("90px-Ch%27en_icon.png"),
            ("operator", "Ch'en"),
        )
        self.assertEqual(
            IMPORTER.decode_asset_name("90px-Wi%C5%A1%27adel_icon.png"),
            ("operator", "Wiš'adel"),
        )
        self.assertEqual(
            IMPORTER.decode_asset_name("47px-Defender.png"),
            ("class", "Defender"),
        )
        with self.assertRaisesRegex(ValueError, "malformed URL escape"):
            IMPORTER.decode_asset_name("90px-Bad%2_icon.png")

    def test_manifest_and_canonical_assets_cover_catalog_exactly(self):
        IMPORTER.check_canonical()
        catalog = json.loads((ROOT / "arknights_is" / "catalog.json").read_text(encoding="utf8"))
        manifest = json.loads(
            (ROOT / "arknights_is" / "portrait_sources.json").read_text(encoding="utf8")
        )
        self.assertTrue(manifest["assets_bundled"])
        self.assertTrue(manifest["locked_assets_bundled"])
        self.assertEqual([entry["name"] for entry in manifest["operators"]], catalog["operators"])
        self.assertEqual(len(manifest["operators"]), 137)
        self.assertEqual(len(manifest["classes"]), 8)

    def test_locked_portraits_are_deterministic_precomputed_grayscale_pngs(self):
        original = (ROOT / "arknights_is" / "assets" / "operators" / "000.png").read_bytes()
        locked = (
            ROOT / "arknights_is" / "assets" / "operators_locked" / "000.png"
        ).read_bytes()
        self.assertNotEqual(original, locked)
        self.assertEqual(IMPORTER.grayscale_png(original, "000.png"), locked)
        self.assertEqual(IMPORTER.png_dimensions(locked, "locked 000.png"), (90, 90))

    def test_built_archive_contains_every_manifest_asset_when_present(self):
        archive = ROOT / "dist" / "arknights_integrated_strategies.apworld"
        if not archive.exists():
            self.skipTest("build artifact not present")
        manifest = json.loads(
            (ROOT / "arknights_is" / "portrait_sources.json").read_text(encoding="utf8")
        )
        prefix = "arknights_integrated_strategies/assets"
        expected = {
            *(f"{prefix}/operators/{entry['filename']}" for entry in manifest["operators"]),
            *(
                f"{prefix}/operators_locked/{entry['locked_filename']}"
                for entry in manifest["operators"]
            ),
            *(f"{prefix}/classes/{entry['filename']}" for entry in manifest["classes"]),
        }
        with ZipFile(archive) as bundle:
            names = set(bundle.namelist())
        self.assertTrue(expected <= names)
        self.assertIn(
            "arknights_integrated_strategies/RecognitionHelper.py",
            names,
        )

    def test_manifest_and_runtime_world_versions_match(self):
        metadata = json.loads((ROOT / "archipelago.json").read_text(encoding="utf8"))
        source = (ROOT / "arknights_is" / "__init__.py").read_text(encoding="utf8")
        self.assertIn(f'WORLD_VERSION = "{metadata["world_version"]}"', source)


if __name__ == "__main__":
    unittest.main()
