"""Offline damage acceptance and non-gating cross-checks.

Run directly to print every result, F5 IV sweep, and knife-edge diagnostic.
Review marks are fixed by ID/table, never derived from current predictions.
"""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from pogo_analyzer.sim.damage import (
    BONUS,
    DOUBLE_RESISTED,
    MEGA_BONUS,
    RESISTED,
    STAB,
    SUPER_EFFECTIVE,
    calculate_damage,
    effectiveness,
    hits_to_ko,
    stage_multiplier,
)
from pogo_analyzer.sim.stats import player_cpm, player_stats, rcpm, rocket_stats

FIXTURES = Path(__file__).parent / "fixtures" / "sim"


def read_fixture(name):
    return json.loads((FIXTURES / name).read_text())


BATTLES = read_fixture("battles.json")
SPECIES = read_fixture("species_moves.json")["species"]
MOVES = read_fixture("move_history.json")
OLD_TABLES = ("venonic-2023", "fugerappi-2023", "flyfunner-old-50-2025")
# Initial review found no acceptance mismatches. Keep any future reviewed
# mismatch IDs explicit; never derive xfail marks from current output.
UNEXPLAINED: set[tuple[str, str]] = set()


def dated_move(move_id, date):
    """Sparse snapshots require an exact date. Never carry forward or use today."""
    matches = [m for m in MOVES[move_id] if m["as_of"] == date]
    if len(matches) != 1:
        raise ValueError(f"no unique exact-date move snapshot: {move_id} on {date}")
    return matches[0]


def rocket(row, table, trainer_level=None):
    r = row["rocket"]
    return rocket_stats(
        SPECIES[r["species"]]["baseStats"],
        row["trainer_level"] if trainer_level is None else trainer_level,
        r["rank"],
        table,
    )


def dealt(row, table, *, attack_iv=None, trainer_level=None, level=None, mega_rule=False):
    p, r = row["player"], row["rocket"]
    move_id = row["observed"].get("move", p["fast_move"])
    move = dated_move(move_id, row["battle_date"])
    iv = p["ivs"]["atk"] if attack_iv is None else attack_iv
    if iv is None:
        raise ValueError("attack IV missing: sweep explicitly")
    # Only the attack total is needed. Null defence/HP IVs remain unknown.
    attack = (SPECIES[p["species"]]["baseStats"]["atk"] + iv) * player_cpm(
        p["level"] if level is None else level
    )
    return calculate_damage(
        move["power"],
        attack,
        rocket(row, table, trainer_level).defence,
        move["type"],
        SPECIES[p["species"]]["types"],
        SPECIES[r["species"]]["types"],
        attacker_shadow=p["form"] == "shadow",
        defender_shadow=True,  # Ledger g: Rocket Pokemon are shadow since late 2022.
        attack_stage=p["stat_stage"]["atk"],
        charged=move["energy"] > 0,
        shielded=row["observed"].get("shielded", False),
        attacker_mega=p["form"] == "mega" and mega_rule,
        # Pinned gamemaster.json 47141–47152: Confusion has no isMegaMove.
        # None of the fixture moves have this metadata. Do not invent it.
        is_mega_move=False,
        mega_level=p.get("mega_level", 3),
    )


def iv_counts(row, table, trainer_level=None):
    hp = rocket(row, table, trainer_level).hp
    return {
        iv: hits_to_ko(dealt(row, table, attack_iv=iv, trainer_level=trainer_level).damage, hp)
        for iv in range(16)
    }


