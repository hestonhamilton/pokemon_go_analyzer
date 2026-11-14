"""Runtime battle acceptance gate. No cached prediction; the target count is pinned."""

import hashlib
import json
from importlib.resources import files
from pathlib import Path

from .calculator import BattlePredictor, matches

# Gate tables publish every trainer level the targets use, so each must cover and
# pass every target. The supplementary table publishes TL50 only: targets it
# covers must pass; levels it lacks are reported, never filled from another table.
# Only gate tables can earn fixture-exact grades (see coverage below).
GATE_TABLES = ("venonic-2023", "fugerappi-2023")
SUPPLEMENTARY_TABLES = ("flyfunner-old-50-2025",)
OLD_TABLES = (*GATE_TABLES, *SUPPLEMENTARY_TABLES)
# The fixtures live in the source tree (tests/fixtures/sim), not in the wheel.
# Validation therefore needs a source checkout or an explicit --fixtures-dir.
DEFAULT_FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sim"
# The reviewed acceptance corpus: the exact target IDs and a SHA-256 of their
# inputs and observations (plus the species and dated moves they use). A
# trimmed, padded, swapped or edited target set fails the gate. Regenerate with
# tools/fixtures/acceptance_pin.py only together with the fixture review.
PIN = json.loads(files(__package__).joinpath("data", "acceptance_pin.json").read_text())
EXPECTED_TARGETS = len(PIN["target_ids"])
FIXTURE_FILES = ("battles.json", "species_moves.json", "move_history.json")
# Fields that decide a target's outcome; prose (evidence, notes, reasons) is excluded.
PINNED_FIELDS = (
    "id",
    "fixture",
    "basis",
    "status",
    "battle_date",
    "regime",
    "trainer_level",
    "player",
    "rocket",
    "observed",
)


def _plural(count, word, plural=None):
    return f"{count} {word}" if count == 1 else f"{count} {plural or word + 's'}"


def _target_moves(row):
    """Move IDs whose dated snapshot a target's prediction used."""
    kind = row["observed"]["kind"]
    if kind in ("player_hp", "rocket_hp"):
        return []
    if kind == "damage_per_hit_taken":
        return [row["observed"]["move"]]
    return [row["observed"].get("move", row["player"]["fast_move"])]


# Which Rocket quantities a target's prediction depends on. Coverage is kept per
# quantity, so the HP-only F2 target at TL41 covers Rocket HP there, nothing else.
QUANTITIES = ("rocket_hp", "rocket_attack", "rocket_defence")
KIND_QUANTITIES = {
    "player_hp": (),
    "rocket_hp": ("rocket_hp",),
    "damage_per_hit_taken": ("rocket_attack",),
    "damage_per_hit_dealt": ("rocket_defence",),
    "hits_to_ko": ("rocket_hp", "rocket_defence"),
    "survives_hits": ("rocket_hp", "rocket_defence"),
    "remaining_hp_after": ("rocket_hp", "rocket_defence"),
}


def _empty_coverage():
    return {"levels": {q: [] for q in QUANTITIES}, "moves": []}


