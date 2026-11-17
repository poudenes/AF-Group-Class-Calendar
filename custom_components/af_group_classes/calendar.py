"""Calendar with the weekly group classes, generated from the stored schedule."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CALENDAR_NAME, DOMAIN
from .coordinator import AFConfigEntry, ScheduleCoordinator
from .schedule import ClassEvent, events_between

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AFConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the group class calendar."""
    async_add_entities([GroupClassCalendar(entry.runtime_data)])


def _to_event(event: ClassEvent) -> CalendarEvent:
    return CalendarEvent(
        start=event.start,
        end=event.end,
        summary=event.summary,
        location=event.location,
        description=event.description,
        uid=event.uid,
    )


class GroupClassCalendar(CoordinatorEntity[ScheduleCoordinator], CalendarEntity):
    """Anytime Fitness group lessons."""

    _attr_has_entity_name = True
    _attr_name = None  # entity takes the device name
    _attr_icon = "mdi:dumbbell"

    def __init__(self, coordinator: ScheduleCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=CALENDAR_NAME,
            manufacturer="Anytime Fitness",
            model=entry.title,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=entry.data.get("url"),
        )

    @property
    def available(self) -> bool:
        # A failed daily check does not make the schedule we already have invalid.
        return bool(self.coordinator.versions) or super().available

    def _events(self, start: datetime, end: datetime) -> list[ClassEvent]:
        return events_between(
            self.coordinator.versions, start, end, dt_util.get_default_time_zone()
        )

    @property
    def event(self) -> CalendarEvent | None:
        """The class that is on now, or the next one."""
        now = dt_util.now()
        events = self._events(now, now + timedelta(days=8))
        return _to_event(events[0]) if events else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [_to_event(e) for e in self._events(start_date, end_date)]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {
            "period": data.get("period"),
            "schedule_image": data.get("image_url"),
            "classes_per_week": data.get("class_count"),
            "last_checked": data.get("last_checked"),
            "last_changed": data.get("last_changed"),
        }
