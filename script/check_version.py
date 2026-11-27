"""Check the version in manifest.json and print its CHANGELOG notes.

    python script/check_version.py           # manifest version is X.Y.Z and in CHANGELOG.md
    python script/check_version.py v1.2.3    # ... and equals this release tag

On success the CHANGELOG section of that version is printed (used as release notes).
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "custom_components" / "af_group_classes" / "manifest.json"
CHANGELOG = ROOT / "CHANGELOG.md"


def fail(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)
    sys.exit(1)


version = json.loads(MANIFEST.read_text())["version"]
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    fail(f"manifest.json version {version!r} is not MAJOR.MINOR.PATCH")

if len(sys.argv) > 1 and sys.argv[1] != f"v{version}":
    fail(f"Tag {sys.argv[1]} does not match manifest.json version v{version}")

match = re.search(
    rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)",
    CHANGELOG.read_text(),
    re.MULTILINE | re.DOTALL,
)
if not match or not match.group(1).strip():
    fail(f"CHANGELOG.md has no entry for {version}")

print(match.group(1).strip())