def acceptance_digest(targets, species, history):
    """SHA-256 over what decides each target, in a canonical JSON form."""
    named = {r["player"]["species"] for r in targets} | {r["rocket"]["species"] for r in targets}
    used_species = sorted(name for name in named if name)  # F2 states no player species.
    used_moves = sorted({(m, r["battle_date"]) for r in targets for m in _target_moves(r)})
    document = {
        "targets": sorted(
            ({k: r[k] for k in PINNED_FIELDS} for r in targets), key=lambda r: r["id"]
        ),
        "species": {name: species[name] for name in used_species},
        "moves": [
            [m, date, [s for s in history[m] if s["as_of"] == date]] for m, date in used_moves
        ],
    }
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def run_acceptance(fixtures_dir):
    result = {
        "passed": [],
        "failed": [],
        "unavailable": [],
        "open_discrepancies": [],
        "errors": [],
        "target_count": 0,
        "coverage": _empty_coverage(),
    }
    levels, moves = {q: set() for q in QUANTITIES}, {}
    try:
        path = Path(fixtures_dir)
        missing = [name for name in FIXTURE_FILES if not (path / name).is_file()]
        if missing:
            # File names only, never the local path.
            raise FileNotFoundError(
                f"fixtures not found (missing {', '.join(missing)}); "
                "validation needs a source checkout or --fixtures-dir"
            )
        battles = json.loads((path / "battles.json").read_text())
        targets = [
            r
            for r in battles
            if r["basis"] in ("recorded", "measured") and r["status"] == "expected_pass"
        ]
        result["target_count"] = len(targets)
        result["open_discrepancies"] = [
            dict(r) for r in battles if r["status"] == "open_discrepancy"
        ]
        species = json.loads((path / "species_moves.json").read_text())["species"]
        history = json.loads((path / "move_history.json").read_text())
        predictor = BattlePredictor(species, history)
        ids = {r["id"] for r in targets}
        expected = set(PIN["target_ids"])
        if len(targets) != EXPECTED_TARGETS or ids != expected:
            detail = []
            if expected - ids:
                detail.append("missing " + ", ".join(sorted(expected - ids)))
            if ids - expected:
                detail.append("unexpected " + ", ".join(sorted(ids - expected)))
            result["errors"].append(
                f"expected the {EXPECTED_TARGETS} reviewed acceptance targets, found "
                f"{len(targets)}" + (f" ({'; '.join(detail)})" if detail else "")
            )
        elif acceptance_digest(targets, species, history) != PIN["sha256"]:
            result["errors"].append(
                "acceptance target inputs differ from the reviewed set (SHA-256 mismatch)"
            )
        for row in targets:
            for table in OLD_TABLES:
                entry = {"id": row["id"], "table": table}
                try:
                    prediction = predictor.predict(row, table)
                    entry.update(prediction=prediction, observed=row["observed"])
                    passed = matches(row, prediction)
                    result["passed" if passed else "failed"].append(entry)
                    if passed and table in GATE_TABLES:
                        for quantity in KIND_QUANTITIES[row["observed"]["kind"]]:
                            levels[quantity].add((table, row["trainer_level"]))
                        for move_id in _target_moves(row):
                            snap = predictor.dated_move(move_id, row["battle_date"])
                            moves[(move_id, row["battle_date"])] = {
                                "move": move_id,
                                "as_of": row["battle_date"],
                                **{
                                    k: snap[k]
                                    for k in ("type", "power", "energy_gain", "energy", "turns")
                                },
                            }
                except ValueError as exc:
                    # A missing published level is a reported coverage gap, never
                    # replaced with another table's value or treated as a pass.
                    entry["reason"] = str(exc)
                    result["unavailable" if "no trainer level" in str(exc) else "failed"].append(
                        entry
                    )
    except FileNotFoundError as exc:
        # No local path in the label: the reason is the same on every machine.
        result["errors"].append(
            exc.args[0]
            if "source checkout" in str(exc)
            else "fixtures not found; validation needs a source checkout or --fixtures-dir"
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["errors"].append(f"fixtures invalid: {type(exc).__name__}: {exc}")
    blocking = [r for r in result["unavailable"] if r["table"] in GATE_TABLES]
    result["validated"] = not (result["failed"] or result["errors"] or blocking)
    if result["validated"]:
        # What the passing targets actually reproduced. Grades use this, so a
        # failed gate leaves nothing fixture-exact.
        result["coverage"] = {
            "levels": {q: sorted([t, tl] for t, tl in levels[q]) for q in QUANTITIES},
            "moves": sorted(moves.values(), key=lambda m: (m["move"], m["as_of"])),
        }
        notes = []
        for table in SUPPLEMENTARY_TABLES:
            gaps = [r["id"] for r in result["unavailable"] if r["table"] == table]
            covered = result["target_count"] - len(gaps)
            note = f"{table}: {covered} covered, all pass"
            notes.append(note + (f"; not covered: {', '.join(gaps)}" if gaps else ""))
        discrepancies = result["open_discrepancies"]
        result["label"] = (
            f"Validated against {_plural(result['target_count'], 'pre-Oct-2025 battle target')} "
            f"under {' and '.join(GATE_TABLES)} ({'; '.join(notes)}); "
            f"{_plural(len(discrepancies), 'open discrepancy', 'open discrepancies')}"
            + (": " + ", ".join(r["id"] for r in discrepancies) if discrepancies else "")
        )
    else:
        reasons = [*result["errors"]]
        failed_ids = sorted({r["id"] for r in result["failed"]})
        if failed_ids:
            reasons.append(f"{_plural(len(failed_ids), 'target')} failed: {', '.join(failed_ids)}")
        reasons += [f"{r['table']} {r['id']}: {r['reason']}" for r in blocking]
        result["label"] = "UNVALIDATED: " + "; ".join(reasons)
    return result
