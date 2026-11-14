import json
from pathlib import Path

import pytest

from pogo_analyzer import cli, lineups
from pogo_analyzer.pokebattler import NotFound, RateLimitedOrBlocked

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FakeClient:
    instances = []
    missing = set()
    blocked = False

    def __init__(self, cache_dir, **kwargs):
        self.kwargs = kwargs
        self.network_requests = 0
        self.urls = []
        self.instances.append(self)

    def get_json(self, url):
        self.urls.append(url)
        if url == lineups.EVENT_INFO_URL:
            return fixture("lineups.json")
        if url == lineups.PVPOKE_GM_URL:
            return fixture("species.json")
        self.network_requests += 1
        if self.blocked:
            raise RateLimitedOrBlocked(429)
        if any(name in url for name in self.missing):
            raise NotFound(url)
        return fixture("rocket_counters_sample.json")


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    FakeClient.instances = []
    FakeClient.missing = set()
    FakeClient.blocked = False
    monkeypatch.setattr(cli, "PoliteClient", FakeClient)


def test_lineups_and_shields():
    characters = lineups.load_lineups(FakeClient("cache"))
    assert [c.tier for c in characters] == [f"RAID_LEVEL_{n}" for n in range(1, 6)]
    assert [lineups.default_shields(c.tier) for c in characters] == ["SHIELD_0"] * 3 + [
        "SHIELD_2"
    ] * 2
    assert [c.name for c in characters] == [
        "Fire grunt (female)",
        "Mixed grunt (male)",
        "Decoy grunt (female)",
        "Cliff",
        "Giovanni",
    ]
    assert characters[0].slots[0][0].candidates == ["MR_MIME_SHADOW_FORM"]
    assert characters[0].slots[1][0].candidates == [
        "WEEZING_GALARIAN_SHADOW_FORM",
        "WEEZING_GALARIAN_FORM_SHADOW_FORM",
    ]


def test_fallback_and_unresolved(capsys):
    FakeClient.missing = {"WEEZING_GALARIAN_SHADOW_FORM"}
    assert cli.main(["counters", "--character", "fire", "--slot", "2"]) == 0
    assert len(FakeClient.instances[1].urls) == 2
    assert "WEEZING_GALARIAN_FORM_SHADOW_FORM" in capsys.readouterr().out
    FakeClient.missing = {"WEEZING_GALARIAN"}
    assert cli.main(["counters", "--character", "fire", "--slot", "2"]) == 0
    assert "Unresolved defender" in capsys.readouterr().err


@pytest.mark.parametrize("fmt", ["table", "json", "csv"])
def test_output(fmt, capsys):
    assert (
        cli.main(
            [
                "counters",
                "--defender",
                "TEST",
                "--tier",
                "RAID_LEVEL_1",
                "--format",
                fmt,
                "--max-requests",
                "7",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert cli.CREDITS in out and "GAMMA" in out
    if fmt == "json":
        assert json.loads(out)["credits"] == cli.CREDITS
    assert FakeClient.instances[1].kwargs["max_requests"] == 7


def test_tally(capsys):
    assert cli.main(["tally", "--character", "fire", "--top", "1", "--format", "json"]) == 0
    results = json.loads(capsys.readouterr().out)["results"]
    assert results[0]["counter_id"] == "GAMMA"
    assert results[0]["count"] == 2


def test_blocked(capsys):
    FakeClient.blocked = True
    assert cli.main(["counters", "--defender", "TEST", "--tier", "RAID_LEVEL_1"]) == 3
    assert "429; 1 requests made; stopping" in capsys.readouterr().err


def test_requests_default_view_whatever_the_sort():
    assert cli.main(["counters", "--character", "fire", "--slot", "1", "--sort", "time"]) == 0
    counter_urls = [u for u in FakeClient.instances[1].urls if "/rocket/" in u]
    assert counter_urls and all("sort=OVERALL" in u for u in counter_urls)


def test_unknown_dex_is_unresolved_not_fatal(monkeypatch, capsys):
    data = fixture("lineups.json")
    data["1"]["encounters"]["first"] = [{"id": 99999}]
    original = FakeClient.get_json

    def get_json(self, url):
        return data if url == lineups.EVENT_INFO_URL else original(self, url)

    monkeypatch.setattr(FakeClient, "get_json", get_json)
    assert cli.main(["counters", "--character", "fire", "--slot", "1"]) == 0
    assert "Unresolved defender" in capsys.readouterr().err
