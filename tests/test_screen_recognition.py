import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "arknights_is" / "ScreenRecognition.py"
SPEC = importlib.util.spec_from_file_location("arknights_screen_recognition", MODULE_PATH)
RECOGNITION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RECOGNITION
SPEC.loader.exec_module(RECOGNITION)

CATALOG = json.loads((ROOT / "arknights_is" / "catalog.json").read_text(encoding="utf8"))


def make_location_ids():
    locations = {}
    code = 1
    for mode, data in CATALOG["modes"].items():
        for entry in data["normal"]:
            locations[f'{mode} — Floor {entry["floor"]}: {entry["name"]}'] = code
            code += 1
        for ending in data["endings"]:
            locations[f"{mode} — Ending: {ending}"] = code
            code += 1
        locations[f"{mode} — Any Ending Cleared"] = code
        code += 1
    return locations


LOCATIONS = make_location_ids()


@unittest.skipUnless(importlib.util.find_spec("PIL"), "requires Pillow")
class RecognitionUnitTests(unittest.TestCase):
    def make_image(self, directory, size=(1920, 1080), name="capture.png"):
        from PIL import Image

        path = Path(directory) / name
        Image.new("RGB", size, "black").save(path)
        return path

    def test_noisy_normal_title_maps_only_to_unresolved_location(self):
        with tempfile.TemporaryDirectory() as directory:
            image = self.make_image(directory)
            result = RECOGNITION.recognize_image(
                image,
                CATALOG,
                LOCATIONS,
                set(),
                ocr_runner=lambda _image, psm: (
                    "Bloodline Debates SCOTS" if psm == 13 else "not an ending"
                ),
            )
        self.assertEqual(result.kind, "operation")
        self.assertEqual(result.title, "Bloodline Debates")
        self.assertEqual(result.location_names, ("IS5 — Floor 3: Bloodline Debates",))
        self.assertGreaterEqual(result.score, RECOGNITION.MIN_SCORE)
        self.assertGreaterEqual(
            result.score - result.runner_up_score, RECOGNITION.MIN_MARGIN
        )

    def test_already_resolved_normal_stage_is_not_reassigned_to_another_location(self):
        location = "IS5 — Floor 3: Bloodline Debates"
        with tempfile.TemporaryDirectory() as directory:
            image = self.make_image(directory)
            with self.assertRaisesRegex(RECOGNITION.RecognitionError, "already resolved"):
                RECOGNITION.recognize_image(
                    image,
                    CATALOG,
                    LOCATIONS,
                    {LOCATIONS[location]},
                    ocr_runner=lambda _image, psm: (
                        "Bloodline Debates SCOTS" if psm == 13 else "not an ending"
                    ),
                )

    def test_in_memory_frame_supports_live_capture_without_saving(self):
        from PIL import Image

        frame = Image.new("RGB", (1920, 1080), "black")
        result = RECOGNITION.recognize_frame(
            frame,
            "live primary display",
            CATALOG,
            LOCATIONS,
            set(),
            ocr_runner=lambda _image, psm: (
                "Blotted Sky" if psm == 13 else "not an ending"
            ),
        )
        self.assertEqual(result.source, "live primary display")
        self.assertEqual(result.location_names, ("IS5 — Floor 3: Blotted Sky",))

    def test_ending_proposes_named_and_any_clear_but_no_boss_check(self):
        with tempfile.TemporaryDirectory() as directory:
            image = self.make_image(directory)
            result = RECOGNITION.recognize_image(
                image,
                CATALOG,
                LOCATIONS,
                set(),
                ocr_runner=lambda _image, _psm: (
                    "You, Doctor, used a squad\nWitnessed the Twin Crowns\nEnding description"
                ),
            )
        self.assertEqual(result.kind, "ending")
        self.assertEqual(result.title, "Twin Crowns")
        self.assertEqual(
            result.location_names,
            ("IS5 — Ending: Twin Crowns (ED2)", "IS5 — Any Ending Cleared"),
        )
        self.assertTrue(result.needs_ending_record)
        self.assertFalse(any("Dreadful Foe" in name for name in result.location_names))

    def test_ending_without_endingsanity_still_records_identity_for_mode_goal(self):
        active = {
            name: code for name, code in LOCATIONS.items() if " — Ending: " not in name
        }
        with tempfile.TemporaryDirectory() as directory:
            image = self.make_image(directory)
            result = RECOGNITION.recognize_image(
                image,
                CATALOG,
                active,
                set(),
                ocr_runner=lambda _image, _psm: "Witnessed the Twin Crowns",
            )
        self.assertEqual(result.location_names, ("IS5 — Any Ending Cleared",))
        self.assertEqual(result.ending_location, "IS5 — Ending: Twin Crowns (ED2)")
        self.assertTrue(result.needs_ending_record)

    def test_checked_ending_can_still_propose_local_completion_identity(self):
        ending = "IS5 — Ending: Twin Crowns (ED2)"
        any_ending = "IS5 — Any Ending Cleared"
        with tempfile.TemporaryDirectory() as directory:
            image = self.make_image(directory)
            result = RECOGNITION.recognize_image(
                image,
                CATALOG,
                LOCATIONS,
                {LOCATIONS[ending], LOCATIONS[any_ending]},
                ocr_runner=lambda _image, _psm: "Witnessed the Twin Crowns",
            )
        self.assertEqual(result.location_names, ())
        self.assertEqual(result.ending_location, ending)
        self.assertTrue(result.needs_ending_record)

    def test_ambiguous_or_wrong_size_image_fails_without_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            image = self.make_image(directory)
            with self.assertRaisesRegex(RECOGNITION.RecognitionError, "high-confidence"):
                RECOGNITION.recognize_image(
                    image,
                    CATALOG,
                    LOCATIONS,
                    set(),
                    ocr_runner=lambda _image, _psm: "unrelated unreadable text",
                )
            wrong = self.make_image(directory, (1280, 720), "wrong.png")
            with self.assertRaisesRegex(RECOGNITION.RecognitionError, "1920×1080"):
                RECOGNITION.recognize_image(
                    wrong,
                    CATALOG,
                    LOCATIONS,
                    set(),
                    ocr_runner=lambda _image, _psm: "anything",
                )

    def test_catalog_title_uniqueness_is_enforced(self):
        duplicate = json.loads(json.dumps(CATALOG))
        duplicate["modes"]["IS2"]["normal"][0]["name"] = duplicate["modes"]["IS3"]["normal"][0]["name"]
        with self.assertRaisesRegex(RECOGNITION.RecognitionError, "not unique"):
            RECOGNITION.validate_normal_stage_names(duplicate)

    def test_frozen_runtime_uses_external_pillow_helper_for_file_import(self):
        payload = {
            "source": "capture.png",
            "width": 1920,
            "height": 1080,
            "signature": "abc",
            "ending_ocr": "not an ending",
            "normal_ocr": "Blotted Sky",
        }
        with tempfile.TemporaryDirectory() as directory:
            image = self.make_image(directory)
            with (
                mock.patch.object(RECOGNITION, "_pillow_available", return_value=False),
                mock.patch.object(RECOGNITION, "capability_problem", return_value=None),
                mock.patch.object(RECOGNITION, "_run_external_helper", return_value=payload) as helper,
            ):
                result = RECOGNITION.recognize_image(image, CATALOG, LOCATIONS, set())
        helper.assert_called_once_with("file", image)
        self.assertEqual(result.location_names, ("IS5 — Floor 3: Blotted Sky",))

    def test_external_live_helper_skips_unchanged_capture_before_recognition(self):
        payload = {
            "source": "live primary display",
            "width": 1920,
            "height": 1080,
            "signature": "same",
            "unchanged": True,
        }
        with (
            mock.patch.object(RECOGNITION, "_pillow_available", return_value=False),
            mock.patch.object(RECOGNITION, "capture_capability_problem", return_value=None),
            mock.patch.object(RECOGNITION, "_run_external_helper", return_value=payload) as helper,
        ):
            signature, result = RECOGNITION.recognize_live_capture(
                CATALOG, LOCATIONS, set(), previous_signature="same"
            )
        helper.assert_called_once_with("live", "same")
        self.assertEqual(signature, "same")
        self.assertIsNone(result)

    def test_capability_accepts_external_pillow_and_standard_tesseract(self):
        with (
            mock.patch.object(RECOGNITION, "_pillow_available", return_value=False),
            mock.patch.object(RECOGNITION, "_external_helper_available", return_value=True),
            mock.patch.object(RECOGNITION, "_tesseract_executable", return_value="tesseract.exe"),
        ):
            self.assertIsNone(RECOGNITION.capability_problem())


