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
from pogo_analyzer.sim.grades import GradeContext, column_grade, grade_row, weakest
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


GATE = run_acceptance(FIXTURES)
COVERAGE = GATE["coverage"]
DATED = {
    "fast": PREDICTOR.move("BULLET_PUNCH", "2022-12-03"),
    "rocket_fast": PREDICTOR.move("BITE", "2022-12-03"),
}


def ctx(
    rank="grunt", table="venonic-2023", level=50, coverage=COVERAGE, moves=DATED, validated=True
):
    row = {"rank": rank, "rcpm_table": table, "trainer_level": level}
    return GradeContext.for_row(row, coverage, moves, validated=validated)


def test_coverage_is_what_the_targets_used():
    # Every target is at TL50 except F2 (TL41, Rocket HP only); only gate tables cover.
    tl50 = [["fugerappi-2023", 50], ["venonic-2023", 50]]
    assert COVERAGE["levels"] == {
        "rocket_hp": [["fugerappi-2023", 41], *tl50[:1], ["venonic-2023", 41], tl50[1]],
        "rocket_attack": tl50,
        "rocket_defence": tl50,
    }
    assert {m["move"] for m in COVERAGE["moves"]} == {
        "BITE",
        "BULLET_PUNCH",
        "CHARGE_BEAM",
        "RAZOR_LEAF",
        "SMACK_DOWN",
        "TACKLE",
    }


@pytest.mark.parametrize(
    "column",
    ["fast_damage", "fast_hits_to_ko", "rocket_fast_damage", "attacker_hp", "ko_on_incoming_hit"],
)
def test_grade_fixture_exact_needs_everything(column):
    # Gate passed, grunt, gate table at a covered level, dated move stats.
    assert column_grade(column, ctx()) == "fixture-exact"


@pytest.mark.parametrize(
    "column", ["fast_damage", "rocket_fast_damage", "rocket_hp", "attacker_hp", "fast_move"]
)
@pytest.mark.parametrize("coverage", [{"levels": [], "moves": []}, None, COVERAGE])
def test_grade_failed_gate_leaves_nothing_fixture_exact(column, coverage):
    # The gate's own result decides; even full coverage cannot override a failure.
    grade = column_grade(column, ctx(coverage=coverage, validated=False))
    assert grade != "fixture-exact"
    # Rocket stats keep their CP backing; damage and player stats fall to PvPoke parity.
    assert grade == ("cp-only" if column == "rocket_hp" else "parity-only")


@pytest.mark.parametrize("table,level", [("fugerappi-2023", 20), ("venonic-2023", 45)])
def test_grade_uncovered_trainer_level_is_cp_only(table, level):
    for column in ("rocket_hp", "rocket_attack", "fast_damage", "rocket_fast_damage"):
        assert column_grade(column, ctx(table=table, level=level)) == "cp-only"
    assert column_grade("attacker_hp", ctx(table=table, level=level)) == "fixture-exact"


def test_grade_tl41_covers_rocket_hp_only():
    # F2 (TL41) measures Rocket HP; no TL41 target checks attack, defence or damage.
    # One floored HP reading bounds the TL41 rCPM only to about 1%, so the shared
    # scaling inputs need every quantity checked: at TL41 they are cp-only too.
    c = ctx(level=41)
    assert column_grade("rocket_hp", c) == "fixture-exact"
    for column in (
        "rocket_attack",
        "rocket_defence",
        "fast_damage",
        "rocket_fast_damage",
        "rocket_cpm",
        "rank",
        "rank_multiplier",
        "trainer_level",
    ):
        assert column_grade(column, c) == "cp-only"
    assert column_grade("rocket_cpm", ctx(level=50)) == "fixture-exact"


@pytest.mark.parametrize(
    "coverage",
    [
        {"levels": {"bogus": [["venonic-2023", 50]]}, "moves": []},
        {"levels": {"rocket_hp": [[]]}, "moves": []},
        {"levels": [["venonic-2023", 50]], "moves": []},
        {"levels": {"rocket_hp": [["venonic-2023", "50"]]}, "moves": [{"move": "BITE"}]},
        "nonsense",
    ],
)
def test_grade_malformed_coverage_fails_closed(coverage):
    # No crash, and no Rocket or damage cell is fixture-exact from a bad shape.
    for validated in (False, True):
        c = ctx(coverage=coverage, validated=validated)
        for column in ("rocket_hp", "rocket_cpm", "fast_damage", "rocket_fast_damage", "fast_move"):
            assert column_grade(column, c) != "fixture-exact"
        if not validated:
            assert column_grade("attacker_hp", c) == "parity-only"


def test_grade_dec_2025_grunt_keeps_player_cells_exact():
    # Design decision: player stats don't depend on the Rocket table, so a dec-2025
    # grunt row keeps them fixture-exact; every Rocket-side cell is cp-only.
    c = ctx(table="dec-2025")
    for column in ("attacker", "level", "ivs", "form", "attacker_hp", "attacker_attack"):
        assert column_grade(column, c) == "fixture-exact"
    for column in ("rocket_hp", "rocket_attack", "rocket_defence", "trainer_level", "rocket_cp"):
        assert column_grade(column, c) == "cp-only"


