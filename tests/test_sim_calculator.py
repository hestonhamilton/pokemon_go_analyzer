"""Offline arithmetic, dependency grades, and recorded battle reconstruction."""

import json
from pathlib import Path

import pytest

from pogo_analyzer.sim.calculator import (
    BattlePredictor,
    Move,
    calculate_matchup,
    energy_hits,
    fast_metrics,
    matches,
    move_damage,
)
from pogo_analyzer.sim.grades import column_grade, grade_row, weakest
from pogo_analyzer.sim.stats import player_cpm, rocket_stats
from pogo_analyzer.sim.validation import OLD_TABLES, run_acceptance

FIXTURES = Path(__file__).parent / "fixtures" / "sim"
BATTLES = json.loads((FIXTURES / "battles.json").read_text())
SPECIES = json.loads((FIXTURES / "species_moves.json").read_text())["species"]
MOVES = json.loads((FIXTURES / "move_history.json").read_text())
PREDICTOR = BattlePredictor(SPECIES, MOVES)


def test_hand_checked_fast_and_energy():
    move = Move("TEST", "water", 10, 2, energy_gain=7)
    # Neutral: floor(10 * 100/100 * .5 * 1.2999999523162842) + 1 = 7.
    result = move_damage(
        move, 100, 100, ["normal"], ["normal"], attacker_shadow=False, defender_shadow=False
    )
    assert result.damage == 7
    # ceil(22/7) = 4 hits; 4*2 = 8 turns; 7/2 = 3.5 nominal DPT.
    assert fast_metrics(result.damage, 22, 2) == {
        "damage": 7,
        "damage_per_turn": 3.5,
        "hits": 4,
        "turns": 8,
    }
    # ceil(50/7)=8, from zero. Zero gain can never reach a charged cost.
    assert energy_hits(50, 7) == 8
    assert energy_hits(50, 0) is None
    with pytest.raises(ValueError):
        fast_metrics(7, 22, 0)
    with pytest.raises(ValueError):
        energy_hits(0, 7)


def test_move_turns_use_cooldown():
    assert (
        Move.from_pvpoke(
            {
                "moveId": "X",
                "type": "water",
                "power": 10,
                "energy": 0,
                "energyGain": 7,
                "cooldown": 1500,
                "turns": 99,
            }
        ).turns
        == 3
    )


def matchup(form="shadow", table="venonic-2023", rank="grunt"):
    attacker = dict(
        SPECIES["metagross"],
        speciesId="metagross",
        level=43.5,
        ivs={"atk": 15, "def": 9, "hp": 12},
        form=form,
    )
    defender = dict(SPECIES["snubbull"], speciesId="snubbull")
    return calculate_matchup(
        attacker,
        defender,
        PREDICTOR.move("BULLET_PUNCH", "2022-12-03"),
        [Move("TEST_CHARGED", "steel", 100, 1, energy=50)],
        PREDICTOR.move("BITE", "2022-12-03"),
        [Move("TEST_INCOMING", "dark", 80, 1, energy=50)],
        trainer_level=50,
        rank=rank,
        table=table,
    )


def test_f1_complete_matchup():
    r = matchup()
    # F1: 134 HP, 19 per Bullet Punch -> ceil(134/19)=8; 8*2=16 turns.
    # Player 163 HP, Bite 11 -> ceil(163/11)=15 (KO on hit 15); 15*1=15 turns.
    assert (r["rocket_hp"], r["fast_damage"], r["fast_hits_to_ko"], r["fast_turns_to_ko"]) == (
        134,
        19,
        8,
        16,
    )
    assert (
        r["attacker_hp"],
        r["rocket_fast_damage"],
        r["ko_on_incoming_hit"],
        r["turns_survived"],
    ) == (163, 11, 15, 15)
    assert r["charged"][0]["fast_moves_to_energy"] == 8
    assert r["rocket_charged"][0]["damage"] > 0
    assert r["rank_multiplier"] == 1


def test_purified_is_plain_and_shadow_only_applied_in_damage():
    plain, purified, shadow = matchup("normal"), matchup("purified"), matchup()
    for key in (
        "attacker_attack",
        "attacker_defence",
        "attacker_hp",
        "rocket_attack",
        "rocket_defence",
        "rocket_cp",
    ):
        assert plain[key] == purified[key] == shadow[key]
    for key in ("fast_damage", "rocket_fast_damage", "charged", "rocket_charged"):
        assert plain[key] == purified[key]
    assert shadow["fast_damage"] > plain["fast_damage"]
    assert shadow["rocket_fast_damage"] > plain["rocket_fast_damage"]


