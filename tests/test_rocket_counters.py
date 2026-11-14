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
