"""Validate the acceptance corpus offline; no battle mechanics are implemented here."""

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "sim"
BATTLES = json.loads((FIXTURES / "battles.json").read_text())
CP_READINGS = json.loads((FIXTURES / "cp_readings.json").read_text())
MOVE_HISTORY = json.loads((FIXTURES / "move_history.json").read_text())
SPECIES_MOVES = json.loads((FIXTURES / "species_moves.json").read_text())
BATTLE_REGIMES = {"rcpm-old", "rcpm-dec-2025"}
CP_REGIMES = BATTLE_REGIMES | {"rcpm-oct-2025"}
RANKS = {"grunt", "leader", "giovanni"}
KINDS = {
    "damage_per_hit_dealt",
    "damage_per_hit_taken",
    "hits_to_ko",
    "rocket_hp",
    "player_hp",
    "remaining_hp_after",
    "survives_hits",
}
# recorded: read off the battle; measured: derived by the author from in-game
# readings; calculated: the author's model output; inferred: our reading of the text.
BASES = {"recorded", "measured", "calculated", "inferred"}
ACCEPTANCE_BASES = {"recorded", "measured"}
# open_discrepancy: a recorded value our model currently misses. It is reported on
# every run and never downgraded to an expected failure.
BATTLE_STATUSES = {"expected_pass", "open_discrepancy", "weak"}
# Every acceptance battle predates the level-80 update; the current regime is
# backed by CP readings only.
LEVEL_80_UPDATE = date(2025, 10, 15)
TYPES = {
    "normal",
    "fire",
    "water",
    "electric",
    "grass",
    "ice",
    "fighting",
    "poison",
    "ground",
    "flying",
    "psychic",
    "bug",
    "rock",
    "ghost",
    "dragon",
    "dark",
    "steel",
    "fairy",
}


def assert_integer(value, minimum, maximum=None):
    assert type(value) is int
    assert value >= minimum
    if maximum is not None:
        assert value <= maximum


def assert_date(value):
    assert isinstance(value, str)
    assert date.fromisoformat(value).isoformat() == value


def assert_sha(value):
    assert re.fullmatch(r"[0-9a-f]{40}", value)


def assert_source_and_evidence(record):
    source = urlparse(record["source"])
    assert source.scheme == "https"
    assert source.netloc in {"www.reddit.com", "www.youtube.com"}
    assert source.path
    assert isinstance(record["evidence"], str) and record["evidence"].strip()
    if "evidence_note" in record:
        assert isinstance(record["evidence_note"], str) and record["evidence_note"].strip()


def referenced_moves(battle):
    return {
        actor[key]
        for actor in (battle["rocket"], battle["player"])
        for key in ("fast_move", "charged_move")
        if actor[key] is not None
    }


def test_corpus_is_complete_and_ids_are_unique():
    assert isinstance(BATTLES, list) and BATTLES
    assert isinstance(CP_READINGS, list) and CP_READINGS
    ids = [battle["id"] for battle in BATTLES]
    assert len(ids) == len(set(ids))
    # The eight retained rows in F4 have four measured columns (32 cells).
    assert Counter(battle["fixture"] for battle in BATTLES) == {
        "F1": 9,
        "F2": 1,
        "F3": 2,
        "F4": 32,
        "F5": 6,
        "F7": 2,
        "F8": 5,
        "F9": 1,
    }
    assert Counter(battle["status"] for battle in BATTLES) == {
        "expected_pass": 44,
        "open_discrepancy": 2,
        "weak": 12,
    }
    assert Counter(battle["basis"] for battle in BATTLES) == {
        "recorded": 47,
        "measured": 1,
        "calculated": 9,
        "inferred": 1,
    }
    assert Counter(reading["status"] for reading in CP_READINGS) == {
        "expected_pass": 166,
        "weak": 5,
    }
    assert len(CP_READINGS) == 171
    # Do not accidentally deduplicate the paired readings or their one-CP anomaly.
    paired = [row for row in CP_READINGS if "/1o7syt9/" in row["source"]]
    assert Counter(row["trainer_level"] for row in paired) == {50: 13, 70: 13}
    assert any(row["species"] == "gallade" and row["cp"] == 10214 for row in paired)


