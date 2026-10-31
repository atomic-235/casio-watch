"""Minimal BlueZ pairing agent for watches that require bonding.

BlueZ refuses to pair without a registered agent. These watches use Just Works
(no PIN, no passkey, no watch interaction), so the agent only accepts the
authorisation requests. Note: annotations here are D-Bus type strings and must
not be deferred by ``from __future__ import annotations``.
"""

# ruff: noqa: F821  (D-Bus type strings: "o" object path, "s" string, "u" uint32, "q" uint16)

import logging

logger = logging.getLogger(__name__)
AGENT_PATH = "/org/casio_watch/agent"


def _build_agent_class():
    from dbus_fast.service import ServiceInterface, method

    class Agent(ServiceInterface):
        def __init__(self) -> None:
            super().__init__("org.bluez.Agent1")

        @method()
        def Release(self) -> None:  # noqa: N802
            logger.info("bluez agent: released")

        @method()
        def RequestConfirmation(self, device: "o", passkey: "u") -> None:  # noqa: N802
            logger.info("bluez agent: confirming passkey %s for %s", passkey, device)

        @method()
        def RequestAuthorization(self, device: "o") -> None:  # noqa: N802
            logger.info("bluez agent: authorising %s", device)

        @method()
        def AuthorizeService(self, device: "o", uuid: "s") -> None:  # noqa: N802
            logger.info("bluez agent: authorising service %s on %s", uuid, device)

        @method()
        def Cancel(self) -> None:  # noqa: N802
            logger.info("bluez agent: request cancelled")

    return Agent


async def register_agent() -> object | None:
    """Register a Just Works agent on the system bus. Returns the bus, or None."""
    try:
        from dbus_fast import BusType
        from dbus_fast.aio import MessageBus
    except Exception as exc:  # noqa: BLE001
        logger.warning("bluez agent: dbus_fast unavailable: %s", exc)
        return None

    try:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        bus.export(AGENT_PATH, _build_agent_class()())
        introspection = await bus.introspect("org.bluez", "/org/bluez")
        obj = bus.get_proxy_object("org.bluez", "/org/bluez", introspection)
        manager = obj.get_interface("org.bluez.AgentManager1")
        await manager.call_register_agent(AGENT_PATH, "NoInputNoOutput")
        await manager.call_request_default_agent(AGENT_PATH)
    except Exception as exc:  # noqa: BLE001
        logger.warning("bluez agent: registration failed: %s: %s", type(exc).__name__, exc)
        return None

    logger.info("bluez agent: registered %s", AGENT_PATH)
    return bus


async def unregister_agent(bus: object | None) -> None:
    if bus is None:
        return
    try:
        introspection = await bus.introspect("org.bluez", "/org/bluez")  # type: ignore[attr-defined]
        obj = bus.get_proxy_object("org.bluez", "/org/bluez", introspection)  # type: ignore[attr-defined]
        manager = obj.get_interface("org.bluez.AgentManager1")
        await manager.call_unregister_agent(AGENT_PATH)
    except Exception as exc:  # noqa: BLE001
        logger.info("bluez agent: unregister failed: %s", exc)
    finally:
        try:
            bus.disconnect()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
