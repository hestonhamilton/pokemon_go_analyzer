import csv
import io
import json
from pathlib import Path

import pytest

from pogo_analyzer import cli, lineups
from pogo_analyzer.pokebattler import CacheMiss, NotFound, RateLimitedOrBlocked

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
        self.cache_only = False
        self.urls = []
        self.instances.append(self)

    def get_json(self, url):
        self.urls.append(url)
        if url == lineups.EVENT_INFO_URL:
            return fixture("lineups.json")
        if url == lineups.PVPOKE_GM_URL:
            return fixture("species.json")
        if self.cache_only:
            raise CacheMiss(url)
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
    assert [lineups.default_shield_strategy(slot) for slot in (1, 2, 3, None)] == [
        "SHIELD_1",
        "SHIELD_1",
        "SHIELD_0",
        "SHIELD_1",
    ]
    assert [c.name for c in characters] == [
        "Fire grunt (female)",
        "Mixed grunt (male)",
        "Decoy grunt (female)",
        "Cliff",
        "Giovanni",
    ]
    assert characters[0].slots[0][0].candidates == ["MR_MIME", "MR_MIME_FORM"]
    assert characters[0].slots[1][0].candidates == [
        "WEEZING_GALARIAN",
        "WEEZING_GALARIAN_FORM",
    ]


def test_fallback_and_unresolved(capsys):
    FakeClient.missing = {"/WEEZING_GALARIAN/"}
    assert cli.main(["counters", "--character", "fire", "--slot", "2"]) == 0
    assert len(FakeClient.instances[1].urls) == 2
    assert "WEEZING_GALARIAN_FORM" in capsys.readouterr().out
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
    captured = capsys.readouterr()
    out = captured.out
    assert "GAMMA" in out
    if fmt == "json":
        assert json.loads(out)["credits"] == cli.CREDITS
        assert not captured.err
    elif fmt == "csv":
        rows = list(csv.reader(io.StringIO(out)))
        assert rows[0] == list(cli.FIELDS)
        assert len(rows) == 4
        assert all(len(row) == len(cli.FIELDS) for row in rows)
        assert cli.CREDITS not in out
        assert cli.CREDITS in captured.err
    else:
        assert cli.CREDITS in out
    assert FakeClient.instances[1].kwargs["max_requests"] == 7


def test_tally(capsys):
    assert cli.main(["tally", "--character", "fire", "--top", "1", "--format", "json"]) == 0
    results = json.loads(capsys.readouterr().out)["results"]
    assert results[0]["counter_id"] == "GAMMA"
    assert results[0]["count"] == 2


def test_blocked(capsys):
    FakeClient.blocked = True
    assert cli.main(["counters", "--defender", "TEST", "--tier", "RAID_LEVEL_1"]) == 3
    assert "stopped: fight.pokebattler.com returned HTTP 429 after 1 requests; try again later" in (
        capsys.readouterr().err
    )


def test_requests_default_view_whatever_the_sort():
    assert cli.main(["counters", "--character", "fire", "--slot", "1", "--sort", "time"]) == 0
    counter_urls = [u for u in FakeClient.instances[1].urls if "/rocket/" in u]
    assert counter_urls and all("sort=POWER" in u for u in counter_urls)


def test_unknown_dex_is_unresolved_not_fatal(monkeypatch, capsys):
    data = fixture("lineups.json")
    data["1"]["encounters"]["first"] = [{"id": 99999}]
    original = FakeClient.get_json

    def get_json(self, url):
        return data if url == lineups.EVENT_INFO_URL else original(self, url)

    monkeypatch.setattr(FakeClient, "get_json", get_json)
    assert cli.main(["counters", "--character", "fire", "--slot", "1"]) == 0
    assert "Unresolved defender" in capsys.readouterr().err


def test_slot_settings_and_deduplication(monkeypatch):
    encounter = lineups.Encounter("test", ["TEST"])
    monkeypatch.setattr(
        cli,
        "load_lineups",
        lambda source: [
            lineups.Character("test", "RAID_LEVEL_1", [[encounter], [encounter], [encounter]])
        ],
    )
    assert cli.main(["counters", "--character", "test"]) == 0
    urls = FakeClient.instances[1].urls
    assert len(urls) == 2
    assert "shieldStrategy=SHIELD_1" in urls[0]
    assert "shieldStrategy=SHIELD_0" in urls[1]
    assert all("defenderShieldStrategy=SHIELD_2" in url for url in urls)


