"""Offline equivalence guard: the timeline simulator remains the oracle."""

import json
import random
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from pogo_analyzer import topn
from pogo_analyzer.sim import solo, winrate
from pogo_analyzer.sim.battle import Combatant, Rules, simulate
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


STAGE_EFFECTS = [
    {"self_stages": (0, -4)},
    {"self_stages": (0, -2)},
    {"self_stages": (1, 0)},
    {"opponent_stages": (-1, 0)},
    {"opponent_stages": (0, -1)},
]


@pytest.mark.parametrize("chance", [1.0, 0.5, 0.2, 0.1])
@pytest.mark.parametrize("rank", ["grunt", "leader"])
@pytest.mark.parametrize("stamp", DATES)
def test_stat_stages_seeded_lineups_and_aggregate(chance, rank, stamp):
    rng = random.Random(20261116)
    rules = replace(DEFAULT_ROCKET_RULES, turn_rules=Rules(stat_stages=True))

    def combatant(effect):
        return mon(
            hp=rng.choice([300, 700, 1000]),
            energy=100,
            fast=replace(FAST, power=6, energy_gain=12, **rng.choice(STAGE_EFFECTS)),
            charged=(replace(CHARGE, power=35, stage_chance=chance, **effect),),
        )

    options = [winrate.Option(str(i), combatant(effect)) for i, effect in enumerate(STAGE_EFFECTS)]
    pools = tuple(tuple(rng.sample(options, n)) for n in (2, 3, 2))
    for effect in STAGE_EFFECTS:
        player = combatant(effect)
        kwargs = dict(rank=rank, battle_date=stamp, rules=rules)
        engine = solo._Engine((player,), pools, **kwargs)
        for lineup in winrate.lineups(pools):
            expected, _ = reference((player,), lineup, **kwargs)
            assert engine.outcome(lineup) == expected
        assert engine.aggregate() == winrate.aggregate(
            (player,), winrate.trials((player,), pools, **kwargs)
        )


def test_stat_stages_self_debuff_carries_into_second_slot():
    rules = replace(DEFAULT_ROCKET_RULES, turn_rules=Rules(stat_stages=True))
    player = mon(
        hp=100,
        energy=35,
        fast=replace(FAST, power=10),
        charged=(replace(CHARGE, self_stages=(0, -4)),),
    )
    lineup = tuple(
        winrate.Option(str(i), mon(hp=hp, fast=replace(FAST, power=15)))
        for i, hp in enumerate([1, 200, 200])
    )
    kwargs = dict(rank="grunt", battle_date=None)
    enabled = solo._Engine((player,), pools_for(lineup), rules=rules, **kwargs)
    disabled = solo._Engine((player,), pools_for(lineup), **kwargs)
    first = enabled.segment(enabled.initial, 0).end
    first_off = disabled.segment(disabled.initial, 0).end
    assert (first.hp, first.energy) == (first_off.hp, first_off.energy)
    assert first.stages == (0, -4)
    assert enabled.segment(first, 1) != disabled.segment(first_off, 1)
    expected, _ = reference((player,), lineup, rules=rules, **kwargs)
    assert enabled.outcome(lineup) == expected
    assert enabled.outcome(lineup) != disabled.outcome(lineup)


def test_stat_stages_distinct_prefixes_are_not_merged():
    player = mon(fast=replace(FAST, power=8))
    plain = winrate.Option("plain", mon(hp=1))
    debuff = winrate.Option("debuff", mon(hp=1, fast=replace(FAST, opponent_stages=(-1, 0))))
    target = winrate.Option("target", mon(hp=100, fast=replace(FAST, power=8)))
    pools = ((plain, debuff), (target,), (target,))
    rules = replace(DEFAULT_ROCKET_RULES, turn_rules=Rules(stat_stages=True))
    kwargs = dict(rank="grunt", battle_date=None, rules=rules)
    engine = solo._Engine((player,), pools, **kwargs)
    first, second = (engine.segment(engine.initial, i).end for i in (0, 1))
    assert first.stages == (0, 0) and second.stages == (-1, 0)
    assert first._replace(stages=second.stages) == second
    assert engine.segment(first, 2) != engine.segment(second, 2)
    assert len(engine.memo[1]) == 2
    outcomes = []
    for lead in (plain, debuff):
        lineup = (lead, target, target)
        expected, _ = reference((player,), lineup, **kwargs)
        outcomes.append(engine.outcome(lineup))
        assert outcomes[-1] == expected
    assert outcomes[0] != outcomes[1]
    assert engine.aggregate() == winrate.aggregate(
        (player,), winrate.trials((player,), pools, **kwargs)
    )


def test_stat_stages_boundary_preserves_unreduced_float_meters():
    player = mon(
        hp=1000,
        energy=100,
        charged=(
            replace(CHARGE, power=0, energy=1, stage_chance=0.1, opponent_stages=(0, -1)),
            replace(CHARGE, energy=2, stage_chance=0.5),
        ),
    )
    lineup = tuple(winrate.Option(str(i), mon(hp=10)) for i in range(3))
    rules = replace(DEFAULT_ROCKET_RULES, turn_rules=Rules(stat_stages=True))
    kwargs = dict(rank="grunt", battle_date=None, rules=rules)
    engine = solo._Engine((player,), pools_for(lineup), **kwargs)
    assert engine.initial.meters == ((0, 0.1), (1, 0.0))
    part = engine.segment(engine.initial, 0)
    assert part.fired[0] == 10
    assert part.end.meters == ((0, 1.0999999999999999), (1, 0.0))
    assert engine.outcome(lineup) == reference((player,), lineup, **kwargs)[0]


