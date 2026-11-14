"""A small, sequential and cached client for Pokebattler's public API."""

import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from pogo_analyzer import __version__

BASE_URL = "https://fight.pokebattler.com"
USER_AGENT = (
    f"pokemon_go_analyzer/{__version__} (+https://github.com/hestonhamilton/pokemon_go_analyzer)"
)


class NotFound(Exception):
    """The requested API resource was not found."""


class RateLimitedOrBlocked(Exception):
    """The server declined the request or is unavailable."""

    def __init__(self, status: int):
        self.status = status
        super().__init__(f"Pokebattler returned HTTP {status}")


class BudgetExceeded(Exception):
    """The network request budget has been exhausted."""


def build_rocket_url(
    defender_id,
    tier,
    attacker_level,
    *,
    sort="OVERALL",
    attacker_shields="SHIELD_2",
    defender_shields="SHIELD_0",
) -> str:
    """Build a Rocket counters URL, rejecting unsupported request options."""
    if tier not in {*(f"RAID_LEVEL_{n}" for n in range(1, 6)), "RAID_LEVEL_UNSET"}:
        raise ValueError("invalid tier")
    if type(attacker_level) is not int or attacker_level not in {20, 25, 30, 35, 40, 45, 50}:
        raise ValueError("invalid attacker level")
    if sort not in {"OVERALL", "POWER", "WIN", "TIME"}:
        raise ValueError("invalid sort")
    if attacker_shields not in {"SHIELD_0", "SHIELD_1", "SHIELD_2"}:
        raise ValueError("invalid attacker shields")
    if defender_shields not in {"SHIELD_0", "SHIELD_2"}:
        raise ValueError("invalid defender shields")
    query = urlencode(
        {
            "sort": sort,
            "shieldStrategy": attacker_shields,
            "defenderShieldStrategy": defender_shields,
            "meta": "DUAL_MOVE",
        }
    )
    return (
        f"{BASE_URL}/rocket/defenders/{quote(defender_id, safe='')}/levels/{tier}"
        f"/attackers/levels/{attacker_level}?{query}"
    )


class PoliteClient:
    """Cache responses and space sequential network requests by their start times."""

    def __init__(
        self,
        cache_dir: Path,
        ttl_seconds=86400,
        min_interval=2.0,
        *,
        clock=time.monotonic,
        sleep=time.sleep,
        wall_clock=time.time,
        opener=None,
        max_requests=None,
    ):
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self.min_interval = min_interval
        self.clock = clock
        self.sleep = sleep
        self.wall_clock = wall_clock
        self.opener = opener if opener is not None else urlopen
        self.max_requests = max_requests
        self.network_requests = 0
        self._last_request = None

    def get_json(self, url) -> dict:
        cache_path = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        try:
            entry = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                entry["url"] == url
                and entry["status"] in (200, 404)
                and 0 <= self.wall_clock() - entry["fetched_at"] < self.ttl_seconds
            ):
                if entry["status"] == 404:
                    raise NotFound(url)
                return entry["body"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if self.max_requests is not None and self.network_requests >= self.max_requests:
            raise BudgetExceeded("network request budget exhausted")
        if self._last_request is not None:
            delay = self.min_interval - (self.clock() - self._last_request)
            if delay > 0:
                self.sleep(delay)
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        self._last_request = self.clock()
        self.network_requests += 1
        try:
            with self.opener(request, timeout=60) as response:
                status = response.status
                body = json.load(response) if status == 200 else None
        except HTTPError as exc:
            status = exc.code
            body = None
        if status == 404:
            self._write_cache(cache_path, url, status, None)
            raise NotFound(url)
        if status in (403, 429) or 500 <= status <= 599:
            raise RateLimitedOrBlocked(status)
        if status != 200:
            raise HTTPError(url, status, "Unexpected HTTP status", None, None)
        self._write_cache(cache_path, url, status, body)
        return body

    def _write_cache(self, path, url, status, body):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "fetched_at": self.wall_clock(),
                    "url": url,
                    "status": status,
                    "body": body,
                }
            ),
            encoding="utf-8",
        )
