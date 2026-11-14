import fcntl
import io
import json
from contextlib import contextmanager
from email.message import Message
from http.client import HTTPException, IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPHandler, build_opener
from urllib.response import addinfourl

import pytest

from pogo_analyzer import pokebattler
from pogo_analyzer.pokebattler import (
    BudgetExceeded,
    CacheError,
    CacheMiss,
    NetworkError,
    NotFound,
    PoliteClient,
    RateLimitedOrBlocked,
    UnexpectedStatus,
    build_rocket_url,
)


class Response(io.BytesIO):
    status = 200


class FakeTime:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


def test_url():
    url = build_rocket_url("INFERNAPE_SHADOW_FORM", "RAID_LEVEL_1", 40)
    parsed = urlparse(url)
    assert parsed.path == "/rocket/defenders/INFERNAPE/levels/RAID_LEVEL_1/attackers/levels/40"
    assert parsed.query == (
        "sort=POWER&view=GROUPED&shieldStrategy=SHIELD_1&defenderShieldStrategy=SHIELD_2"
        "&meta=DUAL_MOVE&aggregation=AVERAGE&attackerTypes=POKEMON_TYPE_ALL"
        "&dodgeStrategy=DODGE_REACTION_TIME&includeLegendary=true&includeMegas=true"
        "&includeShadow=true&numParty=1&weatherCondition=NO_WEATHER"
    )
    assert "/INFERNAPE_SHADOW_FORM_EXTRA/" in build_rocket_url(
        "INFERNAPE_SHADOW_FORM_EXTRA", "RAID_LEVEL_1", 40
    )


@pytest.mark.parametrize(
    ("args", "kwargs"),
    [
        (("X", "RAID_LEVEL_6", 40), {}),
        (("X", "RAID_LEVEL_1", 42), {}),
        (("X", "RAID_LEVEL_1", 40), {"sort": "DODGE_100"}),
        (("X", "RAID_LEVEL_1", 40), {"shield_strategy": "TOTAL_SHIELD"}),
        (("X", "RAID_LEVEL_1", 40), {"defender_shield_strategy": "TOTAL_SHIELD"}),
    ],
)
def test_invalid_url_options(args, kwargs):
    with pytest.raises(ValueError):
        build_rocket_url(*args, **kwargs)


def test_cache_expiry_spacing_and_headers(tmp_path):
    clock = FakeTime()
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return Response(json.dumps({"call": len(calls)}).encode())

    client = PoliteClient(
        tmp_path,
        ttl_seconds=10,
        clock=clock.clock,
        sleep=clock.sleep,
        wall_clock=clock.clock,
        opener=opener,
    )
    assert client.get_json("https://example.test/a") == {"call": 1}
    assert client.get_json("https://example.test/a") == {"call": 1}
    clock.now += 0.5
    client.get_json("https://example.test/b")
    assert clock.sleeps == [1.5]
    assert calls[0][1] == 60
    headers = dict(calls[0][0].header_items())
    assert "https://github.com/hestonhamilton/pokemon_go_analyzer" in headers["User-agent"]
    assert "@" not in headers["User-agent"]
    assert headers["Accept"] == "application/json"
    clock.now += 10
    assert client.get_json("https://example.test/a") == {"call": 3}
    assert client.network_requests == 3


def test_negative_cache_and_budget(tmp_path):
    clock = FakeTime()

    def missing(request, timeout):
        raise HTTPError(request.full_url, 404, "missing", {}, None)

    client = PoliteClient(
        tmp_path,
        ttl_seconds=10,
        opener=missing,
        max_requests=1,
        clock=clock.clock,
        wall_clock=clock.clock,
        sleep=clock.sleep,
    )
    for _ in range(2):
        with pytest.raises(NotFound):
            client.get_json("https://example.test/missing")
    assert client.network_requests == 1
    clock.now += 10
    with pytest.raises(BudgetExceeded):
        client.get_json("https://example.test/missing")


@pytest.mark.parametrize("status", [403, 429, 503])
def test_blocked_no_retry_or_cache(tmp_path, status):
    def blocked(request, timeout):
        raise HTTPError(request.full_url, status, "blocked", {}, None)

    client = PoliteClient(tmp_path, opener=blocked)
    with pytest.raises(RateLimitedOrBlocked) as exc:
        client.get_json("https://example.test")
    assert exc.value.status == status
    assert client.network_requests == 1
    assert {path.name for path in tmp_path.iterdir()} == {".pace.lock", ".pace.json"}


