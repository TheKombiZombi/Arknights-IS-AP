from __future__ import annotations

import json
from importlib.resources import files

from BaseClasses import (
    Entrance,
    Item,
    ItemClassification,
    Location,
    LocationProgressType,
    Region,
)
from Options import OptionError
from worlds.AutoWorld import WebWorld, World
from worlds.LauncherComponents import Component, Type, components, launch_subprocess
from worlds.generic.Rules import set_rule

from .Options import ArknightsISOptions

GAME = "Arknights Integrated Strategies"
BASE_ID = 906_190_000
CATALOG_VERSION = "2026-09-24.1"
WORLD_VERSION = "0.7.4"
LEGACY_OPERATOR_COUNT = 128
MODES = ("IS2", "IS3", "IS4", "IS5", "IS6")
DUCKSANITY_NAMES = (
    "Global — Ducksanity: Beat Duck Lord",
    "Global — Ducksanity: Beat Gopnik",
    "Global — Ducksanity: Beat Crying Thief",
    "Global — Ducksanity: Beat Fatty",
)
STARTING_MODE_VALUES = {2: "IS2", 3: "IS3", 4: "IS4", 5: "IS5", 6: "IS6"}
MODE_QOL_PERMITS = {
    "IS2": ("Thorns", 2),
    "IS3": ("Texas the Omertosa", 2),
    "IS6": ("Raidian", 1),
}

_package = files(__package__)
CATALOG = json.loads(_package.joinpath("catalog.json").read_text(encoding="utf8"))
OPERATOR_CLASS_DATA = json.loads(
    _package.joinpath("operator_classes.json").read_text(encoding="utf8")
)
OPERATOR_CLASSES = OPERATOR_CLASS_DATA["operators"]
if set(OPERATOR_CLASSES) != set(CATALOG["operators"]):
    raise ValueError("operator_classes.json must classify every catalog operator exactly once")

FILLER_ITEMS = (
    "Rhodes Island Supply",  # Original ID retained for old clients and multidata.
    "+0 Hope",
    "+5 Originium Ingots to the Duck Lord",
    "Amiya Tells You That You Cannot Rest Yet",
    "Kal'tsit Yapping",
    "Activating Melantha's Skill",
    "Deploying Ptilopsis Under Your Table",
    "Continuing the SilverAsh Bloodline",
    "Emergency Tactical Beverage",
    "One (1) Suspiciously Normal Rock",
    "Closure's Limited-Time Extended Maintenance",
    "Reserve Operator Recruitment Permit (Decorative)",
    "A Very Convincing Fake Collectible",
    "Doctor's Emergency Sanity Snack",
    "Ceobe's Definitely-Not-Stolen Honey Biscuit",
    "One Extra Deployment Point, Redeemable Yesterday",
)


def build_locations() -> dict[str, int]:
    """Build the complete stable ID registry while omitting retired Floor 1 checks.

    Existing 0.2 IDs retain their positions. The removed Floor 1 IDs remain reserved gaps;
    named bosses and global Ducksanity checks use separate append-only ranges.
    """

    locations: dict[str, int] = {}
    legacy_index = 0
    for mode, data in CATALOG["modes"].items():
        for entry in data["normal"]:
            locations[f'{mode} — Floor {entry["floor"]}: {entry["name"]}'] = (
                BASE_ID + 1000 + legacy_index
            )
            legacy_index += 1
        for floor in (3, 5, 6):
            locations[f"{mode} — Floor {floor} Dreadful Foe"] = BASE_ID + 1000 + legacy_index
            legacy_index += 1
        for name in data["encounters"]:
            locations[f"{mode} — Encounter: {name}"] = BASE_ID + 1000 + legacy_index
            legacy_index += 1
        for name in data["endings"]:
            locations[f"{mode} — Ending: {name}"] = BASE_ID + 1000 + legacy_index
            legacy_index += 1
        for floor in range(1, 7):
            if floor != 1:
                locations[f"{mode} — First reach Floor {floor}"] = BASE_ID + 1000 + legacy_index
            legacy_index += 1  # Floor 1's former code is intentionally never reused.
        locations[f"{mode} — Any Ending Cleared"] = BASE_ID + 1000 + legacy_index
        legacy_index += 1

    boss_index = 0
    for mode, data in CATALOG["modes"].items():
        for floor in (3, 5, 6):
            for boss in data[f"f{floor}_bosses"]:
                locations[f"{mode} — Floor {floor} Dreadful Foe: {boss}"] = (
                    BASE_ID + 5000 + boss_index
                )
                boss_index += 1

    for index, name in enumerate(DUCKSANITY_NAMES):
        locations[name] = BASE_ID + 9000 + index
    return locations