def test_explicit_shield_options():
    assert (
        cli.main(
            [
                "counters",
                "--defender",
                "TEST",
                "--tier",
                "RAID_LEVEL_1",
                "--shield-strategy",
                "SHIELD_2",
                "--defender-shield-strategy",
                "SHIELD_1",
            ]
        )
        == 0
    )
    url = FakeClient.instances[1].urls[0]
    assert "shieldStrategy=SHIELD_2" in url
    assert "defenderShieldStrategy=SHIELD_1" in url


def test_lineup_tolerates_missing_gender_slots_and_encounter_id(monkeypatch, capsys):
    data = fixture("lineups.json")
    entry = data["1"]
    del entry["gender"]
    entry["encounters"] = {"first": [{"template": "BAD"}, {"id": 122}]}
    original = FakeClient.get_json
    monkeypatch.setattr(
        FakeClient,
        "get_json",
        lambda self, url: data if url == lineups.EVENT_INFO_URL else original(self, url),
    )
    character = lineups.load_lineups(FakeClient("cache"))[0]
    assert character.name == "Fire grunt (unknown)"
    assert character.slots[1:] == [[], []]
    assert len(character.slots[0]) == 1
    assert "Skipping malformed encounter" in capsys.readouterr().err


def test_dex_only_form_fallback(capsys):
    FakeClient.missing = {"/MR_MIME/"}
    assert cli.main(["counters", "--character", "fire", "--slot", "1"]) == 0
    assert len(FakeClient.instances[1].urls) == 2
    assert "MR_MIME_FORM" in capsys.readouterr().out


def test_tally_counts_defender_per_tier(monkeypatch, capsys):
    encounter = lineups.Encounter("test", ["TEST"])
    monkeypatch.setattr(
        cli,
        "load_lineups",
        lambda source: [
            lineups.Character("test", "RAID_LEVEL_1", [[encounter], [], [encounter]]),
            lineups.Character("test", "RAID_LEVEL_4", [[encounter], [], []]),
        ],
    )
    assert cli.main(["tally", "--character", "test", "--format", "json"]) == 0
    row = json.loads(capsys.readouterr().out)["results"][0]
    assert row["count"] == 2
    assert row["defenders"] == "TEST (RAID_LEVEL_1), TEST (RAID_LEVEL_4)"


@pytest.mark.parametrize(
    ("key", "field"),
    [
        ("overall_rating", "overallRating"),
        ("power", "power"),
        ("tdo", "tdo"),
        ("win_ratio", "winRatio"),
    ],
)
def test_output_uses_selected_moveset(monkeypatch, capsys, key, field):
    data = fixture("rocket_counters_sample.json")
    data["attackers"][0]["randomMove"]["defenders"][0]["byMove"][0]["result"][field] = 100
    monkeypatch.setattr(FakeClient, "get_json", lambda self, url: data)
    assert (
        cli.main(
            [
                "counters",
                "--defender",
                "TEST",
                "--tier",
                "RAID_LEVEL_1",
                "--sort",
                key,
                "--format",
                "json",
                "--top",
                "1",
            ]
        )
        == 0
    )
    row = json.loads(capsys.readouterr().out)["results"][0]
    assert row["counter_id"] == "ALPHA"
    assert row["charged_move"] == "CHARGED_0"
    assert row[key] == 100


def test_time_output_keeps_loser_own_time(monkeypatch, capsys):
    data = fixture("rocket_counters_sample.json")
    counters = data["attackers"][0]["randomMove"]["defenders"]
    for counter in counters[1:]:
        for move in counter["byMove"]:
            move["result"]["winRatio"] = 0
            move["result"]["effectiveCombatTime"] = 123
    monkeypatch.setattr(FakeClient, "get_json", lambda self, url: data)
    assert (
        cli.main(
            [
                "counters",
                "--defender",
                "TEST",
                "--tier",
                "RAID_LEVEL_1",
                "--sort",
                "time",
                "--format",
                "json",
            ]
        )
        == 0
    )
    rows = json.loads(capsys.readouterr().out)["results"]
    assert [row["counter_id"] for row in rows] == ["ALPHA", "GAMMA", "BETA"]
    assert rows[0]["time_s"] == 9.1
    assert rows[1]["time_s"] == 0.123


