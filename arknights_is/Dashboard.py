"""Kivy/KivyMD dashboard embedded in Archipelago's standard GameManager."""
from __future__ import annotations

from collections import Counter
from importlib.resources import files
import io
from pathlib import Path
import threading

# kvui must be imported before any direct Kivy import for frozen Archipelago builds.
from kvui import (
    ButtonsPrompt,
    Clock,
    GameManager,
    MDBoxLayout,
    MDButton,
    MDButtonText,
    MDLabel,
    MDScrollView,
    dp,
)
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.core.image import Image as CoreImage
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.popup import Popup
from kivy.utils import escape_markup

from . import CATALOG, OPERATOR_CLASSES
from .DashboardState import (
    ALL_CLASSES,
    ALL_MODES,
    ARKNIGHTS_CLASSES,
    MODES,
    build_unlock_tracker,
    checked_union,
    filter_operator_unlocks,
    filter_unresolved_locations,
    goal_progress,
    retire_location_ids,
)
from .ScreenRecognition import (
    RecognitionBatch,
    RecognitionError,
    RecognitionResult,
    capability_problem,
    capture_capability_problem,
    recognize_live_capture,
)


class ArknightsISManager(GameManager):
    base_title = "Arknights IS Manual Client"
    logging_pairs = [("Client", "Archipelago")]
    max_location_rows = 150

    def build(self):
        container = super().build()

        self.overview_label = self._scrolling_label()
        self.add_client_tab("Overview", self._scroll(self.overview_label), index=0)

        self.search_input = TextInput(
            hint_text="Search unresolved locations",
            multiline=False,
            size_hint_y=None,
            height=dp(42),
        )
        self.search_input.bind(text=lambda *_: self.refresh_checks())
        self.mode_filter = Spinner(
            text=ALL_MODES,
            values=(ALL_MODES, *MODES),
            size_hint=(None, None),
            size=(dp(130), dp(42)),
        )
        self.mode_filter.bind(text=lambda *_: self.refresh_checks())

        filters = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8)
        )
        filters.add_widget(self.search_input)
        filters.add_widget(self.mode_filter)

        self.location_summary = MDLabel(size_hint_y=None, height=dp(30))
        self.location_rows = MDBoxLayout(
            orientation="vertical", size_hint_y=None, spacing=dp(3), padding=(0, dp(4))
        )
        self.location_rows.bind(minimum_height=self.location_rows.setter("height"))
        location_scroll = MDScrollView()
        location_scroll.add_widget(self.location_rows)

        self.retire_mode = Spinner(
            text=MODES[0], values=MODES, size_hint=(None, None), size=(dp(110), dp(40))
        )
        retire_button = self._button("Retire unresolved mode checks", self.confirm_retire)
        retire_bar = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(46), spacing=dp(8)
        )
        retire_bar.add_widget(self.retire_mode)
        retire_bar.add_widget(retire_button)

        checks = MDBoxLayout(orientation="vertical", spacing=dp(4), padding=dp(8))
        checks.add_widget(filters)
        checks.add_widget(self.location_summary)
        checks.add_widget(location_scroll)
        checks.add_widget(retire_bar)
        self.add_client_tab("Check Submission", checks, index=1)

        self.operator_class_filter = Spinner(
            text=ALL_CLASSES,
            values=(ALL_CLASSES, *ARKNIGHTS_CLASSES),
            size_hint=(None, None),
            size=(dp(150), dp(42)),
        )
        self.operator_class_filter.bind(text=lambda *_: self.refresh_unlocks())
        self.operator_unlock_filter = Spinner(
            text="All operators",
            values=("All operators", "Unlocked only"),
            size_hint=(None, None),
            size=(dp(145), dp(42)),
        )
        self.operator_unlock_filter.bind(text=lambda *_: self.refresh_unlocks())
        unlock_filters = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8)
        )
        unlock_filters.add_widget(self.operator_class_filter)
        unlock_filters.add_widget(self.operator_unlock_filter)
        self.unlock_summary = self._scrolling_label()
        self.operator_tiles = GridLayout(
            cols=3,
            spacing=dp(8),
            padding=dp(4),
            size_hint_y=None,
            row_default_height=dp(178),
            row_force_default=True,
        )
        self.operator_tiles.bind(
            minimum_height=self.operator_tiles.setter("height")
        )
        self.operator_tiles.bind(
            width=lambda grid, width: setattr(grid, "cols", max(2, int(width // dp(150))))
        )
        self.unlock_summary_scroll = MDScrollView(
            size_hint=(None, 1),
            width=dp(300),
            bar_width=dp(10),
            scroll_type=["bars", "content"],
        )
        self.unlock_summary_scroll.add_widget(self.unlock_summary)
        self.operator_scroll = MDScrollView(
            bar_width=dp(10), scroll_type=["bars", "content"]
        )
        self.operator_scroll.add_widget(self.operator_tiles)
        unlock_body = MDBoxLayout(orientation="horizontal", spacing=dp(8))
        unlock_body.add_widget(self.unlock_summary_scroll)
        unlock_body.add_widget(self.operator_scroll)
        unlocks = MDBoxLayout(orientation="vertical", spacing=dp(4), padding=dp(8))
        unlocks.add_widget(unlock_filters)
        unlocks.add_widget(unlock_body)
        self.add_client_tab("Unlock Tracker", unlocks, index=2)

        self.recognition_path = TextInput(
            hint_text="Select or enter one 1920×1080 screenshot, or a directory",
            multiline=False,
            size_hint_y=None,
            height=dp(42),
        )
        recognition_path_row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(46), spacing=dp(8)
        )
        recognition_path_row.add_widget(self.recognition_path)
        recognition_path_row.add_widget(
            self._button("Browse…", self.open_recognition_picker, width=dp(140))
        )
        self.recognition_analyze_button = self._button(
            "Analyze selected path", self.analyze_recognition
        )
        self.recognition_confirm_button = self._button(
            "Confirm imported check(s)", self.confirm_recognition
        )
        self.recognition_confirm_button.disabled = True
        self.recognition_automation_button = self._button(
            "Start live capture + auto-submit", self.toggle_live_recognition
        )
        self.recognition_status = self._scrolling_label()
        recognition_problem = capability_problem()
        self.recognition_status.text = (
            recognition_problem
            or "Live capture is off. Start it explicitly for this client session to capture "
               "the primary 1920×1080 display in memory and automatically submit unique, "
               "high-confidence results. File import remains available for manual review."
        )
        recognition_controls = MDBoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(188), spacing=dp(6)
        )
        recognition_controls.add_widget(self.recognition_automation_button)
        recognition_controls.add_widget(recognition_path_row)
        recognition_controls.add_widget(self.recognition_analyze_button)
        recognition_controls.add_widget(self.recognition_confirm_button)
        recognition = MDBoxLayout(orientation="vertical", spacing=dp(6), padding=dp(8))
        recognition.add_widget(recognition_controls)
        recognition.add_widget(self._scroll(self.recognition_status))
        self.add_client_tab("Screenshot Reporter", recognition, index=3)

        self.pending_recognition_results = ()
        self.recognition_automation_event = None
        self.recognition_automation_busy = False
        self.recognition_automation_generation = 0
        self.last_live_capture_signature = None
        self.refresh_dashboard()
        return container

    @staticmethod
    def _button(text, callback, *, width=None):
        button_text = MDButtonText(text=text)
        button = MDButton(
            button_text,
            style="filled",
            theme_width="Custom",
            size_hint=((None if width is not None else 1), None),
            width=width or dp(100),
            height=dp(40),
        )
        button.button_text = button_text
        button.bind(on_release=callback)
        return button

    @staticmethod
    def _scrolling_label():
        label = MDLabel(
            text="",
            size_hint_y=None,
            padding=(dp(12), dp(12)),
            valign="top",
        )
        label.bind(width=lambda widget, width: setattr(widget, "text_size", (width, None)))
        label.bind(texture_size=lambda widget, size: setattr(widget, "height", size[1] + dp(24)))
        return label

    @staticmethod
    def _scroll(content):
        scroll = MDScrollView()
        scroll.add_widget(content)
        return scroll

    def request_refresh(self):
        """Schedule one refresh on Kivy's UI clock after a network packet."""
        Clock.schedule_once(lambda _dt: self.refresh_dashboard(), 0)

    def toggle_live_recognition(self, *_args):
        if self.recognition_automation_event is not None:
            self.stop_live_recognition()
            return
        problem = capture_capability_problem()
        if problem:
            self.recognition_status.text = problem
            return
        if not self.ctx.can_submit_checks():
            self.recognition_status.text = (
                "Connect to an Archipelago slot before starting automatic check submission."
            )
            return
        self.recognition_automation_generation += 1
        self.last_live_capture_signature = None
        self.recognition_automation_event = Clock.schedule_interval(
            self._live_recognition_tick, 3.0
        )
        self.recognition_automation_button.button_text.text = "Stop live capture"
        self.recognition_status.markup = True
        self.recognition_status.text = (
            "[b]Live capture and automatic submission are active.[/b]\n"
            "The primary display is sampled in memory every three seconds. Only a unique, "
            "high-confidence active check is sent; captures are not saved."
        )
        self._live_recognition_tick(0)

    def stop_live_recognition(self, *, message: str | None = None):
        self.recognition_automation_generation += 1
        self.recognition_automation_busy = False
        if self.recognition_automation_event is not None:
            self.recognition_automation_event.cancel()
            self.recognition_automation_event = None
        self.recognition_automation_button.button_text.text = (
            "Start live capture + auto-submit"
        )
        self.recognition_status.markup = False
        self.recognition_status.text = message or (
            "Live capture stopped. It must be started explicitly again for this client session."
        )

    def _live_recognition_tick(self, _dt):
        if self.recognition_automation_event is None or self.recognition_automation_busy:
            return
        if not self.ctx.can_submit_checks():
            self.stop_live_recognition(
                message="Live capture stopped because the Archipelago slot disconnected."
            )
            return
        self.recognition_automation_busy = True
        generation = self.recognition_automation_generation
        location_ids = dict(self.ctx.location_ids)
        checked = checked_union(self.ctx.checked_locations, self.ctx.locations_checked)
        completed_endings = set(self.ctx.completed_endings)

        def worker():
            signature = None
            result = None
            error = None
            try:
                signature, proposal = recognize_live_capture(
                    CATALOG,
                    location_ids,
                    checked,
                    completed_endings,
                    self.last_live_capture_signature,
                )
                if signature != self.last_live_capture_signature:
                    result = proposal
            except RecognitionError as exc:
                error = str(exc)
            except Exception as exc:  # ImageGrab and platform errors stay inside the UI boundary.
                error = f"Live capture failed safely: {exc}"
            Clock.schedule_once(
                lambda _elapsed, run=generation, captured=signature, proposal=result, failure=error: (
                    self._finish_live_recognition(run, captured, proposal, failure)
                ),
                0,
            )

        threading.Thread(
            target=worker, name="Arknights IS live screenshot OCR", daemon=True
        ).start()

    def _finish_live_recognition(
        self,
        generation: int,
        signature: str | None,
        result: RecognitionResult | None,
        error: str | None,
    ):
        if generation != self.recognition_automation_generation:
            return
        self.recognition_automation_busy = False
        if self.recognition_automation_event is None:
            return
        if signature is not None:
            self.last_live_capture_signature = signature
        if result is None:
            if error and error.startswith(
                ("Live capture failed safely:", "Expected a native", "Screenshot recognition is unavailable")
            ):
                self.stop_live_recognition(message=error)
                return
            if error and "already resolved" not in error:
                self.recognition_status.markup = False
                self.recognition_status.text = (
                    "Live capture is active; no check was sent. " + error
                )
            return
        if self.ctx.submit_recognition_results((result,)):
            submitted = ", ".join(result.location_names)
            if result.needs_ending_record and result.ending_location:
                submitted = (submitted + ", " if submitted else "") + result.ending_location
            self.recognition_status.markup = True
            self.recognition_status.text = (
                "[b]Automatically submitted a recognized result.[/b]\n"
                f"{escape_markup(result.title)} — {escape_markup(result.confidence_summary)}\n"
                f"{escape_markup(submitted)}\n\nLive capture remains active."
            )

    def on_stop(self):
        if hasattr(self, "recognition_automation_event"):
            self.stop_live_recognition()
        return super().on_stop()

    def open_recognition_picker(self, *_args):
        chooser = FileChooserListView(
            path=str(Path.home()),
            filters=["*.png", "*.jpg", "*.jpeg", "*.PNG", "*.JPG", "*.JPEG"],
            multiselect=False,
        )
        body = MDBoxLayout(orientation="vertical", spacing=dp(6), padding=dp(8))
        body.add_widget(chooser)
        buttons = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(46), spacing=dp(8)
        )
        popup = Popup(title="Choose screenshot or directory", content=body, size_hint=(0.92, 0.92))

        def use_selection(*_unused):
            if chooser.selection:
                self.recognition_path.text = chooser.selection[0]
                popup.dismiss()

        def use_folder(*_unused):
            self.recognition_path.text = chooser.path
            popup.dismiss()

        buttons.add_widget(self._button("Use selected image", use_selection))
        buttons.add_widget(self._button("Use current folder", use_folder))
        buttons.add_widget(self._button("Cancel", lambda *_unused: popup.dismiss()))
        body.add_widget(buttons)
        popup.open()

    def analyze_recognition(self, *_args):
        selected = self.recognition_path.text.strip()
        if not selected:
            self.recognition_status.text = "Choose or enter a screenshot or directory first."
            return
        self.pending_recognition_results = ()
        self.recognition_confirm_button.disabled = True
        self.recognition_analyze_button.disabled = True
        self.recognition_status.text = "Analyzing the selected image(s) locally…"

        def worker():
            try:
                batch = self.ctx.analyze_screenshots(selected)
                error = None
            except Exception as exc:  # Defensive UI boundary; recognition itself uses typed failures.
                batch = None
                error = str(exc)
            Clock.schedule_once(
                lambda _dt, result=batch, failure=error: self._finish_recognition(
                    result, failure
                ),
                0,
            )

        threading.Thread(target=worker, name="Arknights IS screenshot OCR", daemon=True).start()

    def _finish_recognition(self, batch: RecognitionBatch | None, error: str | None):
        self.recognition_analyze_button.disabled = False
        if error or batch is None:
            self.pending_recognition_results = ()
            self.recognition_confirm_button.disabled = True
            self.recognition_status.text = f"Recognition failed safely: {error or 'unknown error'}"
            return
        self.pending_recognition_results = batch.results
        self.recognition_confirm_button.disabled = not bool(batch.results)
        lines = [
            "[b]Nothing has been submitted.[/b] Review every proposal before confirming.",
            "",
        ]
        for result in batch.results:
            lines.extend(
                [
                    f"[b]{escape_markup(Path(result.source).name)}[/b]",
                    f"Recognized {escape_markup(result.kind)}: {escape_markup(result.title)}",
                    escape_markup(result.confidence_summary),
                    f"OCR: {escape_markup(repr(result.ocr_text))}",
                ]
            )
            lines.extend(
                f"Proposed check: {escape_markup(name)}" for name in result.location_names
            )
            if result.needs_ending_record:
                lines.append(
                    f"Proposed ending record: {escape_markup(result.ending_location or '')}"
                )
            lines.append("")
        for issue in batch.issues:
            lines.extend(
                [
                    f"[b]{escape_markup(Path(issue.source).name or issue.source)}[/b]",
                    "Not recognized; no action proposed: " + escape_markup(issue.message),
                    "",
                ]
            )
        if not batch.results:
            lines.append("No high-confidence actionable result was found.")
        self.recognition_status.text = "\n".join(lines)
        self.recognition_status.markup = True

    def confirm_recognition(self, *_args):
        proposals = tuple(self.pending_recognition_results)
        if not proposals:
            self.ctx.command_processor(self.ctx).output(
                "No recognized screenshot proposal is awaiting confirmation."
            )
            return
        if not self.ctx.can_submit_checks():
            self.ctx.command_processor(self.ctx).output(
                "Connect to a slot before submitting recognized checks."
            )
            return
        proposed_locations = [
            location for proposal in proposals for location in proposal.location_names
        ]
        proposed_records = [
            proposal.ending_location
            for proposal in proposals
            if proposal.needs_ending_record and proposal.ending_location
        ]
        summary = [*(f"• {name}" for name in proposed_locations)]
        summary.extend(f"• Record earned ending: {name}" for name in proposed_records)
        dialog = None

        def respond(choice: str):
            dialog.dismiss()
            if choice == "Submit recognized checks":
                if self.ctx.submit_recognition_results(proposals):
                    self.pending_recognition_results = ()
                    self.recognition_confirm_button.disabled = True
                    self.recognition_status.text = (
                        "Confirmed recognition proposal submitted. Select another screenshot "
                        "to analyze it explicitly."
                    )

        dialog = ButtonsPrompt(
            "Confirm recognized location checks",
            "Submit these explicitly reviewed actions?\n\n"
            + "\n".join(summary)
            + "\n\nThis cannot be undone from the client.",
            respond,
            "Cancel",
            "Submit recognized checks",
        )
        dialog.open()

    def refresh_dashboard(self):
        if not hasattr(self, "overview_label"):
            return
        checked = checked_union(self.ctx.checked_locations, self.ctx.locations_checked)
        progress = goal_progress(
            self.ctx.goal,
            self.ctx.enabled_modes,
            self.ctx.victory_required,
            checked,
            self.ctx.location_ids,
            self.ctx.completed_endings,
        )
        connected = self.ctx.server is not None and self.ctx.slot is not None
        slot_name = self.ctx.player_names.get(self.ctx.slot, self.ctx.auth or "—")
        enabled = ", ".join(sorted(self.ctx.enabled_modes)) or "None"
        starting = ", ".join(sorted(self.ctx.starting_modes)) or "None reported"
        names = self.ctx.effective_received_item_names()
        counts = Counter(names)
        core_unit = self.ctx.core_unit or "Off/not reported"
        core_count = counts[f"{self.ctx.core_unit} Permit"] if self.ctx.core_unit else 0
        hint_lines = self.ctx.mode_unlock_hint_lines()
        if hint_lines:
            hint_summary = "\n".join(f"• {escape_markup(line)}" for line in hint_lines)
        elif self.ctx.start_with_is_mode_unlocks_hinted:
            hint_summary = "Requested, but the connected server returned no mode-access hints"
        else:
            hint_summary = "Off/not requested"
        self.overview_label.text = (
            "[b]Connection[/b]\n"
            f"Status: {'Connected' if connected else 'Disconnected'}\n"
            f"Server: {self.ctx.server_address or '—'}\n"
            f"Slot: {slot_name}\n"
            f"Seed APWorld version: {self.ctx.world_version}\n\n"
            "[b]Goal progress[/b]\n"
            f"{progress.label}: {progress.completed} / {progress.required}"
            f"{'  ✓' if progress.reached else ''}\n"
            f"Checks submitted: {len(checked & set(self.ctx.location_ids.values()))} / "
            f"{len(self.ctx.location_ids)}\n\n"
            "[b]Modes[/b]\n"
            f"Enabled: {enabled}\n"
            f"Starting access: {starting}\n"
            f"Permits required for E2: {self.ctx.operator_permits_required_for_e2}\n"
            f"Core unit: {core_unit} ({core_count}/{self.ctx.operator_permits_required_for_e2} permits)\n"
            f"Balance-precollected unlocks: {len(self.ctx.balance_precollected_unlocks)}\n\n"
            "[b]Free starting mode-access hints[/b]\n"
            f"{hint_summary}"
        )
        self.overview_label.markup = True

        self.unlock_tracker = build_unlock_tracker(
            CATALOG,
            OPERATOR_CLASSES,
            names,
            self.ctx.enabled_modes,
            self.ctx.starting_modes,
            self.ctx.operator_permits_required_for_e2,
            self.ctx.operator_roster,
        )
        self.refresh_unlocks()
        self.refresh_checks()

    def refresh_unlocks(self):
        if not hasattr(self, "unlock_tracker"):
            return
        operators = filter_operator_unlocks(
            self.unlock_tracker.operators,
            self.operator_class_filter.text,
            self.operator_unlock_filter.text == "Unlocked only",
        )
        squad_lines = [
            f"{'✓' if unlocked else '·'} {name}"
            for name, unlocked in self.unlock_tracker.squads
        ]
        mode_lines = [
            f"{'✓' if unlocked else '·'} {mode} Access"
            f"{' (starting)' if starting_mode else ''}"
            for mode, unlocked, starting_mode in self.unlock_tracker.modes
        ]
        self.unlock_summary.text = "\n".join(
            [
                "[b]Mode access[/b]",
                *mode_lines,
                "",
                "[b]Squads[/b]",
                *squad_lines,
                "",
                f"[b]Operators ({len(operators)})[/b] — portrait tiles show permit count X/Y",
            ]
        )
        self.unlock_summary.markup = True
        self.operator_tiles.clear_widgets()
        for operator in operators:
            self.operator_tiles.add_widget(self._operator_tile(operator))

    @staticmethod
    def _asset_texture(category: str, filename: str):
        asset = files(__package__).joinpath("assets", category, filename)
        try:
            data = asset.read_bytes()
        except (FileNotFoundError, NotADirectoryError):
            return None
        return CoreImage(io.BytesIO(data), ext="png").texture

    @classmethod
    def _portrait_texture(cls, filename: str, *, locked: bool = False):
        category = "operators_locked" if locked else "operators"
        return cls._asset_texture(category, filename)

    @classmethod
    def _class_texture(cls, operator_class: str):
        return cls._asset_texture("classes", f"{operator_class}.png")

    def _operator_tile(self, operator):
        tile = MDBoxLayout(
            orientation="vertical",
            size_hint=(1, None),
            height=dp(174),
            padding=dp(4),
            spacing=dp(2),
        )
        texture = self._portrait_texture(
            operator.portrait_file, locked=not operator.unlocked
        )
        if texture is not None:
            tile.add_widget(Image(texture=texture, size_hint=(1, None), height=dp(90)))

        name_label = MDLabel(
            text=f"[b]{operator.name}[/b]  {operator.permits}/{operator.required}",
            markup=True,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(48 if texture is not None else 138),
            font_size=dp(14),
        )
        name_label.bind(
            width=lambda label, width: setattr(label, "text_size", (width, None))
        )
        tile.add_widget(name_label)

        class_row = MDBoxLayout(
            orientation="horizontal",
            adaptive_width=True,
            size_hint=(None, None),
            height=dp(24),
            spacing=dp(4),
            pos_hint={"center_x": 0.5},
        )
        class_texture = self._class_texture(operator.operator_class)
        if class_texture is not None:
            class_row.add_widget(
                Image(texture=class_texture, size_hint=(None, None), size=(dp(22), dp(22)))
            )
        class_row.add_widget(
            MDLabel(
                text=operator.operator_class,
                adaptive_width=True,
                size_hint_y=None,
                height=dp(24),
                valign="middle",
            )
        )
        tile.add_widget(class_row)
        return tile

    def refresh_checks(self):
        if not hasattr(self, "location_rows"):
            return
        checked = checked_union(self.ctx.checked_locations, self.ctx.locations_checked)
        matches = filter_unresolved_locations(
            self.ctx.location_ids, checked, self.search_input.text, self.mode_filter.text
        )
        self.location_rows.clear_widgets()
        shown = matches[: self.max_location_rows]
        for name, location_id in shown:
            button = self._button(
                name,
                lambda _button, n=name, code=location_id: self.confirm_check(n, code),
            )
            self.location_rows.add_widget(button)
        suffix = " — refine the search to see fewer" if len(matches) > len(shown) else ""
        self.location_summary.text = (
            f"{len(matches)} unresolved match{'es' if len(matches) != 1 else ''}; "
            f"showing {len(shown)}{suffix}"
        )

    def confirm_check(self, name: str, location_id: int):
        if not self.ctx.can_submit_checks():
            self.ctx.command_processor(self.ctx).output("Connect to a slot before submitting checks.")
            return
        dialog = None

        def respond(choice: str):
            dialog.dismiss()
            if choice == "Submit check":
                if " — Ending: " in name:
                    self.ctx.complete_ending(name, location_id)
                elif name.endswith(" — Any Ending Cleared"):
                    self.ctx.complete_mode(name.split(" — ", 1)[0])
                else:
                    self.ctx.submit_locations([location_id], f"manual check: {name}")

        dialog = ButtonsPrompt(
            "Confirm location check",
            (
                f"Submit this LocationChecks packet?\n\n{name}\n\n"
                + (
                    "This also records the ending toward the distinct-endings goal.\n\n"
                    if " — Ending: " in name else (
                        "This also records the locally earned mode clear toward victory.\n\n"
                        if name.endswith(" — Any Ending Cleared") else ""
                    )
                )
                + "This cannot be undone from the client."
            ),
            respond,
            "Cancel",
            "Submit check",
        )
        dialog.open()

    def confirm_retire(self, *_args):
        mode = self.retire_mode.text
        checked = checked_union(self.ctx.checked_locations, self.ctx.locations_checked)
        locations = retire_location_ids(self.ctx.location_ids, mode, checked)
        if not locations:
            self.ctx.command_processor(self.ctx).output(f"No unresolved {mode} checks to retire.")
            return
        if not self.ctx.can_submit_checks():
            self.ctx.command_processor(self.ctx).output("Connect to a slot before retiring checks.")
            return
        confirmation = f"Retire {mode}"
        dialog = None

        def respond(choice: str):
            dialog.dismiss()
            if choice == confirmation:
                self.ctx.submit_locations(locations, f"retire {mode}", report_goal=False)

        dialog = ButtonsPrompt(
            f"Retire all unresolved {mode} checks",
            f"This submits {len(locations)} unresolved non-goal checks for {mode}.\n\n"
            "The Any Ending Cleared goal check is deliberately excluded. This bulk action cannot be undone.",
            respond,
            "Cancel",
            confirmation,
        )
        dialog.open()
