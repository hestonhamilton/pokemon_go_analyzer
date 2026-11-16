"""Hand arithmetic checks of model rules, never Rocket acceptance targets."""

import hashlib
import json
import warnings
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
from pogo_analyzer.sim.winrate import battle_summary

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


def test_default_fixture_output_bytes_unchanged():
    player, rocket = mon(4, charged=(C,), energy=20), mon(11)
    default = simulate_rocket([player], [rocket], battle_date=None)
    explicit = simulate_rocket(
        [player], [rocket], battle_date=None, rules=RocketRules(pause_turns_override=None)
    )
    assert default == explicit
    payload = {
        **battle_summary(default, [player]),
        "timeline": [asdict(t) for t in default.timeline],
    }
    # Captured before adding the override field; covers all summary and timeline bytes.
    assert hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest() == (
        "78b0015220aa008bacb702ad45f299c95059b0a9dce4d3e2ffe1c029d5e70882"
    )


@pytest.mark.parametrize("turns,winner", [(6, "rocket"), (8, "player")])
def test_pause_override_changes_fixture_outcome(turns, winner):
    player, rocket = mon(4, charged=(C,), energy=20), mon(11)
    result = simulate_rocket(
        [player], [rocket], battle_date=None, rules=RocketRules(pause_turns_override=turns)
    )
    assert result.winner == winner
    assert result.pause_lengths == (turns, turns, 9)
    assert result.timeline[0].pause_through == turns + 2
    summary = battle_summary(result, [player])
    assert summary["rules"]["pause_turns_override"] == turns
    assert any(
        e["row"] == "k"
        and e["grade"] == "pause length override (sensitivity run, not a source value)"
        and e["option"] == f"pause_turns_override:{turns}"
        and e["source"] == "docs/simulator-verification.md#ledger"
        for e in summary["evidence"]
    )
    readings = [
        e["option"] for e in summary["evidence"] if e["option"].startswith("pause_reading:")
    ]
    assert readings == ["pause_reading:9db:mar-2026:manual_switch"]


def test_pause_override_adds_no_evidence_when_pauses_disabled():
    result = run(pauses=False, pause_turns_override=6)
    baseline = run(pauses=False)
    assert result.evidence == baseline.evidence
    assert result.timeline == baseline.timeline
    assert not any(e.option.startswith("pause_turns_override:") for e in result.evidence)


@pytest.mark.parametrize("turns", [1, 20])
@pytest.mark.parametrize("stamp,switch", [("2026-01-01", 12), (None, 9)])
def test_pause_override_changes_faint_but_keeps_manual_switch(turns, stamp, switch):
    result = simulate_rocket(
        [mon()],
        [mon(1), mon()],
        battle_date=stamp,
        rules=RocketRules(pause_turns_override=turns),
        max_turns=24,
        player_policy=FastOnly(),
    )
    assert result.pause_lengths == (turns, turns, switch)
    assert starts(result, 1) == [1, *range(turns + 2, 25)]


@pytest.mark.parametrize("value", [0, -1, 21, True, False, 6.0, "6", float("nan")])
def test_invalid_pause_override(value):
    with pytest.raises(ValueError, match="pause_turns_override"):
        RocketRules(pause_turns_override=value)


@pytest.mark.parametrize(
    "stamp,era,charge,faint,switch",
    [
        ("2025-12-09", "before-dec-2025", 5, 7, 7),
        ("2025-12-10", "dec-2025", 8, 12, 12),
        ("2026-03-11", "dec-2025", 8, 12, 12),
        ("2026-03-12", "mar-2026", 7, 7, 9),
        (None, "mar-2026", 7, 7, 9),
    ],
)
def test_era_charge_pause(stamp, era, charge, faint, switch):
    result = simulate_rocket(
        [mon(charged=(C,), energy=20)],
        [mon()],
        battle_date=stamp,
        max_turns=16,
    )
    # t1 charge hits. t2 is PvPoke's post-charge turn; the pause adds to it,
    # blocking t3..t(N+2). First new Rocket input t(N+3).
    assert result.era == era
    assert result.pause_lengths == (charge, faint, switch)
    assert starts(result, 1) == [1, *range(charge + 3, 17)]
    assert result.timeline[0].pause_through == charge + 2
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


