"""Shared fixtures: a fake club website and a fake AI Task."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.components import media_source
from homeassistant.components.ai_task import GenDataTaskResult
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.af_group_classes.const import CONF_AI_TASK_ENTITY, CONF_URL, DOMAIN

URL = "https://afzuidas.nl/"
IMAGE_URL = "https://afzuidas.nl/wp-content/uploads/AF-Zuidas-rooster-okt-2026-scaled.jpg"
FIXTURE = (Path(__file__).parent / "fixtures" / "zuidas_okt_2026.json").read_text()
PAGE = f'<div class="af-pdf-popup-overlay"><img src="{IMAGE_URL}" alt="Group lesson schedule">'


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let HA load custom_components."""
    return


@pytest.fixture(autouse=True)
async def core(hass: HomeAssistant) -> None:
    """conversation (needed by ai_task) needs the homeassistant core component."""
    assert await async_setup_component(hass, "homeassistant", {})


class FakeSite:
    """The club website: page + schedule image."""

    def __init__(self, mock: AiohttpClientMocker) -> None:
        self.mock = mock
        self.serve(b"image-v1")

    def serve(self, image: bytes, *, status: int = 200, page: str = PAGE) -> None:
        self.mock.clear_requests()
        self.mock.get(URL, status=status, text=page)
        self.mock.get(
            IMAGE_URL, status=status, content=image, headers={"Content-Type": "image/jpeg"}
        )


class FakeAI:
    """Stands in for ai_task.async_generate_data and records what it got."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.answer: Any = FIXTURE
        self.calls: list[dict[str, Any]] = []
        self.images: list[bytes] = []

    async def __call__(self, hass: HomeAssistant, **kwargs: Any) -> GenDataTaskResult:
        self.calls.append(kwargs)
        # Resolve the attachment like the real AI Task does: must be a local file.
        for attachment in kwargs["attachments"]:
            media = await media_source.async_resolve_media(
                hass, attachment["media_content_id"], None
            )
            assert media.path is not None
            self.images.append(media.path.read_bytes())
        return GenDataTaskResult(conversation_id="c1", data=self.answer)


@pytest.fixture
def site(aioclient_mock: AiohttpClientMocker) -> FakeSite:
    return FakeSite(aioclient_mock)


@pytest.fixture
def ai(hass: HomeAssistant):
    fake = FakeAI(hass)
    with patch("custom_components.af_group_classes.coordinator.ai_task.async_generate_data", fake):
        yield fake


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="afzuidas.nl",
        title="afzuidas.nl",
        data={CONF_URL: URL, CONF_AI_TASK_ENTITY: "ai_task.gemini"},
    )
