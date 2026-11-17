"""Config flow, daily check, calendar, refresh action, media source."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.af_group_classes.config_flow import normalize_url
from custom_components.af_group_classes.const import DOMAIN

from .conftest import IMAGE_URL, URL, FakeAI, FakeSite

CAL = "calendar.anytime_fitness_group_lessons"


@pytest.fixture(autouse=True)
async def frozen(freezer: FrozenDateTimeFactory, hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-11-17 08:00:00+01:00")  # Tuesday


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def _events(hass: HomeAssistant, start: str, end: str) -> list[dict]:
    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": CAL, "start_date_time": start, "end_date_time": end},
        blocking=True,
        return_response=True,
    )
    return result[CAL]["events"]


def test_normalize_url() -> None:
    assert normalize_url("afzuidas.nl/#groepslessen") == "https://afzuidas.nl/"
    assert normalize_url(" https://club.nl/rooster ") == "https://club.nl/rooster"
    assert normalize_url("ftp://x") is None
    assert normalize_url("") is None


async def test_config_flow(hass: HomeAssistant, site: FakeSite, ai: FakeAI) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    site.serve(b"img", page="<p>geen rooster</p>")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "afzuidas.nl/#groepslessen"}
    )
    assert result["errors"] == {"base": "no_schedule"}

    site.serve(b"image-v1")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "afzuidas.nl/#groepslessen"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "afzuidas.nl"
    assert result["data"] == {"url": URL, "ai_task_entity": None}
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(CAL) is not None
    assert ai.calls[0]["entity_id"] is None  # default AI Task entity


async def test_config_flow_allows_blocked_site(
    hass: HomeAssistant, site: FakeSite, ai: FakeAI
) -> None:
    site.serve(b"", status=403)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"url": URL})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done(wait_background_tasks=True)
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"site_blocked_{result['result'].entry_id}")


async def test_calendar_and_daily_check(
    hass: HomeAssistant,
    site: FakeSite,
    ai: FakeAI,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, entry)
    assert len(ai.calls) == 1
    assert ai.calls[0]["entity_id"] == "ai_task.gemini"
    assert ai.images == [b"image-v1"]

    state = hass.states.get(CAL)
    assert state.state == "off"
    assert state.attributes["friendly_name"] == "Anytime Fitness group lessons"
    assert state.attributes["message"] == "Circuit Trainig"
    assert state.attributes["start_time"] == "2026-11-17 09:15:00"
    assert state.attributes["period"] == "Okt 2026"
    assert state.attributes["schedule_image"] == IMAGE_URL
    assert state.attributes["classes_per_week"] == 36

    events = await _events(hass, "2026-11-17T00:00:00+01:00", "2026-11-18T00:00:00+01:00")
    assert [e["summary"] for e in events][:2] == ["Circuit Trainig", "Fit 60+"]
    assert events[1]["location"] == "Park – Ontmoetingseiland Gijsbrecht van Aemstelpark"
    week = await _events(hass, "2026-11-16T00:00:00+01:00", "2026-11-23T00:00:00+01:00")
    assert len(week) == 36

    # Next day, same image: AI is not asked again, calendar untouched.
    changed_before = state.attributes["last_changed"]
    freezer.tick(timedelta(days=1, minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(ai.calls) == 1
    state = hass.states.get(CAL)
    assert state.attributes["last_changed"] == changed_before
    assert state.attributes["last_checked"].startswith("2026-11-18")

    # A day later a new image with a different schedule: read and applied from today.
    site.serve(b"image-v2")
    ai.answer = {
        "period": "Nov 2026",
        "period_start": "2026-11-01",
        "classes": [{"weekday": 3, "start": "07:00", "end": "08:00", "name": "Bootcamp"}],
    }
    freezer.tick(timedelta(days=1, minutes=1))  # Thursday 19 Nov
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(ai.calls) == 2
    assert ai.images[-1] == b"image-v2"
    state = hass.states.get(CAL)
    assert state.attributes["period"] == "Nov 2026"
    old_tuesday = await _events(hass, "2026-11-17T00:00:00+01:00", "2026-11-18T00:00:00+01:00")
    assert len(old_tuesday) == 7  # past days keep the old schedule
    thursday = await _events(hass, "2026-11-19T00:00:00+01:00", "2026-11-20T00:00:00+01:00")
    assert [e["summary"] for e in thursday] == ["Bootcamp"]


async def test_restart_keeps_schedule_without_ai(
    hass: HomeAssistant, site: FakeSite, ai: FakeAI, entry: MockConfigEntry
) -> None:
    await _setup(hass, entry)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(ai.calls) == 1
    assert len(await _events(hass, "2026-11-17T00:00:00+01:00", "2026-11-18T00:00:00+01:00")) == 7


async def test_ai_failure_keeps_old_schedule_and_retries(
    hass: HomeAssistant,
    site: FakeSite,
    ai: FakeAI,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, entry)
    site.serve(b"image-v2")
    ai.answer = "Sorry, I cannot read this image."
    freezer.tick(timedelta(days=1, minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(ai.calls) == 2
    state = hass.states.get(CAL)
    assert state.state != "unavailable"
    assert state.attributes["classes_per_week"] == 36

    # Hash was not stored, so the next day it is tried again.
    ai.answer = (Path(__file__).parent / "fixtures" / "zuidas_okt_2026.json").read_text()
    freezer.tick(timedelta(days=1, minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(ai.calls) == 3


async def test_blocked_site_raises_issue(
    hass: HomeAssistant,
    site: FakeSite,
    ai: FakeAI,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, entry)
    site.serve(b"", status=403)
    freezer.tick(timedelta(days=1, minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    issue_id = f"site_blocked_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert hass.states.get(CAL).state != "unavailable"

    site.serve(b"image-v1")
    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_refresh_action(
    hass: HomeAssistant, site: FakeSite, ai: FakeAI, entry: MockConfigEntry, tmp_path: Path
) -> None:
    await _setup(hass, entry)
    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    assert len(ai.calls) == 1  # unchanged
    await hass.services.async_call(DOMAIN, "refresh", {"force": True}, blocking=True)
    assert len(ai.calls) == 2

    image = tmp_path / "rooster.png"
    image.write_bytes(b"local-image")
    with pytest.raises(HomeAssistantError, match="allowlist_external_dirs"):
        await hass.services.async_call(DOMAIN, "refresh", {"image_path": str(image)}, blocking=True)
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    await hass.services.async_call(DOMAIN, "refresh", {"image_path": str(image)}, blocking=True)
    assert ai.images[-1] == b"local-image"
    assert ai.calls[-1]["attachments"][0]["media_content_type"] == "image/png"


async def test_media_source_and_unload(
    hass: HomeAssistant, site: FakeSite, ai: FakeAI, entry: MockConfigEntry
) -> None:
    from homeassistant.components import media_source

    await _setup(hass, entry)
    browse = await media_source.async_browse_media(hass, f"media-source://{DOMAIN}")
    assert [c.title for c in browse.children] == ["afzuidas.nl"]
    media = await media_source.async_resolve_media(
        hass, f"media-source://{DOMAIN}/{entry.entry_id}", None
    )
    assert media.url == IMAGE_URL
    assert media.mime_type == "image/jpeg"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not list(Path(hass.config.path(".storage", DOMAIN)).glob(f"{entry.entry_id}.*"))
