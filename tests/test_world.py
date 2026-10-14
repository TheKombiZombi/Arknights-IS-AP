import unittest

try:
    from BaseClasses import ItemClassification, LocationProgressType, PlandoOptions
    from Fill import distribute_items_restrictive
    from NetUtils import LocationStore
    from Options import OptionError
    from test.general import setup_multiworld

    from arknights_is import (
        BASE_ID,
        CATALOG,
        DUCKSANITY_NAMES,
        FILLER_ITEMS,
        ITEM_IDS,
        LOC_IDS,
        ArknightsISWorld,
        selected_location_names,
    )
    from arknights_is.Options import OperatorRoster
except ModuleNotFoundError:
    AP_AVAILABLE = False
else:
    AP_AVAILABLE = True


@unittest.skipUnless(AP_AVAILABLE, "requires an Archipelago source checkout on PYTHONPATH")
class LocationSelectionTests(unittest.TestCase):
    def test_floor_one_is_permanently_absent_and_floor_sanity_means_reach_two_through_six(self):
        self.assertFalse(any("First reach Floor 1" in name for name in LOC_IDS))
        enabled = {"IS2"}
        without = selected_location_names(
            enabled,
            boss_sanity=0,
            ending_sanity=False,
            encounter_sanity=False,
            floor_sanity=False,
            ducksanity=False,
        )
        with_floor = selected_location_names(
            enabled,
            boss_sanity=0,
            ending_sanity=False,
            encounter_sanity=False,
            floor_sanity=True,
            ducksanity=False,
        )
        added = set(with_floor) - set(without)
        self.assertEqual(added, {f"IS2 — First reach Floor {floor}" for floor in range(2, 7)})

    def test_sanity_and_enabled_mode_selection(self):
        names = selected_location_names(
            {"IS3"},
            boss_sanity=0,
            ending_sanity=False,
            encounter_sanity=False,
            floor_sanity=False,
            ducksanity=False,
        )
        self.assertTrue(all(name.startswith("IS3 — ") for name in names))
        self.assertFalse(any(" — Encounter: " in name for name in names))
        self.assertFalse(any(" — Ending: " in name for name in names))
        self.assertFalse(any("Dreadful Foe" in name for name in names))
        self.assertEqual(sum(name.endswith(" — Any Ending Cleared") for name in names), 1)

    def test_boss_modes_use_named_catalog_data(self):
        off = selected_location_names(
            {"IS2"}, boss_sanity=0, ending_sanity=False, encounter_sanity=False,
            floor_sanity=False, ducksanity=False,
        )
        bundled = selected_location_names(
            {"IS2"}, boss_sanity=1, ending_sanity=False, encounter_sanity=False,
            floor_sanity=False, ducksanity=False,
        )
        individual = selected_location_names(
            {"IS2"}, boss_sanity=2, ending_sanity=False, encounter_sanity=False,
            floor_sanity=False, ducksanity=False,
        )
        split_floor_three = selected_location_names(
            {"IS2"}, boss_sanity=2, individual_floor_3_boss_checks=True,
            ending_sanity=False, encounter_sanity=False, floor_sanity=False, ducksanity=False,
        )
        self.assertFalse(any("Dreadful Foe" in name for name in off))
        self.assertEqual(sum("Dreadful Foe" in name for name in bundled), 3)
        self.assertIn("IS2 — Floor 3 Dreadful Foe", individual)
        self.assertFalse(any("Floor 3 Dreadful Foe:" in name for name in individual))
        expected = sum(len(CATALOG["modes"]["IS2"][f"f{floor}_bosses"]) for floor in (5, 6))
        self.assertEqual(sum("Dreadful Foe:" in name for name in individual), expected)
        self.assertIn("IS2 — Floor 3 Dreadful Foe: A Cold Separation", split_floor_three)

    def test_ducksanity_has_stable_global_integer_codes(self):
        self.assertEqual([LOC_IDS[name] for name in DUCKSANITY_NAMES], [BASE_ID + 9000 + i for i in range(4)])
        self.assertTrue(all(type(LOC_IDS[name]) is int for name in DUCKSANITY_NAMES))


