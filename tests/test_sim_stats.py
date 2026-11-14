"""Offline stats acceptance checks. Run this file directly to print the review report.

The xfail lists were frozen after review and are not regenerated from current output.
New mismatches fail normally; improvements to an xfailed row cause strict XPASS.
Lookups at a trainer level a table lacks are checked separately, so no row can
pass (or XPASS) without a CP comparison.
"""

import json
import math
from collections import Counter
from importlib.resources import files
from pathlib import Path

import pytest

from pogo_analyzer.sim import (
    SHADOW_ATK,
    SHADOW_DEF,
    cp,
    player_cpm,
    player_stats,
    rcpm,
    rocket_stats,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sim"


def read_fixture(name):
    return json.loads((FIXTURES / name).read_text())


READINGS = read_fixture("cp_readings.json")
BATTLES = {row["id"]: row for row in read_fixture("battles.json")}
SPECIES = read_fixture("species_moves.json")["species"]
KNOWN = read_fixture("stats_expected_failures.json")
REVIEW = read_fixture("stats_review.json")
TABLES = json.loads(files("pogo_analyzer.sim").joinpath("data", "rcpm.json").read_text())
OLD_TABLES = ("venonic-2023", "fugerappi-2023")
OLD_COMPARISONS = (*OLD_TABLES, "flyfunner-old-50-2025", "flyfunner-lower-2023")
RANKS = ("grunt", "leader", "giovanni")


def row_key(row):
    return "|".join(
        (
            row["source"],
            str(row["trainer_level"]),
            row["species"],
            row["rank"] or "unknown",
            str(row["cp"]),
        )
    )


def cases():
    for index, row in enumerate(READINGS):
        if row["regime"] == "rcpm-old":
            variants = OLD_COMPARISONS
        elif row["regime"] == "rcpm-dec-2025":
            variants = ("dec-2025",)
        else:
            assert row["regime"] == "rcpm-oct-2025"
            variants = (*OLD_COMPARISONS, "dec-2025")
        for variant in variants:
            yield index, row, variant, variant, row["trainer_level"]
        # The October source explicitly compares new TL70 to old TL40. This is
        # a separate hypothesis, never an alias or extrapolation in rocket_stats.
        if row["regime"] == "rcpm-oct-2025":
            for table in ("fugerappi-2023", "flyfunner-lower-2023"):
                yield index, row, f"october-tl40-hypothesis:{table}", table, 40


CASES = list(cases())


def predictions(row, table, level):
    base = SPECIES[row["species"]]["baseStats"]
    ranks = (row["rank"],) if row["rank"] else RANKS
    return {rank: rocket_stats(base, level, rank, table).cp for rank in ranks}


def xfail_reason(row, variant):
    for entry in KNOWN:
        if entry["row_key"] == row_key(row) and variant in entry["xfail_variants"]:
            return f"{entry['reason']} Source: {entry['source_quotes'][0]}"
    for entry in REVIEW.get(variant, []):
        if entry["row_key"] == row_key(row):
            return "UNEXPLAINED – needs review"
    return None


def available(table, level):
    return str(level) in TABLES[table]["values"]


def reading_params():
    for index, row, variant, table, level in CASES:
        if not available(table, level):
            continue
        if row["status"] == "weak":
            # Disputed or unstated-rank readings are reported, never gating.
            # raises= keeps a crash from hiding as an expected failure.
            marks = [
                pytest.mark.xfail(
                    strict=False,
                    reason=f"weak: {row['status_reason']}",
                    raises=AssertionError,
                )
            ]
        else:
            reason = xfail_reason(row, variant)
            marks = (
                [pytest.mark.xfail(strict=True, reason=reason, raises=AssertionError)]
                if reason
                else []
            )
        yield pytest.param(
            row,
            table,
            level,
            marks=marks,
            id=f"{index:03}-{row['species']}-{row['cp']}-{variant}",
        )


def unavailable_params():
    for index, row, variant, table, level in CASES:
        if not available(table, level):
            yield pytest.param(
                row, table, level, id=f"{index:03}-{row['species']}-{row['cp']}-{variant}"
            )


@pytest.mark.parametrize("row,table,level", list(reading_params()))
def test_cp_reading(row, table, level):
    actual = predictions(row, table, level)
    assert sum(value == row["cp"] for value in actual.values()) == 1, (
        row_key(row),
        actual,
        row["evidence"],
    )


@pytest.mark.parametrize("row,table,level", list(unavailable_params()))
def test_unavailable_level_raises(row, table, level):
    # Unavailable is neither a match nor a mismatch: the lookup must refuse.
    # Neither old table lists TL70; Venonic also omits TL47.
    with pytest.raises(ValueError, match="no trainer level"):
        predictions(row, table, level)


def test_f1_metagross_hp():
    fixture = BATTLES["F1-metagross-hp"]
    assert fixture["basis"] == "recorded" and fixture["status"] == "expected_pass"
    player = fixture["player"]
    # (190 + 12) * 0.807803863460723 = 163.17638041906605 -> 163.
    result = player_stats(
        SPECIES[player["species"]]["baseStats"],
        player["ivs"],
        player["level"],
        form=player["form"],
    )
    assert result.hp == fixture["observed"]["value"] == 163
    assert result.form == "shadow"


@pytest.mark.parametrize("table", OLD_TABLES)
def test_f2_cyndaquil_hp(table):
    fixture = BATTLES["F2-cyndaquil-hp"]
    assert fixture["basis"] == "measured" and fixture["status"] == "expected_pass"
    result = rocket_stats(
        SPECIES[fixture["rocket"]["species"]]["baseStats"],
        fixture["trainer_level"],
        fixture["rocket"]["rank"],
        table,
    )
    # floor(.6 * (118 + 15)) = 79; 79 * 1.27002 = 100.33158.
    # With fugerappi's 1.270: 79 * 1.270 = 100.33. Both fit the measured bracket.
    assert 100 <= result.hp_exact <= 100.99999
    assert result.hp == fixture["observed"]["value"] == 100


def test_player_cpm_values_and_half_level_crosscheck():
    assert player_cpm(1) == 0.0939999967813491
    assert player_cpm(43.5) == 0.807803863460723
    assert player_cpm(55) == 0.865299999713897
    for level in range(1, 55):
        # Squared CPM is linear between the adjacent whole levels.
        interpolated = math.sqrt((player_cpm(level) ** 2 + player_cpm(level + 1) ** 2) / 2)
        assert abs(player_cpm(level + 0.5) - interpolated) <= 1e-9


@pytest.mark.parametrize("level", [0, 0.5, 55.5, 56, 10.25, math.inf, math.nan, True, "10"])
def test_player_cpm_rejects_invalid_levels(level):
    with pytest.raises(ValueError, match="half-level"):
        player_cpm(level)


@pytest.mark.parametrize("form", ["normal", "shadow", "purified"])
def test_player_stats_unrounded_and_form_is_metadata(form):
    result = player_stats(
        {"atk": 100, "def": 80, "hp": 90}, {"atk": 10, "def": 5, "hp": 15}, 1, form=form
    )
    # 110 * CPM = 10.339999645948401; 85 * CPM = 7.989999726414674;
    # 105 * CPM = 9.869999662041655 -> floor 9, then minimum HP 10.
    assert result.attack == pytest.approx(10.339999645948401, abs=1e-13)
    assert result.defence == pytest.approx(7.989999726414674, abs=1e-13)
    assert result.hp_exact == pytest.approx(9.869999662041655, abs=1e-13)
    assert result.hp == 10
    assert result.form == form
    assert SHADOW_ATK == 1.2
    assert SHADOW_DEF == 0.83333331
    assert SHADOW_DEF != 5 / 6


def test_cp_uses_exact_hp_and_minimum():
    # sqrt(100.99) * 100 * sqrt(100) / 10 = 1004.937808997 -> 1004.
    # Flooring stamina first would incorrectly give 1000.
    assert cp(100, 100, 100.99) == 1004
    # 1 * sqrt(1) * sqrt(1) / 10 = .1 -> floor 0 -> minimum 10.
    assert cp(1, 1, 1) == 10
    assert cp(0, 0, 0) == 10


@pytest.mark.parametrize("value", [-1, math.inf, math.nan])
def test_cp_rejects_invalid_totals(value):
    with pytest.raises(ValueError):
        cp(value, 100, 100)


@pytest.mark.parametrize(
    "rank,attack,defence,hp_exact,battle_hp,expected_cp",
    [
        ("grunt", 77, 28, 28.56, 28, 217),
        ("leader", 80.85, 29.4, 29.988, 29, 240),
        ("giovanni", 88.55, 32.2, 32.844, 32, 287),
    ],
)
def test_rocket_formula_by_hand(rank, attack, defence, hp_exact, battle_hp, expected_cp):
    # Base 150/85/155: attack IV floor(2/3 * 150 + 25) = 125.
    # At TL8 (.280), ATK = 275*.28 = 77; DEF = 100*.28 = 28;
    # HP = floor(.6*170)*.28 = 102*.28 = 28.56, battle HP 28.
    # CP = floor(sqrt(28.56)*77*sqrt(28)*.1) = floor(217.745...) = 217.
    # Each rank scales all three stats, hence unrounded CP scales by rank²:
    # leader 217.745...*1.05² = 240.064...; Giovanni *1.15² = 287.968....
    result = rocket_stats({"atk": 150, "def": 85, "hp": 155}, 8, rank, "fugerappi-2023")
    assert result.attack == pytest.approx(attack)
    assert result.defence == pytest.approx(defence)
    assert result.hp_exact == pytest.approx(hp_exact)
    assert result.hp == battle_hp
    assert result.cp == expected_cp
    assert result.rank == rank
    assert result.table == "fugerappi-2023"


def test_rocket_formula_source_example_granbull():
    # Venonic's own worked example (122pfk8, "Quick Look at the New Stats"):
    # Granbull, base 207/212/131 HP/ATK/DEF, level 41 trainer:
    # "|New|8496|168.91|480.07|185.42|". This comes from the formula's source,
    # not the CP corpus, and pins HP, attack and defence individually.
    # HP  floor(.6*(207+15)) = 133; 133*1.27002 = 168.91266.
    # ATK 212 + floor(2/3*212+25) = 212+166 = 378; 378*1.27002 = 480.06756.
    # DEF (131+15)*1.27002 = 185.42292.
    result = rocket_stats({"atk": 212, "def": 131, "hp": 207}, 41, "grunt", "venonic-2023")
    assert round(result.hp_exact, 2) == 168.91
    assert round(result.attack, 2) == 480.07
    assert round(result.defence, 2) == 185.42
    assert result.hp == 168
    assert result.cp == 8496


def test_rocket_floors_attack_iv_and_hp_before_scaling():
    # floor(2/3*2+25) = 26, not 27; floor(.6*(2+15)) = 10, not 10.2.
    result = rocket_stats({"atk": 2, "def": 1, "hp": 2}, 8, "grunt", "fugerappi-2023")
    assert result.attack == pytest.approx(7.84)  # (2+26)*.28
    assert result.defence == pytest.approx(4.48)  # (1+15)*.28
    assert result.hp_exact == pytest.approx(2.8)  # 10*.28
    assert result.hp == 2  # No player HP minimum is asserted for Rockets.


def test_player_stats_missing_key_and_shedinja():
    with pytest.raises(ValueError, match="missing base stat hp"):
        player_stats({"atk": 1, "def": 1}, {"atk": 0, "def": 0, "hp": 0}, 1)
    with pytest.raises(ValueError, match="missing IV def"):
        player_stats({"atk": 1, "def": 1, "hp": 1}, {"atk": 0, "hp": 0}, 1)
    # Shedinja (base 153/73/1): (1 + 15) * 0.84029999 = 13.44 -> 13 without the
    # override; PvPoke Pokemon.js L384-388 sets dex 292 to 10 HP.
    shedinja = {"atk": 153, "def": 73, "hp": 1}
    full = {"atk": 15, "def": 15, "hp": 15}
    assert player_stats(shedinja, full, 50).hp == 13
    assert player_stats(shedinja, full, 50, dex=292).hp == 10


def test_table_precision_and_unmodified_estimates():
    assert rcpm(50, "venonic-2023") == 1.31502
    assert rcpm(50, "fugerappi-2023") == 1.315
    assert rcpm(50, "flyfunner-old-50-2025") == 1.31502044
    # 1.191 converted to IEEE 754 binary32 is 1.190999984741211.
    assert rcpm(60, "dec-2025") == 1.190999984741211
    assert rcpm(80, "dec-2025") == 1.315000057220459
    # The lower-level source's estimate lies BELOW its own minimum. Do not repair it.
    assert rcpm(34, "flyfunner-lower-2023") == 1.116755
    assert float(TABLES["flyfunner-lower-2023"]["values"]["34"]["min"]) == 1.11676025


@pytest.mark.parametrize(
    "level,table",
    [
        (47, "venonic-2023"),
        (70, "fugerappi-2023"),
        (7, "dec-2025"),
        (81, "dec-2025"),
        (13, "flyfunner-lower-2023"),
        (50, "unknown"),
        (50.0, "dec-2025"),
        (True, "dec-2025"),
    ],
)
def test_rcpm_never_fills_missing_levels(level, table):
    with pytest.raises(ValueError):
        rcpm(level, table)


def test_table_inventory_and_review_keys():
    expected = {
        "venonic-2023": {41, 45, 49, 50},
        "fugerappi-2023": set(range(8, 51)),
        "flyfunner-lower-2023": {8, 9, 10, 11, 12, 27, 28, 29, 30, 32, 33, 34, 37, 38, 39, 40},
        "dec-2025": set(range(8, 81)),
        "flyfunner-old-50-2025": {50},
    }
    for table, levels in expected.items():
        assert set(map(int, TABLES[table]["values"])) == levels
        assert TABLES[table]["source"].startswith("https://www.reddit.com/")
        for entry in TABLES[table]["values"].values():
            assert entry["decimal"] in entry["quote"]
    for level in ("32", "48"):
        assert "I lost the data" in TABLES["fugerappi-2023"]["values"][level]["flag"]
    keys = {row_key(row) for row in READINGS}
    assert len(keys) == len(READINGS)
    status = {row_key(row): row["status"] for row in READINGS}
    assert len(KNOWN) == 1
    for entry in KNOWN:
        assert entry["row_key"] in keys
        assert status[entry["row_key"]] == "expected_pass"
        assert entry["reason"] and entry["source_quotes"]
    for entries in REVIEW.values():
        for entry in entries:
            assert entry["row_key"] in keys
            assert status[entry["row_key"]] == "expected_pass"
            assert entry["reason"] == "UNEXPLAINED – needs review"


def test_review_predictions_pinned():
    # The strict xfails only say "CP mismatches". Pin the predicted value too, so
    # a formula change that moves a reviewed row (say 11356 -> 11300) fails here.
    # KNOWN (Gallade) has no stored prediction: its source quote gives 10215.
    for variant, entries in REVIEW.items():
        for entry in entries:
            cases = [
                (row, table, level)
                for _, row, v, table, level in CASES
                if v == variant and row_key(row) == entry["row_key"]
            ]
            assert len(cases) == 1, (variant, entry["row_key"])
            row, table, level = cases[0]
            assert predictions(row, table, level) == entry["predicted"], entry["row_key"]
            assert row["cp"] == entry["observed"]
    (row, table, level), *rest = [
        (row, table, level)
        for _, row, v, table, level in CASES
        if row_key(row) == KNOWN[0]["row_key"] and v in KNOWN[0]["xfail_variants"]
    ]
    assert not rest
    assert predictions(row, table, level) == {"grunt": 10215}


# The published headline counts (docs/simulator-verification.md "Stats results"
# and stats_report.md). Changing a status, a table or the formula must update both.
PUBLISHED_COUNTS = {
    "venonic-2023": {
        "matched": 149,
        "mismatched": 1,
        "unexplained": 1,
        "weak": 5,
        "unavailable": 16,
    },
    "fugerappi-2023": {
        "matched": 123,
        "mismatched": 30,
        "unexplained": 30,
        "weak": 5,
        "unavailable": 13,
    },
    "flyfunner-old-50-2025": {"matched": 147, "weak": 4, "unavailable": 20},
    "flyfunner-lower-2023": {"unavailable": 171},
    "dec-2025": {"matched": 13},
    "october-tl40-hypothesis:fugerappi-2023": {"matched": 13},
    "october-tl40-hypothesis:flyfunner-lower-2023": {
        "matched": 12,
        "mismatched": 1,
        "expected_fail": 1,
    },
}


def test_published_counts():
    assert summary_counts() == PUBLISHED_COUNTS


def summary_counts(report=False):
    counts = {}
    for index, row, variant, table, level in CASES:
        summary = counts.setdefault(variant, Counter())
        if str(level) not in TABLES[table]["values"]:
            summary["unavailable"] += 1
            continue
        values = predictions(row, table, level)
        if row["status"] == "weak":
            summary["weak"] += 1
            if report:
                print(f"{variant} row {index:03} (weak): {row_key(row)}; calculated {values}")
        elif sum(value == row["cp"] for value in values.values()) == 1:
            summary["matched"] += 1
        else:
            summary["mismatched"] += 1
            reason = xfail_reason(row, variant)
            summary[
                "unexplained" if reason == "UNEXPLAINED – needs review" else "expected_fail"
            ] += 1
            if report:
                print(f"{variant} row {index:03}: {row_key(row)}; calculated {values}; {reason}")
    return {variant: dict(counter) for variant, counter in counts.items()}


def print_report():
    print(json.dumps(summary_counts(report=True), indent=2))
    fixture = BATTLES["F1-metagross-hp"]["player"]
    f1 = player_stats(
        SPECIES[fixture["species"]]["baseStats"],
        fixture["ivs"],
        fixture["level"],
        form=fixture["form"],
    )
    for table in OLD_TABLES:
        f2 = rocket_stats(SPECIES["cyndaquil"]["baseStats"], 41, "grunt", table)
        print(f"{table}: F1 HP {f1.hp}; F2 hp_exact {f2.hp_exact:.8f}, battle HP {f2.hp}")


if __name__ == "__main__":
    print_report()
