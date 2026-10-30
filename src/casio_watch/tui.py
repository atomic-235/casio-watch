"""Textual TUI for Casio G-Shock BLE watches.

Interaction model follows lazygit/nvim: panels + a normal mode, single-key
actions, j/k selection, Enter to edit, Esc to cancel, and one bottom-line
prompt for text. No tabbing through form fields.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    Static,
)
from textual.widgets.option_list import Option

from casio_watch.backend import Backend, FakeBackend, RealBackend
from casio_watch.ble import connect_device, is_casio
from casio_watch.compat import configure_logging, install

SETTINGS_ORDER = [
    "time_format",
    "date_format",
    "language",
    "light_duration",
    "auto_light",
    "power_saving_mode",
    "button_tone",
    "time_adjustment",
    "time_adjustment_minutes_after_hour",
]
SETTING_LABELS = {
    "time_format": "Time format",
    "date_format": "Date format",
    "language": "Language",
    "light_duration": "Light duration",
    "auto_light": "Auto light",
    "power_saving_mode": "Power saving",
    "button_tone": "Button tone",
    "time_adjustment": "Time adjustment",
    "time_adjustment_minutes_after_hour": "Adjust minutes after hour",
}
CHOICES = {
    "time_format": ["12h", "24h"],
    "date_format": ["MM:DD", "DD:MM"],
    "language": ["English", "Spanish", "French", "German", "Italian", "Russian"],
    "light_duration": ["1.5s", "3s"],
}
BOOLEANS = {"auto_light", "power_saving_mode", "button_tone", "time_adjustment"}
ALARM_COUNT = 5
OP_TIMEOUT = 20
CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "casio-watch" / "config.json"

HELP_TEXT = """\
Keys (normal mode)

  1 / 2         Watch settings / Alarms panel
  tab           next panel
  j / k         move selection
  g / G         first / last row
  space         toggle value or alarm
  enter         edit value / open menu
  c             toggle hourly chime (alarms panel)
  /             filter rows
  s             scan and connect
  r             refresh from watch
  t             sync clock
  w             write changes (asks to confirm)
  esc           cancel / close
  ?             this help
  q             quit

