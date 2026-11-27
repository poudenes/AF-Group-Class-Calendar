"""Tests for the pure schedule logic."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from custom_components.af_group_classes.coordinator import merge_version
from custom_components.af_group_classes.schedule import (
    GroupClass,
    ScheduleParseError,
    ScheduleVersion,
    events_between,
    find_schedule_image,
    normalize_time,
    parse_ai_answer,
)

AMS = ZoneInfo("Europe/Amsterdam")
FIXTURE = Path(__file__).parent / "fixtures" / "zuidas_okt_2026.json"

# Shortened markup of https://afzuidas.nl/ (November 2026).
PAGE = """
<div class="af-pdf-popup-trigger" data-popup="af-pdf-popup-24">
  <a class="theme-button theme-button-quinary" href="#">Bekijk het rooster</a></div>
<img src="https://afzuidas.nl/wp-content/uploads/logo.png" alt="Anytime Fitness">
<div id="af-pdf-popup-24" class="af-pdf-popup-overlay"> <div class="af-pdf-popup-modal">
 <button type="button" class="af-pdf-popup-close">×</button>
 <picture class="af-pdf-popup-content">
  <source type="image/webp"
   srcset="https://afzuidas.nl/wp-content/uploads/AF-Zuidas-rooster-okt-2026-scaled.jpg.webp">
  <img src="https://afzuidas.nl/wp-content/uploads/AF-Zuidas-rooster-okt-2026-scaled.jpg"
   alt="Group lesson schedule"> </picture> </div> </div>
"""


def test_find_schedule_image() -> None:
    assert (
        find_schedule_image(PAGE, "https://afzuidas.nl/")
        == "https://afzuidas.nl/wp-content/uploads/AF-Zuidas-rooster-okt-2026-scaled.jpg"
    )


def test_find_schedule_image_relative_and_missing() -> None:
    html = '<img data-src="/wp-content/uploads/lesrooster-nov.png" alt="">'
    assert find_schedule_image(html, "https://club.nl/x/") == (
        "https://club.nl/wp-content/uploads/lesrooster-nov.png"
    )
    assert find_schedule_image('<img src="/logo.png" alt="logo">', "https://club.nl/") is None


def test_normalize_time() -> None:
    assert normalize_time("9:15") == "09:15"
    assert normalize_time(" 09.15 ") == "09:15"
    assert normalize_time("25:00") is None
    assert normalize_time("09:15-10:30") is None
    assert normalize_time(None) is None


def test_parse_fixture() -> None:
    parsed = parse_ai_answer(FIXTURE.read_text())
    assert parsed.period == "Okt 2026"
    assert parsed.period_start == date(2026, 10, 1)
    assert len(parsed.classes) == 36
    assert parsed.classes[0] == GroupClass(0, "09:15", "10:15", "Pilates", "Studio", "Wiwit")


def test_parse_cleans_up_messy_answer() -> None:
    answer = """Here is the schedule:
