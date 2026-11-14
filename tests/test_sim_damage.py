"""Offline damage acceptance and non-gating cross-checks.

Run directly to print every result, F5 IV sweep, and knife-edge diagnostic.
Review marks are fixed by ID/table, never derived from current predictions.
"""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from pogo_analyzer.sim.calculator import BattlePredictor, matches
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
from pogo_analyzer.sim.stats import rcpm

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


_predictor = BattlePredictor(SPECIES, MOVES)
dated_move = _predictor.dated_move
rocket = _predictor.rocket
dealt = _predictor.dealt
iv_counts = _predictor.iv_counts
predict = _predictor.predict


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


# Shadow flags are required keywords; these hand cases are both non-shadow.
PLAIN = {"attacker_shadow": False, "defender_shadow": False}


def test_hand_arithmetic():
    # Neutral: floor(10 * 1 * (100/100) * 1 * 1 * 1 * .5 * BONUS)+1 = 7.
    args = (10, 100, 100, "water", ("normal",), ("normal",))
    assert calculate_damage(*args, **PLAIN).damage == 7
    # STAB gives raw ~7.8 -> 8; super-effective alone raw ~10.4 -> 11.
    assert calculate_damage(10, 100, 100, "water", ("water",), ("normal",), **PLAIN).damage == 8
    assert calculate_damage(10, 100, 100, "water", ("normal",), ("fire",), **PLAIN).damage == 11
    # Both shadow: raw ~6.5 * (1.2/.83333331) = 9.360000..., -> 10.
    assert calculate_damage(*args, attacker_shadow=True, defender_shadow=True).damage == 10
    # +4 attack and -4 defence: raw ~6.5 * (2/.5) = 25.999999... -> 26.
    assert calculate_damage(*args, **PLAIN, attack_stage=4, defence_stage=-4).damage == 26
    # Full charge has the same formula. A shield then overrides it to 1.
    assert calculate_damage(*args, **PLAIN, charged=True).damage == 7
    shielded = calculate_damage(*args, **PLAIN, charged=True, shielded=True)
    assert shielded.damage == 1 and shielded.raw == calculate_damage(*args, **PLAIN).raw
    # Power zero (e.g. Yawn) still does floor(0)+1.
    assert calculate_damage(0, *args[1:], **PLAIN).damage == 1


def test_shadow_flags_are_required():
    # A caller that forgets the Rocket shadow modifiers must fail, not be ~20% off.
    args = (10, 100, 100, "water", ("normal",), ("normal",))
    with pytest.raises(TypeError):
        calculate_damage(*args)
    with pytest.raises(TypeError):
        calculate_damage(*args, attacker_shadow=True)


def test_float_literal_floor_boundary():
    # Human-friendly 20*.5*1.3 = 13 -> 14 damage. Pinned BONUS makes raw
    # 12.999999523162842 -> 13 damage. No fitted stats or float32 intermediates.
    result = calculate_damage(20, 100, 100, "water", ("normal",), ("normal",), **PLAIN)
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
    # Guards: a move is never typeless; a defender needs one or two real types;
    # a bare string is not a type list (it would be read letter by letter).
    for move_type, defenders in [
        ("none", ("water",)),
        ("water", ("none",)),
        ("water", ()),
        ("water", ("fire", "rock", "water")),
        ("water", "fire"),
    ]:
        with pytest.raises(ValueError):
            effectiveness(move_type, defenders)
    with pytest.raises(ValueError, match="real type"):
        calculate_damage(10, 100, 100, "none", ("none",), ("water",), **PLAIN)
    with pytest.raises(ValueError, match="not one string"):
        calculate_damage(10, 100, 100, "water", "water", ("fire",), **PLAIN)


@pytest.mark.parametrize("level", range(1, 5))
def test_mega_metadata_gate(level):
    args = (20, 100, 100, "water", ("water",), ("fire",))
    normal = calculate_damage(*args, **PLAIN)
    assert calculate_damage(*args, **PLAIN, attacker_mega=True, mega_level=level) == normal
    assert calculate_damage(*args, **PLAIN, is_mega_move=True, mega_level=level) == normal
    result = calculate_damage(
        *args, **PLAIN, attacker_mega=True, is_mega_move=True, mega_level=level
    )
    # Preserve where megaMultiplier sits in damage(), including level 1 = 1.
    expected = 20 * STAB * (100 / 100) * SUPER_EFFECTIVE * 1 * MEGA_BONUS[level - 1] * 0.5 * BONUS
    assert result.raw == expected


@pytest.mark.parametrize(
    "damage,hp,expected", [(19, 134, 8), (18, 102, 6), (1, 285, 285), (10, 20, 2), (10, 21, 3)]
)
def test_hit_counts(damage, hp, expected):
    assert hits_to_ko(damage, hp) == expected


def test_hit_counts_accept_any_integral():
    # numpy integers are not int subclasses but register as numbers.Integral.
    # This stdlib stand-in behaves the same way, so no numpy dependency is needed.
    import numbers

    class Int:
        def __init__(self, value):
            self.value = value

        def __le__(self, other):
            return self.value <= other

        def __add__(self, other):
            return Int(self.value + getattr(other, "value", other))

        def __sub__(self, other):
            return Int(self.value - getattr(other, "value", other))

        def __floordiv__(self, other):
            return Int(self.value // getattr(other, "value", other))

        def __int__(self):
            return self.value

    numbers.Integral.register(Int)
    assert not isinstance(Int(1), int)
    result = hits_to_ko(Int(19), Int(134))
    assert type(result) is int and result == 8


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
            calculate_damage(*args, **PLAIN, **options)
    for power, atk, defence in [
        (-1, 100, 100),
        (1, 0, 100),
        (1, 100, 0),
        (math.nan, 100, 100),
        (1, math.inf, 100),
    ]:
        with pytest.raises(ValueError):
            calculate_damage(power, atk, defence, *args[3:], **PLAIN)
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


def test_f7_mega_flag_is_inert():
    # Pinned PvPoke gates the Mega bonus on the move's isMegaMove metadata, and
    # no fixture move has it, so F7's mega_rule alternatives cannot differ.
    for row in (r for r in BATTLES if r["fixture"] == "F7"):
        assert dealt(row, "dec-2025", mega_rule=True) == dealt(row, "dec-2025", mega_rule=False)


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