def predict(row, table):
    obs, p, r = row["observed"], row["player"], row["rocket"]
    kind = obs["kind"]
    rs = rocket(row, table)
    if kind == "rocket_hp":
        return rs.hp
    if kind == "player_hp":
        return player_stats(SPECIES[p["species"]]["baseStats"], p["ivs"], p["level"]).hp
    if kind == "damage_per_hit_taken":
        move = dated_move(obs["move"], row["battle_date"])
        defence = (SPECIES[p["species"]]["baseStats"]["def"] + p["ivs"]["def"]) * player_cpm(
            p["level"]
        )
        return calculate_damage(
            move["power"],
            rs.attack,
            defence,
            move["type"],
            SPECIES[r["species"]]["types"],
            SPECIES[p["species"]]["types"],
            attacker_shadow=True,
            defender_shadow=p["form"] == "shadow",
            defence_stage=p["stat_stage"]["def"],
        ).damage
    if row["fixture"] == "F5":
        return iv_counts(row, table)
    damage = dealt(row, table).damage
    if kind == "damage_per_hit_dealt":
        return damage
    if kind == "hits_to_ko":
        return hits_to_ko(damage, rs.hp)
    if kind == "survives_hits":
        return damage * obs["value"] < rs.hp
    if kind == "remaining_hp_after" and obs["subject"] == "rocket":
        return rs.hp - damage * obs["hits"]
    raise ValueError(f"requires the turn loop: {row['id']}")


def matches(row, prediction):
    if row["fixture"] == "F5":
        return all(prediction[iv] == row["observed"]["value"] for iv in (13, 14, 15))
    if row["observed"]["kind"] == "survives_hits":
        return prediction is True
    return prediction == row["observed"]["value"]


def battle_params():
    for row in BATTLES:
        # F9's unknown inputs are swept in a separate non-gating report test.
        if row["fixture"] == "F9":
            continue
        tables = OLD_TABLES if row["regime"] == "rcpm-old" else ("dec-2025",)
        for table in tables:
            marks = []
            if row["id"] == "F3-metagross-remaining":
                marks.append(
                    pytest.mark.skip(
                        reason=f"OPEN DISCREPANCY (remaining HP needs a turn loop): "
                        f"{row['status_reason']}"
                    )
                )
            elif row["status"] == "weak":
                marks.append(pytest.mark.xfail(strict=False, reason=row["status_reason"]))
            elif row["status"] == "open_discrepancy":
                # A recorded value our model misses. Strict, so a model change that
                # reproduces it surfaces as XPASS and the status must be revisited.
                marks.append(
                    pytest.mark.xfail(
                        strict=True,
                        reason=f"OPEN DISCREPANCY: {row['status_reason']}",
                        raises=AssertionError,
                    )
                )
            elif (row["id"], table) in UNEXPLAINED:
                marks.append(
                    pytest.mark.xfail(
                        strict=True, reason="UNEXPLAINED – needs review", raises=AssertionError
                    )
                )
            yield pytest.param(row, table, marks=marks, id=f"{row['id']}-{table}")


@pytest.mark.parametrize("row,table", list(battle_params()))
def test_battle(row, table):
    if row["id"] == "F2-cyndaquil-hp" and table == "flyfunner-old-50-2025":
        with pytest.raises(ValueError, match="no trainer level 41"):
            rocket(row, table)
        pytest.skip("the retrospective table supplies TL50 only; F2 requires TL41")
    result = predict(row, table)
    assert matches(row, result), (row["id"], table, result, row["observed"])


@pytest.mark.parametrize(
    "stage,expected", list(enumerate([0.5, 4 / 7, 2 / 3, 0.8, 1, 1.25, 1.5, 1.75, 2], start=-4))
)
def test_stages(stage, expected):
    # +n = (4+n)/4; -n = 4/(4+n), without rounded decimal thirds/sevenths.
    assert stage_multiplier(stage) == expected