@pytest.mark.parametrize("command", ["counters", "tally"])
@pytest.mark.parametrize("fmt", ["csv", "table"])
@pytest.mark.parametrize("credits_column", [False, True])
def test_credits_column(command, fmt, credits_column, capsys):
    args = [command, "--defender", "TEST", "--tier", "RAID_LEVEL_1", "--format", fmt]
    if credits_column:
        args.append("--credits-column")
    assert cli.main(args) == 0
    captured = capsys.readouterr()
    if fmt == "csv":
        reader = csv.DictReader(io.StringIO(captured.out))
        rows = list(reader)
        fields = reader.fieldnames
        assert cli.CREDITS in captured.err
    else:
        lines = captured.out.splitlines()
        fields = lines[0].split(" | ")
        rows = [dict(zip(fields, line.split(" | "), strict=True)) for line in lines[1:-1]]
    assert ("source" in fields) == credits_column
    assert rows
    if credits_column:
        assert all(row["source"] == cli.SHORT_CREDIT for row in rows)


def test_credits_column_keeps_json_credits(capsys):
    assert (
        cli.main(
            [
                "counters",
                "--defender",
                "TEST",
                "--tier",
                "RAID_LEVEL_1",
                "--format",
                "json",
                "--credits-column",
            ]
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["credits"] == cli.CREDITS
    assert all("source" not in row for row in data["results"])


@pytest.mark.parametrize(
    ("selector", "selected"),
    [
        ("male", {"FIRE_MALE", "WATER_MALE"}),
        ("FeMaLe", {"FIRE_FEMALE"}),
        ("grunt", {"FIRE_MALE", "FIRE_FEMALE", "WATER_MALE", "ICE"}),
        ("FiRe grunt", {"FIRE_MALE", "FIRE_FEMALE"}),
        ("  fire   male  ", {"FIRE_MALE"}),
        ("cliff", {"CLIFF"}),
        ("ice grunt", {"ICE"}),
    ],
)
def test_character_whole_word_matching(monkeypatch, capsys, selector, selected):
    names = {
        "FIRE_MALE": "Fire grunt (male)",
        "FIRE_FEMALE": "Fire grunt (female)",
        "WATER_MALE": "Water grunt (male)",
        "CLIFF": "Cliff",
        "ICE": "Ice-grunt (unknown)",
    }
    monkeypatch.setattr(
        cli,
        "load_lineups",
        lambda source: [
            lineups.Character(name, "RAID_LEVEL_1", [[lineups.Encounter(key, [key])], [], []])
            for key, name in names.items()
        ],
    )
    assert cli.main(["counters", "--character", selector, "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)["results"]
    assert {row["defender"] for row in rows} == selected


@pytest.mark.parametrize("selector", ["fir", "male fire cliff", "missing", "", "() -"])
def test_character_no_match_lists_available(selector, capsys):
    assert cli.main(["counters", "--character", selector]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "Available characters:" in captured.err
    for name in ("Fire grunt (female)", "Mixed grunt (male)", "Cliff", "Giovanni"):
        assert name in captured.err
    assert not FakeClient.instances[1].urls


@pytest.mark.parametrize(
    "bad",
    [{"not_pokemon": []}, [], {"pokemon": "x"}],
)
def test_malformed_species_source_exits_5(bad, monkeypatch, capsys):
    original = FakeClient.get_json

    def get_json(self, url):
        return bad if url == lineups.PVPOKE_GM_URL else original(self, url)

    monkeypatch.setattr(FakeClient, "get_json", get_json)
    assert cli.main(["lineups"]) == 5
    err = capsys.readouterr().err
    assert "raw.githubusercontent.com" in err and "Traceback" not in err


def test_species_entries_without_fields_are_skipped(monkeypatch):
    data = fixture("species.json")
    data["pokemon"] = [{"dex": 1}, "junk", *data["pokemon"]]
    original = FakeClient.get_json

    def get_json(self, url):
        return data if url == lineups.PVPOKE_GM_URL else original(self, url)

    monkeypatch.setattr(FakeClient, "get_json", get_json)
    assert lineups.load_lineups(FakeClient("cache"))
