"""Command line interface for Casio G-Shock BLE watches."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from gshock_api.connection import Connection
from gshock_api.gshock_api import GshockAPI

from casio_watch.compat import install

DEFAULT_TIMEOUT = 120.0


async def scan_for_watches() -> int:
    from bleak import BleakScanner

    print("scanning 10s for CASIO devices...", flush=True)
    devices = await BleakScanner.discover(timeout=10)
    found = [d for d in devices if (d.name or "").upper().startswith("CASIO")]
    for device in found:
        print(f"{device.address}  {device.name}")
    if not found:
        print("no CASIO device found (press the watch's connect button)")
        return 1
    return 0


async def call(coro: Awaitable[Any], seconds: float = 15.0) -> Any:
    """Run one watch operation with a hard deadline; the library can wait forever."""
    return await asyncio.wait_for(coro, timeout=seconds)


async def run(address: str | None, timeout: float, action: Callable[[GshockAPI], Awaitable[int]]) -> int:
    connection = Connection(address=address)
    try:
        connected = await asyncio.wait_for(connection.connect(timeout=timeout), timeout=timeout + 20)
    except TimeoutError:
        print("timed out waiting for the watch", file=sys.stderr)
        return 1
    if not connected:
        print("could not connect to the watch", file=sys.stderr)
        return 1

    try:
        return await asyncio.wait_for(action(GshockAPI(connection)), timeout=90)
    except TimeoutError:
        print("watch stopped responding", file=sys.stderr)
        return 1
    finally:
        try:
            await asyncio.wait_for(connection.disconnect(), timeout=10)
        except Exception as exc:  # noqa: BLE001
            print(f"disconnect failed: {type(exc).__name__}: {exc}", file=sys.stderr)


async def print_status(api: GshockAPI) -> int:
    print(f"name:      {await call(api.get_watch_name())}")
    print(f"condition: {await call(api.get_watch_condition())}")
    print("settings:")
    for key, value in (await call(api.get_basic_settings())).items():
        print(f"  {key}: {value}")
    print("alarms:")
    for index, alarm in enumerate(await call(api.get_alarms())):
        flag = "on " if alarm["enabled"] else "off"
        chime = " chime" if alarm["hasHourlyChime"] else ""
        print(f"  [{index}] {alarm['hour']:02d}:{alarm['minute']:02d} {flag}{chime}")
    print(f"timer:     {await call(api.get_timer())} s")
    return 0


async def sync_time(api: GshockAPI) -> int:
    await call(api.set_time())
    print("time synchronized")
    return 0


async def alarms_get(api: GshockAPI) -> int:
    for index, alarm in enumerate(await call(api.get_alarms())):
        print(f"[{index}] {json.dumps(alarm)}")
    return 0


async def alarms_disable(api: GshockAPI) -> int:
    alarms = await call(api.get_alarms())
    for alarm in alarms:
        alarm["enabled"] = False
    await call(api.set_alarms(alarms))
    print("all alarms disabled")
    return 0


async def alarms_enable(api: GshockAPI, index: int) -> int:
    alarms = await call(api.get_alarms())
    if not 0 <= index < len(alarms):
        print(f"alarm index out of range 0..{len(alarms) - 1}", file=sys.stderr)
        return 1
    alarms[index]["enabled"] = True
    await call(api.set_alarms(alarms))
    print(f"alarm [{index}] enabled")
    return 0


async def alarms_chime(api: GshockAPI, state: str) -> int:
    alarms = await call(api.get_alarms())
    if not alarms:
        print("watch returned no alarms", file=sys.stderr)
        return 1
    alarms[0]["hasHourlyChime"] = state == "on"
    await call(api.set_alarms(alarms))
    print(f"hourly chime {state}")
    return 0


async def settings_get(api: GshockAPI) -> int:
    for key, value in (await call(api.get_basic_settings())).items():
        print(f"{key}: {value}")
    print(f"time_adjustment: {await call(api.get_time_adjustment())}")
    return 0


def parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


async def settings_set(api: GshockAPI, key: str, raw_value: str) -> int:
    settings = await call(api.get_basic_settings())
    if key not in settings:
        print(f"unknown setting {key!r}; known: {', '.join(settings)}", file=sys.stderr)
        return 1
    settings[key] = parse_value(raw_value)
    await call(api.set_settings(settings))
    after = await call(api.get_basic_settings())
    print(f"{key}: {settings[key]} -> {after.get(key)}")
    return 0


async def timer_get(api: GshockAPI) -> int:
    print(f"{await call(api.get_timer())} s")
    return 0


async def timer_set(api: GshockAPI, seconds: int) -> int:
    await call(api.set_timer(seconds))
    print(f"timer set to {await call(api.get_timer())} s")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="casio-watch", description="Configure Casio G-Shock watches over BLE")
    parser.add_argument("-a", "--address", help="watch BLE address (omit to scan)")
    parser.add_argument("-t", "--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds to wait for the watch")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="scan for nearby CASIO devices")
    sub.add_parser("status", help="show watch state")
    sub.add_parser("time", help="synchronize the clock")

    alarms = sub.add_parser("alarms", help="read or change alarms")
    alarms_sub = alarms.add_subparsers(dest="alarms_command", required=True)
    alarms_sub.add_parser("get")
    alarms_sub.add_parser("disable")
    enable = alarms_sub.add_parser("enable")
    enable.add_argument("index", type=int)
    chime = alarms_sub.add_parser("chime")
    chime.add_argument("state", choices=["on", "off"])

    settings = sub.add_parser("settings", help="read or change settings")
    settings_sub = settings.add_subparsers(dest="settings_command", required=True)
    settings_sub.add_parser("get")
    setter = settings_sub.add_parser("set")
    setter.add_argument("key")
    setter.add_argument("value")

    timer = sub.add_parser("timer", help="read or change the countdown timer")
    timer_sub = timer.add_subparsers(dest="timer_command", required=True)
    timer_sub.add_parser("get")
    timer_setter = timer_sub.add_parser("set")
    timer_setter.add_argument("seconds", type=int)

    return parser


async def dispatch(args: argparse.Namespace) -> int:
    if args.command == "scan":
        return await scan_for_watches()

    async def action(api: GshockAPI) -> int:
        match args.command:
            case "status":
                return await print_status(api)
            case "time":
                return await sync_time(api)
            case "alarms":
                match args.alarms_command:
                    case "get":
                        return await alarms_get(api)
                    case "disable":
                        return await alarms_disable(api)
                    case "enable":
                        return await alarms_enable(api, args.index)
                    case "chime":
                        return await alarms_chime(api, args.state)
            case "settings":
                match args.settings_command:
                    case "get":
                        return await settings_get(api)
                    case "set":
                        return await settings_set(api, args.key, args.value)
            case "timer":
                match args.timer_command:
                    case "get":
                        return await timer_get(api)
                    case "set":
                        return await timer_set(api, args.seconds)
        raise AssertionError(f"unhandled command {args.command}")

    return await run(args.address, args.timeout, action)


def main() -> None:
    install()
    sys.stdout.reconfigure(line_buffering=True)
    args = build_parser().parse_args()
    code = asyncio.run(dispatch(args))
    sys.stdout.flush()
    sys.stderr.flush()
    # bleak/dbus-fast leaves a non-daemon thread behind; do not wait for it.
    os._exit(code)


if __name__ == "__main__":
    main()