def test_hand_arithmetic():
    # Neutral: floor(10 * 1 * (100/100) * 1 * 1 * 1 * .5 * BONUS)+1 = 7.
    args = (10, 100, 100, "water", ("normal",), ("normal",))
    assert calculate_damage(*args).damage == 7
    # STAB gives raw ~7.8 -> 8; super-effective alone raw ~10.4 -> 11.
    assert calculate_damage(10, 100, 100, "water", ("water",), ("normal",)).damage == 8
    assert calculate_damage(10, 100, 100, "water", ("normal",), ("fire",)).damage == 11
    # Both shadow: raw ~6.5 * (1.2/.83333331) = 9.360000..., -> 10.
    assert calculate_damage(*args, attacker_shadow=True, defender_shadow=True).damage == 10
    # +4 attack and -4 defence: raw ~6.5 * (2/.5) = 25.999999... -> 26.
    assert calculate_damage(*args, attack_stage=4, defence_stage=-4).damage == 26
    # Full charge has the same formula. A shield then overrides it to 1.
    assert calculate_damage(*args, charged=True).damage == 7
    shielded = calculate_damage(*args, charged=True, shielded=True)
    assert shielded.damage == 1 and shielded.raw == calculate_damage(*args).raw
    # Power zero (e.g. Yawn) still does floor(0)+1.
    assert calculate_damage(0, *args[1:]).damage == 1


def test_float_literal_floor_boundary():
    # Human-friendly 20*.5*1.3 = 13 -> 14 damage. Pinned BONUS makes raw
    # 12.999999523162842 -> 13 damage. No fitted stats or float32 intermediates.
    result = calculate_damage(20, 100, 100, "water", ("normal",), ("normal",))
    assert result.raw == 12.999999523162842
    assert result.damage == 13
    assert math.floor(20 * 0.5 * 1.3) + 1 == 14


def test_type_chart():
    assert effectiveness("water", ("fire", "rock")) == SUPER_EFFECTIVE * SUPER_EFFECTIVE
    assert effectiveness("ghost", ("normal", "none")) == DOUBLE_RESISTED
    assert effectiveness("normal", ("ghost", "steel")) == DOUBLE_RESISTED * RESISTED
    assert effectiveness("ELECTRIC", ("water", "flying")) == SUPER_EFFECTIVE**2
    # Immunity and weakness multiply, using the literal SE constant, not 1/1.6.
    assert effectiveness("ground", ("flying", "fire")) == DOUBLE_RESISTED * SUPER_EFFECTIVE
    assert effectiveness("water", ("none",)) == 1


@pytest.mark.parametrize("level", range(1, 5))
def test_mega_metadata_gate(level):
    args = (20, 100, 100, "water", ("water",), ("fire",))
    normal = calculate_damage(*args)
    assert calculate_damage(*args, attacker_mega=True, mega_level=level) == normal
    assert calculate_damage(*args, is_mega_move=True, mega_level=level) == normal
    result = calculate_damage(*args, attacker_mega=True, is_mega_move=True, mega_level=level)
    # Preserve where megaMultiplier sits in damage(), including level 1 = 1.
    expected = 20 * STAB * (100 / 100) * SUPER_EFFECTIVE * 1 * MEGA_BONUS[level - 1] * 0.5 * BONUS
    assert result.raw == expected


@pytest.mark.parametrize(
    "damage,hp,expected", [(19, 134, 8), (18, 102, 6), (1, 285, 285), (10, 20, 2), (10, 21, 3)]
)
def test_hit_counts(damage, hp, expected):
    assert hits_to_ko(damage, hp) == expected


@pytest.mark.parametrize("stage", [-5, 5, 0.5, True])
def test_invalid_stage(stage):
    with pytest.raises(ValueError):
        stage_multiplier(stage)


def test_invalid_inputs():
    for damage, hp in [(0, 10), (1, 0), (-1, 10), (1.5, 10), (True, 10)]:
        with pytest.raises(ValueError):
            hits_to_ko(damage, hp)
    args = (10, 100, 100, "water", ("normal",), ("normal",))
    for options in ({"shielded": True}, {"mega_level": 5}, {"mega_level": True}):
        with pytest.raises(ValueError):
            calculate_damage(*args, **options)
    for power, atk, defence in [
        (-1, 100, 100),
        (1, 0, 100),
        (1, 100, 0),
        (math.nan, 100, 100),
        (1, math.inf, 100),
    ]:
        with pytest.raises(ValueError):
            calculate_damage(power, atk, defence, *args[3:])
    with pytest.raises(ValueError, match="unknown type"):
        effectiveness("typo", ("water",))
    with pytest.raises(ValueError, match="exact-date"):
        dated_move("SMACK_DOWN", "2023-01-22")