def test_pin_matches_the_fixtures():
    # Editing a target, or the species and dated moves it uses, needs a new pin
    # (tools/fixtures/acceptance_pin.py) and a fixture review.
    from pogo_analyzer.sim import validation

    targets = validation.acceptance_targets(BATTLES)
    assert validation.pin_errors(BATTLES, SPECIES, MOVES) == []
    assert sorted(r["id"] for r in targets) == validation.PIN["target_ids"]
    assert validation.PIN["discrepancy_ids"] == [
        "F3-metagross-remaining",
        "F4-ducklett-shadow-tyranitar",
    ]
    # The count is a code constant, not read from the pin.
    assert validation.EXPECTED_TARGETS == 44 == len(validation.PIN["target_ids"])


def test_pin_with_another_count_fails_even_if_regenerated():
    from pogo_analyzer.sim import validation

    trimmed = [r for r in BATTLES if r["id"] != "F2-cyndaquil-hp"]
    targets = validation.acceptance_targets(trimmed)
    repinned = {
        "target_ids": sorted(r["id"] for r in targets),
        "discrepancy_ids": validation.PIN["discrepancy_ids"],
        "discrepancy_sha256": validation.PIN["discrepancy_sha256"],
        "sha256": validation.acceptance_digest(targets, SPECIES, MOVES),
    }
    errors = validation.pin_errors(trimmed, SPECIES, MOVES, pin=repinned)
    assert "the pin lists 43 targets, not 44" in errors
    assert any("found 43" in e for e in errors)


def test_digest_ignores_species_move_lists():
    from pogo_analyzer.sim import validation

    targets = validation.acceptance_targets(BATTLES)
    refreshed = {name: dict(entry, fastMoves=["X"]) for name, entry in SPECIES.items()}
    assert validation.acceptance_digest(targets, refreshed, MOVES) == validation.PIN["sha256"]
    moved = [dict(r, source=r["source"] + "x") if r in targets[:1] else r for r in BATTLES]
    assert validation.pin_errors(moved, SPECIES, MOVES)


def test_grade_supplementary_and_current_tables_never_fixture_exact():
    for table in ("flyfunner-old-50-2025", "dec-2025", "flyfunner-lower-2023"):
        assert column_grade("rocket_hp", ctx(table=table)) == "cp-only"
        assert column_grade("fast_damage", ctx(table=table)) == "cp-only"


def test_grade_move_stats_must_equal_a_dated_snapshot():
    today = Move("BULLET_PUNCH", "steel", 7, 2, energy_gain=7)  # Dated: power 6, gain 7.
    c = ctx(moves={"fast": today, "rocket_fast": DATED["rocket_fast"]})
    assert column_grade("fast_move", c) == "parity-only"
    assert column_grade("fast_damage", c) == "parity-only"
    assert column_grade("fast_hits_to_ko", c) == "parity-only"
    assert column_grade("rocket_fast_damage", c) == "fixture-exact"
    assert column_grade("fast_move", ctx()) == "fixture-exact"


@pytest.mark.parametrize("rank", ["leader", "giovanni"])
def test_grade_leader_and_giovanni_never_fixture_exact(rank):
    row = grade_row(matchup(rank=rank), GATE, DATED)
    grades = {key: cell["grade"] for key, cell in row.items()}
    assert "fixture-exact" not in grades.values()
    for column in ("attacker", "attacker_hp", "rocket_hp", "fast_damage", "rocket_fast_damage"):
        assert grades[column] == "cp-only"


def test_grade_charged_is_parity_only():
    for c in (ctx(), ctx(table="dec-2025"), ctx(rank="giovanni")):
        assert column_grade("charged_damage", c) == "parity-only"


@pytest.mark.parametrize(
    "column",
    [
        "fast_turns_to_ko",
        "turns_survived",
        "fast_moves_to_energy",
        "moveset_pool",
        "defender",
        "character",
    ],
)
def test_grade_behaviour_and_lineup_are_model(column):
    assert column_grade(column, ctx()) == "model"
    assert column_grade(column, ctx(rank="giovanni", table="dec-2025")) == "model"


def test_grade_weakest_dependency_and_row():
    assert weakest("fixture-exact", "cp-only", "parity-only", "model") == "model"
    r = grade_row(matchup(), GATE, DATED)
    assert r["row_grade"] == {"value": "model", "grade": "model"}
    assert r["charged"]["value"][0]["damage"]["grade"] == "parity-only"
    assert r["charged"]["value"][0]["fast_moves_to_energy"]["grade"] == "model"
    # A nominal rate also depends on move-duration metadata, without a battle target.
    assert r["fast_damage_per_turn"]["grade"] == "parity-only"
    assert r["rocket_cp"]["grade"] == "cp-only"
    with pytest.raises(ValueError, match="no grade dependency"):
        column_grade("unknown", ctx())


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


def test_label_wording_singular_and_plural():
    from pogo_analyzer.sim.validation import _plural

    assert _plural(1, "target") == "1 target"
    assert _plural(2, "target") == "2 targets"
    assert _plural(1, "open discrepancy", "open discrepancies") == "1 open discrepancy"
    assert _plural(2, "open discrepancy", "open discrepancies") == "2 open discrepancies"


def test_discrepancy_records_are_pinned_by_content():
    from pogo_analyzer.sim import validation

    edited = [
        dict(r, observed=dict(r["observed"], value=2)) if r["id"] == "F3-metagross-remaining" else r
        for r in BATTLES
    ]
    assert validation.pin_errors(edited, SPECIES, MOVES) == [
        "open discrepancy records differ from the reviewed set (SHA-256 mismatch)"
    ]
