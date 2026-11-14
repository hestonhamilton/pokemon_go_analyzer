import json
from pathlib import Path

import pytest

from pogo_analyzer.rocket_counters import parse_rocket_response, rank


@pytest.fixture
def data():
    return json.loads((Path(__file__).parent / "fixtures/rocket_counters_sample.json").read_text())


def test_random_and_explicit_movesets(data):
    random = parse_rocket_response(data)
    assert (random.defender_id, random.tier, random.defender_cp, random.moveset) == (
        "TEST_SHADOW_FORM",
        "RAID_LEVEL_1",
        4321,
        None,
    )
    assert [c.pokemon_id for c in random.counters] == ["ALPHA", "BETA", "GAMMA"]
    alpha = random.counters[0]
    assert alpha.best.charged_move == "CHARGED_1"
    assert [m.win_ratio for m in alpha.movesets] == [0.0, 1.0]
    assert random.counters[1].best.win_ratio == 0.35
    explicit = parse_rocket_response(data, moveset=("FIRE_FAST", "PUNCH"))
    assert explicit.moveset == ("FIRE_FAST", "PUNCH")
    assert explicit.counters[0].best.overall_rating == 31
    with pytest.raises(ValueError):
        parse_rocket_response(data, moveset=("MISSING", "MOVE"))


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("overall_rating", ["GAMMA", "BETA", "ALPHA"]),
        ("power", ["ALPHA", "BETA", "GAMMA"]),
        ("win_ratio", ["ALPHA", "GAMMA", "BETA"]),
        ("tdo", ["GAMMA", "BETA", "ALPHA"]),
        ("effective_combat_time_ms", ["GAMMA", "BETA", "ALPHA"]),
    ],
)
def test_rank(data, key, expected):
    counters = parse_rocket_response(data).counters
    assert [c.pokemon_id for c in rank(counters, key)] == expected
    assert counters[0].pokemon_id == "ALPHA"


def test_invalid_rank(data):
    with pytest.raises(ValueError):
        rank(parse_rocket_response(data).counters, "invalid")


@pytest.mark.parametrize("key", ["overall_rating", "power", "win_ratio", "tdo"])
def test_selects_moveset_by_requested_key(data, key):
    field = {
        "overall_rating": "overallRating",
        "power": "power",
        "win_ratio": "winRatio",
        "tdo": "tdo",
    }[key]
    data["attackers"][0]["randomMove"]["defenders"][0]["byMove"][0]["result"][field] = 100
    counters = parse_rocket_response(data).counters
    alpha = counters[0]
    ranked = rank(counters, key)
    assert ranked[0] is alpha
    assert alpha.best_for(key) is alpha.movesets[0]
    # Choosing another ranking never changes the stored overall-rating best.
    assert alpha.best is max(alpha.movesets, key=lambda move: move.overall_rating)


def test_time_winners_before_losers_and_losers_by_rating(data):
    counters = parse_rocket_response(data).counters
    alpha, beta, gamma = counters
    for counter in (beta, gamma):
        for move in counter.movesets:
            move.win_ratio = 0
            move.effective_combat_time_ms = 1
    ranked = rank(counters, "effective_combat_time_ms")
    assert ranked == [alpha, gamma, beta]
    assert alpha.best_for("effective_combat_time_ms").effective_combat_time_ms == 9100
    assert gamma.best_for("effective_combat_time_ms") is gamma.best
    assert gamma.best_for("effective_combat_time_ms").effective_combat_time_ms == 1


def test_time_selects_shortest_winning_moveset(data):
    beta = parse_rocket_response(data).counters[1]
    assert beta.best.effective_combat_time_ms == 8100
    assert beta.best_for("effective_combat_time_ms").effective_combat_time_ms == 8000


@pytest.mark.parametrize("field", ["boss", "cp"])
def test_missing_defender_metadata(data, field):
    del data["attackers"][0][field]
    result = parse_rocket_response(data, tier="RAID_LEVEL_UNSET")
    if field == "boss":
        assert result.tier == "RAID_LEVEL_UNSET"
        assert parse_rocket_response(data).tier is None
    else:
        assert result.defender_cp is None
    assert len(result.counters) == 3


@pytest.mark.parametrize("data", [{}, [], None, {"attackers": []}, {"attackers": [{}]}])
def test_unparseable_response(data):
    with pytest.raises(ValueError):
        parse_rocket_response(data)


def test_missing_random_move(data):
    del data["attackers"][0]["randomMove"]
    with pytest.raises(ValueError):
        parse_rocket_response(data)


def test_empty_counter_movesets(data):
    data["attackers"][0]["randomMove"]["defenders"][0]["byMove"] = []
    assert [c.pokemon_id for c in parse_rocket_response(data).counters] == ["BETA", "GAMMA"]


@pytest.mark.parametrize("field", ["overallRating", "power", "tdo", "effectiveCombatTime"])
def test_missing_result_field_skips_moveset_and_empty_counter(data, field):
    alpha = data["attackers"][0]["randomMove"]["defenders"][0]
    del alpha["byMove"][0]["result"][field]
    parsed = parse_rocket_response(data)
    assert len(parsed.counters[0].movesets) == 1
    del alpha["byMove"][1]["result"][field]
    assert [c.pokemon_id for c in parse_rocket_response(data).counters] == ["BETA", "GAMMA"]