```json
{"period": "Okt 2026", "period_start": "oktober",
 "classes": [
  {"weekday": "Dinsdag", "start": "9:15", "end": "10.15", "name": " Circuit  Trainig ",
   "room": "", "instructor": "Celestino"},
  {"weekday": "dinsdag", "start": "09:15", "end": "10:15", "name": "Circuit Trainig",
   "room": null, "instructor": "Celestino"},
  {"weekday": 6, "start": null, "end": null, "name": "Ontmoetingseiland"},
  {"weekday": 9, "start": "10:00", "end": "11:00", "name": "Bogus"},
  {"weekday": 5, "start": "12:00", "end": "", "name": "Zak-Kickboks-Fit"}
 ]}
```"""
    parsed = parse_ai_answer(answer)
    assert parsed.period_start is None
    assert parsed.classes == [
        GroupClass(1, "09:15", "10:15", "Circuit Trainig", None, "Celestino"),
        GroupClass(5, "12:00", "13:00", "Zak-Kickboks-Fit"),
    ]


@pytest.mark.parametrize("answer", ["no json here", '{"classes": []}', '{"x": 1}', 42])
def test_parse_rejects_unusable(answer) -> None:
    with pytest.raises(ScheduleParseError):
        parse_ai_answer(answer)


def _version(valid_from: str, raw: dict | None = None) -> ScheduleVersion:
    parsed = parse_ai_answer(raw or json.loads(FIXTURE.read_text()))
    return ScheduleVersion(date.fromisoformat(valid_from), parsed.notes, parsed.classes)


def test_events_for_a_tuesday() -> None:
    versions = [_version("2026-10-01")]
    start = datetime(2026, 11, 17, 0, 0, tzinfo=AMS)  # a Tuesday
    events = events_between(versions, start, datetime(2026, 11, 18, tzinfo=AMS), AMS)
    assert [(e.start.strftime("%H:%M"), e.summary) for e in events] == [
        ("09:15", "Circuit Trainig"),
        ("10:30", "Fit 60+"),
        ("11:30", "Yin Yoga"),
        ("17:30", "Pilates"),
        ("18:30", "Total Body Workout"),
        ("18:30", "Zumba"),
        ("19:30", "Power Yoga"),
    ]
    fit = events[1]
    assert fit.location == "Park – Ontmoetingseiland Gijsbrecht van Aemstelpark"
    assert fit.description == (
        "Instructor: Celestino\nRoom: *Park\n*Park: Ontmoetingseiland Gijsbrecht van Aemstelpark"
    )
    assert fit.end == datetime(2026, 11, 17, 11, 30, tzinfo=AMS)
    assert fit.uid == "2026-11-17-10:30-fit-60"
    assert events[0].description == "Instructor: Celestino"


def test_events_respect_valid_from_and_versions() -> None:
    new = {"classes": [{"weekday": 1, "start": "07:00", "end": "08:00", "name": "Bootcamp"}]}
    versions = [_version("2026-10-01"), _version("2026-11-17", new)]
    week = events_between(
        versions,
        datetime(2026, 9, 28, tzinfo=AMS),
        datetime(2026, 11, 19, tzinfo=AMS),
        AMS,
    )
    days = {e.start.date() for e in week}
    assert min(days) == date(2026, 10, 1)  # nothing before the first version
    assert [e.summary for e in week if e.start.date() == date(2026, 11, 17)] == ["Bootcamp"]
    assert any(e.summary == "Fit 60+" for e in week if e.start.date() == date(2026, 11, 12))
    assert not any(e.start.date() == date(2026, 11, 18) for e in week)


def test_events_partial_overlap_and_dst() -> None:
    versions = [_version("2026-10-01")]
    # Sunday 25 Oct 2026: clocks go back. Ask from 10:30 -> classes still running count.
    events = events_between(
        versions,
        datetime(2026, 10, 25, 10, 30, tzinfo=AMS),
        datetime(2026, 10, 25, 11, 0, tzinfo=AMS),
        AMS,
    )
    assert [e.summary for e in events] == ["Hiit", "Pilates"]
    assert events[0].start.utcoffset().total_seconds() == 3600  # CET after the change


def test_merge_version_rules() -> None:
    first = parse_ai_answer(FIXTURE.read_text())
    versions = merge_version([], first, date(2026, 11, 18))
    assert [v["valid_from"] for v in versions] == ["2026-10-01"]

    # Same classes in a new image: nothing changes.
    assert merge_version(versions, first, date(2026, 11, 20)) is None

    raw = json.loads(FIXTURE.read_text())
    raw["classes"] = raw["classes"][1:]
    changed = parse_ai_answer(raw)
    after = merge_version(versions, changed, date(2026, 11, 20))
    assert [v["valid_from"] for v in after] == ["2026-10-01", "2026-11-20"]

    # Posted ahead of time: starts on the period start.
    raw["period_start"] = "2026-12-01"
    future = parse_ai_answer(raw | {"classes": raw["classes"][1:]})
    ahead = merge_version(after, future, date(2026, 11, 25))
    assert [v["valid_from"] for v in ahead] == ["2026-10-01", "2026-11-20", "2026-12-01"]

    # Corrected again the same day: replaces that day's version.
    again = merge_version(after, first, date(2026, 11, 20))
    assert [v["valid_from"] for v in again] == ["2026-10-01", "2026-11-20"]


def test_merge_first_version_without_period_starts_this_week() -> None:
    parsed = parse_ai_answer({"classes": [{"weekday": 0, "start": "9:00", "name": "X"}]})
    versions = merge_version([], parsed, date(2026, 11, 19))  # Thursday
    assert versions[0]["valid_from"] == "2026-11-16"