def test_trigger_default_and_player_charged_option():
    # t1 Rocket charge=1, default player shields ->1; t2 core suppresses.
    # Default any_charged then blocks t3..9 (mar-2026: 7), so t10 is the
    # first new Rocket input. player_charged ignores the Rocket's own charge.
    rocket = mon(charged=(C,), energy=20)
    default = run(rocket=rocket, turns=12)
    alternative = run(rocket=rocket, turns=12, pause_reading="cwizz1")
    narrower = run(rocket=rocket, turns=12, pause_trigger="player_charged")
    assert starts(default, 1) == list(range(10, 13))
    assert starts(alternative, 1) == list(range(10, 13))
    assert starts(narrower, 1) == list(range(3, 13))
    assert alternative.pause_lengths == (7, 7, 6)
    assert default.pause_trigger == alternative.pause_trigger == "any_charged"
    assert narrower.pause_trigger == "player_charged"
    grades = {e.option: e.grade for e in default.evidence}
    assert grades["pause_trigger:any_charged"] == (
        "owner observation, agrees with cwizz1; not measured"
    )
    assert "pause_trigger:player_charged" in {e.option for e in narrower.evidence}


def test_any_charge_pause_adds_to_post_charge_turn():
    rocket = mon(charged=(C,), energy=20)
    result = run(rocket=rocket, turns=11, pause_trigger="any_charged")
    # Core t2, then seven paused turns t3..9. t10 (not t9) resumes.
    assert starts(result, 1) == [10, 11]
    assert "l" in result.ledger_rows and "unverified" in result.flags
    grades = {e.option: e.grade for e in result.evidence}
    assert grades["pause_composition:sum"] == ("practitioner-reproduced (2 accounts), not measured")


@pytest.mark.parametrize("between,sneaks", [(6, False), (7, True)])
def test_six_fast_turns_safe_seventh_sneaks(between, sneaks):
    # cwizz1: "7 turns means you throw after 6 turns of fast moves"; Jason2890:
    # 6 turns between charges keeps the Rocket from any fast move.
    # Player 1-turn fast +5 energy, charge costs 5*between, thrown t1.
    # Core t2; pause t3..9; Rocket's first input t10.
    # Fast moves t3..t(2+between); second charge t(3+between): t9 or t10.
    # The Rocket's t1 fast slips in on t2 either way (flushed by the charge).
    # Six: t9 charge renews the pause before t10; no later Rocket move starts.
    # Seven: the Rocket's 3-turn fast starts t10 beside the charge, then
    # flushes and lands t11 (slip-in, mar-2026).
    lock_on = Move("LO", "normal", 0, 1, energy_gain=5)
    charge = Move("PC", "normal", 0, 1, energy=5 * between)
    player = mon(999, fast=lock_on, charged=(charge,), energy=5 * between)
    rocket = mon(999, fast=replace(F, turns=3))
    result = run(player=player, rocket=rocket, turns=6 + between)
    assert starts(result, 0, "charged") == [1, 3 + between]
    assert starts(result, 1) == ([1, 10] if sneaks else [1])
    late = [r.core.number for r in result.timeline if r.core.damage[1] and r.core.number > 2]
    assert late == ([11] if sneaks else [])


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
    # F on t3 (post-charge); new Rocket inputs pause t4..10, resume t11.
    # The 9db slip-in row (since Dec 2025) supports the landing.
    assert starts(result, 1) == [1, 11]
    assert result.timeline[2].core.actions[1] == ("fast:hit:F",)
    assert result.timeline[2].core.damage == (0, 1)
    assert result.timeline[2].pause_through == 10


def test_before_dec_2025_in_flight_fast_is_void():
    class AtTwo(FastOnly):
        def choose_charged(self, own, opponent, turn):
            return 0 if turn == 2 else None

    result = simulate_rocket(
        [mon(charged=(C,), energy=20)],
        [mon(fast=replace(F, turns=5))],
        battle_date="2025-11-01",
        player_policy=AtTwo(),
        max_turns=9,
    )
    # Same timeline, old era: no slip-in, so the pending F is void on t2.
    # Pause 5: core t3, blocked t4..8, Rocket resumes t9. No damage dealt.
    assert "fast:cancel:F" in result.timeline[1].core.actions[1]
    assert result.timeline[2].core.actions[1] == ()
    assert result.damage[1] == 0
    assert starts(result, 1) == [1, 9]
    assert result.timeline[1].pause_through == 8