def test_stat_stages_meters_are_part_of_memo_key():
    player = mon(
        energy=35,
        fast=replace(FAST, power=8),
        charged=(replace(CHARGE, power=0, self_stages=(1, 0), stage_chance=0.5),),
    )
    target = winrate.Option("target", mon(hp=100, fast=replace(FAST, power=8)))
    rules = replace(DEFAULT_ROCKET_RULES, turn_rules=Rules(stat_stages=True))
    engine = solo._Engine((player,), ((target,),) * 3, rank="grunt", battle_date=None, rules=rules)
    fresh = engine.initial
    advanced = fresh._replace(meters=((0, 0.5),))
    assert fresh.stages == advanced.stages
    assert engine.segment(fresh, 0) != engine.segment(advanced, 0)
    assert len(engine.memo[0]) == 2


@pytest.mark.xfail(strict=True, reason='found, not fixed: RocketResult drops core ledger row "o"')
def test_reference_rocket_stat_change_ledger_row():
    player = mon(fast=replace(FAST, power=8, self_stages=(1, 0)))
    opponent = mon(hp=1)
    rules = replace(DEFAULT_ROCKET_RULES, turn_rules=Rules(stat_stages=True))
    assert "o" in simulate(player, opponent, rules=rules.turn_rules).ledger_rows
    result = simulate_rocket((player,), (opponent,) * 3, battle_date=None, rules=rules)
    assert "o" in result.ledger_rows


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
        assert solo.supports(
            (player,),
            pools,
            replace(
                DEFAULT_ROCKET_RULES,
                pause_turns_override=turn,
                turn_rules=Rules(stat_stages=True),
            ),
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
        assert not solo.supports(
            team, pools, replace(rules, turn_rules=replace(rules.turn_rules, stat_stages=True))
        )
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


FUZZ_TYPES = ["normal", "fire", "water", "grass", "steel", "fairy", "dragon", "ghost"]


def _fuzz_mon(rng, rocket, stat_stages=False):
    def effect():
        if not stat_stages:
            return {}
        return dict(
            self_stages=rng.choice([(0, 0), (0, -4), (0, -2), (1, 0)]),
            opponent_stages=rng.choice([(0, 0), (-1, 0), (0, -1)]),
            stage_chance=rng.choice([1.0, 0.5, 0.2, 0.1]),
        )

    def fast():
        return Move(
            "F",
            rng.choice(FUZZ_TYPES),
            rng.choice([0, 1, 3, 5, 10]),
            rng.choice([1, 2, 3, 4, 5]),
            energy_gain=rng.choice([0, 3, 8, 12]),
            **effect(),
        )

    def charged():
        return Move(
            "C" + str(rng.randrange(9)),
            rng.choice(FUZZ_TYPES),
            rng.choice([10, 40, 90, 150]),
            1,
            energy=rng.choice([35, 45, 50, 100]),
            **effect(),
        )

    count = rng.choice([0, 1] if rocket else [0, 1, 2])
    return Combatant(
        rng.choice([90, 100, 100, 120.5]),
        rng.choice([80, 100, 130]),
        rng.choice([1, 5, 30, 80, 200]),
        tuple(rng.sample(FUZZ_TYPES, rng.choice([1, 2]))),
        fast(),
        tuple(charged() for _ in range(count)),
        shadow=(not rocket) and rng.random() < 0.3,
        energy=rng.choice([0, 0, 35, 100]),
    )


@pytest.mark.parametrize(("seed", "stat_stages"), [(1, False), (2, False), (3, False), (3, True)])
def test_fuzz_random_pools_whole_aggregate(seed, stat_stages, monkeypatch):
    """Random players and 1-3 option pools with duplicate combatants, so equal boundary
    states are also reached through distinct prefixes. Whole-dict ==, errors by message."""
    rng = random.Random(seed)
    dates = [*DATES, None]
    hits = 0
    for _ in range(100):
        team = (_fuzz_mon(rng, False, stat_stages),)
        base = [_fuzz_mon(rng, True, stat_stages) for _ in range(4)]
        pools = tuple(
            tuple(
                winrate.Option(str(rng.randrange(3)), rng.choice(base))
                for _ in range(rng.choice([1, 2, 3]))
            )
            for _ in range(3)
        )
        rank = rng.choice(["grunt", "leader", "giovanni"])
        stamp = rng.choice(dates)
        rules = replace(
            DEFAULT_ROCKET_RULES,
            pause_turns_override=rng.choice([None, 1, 3, 20]),
            turn_rules=Rules(stat_stages=stat_stages),
        )
        kwargs = dict(rank=rank, battle_date=stamp, rules=rules)
        try:
            expected = winrate.aggregate(team, winrate.trials(team, pools, **kwargs))
        except ValueError as exc:
            expected = ("error", str(exc))
        engine = solo._Engine(team, pools, **kwargs)
        simulated = [0]
        inner = engine._segment

        def counted(state, option, inner=inner, simulated=simulated):
            simulated[0] += 1
            return inner(state, option)

        engine._segment = counted
        requested = [0]
        outer = engine.segment

        def requests(state, option, outer=outer, requested=requested):
            requested[0] += 1
            return outer(state, option)

        engine.segment = requests
        try:
            actual = engine.aggregate()
        except ValueError as exc:
            actual = ("error", str(exc))
        assert actual == expected, (rank, stamp, rules.pause_turns_override, team, pools)
        hits += requested[0] - simulated[0]
    assert hits > 0
