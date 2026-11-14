"""Check every fixture quote verbatim against the archived Reddit threads.

Run fetch_reddit.py first, then `uv run python tools/fixtures/verify_quotes.py`.
Exits non-zero if any quote is missing from the thread its record cites.
"""

import json
import re
import sys
from pathlib import Path

CACHE = Path(".cache/fixture-sources")
FIXTURES = Path("tests/fixtures/sim")


def strings(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("selftext", "body", "title") and isinstance(value, str):
                yield value
            else:
                yield from strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from strings(item)


def thread_text(thread):
    parts = []
    for kind in ("post", "comments"):
        path = CACHE / f"{thread}-{kind}.json"
        if not path.exists():
            raise SystemExit(f"missing {path}: run tools/fixtures/fetch_reddit.py")
        parts.extend(strings(json.loads(path.read_text())))
    return "\n".join(parts)


def main():
    records = json.loads((FIXTURES / "battles.json").read_text())
    records += json.loads((FIXTURES / "cp_readings.json").read_text())
    texts, checked, missing = {}, 0, []
    for record in records:
        match = re.search(r"/comments/([a-z0-9]+)/", record["source"])
        if not match:
            continue  # Non-Reddit sources (video metadata) are not archived here.
        thread = match.group(1)
        if thread not in texts:
            texts[thread] = thread_text(thread)
        checked += 1
        if record["evidence"] not in texts[thread]:
            missing.append(record.get("id") or f"{record['species']} {record['cp']}")
    print(f"{checked} quotes checked, {len(missing)} missing")
    for name in missing:
        print("MISSING", name)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
