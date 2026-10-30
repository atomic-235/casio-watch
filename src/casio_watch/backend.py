"""Watch backends: real BLE and an in-memory mock for tests."""

from __future__ import annotations

from typing import Any, Protocol

from gshock_api.connection import Connection
from gshock_api.gshock_api import GshockAPI


class Backend(Protocol):
    async def name(self) -> str: ...
    async def condition(self) -> dict[str, Any]: ...
    async def settings(self) -> dict[str, Any]: ...
    async def alarms(self) -> list[dict[str, Any]]: ...
    async def timer(self) -> int: ...
    async def time_adjustment(self) -> bool: ...
    async def reminders(self) -> list[dict[str, Any]]: ...
    async def set_reminders(self, reminders: list[dict[str, Any]]) -> None: ...
    async def set_settings(self, settings: dict[str, Any]) -> None: ...
    async def set_alarms(self, alarms: list[dict[str, Any]]) -> None: ...
    async def set_time(self) -> None: ...
    async def set_time_adjustment(self, time_adjustment: bool, minutes_after_hour: int) -> None: ...
    async def disconnect(self) -> None: ...


class RealBackend:
    """Thin adapter over gshock_api."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.api = GshockAPI(connection)

    async def name(self) -> str:
        return await self.api.get_watch_name()

    async def condition(self) -> dict[str, Any]:
        return await self.api.get_watch_condition()

    async def settings(self) -> dict[str, Any]:
        return await self.api.get_basic_settings()

    async def alarms(self) -> list[dict[str, Any]]:
        return await self.api.get_alarms()

    async def timer(self) -> int:
        return await self.api.get_timer()

    async def time_adjustment(self) -> bool:
        return await self.api.get_time_adjustment()

    async def reminders(self) -> list[dict[str, Any]]:
        return await self.api.get_reminders()

    async def set_reminders(self, reminders: list[dict[str, Any]]) -> None:
        await self.api.set_reminders(reminders)

    async def set_settings(self, settings: dict[str, Any]) -> None:
        await self.api.set_settings(settings)

    async def set_alarms(self, alarms: list[dict[str, Any]]) -> None:
        await self.api.set_alarms(alarms)

    async def set_time(self) -> None:
        await self.api.set_time()

    async def set_time_adjustment(self, time_adjustment: bool, minutes_after_hour: int) -> None:
        await self.api.set_time_adjustment(
            time_adjustment=time_adjustment, minutes_after_hour=minutes_after_hour
        )

    async def disconnect(self) -> None:
        await self.connection.disconnect()


class FakeBackend:
    """Deterministic in-memory watch for UI tests."""

    def __init__(self) -> None:
        self._settings: dict[str, Any] = {
            "time_format": "12h",
            "date_format": "MM:DD",
            "language": "English",
            "auto_light": True,
            "light_duration": "1.5s",
            "power_saving_mode": True,
            "button_tone": True,
        }
        self._alarms: list[dict[str, Any]] = [
            {"enabled": True, "hasHourlyChime": False, "hour": 9, "minute": 0},
            {"enabled": True, "hasHourlyChime": False, "hour": 21, "minute": 0},
            {"enabled": True, "hasHourlyChime": False, "hour": 0, "minute": 0},
            {"enabled": False, "hasHourlyChime": False, "hour": 0, "minute": 0},
            {"enabled": False, "hasHourlyChime": False, "hour": 0, "minute": 0},
        ]
        self.writes: list[tuple[str, Any]] = []
        self._time_adjustment = True
        self._reminders: list[dict[str, Any]] = [self._empty_reminder(i) for i in range(5)]

    @staticmethod
    def _empty_reminder(index: int) -> dict[str, Any]:
        return {
            "title": "",
            "time": {
                "enabled": False,
                "repeat_period": "NEVER",
                "start_date": {"year": 2026, "month": "JANUARY", "day": 1 + index},
                "end_date": {"year": 2026, "month": "JANUARY", "day": 1 + index},
                "days_of_week": [],
            },
        }

    async def name(self) -> str:
        return "CASIO GA-B2100"

    async def condition(self) -> dict[str, Any]:
        return {"battery_level_percent": 80, "temperature": 28}

    async def settings(self) -> dict[str, Any]:
        return dict(self._settings)

    async def alarms(self) -> list[dict[str, Any]]:
        return [dict(alarm) for alarm in self._alarms]

    async def timer(self) -> int:
        return 600

    async def time_adjustment(self) -> bool:
        return self._time_adjustment

    async def reminders(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._reminders]

    async def set_reminders(self, reminders: list[dict[str, Any]]) -> None:
        self._reminders = [dict(item) for item in reminders]
        self.writes.append(("reminders", reminders))

    async def set_settings(self, settings: dict[str, Any]) -> None:
        self._settings.update(settings)
        self.writes.append(("settings", settings))

    async def set_alarms(self, alarms: list[dict[str, Any]]) -> None:
        self._alarms = [dict(alarm) for alarm in alarms]
        self.writes.append(("alarms", alarms))

    async def set_time(self) -> None:
        self.writes.append(("time", None))

    async def set_time_adjustment(self, time_adjustment: bool, minutes_after_hour: int) -> None:
        self._time_adjustment = time_adjustment
        self.writes.append(("adjustment", (time_adjustment, minutes_after_hour)))

    async def disconnect(self) -> None:
        pass
