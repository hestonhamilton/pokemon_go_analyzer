"""Hand arithmetic checks of model rules, never Rocket acceptance targets."""

from dataclasses import asdict, replace
from datetime import date

import pytest

from pogo_analyzer.sim.battle import (
    ChargedWhenReady,
    Combatant,
    FastOnly,
    Rules,
    simulate,
)
from pogo_analyzer.sim.calculator import Move
from pogo_analyzer.sim.rocket import RocketRules, rocket_combatant, rule_data, simulate_rocket
from pogo_analyzer.sim.stats import rocket_stats

# Zero power still does floor(0)+1 = 1, irrespective of shadows or typing.
F = Move("F", "normal", 0, 1, energy_gain=0)
C = Move("C", "normal", 0, 1, energy=20)


def mon(hp=100, fast=F, charged=(), energy=0, attack=100, defence=100):
    return Combatant(attack, defence, hp, ("normal",), fast, charged, energy=energy)


def run(player=None, rocket=None, turns=20, **options):
    return simulate_rocket(
        [player or mon()],
        [rocket or mon()],
        battle_date=None,
        rules=RocketRules(**options),
        max_turns=turns,
    )


def starts(result, side, kind="fast"):
    return [
        r.core.number
        for r in result.timeline
        if any(a.startswith(f"{kind}:start:") for a in r.core.actions[side])
    ]


@pytest.mark.parametrize(
    "stamp,era,charge,faint,switch",
    [
        ("2025-11-30", "before-dec-2025", 5, 7, 7),
        ("2025-12-01", "dec-2025", 8, 12, 12),
        ("2026-08-31", "dec-2025", 8, 12, 12),
        ("2026-09-01", "sep-2026", 7, 7, 9),
        (None, "sep-2026", 7, 7, 9),
    ],
)
def test_era_charge_pause(stamp, era, charge, faint, switch):
    result = simulate_rocket(
        [mon(charged=(C,), energy=20)],
        [mon()],
        battle_date=stamp,
        max_turns=16,
    )
    # t1 charge hits, no new inputs t2..t(1+N). Resume t(N+2).
    # t2 is also PvPoke's one post-charge turn, so no extra turn is added.
    assert result.era == era
    assert result.pause_lengths == (charge, faint, switch)
    assert starts(result, 1) == [1, *range(charge + 2, 17)]
    assert result.timeline[0].pause_through == charge + 1
    assert result.timeline[1].core.actions == ((), ())


@pytest.mark.parametrize("stamp,n", [("2025-11-01", 7), ("2026-01-01", 12), ("2026-10-01", 7)])
def test_faint_pause(stamp, n):
    result = simulate_rocket(
        [mon()],
        [mon(1), mon(100)],
        battle_date=stamp,
        max_turns=16,
        player_policy=FastOnly(),
    )
    # t1: F=1 KOs slot 1; its already submitted F retaliates for 1.
    # Slot 2 arrives at end t1; pause turns 2..N+1; first input N+2.
    assert result.timeline[0].core.hp == (99, 0)
    assert result.timeline[0].replacements == (None, 2)
    assert result.timeline[1].active_slots == (1, 2)
    assert starts(result, 1) == [1, *range(n + 2, 17)]
    assert result.hp == ((99 - (15 - n),), (0, 85))
    assert result.timeline[0].pause_through == 1 + n


def test_cwizz1_reading_and_trigger_override():
    # t1 Rocket charge=1, default player shields ->1; t2 core suppresses;
    # cwizz1 additionally blocks t2..8, so t9 is first new Rocket input.
    rocket = mon(charged=(C,), energy=20)
    default = run(rocket=rocket, turns=12)
    alternative = run(rocket=rocket, turns=12, pause_reading="cwizz1")
    overridden = run(
        rocket=rocket, turns=12, pause_reading="cwizz1", pause_trigger="player_charged"
    )
    assert starts(default, 1) == list(range(3, 13))
    assert starts(alternative, 1) == list(range(9, 13))
    assert starts(overridden, 1) == starts(default, 1)
    assert alternative.pause_lengths == (7, 7, 6)
    assert alternative.pause_trigger == "any_charged"
    assert default.pause_trigger == "player_charged"


