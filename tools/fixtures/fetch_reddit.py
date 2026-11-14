"""Archive the Reddit threads behind tests/fixtures/sim/ through Arctic Shift.

Run from the repository root: `uv run python tools/fixtures/fetch_reddit.py`.
Responses are cached in .cache/fixture-sources/ (gitignored); cached files are reused.
"""

import json
import time
import urllib.request
from pathlib import Path

CACHE = Path(".cache/fixture-sources")
THREADS = [
    "13puajs",
    "z3qck5",
    "122pfk8",
    "184iqov",
    "10hihvd",
    "10qgrga",
    "1uwoshu",
    "1trpag8",
    "1rs03m9",
    "1o7syt9",
    "12ib623",
    "1puc05x",
]
API = "https://arctic-shift.photon-reddit.com/api/"
HEADERS = {"User-Agent": "pokemon_go_analyzer-fixtures"}


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    for thread in THREADS:
        for kind, endpoint in (
            ("post", f"posts/ids?ids={thread}"),
            ("comments", f"comments/tree?link_id={thread}&limit=500"),
        ):
            path = CACHE / f"{thread}-{kind}.json"
            if path.exists():
                continue
            request = urllib.request.Request(API + endpoint, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
            json.loads(data)
            path.write_bytes(data)
            print(path, len(data), flush=True)
            time.sleep(1)


if __name__ == "__main__":
    main()