@unittest.skipUnless(
    (ROOT / "imgrec").is_dir() and RECOGNITION.capability_problem() is None,
    "requires local imgrec fixtures, Pillow, and Tesseract",
)
class NativeCaptureEvidenceTests(unittest.TestCase):
    def test_all_supplied_native_captures_match_exact_expected_titles(self):
        expected = {
            "Arknights_1nLxEXeyOB.jpg": ("operation", "Bloodline Debates"),
            "Arknights_Qi279asY5r.jpg": ("operation", "Collapsals' Afternoon"),
            "Arknights_SABSRGge9l.jpg": ("operation", "Blotted Sky"),
            "Crimson_Finale.png": ("ending", "Crimson Finale"),
            "Precious_Days.jpg": ("ending", "Precious Days"),
            "Twin_Crowns.jpg": ("ending", "Twin Crowns"),
            "Orderly_Placation.jpg": ("ending", "Orderly Placation"),
        }
        for filename, identity in expected.items():
            with self.subTest(filename=filename):
                result = RECOGNITION.recognize_image(
                    ROOT / "imgrec" / filename, CATALOG, LOCATIONS, set()
                )
                self.assertEqual((result.kind, result.title), identity)
                self.assertGreaterEqual(result.score, RECOGNITION.MIN_SCORE)
                self.assertGreaterEqual(
                    result.score - result.runner_up_score,
                    RECOGNITION.MIN_MARGIN,
                )

    def test_external_helper_matches_a_native_capture(self):
        payload = RECOGNITION._run_external_helper(
            "file", ROOT / "imgrec" / "Arknights_SABSRGge9l.jpg"
        )
        result = RECOGNITION._recognize_ocr_texts(
            payload["source"],
            payload["width"],
            payload["height"],
            payload["ending_ocr"],
            payload["normal_ocr"],
            CATALOG,
            LOCATIONS,
            set(),
        )
        self.assertEqual((result.kind, result.title), ("operation", "Blotted Sky"))


if __name__ == "__main__":
    unittest.main()