@pytest.mark.parametrize(
    "column",
    ["fast_damage", "fast_hits_to_ko", "rocket_fast_damage", "attacker_hp", "ko_on_incoming_hit"],
)
def test_grade_fixture_exact_old_grunt(column):
    assert column_grade(column, "grunt", "venonic-2023") == "fixture-exact"


@pytest.mark.parametrize(
    "column",
    [
        "fast_damage",
        "fast_hits_to_ko",
        "rocket_fast_damage",
        "rocket_attack",
        "rocket_defence",
        "rocket_hp",
    ],
)
def test_grade_current_rocket_path_cp_only(column):
    assert column_grade(column, "grunt", "dec-2025") == "cp-only"
    assert column_grade("attacker_hp", "grunt", "dec-2025") == "fixture-exact"


@pytest.mark.parametrize("rank", ["leader", "giovanni"])
@pytest.mark.parametrize("table", OLD_TABLES + ("dec-2025",))
def test_grade_rank_has_cp_only_targets(rank, table):
    assert column_grade("fast_damage", rank, table) == "cp-only"
    assert column_grade("rocket_hp", rank, table) == "cp-only"


def test_grade_fixture_tables_match_the_gate():
    from pogo_analyzer.sim.grades import FIXTURE_TABLES

    assert FIXTURE_TABLES == set(OLD_TABLES)
    # A table the gate never checks cannot earn fixture-exact.
    assert column_grade("fast_damage", "grunt", "flyfunner-lower-2023") == "cp-only"


def test_grade_charged_is_parity_only():
    for table in OLD_TABLES + ("dec-2025",):
        for rank in ("grunt", "leader", "giovanni"):
            assert column_grade("charged_damage", rank, table) == "parity-only"


@pytest.mark.parametrize(
    "column", ["fast_turns_to_ko", "turns_survived", "fast_moves_to_energy", "moveset_pool"]
)
def test_grade_behaviour_is_model(column):
    assert column_grade(column, "grunt", "venonic-2023") == "model"
    assert column_grade(column, "giovanni", "dec-2025") == "model"


def test_grade_weakest_dependency_and_row():
    assert weakest("fixture-exact", "cp-only", "parity-only", "model") == "model"
    r = grade_row(matchup())
    assert r["row_grade"] == {"value": "model", "grade": "model"}
    assert r["charged"]["value"][0]["damage"]["grade"] == "parity-only"
    assert r["charged"]["value"][0]["fast_moves_to_energy"]["grade"] == "model"
    # A nominal rate also depends on move-duration metadata, without a battle target.
    assert r["fast_damage_per_turn"]["grade"] == "parity-only"
    assert r["rocket_cp"]["grade"] == "cp-only"
    with pytest.raises(ValueError, match="no grade dependency"):
        column_grade("unknown", "grunt", "dec-2025")


def reconstruction_cases():
    for row in BATTLES:
        if row["fixture"] not in ("F1", "F4", "F5"):
            continue
        if row["status"] == "weak":
            continue
        for table in OLD_TABLES:
            marks = []
            if row["status"] == "open_discrepancy":
                marks = [
                    pytest.mark.xfail(
                        strict=True,
                        raises=AssertionError,
                        reason=f"OPEN DISCREPANCY: {row['status_reason']}",
                    )
                ]
            yield pytest.param(row, table, marks=marks, id=f"{row['id']}-{table}")


@pytest.mark.parametrize("row,table", list(reconstruction_cases()))
def test_recorded_targets_rebuilt_as_calculator_inputs(row, table):
    # No test helpers. Rebuild the attacking arithmetic using only the stated IVs;
    # F4/F5 have no defence/HP IVs, so those quantities are never invented.
    if row["fixture"] in ("F4", "F5"):
        p, r = row["player"], row["rocket"]
        rs = rocket_stats(
            SPECIES[r["species"]]["baseStats"], row["trainer_level"], r["rank"], table
        )
        ivs = (13, 14, 15) if row["fixture"] == "F5" else (p["ivs"]["atk"],)
        move = PREDICTOR.move(p["fast_move"], row["battle_date"])
        for iv in ivs:
            attack = (SPECIES[p["species"]]["baseStats"]["atk"] + iv) * player_cpm(p["level"])
            damage = move_damage(
                move,
                attack,
                rs.defence,
                SPECIES[p["species"]]["types"],
                SPECIES[r["species"]]["types"],
                attacker_shadow=p["form"] == "shadow",
                defender_shadow=True,
            ).damage
            assert fast_metrics(damage, rs.hp, move.turns)["hits"] == row["observed"]["value"]
    else:
        assert matches(row, PREDICTOR.predict(row, table))