@pytest.mark.parametrize("stamp,both", [("2025-11-01", False), ("2026-10-01", True)])
def test_simultaneous_charges_by_era(stamp, both):
    # Equal attack: the player's t1 charge resolves first. Before Dec 2025
    # only the first fires; the Rocket's is void and keeps its 20 energy.
    result = simulate_rocket(
        [mon(charged=(C,), energy=20)],
        [mon(charged=(C,), energy=20)],
        battle_date=stamp,
        max_turns=1,
    )
    first = result.timeline[0].core
    assert ("charged:hit:C" in first.actions[1]) is both
    assert ("charged:cancel:C" in first.actions[1]) is not both
    assert first.energy[1] == (0 if both else 20)
    assert result.timeline[0].deadline == 1440 + 14 * (2 if both else 1)


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
    assert result.shields[1] == 0  # A side that never shields reports none.
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
    # player_charged keeps the Rocket's own charges from pausing it, so
    # three charges land on t1, t3 and t5.
    result = run(
        rocket=mon(charged=(replace(C, power=20),), energy=60),
        turns=5,
        pause_trigger="player_charged",
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
    # "never" is itself an unverified assumption about a charge-holding Rocket.
    assert "l" in result.ledger_rows and "unverified" in result.flags
    assert any(e.option == "rocket_charged:never" for e in result.evidence)


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
    # Zero-power F hits for1; player slot1 (1HP) faints on t1. Its
    # replacement pauses the Rocket t2..8, so slot2 takes t9..1440 = 1432.
    # Remaining player has far more raw HP, but only2 survivors versus Rocket3.
    result = simulate_rocket(
        [mon(1), mon(20000), mon(1)],
        [mon(2000)] * 3,
        battle_date=None,
        player_policy=FastOnly(),
    )
    assert result.ended_by == "timeout" and result.turns_elapsed == 1440
    assert result.hp[0] == (0, 18568, 1)
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


def test_loss_fixed_order_and_player_replacement_pause():
    # Default: either side's faint pauses. P1 faints t1; P2 hits t2..9 while
    # the Rocket is paused t2..8, then dies t9; P3 hits t10..17, dies t17.
    # Rocket lead takes 17 and hits only t1, t9 and t17 (30 energy).
    rocket_team = [mon(fast=replace(F, energy_gain=10)), mon(), mon()]
    result = simulate_rocket([mon(1)] * 3, rocket_team, battle_date=None, player_policy=FastOnly())
    assert result.winner == "rocket" and result.ended_by == "knockout"
    assert result.turns_elapsed == 17 and result.faint_trigger == "any_replacement"
    assert [result.timeline[t - 1].active_slots[0] for t in (1, 9, 17)] == [1, 2, 3]
    assert result.hp == ((0, 0, 0), (83, 100, 100))
    assert result.energy[1] == (30, 0, 0)
    grades = {e.option: e.grade for e in result.evidence}
    assert grades["faint_trigger:any_replacement"] == "owner reading; not measured"
    # Rocket-faint-only option: t1..3 each player faints; each deals1.
    narrower = simulate_rocket(
        [mon(1)] * 3,
        rocket_team,
        battle_date=None,
        player_policy=FastOnly(),
        rules=RocketRules(faint_trigger="rocket_replacement"),
    )
    assert [r.active_slots for r in narrower.timeline] == [(1, 1), (2, 1), (3, 1)]
    assert narrower.hp == ((0, 0, 0), (97, 100, 100))
    assert narrower.energy[1] == (30, 0, 0)


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


def test_cwizz1_reading_is_dated_to_mar_2026():
    with pytest.raises(ValueError):
        simulate_rocket(
            [mon()], [mon()], battle_date="2025-11-01", rules=RocketRules(pause_reading="cwizz1")
        )


@pytest.mark.parametrize("rank,winner", [("leader", "rocket"), ("grunt", None)])
def test_before_dec_2025_leader_timeout_is_loss(rank, winner):
    # Equal leads lose1 per turn: an even timeout. The old leader rule
    # ("a timeout vs the Rocket Leaders counts as a loss") gives the Rocket it.
    result = simulate_rocket(
        [mon(5000)], [mon(5000)], battle_date="2025-11-01", rank=rank, player_policy=FastOnly()
    )
    assert result.ended_by == "timeout" and result.winner == winner


def test_era_grades_reach_every_result():
    old = simulate_rocket([mon()], [mon()], battle_date="2025-11-01", max_turns=1)
    grades = {e.option: e.grade for e in old.evidence}
    assert grades["pause_reading:9db:before-dec-2025:charged"].startswith("conflicting")
    assert grades["era_turn_rules:before-dec-2025:fast_slip_in:False"] == (
        "single source (9db), method unstated"
    )
    assert grades["pause_trigger:any_charged"].endswith("(applied to before-dec-2025 by extension)")
    assert grades["pause_composition:sum"].endswith("(applied to before-dec-2025 by extension)")
    new = simulate_rocket([mon()], [mon()], battle_date=None, max_turns=1)
    grades = {e.option: e.grade for e in new.evidence}
    assert grades["pause_reading:9db:mar-2026:charged"] == "measured-reproduced"
    assert grades["era_turn_rules:mar-2026:fast_slip_in:True"] == "measured-reproduced (ledger j)"
    assert "extension" not in grades["pause_trigger:any_charged"]


def test_era_turn_rules_override_warns():
    rules = RocketRules(turn_rules=Rules(ledger_j_both_charged_fire=True))
    with pytest.warns(UserWarning, match="era_turn_rules"):
        old = simulate_rocket([mon()], [mon()], battle_date="2025-11-01", rules=rules, max_turns=1)
    assert any("replaced the caller" in s for s in old.interpretations)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        simulate_rocket([mon()], [mon()], battle_date=None, rules=rules, max_turns=1)


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
        era_turn_rules=False,
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
    # Queue t1, resolve t2, core t3, pause t4..10, resume t11.
    assert result.timeline[0].pause_through == 0
    assert result.timeline[1].pause_through == 10
    assert starts(result, 1) == [1, 2, 11]


def test_metadata_dates_sources_and_stat_adapter():
    result = simulate_rocket([mon()], [mon()], battle_date=date(2026, 11, 14), max_turns=1)
    assert result.label == "estimate"
    assert result.battle_date == "2026-11-14"
    assert set("kmn") <= set(result.ledger_rows)
    assert all(e.grade and e.source and e.option for e in result.evidence)
    data = rule_data()
    for era in data["eras"]:
        assert all(key in data["rows"] and data["rows"][key] for key in era["grades"])
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
        {"faint_trigger": "unknown"},
        {"era_turn_rules": 1},
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
    # player_charged keeps the Rocket's own charges from pausing it.
    result = simulate_rocket(
        [mon(1), mon(), mon()],
        [mon(charged=(replace(C, power=20),), energy=60)] * 3,
        battle_date=None,
        # Rocket faint only, too: the player lead's t1 faint must not pause.
        rules=RocketRules(pause_trigger="player_charged", faint_trigger="rocket_replacement"),
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


def test_dates_before_rocket_battles_and_forward_extrapolation():
    # Team GO Rocket grunt battles first appeared on 2019-07-22.
    with pytest.raises(ValueError, match="before Team GO Rocket battles began"):
        simulate_rocket([mon()], [mon()], battle_date="2019-07-21", max_turns=1)
    first = simulate_rocket([mon()], [mon()], battle_date="2019-07-22", max_turns=1)
    assert first.era == "before-dec-2025" and "extrapolated" not in first.flags
    # The newest rules source is dated 2026-09-29; later dates are flagged.
    last = simulate_rocket([mon()], [mon()], battle_date="2026-09-29", max_turns=1)
    later = simulate_rocket([mon()], [mon()], battle_date="2026-09-30", max_turns=1)
    assert "extrapolated" not in last.flags
    assert "extrapolated" in later.flags
    assert any("extrapolated forward" in s for s in later.interpretations)
    static = simulate_rocket([mon()], [mon()], battle_date=None, max_turns=1)
    assert "extrapolated" not in static.flags


@pytest.mark.parametrize(
    "stamp,charge,faint", [("2026-10-01", 7, 7), ("2026-01-01", 8, 12), ("2025-11-01", 5, 7)]
)
def test_switch_in_pause_replaces_charge_pause(stamp, charge, faint):
    # Owner in-game test, 16 Nov 2026 (verbatim): "The post charge move pause does not carry
    # over between Pokemon, but there is the pause on new Pokemon switch in or player Pokemon
    # swap." A charged attack that knocks out slot 1 leaves only the switch-in pause.
    result = simulate_rocket(
        [mon(charged=(C,), energy=20)], [mon(1), mon(100)], battle_date=stamp, max_turns=30
    )
    ko = next(t for t in result.timeline if t.replacements[1] == 2)
    assert any(a.startswith("charged:hit:") for a in ko.core.actions[0])
    assert ko.pause_through == ko.core.number + faint
    # Before the owner test, the charge pause (t + 1 + charge) could outlast the switch-in.
    assert (ko.core.number + 1 + charge > ko.core.number + faint) is (charge >= faint)


def test_stat_stages_carry_for_survivor_and_reset_for_replacement():
    from pogo_analyzer.sim.damage import calculate_damage

    debuff = replace(C, self_stages=(0, -2))
    hit = replace(F, power=20)
    rules = RocketRules(turn_rules=Rules(stat_stages=True), pauses=False)
    player = mon(1000, charged=(debuff,), energy=20)
    result = simulate_rocket(
        [player], [mon(1), mon(1000, fast=hit)], battle_date=None, rules=rules, max_turns=3
    )
    expected = calculate_damage(
        20,
        100,
        100,
        "normal",
        ("normal",),
        ("normal",),
        attacker_shadow=True,
        defender_shadow=False,
        defence_stage=-2,
    )
    assert result.timeline[0].replacements == (None, 2)
    assert result.timeline[2].core.damage[1] == expected.damage

    rocket = mon(1, charged=(debuff,), energy=20, attack=101)
    result = simulate_rocket(
        [mon(1000, fast=hit)],
        [rocket, mon(1000)],
        battle_date=None,
        rules=rules,
        max_turns=3,
        player_policy=FastOnly(),
    )
    expected = calculate_damage(
        20,
        100,
        100,
        "normal",
        ("normal",),
        ("normal",),
        attacker_shadow=False,
        defender_shadow=True,
    )
    assert result.timeline[0].replacements == (None, 2)
    assert result.timeline[2].core.damage[0] == expected.damage


def test_chance_meters_carry_for_survivor_and_reset_on_replacement(monkeypatch):
    from pogo_analyzer.sim import battle

    seen = []
    original = battle.calculate_damage

    def capture(*args, **kwargs):
        seen.append((kwargs["attacker_shadow"], kwargs["charged"], kwargs["attack_stage"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(battle, "calculate_damage", capture)
    chance = replace(C, self_stages=(1, 0), stage_chance=0.5)
    rules = RocketRules(
        turn_rules=Rules(stat_stages=True),
        pauses=False,
        rocket_shields=False,
        player_shield_policy="never",
    )
    player = mon(1000, fast=replace(F, energy_gain=20), charged=(chance,), energy=20)
    result = simulate_rocket(
        [player], [mon(1), mon(1000)], battle_date=None, rules=rules, max_turns=10
    )
    assert result.timeline[0].replacements == (None, 2)
    assert [stage for shadow, charged, stage in seen if not shadow and charged][:3] == [0, 0, 1]

    seen.clear()
    rocket = mon(1, charged=(chance,), energy=20, attack=101)
    result = simulate_rocket(
        [mon(1000)],
        [rocket, replace(rocket, hp=1000)],
        battle_date=None,
        rules=rules,
        max_turns=5,
        player_policy=FastOnly(),
    )
    assert result.timeline[0].replacements == (None, 2)
    assert [stage for shadow, charged, stage in seen if shadow and charged] == [0, 0]
    assert [stage for shadow, charged, stage in seen if shadow and not charged] == [0]
