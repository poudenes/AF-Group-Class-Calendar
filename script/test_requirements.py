"""Print the requirements of the HA components this integration depends on.

pytest-homeassistant-custom-component does not install them (ai_task needs
conversation, which needs hassil etc.), so CI runs:
    pip install $(python script/test_requirements.py)
"""

import json
from importlib.util import find_spec
from pathlib import Path

components = Path(find_spec("homeassistant").origin).parent / "components"
reqs: list[str] = []
for name in ("ai_task", "conversation", "media_source", "camera", "image", "calendar", "http"):
    reqs += json.loads((components / name / "manifest.json").read_text()).get("requirements", [])
print(" ".join(dict.fromkeys(reqs)))