def test_acceptance_totals_and_discrepancies():
    r = run_acceptance(FIXTURES)
    assert r["target_count"] == 44
    assert not r["failed"] and not r["errors"]
    assert [sum(p["table"] == t for p in r["passed"]) for t in OLD_TABLES] == [44, 44, 43]
    assert len(r["unavailable"]) == 1
    assert r["unavailable"][0]["id"] == "F2-cyndaquil-hp"
    # F2's TL41 is missing from the TL50-only supplementary table: reported as a
    # gap, never a pass, and not blocking because both gate tables cover it.
    assert r["unavailable"][0]["table"] == "flyfunner-old-50-2025"
    assert r["validated"]
    assert r["label"].startswith(
        "Validated against 44 pre-Oct-2025 battle targets under venonic-2023 and "
        "fugerappi-2023 (flyfunner-old-50-2025: 43 covered, all pass; not covered: "
        "F2-cyndaquil-hp); 2 open discrepancies:"
    )
    assert {d["id"] for d in r["open_discrepancies"]} == {
        "F3-metagross-remaining",
        "F4-ducklett-shadow-tyranitar",
    }
    assert all(d["status_reason"] for d in r["open_discrepancies"])


F1_TARGETS = {
    row["id"]: row for row in BATTLES if row["fixture"] == "F1" and row["status"] == "expected_pass"
}


@pytest.mark.parametrize("table", OLD_TABLES)
def test_f1_targets_through_calculate_matchup(table):
    # F1 states every attacker input (shadow Metagross L43.5, 15/9/12, trainer
    # level 50, 3 Dec 2022), so the CLI's own entry point can be checked end to
    # end: shadow flags in both directions, attacker HP, damage taken and hits.
    assert set(F1_TARGETS) == {
        "F1-metagross-hp",
        "F1-tackle-taken",
        "F1-bite-taken",
        "F1-charge-beam-taken",
        "F1-snubbull-survives-7",
        "F1-kirlia-hits",
    }
    p = F1_TARGETS["F1-metagross-hp"]["player"]
    date = F1_TARGETS["F1-metagross-hp"]["battle_date"]
    attacker = dict(SPECIES[p["species"]], speciesId=p["species"], **p)
    bullet_punch = PREDICTOR.move("BULLET_PUNCH", date)

    def run(defender, rocket_fast):
        return calculate_matchup(
            attacker,
            dict(SPECIES[defender], speciesId=defender),
            bullet_punch,
            [],
            PREDICTOR.move(rocket_fast, date),
            [],
            trainer_level=50,
            rank="grunt",
            table=table,
        )

    tackle = run("snubbull", "TACKLE")
    assert tackle["attacker_hp"] == F1_TARGETS["F1-metagross-hp"]["observed"]["value"]
    assert tackle["rocket_fast_damage"] == F1_TARGETS["F1-tackle-taken"]["observed"]["value"]
    assert (
        run("snubbull", "BITE")["rocket_fast_damage"]
        == F1_TARGETS["F1-bite-taken"]["observed"]["value"]
    )
    kirlia = run("kirlia", "CHARGE_BEAM")
    assert kirlia["rocket_fast_damage"] == F1_TARGETS["F1-charge-beam-taken"]["observed"]["value"]
    assert kirlia["fast_hits_to_ko"] == F1_TARGETS["F1-kirlia-hits"]["observed"]["value"]
    survived = F1_TARGETS["F1-snubbull-survives-7"]["observed"]["value"]
    assert tackle["fast_damage"] * survived < tackle["rocket_hp"]


def test_shedinja_attacker_gets_ten_hp():
    # PvPoke Pokemon.js L384-388: dex 292 has 10 HP whatever its level and IVs.
    # Without the rule, (1 + 15) * CPM(50) = 13.44 -> 13.
    shedinja = {
        "speciesId": "shedinja",
        "dex": 292,
        "baseStats": {"atk": 153, "def": 73, "hp": 1},
        "types": ["bug", "ghost"],
        "level": 50,
        "ivs": {"atk": 15, "def": 15, "hp": 15},
    }
    move = Move("SHADOW_CLAW", "ghost", 6, 2, energy_gain=8)
    snubbull = dict(SPECIES["snubbull"], speciesId="snubbull")
    row = calculate_matchup(
        shedinja, snubbull, move, [], move, [], trainer_level=50, rank="grunt", table="venonic-2023"
    )
    assert row["attacker_hp"] == 10
    without_dex = {k: v for k, v in shedinja.items() if k != "dex"}
    row = calculate_matchup(
        without_dex,
        snubbull,
        move,
        [],
        move,
        [],
        trainer_level=50,
        rank="grunt",
        table="venonic-2023",
    )
    assert row["attacker_hp"] == 13
