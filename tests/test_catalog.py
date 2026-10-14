import hashlib
import json
import unittest
from pathlib import Path

catalog = json.loads(
    (Path(__file__).parents[1] / "arknights_is" / "catalog.json").read_text(encoding="utf8")
)


class CatalogTests(unittest.TestCase):
    def test_catalog_counts(self):
        self.assertEqual(len(catalog["operators"]), 137)
        self.assertEqual(sum(len(squads) for squads in catalog["squads"].values()), 72)
        self.assertEqual(
            [len(catalog["modes"][f"IS{i}"]["endings"]) for i in range(2, 7)],
            [4, 4, 4, 5, 5],
        )

    def test_legacy_operator_order_is_unchanged_and_extension_is_exact(self):
        legacy = catalog["operators"][:128]
        fingerprint = hashlib.sha256(("\n".join(legacy) + "\n").encode()).hexdigest()
        self.assertEqual(
            fingerprint,
            "3d0e54bd27b8b07d8cc9711dd3d6c818d4bf41c41ede3243a5a9f8ca30528e6f",
        )
        self.assertEqual(
            catalog["operators"][128:],
            [
                "Angelina the Mellow Wish",
                "Aphrissa",
                "Closure",
                "Kal'tsit - Esperanta",
                "Makoto Yuki",
                "Mechanist",
                "Thumpy",
                "Violet Mizutsune Orchid",
                "Viy",
            ],
        )

    def test_named_boss_catalogs_exist_for_all_boss_floors(self):
        for mode in (f"IS{i}" for i in range(2, 7)):
            for floor in (3, 5, 6):
                self.assertTrue(catalog["modes"][mode][f"f{floor}_bosses"])


if __name__ == "__main__":
    unittest.main()
