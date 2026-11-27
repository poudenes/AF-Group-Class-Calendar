"""Pure logic: schedule image on the club page, AI answer -> classes, classes -> events.

Nothing in here talks to Home Assistant, so it is easy to test.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from html import unescape
from typing import Any
from urllib.parse import urljoin

WEEKDAYS_NL = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")
WEEKDAYS_EN = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r"""([\w:-]+)\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""")
_IMAGE_URL = re.compile(
    r"""https?://[^\s"'<>()]+?\.(?:jpe?g|png|webp)(?:\?[^\s"'<>()]*)?""", re.IGNORECASE
)
_SCHEDULE_HINT = re.compile(r"rooster|schedule|lesrooster|timetable|group[\s_-]?lesson", re.I)
_TIME = re.compile(r"^\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*$")


class ScheduleParseError(Exception):
    """The AI answer could not be turned into a list of classes."""


def _attrs(tag: str) -> dict[str, str]:
    return {
        m.group(1).lower(): unescape(m.group(3) or m.group(4) or m.group(5) or "")
        for m in _ATTR.finditer(tag)
    }


def find_schedule_image(html: str, base_url: str) -> str | None:
    """Return the URL of the group class schedule image on a club page.

    AF club sites (WordPress/Divi) put the schedule in a popup:
    ``<div class="af-pdf-popup-overlay"> ... <img src="...rooster...jpg" alt="Group lesson
    schedule">``. We look for an ``<img>`` whose src/alt mentions the schedule and fall
    back to any image URL with "rooster"/"schedule" in it.
    """
    candidates: list[tuple[int, str]] = []
    for match in _IMG_TAG.finditer(html):
        attrs = _attrs(match.group(0))
        src = attrs.get("src") or attrs.get("data-src") or attrs.get("data-lazy-src")
        if not src or src.startswith("data:"):
            continue
        score = 0
        if _SCHEDULE_HINT.search(src.rsplit("/", 1)[-1]):
            score += 2
        if _SCHEDULE_HINT.search(attrs.get("alt", "")):
            score += 2
        # The popup markup sits right before the img; a bonus keeps it on top.
        if "af-pdf-popup" in html[max(0, match.start() - 600) : match.start()]:
            score += 1
        if score >= 2:
            candidates.append((score, src))
    if not candidates:
        for url in _IMAGE_URL.findall(html):
            if _SCHEDULE_HINT.search(url.rsplit("/", 1)[-1]):
                candidates.append((1, url))
    if not candidates:
        return None
    best = max(candidates, key=lambda c: c[0])[1]
    return urljoin(base_url, best)


