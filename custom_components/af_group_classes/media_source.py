"""Media source for the stored schedule image.

The AI Task integration only accepts attachments as media-source IDs that resolve to
a local file. This exposes ``media-source://af_group_classes/<entry_id>`` for that,
and lets you look at the current schedule in the media browser.
"""

from __future__ import annotations

from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import IMAGE_TYPES, AFConfigEntry, ScheduleCoordinator

MIME_BY_EXT = {ext: mime for mime, ext in IMAGE_TYPES.items()}


async def async_get_media_source(hass: HomeAssistant) -> ScheduleMediaSource:
    """Set up the schedule image media source."""
    return ScheduleMediaSource(hass)


def _coordinator(entry: AFConfigEntry) -> ScheduleCoordinator | None:
    """The entry's coordinator once setup has created it (and until it is unloaded)."""
    if entry.state not in (ConfigEntryState.LOADED, ConfigEntryState.SETUP_IN_PROGRESS):
        return None
    return getattr(entry, "runtime_data", None)


class ScheduleMediaSource(MediaSource):
    """Serves the latest schedule image per config entry."""

    name = "Anytime Fitness group lessons"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    def _entries(self) -> list[AFConfigEntry]:
        return [
            entry
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if _coordinator(entry) is not None
        ]

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        entry = self.hass.config_entries.async_get_entry(item.identifier)
        # Not "state is LOADED": the first check can run while setup is still finishing.
        if entry is None or entry.domain != DOMAIN or (coordinator := _coordinator(entry)) is None:
            raise Unresolvable(f"Unknown schedule {item.identifier}")
        path = coordinator.image_path()
        if path is None or not await self.hass.async_add_executor_job(path.is_file):
            raise Unresolvable("No schedule image downloaded yet")
        url = (coordinator.data or {}).get("image_url") or ""
        if not url.startswith("http"):
            url = ""
        return PlayMedia(url, MIME_BY_EXT[path.suffix], path=path)

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        children = [
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=entry.entry_id,
                media_class=MediaClass.IMAGE,
                media_content_type=MediaType.IMAGE,
                title=entry.title,
                can_play=True,
                can_expand=False,
                thumbnail=(entry.runtime_data.data or {}).get("image_url"),
            )
            for entry in self._entries()
            if entry.runtime_data.image_path() is not None
        ]
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.IMAGE,
            title=self.name,
            can_play=False,
            can_expand=True,
            children=children,
            children_media_class=MediaClass.IMAGE,
        )