@pytest.mark.parametrize("battle", BATTLES, ids=lambda battle: battle["id"])
def test_battle_schema_and_references(battle):
    assert {
        "id",
        "fixture",
        "source",
        "evidence",
        "battle_date",
        "regime",
        "trainer_level",
        "rocket",
        "player",
        "observed",
        "basis",
        "status",
        "status_reason",
    } <= battle.keys()
    assert battle["id"].startswith(battle["fixture"] + "-")
    assert re.fullmatch(r"F\d+-[a-z0-9-]+", battle["id"])
    assert_source_and_evidence(battle)
    assert_date(battle["battle_date"])
    assert battle["regime"] in BATTLE_REGIMES
    if battle["trainer_level"] is not None:
        assert_integer(battle["trainer_level"], 1, 80)
    assert battle["status"] in BATTLE_STATUSES
    assert battle["basis"] in BASES
    if battle["basis"] not in ACCEPTANCE_BASES:
        # A published calculation or our own inference is never an acceptance target.
        assert battle["status"] == "weak"
    if battle["status"] == "expected_pass":
        assert date.fromisoformat(battle["battle_date"]) < LEVEL_80_UPDATE
    if battle["status"] in {"open_discrepancy", "weak"}:
        assert isinstance(battle["status_reason"], str) and battle["status_reason"].strip()
    else:
        assert battle["status_reason"] is None or isinstance(battle["status_reason"], str)

    rocket = battle["rocket"]
    assert {"species", "rank", "slot", "fast_move", "charged_move"} == rocket.keys()
    assert rocket["species"] in SPECIES_MOVES["species"]
    assert not rocket["species"].endswith("_shadow")
    assert rocket["rank"] in RANKS
    if rocket["slot"] is not None:
        assert_integer(rocket["slot"], 1, 3)
    assert rocket["charged_move"] is None

    player = battle["player"]
    assert {
        "species",
        "form",
        "level",
        "ivs",
        "fast_move",
        "charged_move",
        "stat_stage",
    } <= player.keys()
    if player["species"] is not None:
        assert player["species"] in SPECIES_MOVES["species"]
        assert not player["species"].endswith("_shadow")
        assert player["form"] in {"normal", "shadow", "purified", "mega"}
    else:
        assert player["form"] is None
    if player["level"] is not None:
        assert type(player["level"]) in {int, float}
        assert 1 <= player["level"] <= 55
        assert player["level"] * 2 == int(player["level"] * 2)
    assert {"atk", "def", "hp"} == player["ivs"].keys()
    for iv in player["ivs"].values():
        if iv is not None:
            assert_integer(iv, 0, 15)
    assert {"atk", "def"} == player["stat_stage"].keys()
    for stage in player["stat_stage"].values():
        assert_integer(stage, -4, 4)
    if "mega_level" in player or "effective_level" in player:
        assert player["form"] == "mega"
        assert_integer(player["mega_level"], 1, 4)
        assert type(player["effective_level"]) in {int, float}
        assert player["level"] <= player["effective_level"] <= 55

    observed = battle["observed"]
    assert {"kind", "value", "hits"} <= observed.keys()
    assert observed["kind"] in KINDS
    assert_integer(observed["value"], 0)
    if observed["hits"] is not None:
        assert_integer(observed["hits"], 1)
        assert observed["kind"] == "remaining_hp_after"
    if observed["kind"] in {"remaining_hp_after", "survives_hits"}:
        assert observed["subject"] in {"player", "rocket"}
    if observed["kind"] in {"hits_to_ko", "rocket_hp", "player_hp", "survives_hits"}:
        assert observed["value"] > 0
    if observed["kind"].startswith("damage_per_hit"):
        assert observed["move"] in referenced_moves(battle)
        attacker = player if observed["kind"] == "damage_per_hit_dealt" else rocket
        assert observed["move"] in {attacker["fast_move"], attacker["charged_move"]}
    if "shielded" in observed:
        assert type(observed["shielded"]) is bool
        assert observed["kind"] == "damage_per_hit_dealt"
        assert observed["move"] == player["charged_move"]
        assert rocket["rank"] in {"leader", "giovanni"}

    for actor in (rocket, player):
        for key in ("fast_move", "charged_move"):
            if actor[key] is not None:
                assert actor[key] in SPECIES_MOVES["moves"]
    for move in referenced_moves(battle):
        # A same-date snapshot proves coverage; an older unrelated snapshot does not.
        snapshots = [s for s in MOVE_HISTORY[move] if s["as_of"] == battle["battle_date"]]
        assert len(snapshots) == 1, (battle["id"], move)