def f9_sweep():
    row = next(r for r in BATTLES if r["fixture"] == "F9")
    # Every published dec-2025 level, every attack IV. No chosen trainer level.
    return {tl: iv_counts(row, "dec-2025", tl) for tl in range(8, 81)}


def test_f9_report_only(record_property):
    row = next(r for r in BATTLES if r["fixture"] == "F9")
    sweep = f9_sweep()
    record_property("status_reason", row["status_reason"])
    record_property(
        "matching_iv_counts_by_trainer_level",
        {
            tl: sum(count == row["observed"]["value"] for count in counts.values())
            for tl, counts in sweep.items()
        },
    )
    # No comparison asserts an inferred outcome with unstated inputs.


@pytest.mark.parametrize("row", [r for r in BATTLES if r["fixture"] == "F7"], ids=lambda r: r["id"])
@pytest.mark.parametrize("mega_rule", [False, True])
@pytest.mark.parametrize("effective_level", [False, True])
@pytest.mark.xfail(
    strict=False, reason="F7 weak; ledger q unresolved; report both Mega flags/levels"
)
def test_f7_alternatives(row, mega_rule, effective_level):
    p = row["player"]
    level = p.get("effective_level", p["level"]) if effective_level else p["level"]
    damage = dealt(row, "dec-2025", level=level, mega_rule=mega_rule).damage
    assert hits_to_ko(damage, rocket(row, "dec-2025").hp) == row["observed"]["value"]


def print_report():
    totals = defaultdict(Counter)
    for row in BATTLES:
        if row["fixture"] == "F9" or row["id"] == "F3-metagross-remaining":
            continue
        tables = OLD_TABLES if row["regime"] == "rcpm-old" else ("dec-2025",)
        for table in tables:
            try:
                prediction = predict(row, table)
            except ValueError as exc:
                print(row["id"], table, "UNAVAILABLE", exc)
                continue
            ok = matches(row, prediction)
            category = "acceptance" if row["status"] == "expected_pass" else row["status"]
            totals[table][f"{category}-{'pass' if ok else 'fail'}"] += 1
            print(
                row["id"],
                table,
                "PASS" if ok else "FAIL",
                prediction,
                "target",
                row["observed"]["value"],
            )
            if row["fixture"] == "F5":
                print(
                    "  consistent IVs:",
                    [iv for iv, count in prediction.items() if count == row["observed"]["value"]],
                )
            if row["id"] == "F4-ducklett-shadow-tyranitar":
                for iv in (14, 15):
                    result = dealt(row, table, attack_iv=iv)
                    print(
                        "  knife edge IV",
                        iv,
                        result,
                        "raw minus 33",
                        result.raw - 33,
                        "HP",
                        rocket(row, table).hp,
                    )
    print("TOTALS", dict(totals))
    for row in BATTLES:
        if row["fixture"] != "F7":
            continue
        for level in sorted({row["player"]["level"], row["player"].get("effective_level", 50)}):
            for flag in (False, True):
                result = dealt(row, "dec-2025", level=level, mega_rule=flag)
                print(
                    "F7",
                    row["id"],
                    "level",
                    level,
                    "mega flag",
                    flag,
                    result,
                    "HP",
                    rocket(row, "dec-2025").hp,
                    "hits",
                    hits_to_ko(result.damage, rocket(row, "dec-2025").hp),
                )
    for tl, counts in f9_sweep().items():
        print(
            "F9 trainer level",
            tl,
            "rCPM",
            rcpm(tl, "dec-2025"),
            "IVs matching 3",
            [iv for iv, count in counts.items() if count == 3],
            "counts",
            sorted(set(counts.values())),
        )


if __name__ == "__main__":
    print_report()
