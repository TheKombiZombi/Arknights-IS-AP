"""Pure state helpers shared by the graphical companion and its tests."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

MODES = ("IS2", "IS3", "IS4", "IS5", "IS6")
ALL_MODES = "All modes"
ALL_CLASSES = "All classes"
ARKNIGHTS_CLASSES = (
    "Vanguard",
    "Guard",
    "Defender",
    "Sniper",
    "Caster",
    "Medic",
    "Supporter",
    "Specialist",
)


@dataclass(frozen=True)
class GoalProgress:
    label: str
    completed: int
    required: int

    @property
    def reached(self) -> bool:
        return self.completed >= self.required


@dataclass(frozen=True)
class OperatorUnlock:
    """View-model record for one selected operator and its optional packaged portrait."""

    name: str
    operator_class: str
    permits: int
    required: int
    portrait_file: str

    @property
    def unlocked(self) -> bool:
        return self.permits > 0


@dataclass(frozen=True)
class UnlockTracker:
    operators: tuple[OperatorUnlock, ...]
    squads: tuple[tuple[str, bool], ...]
    modes: tuple[tuple[str, bool, bool], ...]


def checked_union(server_checked: Iterable[int], locally_checked: Iterable[int]) -> set[int]:
    return set(server_checked) | set(locally_checked)


def filter_unresolved_locations(
    location_ids: Mapping[str, int],
    checked: Iterable[int],
    query: str = "",
    mode: str = ALL_MODES,
) -> list[tuple[str, int]]:
    """Return unresolved locations sorted by name, narrowed by mode and substring."""

    checked_ids = set(checked)
    needle = query.strip().casefold()
    result = []
    for name, location_id in location_ids.items():
        location_mode = name.split(" — ", 1)[0]
        if location_id in checked_ids or (mode != ALL_MODES and location_mode != mode):
            continue
        if needle and needle not in name.casefold():
            continue
        result.append((name, location_id))
    return sorted(result, key=lambda pair: pair[0].casefold())


def retire_location_ids(
    location_ids: Mapping[str, int], mode: str, checked: Iterable[int]
) -> list[int]:
    """Return unresolved non-goal checks for one mode in stable order."""

    if mode not in MODES:
        return []
    checked_ids = set(checked)
    prefix = f"{mode} — "
    return [
        location_id
        for name, location_id in sorted(location_ids.items())
        if name.startswith(prefix)
        and not name.endswith(" — Any Ending Cleared")
        and location_id not in checked_ids
    ]


def goal_progress(
    goal: str,
    enabled_modes: Iterable[str],
    required: int,
    checked: Iterable[int],
    location_ids: Mapping[str, int],
    completed_endings: Iterable[str] | None = None,
) -> GoalProgress:
    enabled = set(enabled_modes)
    if goal == "distinct_endings":
        eligible = {
            name
            for name in location_ids
            if name.split(" — ", 1)[0] in enabled and " — Ending: " in name
        }
        # Location checks can be remotely collected when their item belongs to a player whose
        # game has finished. Only an explicit local ending completion records victory progress.
        completed = set(completed_endings or ())
        return GoalProgress("Distinct endings", len(eligible & completed), required)

    # Any Ending Cleared can be remotely collected when its placed item is released after
    # another player's completion. Count only modes represented by an explicit locally earned
    # ending record; server check state alone is not proof that this slot cleared the mode.
    completed_modes = {
        name.split(" — ", 1)[0]
        for name in set(completed_endings or ())
        if (
            " — Ending: " in name or name.endswith(" — Any Ending Cleared")
        ) and name.split(" — ", 1)[0] in enabled
    }
    completed = len(completed_modes)
    target = len(enabled) if goal == "all_enabled_modes" else required
    label = "Enabled modes cleared" if goal == "all_enabled_modes" else "Modes cleared"
    return GoalProgress(label, completed, target)


def filter_operator_unlocks(
    operators: Iterable[OperatorUnlock],
    operator_class: str = ALL_CLASSES,
    unlocked_only: bool = False,
) -> list[OperatorUnlock]:
    """Filter operator view records without coupling tests to Kivy widgets."""

    if operator_class != ALL_CLASSES and operator_class not in ARKNIGHTS_CLASSES:
        return []
    return [
        operator
        for operator in operators
        if (operator_class == ALL_CLASSES or operator.operator_class == operator_class)
        and (not unlocked_only or operator.unlocked)
    ]


def effective_received_names(
    received_item_names: Iterable[str], precollected_item_names: Iterable[str]
) -> list[str]:
    """Merge server inventory with slot-data starts without double-counting either source.

    Modern servers send precollected items through ReceivedItems when the client requests
    remote start inventory. Slot data remains a compatibility/diagnostic fallback.
    """

    received = Counter(received_item_names)
    precollected = Counter(precollected_item_names)
    for name, count in precollected.items():
        received[name] = max(received[name], count)
    return list(received.elements())


def build_unlock_tracker(
    catalog: Mapping[str, object],
    operator_classes: Mapping[str, str],
    received_item_names: Sequence[str],
    enabled_modes: Iterable[str],
    starting_modes: Iterable[str],
    permits_required: int = 2,
    operator_roster: Iterable[str] | None = None,
) -> UnlockTracker:
    if set(operator_classes) != set(catalog["operators"]):  # type: ignore[arg-type,index]
        raise ValueError("operator class metadata does not match the operator catalog")
    if set(operator_classes.values()) - set(ARKNIGHTS_CLASSES):
        raise ValueError("operator class metadata contains an unknown class")

    counts = Counter(received_item_names)
    selected = set(catalog["operators"] if operator_roster is None else operator_roster)  # type: ignore[index]
    unknown = selected - set(operator_classes)
    if unknown:
        raise ValueError(f"operator roster contains unknown operators: {sorted(unknown)}")
    operators = tuple(
        OperatorUnlock(
            operator,
            operator_classes[operator],
            min(permits_required, counts[f"{operator} Permit"]),
            permits_required,
            f"{index:03d}.png",
        )
        for index, operator in enumerate(catalog["operators"])  # type: ignore[index]
        if operator in selected
    )

    enabled = set(enabled_modes)
    starting = set(starting_modes)
    squads = []
    for mode in MODES:
        if mode not in enabled:
            continue
        for squad in catalog["squads"][mode]:  # type: ignore[index]
            if squad == "Leader Squad":
                continue
            item_name = f"{mode} — {squad}"
            squads.append((item_name, counts[item_name] > 0))

    mode_access = tuple(
        (mode, mode in starting or counts[f"{mode} Access"] > 0, mode in starting)
        for mode in MODES
        if mode in enabled
    )
    return UnlockTracker(operators, tuple(squads), mode_access)
