"""Offline equivalence guard: the timeline simulator remains the oracle."""

import json
import random
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from pogo_analyzer import topn
from pogo_analyzer.sim import solo, winrate
from pogo_analyzer.sim.battle import Combatant, Rules
from pogo_analyzer.sim.calculator import Move
from pogo_analyzer.sim.rocket import DEFAULT_ROCKET_RULES, rule_data, simulate_rocket

DATES = [e["from"] or "2025-11-14" for e in rule_data()["eras"]] + ["2026-11-14"]
FAST = Move("F", "normal", 0, 1, energy_gain=0)
CHARGE = Move("C", "normal", 100, 1, energy=35)


def mon(**kwargs):
    return replace(Combatant(100, 100, 200, ("normal",), FAST), **kwargs)


def pools_for(lineup):
    return tuple((o,) for o in lineup)


def reference(team, lineup, **kwargs):
    result = simulate_rocket(team, tuple(o.combatant for o in lineup), **kwargs)
    summary = winrate.battle_summary(result, team)
    fired = [
        sum(a.startswith("charged:hit:") for t in result.timeline for a in t.core.actions[i])
        for i in range(2)
    ]
    return dict(
        winner=result.winner,
        ended_by=result.ended_by,
        turns=result.turns_elapsed,
        player_hp=result.hp[0][0],
        fainted=summary["fainted"],
        fired=fired,
    ), result


@pytest.fixture
def builds():
    gm = json.loads((Path(__file__).parent / "fixtures/calc/gamemaster.json").read_text())
    return topn.build_candidates(gm["pokemon"], gm["moves"], (40,))[0]


@pytest.mark.parametrize("rank", ["grunt", "leader", "giovanni"])
@pytest.mark.parametrize("stamp", DATES)
@pytest.mark.parametrize("override", [None, 1, 8, 20])
def test_seeded_lineups(rank, stamp, override, builds):
    rng = random.Random(20261114)
    rules = replace(DEFAULT_ROCKET_RULES, pause_turns_override=override)
    options = [winrate.Option(c.species_id, replace(c.team[0], shadow=False)) for c in builds]
    pools = tuple(tuple(rng.sample(options, 4)) for _ in range(3))
    # Include multiple player charges, shadow damage, starting energy and attack ties.
    for candidate in rng.sample(builds, 2):
        player = candidate.team[0]
        player = replace(player, energy=35, shadow=True, charged=(*player.charged, CHARGE))
        engine = solo._Engine((player,), pools, rank=rank, battle_date=stamp, rules=rules)
        for _ in range(4):
            lineup = tuple(rng.choice(p) for p in pools)
            expected, _ = reference((player,), lineup, rank=rank, battle_date=stamp, rules=rules)
            assert engine.outcome(lineup) == expected


@pytest.mark.parametrize("rank", ["grunt", "leader", "giovanni"])
@pytest.mark.parametrize("stamp", DATES)
@pytest.mark.parametrize("override", [None, 6])
def test_aggregate_exact(rank, stamp, override):
    rules = replace(DEFAULT_ROCKET_RULES, pause_turns_override=override)
    player = mon(fast=replace(FAST, power=8, energy_gain=9), charged=(CHARGE,))
    # Unequal pool sizes and repeated species test the uniform species denominators.
    # Some reserves have no charges; both metadata variants must survive early KOs.
    pools = tuple(
        tuple(
            winrate.Option(
                str(j % 2),
                mon(
                    hp=hp,
                    charged=(CHARGE,) if j % 2 else (),
                    energy=70,
                    fast=replace(FAST, power=power, turns=turns, energy_gain=7),
                ),
            )
            for j, (hp, power, turns) in enumerate([(40, 4, 1), (220, 30, 3), (500, 60, 5)][:n])
        )
        for n in (2, 3, 2)
    )
    for team in ((player,), (replace(player, hp=1),)):
        actual = solo.aggregate(team, pools, rank=rank, battle_date=stamp, rules=rules)
        expected = winrate.aggregate(
            team, winrate.trials(team, pools, rank=rank, battle_date=stamp, rules=rules)
        )
        assert actual == expected


@pytest.mark.parametrize("rank", ["grunt", "leader", "giovanni"])
@pytest.mark.parametrize("stamp", DATES)
def test_timeouts_and_leader_loss(rank, stamp):
    player = mon(hp=2864)
    lineup = tuple(winrate.Option(str(i), mon(hp=1 if i < 2 else 2876)) for i in range(3))
    kwargs = dict(rank=rank, battle_date=stamp)
    expected, result = reference((player,), lineup, **kwargs)
    assert expected["ended_by"] == "timeout"
    if stamp == "2025-11-14":
        assert expected["winner"] == (None if rank == "grunt" else "rocket")
    if stamp == "2026-03-12":
        assert expected["winner"] is None
    assert solo._Engine((player,), pools_for(lineup), **kwargs).outcome(lineup) == expected
    assert solo.aggregate((player,), pools_for(lineup), **kwargs) == winrate.aggregate(
        (player,), [(lineup, winrate.battle_summary(result, (player,)))]
    )