def test_any_charge_option_and_max_composition():
    rocket = mon(charged=(C,), energy=20)
    result = run(rocket=rocket, turns=10, pause_trigger="any_charged")
    # Seven paused turns t2..8 overlap the core's t2. t9 (not t10) resumes.
    assert starts(result, 1) == [9, 10]
    assert "l" in result.ledger_rows and "unverified" in result.flags


def test_fast_already_in_flight_lands_inside_pause():
    class AtTwo(FastOnly):
        def choose_charged(self, own, opponent, turn):
            return 0 if turn == 2 else None

    result = simulate_rocket(
        [mon(charged=(C,), energy=20)],
        [mon(fast=replace(F, turns=5))],
        battle_date=None,
        player_policy=AtTwo(),
        max_turns=11,
    )
    # Rocket F starts t1 (normally due t5). Player C hits t2. PvPoke flushes
    # F on t3 (post-charge), even though new Rocket inputs pause t3..9.
    assert starts(result, 1) == [1, 10]
    assert result.timeline[2].core.actions[1] == ("fast:hit:F",)
    assert result.timeline[2].core.damage == (0, 1)
    assert result.timeline[2].pause_through == 9


@pytest.mark.parametrize("rank", ["leader", "giovanni"])
def test_first_two_rocket_shields_then_unshielded(rank):
    # P: power 20 -> raw about 18.72 against shadow defence, damage 19.
    # Energy 60 buys C on t1,t3,t5. Shields make first two damage 1.
    charge = replace(C, power=20)
    result = simulate_rocket(
        [mon(charged=(charge,), energy=60)],
        [mon()],
        rank=rank,
        battle_date=None,
        max_turns=5,
    )
    assert [result.timeline[t - 1].core.damage[0] for t in (1, 3, 5)] == [1, 1, 19]
    assert [result.timeline[t - 1].shields[1] for t in (1, 3, 5)] == [1, 0, 0]
    assert result.rocket_shield_policy == "first_two"
    assert result.hp[1] == (79,)


def test_grunt_never_shields():
    result = run(player=mon(charged=(replace(C, power=20),), energy=60), turns=5)
    assert [result.timeline[t - 1].core.damage[0] for t in (1, 3, 5)] == [19] * 3
    assert result.shields[1] == 2  # Available but unused, as in the source.
    assert result.rocket_shield_policy == "never"


@pytest.mark.parametrize(
    "policy,damages,remaining",
    [
        ("first_two", [1, 1, 19], 0),
        ("never", [19, 19, 19], 2),
        ("threshold", [19, 1, 1], 0),
    ],
)
def test_player_shield_policies(policy, damages, remaining):
    # Rocket charge power20: raw18.72 ->19. Threshold=.2 of current HP:
    # at 100HP, 19<20 -> no shield; at 81HP, 19>=16.2 -> shield twice.
    result = run(
        rocket=mon(charged=(replace(C, power=20),), energy=60),
        turns=5,
        player_shield_policy=policy,
        player_shield_threshold=0.2,
    )
    assert [result.timeline[t - 1].core.damage[1] for t in (1, 3, 5)] == damages
    assert result.shields[0] == remaining
    assert result.player_shield_policy == policy


def test_threshold_is_inclusive():
    # Zero power C does1; 1 >= .01*100 exactly. Shield is spent.
    result = run(
        rocket=mon(charged=(C,), energy=20),
        turns=1,
        player_shield_policy="threshold",
        player_shield_threshold=0.01,
    )
    assert result.shields[0] == 1


def test_never_rocket_charge():
    result = run(rocket=mon(charged=(C,), energy=100), turns=10, rocket_charged="never")
    assert starts(result, 1, "charged") == []
    assert result.energy[1] == (100,)
    assert "l" not in result.ledger_rows and "unverified" not in result.flags