def normalize_time(value: Any) -> str | None:
    """'9:15' / '09.15' / ' 9:15 ' -> '09:15'; anything else -> None."""
    if not isinstance(value, str):
        return None
    match = _TIME.match(value)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _weekday(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value <= 6:
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text.isdigit() and 0 <= int(text) <= 6:
            return int(text)
        for names in (WEEKDAYS_NL, WEEKDAYS_EN):
            for index, name in enumerate(names):
                if text and name.startswith(text[:2]) and text in name:
                    return index
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


@dataclass(frozen=True)
class GroupClass:
    """One weekly recurring class."""

    weekday: int  # 0 = Monday
    start: str  # "HH:MM"
    end: str  # "HH:MM"
    name: str
    room: str | None = None
    instructor: str | None = None
    info: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroupClass:
        return cls(**{k: data.get(k) for k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class ParsedSchedule:
    """What the AI read from one schedule image."""

    period: str | None
    period_start: date | None
    notes: dict[str, str]
    classes: list[GroupClass]


def _extract_json(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    if not isinstance(data, str):
        raise ScheduleParseError(f"unexpected AI answer type {type(data).__name__}")
    text = data.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ScheduleParseError("AI answer contains no JSON object")
    try:
        result = json.loads(text[start : end + 1])
    except ValueError as exc:
        raise ScheduleParseError(f"AI answer is not valid JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise ScheduleParseError("AI answer JSON is not an object")
    return result


def parse_ai_answer(data: Any) -> ParsedSchedule:
    """Validate and clean the JSON that the AI task returned."""
    raw = _extract_json(data)
    rows = raw.get("classes")
    if not isinstance(rows, list):
        raise ScheduleParseError("AI answer has no 'classes' list")

    classes: list[GroupClass] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        weekday = _weekday(row.get("weekday", row.get("day")))
        start = normalize_time(row.get("start"))
        end = normalize_time(row.get("end"))
        name = _text(row.get("name"))
        if weekday is None or start is None or name is None:
            continue
        if end is None or end <= start:
            # Missing/odd end time: assume a one-hour class.
            hour, minute = map(int, start.split(":"))
            end = f"{min(hour + 1, 23):02d}:{minute:02d}"
        classes.append(
            GroupClass(
                weekday=weekday,
                start=start,
                end=end,
                name=name,
                room=_text(row.get("room")),
                instructor=_text(row.get("instructor")),
                info=_text(row.get("info")),
            )
        )
    if not classes:
        raise ScheduleParseError("AI answer contains no usable classes")
    # Same class twice (AI repeated a cell) -> keep one.
    classes = sorted(set(classes), key=lambda c: (c.weekday, c.start, c.name))

    period_start: date | None = None
    if isinstance(raw.get("period_start"), str):
        try:
            period_start = date.fromisoformat(raw["period_start"].strip()[:10])
        except ValueError:
            period_start = None

    notes_raw = raw.get("notes")
    notes = (
        {str(k).strip(): t for k, v in notes_raw.items() if (t := _text(v))}
        if isinstance(notes_raw, dict)
        else {}
    )
    return ParsedSchedule(_text(raw.get("period")), period_start, notes, classes)


@dataclass(frozen=True)
class ClassEvent:
    """One concrete occurrence of a class, ready for the calendar."""

    start: datetime
    end: datetime
    summary: str
    location: str | None
    description: str | None
    uid: str


def _note_for(text: str | None, notes: dict[str, str]) -> tuple[str, str] | None:
    if not text:
        return None
    for marker, note in notes.items():
        if marker and marker in text:
            return marker, note
    return None


def describe(group_class: GroupClass, notes: dict[str, str]) -> tuple[str | None, str | None]:
    """Location and description texts for a class."""
    location = group_class.room
    lines: list[str] = []
    if group_class.instructor:
        lines.append(f"Instructor: {group_class.instructor}")
    if group_class.room:
        lines.append(f"Room: {group_class.room}")
    if group_class.info:
        lines.append(group_class.info)
    found = _note_for(group_class.room, notes) or _note_for(group_class.name, notes)
    if found:
        marker, note = found
        lines.append(f"{marker}: {note}")
        if group_class.room and marker in group_class.room:
            location = f"{group_class.room.replace(marker, marker.lstrip('*')).strip()} – {note}"
    return location, "\n".join(lines) or None


@dataclass(frozen=True)
class ScheduleVersion:
    """A schedule that applies from ``valid_from`` until the next version starts."""

    valid_from: date
    notes: dict[str, str]
    classes: list[GroupClass]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleVersion:
        return cls(
            valid_from=date.fromisoformat(data["valid_from"]),
            notes=dict(data.get("notes") or {}),
            classes=[GroupClass.from_dict(c) for c in data.get("classes") or []],
        )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def events_between(
    versions: list[ScheduleVersion], start: datetime, end: datetime, tz: tzinfo
) -> list[ClassEvent]:
    """All class occurrences that overlap [start, end), oldest first.

    ``versions`` must be sorted by ``valid_from``. Each version applies from its own
    ``valid_from`` up to (not including) the next version's ``valid_from``.
    """
    if not versions or end <= start:
        return []
    events: list[ClassEvent] = []
    day = start.astimezone(tz).date() - timedelta(days=1)
    last_day = end.astimezone(tz).date()
    index = 0
    while day <= last_day:
        while index + 1 < len(versions) and versions[index + 1].valid_from <= day:
            index += 1
        version = versions[index]
        if day >= version.valid_from:
            for group_class in version.classes:
                if group_class.weekday != day.weekday():
                    continue
                begin = datetime.combine(day, time.fromisoformat(group_class.start), tz)
                finish = datetime.combine(day, time.fromisoformat(group_class.end), tz)
                if finish <= start or begin >= end:
                    continue
                location, description = describe(group_class, version.notes)
                events.append(
                    ClassEvent(
                        start=begin,
                        end=finish,
                        summary=group_class.name,
                        location=location,
                        description=description,
                        uid=f"{day.isoformat()}-{group_class.start}-{_slug(group_class.name)}",
                    )
                )
        day += timedelta(days=1)
    events.sort(key=lambda e: (e.start, e.summary))
    return events