@pytest.mark.parametrize("stamp", DATES)
def test_double_ko_and_shields(stamp):
    era = next(
        e
        for e in rule_data()["eras"]
        if (e["from"] is None or stamp >= e["from"]) and (e["until"] is None or stamp < e["until"])
    )
    # The final opponent lands 20 - faint_pause one-damage fast moves.
    # Its last hit retaliates on the player's final KO turn.
    player = mon(hp=20 - era["faint"], fast=replace(FAST, turns=20))
    slow = mon(hp=1, fast=replace(FAST, turns=100000))
    lineup = tuple(winrate.Option(str(i), c) for i, c in enumerate((slow, slow, mon(hp=1))))
    expected, _ = reference((player,), lineup, rank="grunt", battle_date=stamp)
    assert expected["winner"] is None and expected["fainted"] == [1, 2, 3]
    assert (
        solo._Engine((player,), pools_for(lineup), rank="grunt", battle_date=stamp).outcome(lineup)
        == expected
    )
    player = mon(
        hp=1000, charged=(CHARGE,), energy=100, fast=replace(FAST, power=5, energy_gain=10)
    )
    lineup = tuple(winrate.Option(str(i), replace(player, attack=101)) for i in range(3))
    expected, result = reference((player,), lineup, rank="leader", battle_date=stamp)
    assert all(expected["fired"])
    assert result.shields[1] == 0
    assert (
        solo._Engine((player,), pools_for(lineup), rank="leader", battle_date=stamp).outcome(lineup)
        == expected
    )


@pytest.mark.parametrize("stamp", DATES)
@pytest.mark.parametrize("attack", [100, 101])
def test_simultaneous_charges_and_nullification(stamp, attack):
    player = mon(energy=100, charged=(CHARGE,), fast=replace(FAST, turns=3, energy_gain=10))
    opponent = replace(player, attack=attack)
    lineup = tuple(winrate.Option(str(i), opponent) for i in range(3))
    kwargs = dict(rank="leader", battle_date=stamp)
    expected, result = reference((player,), lineup, **kwargs)
    first_fired = [
        any(a.startswith("charged:hit:") for a in actions)
        for actions in result.timeline[0].core.actions
    ]
    assert first_fired == (
        [attack == 100, attack == 101] if stamp == "2025-11-14" else [True, True]
    )
    assert solo._Engine((player,), pools_for(lineup), **kwargs).outcome(lineup) == expected


RULE_CHANGES = dict(
    pauses=False,
    pause_reading="cwizz1",
    pause_trigger="player_charged",
    faint_trigger="rocket_replacement",
    era_turn_rules=False,
    rocket_charged="never",
    rocket_charged_damage_scale=0.5625,
    rocket_shields=False,
    player_shield_policy="never",
    player_shield_threshold=0.25,
    timer=False,
    turn_rules=Rules(ledger_j_next_turn_charged=True),
)


def test_supports_and_fallback(monkeypatch):
    player = mon(hp=10)
    pools = ((winrate.Option("target", mon(hp=3)),),) * 3
    assert set(RULE_CHANGES) == {f.name for f in fields(DEFAULT_ROCKET_RULES)} - {
        "pause_turns_override"
    }
    assert solo.supports((player,), pools, DEFAULT_ROCKET_RULES)
    for turn in range(1, 21):
        assert solo.supports(
            (player,), pools, replace(DEFAULT_ROCKET_RULES, pause_turns_override=turn)
        )
    assert not solo.supports((player,), pools[:2], DEFAULT_ROCKET_RULES)
    assert not solo.supports((player,), ((), *pools[1:]), DEFAULT_ROCKET_RULES)
    cases = [((player, player), DEFAULT_ROCKET_RULES)]
    cases.extend(
        ((player,), replace(DEFAULT_ROCKET_RULES, **{field: value}))
        for field, value in RULE_CHANGES.items()
    )
    monkeypatch.setattr(solo, "aggregate", lambda *a, **k: pytest.fail("must fall back"))
    for team, rules in cases:
        assert not solo.supports(team, pools, rules)
        kwargs = dict(rank="leader", battle_date="2026-11-14", rules=rules)
        assert topn.full_result(SimpleNamespace(team=team), pools, **kwargs) == winrate.aggregate(
            team, winrate.trials(team, pools, **kwargs)
        )
    calls = []

    def custom(*a, **k):
        calls.append(1)
        return simulate_rocket(*a, **k)

    kwargs = dict(rank="grunt", battle_date=None)
    assert topn.full_result(
        SimpleNamespace(team=(player,)), pools, battle=custom, **kwargs
    ) == winrate.aggregate((player,), winrate.trials((player,), pools, **kwargs))
    assert calls == [1]


def test_full_result_and_pause_band(builds, monkeypatch):
    candidates = [
        next(c for c in builds if c.species_id == name)
        for name in ("metagross", "kirlia", "snubbull")
    ]
    pools = tuple(
        tuple(winrate.Option(c.species_id, c.team[0]) for c in candidates[:n]) for n in (2, 1, 2)
    )
    kwargs = dict(rank="leader", battle_date="2026-11-14")
    original_aggregate = solo.aggregate
    calls = []

    def counted(*a, **k):
        calls.append(k["rules"].pause_turns_override)
        return original_aggregate(*a, **k)

    monkeypatch.setattr(solo, "aggregate", counted)
    for c in candidates:
        assert topn.full_result(c, pools, **kwargs) == topn.full_result(
            c, pools, battle=lambda *a, **k: simulate_rocket(*a, **k), **kwargs
        )
        row = topn.full_result(
            c, pools, trial_runner=lambda *a, **k: pytest.fail("engine"), **kwargs
        )
        assert row.pop("execution") == dict(mode="exact solo engine", workers=1)
        assert row == topn.full_result(c, pools, **kwargs)
    ranked = topn.rank_character(candidates, pools, k=3, pause_band=(6, 8), **kwargs)
    assert {None, 6, 8} <= set(calls)
    monkeypatch.setattr(solo, "supports", lambda *a: False)
    assert ranked == topn.rank_character(candidates, pools, k=3, pause_band=(6, 8), **kwargs)


def test_bounded_damage_cache():
    assert 0 < solo._damage_cached.cache_info().maxsize <= 32768