Editing is a bottom-line prompt: enter commits, esc cancels.
No tab-through-fields; digits only type while the prompt is open.
"""


def load_config() -> dict[str, str]:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(address: str, name: str) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps({"address": address, "name": name}, indent=2))
    except OSError:
        pass


def format_seconds(total: int) -> str:
    hours, remainder = divmod(int(total), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class State(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    READY = auto()
    STALE = auto()


class ChoiceScreen(ModalScreen[str | None]):
    """lazygit-style option menu."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, title: str, options: list[str], current: str) -> None:
        super().__init__()
        self.title = title
        self.options = options
        self.current = current

    def compose(self) -> ComposeResult:
        with Container(id="menu"):
            yield Label(self.title)
            yield OptionList(
                *[Option(f"{value} *" if value == self.current else value, id=value) for value in self.options],
                id="choices",
            )

    def on_mount(self) -> None:
        choices = self.query_one("#choices", OptionList)
        choices.focus()
        for index, value in enumerate(self.options):
            if value == self.current:
                choices.highlighted = index

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("enter", "confirm", "Write"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, lines: list[str]) -> None:
        super().__init__()
        self.lines = lines

    def compose(self) -> ComposeResult:
        with Container(id="menu"):
            yield Label("Write these changes?")
            yield Static("\n".join(self.lines), id="confirm-lines")
            yield Static("enter write   esc cancel", classes="hint")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "dismiss", "Close"), Binding("question_mark", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Container(id="menu"):
            yield Static(HELP_TEXT)


class EditorInput(Input):
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def action_cancel(self) -> None:
        self.app.cancel_prompt()


class CasioTUI(App):
    CSS = """
    #sidebar { width: 30; padding: 0 1; border: round $primary; }
    #sidebar Static { padding-bottom: 1; }
    #main { width: 1fr; }
    #view-title { padding: 0 1; background: $boost; text-style: bold; }
    #filter { padding: 0 1; color: $text-muted; height: 1; }
    #table { height: 1fr; border: round $primary; }
    #editor { height: 3; border: round $accent; }
    #mode { height: 1; padding: 0 1; background: $boost; }
    #menu { width: 60; height: auto; padding: 1 2; border: thick $primary; background: $surface; }
    #confirm-lines { padding: 1 0; height: auto; }
    .hint { color: $text-muted; padding-top: 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "scan", "Scan"),
        Binding("r", "refresh", "Refresh"),
        Binding("t", "sync_time", "Sync"),
        Binding("w", "write", "Write"),
        Binding("1", "view('settings')", "Settings"),
        Binding("2", "view('alarms')", "Alarms"),
        Binding("tab", "next_view", "Panel"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "top", "Top", show=False),
        Binding("G", "bottom", "Bottom", show=False),
        Binding("space", "toggle", "Toggle"),
        Binding("c", "chime", "Chime"),
        Binding("slash", "filter", "Filter"),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(self, mock: bool = False) -> None:
        super().__init__()
        self.mock = mock
        self.backend: Backend | None = None
        self.state = State.DISCONNECTED
        self._lock = asyncio.Lock()

        self.view = "settings"
        self.filter_text = ""
        self.settings: dict[str, Any] = {}
        self.alarms: list[dict[str, Any]] = []
        self.adjustment = False
        self.timer = 0
        self.condition: dict[str, Any] = {}
        self.watch_name = ""
        self._baseline: dict[str, Any] = {}
        self._prompt_action: Any = None

        config = load_config()
        saved = config.get("address")
        self._address: str | None = saved if saved and saved != "MOCK" else None
        self._name = config.get("name", "") if self._address else ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("no watch", id="watch-name")
                yield Static("battery: --", id="battery")
                yield Static("temp: --", id="temp")
                yield Static("timer: --", id="timer")
                yield Static("read: --", id="read")
                yield Static("disconnected", id="conn")
            with Vertical(id="main"):
                yield Static("Settings", id="view-title")
                yield Static("", id="filter")
                yield DataTable(id="table", cursor_type="row", zebra_stripes=False)
        yield EditorInput(id="editor", placeholder="value")
        yield Static("-- NORMAL --", id="mode")
        yield Footer()

    def on_mount(self) -> None:
        configure_logging()
        self.query_one("#editor", EditorInput).display = False
        self.query_one("#filter", Static).display = False
        table = self.query_one(DataTable)
        table.focus()
        self.rebuild()
        self.set_state(State.DISCONNECTED)

    async def on_unmount(self) -> None:
        if self.backend is not None:
            try:
                await asyncio.wait_for(self.backend.disconnect(), timeout=5)
            except Exception:  # noqa: BLE001
                pass

    # ---------- state rendering ----------

    def set_state(self, state: State, detail: str = "") -> None:
        self.state = state
        labels = {
            State.DISCONNECTED: "disconnected",
            State.CONNECTING: "connecting...",
            State.READY: "ready",
            State.STALE: "stale - press r",
        }
        text = labels[state] + (f" | {detail}" if detail else "")
        self.query_one("#conn", Static).update(text)
        self.query_one("#mode", Static).update(f"-- {'NORMAL' if state is not State.CONNECTING else 'BUSY'} --")

    def set_mode(self, editing: bool) -> None:
        self.query_one("#mode", Static).update("-- EDIT --" if editing else "-- NORMAL --")

    def display_name(self, value: Any) -> str:
        if isinstance(value, bool):
            return "on" if value else "off"
        return str(value)

    def rebuild(self) -> None:
        table = self.query_one(DataTable)
        position = table.cursor_row if table.row_count else 0
        table.clear(columns=True)

        if self.view == "settings":
            self.query_one("#view-title", Static).update("Settings")
            table.add_column("Setting", key="name")
            table.add_column("Value", key="value")
            for key in SETTINGS_ORDER:
                label = SETTING_LABELS[key]
                value: Any
                if key == "time_adjustment":
                    value = self.adjustment
                elif key == "time_adjustment_minutes_after_hour":
                    value = self.settings.get(key, 30)
                else:
                    value = self.settings.get(key, "")
                if self.filter_text and self.filter_text.lower() not in f"{label} {value}".lower():
                    continue
                table.add_row(label, self.display_name(value), key=key)
        else:
            self.query_one("#view-title", Static).update("Alarms")
            table.add_column("Alarm", key="name")
            table.add_column("Time", key="value")
            table.add_column("On", key="on")
            table.add_column("Chime", key="chime")
            for index, alarm in enumerate(self.alarms[:ALARM_COUNT]):
                name = f"Alarm {index + 1}"
                if self.filter_text and self.filter_text.lower() not in name.lower():
                    continue
                table.add_row(
                    name,
                    f"{alarm['hour']:02d}:{alarm['minute']:02d}",
                    "on" if alarm["enabled"] else "off",
                    "chime" if index == 0 and alarm["hasHourlyChime"] else "",
                    key=f"alarm-{index}",
                )

        if table.row_count:
            table.move_cursor(row=min(position, table.row_count - 1))
        self.query_one("#filter", Static).display = bool(self.filter_text)

    def current_key(self) -> str | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    # ---------- panel/actions ----------

    def action_view(self, view: str) -> None:
        self.view = view
        self.rebuild()
        self.query_one(DataTable).focus()

    def action_next_view(self) -> None:
        self.action_view("alarms" if self.view == "settings" else "settings")

    def action_cursor_down(self) -> None:
        self.query_one(DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(DataTable).action_cursor_up()

    def action_top(self) -> None:
        self.query_one(DataTable).move_cursor(row=0)

    def action_bottom(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count:
            table.move_cursor(row=table.row_count - 1)

    def action_toggle(self) -> None:
        key = self.current_key()
        if key is None:
            return
        if self.view == "alarms":
            index = int(key.split("-")[1])
            self.alarms[index]["enabled"] = not self.alarms[index]["enabled"]
        elif key in BOOLEANS:
            if key == "time_adjustment":
                self.adjustment = not self.adjustment
            else:
                self.settings[key] = not self.settings.get(key, False)
        else:
            return
        self.rebuild()

    def action_chime(self) -> None:
        if self.view != "alarms" or not self.alarms:
            return
        self.alarms[0]["hasHourlyChime"] = not self.alarms[0]["hasHourlyChime"]
        self.rebuild()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_refresh(self) -> None:
        self.refresh_data()

    def action_scan(self) -> None:
        self.connect_watch()

    def action_sync_time(self) -> None:
        self.sync_time()

    def action_write(self) -> None:
        self.write_changes()

    def action_filter(self) -> None:
        self.open_prompt("filter rows", self.filter_text, self.apply_filter)

    def apply_filter(self, text: str) -> None:
        self.filter_text = text if text != self.filter_text else ""
        self.rebuild()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if key is None:
            return
        if self.view == "alarms":
            index = int(key.split("-")[1])
            alarm = self.alarms[index]
            self.open_prompt(
                "alarm time HH:MM",
                f"{alarm['hour']:02d}:{alarm['minute']:02d}",
                lambda value, i=index: self.apply_alarm_time(i, value),
            )
            return

        if key in CHOICES:
            self.choose(key)
        elif key == "time_adjustment_minutes_after_hour":
            self.open_prompt(
                "minutes after hour (0-59)",
                str(self.settings.get(key, 30)),
                lambda value: self.apply_minutes(key, value),
            )
        elif key in BOOLEANS:
            self.action_toggle()

    def choose(self, key: str) -> None:
        current = self.display_name(self.settings.get(key, ""))
        self.push_screen(ChoiceScreen(SETTING_LABELS[key], CHOICES[key], current), callback=self.choice_made)

    def choice_made(self, value: str | None) -> None:
        if value is None:
            self.query_one(DataTable).focus()
            return
        key = self.current_key()
        if key in CHOICES:
            self.settings[key] = value
        self.rebuild()
        self.query_one(DataTable).focus()

    # ---------- bottom prompt ----------

    def open_prompt(self, label: str, value: str, action: Any) -> None:
        self._prompt_action = action
        editor = self.query_one("#editor", EditorInput)
        editor.placeholder = label
        editor.value = value
        editor.display = True
        editor.focus()
        self.set_mode(True)

    def cancel_prompt(self) -> None:
        self._prompt_action = None
        editor = self.query_one("#editor", EditorInput)
        editor.display = False
        self.query_one(DataTable).focus()
        self.set_mode(False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "editor":
            return
        action = self._prompt_action
        value = event.value.strip()
        self._prompt_action = None
        self.query_one("#editor", EditorInput).display = False
        self.query_one(DataTable).focus()
        self.set_mode(False)
        if action is not None:
            action(value)

    def apply_alarm_time(self, index: int, value: str) -> None:
        raw = value.strip()
        try:
            if ":" in raw or " " in raw:
                hour_text, minute_text = raw.replace(":", " ").split()[:2]
            elif len(raw) == 4 and raw.isdigit():
                hour_text, minute_text = raw[:2], raw[2:]
            else:
                raise ValueError
            hour, minute = int(hour_text), int(minute_text)
        except ValueError:
            self.notify("Use HH:MM", severity="warning")
            return
        self.alarms[index]["hour"] = max(0, min(23, hour))
        self.alarms[index]["minute"] = max(0, min(59, minute))
        self.rebuild()

    def apply_minutes(self, key: str, value: str) -> None:
        try:
            minutes = int(value)
        except ValueError:
            self.notify("Enter 0-59", severity="warning")
            return
        self.settings[key] = max(0, min(59, minutes))
        self.rebuild()

    # ---------- BLE ----------

    @work
    async def connect_watch(self) -> None:
        if self._lock.locked():
            self.notify("Busy", severity="warning")
            return
        async with self._lock:
            if self.mock:
                await self._connect_mock()
            else:
                await self._scan_and_connect()

    async def _connect_mock(self) -> None:
        self.backend = FakeBackend()
        self._address = "MOCK"
        self._name = "CASIO GA-B2100"
        self.set_state(State.CONNECTING, "mock")
        await self._read_watch()

    async def _scan_and_connect(self) -> bool:
        from bleak import BleakScanner

        self.set_state(State.CONNECTING, "scanning")
        try:
            device = await BleakScanner.find_device_by_filter(is_casio, timeout=10)
        except Exception as exc:  # noqa: BLE001
            self.set_state(State.DISCONNECTED)
            self.notify(f"Scan failed: {exc}", severity="error")
            return False
        if device is None:
            self.set_state(State.DISCONNECTED, "no watch")
            self.notify("No watch - hold MODE, then press s", severity="warning")
            return False

        self._address = device.address
        self._name = device.name or "CASIO"
        self.set_state(State.CONNECTING, self._name)
        try:
            connection = await asyncio.wait_for(connect_device(device), timeout=60)
        except Exception as exc:  # noqa: BLE001
            self.set_state(State.DISCONNECTED)
            self.notify(f"Connect failed: {exc}", severity="error")
            return False
        if connection is None:
            self.set_state(State.DISCONNECTED)
            self.notify("Connect failed - hold MODE and retry", severity="error")
            return False

        self.backend = RealBackend(connection)
        await self._read_watch()
        return True

    @work
    async def refresh_data(self) -> None:
        if self.backend is None:
            self.notify("Connect first (s)", severity="warning")
            return
        if self._lock.locked():
            self.notify("Busy", severity="warning")
            return
        async with self._lock:
            await self._read_watch()

    async def _read_watch(self) -> None:
        if self.backend is None:
            return
        try:
            name = await asyncio.wait_for(self.backend.name(), timeout=OP_TIMEOUT)
            condition = await asyncio.wait_for(self.backend.condition(), timeout=OP_TIMEOUT)
            settings = await asyncio.wait_for(self.backend.settings(), timeout=OP_TIMEOUT)
            alarms = await asyncio.wait_for(self.backend.alarms(), timeout=OP_TIMEOUT)
            timer = await asyncio.wait_for(self.backend.timer(), timeout=OP_TIMEOUT)
            adjustment = await asyncio.wait_for(self.backend.time_adjustment(), timeout=OP_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            self.set_state(State.STALE)
            self.notify(f"Read failed: {type(exc).__name__}", severity="error")
            return

        self.watch_name = name
        self.condition = condition
        self.settings = dict(settings)
        self.alarms = [dict(alarm) for alarm in alarms]
        self.timer = timer
        self.adjustment = bool(adjustment)
        self._baseline = {
            "settings": dict(self.settings),
            "alarms": [dict(alarm) for alarm in self.alarms],
            "adjustment": self.adjustment,
        }
        self.query_one("#watch-name", Static).update(f"{name}\n{self._address}")
        self.query_one("#battery", Static).update(f"battery: {condition.get('battery_level_percent')}%")
        self.query_one("#temp", Static).update(f"temp: {condition.get('temperature')} °C")
        self.query_one("#timer", Static).update(f"timer: {format_seconds(timer)}")
        self.query_one("#read", Static).update(f"read: {datetime.now():%H:%M:%S}")
        if not self.mock:
            save_config(self._address or "", name)
        self.set_state(State.READY)
        self.rebuild()
        self.query_one(DataTable).focus()

    def changes(self) -> list[str]:
        if not self._baseline:
            return []
        lines = []
        base_settings = self._baseline.get("settings", {})
        for key in SETTINGS_ORDER:
            if key == "time_adjustment" or key == "time_adjustment_minutes_after_hour":
                continue
            old, new = base_settings.get(key), self.settings.get(key)
            if old != new:
                lines.append(f"{SETTING_LABELS[key]}: {old} -> {new}")
        if self._baseline.get("adjustment") != self.adjustment:
            lines.append(f"Time adjustment: {self._baseline.get('adjustment')} -> {self.adjustment}")
        old_minutes = base_settings.get("time_adjustment_minutes_after_hour")
        new_minutes = self.settings.get("time_adjustment_minutes_after_hour")
        if old_minutes != new_minutes:
            lines.append(f"Adjust minutes: {old_minutes} -> {new_minutes}")
        for index, (old, new) in enumerate(zip(self._baseline.get("alarms", []), self.alarms, strict=False)):
            if old != new:
                lines.append(f"Alarm {index + 1}: {old} -> {new}")
        return lines

    @work
    async def write_changes(self) -> None:
        if self.backend is None:
            self.notify("Connect first (s)", severity="warning")
            return
        if self._lock.locked():
            self.notify("Busy", severity="warning")
            return
        lines = self.changes()
        if not lines:
            self.notify("No changes")
            return

        confirmed = await self.push_screen_wait(ConfirmScreen(lines))
        if not confirmed:
            self.query_one(DataTable).focus()
            return

        async with self._lock:
            try:
                await asyncio.wait_for(self.backend.set_settings(self.settings), timeout=OP_TIMEOUT)
                await asyncio.wait_for(
                    self.backend.set_time_adjustment(
                        time_adjustment=self.adjustment,
                        minutes_after_hour=int(self.settings.get("time_adjustment_minutes_after_hour", 30)),
                    ),
                    timeout=OP_TIMEOUT,
                )
                await asyncio.wait_for(self.backend.set_alarms(self.alarms), timeout=OP_TIMEOUT)
            except Exception as exc:  # noqa: BLE001
                self.set_state(State.STALE)
                self.notify(f"Write failed: {type(exc).__name__}", severity="error")
                return
            await self._read_watch()
            self.notify("Changes written and verified")

    @work
    async def sync_time(self) -> None:
        if self.backend is None:
            self.notify("Connect first (s)", severity="warning")
            return
        if self._lock.locked():
            self.notify("Busy", severity="warning")
            return
        async with self._lock:
            try:
                await asyncio.wait_for(self.backend.set_time(), timeout=OP_TIMEOUT)
            except Exception as exc:  # noqa: BLE001
                self.set_state(State.STALE)
                self.notify(f"Time sync failed: {type(exc).__name__}", severity="error")
                return
            self.notify("Time synchronized")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="casio-watch-tui", description="Casio G-Shock TUI")
    parser.add_argument("--mock", action="store_true", help="use the in-memory fake watch")
    args = parser.parse_args()

    install()
    CasioTUI(mock=args.mock).run()


if __name__ == "__main__":
    main()