def test_shared_pacing_between_client_instances_and_lock_during_request(tmp_path):
    clock = FakeTime()
    starts = []

    def opener(request, timeout):
        with (tmp_path / ".pace.lock").open("a") as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        starts.append(clock.now)
        return Response(b"{}")

    clients = [
        PoliteClient(
            tmp_path,
            opener=opener,
            wall_clock=clock.clock,
            clock=lambda: 0,
            sleep=clock.sleep,
        )
        for _ in range(2)
    ]
    clients[0].get_json("https://example.test/a")
    clock.now += 0.5
    clients[1].get_json("https://example.test/b")
    assert clock.sleeps == [1.5]
    assert starts == [100, 102]
    assert json.loads((tmp_path / ".pace.json").read_text())["last_request_start"] == 102
    with (tmp_path / ".pace.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_cache_atomic_replace_and_no_temporary_files(tmp_path, monkeypatch):
    original_replace = pokebattler.os.replace
    replacements = []

    def replace(source, destination):
        assert source.parent == destination.parent == tmp_path
        assert json.loads(source.read_text())["body"] == {"ok": True}
        assert not destination.exists()
        with (tmp_path / ".pace.lock").open("a") as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        replacements.append(destination)
        original_replace(source, destination)

    monkeypatch.setattr(pokebattler.os, "replace", replace)
    client = PoliteClient(
        tmp_path, min_interval=0, opener=lambda *a, **kw: Response(b'{"ok":true}')
    )
    assert client.get_json("https://example.test") == {"ok": True}
    assert len(replacements) == 1
    assert set(tmp_path.iterdir()) == {*replacements, tmp_path / ".pace.lock"}


def test_failed_atomic_replace_cleans_temporary_files(tmp_path, monkeypatch):
    def fail(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(pokebattler.os, "replace", fail)
    client = PoliteClient(tmp_path, min_interval=0, opener=lambda *a, **kw: Response(b"{}"))
    with pytest.raises(CacheError, match="replace failed") as exc:
        client.get_json("https://example.test")
    assert exc.value.path.parent == tmp_path
    assert list(tmp_path.iterdir()) == [tmp_path / ".pace.lock"]


@pytest.mark.parametrize("status", [400, 302, 404, 403, 429, 503])
def test_http_error_response_closed(tmp_path, status):
    stream = io.BytesIO()

    def opener(request, timeout):
        raise HTTPError(request.full_url, status, "test", {}, stream)

    client = PoliteClient(tmp_path, min_interval=0, opener=opener)
    with pytest.raises((NotFound, RateLimitedOrBlocked, UnexpectedStatus)):
        client.get_json("https://example.test")
    assert stream.closed
    assert client.network_requests == 1


def test_default_opener_refuses_redirect_without_second_request(tmp_path, monkeypatch):
    calls = []
    streams = []

    class RedirectTransport(HTTPHandler):
        def http_open(self, request):
            calls.append(request.full_url)
            headers = Message()
            headers["Location"] = "http://example.test/redirected"
            stream = io.BytesIO()
            streams.append(stream)
            response = addinfourl(stream, headers, request.full_url, 302)
            response.msg = "Found"
            return response

    monkeypatch.setattr(
        pokebattler, "build_opener", lambda *handlers: build_opener(*handlers, RedirectTransport())
    )
    client = PoliteClient(tmp_path, min_interval=0, max_requests=1)
    with pytest.raises(UnexpectedStatus, match="example.test returned HTTP 302"):
        client.get_json("http://example.test/start")
    assert calls == ["http://example.test/start"]
    assert streams[0].closed
    assert client.network_requests == 1
    with pytest.raises(BudgetExceeded):
        client.get_json("http://example.test/start")


def test_corrupt_cache_is_refetched(tmp_path):
    client = PoliteClient(tmp_path, min_interval=0, opener=lambda *a, **kw: Response(b"{}"))
    client.get_json("https://example.test")
    next(tmp_path.glob("*.json")).write_text('{"partial":')
    assert client.get_json("https://example.test") == {}
    assert client.network_requests == 2


def test_future_pace_stamp_caps_sleep(tmp_path):
    clock = FakeTime()
    (tmp_path / ".pace.json").write_text(json.dumps({"last_request_start": clock.now + 3600}))
    client = PoliteClient(
        tmp_path,
        opener=lambda *a, **kw: Response(b"{}"),
        clock=clock.clock,
        wall_clock=clock.clock,
        sleep=clock.sleep,
    )
    assert client.get_json("https://example.test") == {}
    assert clock.sleeps == [client.min_interval]


@pytest.mark.parametrize("status", [200, 404])
def test_cache_rechecked_after_lock_before_budget_or_request(tmp_path, monkeypatch, status):
    clock = FakeTime()
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        if status == 404:
            raise HTTPError(request.full_url, 404, "missing", {}, None)
        return Response(b'{"winner":1}')

    first, second = [
        PoliteClient(
            tmp_path,
            opener=opener,
            clock=clock.clock,
            wall_clock=clock.clock,
            sleep=clock.sleep,
        )
        for _ in range(2)
    ]
    second.max_requests = 0
    original_lock = second._pace_lock
    url = "https://example.test/shared"

    @contextmanager
    def another_process_wins_lock():
        # The second client's initial read has missed. Another client now fills it.
        if status == 404:
            with pytest.raises(NotFound):
                first.get_json(url)
        else:
            first.get_json(url)
        with original_lock():
            yield

    monkeypatch.setattr(second, "_pace_lock", another_process_wins_lock)
    if status == 404:
        with pytest.raises(NotFound):
            second.get_json(url)
    else:
        assert second.get_json(url) == {"winner": 1}
    assert calls == [url]
    assert first.network_requests == 1
    assert second.network_requests == 0
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "failure",
    [
        IncompleteRead(b"partial", 100),
        HTTPException("bad HTTP"),
        URLError("offline"),
        TimeoutError("timed out"),
        ConnectionError("connection lost"),
        OSError("read failed"),
    ],
)
@pytest.mark.parametrize("during_read", [False, True])
def test_http_exchange_errors_are_network_errors(tmp_path, failure, during_read):
    class BrokenResponse(Response):
        def read(self, *args, **kwargs):
            raise failure

    def opener(request, timeout):
        if during_read:
            return BrokenResponse()
        raise failure

    client = PoliteClient(tmp_path, opener=opener)
    with pytest.raises(NetworkError, match="example.test") as exc:
        client.get_json("https://example.test")
    assert exc.value.__cause__ is failure
    assert client.network_requests == 1


@pytest.mark.parametrize("operation", ["mkdir", "flock", "pace_write", "cache_write", "read"])
def test_cache_failures_name_path(tmp_path, monkeypatch, operation):
    client = PoliteClient(tmp_path / "cache", opener=lambda *a, **kw: Response(b"{}"))
    reason = PermissionError("read-only cache")

    def fail(*args, **kwargs):
        raise reason

    if operation == "mkdir":
        monkeypatch.setattr(pokebattler.Path, "mkdir", fail)
    elif operation == "flock":
        monkeypatch.setattr(pokebattler.fcntl, "flock", fail)
    elif operation == "read":
        monkeypatch.setattr(pokebattler.Path, "read_text", fail)
    else:
        original = pokebattler.os.replace

        def replace(source, destination):
            if (destination.name == ".pace.json") == (operation == "pace_write"):
                raise reason
            original(source, destination)

        monkeypatch.setattr(pokebattler.os, "replace", replace)

    with pytest.raises(CacheError, match="read-only cache") as exc:
        client.get_json("https://example.test")
    expected = {
        "mkdir": client.cache_dir,
        "flock": client.cache_dir / ".pace.lock",
        "pace_write": client.cache_dir / ".pace.json",
    }.get(operation)
    if expected is not None:
        assert exc.value.path == expected
    else:
        assert exc.value.path.parent == client.cache_dir
        assert exc.value.path.name.endswith(".json")
    assert client.network_requests == (1 if operation == "cache_write" else 0)


def test_cache_only_never_locks_or_requests(tmp_path, monkeypatch):
    client = PoliteClient(tmp_path, opener=lambda *a, **kw: Response(b"{}"))
    url = "https://example.test/cached"
    client.get_json(url)
    client.cache_only = True

    def forbidden(*args, **kwargs):
        pytest.fail("cache-only mode must not lock, pace, or request")

    monkeypatch.setattr(client, "_pace_lock", forbidden)
    monkeypatch.setattr(client, "opener", forbidden)
    assert client.get_json(url) == {}
    with pytest.raises(CacheMiss):
        client.get_json("https://example.test/missing")
    assert client.network_requests == 1


def test_cache_only_ignores_expired_entries(tmp_path):
    clock = FakeTime()
    client = PoliteClient(
        tmp_path,
        ttl_seconds=10,
        opener=lambda *a, **kw: Response(b"{}"),
        wall_clock=clock.clock,
        clock=clock.clock,
        sleep=clock.sleep,
    )
    url = "https://example.test/expired"
    client.get_json(url)
    clock.now += 10
    client.cache_only = True
    with pytest.raises(CacheMiss):
        client.get_json(url)
    assert client.network_requests == 1