@unittest.skipUnless(AP_AVAILABLE, "requires an Archipelago source checkout on PYTHONPATH")
class GenerationTests(unittest.TestCase):
    def make_world(self, **overrides):
        options = {
            "enabled_modes": ["IS2", "IS3", "IS4", "IS5", "IS6"],
            "starting_mode": "IS2",
            "starting_mode_count": 1,
            "boss_sanity": "off",
            "individual_floor_3_boss_checks": False,
            "ending_sanity": False,
            "encounter_sanity": False,
            "floor_sanity": False,
            "ducksanity": False,
            "operator_copies": "two",
            "operator_roster": list(CATALOG["operators"]),
            "mode_qol_progression": False,
            "core_unit": [],
            "preferred_class_pool": [],
            "start_with_is_mode_unlocks_hinted": False,
        }
        options.update(overrides)
        return setup_multiworld(ArknightsISWorld, seed=12345, options=options)

    def test_minimal_sanity_generation_balances_without_overfill(self):
        multiworld = self.make_world()
        world = multiworld.worlds[1]
        locations = multiworld.get_locations(1)
        self.assertEqual(len(multiworld.itempool), len(multiworld.get_unfilled_locations(1)))
        self.assertTrue(all(type(location.address) is int for location in locations))
        self.assertEqual(
            {location.name for location in locations if location.name.endswith("Any Ending Cleared")},
            {f"IS{i} — Any Ending Cleared" for i in range(2, 7)},
        )
        self.assertFalse(any("Encounter:" in location.name for location in locations))
        self.assertFalse(any("Ending:" in location.name for location in locations))
        self.assertFalse(any("First reach Floor" in location.name for location in locations))

        precollected = world.balance_precollected_unlocks
        permit_index = next((i for i, name in enumerate(precollected) if name.endswith(" Permit")), len(precollected))
        self.assertTrue(all(not name.endswith(" Permit") for name in precollected[:permit_index]))
        expected_non_permits = {
            f"{mode} — {squad}"
            for mode in ("IS2", "IS3", "IS4", "IS5", "IS6")
            for squad in CATALOG["squads"][mode]
            if squad != "Leader Squad"
        } | {f"IS{i} Access" for i in range(3, 7)}
        self.assertTrue(expected_non_permits.issubset(set(precollected)))
        self.assertEqual(world.starting_modes, ["IS2"])
        self.assertEqual(world.starting_items, ["IS2 Access"])

        distribute_items_restrictive(multiworld)
        self.assertTrue(all(location.item is not None for location in locations))
        slot_data = world.fill_slot_data()
        self.assertEqual(slot_data["starting_mode"], "is2")
        self.assertEqual(slot_data["precollected_unlocks"], world.precollected_unlocks)
        self.assertTrue(all(type(code) is int for code in slot_data["active_location_ids"]))

        raw = {
            1: {
                location.address: (location.item.code, location.item.player, 0)
                for location in locations
                if location.address is not None and location.item.code is not None
            }
        }
        store = LocationStore(raw)
        self.assertEqual(set(store[1]), set(raw[1]))

    def test_maximal_generation_and_restrictive_fill(self):
        multiworld = self.make_world(
            boss_sanity="individual",
            individual_floor_3_boss_checks=True,
            ending_sanity=True,
            encounter_sanity=True,
            floor_sanity=True,
            ducksanity=True,
            operator_copies="two",
            operator_roster=list(CATALOG["operators"]),
        )
        world = multiworld.worlds[1]
        self.assertEqual(
            {location.name for location in multiworld.get_locations(1)},
            set(world.active_location_names),
        )
        self.assertEqual(len(multiworld.itempool), len(multiworld.get_unfilled_locations(1)))
        distribute_items_restrictive(multiworld)
        self.assertTrue(all(location.item is not None for location in multiworld.get_locations(1)))
        self.assertTrue(
            all(type(code) is int for code in world.fill_slot_data()["active_location_ids"])
        )

    def test_random_starting_mode_count_and_disabled_item_attribution(self):
        multiworld = self.make_world(
            enabled_modes=["IS3", "IS5"],
            starting_mode="random",
            starting_mode_count=2,
            ending_sanity=True,
            encounter_sanity=True,
            floor_sanity=True,
            boss_sanity="individual",
            ducksanity=True,
            operator_copies="one",
        )
        world = multiworld.worlds[1]
        self.assertEqual(world.starting_modes, ["IS3", "IS5"])
        self.assertTrue(all("IS2 — " not in location.name for location in multiworld.get_locations(1)))
        attributed = [item.name for item in multiworld.itempool]
        attributed.extend(item.name for item in multiworld.precollected_items[1])
        self.assertFalse(any(name.startswith(("IS2 — ", "IS4 — ", "IS6 — ")) for name in attributed))
        self.assertFalse(any(name in {"IS2 Access", "IS4 Access", "IS6 Access"} for name in attributed))
        self.assertTrue(all(name in world.active_location_names for name in DUCKSANITY_NAMES))

    def test_disabled_explicit_starting_mode_is_rejected(self):
        with self.assertRaisesRegex(OptionError, "Starting Mode IS2 must also be enabled"):
            self.make_world(enabled_modes=["IS3"], starting_mode="IS2")

    def test_distinct_endings_requires_ending_sanity(self):
        with self.assertRaisesRegex(OptionError, "requires EndingSanity"):
            self.make_world(goal="distinct_endings", ending_sanity=False)

    def test_mode_access_controls_reachability_and_starting_access_is_live(self):
        multiworld = self.make_world(
            enabled_modes=["IS2", "IS3"],
            starting_mode="IS2",
            starting_mode_count=1,
            operator_roster=[],
        )
        is2 = multiworld.get_location("IS2 — Any Ending Cleared", 1)
        is3 = multiworld.get_location("IS3 — Any Ending Cleared", 1)
        state = multiworld.state.copy()
        self.assertTrue(state.can_reach(is2))
        self.assertFalse(state.can_reach(is3))
        state.collect(multiworld.worlds[1].create_item("IS3 Access"), True)
        self.assertTrue(state.can_reach(is3))

    def test_item_classifications_are_semantic(self):
        world = self.make_world(operator_roster=["Aak"]).worlds[1]
        squad = next(name for name in CATALOG["squads"]["IS2"] if name != "Leader Squad")
        self.assertEqual(world.create_item("IS3 Access").classification, ItemClassification.progression)
        self.assertEqual(world.create_item("IS2 Cleared").classification, ItemClassification.progression)
        self.assertEqual(world.create_item("Aak Permit").classification, ItemClassification.useful)
        self.assertEqual(world.create_item(f"IS2 — {squad}").classification, ItemClassification.useful)
        self.assertTrue(all(world.create_item(name).classification == ItemClassification.filler for name in FILLER_ITEMS))

    def test_location_progress_types_bias_only_intended_checks(self):
        multiworld = self.make_world(
            enabled_modes=["IS2"], boss_sanity="individual",
            individual_floor_3_boss_checks=True, ending_sanity=True,
            encounter_sanity=True, floor_sanity=True, ducksanity=True, operator_roster=[],
        )
        self.assertEqual(
            multiworld.get_location("IS2 — Floor 3 Dreadful Foe: A Cold Separation", 1).progress_type,
            LocationProgressType.PRIORITY,
        )
        normal = next(location for location in multiworld.get_locations(1) if " — Floor 2:" in location.name)
        self.assertEqual(normal.progress_type, LocationProgressType.DEFAULT)
        for location in multiworld.get_locations(1):
            if " — Encounter: " in location.name or location.name.startswith("Global — Ducksanity:"):
                self.assertEqual(location.progress_type, LocationProgressType.EXCLUDED)

    def test_roster_empty_subset_and_default_full(self):
        empty = self.make_world(operator_roster=[])
        self.assertFalse(any(item.name.endswith(" Permit") for item in empty.itempool))
        self.assertEqual(empty.worlds[1].fill_slot_data()["operator_roster"], [])

        subset = self.make_world(operator_roster=["Aak", "Angelina"], operator_copies="one")
        permits = {item.name for item in subset.itempool if item.name.endswith(" Permit")}
        permits.update(item.name for item in subset.precollected_items[1] if item.name.endswith(" Permit"))
        self.assertEqual(permits, {"Aak Permit", "Angelina Permit"})
        self.assertEqual(subset.worlds[1].fill_slot_data()["operator_roster"], ["Aak", "Angelina"])

        full = setup_multiworld(ArknightsISWorld, seed=12345, options={
            "enabled_modes": ["IS2"], "starting_mode": "IS2", "starting_mode_count": 1,
            "boss_sanity": "off", "individual_floor_3_boss_checks": False,
            "ending_sanity": False, "encounter_sanity": False,
            "floor_sanity": False, "ducksanity": False, "operator_copies": "one",
        })
        self.assertEqual(set(full.worlds[1].fill_slot_data()["operator_roster"]), set(CATALOG["operators"]))

    def test_unknown_roster_name_is_rejected_by_option_framework(self):
        with self.assertRaises(OptionError):
            OperatorRoster.from_any(["Definitely Not An Operator"]).verify(
                ArknightsISWorld, "Tester", PlandoOptions.none
            )

    def test_item_ids_are_append_only_across_catalog_extension(self):
        self.assertEqual(ITEM_IDS["Aak Permit"], BASE_ID)
        self.assertEqual(ITEM_IDS["Zuo Le Permit"], BASE_ID + 127)
        self.assertEqual(ITEM_IDS["IS2 — Gathering Squad"], BASE_ID + 128)
        self.assertEqual(ITEM_IDS["IS6 Access"], BASE_ID + 199)
        self.assertEqual(ITEM_IDS["Rhodes Island Supply"], BASE_ID + 200)
        self.assertEqual(ITEM_IDS["IS2 Cleared"], BASE_ID + 201)
        self.assertEqual(
            ITEM_IDS["One Extra Deployment Point, Redeemable Yesterday"], BASE_ID + 220
        )
        self.assertEqual(ITEM_IDS["Angelina the Mellow Wish Permit"], BASE_ID + 221)
        self.assertEqual(ITEM_IDS["Viy Permit"], BASE_ID + 229)

    def test_filler_ids_and_seeded_distribution_are_stable(self):
        self.assertEqual(ITEM_IDS["Rhodes Island Supply"], BASE_ID + 200)
        self.assertEqual(len({ITEM_IDS[name] for name in FILLER_ITEMS}), len(FILLER_ITEMS))
        options = dict(enabled_modes=["IS2"], starting_mode="IS2", operator_roster=[])
        first = self.make_world(**options)
        second = self.make_world(**options)
        first_fillers = [item.name for item in first.itempool if item.classification == ItemClassification.filler]
        second_fillers = [item.name for item in second.itempool if item.classification == ItemClassification.filler]
        self.assertEqual(first_fillers, second_fillers)
        self.assertGreater(len(set(first_fillers)), 1)

    def test_restrictive_fill_succeeds_with_access_logic(self):
        multiworld = self.make_world(
            enabled_modes=["IS2", "IS3", "IS4"], starting_mode="IS2",
            starting_mode_count=1, operator_roster=["Aak", "Angelina"], operator_copies="one",
        )
        distribute_items_restrictive(multiworld)
        self.assertTrue(all(location.item is not None for location in multiworld.get_locations(1)))

    def test_mode_qol_permits_are_local_starting_sphere_guarantees(self):
        multiworld = self.make_world(
            enabled_modes=["IS2", "IS3", "IS4", "IS6"],
            starting_mode="IS4",
            operator_roster=["Thorns", "Texas the Omertosa", "Raidian"],
            operator_copies="two",
            mode_qol_progression=True,
        )
        world = multiworld.worlds[1]
        self.assertEqual(
            multiworld.local_early_items[1],
            {"Raidian Permit": 1, "Texas the Omertosa Permit": 2, "Thorns Permit": 2},
        )
        distribute_items_restrictive(multiworld)
        initially_reachable = multiworld.state.copy()
        placed = [
            location.item.name
            for location in multiworld.get_locations(1)
            if location.item and location.can_reach(initially_reachable)
        ]
        self.assertEqual(placed.count("Thorns Permit"), 2)
        self.assertEqual(placed.count("Texas the Omertosa Permit"), 2)
        self.assertGreaterEqual(placed.count("Raidian Permit"), 1)
        self.assertEqual(world.fill_slot_data()["guaranteed_early_permits"], multiworld.local_early_items[1])

    def test_mode_qol_validates_roster_and_copy_compatibility(self):
        with self.assertRaisesRegex(OptionError, "signature operators"):
            self.make_world(
                enabled_modes=["IS2"], starting_mode="IS2", operator_roster=[],
                mode_qol_progression=True,
            )
        with self.assertRaisesRegex(OptionError, "requires Operator Permits"):
            self.make_world(
                enabled_modes=["IS3"], starting_mode="IS3",
                operator_roster=["Texas the Omertosa"], operator_copies="one",
                mode_qol_progression=True,
            )
        compatible = self.make_world(
            enabled_modes=["IS6"], starting_mode="IS6", operator_roster=["Raidian"],
            operator_copies="one", mode_qol_progression=True,
        )
        self.assertEqual(compatible.worlds[1].starting_modes, ["IS6"])

    def test_core_unit_starts_two_of_two_without_pool_duplication(self):
        multiworld = self.make_world(
            enabled_modes=["IS2"], starting_mode="IS2", operator_roster=["Thorns", "Aak"],
            operator_copies="two", core_unit=["Thorns"],
        )
        world = multiworld.worlds[1]
        precollected = [item.name for item in multiworld.precollected_items[1]]
        self.assertEqual(precollected.count("Thorns Permit"), 2)
        self.assertFalse(any(item.name == "Thorns Permit" for item in multiworld.itempool))
        self.assertEqual(sum(item.name == "Aak Permit" for item in multiworld.itempool), 2)
        self.assertEqual(world.fill_slot_data()["core_unit"], "Thorns")
        self.assertEqual(world.fill_slot_data()["core_starting_items"], ["Thorns Permit"] * 2)

    def test_core_unit_validation_is_explicit(self):
        with self.assertRaisesRegex(OptionError, "exactly one"):
            self.make_world(operator_roster=["Aak", "Thorns"], core_unit=["Aak", "Thorns"])
        with self.assertRaisesRegex(OptionError, "Owned Operator Roster"):
            self.make_world(operator_roster=["Aak"], core_unit=["Thorns"])
        with self.assertRaisesRegex(OptionError, "2/2 start"):
            self.make_world(operator_roster=["Thorns"], operator_copies="one", core_unit=["Thorns"])

    def test_preferred_class_pool_is_hard_early_and_validated_per_class(self):
        multiworld = self.make_world(
            enabled_modes=["IS2", "IS4"], starting_mode="IS4",
            operator_roster=["Thorns", "Raidian", "Aak"], operator_copies="one",
            preferred_class_pool=["Thorns", "Raidian", "Aak"],
        )
        self.assertEqual(
            multiworld.local_early_items[1],
            {"Aak Permit": 1, "Raidian Permit": 1, "Thorns Permit": 1},
        )
        distribute_items_restrictive(multiworld)
        state = multiworld.state.copy()
        early_items = {
            location.item.name
            for location in multiworld.get_locations(1)
            if location.item and location.can_reach(state)
        }
        self.assertTrue({"Aak Permit", "Raidian Permit", "Thorns Permit"}.issubset(early_items))

        with self.assertRaisesRegex(OptionError, "at most one operator per class"):
            self.make_world(
                operator_roster=["Thorns", "SilverAsh"],
                preferred_class_pool=["Thorns", "SilverAsh"],
            )
        with self.assertRaisesRegex(OptionError, "must be in Owned Operator Roster"):
            self.make_world(operator_roster=["Aak"], preferred_class_pool=["Raidian"])

    def test_start_mode_unlock_hints_extend_common_start_hints(self):
        multiworld = self.make_world(
            enabled_modes=["IS2", "IS3", "IS6"], starting_mode="IS3",
            operator_roster=[], start_with_is_mode_unlocks_hinted=True,
        )
        self.assertTrue({"IS2 Access", "IS3 Access", "IS6 Access"}.issubset(
            multiworld.worlds[1].options.start_hints.value
        ))
        self.assertTrue(multiworld.worlds[1].fill_slot_data()["start_with_is_mode_unlocks_hinted"])
        self.assertEqual(
            multiworld.worlds[1].fill_slot_data()["requested_start_hints"],
            ["IS2 Access", "IS3 Access", "IS6 Access"],
        )
        distribute_items_restrictive(multiworld)
        placed_access = {
            location.item.name
            for location in multiworld.get_locations(1)
            if location.item and location.item.name.endswith(" Access")
        }
        self.assertEqual(placed_access, {"IS2 Access", "IS6 Access"})


if __name__ == "__main__":
    unittest.main()