def selected_location_names(
    enabled_modes: set[str] | list[str] | tuple[str, ...],
    *,
    boss_sanity: int,
    ending_sanity: bool,
    encounter_sanity: bool,
    floor_sanity: bool,
    ducksanity: bool,
    individual_floor_3_boss_checks: bool = False,
) -> list[str]:
    """Return the exact locations instantiated by a normalized option set."""

    names: list[str] = []
    for mode in MODES:
        if mode not in enabled_modes:
            continue
        data = CATALOG["modes"][mode]
        names.extend(
            f'{mode} — Floor {entry["floor"]}: {entry["name"]}' for entry in data["normal"]
        )
        if boss_sanity:
            # Floor 3's Dreadful Foe is RNG-selected and normally remains one fair combined
            # check, even under Individual BossSanity. Splitting it is an explicit opt-in.
            names.append(f"{mode} — Floor 3 Dreadful Foe")
        if boss_sanity == 1:
            names.extend(f"{mode} — Floor {floor} Dreadful Foe" for floor in (5, 6))
        elif boss_sanity == 2:
            floors = (3, 5, 6) if individual_floor_3_boss_checks else (5, 6)
            for floor in floors:
                names.extend(
                    f"{mode} — Floor {floor} Dreadful Foe: {boss}"
                    for boss in data[f"f{floor}_bosses"]
                )
        if encounter_sanity:
            names.extend(f"{mode} — Encounter: {name}" for name in data["encounters"])
        if ending_sanity:
            names.extend(f"{mode} — Ending: {name}" for name in data["endings"])
        if floor_sanity:
            names.extend(f"{mode} — First reach Floor {floor}" for floor in range(2, 7))
        names.append(f"{mode} — Any Ending Cleared")
    if ducksanity:
        names.extend(DUCKSANITY_NAMES)
    return names


# Keep the original 128 permit IDs and every following 0.4 item ID fixed. New catalog
# permits are appended after the complete legacy registry instead of shifting squad/access IDs.
legacy_operators = CATALOG["operators"][:LEGACY_OPERATOR_COUNT]
appended_operators = CATALOG["operators"][LEGACY_OPERATOR_COUNT:]
ITEM_NAMES = [f"{operator} Permit" for operator in legacy_operators]
for mode, squads in CATALOG["squads"].items():
    ITEM_NAMES.extend(f"{mode} — {squad}" for squad in squads if squad != "Leader Squad")
ITEM_NAMES.extend(f"{mode} Access" for mode in MODES)
ITEM_NAMES.extend(
    ["Rhodes Island Supply", *(f"{mode} Cleared" for mode in MODES), *FILLER_ITEMS[1:]]
)
ITEM_NAMES.extend(f"{operator} Permit" for operator in appended_operators)
ITEM_IDS = {name: BASE_ID + index for index, name in enumerate(dict.fromkeys(ITEM_NAMES))}
LOC_IDS = build_locations()


class AKItem(Item):
    game = GAME


class AKLocation(Location):
    game = GAME