@pytest.mark.parametrize("scale,damage", [(1.0, 3), (0.5625, 2)])
def test_damage_scale_raw_before_floor(scale, damage):
    # Rocket power3: raw 0.5*3*1.2(STAB)*1.2(shadow atk)*1.3 = 2.808.
    # Default floor(2.808)+1=3; scaled floor(2.808*.5625)+1=2.
    # Alternative floor(final3*.5625)=1; not the selected interpretation.
    result = run(
        rocket=mon(charged=(replace(C, power=3),), energy=20),
        turns=1,
        player_shield_policy="never",
        rocket_charged_damage_scale=scale,
    )
    assert result.timeline[0].core.damage[1] == damage
    assert result.flags == ("unverified",)
    assert any("before floor" in s for s in result.interpretations)


def test_scaled_charge_shield_override_and_threshold():
    rocket = mon(charged=(replace(C, power=3),), energy=20)
    shielded = run(rocket=rocket, turns=1, rocket_charged_damage_scale=0.5625)
    threshold = run(
        rocket=rocket,
        turns=1,
        rocket_charged_damage_scale=0.5625,
        player_shield_policy="threshold",
        player_shield_threshold=0.03,
    )
    assert shielded.timeline[0].core.damage[1] == 1
    # Scaled damage2 < .03*100=3, so no shield (unscaled damage would be3).
    assert threshold.shields[0] == 2
    assert threshold.timeline[0].core.damage[1] == 2


def test_timer_both_sides_and_shielded_charge():
    # At equal attack both charges resolve t1, each adds14 -> deadline1468.
    result = run(
        player=mon(5000, charged=(C,), energy=20),
        rocket=mon(5000, charged=(C,), energy=20),
        turns=2000,
    )
    assert result.timeline[0].deadline == 1440 + 2 * 14
    assert result.ended_by == "timeout" and result.turns_elapsed == 1468
    assert result.winner == "player"  # Rocket idle t2..8, player only t2.


def test_timeout_pokemon_count_precedes_hp_fraction():
    # Zero-power F hits for1; player slot1 (1HP) faints on t1. Remaining
    # player has far more raw HP, but only2 survivors versus Rocket3.
    result = simulate_rocket(
        [mon(1), mon(20000), mon(1)],
        [mon(2000)] * 3,
        battle_date=None,
        player_policy=FastOnly(),
    )
    assert result.ended_by == "timeout" and result.turns_elapsed == 1440
    assert result.hp[0] == (0, 18561, 1)
    assert result.winner == "rocket"  # 3 left beats2, despite much less raw HP.
    assert result.hp[1] == (560, 2000, 2000)


def test_timeout_hp_fraction_uses_members_not_raw_hp():
    # 1440 hits for1 on each lead. Both have3 remaining. Player raw HP
    # 560+20000=20560 exceeds Rocket2560+2=2562, but fractions
    # 2+.28=2.28 < 2+.64=2.64, so Rocket wins.
    result = simulate_rocket(
        [mon(2000), mon(10000), mon(10000)],
        [mon(4000), mon(1), mon(1)],
        battle_date=None,
        player_policy=FastOnly(),
    )
    assert result.ended_by == "timeout" and result.turns_elapsed == 1440
    assert result.winner == "rocket"
    assert result.hp == ((560, 10000, 10000), (2560, 1, 1))


def test_timeout_equal_fractions_draw_despite_different_raw_hp():
    # Different absolute bulk: Rocket F does2, player F1. Leads both lose
    # exactly 50% in1440 turns: 1440/2880 == 2880/5760. Teams still tie.
    result = simulate_rocket(
        [mon(5760)] * 3,
        [mon(2880, fast=replace(F, power=2))] * 3,
        battle_date=None,
        player_policy=FastOnly(),
    )
    assert result.ended_by == "timeout" and result.winner is None


