"""Daily check of the club page; only when the schedule image changed is it read again."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.components import ai_task
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import STORAGE_DIR, Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    AI_INSTRUCTIONS,
    CONF_AI_TASK_ENTITY,
    CONF_URL,
    DOMAIN,
    ISSUE_BLOCKED,
    MAX_VERSIONS,
    UPDATE_INTERVAL,
)
from .schedule import (
    ParsedSchedule,
    ScheduleParseError,
    ScheduleVersion,
    find_schedule_image,
    parse_ai_answer,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
TIMEOUT = aiohttp.ClientTimeout(total=60)
MAX_IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

type AFConfigEntry = ConfigEntry[ScheduleCoordinator]


class ScheduleError(HomeAssistantError):
    """Fetching or reading the schedule failed."""


class NoScheduleImageError(ScheduleError):
    """The page loaded, but no schedule image was found on it."""


class SiteBlockedError(ScheduleError):
    """The website refused the request (HTTP 403, e.g. Cloudflare bot protection)."""


async def fetch(session: aiohttp.ClientSession, url: str, accept: str) -> tuple[bytes, str | None]:
    """GET a URL; returns body and content type."""
    try:
        async with session.get(url, headers={"Accept": accept}, timeout=TIMEOUT) as resp:
            if resp.status == 403:
                raise SiteBlockedError(f"{url} refused the request (HTTP 403)")
            if resp.status >= 400:
                raise ScheduleError(f"{url} returned HTTP {resp.status}")
            if int(resp.headers.get("Content-Length") or 0) > MAX_IMAGE_BYTES:
                raise ScheduleError(f"{url} is too large")
            body = await resp.read()
            if len(body) > MAX_IMAGE_BYTES:
                raise ScheduleError(f"{url} is too large")
            return body, resp.content_type
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise ScheduleError(f"Could not fetch {url}: {exc}") from exc


async def find_image_url(session: aiohttp.ClientSession, page_url: str) -> str:
    """Load the club page and return the URL of the schedule image."""
    html, _ = await fetch(session, page_url, "text/html,application/xhtml+xml")
    image_url = find_schedule_image(html.decode(errors="replace"), page_url)
    if image_url is None:
        raise NoScheduleImageError(f"No schedule image found on {page_url}")
    return image_url


def _image_type(content_type: str | None, name: str) -> str:
    if content_type in IMAGE_TYPES:
        return content_type
    guessed = mimetypes.guess_type(name)[0]
    if guessed in IMAGE_TYPES:
        return guessed
    raise ScheduleError(f"{name} is not a JPEG, PNG or WebP image")


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _version_dict(valid_from: date, parsed: ParsedSchedule) -> dict[str, Any]:
    return {
        "valid_from": valid_from.isoformat(),
        "period": parsed.period,
        "notes": parsed.notes,
        "classes": [c.as_dict() for c in parsed.classes],
    }


def merge_version(
    versions: list[dict[str, Any]], parsed: ParsedSchedule, today: date
) -> list[dict[str, Any]] | None:
    """New list of versions, or None when the classes did not change.

    First schedule: valid from its period start, but at least this whole week.
    A changed schedule: valid from its period start if that is still to come,
    otherwise from today. Older versions keep the days before that.
    """
    new_classes = [c.as_dict() for c in parsed.classes]
    if (
        versions
        and versions[-1]["classes"] == new_classes
        and (versions[-1].get("notes") or {}) == parsed.notes
    ):
        return None
    if not versions:
        valid_from = _monday(today)
        if parsed.period_start and parsed.period_start < valid_from:
            valid_from = parsed.period_start
        return [_version_dict(valid_from, parsed)]
    if parsed.period_start and parsed.period_start > today:
        valid_from = parsed.period_start
    else:
        valid_from = today
    kept = [v for v in versions if date.fromisoformat(v["valid_from"]) < valid_from]
    return [*kept, _version_dict(valid_from, parsed)][-MAX_VERSIONS:]


class ScheduleCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keeps the stored schedule in sync with the image on the club website.

    ``data`` is the stored state: image URL + hash, when it was checked/changed and
    the list of schedule versions that the calendar turns into events.
    """

    config_entry: AFConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AFConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._lock = asyncio.Lock()
        self.image_dir = Path(hass.config.path(STORAGE_DIR, DOMAIN))
        self._image_path: Path | None = None

    async def async_load(self) -> None:
        """Load what was read before, so the calendar works straight after a restart."""
        self.data = await self._store.async_load() or {"versions": []}
        if ext := self.data.get("image_ext"):
            self._image_path = self.image_dir / f"{self.config_entry.entry_id}{ext}"

    @property
    def versions(self) -> list[ScheduleVersion]:
        return [ScheduleVersion.from_dict(v) for v in (self.data or {}).get("versions", [])]

    def image_path(self) -> Path | None:
        """Local copy of the latest schedule image (used as AI attachment)."""
        return self._image_path

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.async_check()
        except ScheduleError as exc:
            raise UpdateFailed(str(exc)) from exc

    async def async_check(
        self, *, force: bool = False, image_file: str | None = None
    ) -> dict[str, Any]:
        """Fetch the image; read it with AI only when it differs from last time."""
        async with self._lock:
            return await self._check(force, image_file)

    async def _check(self, force: bool, image_file: str | None) -> dict[str, Any]:
        state = dict(self.data or {"versions": []})
        now = dt_util.now()

        if image_file:
            image, mime, image_url = await self._read_local(image_file)
        else:
            session = async_get_clientsession(self.hass)
            try:
                image_url = await find_image_url(session, self.config_entry.data[CONF_URL])
                image, content_type = await fetch(
                    session, image_url, "image/jpeg,image/png,image/webp;q=0.9,*/*;q=0.5"
                )
            except SiteBlockedError:
                self._raise_blocked_issue()
                raise
            mime = _image_type(content_type, image_url)
        ir.async_delete_issue(self.hass, DOMAIN, f"{ISSUE_BLOCKED}_{self.config_entry.entry_id}")

        digest = hashlib.sha256(image).hexdigest()
        state["last_checked"] = now.isoformat()
        if digest == state.get("image_hash") and not force:
            _LOGGER.debug("Schedule image unchanged (%s)", image_url)
            await self._store.async_save(state)
            return state

        _LOGGER.info("Schedule image changed (%s); reading it", image_url)
        state["image_ext"] = IMAGE_TYPES[mime]
        path = self.image_dir / f"{self.config_entry.entry_id}{state['image_ext']}"
        await self.hass.async_add_executor_job(self._write_image, path, image)
        self._image_path = path
        parsed = await self._read_with_ai(mime)

        merged = merge_version(state.get("versions", []), parsed, now.date())
        if merged is None:
            _LOGGER.info("New image, but the classes are the same; calendar unchanged")
        else:
            state["versions"] = merged
            state["last_changed"] = now.isoformat()
        state.update(
            image_url=image_url,
            image_hash=digest,
            period=parsed.period,
            class_count=len(parsed.classes),
        )
        await self._store.async_save(state)
        return state

    async def _read_local(self, image_file: str) -> tuple[bytes, str, str]:
        if not self.hass.config.is_allowed_path(image_file):
            raise ScheduleError(
                f"{image_file} is not in allowlist_external_dirs of configuration.yaml"
            )
        mime = _image_type(None, image_file)
        try:
            image = await self.hass.async_add_executor_job(Path(image_file).read_bytes)
        except OSError as exc:
            raise ScheduleError(f"Could not read {image_file}: {exc}") from exc
        return image, mime, f"file://{image_file}"

    @staticmethod
    def _write_image(path: Path, image: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        for old in path.parent.glob(f"{path.stem}.*"):
            if old != path:
                old.unlink(missing_ok=True)
        path.write_bytes(image)

    async def _read_with_ai(self, mime: str) -> ParsedSchedule:
        entity_id = self.config_entry.data.get(CONF_AI_TASK_ENTITY) or None
        try:
            result = await ai_task.async_generate_data(
                self.hass,
                task_name="Anytime Fitness group class schedule",
                entity_id=entity_id,
                instructions=AI_INSTRUCTIONS,
                attachments=[
                    {
                        "media_content_id": f"media-source://{DOMAIN}/{self.config_entry.entry_id}",
                        "media_content_type": mime,
                    }
                ],
            )
        except HomeAssistantError as exc:
            raise ScheduleError(f"AI task failed: {exc}") from exc
        try:
            return parse_ai_answer(result.data)
        except ScheduleParseError as exc:
            _LOGGER.debug("AI answer that could not be read: %s", result.data)
            raise ScheduleError(f"Could not read the AI answer: {exc}") from exc

    def _raise_blocked_issue(self) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{ISSUE_BLOCKED}_{self.config_entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_BLOCKED,
            translation_placeholders={"url": self.config_entry.data[CONF_URL]},
        )
