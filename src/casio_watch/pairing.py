"""Casio GBX/GBD init ("pairing") handshake.

gshock_api only connects and subscribes: it never runs Casio's app-level init
sequence, which is why the GBX-100 answers a few plain reads and never finishes
pairing.

This mirrors Gadgetbridge's ``gbx100/InitOperation`` step for step. On the
ALL_FEATURES characteristic (handle 0x0E):

  0x22 + 10 app-id bytes + 0x02   app information, written after the name is read
  0x11 (current BLE settings)     written back with bytes 12/13 set to 80 1e
  0x3b                            advertising parameters (fixed packet)
  0x3a                            connection parameters (fixed packet)
  0x09 + 10 time bytes            current time, when the watch asks (0x47 0x02)
  0x00 0x01                       init packet, when the watch asks (0x47 0x02)

Requests go to the READ_REQUEST characteristic (handle 0x0C) one feature at a
time: 0x10 -> 0x11 -> 0x3b -> 0x3a -> 0x26 -> 0x28 -> 0x20 -> 0x1d -> 0x1e.
The watch closes the handshake with 0x3D ("Init operation done").
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from gshock_api.iolib.time_io import TimeEncoderPure

from casio_watch.bluez_agent import register_agent, unregister_agent
from casio_watch.compat import add_raw_listener, remove_raw_listener

ALL_FEATURES_HANDLE = 0x0E
READ_REQUEST_HANDLE = 0x0C

FEATURE_INIT = 0x00
FEATURE_CURRENT_TIME = 0x09
FEATURE_BLE_FEATURES = 0x10
FEATURE_SETTING_FOR_BLE = 0x11
FEATURE_VERSION_INFORMATION = 0x20
FEATURE_APP_INFORMATION = 0x22
FEATURE_WATCH_NAME = 0x23
FEATURE_MODULE_ID = 0x26
FEATURE_WATCH_CONDITION = 0x28
FEATURE_DST_WATCH_STATE = 0x1D
FEATURE_DST_SETTING = 0x1E
FEATURE_ADVERTISE_PARAMETER_MANAGER = 0x3B
FEATURE_CONNECTION_PARAMETER_MANAGER = 0x3A
FEATURE_SERVICE_DISCOVERY_MANAGER = 0x47
SERVICE_DISCOVERY_FIRST_CONNECT = 0x02
SERVICE_DISCOVERY_ALREADY_PAIRED = 0x01
INIT_DONE_KEY = 0x3D

# Fixed packets from Gadgetbridge's InitOperation (HCI captures of a real watch).
ADVERTISE_PARAMETERS = bytes(
    [0x3B, 0x50, 0x00, 0x0A, 0x40, 0x01, 0x05, 0x05, 0x40, 0x06, 0x0A, 0x02,
     0xA0, 0x00, 0x05, 0x40, 0x01, 0x05, 0x1C, 0x00]
)
CONNECTION_PARAMETERS = bytes([0x3A, 0x00, 0x34, 0x01, 0x40, 0x01, 0x04, 0x00, 0xDC, 0x05])

PAIRING_MODELS = ("GBX-", "GBD-")
PAIRING_TIMEOUT = 60.0

logger = logging.getLogger(__name__)


def needs_pairing(name: str) -> bool:
    model = (name or "").removeprefix("CASIO ").strip().upper()
    return model.startswith(PAIRING_MODELS)


def encode_current_time(now: datetime | None = None) -> bytes:
    """10-byte BLE current-time payload, matching Gadgetbridge's toCurrentTime."""
    now = now or datetime.now()
    payload = bytearray(TimeEncoderPure.encode_current_time(now))
    # gshock_api encodes weekday as 0..6 (Mon=0); BLE/Casio expect 1..7 (Mon=1).
    payload[7] = now.isoweekday()
    return bytes(payload)


def _app_information() -> bytes:
    return bytes([FEATURE_APP_INFORMATION, *range(10), 0x02])


def _time_packet() -> bytes:
    return bytes([FEATURE_CURRENT_TIME]) + encode_current_time()


def _init_packet() -> bytes:
    return bytes([FEATURE_INIT, 0x01])