def test_sweep_carries_hp_energy_and_reserves():
    # P fast1/gain10: t1 kills R1; replacement pauses t2..8; t2 kills R2;
    # replacement extends pause to t9; t3 kills R3. Only t1 retaliation hits.
    result = simulate_rocket(
        [mon(fast=replace(F, energy_gain=10)), mon(), mon()],
        [mon(1)] * 3,
        battle_date=None,
        player_policy=FastOnly(),
    )
    assert result.winner == "player" and result.ended_by == "knockout"
    assert result.turns_elapsed == 3
    assert [r.active_slots for r in result.timeline] == [(1, 1), (1, 2), (1, 3)]
    assert result.hp == ((99, 100, 100), (0, 0, 0))
    assert result.energy == ((30, 0, 0), (0, 0, 0))


def test_loss_fixed_order_and_player_replacement_no_9db_pause():
    # t1..3 each player1HP faints; each deals1. No Rocket replacement
    # occurs, hence no faint pause; R lead carries97HP and30 energy.
    result = simulate_rocket(
        [mon(1)] * 3,
        [mon(fast=replace(F, energy_gain=10)), mon(), mon()],
        battle_date=None,
        player_policy=FastOnly(),
    )
    assert result.winner == "rocket" and result.ended_by == "knockout"
    assert [r.active_slots for r in result.timeline] == [(1, 1), (2, 1), (3, 1)]
    assert result.hp == ((0, 0, 0), (97, 100, 100))
    assert result.energy[1] == (30, 0, 0)


def test_cwizz1_pauses_after_player_replacement():
    result = simulate_rocket(
        [mon(1), mon()],
        [mon()],
        battle_date=None,
        player_policy=FastOnly(),
        rules=RocketRules(pause_reading="cwizz1"),
        max_turns=10,
    )
    assert starts(result, 1) == [1, 9, 10]


def test_queue_is_cleared_on_replacement():
    # Player's3-turn F is pending when Rocket1-turn F kills player slot1 t1.
    # Outgoing F must never land on behalf of slot2.
    result = simulate_rocket(
        [mon(1, fast=replace(F, turns=3)), mon()],
        [mon()],
        battle_date=None,
        player_policy=FastOnly(),
        max_turns=3,
    )
    assert [r.core.damage[0] for r in result.timeline] == [0, 1, 1]


def test_shields_persist_across_both_teams_replacements():
    # Pauses off. t1 P charge1 KOs R1 (shielded), cancels its fast reply.
    # t2 post-charge. t3 P fast gains20, R fast takes P from2HP to1HP.
    # t4 P's next charge spends shield2, R fast KOs P. Replacement P2
    # retains that side's energy20; t5 post-charge; t6 charge is unshielded.
    result = simulate_rocket(
        [
            mon(2, fast=replace(F, energy_gain=20), charged=(C,), energy=20),
            mon(charged=(replace(C, power=20),), energy=20),
            mon(),
        ],
        [mon(1), mon(), mon()],
        battle_date=None,
        rank="leader",
        max_turns=6,
        rules=RocketRules(pauses=False),
    )
    assert result.timeline[0].replacements == (None, 2)
    assert result.timeline[3].replacements == (2, None)
    assert [result.timeline[t - 1].shields[1] for t in (1, 4, 6)] == [1, 0, 0]
    assert result.timeline[5].core.damage[0] == 19
    assert result.energy[0][:2] == (0, 0)


def test_final_double_knockout_and_observation_limit():
    result = run(player=mon(1), rocket=mon(1))
    assert result.winner is None and result.ended_by == "knockout"
    result = run(turns=1, timer=False)
    assert result.winner is None and result.ended_by == "observation_limit"


@pytest.mark.parametrize("turn_rules", [Rules(), Rules(True, True)])
def test_all_rocket_options_off_matches_core(turn_rules):
    p = mon(60, replace(F, turns=3, energy_gain=20), (replace(C, power=20),))
    r = mon(80, replace(F, turns=2, energy_gain=10))
    rules = RocketRules(
        pauses=False,
        timer=False,
        rocket_charged="never",
        rocket_shields=False,
        player_shield_policy="never",
        turn_rules=turn_rules,
    )
    team = simulate_rocket([p], [r], battle_date=None, rules=rules)
    core = simulate(p, r, player_policy=ChargedWhenReady(), rules=turn_rules)
    assert [asdict(row.core) for row in team.timeline] == [asdict(row) for row in core.timeline]
    assert team.damage == core.damage


