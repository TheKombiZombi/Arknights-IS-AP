from dataclasses import dataclass
import json
from importlib.resources import files

from Options import Choice, DefaultOnToggle, OptionSet, PerGameCommonOptions, Range, Toggle


_CATALOG_OPERATORS = frozenset(
    json.loads(files(__package__).joinpath("catalog.json").read_text(encoding="utf8"))["operators"]
)


class EnabledModes(OptionSet):
    """Integrated Strategies themes included in the seed."""

    display_name = "Enabled Integrated Strategies modes"
    valid_keys = {"IS2", "IS3", "IS4", "IS5", "IS6"}
    default = {"IS2", "IS3", "IS4", "IS5", "IS6"}


class StartingMode(Choice):
    """Guarantee one starting mode, or choose all starting modes randomly.

    `random` is accepted as the natural YAML spelling. Internally the named choice is
    `random_mode` because Archipelago reserves `random` for weighted option rolling.
    """

    display_name = "Starting mode"
    option_random_mode = 0
    option_is2 = 2
    option_is3 = 3
    option_is4 = 4
    option_is5 = 5
    option_is6 = 6
    default = 0

    @classmethod
    def from_text(cls, text: str):
        if text.lower() == "random":
            return cls(cls.option_random_mode)
        return super().from_text(text)

    @classmethod
    def get_option_name(cls, value: int) -> str:
        return "Random" if value == cls.option_random_mode else super().get_option_name(value)


class StartingModeCount(Range):
    """Total enabled modes whose access items are precollected at the start."""

    display_name = "Starting mode count"
    range_start = 1
    range_end = 5
    default = 1


class Goal(Choice):
    """Victory condition. By default, clear any ending once in every enabled mode."""

    display_name = "Goal"
    option_all_enabled_modes = 0
    option_mode_count = 1
    option_distinct_endings = 2
    default = 0


class ModesRequiredForVictory(Range):
    """With the Mode Count goal, clear any ending in this many enabled modes."""

    display_name = "Modes Required for Victory"
    range_start = 1
    range_end = 5
    default = 1


class EndingsRequiredForVictory(Range):
    """With the Distinct Endings goal, clear this many different endings across enabled modes."""

    display_name = "Distinct Endings Required for Victory"
    range_start = 1
    range_end = 22
    default = 5


class BossSanity(Choice):
    """Off removes boss checks; Bundled adds one per boss floor; Individual names Floors 5/6 bosses."""

    display_name = "BossSanity"
    option_off = 0
    option_bundled = 1
    option_individual = 2
    default = 1


class IndividualFloor3BossChecks(Toggle):
    """RNG warning: split Floor 3 Dreadful Foes into named checks instead of one combined check."""

    display_name = "Individual Floor 3 Boss Checks (RNG warning)"
    default = 0


class EndingSanity(Toggle):
    """Add named ending checks. Any Ending Cleared always remains for every enabled mode."""

    display_name = "EndingSanity"
    default = 1


class EncounterSanity(Toggle):
    """Add named Encounter-stage checks."""

    display_name = "EncounterSanity"
    default = 1


class FloorSanity(DefaultOnToggle):
    """Add first-reach checks for Floors 2–6. Floor 1 is the run start and never a check."""

    display_name = "FloorSanity"


class Ducksanity(Toggle):
    """Add four global checks for defeating Duck Lord, Gopnik, Crying Thief, and Fatty."""

    display_name = "Ducksanity"
    default = 0


class OperatorCopies(Choice):
    """Number of permits for each operator and permits required for E2."""

    display_name = "Operator permits required for E2"
    option_one = 1
    option_two = 2
    default = 2


class OperatorRoster(OptionSet):
    """Operators owned by the player. Only these operators have permits in the item pool."""

    display_name = "Owned operator roster"
    valid_keys = _CATALOG_OPERATORS
    default = _CATALOG_OPERATORS


class ModeQolProgression(Toggle):
    """Place mode-signature permits in the starting sphere before gated modes are needed.

    IS2 requests two Thorns permits, IS3 requests two Texas the Omertosa permits,
    and IS6 requests one Raidian permit. IS4 and IS5 add no permit guarantee.
    """

    display_name = "Mode QoL Progression"
    default = 0


class CoreUnit(OptionSet):
    """Start with both permits for exactly one owned operator, or leave empty to disable.

    This requires Operator Permits Required for E2 to be Two. The two permits are
    removed from the randomized pool rather than duplicated.
    """

    display_name = "Core Unit (choose zero or one operator)"
    valid_keys = _CATALOG_OPERATORS
    default = frozenset()


class PreferredClassPool(OptionSet):
    """Choose at most one owned operator per class for guaranteed starting-sphere permits.

    Selected permits remain randomized but are forced into reachable checks that do not
    require a non-starting mode's Access item.
    """

    display_name = "Preferred Class Pool (at most one operator per class)"
    valid_keys = _CATALOG_OPERATORS
    default = frozenset()


class StartWithISModeUnlocksHinted(Toggle):
    """Create free starting hints for every enabled IS mode Access item that is placed."""

    display_name = "Start with IS Mode Unlocks Hinted"
    default = 0


@dataclass
class ArknightsISOptions(PerGameCommonOptions):
    enabled_modes: EnabledModes
    starting_mode: StartingMode
    starting_mode_count: StartingModeCount
    goal: Goal
    modes_required_for_victory: ModesRequiredForVictory
    endings_required_for_victory: EndingsRequiredForVictory
    boss_sanity: BossSanity
    individual_floor_3_boss_checks: IndividualFloor3BossChecks
    ending_sanity: EndingSanity
    encounter_sanity: EncounterSanity
    floor_sanity: FloorSanity
    ducksanity: Ducksanity
    operator_copies: OperatorCopies
    operator_roster: OperatorRoster
    mode_qol_progression: ModeQolProgression
    core_unit: CoreUnit
    preferred_class_pool: PreferredClassPool
    start_with_is_mode_unlocks_hinted: StartWithISModeUnlocksHinted
