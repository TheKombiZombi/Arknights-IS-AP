import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
STATE_PATH = ROOT / "arknights_is" / "DashboardState.py"
SPEC = importlib.util.spec_from_file_location("arknights_dashboard_state", STATE_PATH)
STATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = STATE
SPEC.loader.exec_module(STATE)
ALL_CLASSES = STATE.ALL_CLASSES
ALL_MODES = STATE.ALL_MODES
build_unlock_tracker = STATE.build_unlock_tracker
effective_received_names = STATE.effective_received_names
filter_operator_unlocks = STATE.filter_operator_unlocks
filter_unresolved_locations = STATE.filter_unresolved_locations
goal_progress = STATE.goal_progress
retire_location_ids = STATE.retire_location_ids


class DashboardStateTests(unittest.TestCase):
    def setUp(self):
        self.locations = {
            "IS2 — Encounter: A": 1,
            "IS2 — Ending: B": 2,
            "IS2 — Any Ending Cleared": 3,
            "IS3 — Encounter: A": 4,
            "IS3 — Any Ending Cleared": 5,
            "Global — Ducksanity: Beat Gopnik": 6,
        }

    def test_unresolved_filter_applies_mode_query_and_checked_state(self):
        self.assertEqual(
            filter_unresolved_locations(self.locations, {1}, "ending", "IS2"),
            [("IS2 — Any Ending Cleared", 3), ("IS2 — Ending: B", 2)],
        )
        self.assertEqual(len(filter_unresolved_locations(self.locations, set(), "", ALL_MODES)), 6)

    def test_retire_excludes_mode_goal_and_global_checks(self):
        self.assertEqual(retire_location_ids(self.locations, "IS2", {1}), [2])
        self.assertEqual(retire_location_ids(self.locations, "bad", set()), [])

    def test_goal_progress_supports_all_goal_types(self):
        # A checked Any Ending location alone does not prove this player completed a mode:
        # another player's completion can release its placed item and check it remotely.
        all_modes = goal_progress("all_enabled_modes", {"IS2", "IS3"}, 1, {3}, self.locations)
        self.assertEqual((all_modes.completed, all_modes.required, all_modes.reached), (0, 2, False))
        all_modes = goal_progress(
            "all_enabled_modes", {"IS2", "IS3"}, 1, {3, 5}, self.locations,
            {"IS2 — Ending: B", "IS3 — Ending: C"},
        )
        self.assertEqual((all_modes.completed, all_modes.required, all_modes.reached), (2, 2, True))

        mode_count = goal_progress("mode_count", {"IS2", "IS3"}, 1, {3}, self.locations)
        self.assertFalse(mode_count.reached)
        mode_count = goal_progress(
            "mode_count", {"IS2", "IS3"}, 1, {3}, self.locations,
            {"IS2 — Ending: B"},
        )
        self.assertTrue(mode_count.reached)
        manual_mode_count = goal_progress(
            "mode_count", {"IS2", "IS3"}, 1, {3}, self.locations,
            {"IS2 — Any Ending Cleared"},
        )
        self.assertTrue(manual_mode_count.reached)

        # Checked locations alone do not prove the player completed an ending: a remote
        # collection can check an Arknights location when it holds another player's item.
        endings = goal_progress("distinct_endings", {"IS2", "IS3"}, 1, {2}, self.locations)
        self.assertEqual((endings.completed, endings.required, endings.reached), (0, 1, False))
        endings = goal_progress(
            "distinct_endings", {"IS2", "IS3"}, 1, {2}, self.locations,
            {"IS2 — Ending: B"},
        )
        self.assertEqual((endings.completed, endings.required, endings.reached), (1, 1, True))

    def test_unlock_tracker_classes_filters_and_precollected_items(self):
        catalog = json.loads((ROOT / "arknights_is" / "catalog.json").read_text(encoding="utf8"))
        class_data = json.loads(
            (ROOT / "arknights_is" / "operator_classes.json").read_text(encoding="utf8")
        )
        classes = class_data["operators"]
        first, second, third = catalog["operators"][:3]
        squad = next(name for name in catalog["squads"]["IS2"] if name != "Leader Squad")
        tracker = build_unlock_tracker(
            catalog,
            classes,
            [f"{second} Permit", f"{third} Permit", f"{third} Permit", f"IS2 — {squad}"],
            {"IS2", "IS3"},
            {"IS2"},
            2,
        )
        operator_states = {operator.name: operator.permits for operator in tracker.operators}
        self.assertEqual(
            [operator_states[first], operator_states[second], operator_states[third]], [0, 1, 2]
        )
        self.assertIn((f"IS2 — {squad}", True), tracker.squads)
        self.assertIn(("IS2", True, True), tracker.modes)
        self.assertIn(("IS3", False, False), tracker.modes)

        selected_class = classes[second]
        class_rows = filter_operator_unlocks(tracker.operators, selected_class, False)
        self.assertTrue(class_rows)
        self.assertTrue(all(row.operator_class == selected_class for row in class_rows))
        unlocked = filter_operator_unlocks(tracker.operators, ALL_CLASSES, True)
        self.assertEqual({row.name for row in unlocked}, {second, third})
        self.assertEqual(filter_operator_unlocks(tracker.operators, "Not a class", False), [])

        subset = build_unlock_tracker(
            catalog, classes, [f"{second} Permit"], {"IS2"}, {"IS2"}, 2, {second}
        )
        self.assertEqual([row.name for row in subset.operators], [second])
        self.assertRegex(subset.operators[0].portrait_file, r"^\d{3}\.png$")

    def test_precollected_fallback_does_not_double_server_start_inventory(self):
        self.assertEqual(
            effective_received_names(
                ["Thorns Permit", "Thorns Permit", "IS2 Access"],
                ["Thorns Permit", "Thorns Permit", "IS2 Access"],
            ).count("Thorns Permit"),
            2,
        )
        self.assertEqual(
            effective_received_names([], ["Thorns Permit", "Thorns Permit"]).count(
                "Thorns Permit"
            ),
            2,
        )

    def test_metadata_covers_catalog_and_all_eight_classes(self):
        catalog = json.loads((ROOT / "arknights_is" / "catalog.json").read_text(encoding="utf8"))
        class_data = json.loads(
            (ROOT / "arknights_is" / "operator_classes.json").read_text(encoding="utf8")
        )
        self.assertEqual(set(class_data["operators"]), set(catalog["operators"]))
        self.assertEqual(set(class_data["classes"]), set(STATE.ARKNIGHTS_CLASSES))
        self.assertEqual(set(class_data["operators"].values()), set(STATE.ARKNIGHTS_CLASSES))
        self.assertEqual(
            {name: class_data["operators"][name] for name in catalog["operators"][128:]},
            {
                "Angelina the Mellow Wish": "Specialist",
                "Aphrissa": "Caster",
                "Closure": "Vanguard",
                "Kal'tsit - Esperanta": "Medic",
                "Makoto Yuki": "Specialist",
                "Mechanist": "Defender",
                "Thumpy": "Defender",
                "Violet Mizutsune Orchid": "Sniper",
                "Viy": "Caster",
            },
        )


if __name__ == "__main__":
    unittest.main()
