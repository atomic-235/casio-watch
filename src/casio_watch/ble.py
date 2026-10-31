"""Direct BLE connection helpers.

gshock_api's Connection always re-scans by address before connecting. Casio
watches advertise for only a few seconds, so that second scan usually finds
nothing. Connect straight to the BLEDevice discovered by the scan instead.
"""

from __future__ import annotations

import logging
from typing import Any

from bleak import BleakClient
from gshock_api.connection import Connection
from gshock_api.watch_info import watch_info as gshock_watch_info

logger = logging.getLogger(__name__)

CASIO_ALL_FEATURES_UUID = "26eb002d-b012-49a8-b1f8-394fb2032b0f"


def is_casio(device: Any, advertisement: Any = None) -> bool:
    return (device.name or "").upper().startswith("CASIO")


async def connect_device(device: Any) -> Connection | None:
    client = BleakClient(device)
    await client.connect()
    if not client.is_connected:
        return None

    connection = Connection(address=device.address)
    connection.client = client
    await connection.init_characteristics_map()

    # gshock_api only sets the model when its own scanner finds the watch; we
    # connect directly, so do it here or every capability check falls back to
    # the GENERIC profile (world cities, temperature, alarm count, ...).
    if device.name:
        gshock_watch_info.set_name_and_model(device.name)

    # Only the "all features" characteristic carries the Casio command
    # responses. Subscribing to the step-counter/convoy characteristics as well
    # (the library's default) makes the GBX/GBD generation drop the link.
    uuids = [
        char.uuid
        for service in client.services
        for char in service.characteristics
        if char.uuid == CASIO_ALL_FEATURES_UUID
    ]
    if not uuids:
        uuids = [
            char.uuid
            for service in client.services
            for char in service.characteristics
            if "notify" in char.properties or "indicate" in char.properties
        ]

    for uuid in uuids:
        try:
            await client.start_notify(uuid, connection.notification_handler)
        except Exception as exc:  # noqa: BLE001
            logger.warning("start_notify failed for %s: %s", uuid, exc)

    return connection