def test_next_turn_charge_pause_begins_after_resolution():
    result = run(
        player=mon(charged=(C,), energy=20),
        turns=11,
        turn_rules=Rules(ledger_j_next_turn_charged=True),
    )
    # Queue t1, resolve t2, pause t3..9, resume t10.
    assert result.timeline[0].pause_through == 0
    assert result.timeline[1].pause_through == 9
    assert starts(result, 1) == [1, 2, 10, 11]


def test_metadata_dates_sources_and_stat_adapter():
    result = simulate_rocket([mon()], [mon()], battle_date=date(2026, 11, 14), max_turns=1)
    assert result.label == "estimate"
    assert result.battle_date == "2026-11-14"
    assert set("kmn") <= set(result.ledger_rows)
    assert all(e.grade and e.source and e.option for e in result.evidence)
    data = rule_data()
    assert all(key in data["rows"] and data["rows"][key] for key in data["grades"])
    assert "approximate" in data["boundary_note"]
    for rank in ("grunt", "leader", "giovanni"):
        base = {"atk": 100, "def": 100, "hp": 100}
        stats = rocket_stats(base, 50, rank, "venonic-2023")
        pokemon = rocket_combatant(
            base, ("normal",), F, trainer_level=50, rank=rank, table="venonic-2023"
        )
        assert (pokemon.attack, pokemon.defence, pokemon.hp) == (
            stats.attack,
            stats.defence,
            stats.hp,
        )
        assert not pokemon.shadow  # The core supplies the always-shadow flag.


@pytest.mark.parametrize(
    "options",
    [
        {"pause_reading": "unknown"},
        {"pause_trigger": "unknown"},
        {"rocket_charged": "sometimes"},
        {"rocket_charged_damage_scale": 0.5},
        {"player_shield_policy": "unknown"},
        {"player_shield_threshold": 0},
        {"player_shield_threshold": float("nan")},
        {"timer": 1},
    ],
)
def test_invalid_rules(options):
    with pytest.raises(ValueError):
        RocketRules(**options)


@pytest.mark.parametrize(
    "players,rockets,kwargs",
    [
        ([], [mon()], {}),
        ([mon()] * 4, [mon()], {}),
        ([mon()], [replace(mon(), shadow=True)], {}),
        ([mon()], [mon(charged=(C, C))], {}),
        ([mon()], [mon()], {"rank": "unknown"}),
        ([mon()], [mon()], {"battle_date": "bad"}),
    ],
)
def test_invalid_inputs(players, rockets, kwargs):
    with pytest.raises(ValueError):
        simulate_rocket(players, rockets, **({"battle_date": None} | kwargs))


def test_player_shields_carry_across_player_faint():
    # t1 shield1 reduces19 to1, but that still KOs the1HP player lead.
    # P2 arrives with the side's remaining1 shield. Rocket still has40
    # energy: t3 shield2 takes1HP; t5 third charge takes19HP unshielded.
    result = simulate_rocket(
        [mon(1), mon(), mon()],
        [mon(charged=(replace(C, power=20),), energy=60)] * 3,
        battle_date=None,
        max_turns=5,
        player_policy=FastOnly(),
    )
    assert result.timeline[0].replacements == (2, None)
    assert [result.timeline[t - 1].shields[0] for t in (1, 3, 5)] == [1, 0, 0]
    assert [result.timeline[t - 1].core.damage[1] for t in (1, 3, 5)] == [1, 1, 19]
    assert result.hp[0] == (0, 80, 100)


def test_knockout_on_timeout_turn_is_knockout():
    # Each lead has1440HP and loses1 per turn. The final damage resolves
    # on the deadline; complete knockout takes precedence over the clock.
    result = run(player=mon(1440), rocket=mon(1440), turns=1500)
    assert result.turns_elapsed == 1440
    assert result.ended_by == "knockout" and result.winner is None
