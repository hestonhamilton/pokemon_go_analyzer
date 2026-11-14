"""Archive the PvPoke game masters in effect on each fixture's reference date.

Run from the repository root: `uv run python tools/fixtures/fetch_pvpoke.py`.
Uses the end of each UTC day; results are cached in .cache/fixture-sources/.
"""

import json
import urllib.request
from pathlib import Path

CACHE = Path(".cache/fixture-sources")
DATES = [
    "2022-12-03",
    "2023-01-21",
    "2023-02-01",
    "2023-03-26",
    "2023-11-27",
    "2026-03-12",
    "2026-05-30",
    "2026-07-14",
]
HEADERS = {"User-Agent": "pokemon_go_analyzer-fixtures"}


def fetch(name, url):
    path = CACHE / name
    if not path.exists():
        request = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read()
        json.loads(data)
        path.write_bytes(data)
    return json.loads(path.read_text())


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    for date in DATES:
        commits = fetch(
            f"pvpoke-{date}-commit.json",
            "https://api.github.com/repos/pvpoke/pvpoke/commits"
            f"?path=src/data/gamemaster.json&until={date}T23:59:59Z&per_page=1",
        )
        sha = commits[0]["sha"]
        fetch(
            f"pvpoke-{sha}-gamemaster.json",
            f"https://raw.githubusercontent.com/pvpoke/pvpoke/{sha}/src/data/gamemaster.json",
        )
        print(date, sha, flush=True)


if __name__ == "__main__":
    main()