class ArknightsISWorld(World):
    game = GAME
    item_name_to_id = ITEM_IDS
    location_name_to_id = LOC_IDS
    web = WebWorld()
    options_dataclass = ArknightsISOptions

    def generate_early(self):
        enabled = set(self.options.enabled_modes.value)
        enabled_count = len(enabled)
        if not enabled:
            raise OptionError("Enabled Modes must contain at least one mode.")
        if self.options.goal.value == 1 and self.options.modes_required_for_victory.value > enabled_count:
            raise OptionError("Modes Required for Victory cannot exceed the number of enabled modes.")
        if self.options.goal.value == 2:
            if not self.options.ending_sanity.value:
                raise OptionError("Distinct Endings goal requires EndingSanity to be enabled.")
            available_endings = sum(len(CATALOG["modes"][mode]["endings"]) for mode in enabled)
            if self.options.endings_required_for_victory.value > available_endings:
                raise OptionError(
                    "Distinct Endings Required for Victory cannot exceed the endings in enabled modes."
                )
        if self.options.starting_mode_count.value > enabled_count:
            raise OptionError("Starting Mode Count cannot exceed the number of enabled modes.")
        explicit_mode = STARTING_MODE_VALUES.get(self.options.starting_mode.value)
        if explicit_mode and explicit_mode not in enabled:
            raise OptionError(f"Starting Mode {explicit_mode} must also be enabled.")

        roster = set(self.options.operator_roster.value)
        core_units = set(self.options.core_unit.value)
        if len(core_units) > 1:
            raise OptionError("Core Unit accepts exactly one operator when enabled; choose zero or one.")
        if core_units and self.options.operator_copies.value != 2:
            raise OptionError(
                "Core Unit requires Operator Permits Required for E2 to be Two so its 2/2 start "
                "matches the configured permit-copy model."
            )
        missing_core = core_units - roster
        if missing_core:
            raise OptionError(
                f"Core Unit must be in Owned Operator Roster: {', '.join(sorted(missing_core))}."
            )

        preferred = set(self.options.preferred_class_pool.value)
        missing_preferred = preferred - roster
        if missing_preferred:
            raise OptionError(
                "Preferred Class Pool operators must be in Owned Operator Roster: "
                f"{', '.join(sorted(missing_preferred))}."
            )
        by_class: dict[str, list[str]] = {}
        for operator in preferred:
            by_class.setdefault(OPERATOR_CLASSES[operator], []).append(operator)
        duplicate_classes = {
            operator_class: sorted(operators)
            for operator_class, operators in by_class.items()
            if len(operators) > 1
        }
        if duplicate_classes:
            details = "; ".join(
                f"{operator_class}: {', '.join(operators)}"
                for operator_class, operators in sorted(duplicate_classes.items())
            )
            raise OptionError(f"Preferred Class Pool accepts at most one operator per class ({details}).")

        if self.options.mode_qol_progression.value:
            required = {
                operator: copies
                for mode, (operator, copies) in MODE_QOL_PERMITS.items()
                if mode in enabled
            }
            missing = set(required) - roster
            if missing:
                raise OptionError(
                    "Mode QoL Progression requires its signature operators in Owned Operator "
                    f"Roster: {', '.join(sorted(missing))}."
                )
            incompatible = [
                operator
                for operator, copies in required.items()
                if copies > self.options.operator_copies.value
            ]
            if incompatible:
                raise OptionError(
                    "Mode QoL Progression requires Operator Permits Required for E2 to be Two "
                    "when IS2 or IS3 is enabled."
                )

    def _active_location_names(self) -> list[str]:
        return selected_location_names(
            set(self.options.enabled_modes.value),
            boss_sanity=self.options.boss_sanity.value,
            individual_floor_3_boss_checks=bool(
                self.options.individual_floor_3_boss_checks.value
            ),
            ending_sanity=bool(self.options.ending_sanity.value),
            encounter_sanity=bool(self.options.encounter_sanity.value),
            floor_sanity=bool(self.options.floor_sanity.value),
            ducksanity=bool(self.options.ducksanity.value),
        )

    def create_regions(self):
        menu = Region("Menu", self.player, self.multiworld)
        global_board = Region("Global Expedition Board", self.player, self.multiworld)
        global_entrance = Entrance(self.player, "Open Global Expedition Board", menu)
        menu.exits.append(global_entrance)
        global_entrance.connect(global_board)

        enabled = set(self.options.enabled_modes.value)
        goal = self.options.goal.value
        self.active_location_names = self._active_location_names()
        mode_regions: dict[str, Region] = {}
        for mode in sorted(enabled):
            board = Region(f"{mode} Expedition Board", self.player, self.multiworld)
            entrance = Entrance(self.player, f"Enter {mode}", menu)
            set_rule(entrance, lambda state, item=f"{mode} Access": state.has(item, self.player))
            menu.exits.append(entrance)
            entrance.connect(board)
            mode_regions[mode] = board

        for name in self.active_location_names:
            mode = name.split(" — ", 1)[0]
            board = mode_regions.get(mode, global_board)
            location = AKLocation(self.player, name, LOC_IDS[name], board)
            location.progress_type = self._location_progress_type(name)
            if mode in enabled and goal in (0, 1) and name.endswith(" — Any Ending Cleared"):
                location.place_locked_item(
                    AKItem(
                        f"{mode} Cleared",
                        ItemClassification.progression,
                        ITEM_IDS[f"{mode} Cleared"],
                        self.player,
                    )
                )
            board.locations.append(location)
        self.multiworld.regions += [menu, global_board, *mode_regions.values()]

    @staticmethod
    def _location_progress_type(name: str) -> LocationProgressType:
        """Bias foreign progression toward fair checks without imposing fill quotas."""

        if " — Floor 3 Dreadful Foe" in name:
            return LocationProgressType.PRIORITY
        if (
            name.startswith("Global — Ducksanity:")
            or " — Encounter: " in name
            or " — Ending: " in name
            or " — Floor 5" in name
            or " — Floor 6" in name
            or name.endswith("First reach Floor 5")
            or name.endswith("First reach Floor 6")
        ):
            return LocationProgressType.EXCLUDED
        return LocationProgressType.DEFAULT

    def create_item(self, name: str) -> AKItem:
        if name in FILLER_ITEMS:
            classification = ItemClassification.filler
        elif name.endswith(" Access") or name.endswith(" Cleared"):
            classification = ItemClassification.progression
        else:
            classification = ItemClassification.useful
        return AKItem(name, classification, ITEM_IDS[name], self.player)

    def _select_starting_modes(self, enabled: list[str]) -> list[str]:
        count = self.options.starting_mode_count.value
        explicit = STARTING_MODE_VALUES.get(self.options.starting_mode.value)
        if explicit:
            remaining = [mode for mode in enabled if mode != explicit]
            return sorted([explicit, *self.random.sample(remaining, count - 1)])
        return sorted(self.random.sample(enabled, count))

    def create_items(self):
        enabled = sorted(self.options.enabled_modes.value)
        starting = self._select_starting_modes(enabled)
        selected_operators = sorted(self.options.operator_roster.value)
        core_unit = next(iter(self.options.core_unit.value), None)
        permit_items = [
            f"{operator} Permit"
            for operator in selected_operators
            for _copy in range(self.options.operator_copies.value)
        ]
        core_starting_items: list[str] = []
        if core_unit:
            core_permit = f"{core_unit} Permit"
            for _copy in range(2):
                permit_items.remove(core_permit)
            core_starting_items = [core_permit, core_permit]
        squad_items = [
            f"{mode} — {squad}"
            for mode in enabled
            for squad in CATALOG["squads"][mode]
            if squad != "Leader Squad"
        ]
        access_items = [f"{mode} Access" for mode in enabled if mode not in starting]
        pool_names = [*permit_items, *squad_items, *access_items]

        starting_items = [f"{mode} Access" for mode in starting]
        for name in starting_items:
            self.multiworld.push_precollected(self.create_item(name))
        for name in core_starting_items:
            self.multiworld.push_precollected(self.create_item(name))

        fillable_count = len(self.multiworld.get_unfilled_locations(self.player))
        excess = max(0, len(pool_names) - fillable_count)
        balance_precollected: list[str] = []
        # Preserve operator permits as defining rewards whenever possible: precollect mode/squad
        # unlocks first, then permits only when the active location set is smaller still.
        for name in [*squad_items, *access_items, *permit_items]:
            if not excess:
                break
            pool_names.remove(name)
            balance_precollected.append(name)
            self.multiworld.push_precollected(self.create_item(name))
            excess -= 1

        if len(pool_names) > fillable_count:
            raise OptionError(
                f"Item pool has {len(pool_names)} items for {fillable_count} locations after balancing."
            )
        filler_count = fillable_count - len(pool_names)
        self._cap_excluded_locations(filler_count)
        # Seeded choices make repeats natural, distribution reproducible, and the stable filler
        # catalog independent from location count or progression quantity.
        pool_names.extend(self.random.choice(FILLER_ITEMS) for _ in range(filler_count))
        if len(pool_names) != fillable_count:
            raise OptionError("Internal item/location balance failure; refusing to overfill the seed.")
        self.multiworld.itempool += [self.create_item(name) for name in pool_names]

        guaranteed_permits: dict[str, int] = {}
        if self.options.mode_qol_progression.value:
            for mode, (operator, copies) in MODE_QOL_PERMITS.items():
                if mode in enabled and mode not in starting:
                    guaranteed_permits[operator] = max(guaranteed_permits.get(operator, 0), copies)
        for operator in self.options.preferred_class_pool.value:
            guaranteed_permits[operator] = max(guaranteed_permits.get(operator, 0), 1)

        already_early: dict[str, int] = {}
        for name in [*core_starting_items, *balance_precollected]:
            if name.endswith(" Permit"):
                operator = name.removesuffix(" Permit")
                already_early[operator] = already_early.get(operator, 0) + 1
        early_permits: dict[str, int] = {}
        for operator, requested in sorted(guaranteed_permits.items()):
            needed = max(0, requested - already_early.get(operator, 0))
            if needed:
                early_permits[f"{operator} Permit"] = needed

        initial_unfilled = [
            location
            for location in self.multiworld.get_unfilled_locations(self.player)
            if location.can_reach(self.multiworld.state)
        ]
        if sum(early_permits.values()) > len(initial_unfilled):
            raise OptionError(
                "The requested Mode QoL/Preferred Class Pool guarantees need "
                f"{sum(early_permits.values())} starting-sphere locations, but only "
                f"{len(initial_unfilled)} are reachable without non-starting mode access."
            )
        self.multiworld.local_early_items[self.player].update(early_permits)

        if self.options.start_with_is_mode_unlocks_hinted.value:
            self.options.start_hints.value.update(f"{mode} Access" for mode in enabled)

        self.starting_modes = starting
        self.starting_items = starting_items
        self.core_unit = core_unit
        self.core_starting_items = core_starting_items
        self.preferred_class_pool = sorted(self.options.preferred_class_pool.value)
        self.guaranteed_early_permits = early_permits
        self.balance_precollected_unlocks = balance_precollected
        self.precollected_unlocks = [*starting_items, *core_starting_items, *balance_precollected]
        self.selected_operators = selected_operators

    def _cap_excluded_locations(self, available_filler: int) -> None:
        """Keep EXCLUDED bias valid even when a dense roster leaves little filler.

        Archipelago reserves excluded checks for excludable items.  Downgrading the deterministic
        tail to DEFAULT avoids requiring or fabricating a fixed filler/progression quantity.
        """

        excluded = sorted(
            (
                location
                for location in self.multiworld.get_locations(self.player)
                if location.progress_type == LocationProgressType.EXCLUDED and not location.locked
            ),
            key=lambda location: location.name,
        )
        for location in excluded[available_filler:]:
            location.progress_type = LocationProgressType.DEFAULT

    def set_rules(self):
        enabled = tuple(sorted(self.options.enabled_modes.value))
        goal = self.options.goal.value
        if goal == 0:
            self.multiworld.completion_condition[self.player] = lambda state: all(
                state.has(f"{mode} Cleared", self.player) for mode in enabled
            )
        elif goal == 1:
            required = self.options.modes_required_for_victory.value
            self.multiworld.completion_condition[self.player] = lambda state: sum(
                state.has(f"{mode} Cleared", self.player) for mode in enabled
            ) >= required
        else:
            # Distinct endings are manual checks; the companion reports CLIENT_GOAL.
            self.multiworld.completion_condition[self.player] = lambda state: True

    def fill_slot_data(self):
        active_names = getattr(self, "active_location_names", self._active_location_names())
        return {
            "game": GAME,
            "world_version": WORLD_VERSION,
            "catalog_version": CATALOG_VERSION,
            "operator_permits_required_for_e2": self.options.operator_copies.value,
            "operator_roster": getattr(
                self, "selected_operators", sorted(self.options.operator_roster.value)
            ),
            "mode_qol_progression": bool(self.options.mode_qol_progression.value),
            "core_unit": getattr(self, "core_unit", next(iter(self.options.core_unit.value), None)),
            "core_starting_items": getattr(self, "core_starting_items", []),
            "preferred_class_pool": getattr(
                self, "preferred_class_pool", sorted(self.options.preferred_class_pool.value)
            ),
            "guaranteed_early_permits": getattr(self, "guaranteed_early_permits", {}),
            "start_with_is_mode_unlocks_hinted": bool(
                self.options.start_with_is_mode_unlocks_hinted.value
            ),
            "requested_start_hints": sorted(self.options.start_hints.value),
            "enabled_modes": sorted(self.options.enabled_modes.value),
            "starting_mode": (
                "random" if self.options.starting_mode.value == 0 else self.options.starting_mode.current_key
            ),
            "starting_modes": getattr(self, "starting_modes", []),
            "starting_items": getattr(self, "starting_items", []),
            "balance_precollected_unlocks": getattr(self, "balance_precollected_unlocks", []),
            "precollected_unlocks": getattr(self, "precollected_unlocks", []),
            "active_location_ids": [LOC_IDS[name] for name in active_names],
            "goal": self.options.goal.current_key,
            "modes_required_for_victory": self.options.modes_required_for_victory.value,
            "endings_required_for_victory": self.options.endings_required_for_victory.value,
            "boss_sanity": self.options.boss_sanity.current_key,
            "individual_floor_3_boss_checks": bool(
                self.options.individual_floor_3_boss_checks.value
            ),
            "ending_sanity": bool(self.options.ending_sanity.value),
            "encounter_sanity": bool(self.options.encounter_sanity.value),
            "floor_sanity": bool(self.options.floor_sanity.value),
            "ducksanity": bool(self.options.ducksanity.value),
        }


def launch_client(*args: str) -> None:
    from .Client import main

    launch_subprocess(main, name="Arknights IS Manual Client", args=args)


components.append(
    Component(
        "Arknights IS Manual Client",
        game_name=GAME,
        func=launch_client,
        component_type=Type.CLIENT,
        supports_uri=True,
    )
)
