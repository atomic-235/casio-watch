"""Direct BLE connection helpers.

gshock_api's Connection always re-scans by address before connecting. Casio
watches advertise for only a few seconds, so that second scan usually finds
nothing. Connect straight to the BLEDevice discovered by the scan instead.
"""

from __future__ import annotations

from typing import Any

from bleak import BleakClient
from gshock_api.connection import Connection


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

    for service in client.services:
        for characteristic in service.characteristics:
            if "notify" in characteristic.properties or "indicate" in characteristic.properties:
                try:
                    await client.start_notify(characteristic.uuid, connection.notification_handler)
                except Exception:  # noqa: BLE001
                    pass

    return connection
