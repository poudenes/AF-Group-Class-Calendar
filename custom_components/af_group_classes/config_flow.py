"""Config flow: club website + which AI Task entity reads the schedule image."""

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
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import CONF_AI_TASK_ENTITY, CONF_URL, DEFAULT_URL, DOMAIN
from .coordinator import (
    NoScheduleImageError,
    ScheduleError,
    SiteBlockedError,
    find_image_url,
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
            vol.Required(CONF_URL, default=defaults.get(CONF_URL, DEFAULT_URL)): TextSelector(
                TextSelectorConfig(type=TextSelectorType.URL)
            ),
            vol.Optional(
                CONF_AI_TASK_ENTITY,
                description={"suggested_value": defaults.get(CONF_AI_TASK_ENTITY)},
            ): EntitySelector(EntitySelectorConfig(domain="ai_task")),
        }
    )


class AFGroupClassesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a club whose group class schedule should become a calendar."""

    VERSION = 1

    async def _validate(self, user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        url = normalize_url(user_input[CONF_URL])
        if url is None:
            return {}, {CONF_URL: "invalid_url"}
        data = {CONF_URL: url, CONF_AI_TASK_ENTITY: user_input.get(CONF_AI_TASK_ENTITY)}
        try:
            await find_image_url(async_get_clientsession(self.hass), url)
        except SiteBlockedError:
            # Website blocks Home Assistant; still allow setup: a repair issue explains
            # how to feed the image yourself with the refresh action.
            _LOGGER.warning("%s refused the request (HTTP 403)", url)
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
                host = urlparse(data[CONF_URL]).hostname or data[CONF_URL]
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=host, data=data)
        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input or {}), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = await self._validate(user_input)
            if not errors:
                await self.async_set_unique_id(urlparse(data[CONF_URL]).hostname)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or dict(entry.data)),
            errors=errors,
        )