@pytest.mark.parametrize("reading", CP_READINGS)
def test_cp_reading_schema(reading):
    assert {
        "trainer_level",
        "species",
        "rank",
        "cp",
        "regime",
        "source",
        "evidence",
    } <= reading.keys()
    assert_integer(reading["trainer_level"], 1, 80)
    assert reading["species"] in SPECIES_MOVES["species"]
    assert reading["rank"] in RANKS or reading["rank"] is None
    assert reading["basis"] in ACCEPTANCE_BASES
    assert reading["status"] in {"expected_pass", "weak"}
    if reading["status"] == "weak":
        assert isinstance(reading["status_reason"], str) and reading["status_reason"].strip()
    else:
        assert reading["status_reason"] is None
    if reading["rank"] is None:
        # An unstated rank can't be a target: fitting it would be circular.
        assert reading["status"] == "weak"
    assert_integer(reading["cp"], 1)
    assert reading["regime"] in CP_REGIMES
    assert_source_and_evidence(reading)
    if reading["regime"] == "rcpm-oct-2025":
        assert reading["trainer_level"] == 70
        assert "/1o7syt9/" in reading["source"]


@pytest.mark.parametrize("move,snapshots", MOVE_HISTORY.items())
def test_move_history_schema(move, snapshots):
    assert move in SPECIES_MOVES["moves"]
    assert snapshots
    dates = [snapshot["as_of"] for snapshot in snapshots]
    assert dates == sorted(set(dates))
    for snapshot in snapshots:
        assert {
            "as_of",
            "pvpoke_commit",
            "type",
            "power",
            "energy_gain",
            "energy",
            "turns",
        } == snapshot.keys()
        assert_date(snapshot["as_of"])
        assert_sha(snapshot["pvpoke_commit"])
        assert snapshot["type"] in TYPES
        assert snapshot["type"] == SPECIES_MOVES["moves"][move]["type"]
        for key in ("power", "energy_gain", "energy"):
            assert_integer(snapshot[key], 0)
        assert_integer(snapshot["turns"], 1)
        assert (snapshot["energy"] == 0) != (snapshot["energy_gain"] == 0)


def test_extract_and_snapshot_consistency():
    assert {"as_of", "pvpoke_commit", "species", "moves"} == SPECIES_MOVES.keys()
    assert SPECIES_MOVES["as_of"] == max(battle["battle_date"] for battle in BATTLES)
    assert_sha(SPECIES_MOVES["pvpoke_commit"])
    species_used = {reading["species"] for reading in CP_READINGS}
    for battle in BATTLES:
        species_used.add(battle["rocket"]["species"])
        if battle["player"]["species"] is not None:
            species_used.add(battle["player"]["species"])
    assert SPECIES_MOVES["species"].keys() == species_used
    for species in SPECIES_MOVES["species"].values():
        assert {"baseStats", "types"} == species.keys()
        assert {"atk", "def", "hp"} == species["baseStats"].keys()
        for stat in species["baseStats"].values():
            assert_integer(stat, 1)
        # PvPoke represents monotypes with a second "none" slot; retain it verbatim.
        assert len(species["types"]) == 2
        assert species["types"][0] in TYPES
        assert species["types"][1] in TYPES | {"none"}
    moves_used = set().union(*(referenced_moves(battle) for battle in BATTLES))
    assert SPECIES_MOVES["moves"].keys() == MOVE_HISTORY.keys() == moves_used
    commits_by_date = {}
    current_dates = set()
    for snapshots in MOVE_HISTORY.values():
        current_dates.add(snapshots[-1]["as_of"])
        for snapshot in snapshots:
            commits_by_date.setdefault(snapshot["as_of"], set()).add(snapshot["pvpoke_commit"])
    assert len(current_dates) == 1
    assert next(iter(current_dates)) > SPECIES_MOVES["as_of"]
    assert all(len(commits) == 1 for commits in commits_by_date.values())
    assert commits_by_date[SPECIES_MOVES["as_of"]] == {SPECIES_MOVES["pvpoke_commit"]}
    for path in FIXTURES.glob("*.json"):
        assert path.stat().st_size < 500 * 1024
