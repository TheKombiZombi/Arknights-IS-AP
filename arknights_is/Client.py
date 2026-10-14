"""Manual companion client for Arknights Integrated Strategies Archipelago seeds.

The client never connects to, automates, or modifies Arknights. It can explicitly enable
local screen capture to recognize and report checks, or import screenshots for manual review.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import Iterable
from typing import Any

from CommonClient import (
    ClientCommandProcessor,
    CommonContext,
    get_base_parser,
    gui_enabled,
    logger,
    server_loop,
)
from NetUtils import ClientStatus, Hint
import Utils

from . import CATALOG, GAME, ITEM_IDS, LOC_IDS
from .DashboardState import (
    MODES,
    checked_union,
    effective_received_names,
    filter_unresolved_locations,
    goal_progress,
    retire_location_ids,
)
from .ScreenRecognition import RecognitionBatch, RecognitionResult, recognize_path


class Commands(ClientCommandProcessor):
    def _cmd_unlocked(self) -> bool:
        counts = Counter(self.ctx.effective_received_item_names())
        if not counts:
            self.output("No permissions received yet.")
            return True
        for name, count in sorted(counts.items()):
            suffix = (
                f" ({count}/2)"
                if name.endswith(" Permit")
                else (f" ×{count}" if count > 1 else "")
            )
            self.output(name + suffix)
        return True

    def _cmd_mode_hints(self) -> bool:
        lines = self.ctx.mode_unlock_hint_lines()
        if lines:
            self.output("Free starting mode-access hints recorded by the server:")
            for line in lines:
                self.output("  " + line)
        elif self.ctx.start_with_is_mode_unlocks_hinted:
            self.output(
                "This seed requested mode-access starting hints, but the server returned none. "
                "The room generator or host may not have preserved precollected hints."
            )
        else:
            self.output("This seed did not request automatic mode-access starting hints.")
        return True

    def _cmd_check(self, *words: str) -> bool:
        matches = filter_unresolved_locations(
            self.ctx.location_ids,
            checked_union(self.ctx.checked_locations, self.ctx.locations_checked),
            " ".join(words),
        )
        if len(matches) != 1:
            self.output(
                f"Expected one unchecked location match; found {len(matches)}. "
                "Use /missing <text> to refine."
            )
            return False
        location, code = matches[0]
        self.output(f"Submitting: {location}")
        if " — Ending: " in location:
            return self.ctx.complete_ending(location, code)
        if location.endswith(" — Any Ending Cleared"):
            return self.ctx.complete_mode(location.split(" — ", 1)[0])
        return self.ctx.submit_locations([code], f"manual check: {location}")

    def _cmd_complete_ending(self, *words: str) -> bool:
        matches = [
            (name, code)
            for name, code in self.ctx.location_ids.items()
            if " — Ending: " in name and " ".join(words).casefold() in name.casefold()
        ]
        if len(matches) != 1:
            self.output(
                f"Expected one ending match; found {len(matches)}. "
                "Use /complete-ending <unique ending fragment>."
            )
            return False
        location, code = matches[0]
        return self.ctx.complete_ending(location, code)

    def _cmd_complete_mode(self, mode: str = "") -> bool:
        mode = mode.upper()
        if mode not in MODES:
            self.output("Usage: /complete-mode IS2")
            return False
        return self.ctx.complete_mode(mode)

    def _cmd_retire(self, mode: str = "") -> bool:
        mode = mode.upper()
        if mode not in MODES:
            self.output("Usage: /retire IS2")
            return False
        pending = retire_location_ids(
            self.ctx.location_ids,
            mode,
            checked_union(self.ctx.checked_locations, self.ctx.locations_checked),
        )
        self.output(
            f"Retiring would submit {len(pending)} unresolved non-goal {mode} locations. "
            f"Re-run as /retire-confirm {mode} to submit."
        )
        return True

    def _cmd_retire_confirm(self, mode: str = "") -> bool:
        mode = mode.upper()
        if mode not in MODES:
            self.output("Usage: /retire-confirm IS2")
            return False
        pending = retire_location_ids(
            self.ctx.location_ids,
            mode,
            checked_union(self.ctx.checked_locations, self.ctx.locations_checked),
        )
        return self.ctx.submit_locations(pending, f"retire {mode}", report_goal=False)

    def _cmd_recognize(self, *words: str) -> bool:
        path = " ".join(words).strip()
        if not path:
            self.output("Usage: /recognize <screenshot-or-directory>")
            return False
        batch = self.ctx.analyze_screenshots(path)
        for result in batch.results:
            self.output(
                f"Recognized {result.kind}: {result.title} "
                f"({result.confidence_summary}) from {result.source}"
            )
            for location in result.location_names:
                self.output(f"  proposed check: {location}")
            if result.needs_ending_record:
                self.output(f"  proposed ending record: {result.ending_location}")
        for issue in batch.issues:
            self.output(f"Not recognized: {issue.source}: {issue.message}")
        if batch.results:
            self.output(
                "Nothing has been submitted. Review the proposal, then run "
                "/recognize-confirm to submit it."
            )
            return True
        return False

    def _cmd_recognize_confirm(self) -> bool:
        if not self.ctx.pending_recognitions:
            self.output("No recognized screenshot proposal is awaiting confirmation.")
            return False
        return self.ctx.submit_recognition_results()


class Context(CommonContext):
    game = GAME
    items_handling = 0b111
    command_processor = Commands
    goal = "all_enabled_modes"
    enabled_modes = set(MODES)
    starting_modes: set[str] = set()
    victory_required = 1
    operator_permits_required_for_e2 = 2
    operator_roster: set[str] = set(CATALOG["operators"])
    location_ids = LOC_IDS
    precollected_unlocks: tuple[str, ...] = ()
    balance_precollected_unlocks: tuple[str, ...] = ()
    completed_endings: set[str]
    ending_goal_storage_key: str | None
    pending_recognitions: tuple[RecognitionResult, ...]
    world_version = "unknown"
    core_unit: str | None = None
    core_starting_items: tuple[str, ...] = ()
    start_with_is_mode_unlocks_hinted = False
    requested_start_hints: tuple[str, ...] = ()
    starting_hints: tuple[Hint, ...] = ()
    hints_storage_key: str | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.completed_endings = set()
        self.ending_goal_storage_key = None
        self.pending_recognitions = ()

    def effective_received_item_names(self) -> list[str]:
        return effective_received_names(
            (self.item_name(item.item) for item in self.items_received),
            self.precollected_unlocks,
        )

    @staticmethod
    def _coerce_hints(value: Any) -> tuple[Hint, ...]:
        if not isinstance(value, (list, tuple, set)):
            return ()
        result = []
        for entry in value:
            if isinstance(entry, Hint):
                result.append(entry)
            elif isinstance(entry, (list, tuple)) and len(entry) == 8:
                try:
                    result.append(Hint(*entry))
                except (TypeError, ValueError):
                    continue
        return tuple(result)

    def mode_unlock_hint_lines(self) -> list[str]:
        lines = []
        for hint in self.starting_hints:
            if hint.receiving_player != self.slot:
                continue
            item_name = self.item_name(hint.item)
            if not item_name.endswith(" Access"):
                continue
            slot_info = self.slot_info.get(hint.finding_player)
            game = slot_info.game if slot_info else self.game
            location_name = self.location_names.get(game, {}).get(
                hint.location, f"Unknown location {hint.location}"
            )
            finder = self.player_names.get(
                hint.finding_player, f"Player {hint.finding_player}"
            )
            lines.append(f"{item_name}: {location_name} in {finder}'s world")
        return sorted(lines)

    def item_name(self, item_id: int) -> str:
        return self.item_names[self.game].get(item_id, f"Unknown item {item_id}")

    def can_submit_checks(self) -> bool:
        return self.server is not None and self.slot is not None

    def goal_reached_with(self, new_locations: int | Iterable[int] | None = None) -> bool:
        checked = checked_union(self.checked_locations, self.locations_checked)
        if isinstance(new_locations, int):
            checked.add(new_locations)
        elif new_locations is not None:
            checked.update(new_locations)
        return goal_progress(
            self.goal,
            self.enabled_modes,
            self.victory_required,
            checked,
            self.location_ids,
            self.completed_endings,
        ).reached

    @staticmethod
    def _valid_completion_records(ending_names: Iterable[str]) -> set[str]:
        return {
            name
            for name in ending_names
            if name in LOC_IDS
            and (" — Ending: " in name or name.endswith(" — Any Ending Cleared"))
        }

    def _ending_completion_message(self, ending_names: Iterable[str]) -> dict[str, Any] | None:
        names = sorted(self._valid_completion_records(ending_names) - self.completed_endings)
        if not names or not self.ending_goal_storage_key:
            return None
        self.completed_endings.update(names)
        return {
            "cmd": "Set",
            "key": self.ending_goal_storage_key,
            "default": [],
            "want_reply": True,
            "operations": [{"operation": "update", "value": names}],
        }

    def complete_ending(self, location: str, location_id: int) -> bool:
        """Record an ending earned in Arknights, even if its item was remotely collected."""

        if not self.can_submit_checks():
            self.command_processor(self).output("Connect to a slot before recording an ending.")
            return False
        already_checked = location_id in checked_union(self.checked_locations, self.locations_checked)
        return self.submit_locations(
            [] if already_checked else [location_id],
            f"complete ending: {location}",
            record_endings=[location],
            allow_empty=True,
        )

    def complete_mode(self, mode: str) -> bool:
        """Record a mode clear locally even if its Any Ending check was released remotely."""

        location = f"{mode} — Any Ending Cleared"
        location_id = self.location_ids.get(location)
        if location_id is None:
            self.command_processor(self).output(f"{mode} is not active for this slot.")
            return False
        if not self.can_submit_checks():
            self.command_processor(self).output("Connect to a slot before recording a mode clear.")
            return False
        already_checked = location_id in checked_union(
            self.checked_locations, self.locations_checked
        )
        return self.submit_locations(
            [] if already_checked else [location_id],
            f"complete mode: {mode}",
            record_endings=[location],
            allow_empty=True,
        )

    def analyze_screenshots(self, path: str) -> RecognitionBatch:
        """Read only a path explicitly supplied by the player and stage proposals locally."""

        batch = recognize_path(
            path,
            CATALOG,
            self.location_ids,
            checked_union(self.checked_locations, self.locations_checked),
            self.completed_endings,
        )
        self.pending_recognitions = batch.results
        return batch

    def submit_recognition_results(
        self, results: Iterable[RecognitionResult] | None = None
    ) -> bool:
        """Submit a recognition proposal after manual confirmation or opt-in live capture."""

        proposals = tuple(self.pending_recognitions if results is None else results)
        if not proposals:
            self.command_processor(self).output(
                "No recognized screenshot proposal is awaiting confirmation."
            )
            return False
        checked = checked_union(self.checked_locations, self.locations_checked)
        pending_ids: set[int] = set()
        ending_records: set[str] = set()
        for proposal in proposals:
            for location in proposal.location_names:
                code = self.location_ids.get(location)
                if code is not None and code not in checked:
                    pending_ids.add(code)
            if (
                proposal.needs_ending_record
                and proposal.ending_location in LOC_IDS
                and proposal.ending_location not in self.completed_endings
            ):
                ending_records.add(proposal.ending_location)
        submitted = self.submit_locations(
            pending_ids,
            "confirmed screenshot recognition",
            record_endings=ending_records,
            allow_empty=bool(ending_records),
        )
        if submitted:
            self.pending_recognitions = ()
        return submitted

    def submit_locations(
        self,
        locations: Iterable[int],
        task_name: str,
        *,
        report_goal: bool = True,
        record_endings: Iterable[str] = (),
        allow_empty: bool = False,
    ) -> bool:
        if not self.can_submit_checks():
            self.command_processor(self).output("Connect to a slot before submitting checks.")
            return False
        checked = checked_union(self.checked_locations, self.locations_checked)
        pending = sorted(set(locations) - checked)
        completion_message = self._ending_completion_message(record_endings)
        if not pending and completion_message is None:
            self.command_processor(self).output("No unresolved locations to submit.")
            return False
        if not pending and not allow_empty:
            self.command_processor(self).output("No unresolved locations to submit.")
            return False

        self.locations_checked.update(pending)
        messages: list[dict[str, Any]] = []
        if pending:
            messages.append({"cmd": "LocationChecks", "locations": pending})
        if completion_message is not None:
            messages.append(completion_message)
        if report_goal and self.goal_reached_with():
            messages.append({"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL})
            self.command_processor(self).output(
                "Victory condition reached. Reporting goal completion to Archipelago."
            )
        Utils.async_start(self.send_msgs(messages), name=task_name)
        if pending:
            self.command_processor(self).output(f"Submitted {len(pending)} location check(s).")
        elif completion_message is not None:
            self.command_processor(self).output("Recorded ending completion without submitting a check.")
        self._refresh_dashboard()
        return True

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    async def connection_closed(self):
        await super().connection_closed()
        self._refresh_dashboard()

    def run_gui(self):
        from .Dashboard import ArknightsISManager

        self.ui = ArknightsISManager(self)
        self.ui_task = asyncio.create_task(self.ui.async_run(), name="UI")

    def _refresh_dashboard(self):
        if self.ui and hasattr(self.ui, "request_refresh"):
            self.ui.request_refresh()

    def on_package(self, cmd: str, args: dict[str, Any]):
        if cmd == "Connected":
            slot_data = args.get("slot_data", {})
            self.world_version = str(slot_data.get("world_version", "unknown/legacy seed"))
            self.goal = slot_data.get("goal", "all_enabled_modes")
            self.enabled_modes = set(slot_data.get("enabled_modes", MODES))
            self.starting_modes = set(slot_data.get("starting_modes", ()))
            self.operator_permits_required_for_e2 = int(
                slot_data.get("operator_permits_required_for_e2", 2)
            )
            self.operator_roster = set(slot_data.get("operator_roster", CATALOG["operators"]))
            self.precollected_unlocks = tuple(slot_data.get("precollected_unlocks", ()))
            self.core_unit = slot_data.get("core_unit")
            self.core_starting_items = tuple(slot_data.get("core_starting_items", ()))
            self.start_with_is_mode_unlocks_hinted = bool(
                slot_data.get("start_with_is_mode_unlocks_hinted", False)
            )
            self.requested_start_hints = tuple(slot_data.get("requested_start_hints", ()))
            self.balance_precollected_unlocks = tuple(
                slot_data.get("balance_precollected_unlocks", ())
            )
            active_codes = slot_data.get("active_location_ids")
            if active_codes is None:
                self.location_ids = LOC_IDS
            else:
                active = {int(code) for code in active_codes}
                self.location_ids = {
                    name: code for name, code in LOC_IDS.items() if code in active
                }
            requirement_key = (
                "endings_required_for_victory"
                if self.goal == "distinct_endings"
                else "modes_required_for_victory"
            )
            self.victory_required = int(slot_data.get(requirement_key, 1))
            self.completed_endings = set()
            self.ending_goal_storage_key = (
                f"arknights_is_completed_endings_{self.team}_{self.slot}"
            )
            self.hints_storage_key = f"_read_hints_{self.team}_{self.slot}"
            self.starting_hints = ()
            Utils.async_start(
                self.send_msgs([
                    {
                        "cmd": "SetNotify",
                        "keys": [self.ending_goal_storage_key, self.hints_storage_key],
                    },
                    {
                        "cmd": "Get",
                        "keys": [self.ending_goal_storage_key, self.hints_storage_key],
                    },
                ]),
                name="load completion records and starting hints",
            )
            logger.info(
                "Connected. Goal: %s (enabled modes: %s; starting modes: %s).",
                self.goal,
                ", ".join(sorted(self.enabled_modes)),
                ", ".join(sorted(self.starting_modes)) or "none reported",
            )
            logger.info(
                "Use the Overview, Check Submission, Unlock Tracker, and Screenshot Reporter "
                "tabs, or /unlocked, /missing, /check, /complete-mode, /retire, and /hint."
            )
            if self.balance_precollected_unlocks:
                logger.info(
                    "Seed balance precollected %d unlock(s); see the Overview tab or /unlocked.",
                    len(self.balance_precollected_unlocks),
                )
        if cmd == "Retrieved":
            keys = args.get("keys", {})
            if self.ending_goal_storage_key:
                value = keys.get(self.ending_goal_storage_key)
                if isinstance(value, list):
                    self.completed_endings = self._valid_completion_records(
                        name for name in value if isinstance(name, str)
                    )
            if self.hints_storage_key and self.hints_storage_key in keys:
                self.starting_hints = self._coerce_hints(keys[self.hints_storage_key])
        if cmd == "SetReply" and args.get("key") == self.ending_goal_storage_key:
            value = args.get("value")
            if isinstance(value, list):
                self.completed_endings = self._valid_completion_records(
                    name for name in value if isinstance(name, str)
                )
        if cmd == "SetReply" and args.get("key") == self.hints_storage_key:
            self.starting_hints = self._coerce_hints(args.get("value"))
        if cmd in {"Connected", "ReceivedItems", "RoomUpdate", "Retrieved", "SetReply"}:
            if cmd in {"Retrieved", "SetReply"} and self.goal_reached_with():
                Utils.async_start(
                    self.send_msgs(
                        [{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}]
                    ),
                    name="report restored goal",
                )
            self._refresh_dashboard()


def main():
    Utils.init_logging("Arknights IS Manual Client")
    parser = get_base_parser()
    parser.add_argument("--name", help="Archipelago slot name")
    args = parser.parse_args()

    async def run():
        ctx = Context(args.connect, args.password)
        ctx.auth = args.name
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="ServerLoop")
        if gui_enabled:
            ctx.run_gui()
        await ctx.exit_event.wait()
        ctx.server_address = None
        await ctx.shutdown()

    asyncio.run(run())


if __name__ == "__main__":
    main()