def _log_task(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except Exception as exc:  # noqa: BLE001
        logger.info("pairing: write ended with %s", type(exc).__name__)


async def _write_init(connection: Any) -> None:
    """Send 0x00 0x01 without waiting: the watch starts pairing instead of acking."""
    data = _init_packet()
    logger.info("pairing: writing init %s", data.hex())
    task = asyncio.create_task(connection.write(ALL_FEATURES_HANDLE, data))
    task.add_done_callback(_log_task)


async def finish_pairing(connection: Any, name: str = "", timeout: float = PAIRING_TIMEOUT) -> bool:
    """Run Gadgetbridge's init sequence. Returns True when the watch reports 0x3D."""
    if not needs_pairing(name):
        return False

    loop = asyncio.get_running_loop()
    packets: asyncio.Queue[bytes] = asyncio.Queue()
    paired_requested = 0

    def on_packet(data: bytes) -> None:
        if data:
            loop.call_soon_threadsafe(packets.put_nowait, bytes(data))

    async def request(feature: int) -> None:
        logger.info("pairing: request 0x%02X", feature)
        await connection.write(READ_REQUEST_HANDLE, bytes([feature]))

    async def on_first_connect() -> None:
        nonlocal paired_requested
        paired_requested += 1
        if paired_requested > 2:
            return
        logger.info("pairing: watch asks for pairing, sending time and init")
        await connection.write(ALL_FEATURES_HANDLE, _time_packet())
        await _write_init(connection)

    add_raw_listener(on_packet)
    agent_bus = await register_agent()
    try:
        logger.info("pairing: writing app information %s", _app_information().hex())
        await connection.write(ALL_FEATURES_HANDLE, _app_information())
        await request(FEATURE_BLE_FEATURES)

        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                logger.warning("pairing: watch never reported 0x3D within %.0fs", timeout)
                return False
            try:
                data = await asyncio.wait_for(packets.get(), timeout=remaining)
            except TimeoutError:
                continue

            key = data[0]
            logger.info("pairing: watch -> 0x%02X %s", key, data[1:].hex())

            if key == INIT_DONE_KEY:
                logger.info("pairing: watch reported init done (0x3D)")
                await asyncio.sleep(0.5)
                return True
            if key == FEATURE_WATCH_NAME:
                # Name already read by the caller; keep the reference order.
                continue
            if key == FEATURE_SETTING_FOR_BLE:
                settings = bytearray(data)
                if len(settings) >= 14:
                    settings[12] = 0x80
                    settings[13] = 0x1E
                    logger.info("pairing: writing BLE settings %s", bytes(settings).hex())
                    await connection.write(ALL_FEATURES_HANDLE, bytes(settings))
                await request(FEATURE_ADVERTISE_PARAMETER_MANAGER)
            elif key == FEATURE_ADVERTISE_PARAMETER_MANAGER:
                logger.info("pairing: writing advertising parameters")
                await connection.write(ALL_FEATURES_HANDLE, ADVERTISE_PARAMETERS)
                await request(FEATURE_CONNECTION_PARAMETER_MANAGER)
            elif key == FEATURE_CONNECTION_PARAMETER_MANAGER:
                logger.info("pairing: writing connection parameters")
                await connection.write(ALL_FEATURES_HANDLE, CONNECTION_PARAMETERS)
                await request(FEATURE_MODULE_ID)
            elif key == FEATURE_BLE_FEATURES:
                await request(FEATURE_SETTING_FOR_BLE)
            elif key == FEATURE_MODULE_ID:
                await request(FEATURE_WATCH_CONDITION)
            elif key == FEATURE_WATCH_CONDITION:
                await request(FEATURE_VERSION_INFORMATION)
            elif key == FEATURE_VERSION_INFORMATION:
                await request(FEATURE_DST_WATCH_STATE)
            elif key == FEATURE_DST_WATCH_STATE:
                await request(FEATURE_DST_SETTING)
            elif key == FEATURE_SERVICE_DISCOVERY_MANAGER and len(data) > 1:
                if data[1] == SERVICE_DISCOVERY_FIRST_CONNECT:
                    await on_first_connect()
                elif data[1] == SERVICE_DISCOVERY_ALREADY_PAIRED:
                    logger.info("pairing: watch reports already paired")
    except Exception as exc:  # noqa: BLE001
        logger.warning("pairing: failed: %s: %s", type(exc).__name__, exc)
        return False
    finally:
        remove_raw_listener(on_packet)
        await unregister_agent(agent_bus)
