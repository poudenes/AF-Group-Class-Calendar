"""Constants for the Anytime Fitness group class calendar."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "af_group_classes"

CONF_URL: Final = "url"
CONF_AI_TASK_ENTITY: Final = "ai_task_entity"

DEFAULT_URL: Final = "https://afzuidas.nl/"
CALENDAR_NAME: Final = "Anytime Fitness group lessons"

UPDATE_INTERVAL: Final = timedelta(days=1)
MAX_VERSIONS: Final = 12  # old schedules kept so past weeks stay in the calendar

SERVICE_REFRESH: Final = "refresh"
ATTR_FORCE: Final = "force"
ATTR_IMAGE_PATH: Final = "image_path"

ISSUE_BLOCKED: Final = "site_blocked"

AI_INSTRUCTIONS: Final = """\
The attached image is the weekly group class schedule ("lesrooster") of an Anytime \
Fitness gym. Read EVERY class in the grid.

- Columns are weekdays. Use weekday numbers: MAANDAG/Monday=0, DINSDAG=1, WOENSDAG=2, \
DONDERDAG=3, VRIJDAG=4, ZATERDAG=5, ZONDAG/Sunday=6. Check the column header above \
each cell carefully.
- A cell usually holds: a time range, the class name with the room in parentheses, \
and the instructor's name. Ignore empty cells.
- Extra text in a cell such as "30 min" goes into "info".
- Text outside the classes that explains a marker (for example "*Park" followed by an \
address) goes into "notes" as {"<marker>": "<explanation>"}; keep the marker in the \
room/name of the classes it belongs to.
- "period" is the period printed on the schedule (e.g. "Okt 2026"); "period_start" \
is the first day of that period as YYYY-MM-DD (null if unknown).
- Copy names exactly as printed. Times in 24-hour HH:MM with a leading zero.

Answer with ONLY this JSON, no markdown and no explanation:
{"period": "Okt 2026", "period_start": "2026-10-01", "notes": {"*Park": "..."}, \
"classes": [{"weekday": 0, "start": "09:15", "end": "10:15", "name": "Pilates", \
"room": "Studio", "instructor": "Wiwit", "info": null}]}
"""
