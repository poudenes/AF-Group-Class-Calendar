"""Config flow: where the schedule image comes from + which AI Task entity reads it."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_AI_TASK_ENTITY,
    CONF_SOURCE,
    CONF_URL,
    DEFAULT_URL,
    DOMAIN,
    MEDIA_FOLDER,
    SOURCE_MEDIA,
    SOURCE_WEBSITE,
)
from .coordinator import (
    NoScheduleImageError,
    ScheduleError,
    SiteBlockedError,
    find_image_url,
    media_folder,
)

_LOGGER = logging.getLogger(__name__)


def normalize_url(value: str) -> str | None:
    """'afzuidas.nl/#groepslessen' -> 'https://afzuidas.nl/'."""
    text = value.strip()
    if not text:
        return None
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return parsed._replace(fragment="", path=parsed.path or "/").geturl()


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_SOURCE, default=defaults.get(CONF_SOURCE, SOURCE_WEBSITE)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[SOURCE_WEBSITE, SOURCE_MEDIA],
                    translation_key=CONF_SOURCE,
                    mode=SelectSelectorMode.LIST,
                )
            ),
            vol.Optional(CONF_URL, default=defaults.get(CONF_URL, DEFAULT_URL)): TextSelector(
                TextSelectorConfig(type=TextSelectorType.URL)
            ),
            vol.Optional(
                CONF_AI_TASK_ENTITY,
                description={"suggested_value": defaults.get(CONF_AI_TASK_ENTITY)},
            ): EntitySelector(EntitySelectorConfig(domain="ai_task")),
        }
    )


def _unique_id(data: dict[str, Any]) -> str:
    if data[CONF_SOURCE] == SOURCE_MEDIA:
        return SOURCE_MEDIA
    return urlparse(data[CONF_URL]).hostname or data[CONF_URL]


def _title(data: dict[str, Any]) -> str:
    if data[CONF_SOURCE] == SOURCE_MEDIA:
        return f"Media: {MEDIA_FOLDER}"
    return _unique_id(data)


class AFGroupClassesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a club whose group class schedule should become a calendar."""

    VERSION = 1

    async def _validate(self, user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        source = user_input.get(CONF_SOURCE, SOURCE_WEBSITE)
        url = normalize_url(user_input.get(CONF_URL) or DEFAULT_URL)
        if url is None:
            return {}, {CONF_URL: "invalid_url"}
        data = {
            CONF_SOURCE: source,
            CONF_URL: url,
            CONF_AI_TASK_ENTITY: user_input.get(CONF_AI_TASK_ENTITY),
        }
        if source == SOURCE_MEDIA:
            if media_folder(self.hass) is None:
                return {}, {"base": "no_media_dir"}
            return data, {}
        try:
            await find_image_url(async_get_clientsession(self.hass), url)
        except SiteBlockedError:
            return {}, {"base": "blocked"}
        except NoScheduleImageError:
            return {}, {"base": "no_schedule"}
        except ScheduleError as exc:
            _LOGGER.warning("Schedule check failed: %s", exc)
            return {}, {"base": "cannot_connect"}
        return data, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = await self._validate(user_input)
            if not errors:
                await self.async_set_unique_id(_unique_id(data))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=_title(data), data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
            description_placeholders={"folder": MEDIA_FOLDER, "example_url": DEFAULT_URL},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = await self._validate(user_input)
            if not errors:
                # Switching website <-> media folder keeps the calendar and its history.
                return self.async_update_reload_and_abort(
                    entry, unique_id=_unique_id(data), title=_title(data), data=data
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or dict(entry.data)),
            errors=errors,
            description_placeholders={"folder": MEDIA_FOLDER, "example_url": DEFAULT_URL},
        )
