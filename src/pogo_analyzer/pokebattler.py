"""A small, sequential and cached client for Pokebattler's public API."""

import fcntl
import hashlib
import json
import math
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pogo_analyzer import __version__

BASE_URL = "https://fight.pokebattler.com"
USER_AGENT = (
    f"pokemon_go_analyzer/{__version__} (+https://github.com/hestonhamilton/pokemon_go_analyzer)"
)


class NotFound(Exception):
    """The requested API resource was not found."""

    def __init__(self, url):
        self.host = urlsplit(url).netloc
        super().__init__(f"{self.host} returned HTTP 404")


class NetworkError(Exception):
    """A request could not reach the server or read its response."""

    def __init__(self, host, reason):
        self.host = host
        super().__init__(f"{host}: network error ({reason})")


class BadResponse(Exception):
    """The server's successful response was not JSON."""

    def __init__(self, host):
        self.host = host
        super().__init__(f"{host} returned invalid JSON")


class UnexpectedStatus(Exception):
    """The server returned an unsupported HTTP status."""

    def __init__(self, status, host):
        self.status = status
        self.host = host
        super().__init__(f"{host} returned HTTP {status}")


class RateLimitedOrBlocked(Exception):
    """The server declined the request or is unavailable."""

    def __init__(self, status: int, host="fight.pokebattler.com"):
        self.status = status
        self.host = host
        super().__init__(f"{host} returned HTTP {status}")


class BudgetExceeded(Exception):
    """The network request budget has been exhausted."""


class NoRedirect(HTTPRedirectHandler):
    """Let the client classify redirects without making another request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _atomic_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_rocket_url(
    defender_id,
    tier,
    attacker_level,
    *,
    sort="POWER",
    shield_strategy="SHIELD_1",
    defender_shield_strategy="SHIELD_2",
) -> str:
    """Build a Rocket counters URL, rejecting unsupported request options."""
    if tier not in {*(f"RAID_LEVEL_{n}" for n in range(1, 6)), "RAID_LEVEL_UNSET"}:
        raise ValueError("invalid tier")
    if type(attacker_level) is not int or attacker_level not in {20, 25, 30, 35, 40, 45, 50}:
        raise ValueError("invalid attacker level")
    if sort not in {"OVERALL", "POWER", "WIN", "TIME"}:
        raise ValueError("invalid sort")
    if shield_strategy not in {"SHIELD_0", "SHIELD_1", "SHIELD_2"}:
        raise ValueError("invalid shield strategy")
    if defender_shield_strategy not in {"SHIELD_0", "SHIELD_1", "SHIELD_2"}:
        raise ValueError("invalid defender shield strategy")
    query = urlencode(
        {
            "sort": sort,
            "view": "GROUPED",
            "shieldStrategy": shield_strategy,
            "defenderShieldStrategy": defender_shield_strategy,
            "meta": "DUAL_MOVE",
            "aggregation": "AVERAGE",
            "attackerTypes": "POKEMON_TYPE_ALL",
            "dodgeStrategy": "DODGE_REACTION_TIME",
            "includeLegendary": "true",
            "includeMegas": "true",
            "includeShadow": "true",
            "numParty": "1",
            "weatherCondition": "NO_WEATHER",
        }
    )
    defender_id = defender_id.removesuffix("_SHADOW_FORM")
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
        self.opener = opener if opener is not None else build_opener(NoRedirect()).open
        self.max_requests = max_requests
        self.network_requests = 0
        self._last_request = None

    def get_json(self, url) -> dict:
        try:
            return self._get_json(url)
        except (URLError, OSError) as exc:
            raise NetworkError(urlsplit(url).netloc, str(exc)) from exc

    def _get_json(self, url):
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
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        host = urlsplit(url).netloc
        with self._paced():
            self._last_request = self.clock()
            self.network_requests += 1
            try:
                with self.opener(request, timeout=60) as response:
                    status = response.status
                    body = json.load(response) if status == 200 else None
            except HTTPError as exc:
                status = exc.code
                body = None
                exc.close()
            except (ValueError, UnicodeError) as exc:
                raise BadResponse(host) from exc
        if status == 404:
            self._write_cache(cache_path, url, status, None)
            raise NotFound(url)
        if status in (403, 429) or 500 <= status <= 599:
            raise RateLimitedOrBlocked(status, host)
        if status != 200:
            raise UnexpectedStatus(status, host)
        self._write_cache(cache_path, url, status, body)
        return body

    @contextmanager
    def _paced(self):
        if self.min_interval <= 0:
            yield
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with (self.cache_dir / ".pace.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                path = self.cache_dir / ".pace.json"
                delay = 0
                try:
                    last = json.loads(path.read_text(encoding="utf-8"))["last_request_start"]
                    if isinstance(last, (int, float)) and math.isfinite(last):
                        delay = self.min_interval - (self.wall_clock() - last)
                except (OSError, ValueError, KeyError, TypeError):
                    pass
                if self._last_request is not None:
                    delay = max(delay, self.min_interval - (self.clock() - self._last_request))
                if delay > 0:
                    self.sleep(delay)
                _atomic_json(path, {"last_request_start": self.wall_clock()})
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _write_cache(self, path, url, status, body):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json(
            path,
            {
                "fetched_at": self.wall_clock(),
                "url": url,
                "status": status,
                "body": body,
            },
        )
