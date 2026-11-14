"""Runtime battle acceptance gate. No cached prediction or fixed pass count."""

import json
from pathlib import Path

from .calculator import BattlePredictor, matches

# Gate tables publish every trainer level the targets use, so each must cover and
# pass every target. The supplementary table publishes TL50 only: targets it
# covers must pass; levels it lacks are reported, never filled from another table.
GATE_TABLES = ("venonic-2023", "fugerappi-2023")
SUPPLEMENTARY_TABLES = ("flyfunner-old-50-2025",)
OLD_TABLES = (*GATE_TABLES, *SUPPLEMENTARY_TABLES)
DEFAULT_FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sim"


def run_acceptance(fixtures_dir):
    result = {
        "passed": [],
        "failed": [],
        "unavailable": [],
        "open_discrepancies": [],
        "errors": [],
        "target_count": 0,
    }
    try:
        path = Path(fixtures_dir)
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
        moves = json.loads((path / "move_history.json").read_text())
        predictor = BattlePredictor(species, moves)
        if not targets:
            result["errors"].append("no acceptance targets")
        for row in targets:
            for table in OLD_TABLES:
                entry = {"id": row["id"], "table": table}
                try:
                    prediction = predictor.predict(row, table)
                    entry.update(prediction=prediction, observed=row["observed"])
                    result["passed" if matches(row, prediction) else "failed"].append(entry)
                except ValueError as exc:
                    # A missing published level is a reported coverage gap, never
                    # replaced with another table's value or treated as a pass.
                    entry["reason"] = str(exc)
                    result["unavailable" if "no trainer level" in str(exc) else "failed"].append(
                        entry
                    )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["errors"].append(f"fixtures unavailable or invalid: {exc}")
    blocking = [r for r in result["unavailable"] if r["table"] in GATE_TABLES]
    result["validated"] = not (result["failed"] or result["errors"] or blocking)
    if result["validated"]:
        notes = []
        for table in SUPPLEMENTARY_TABLES:
            gaps = [r["id"] for r in result["unavailable"] if r["table"] == table]
            covered = result["target_count"] - len(gaps)
            note = f"{table}: {covered} covered, all pass"
            notes.append(note + (f"; not covered: {', '.join(gaps)}" if gaps else ""))
        result["label"] = (
            f"Validated against {result['target_count']} pre-Oct-2025 battle targets under "
            f"{' and '.join(GATE_TABLES)} ({'; '.join(notes)}); "
            f"{len(result['open_discrepancies'])} open discrepancies: "
            + ", ".join(r["id"] for r in result["open_discrepancies"])
        )
    else:
        reasons = [*result["errors"]]
        reasons += [f"{len(result['failed'])} target failures"] if result["failed"] else []
        reasons += [f"{r['table']} {r['id']}: {r['reason']}" for r in blocking]
        result["label"] = "UNVALIDATED: " + "; ".join(reasons)
    return result
