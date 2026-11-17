"""Anytime Fitness group lessons: the club's class schedule image as a calendar."""

from __future__ import annotations

from pathlib import Path

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_CONFIG_ENTRY_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import STORAGE_DIR, Store
from homeassistant.helpers.typing import ConfigType

from .const import ATTR_FORCE, ATTR_IMAGE_PATH, DOMAIN, SERVICE_REFRESH
from .coordinator import STORAGE_VERSION, AFConfigEntry, ScheduleCoordinator, ScheduleError

PLATFORMS: list[Platform] = [Platform.CALENDAR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

REFRESH_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_FORCE, default=False): cv.boolean,
        vol.Optional(ATTR_IMAGE_PATH): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the refresh action."""

    async def refresh(call: ServiceCall) -> None:
        entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED and entry_id in (None, e.entry_id)
        ]
        if not entries:
            raise ServiceValidationError("No loaded Anytime Fitness group lessons entry")
        for entry in entries:
            coordinator: ScheduleCoordinator = entry.runtime_data
            try:
                state = await coordinator.async_check(
                    force=call.data[ATTR_FORCE], image_file=call.data.get(ATTR_IMAGE_PATH)
                )
            except ScheduleError as exc:
                raise HomeAssistantError(str(exc)) from exc
            coordinator.async_set_updated_data(state)

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh, schema=REFRESH_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AFConfigEntry) -> bool:
    """Set up from a config entry."""
    coordinator = ScheduleCoordinator(hass, entry)
    await coordinator.async_load()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Reading a new image with AI can take a while: do the first check in the
    # background. The stored schedule is shown in the meantime.
    entry.async_create_background_task(hass, coordinator.async_refresh(), f"{DOMAIN}_first_check")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AFConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: AFConfigEntry) -> None:
    """Remove stored schedule and image when the entry is deleted."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()

    def remove_images() -> None:
        for image in Path(hass.config.path(STORAGE_DIR, DOMAIN)).glob(f"{entry.entry_id}.*"):
            image.unlink(missing_ok=True)

    await hass.async_add_executor_job(remove_images)
