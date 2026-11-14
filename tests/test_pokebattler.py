import io
import json
from urllib.error import HTTPError
from urllib.parse import urlparse

import pytest

from pogo_analyzer.pokebattler import (
    BudgetExceeded,
    NotFound,
    PoliteClient,
    RateLimitedOrBlocked,
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
    assert list(tmp_path.iterdir()) == []
