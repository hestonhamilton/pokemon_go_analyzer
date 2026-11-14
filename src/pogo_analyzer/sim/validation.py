"""Runtime battle acceptance gate. No cached prediction; the target count is pinned."""

import json
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
# The acceptance corpus has exactly this many recorded or measured expected_pass
# targets. A trimmed or edited fixture set must not report itself as validated.
# Change this only together with the fixtures and their review.
EXPECTED_TARGETS = 44


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


def _empty_coverage():
    return {"levels": [], "moves": []}


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
    levels, moves = set(), {}
    try:
        path = Path(fixtures_dir)
        if not (path / "battles.json").is_file():
            raise FileNotFoundError(
                "fixtures not found; validation needs a source checkout or --fixtures-dir"
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
        if len(targets) != EXPECTED_TARGETS:
            result["errors"].append(
                f"expected {EXPECTED_TARGETS} acceptance targets, found {len(targets)}"
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
                        levels.add((table, row["trainer_level"]))
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
            "levels": sorted([t, tl] for t, tl in levels),
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
