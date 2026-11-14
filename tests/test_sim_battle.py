"""Offline hand traces of pinned Battle.js, plus explicitly graded fixture reports."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pogo_analyzer.sim.battle import (
    ChargedWhenReady,
    Combatant,
    FastOnly,
    NeverShield,
    Rules,
    simulate,
)
from pogo_analyzer.sim.calculator import BattlePredictor, Move
from pogo_analyzer.sim.stats import player_stats

FIXTURES = Path(__file__).parent / "fixtures" / "sim"
BATTLES = {r["id"]: r for r in json.loads((FIXTURES / "battles.json").read_text())}
SPECIES = json.loads((FIXTURES / "species_moves.json").read_text())["species"]
PREDICTOR = BattlePredictor(SPECIES, json.loads((FIXTURES / "move_history.json").read_text()))
OLD_TABLES = ("venonic-2023", "fugerappi-2023")


def fighter(*, turns=1, power=0, hp=100, energy=0, attack=100, gain=10):
    # Water combatants / normal moves: no STAB or effectiveness. At 100/100,
    # power 0 -> 1; power 10 -> floor(10*1.2*.5*1.3)+1 = 8 on either side.
    # Outgoing shadow defence uses 1/0.83333331, which also floors to 8.
    return Combatant(
        attack,
        100,
        hp,
        ("water",),
        Move("F", "normal", power, turns, energy_gain=gain),
        (Move("C", "normal", 10, 1, energy=10),),
        energy=energy,
    )


@pytest.mark.parametrize("duration", (1, 2, 3, 4, 5))
def test_duration_registration_and_energy(duration):
    # Battle.js 367,405–409: start at 1, hit at duration; next start duration+1.
    result = simulate(fighter(turns=duration), fighter(turns=duration), max_turns=duration * 2)
    assert [t.number for t in result.timeline if t.damage[0]] == [duration, 2 * duration]
    for t in result.timeline:
        hits = t.number // duration
        assert t.hp == (100 - hits, 100 - hits)
        assert t.energy == (10 * hits, 10 * hits)
    assert result.turns_elapsed == duration * 2
    assert result.label == "estimate" and "j" in result.ledger_rows
    assert result.limit_reached and result.winner is None


def test_fast_retaliation_and_double_ko():
    # 451–460: t1 Bite-like fast hits for 8; t2 slower fast hits for 8 then
    # the fainted fast user's eligible reply hits for 8. Finish the whole turn.
    result = simulate(fighter(turns=2, power=10, hp=16), fighter(power=10, hp=8))
    assert [(t.hp, t.energy, t.damage) for t in result.timeline] == [
        ((8, 8), (0, 10), (0, 8)),
        ((0, 0), (10, 20), (8, 8)),
    ]
    assert result.winner is None and not result.limit_reached
    assert result.damage == (8, 16)


def test_faint_ends_before_a_future_fast_lands():
    # 629: queued three-turn move cannot retaliate after the battle ends on t1.
    result = simulate(fighter(power=10), fighter(turns=3, hp=8))
    assert result.winner == "player" and result.turns_elapsed == 1
    assert result.hp == (100, 0) and result.timeline[0].energy == (10, 0)


@pytest.mark.parametrize(
    ("attacks", "winner", "hp", "energy"),
    [
        ((101, 100), "player", (8, 0), (0, 10)),
        ((100, 101), "rocket", (0, 8), (10, 0)),
        ((100, 100), None, (0, 0), (0, 0)),
    ],
)
def test_cmp_unmodified_attack_and_equal_attack_double_fire(attacks, winner, hp, energy):
    # 262–265, 780–785, 479–481. Each charge does 8. Shadow Rocket's effective
    # attack is 120, but CMP compares the supplied 100/101, before shadow.
    result = simulate(
        fighter(attack=attacks[0], hp=8, energy=10),
        fighter(attack=attacks[1], hp=8, energy=10),
        player_policy=ChargedWhenReady(),
        rocket_policy=ChargedWhenReady(),
    )
    assert (result.winner, result.hp, result.timeline[0].energy) == (winner, hp, energy)
    assert result.turns_elapsed == 1
    assert "l" in result.ledger_rows
    assert ("charged:cancel:C" in result.timeline[0].actions[0]) == (winner == "rocket")
    assert ("charged:cancel:C" in result.timeline[0].actions[1]) == (winner == "player")


def test_charged_ko_cancels_fast_on_same_turn():
    # 434,451–460: charge does 8 first. Opponent submitted a fast move but gets
    # no damage or energy after a charged KO, unlike the fast-KO case above.
    result = simulate(fighter(energy=10), fighter(hp=8), player_policy=ChargedWhenReady())
    assert result.hp == (100, 0) and result.timeline[0].energy == (0, 0)
    assert result.timeline[0].actions == (
        ("charged:start:C", "charged:hit:C"),
        ("fast:start:F", "fast:cancel:F"),
    )


def test_floating_fast_flush_cooldown_reset_and_post_charge_input_block():
    # 405–409,341–343,546–549: t1 fast for 1 gains 10; t2 charge for 8 costs 10.
    # Opponent's four-turn fast is still queued. Both cooldowns reset to 1.
    # t3 accepts no inputs, but flushes that fast early: 1 damage, 10 energy.
    # t4 both can start again. This is not a Rocket pause.
    result = simulate(fighter(), fighter(turns=4), player_policy=ChargedWhenReady(), max_turns=4)
    assert [(t.hp, t.energy, t.damage) for t in result.timeline] == [
        ((100, 99), (10, 0), (1, 0)),
        ((100, 91), (0, 0), (8, 0)),
        ((99, 91), (0, 10), (0, 1)),
        ((99, 90), (10, 10), (1, 0)),
    ]
    assert result.timeline[2].actions == ((), ("fast:hit:F",))
    assert result.timeline[3].actions[1] == ("fast:start:F",)


def test_fast_due_during_charge_still_lands_if_alive():
    # 434,451–460: t2 charge has priority, then surviving two-turn fast lands.
    result = simulate(fighter(), fighter(turns=2), player_policy=ChargedWhenReady(), max_turns=2)
    assert result.timeline[1].hp == (99, 91)
    assert result.timeline[1].damage == (8, 1)
    assert result.timeline[1].energy == (0, 10)


def test_energy_cap_and_cost_only_on_resolution():
    # 1337–1340: 95+10 caps at 100 on t1, no further gain on t2.
    result = simulate(fighter(energy=95), fighter(energy=95), max_turns=2)
    assert [t.energy for t in result.timeline] == [(100, 100), (100, 100)]
    # 1058: charge costs 10; it gains no fast energy. t2 is input-blocked.
    result = simulate(fighter(energy=95), fighter(), player_policy=ChargedWhenReady(), max_turns=2)
    assert [t.energy[0] for t in result.timeline] == [85, 85]


def test_policy_list_order_and_first_affordable():
    p = replace(
        fighter(energy=30),
        charged=(Move("A", "normal", 0, 1, energy=45), Move("B", "normal", 0, 1, energy=30)),
    )
    result = simulate(p, fighter(), player_policy=ChargedWhenReady(), max_turns=1)
    assert result.timeline[0].actions[0] == ("charged:start:B", "charged:hit:B")
    result = simulate(
        replace(p, energy=100), fighter(), player_policy=ChargedWhenReady(), max_turns=1
    )
    assert result.timeline[0].actions[0] == ("charged:start:A", "charged:hit:A")
    assert result.timeline[0].energy[0] == 55
    assert FastOnly().name == "fast_only" and NeverShield().name == "never_shield"


def test_shield_decision_is_injected_without_inventory_rules():
    class Shield:
        def shield(self, own, opponent, move, turn):
            assert (move.id, turn, own.hp, opponent.energy) == ("C", 1, 100, 10)
            return True

    result = simulate(
        fighter(energy=10),
        fighter(),
        player_policy=ChargedWhenReady(),
        rocket_shield_policy=Shield(),
        max_turns=1,
    )
    # Damage calculator's shield override, Battle.js 1194–1200. No inventory rule.
    assert result.timeline[0].damage == (1, 1)
    assert "m" in result.ledger_rows


def test_ledger_j_next_turn_is_an_explicit_option():
    result = simulate(
        fighter(energy=10),
        fighter(),
        player_policy=ChargedWhenReady(),
        rules=Rules(ledger_j_next_turn_charged=True),
        max_turns=2,
    )
    # Alternative: t1 submission leaves energy intact; t2 resolves for 8/cost 10.
    # The already-pending charge prevents an extra player input on t2.
    assert result.timeline[0].actions[0] == ("charged:queue:C",)
    assert result.timeline[0].energy == (10, 10)
    assert result.timeline[1].actions[0] == ("charged:start:C", "charged:hit:C")
    assert result.timeline[1].hp == (98, 92)
    assert result.timeline[1].energy == (0, 20)
    assert result.rules.ledger_j_next_turn_charged


def test_ledger_j_next_turn_opponent_charge_resolves_after():
    # Decisions come before resolution: on t2, while the player's charge from t1
    # resolves, the Rocket (now at 10 energy) submits its own; it resolves on t3,
    # the turn after a charge, which accepts no new inputs; t4 is empty.
    result = simulate(
        fighter(energy=10, hp=1000),
        fighter(energy=10, hp=1000, gain=0),
        player_policy=ChargedWhenReady(),
        rocket_policy=ChargedWhenReady(),
        rules=Rules(ledger_j_next_turn_charged=True),
        max_turns=4,
    )
    actions = [t.actions for t in result.timeline]
    assert actions[0] == (("charged:queue:C",), ("charged:queue:C",))
    assert actions[1] == (
        ("charged:start:C", "charged:hit:C"),
        ("charged:start:C", "charged:hit:C"),
    )
    assert result.rules.ledger_j_next_turn_charged


def test_ledger_j_next_turn_staggered_charges():
    # The documented example: player charges at t1, Rocket reaches energy on t1
    # (its fast hit) and submits at t2; t2 player hits, t3 Rocket hits, t4 empty.
    result = simulate(
        fighter(energy=10, hp=1000),
        fighter(energy=0, hp=1000, gain=10),
        player_policy=ChargedWhenReady(),
        rocket_policy=ChargedWhenReady(),
        rules=Rules(ledger_j_next_turn_charged=True),
        max_turns=4,
    )
    rows = [t.actions for t in result.timeline]
    assert rows[0][0] == ("charged:queue:C",)
    assert "charged:hit:C" in rows[1][0] and "charged:queue:C" in rows[1][1]
    assert "charged:hit:C" in rows[2][1]
    assert rows[3] == ((), ())


def test_rocket_shadow_flag_and_negative_power_are_rejected():
    with pytest.raises(ValueError, match="Rocket side is always shadow"):
        simulate(fighter(), replace(fighter(), shadow=True))
    bad = Move("C", "normal", -1, 1, energy=10)
    with pytest.raises(ValueError, match="power must be finite and nonnegative"):
        replace(fighter(), charged=(bad,))
    with pytest.raises(ValueError, match="power must be finite and nonnegative"):
        replace(fighter(), fast=Move("F", "normal", -1, 1, energy_gain=10))


@pytest.mark.parametrize("next_turn", (False, True))
def test_ledger_j_both_fire_overrides_unequal_attack_cancellation(next_turn):
    result = simulate(
        fighter(attack=101, hp=8, energy=10),
        fighter(hp=8, energy=10),
        player_policy=ChargedWhenReady(),
        rocket_policy=ChargedWhenReady(),
        rules=Rules(ledger_j_both_charged_fire=True, ledger_j_next_turn_charged=next_turn),
    )
    assert result.hp == (0, 0) and result.winner is None
    assert result.turns_elapsed == 1 + next_turn
    assert result.timeline[-1].energy == (0, 0)


def fixture_battle(row, table, rocket_fast=None, max_turns=10000):
    p, r = row["player"], row["rocket"]
    ps = player_stats(SPECIES[p["species"]]["baseStats"], p["ivs"], p["level"], form=p["form"])
    rs = PREDICTOR.rocket(row, table)
    return simulate(
        Combatant(
            ps.attack,
            ps.defence,
            ps.hp,
            tuple(SPECIES[p["species"]]["types"]),
            PREDICTOR.move(p["fast_move"], row["battle_date"]),
            shadow=p["form"] == "shadow",
        ),
        Combatant(
            rs.attack,
            rs.defence,
            rs.hp,
            tuple(SPECIES[r["species"]]["types"]),
            PREDICTOR.move(rocket_fast or r["fast_move"], row["battle_date"]),
        ),
        max_turns=max_turns,
    )


@pytest.mark.parametrize("table", OLD_TABLES)
def test_f3_hand_trace(table):
    # No target fitting: dated BP=6/7 energy/2 turns, Bite=4/2 energy/1 turn.
    # Actual damage is BP=19, Bite=11. HP=166/134. Fifteen Bites leave 1 HP;
    # the sixteenth still fires after the eighth BP KOs Snubbull (451–460).
    result = fixture_battle(BATTLES["F3-metagross-remaining"], table)
    assert result.turns_elapsed == 16 and result.winner is None
    for t in result.timeline:
        assert t.hp == (max(0, 166 - 11 * t.number), max(0, 134 - 19 * (t.number // 2)))
        assert t.energy == (7 * (t.number // 2), 2 * t.number)
        assert t.damage == (19 if t.number % 2 == 0 else 0, 11)


@pytest.mark.parametrize("table", OLD_TABLES)
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="OPEN DISCREPANCY F3: computed 0 HP (turn 16 double KO), recorded 1 HP",
)
def test_f3_recorded_remaining_report(table):
    row = BATTLES["F3-metagross-remaining"]
    result = fixture_battle(row, table)
    assert result.hp[0] == row["observed"]["value"], result


@pytest.mark.parametrize("table", OLD_TABLES)
@pytest.mark.parametrize("rocket_fast", ("TACKLE", "BITE"))
def test_f1_turn_structure(table, rocket_fast):
    # Plain test, so it can fail: seven Bullet Punches land on turns 2, 4, ..., 14,
    # the run stops at the 14-turn observation limit, and 7 x 7 energy = 49.
    row = BATTLES["F1-snubbull-remaining"]
    result = fixture_battle(row, table, rocket_fast, max_turns=14)
    assert result.limit_reached and result.winner is None
    assert [t.number for t in result.timeline if t.damage[0]] == [2, 4, 6, 8, 10, 12, 14]
    assert result.timeline[-1].energy[0] == 49


@pytest.mark.parametrize("table", OLD_TABLES)
@pytest.mark.parametrize("rocket_fast", ("TACKLE", "BITE"))
@pytest.mark.xfail(
    strict=False,
    raises=AssertionError,
    reason="F1 weak calculated record; Rocket fast move unknown; explicit sensitivity",
)
def test_f1_weak_remaining_report(table, rocket_fast):
    # Only the weak record's value is compared here: 134 - 7*19 = 1.
    row = BATTLES["F1-snubbull-remaining"]
    result = fixture_battle(row, table, rocket_fast, max_turns=14)
    assert result.hp[1] == row["observed"]["value"], result


@pytest.mark.parametrize("shadow", (False, True))
def test_explicit_shadow_flags_both_directions(monkeypatch, shadow):
    from pogo_analyzer.sim import battle

    original = battle.calculate_damage
    flags = []

    def record(*args, **kwargs):
        flags.append((kwargs["attacker_shadow"], kwargs["defender_shadow"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(battle, "calculate_damage", record)
    simulate(replace(fighter(), shadow=shadow), fighter(), max_turns=1)
    assert flags == [(shadow, True), (True, shadow)]
