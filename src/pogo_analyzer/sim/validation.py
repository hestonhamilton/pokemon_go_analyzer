"""Runtime battle acceptance gate, pinned to the reviewed target set. No cached prediction."""

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
# The reviewed acceptance corpus has exactly this many targets. This is a code
# constant on purpose: regenerating the pin file cannot change it.
EXPECTED_TARGETS = 44
# The pin: the exact target IDs, the open-discrepancy IDs, and a SHA-256 of what
# decides each target. It catches accidental or unreviewed drift in the fixtures.
# It does NOT stop a deliberate change made together with a regenerated pin
# (tools/fixtures/acceptance_pin.py): that is defended only by the owner reviewing
# the pin diff. CODEOWNERS marks the file but does not enforce review here.
PIN = json.loads(files(__package__).joinpath("data", "acceptance_pin.json").read_text())
FIXTURE_FILES = ("battles.json", "species_moves.json", "move_history.json")
# Fields that decide or identify a target; free prose (evidence, notes, reasons)
# is not pinned.
PINNED_FIELDS = (
    "id",
    "fixture",
    "source",
    "basis",
    "status",
    "battle_date",
    "regime",
    "trainer_level",
    "player",
    "rocket",
    "observed",
)
# The species fields the predictor reads. PvPoke move lists are not pinned, so
# a routine species refresh does not force a meaningless re-pin.
SPECIES_FIELDS = ("baseStats", "types")
MOVE_FIELDS = ("type", "power", "energy_gain", "energy", "turns")

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


def _plural(count, word, plural=None):
    return f"{count} {word}" if count == 1 else f"{count} {plural or word + 's'}"


def acceptance_targets(battles):
    """The acceptance targets: recorded or measured records expected to pass."""
    return [
        r
        for r in battles
        if r["basis"] in ("recorded", "measured") and r["status"] == "expected_pass"
    ]


def open_discrepancies(battles):
    return [r for r in battles if r["status"] == "open_discrepancy"]


def _target_moves(row):
    """Move IDs whose dated snapshot a target's prediction used."""
    kind = row["observed"]["kind"]
    if kind in ("player_hp", "rocket_hp"):
        return []
    if kind == "damage_per_hit_taken":
        return [row["observed"]["move"]]
    return [row["observed"].get("move", row["player"]["fast_move"])]


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
        "species": {name: {k: species[name][k] for k in SPECIES_FIELDS} for name in used_species},
        "moves": [
            [m, date, [s for s in history[m] if s["as_of"] == date]] for m, date in used_moves
        ],
    }
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_fixtures(fixtures_dir):
    """(battles, species, history). File names only in errors, never a local path."""
    path = Path(fixtures_dir)
    missing = [name for name in FIXTURE_FILES if not (path / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"fixtures not found (missing {', '.join(missing)}); "
            "validation needs a source checkout or --fixtures-dir"
        )
    loaded = {}
    for name in FIXTURE_FILES:
        try:
            loaded[name] = json.loads((path / name).read_text())
        except OSError as exc:
            raise OSError(f"cannot read {name}: {type(exc).__name__}") from None
        except ValueError as exc:
            raise ValueError(f"{name} is not valid JSON: {exc}") from None
    battles = loaded["battles.json"]
    return battles, loaded["species_moves.json"]["species"], loaded["move_history.json"]


def _id_diff(expected, found):
    detail = []
    if expected - found:
        detail.append("missing " + ", ".join(sorted(expected - found)))
    if found - expected:
        detail.append("unexpected " + ", ".join(sorted(found - expected)))
    return "; ".join(detail)


def discrepancy_digest(battles):
    """SHA-256 of the open discrepancies' identifying and outcome fields."""
    rows = sorted(
        ({k: r[k] for k in PINNED_FIELDS} for r in open_discrepancies(battles)),
        key=lambda r: r["id"],
    )
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def pin_errors(battles, species, history, pin=None):
    """Every way the fixtures differ from the pin; empty means they match."""
    pin = PIN if pin is None else pin
    errors = []
    targets = acceptance_targets(battles)
    ids = {r["id"] for r in targets}
    expected = set(pin["target_ids"])
    if len(expected) != EXPECTED_TARGETS:
        errors.append(f"the pin lists {len(expected)} targets, not {EXPECTED_TARGETS}")
    if len(targets) != EXPECTED_TARGETS or ids != expected:
        message = (
            f"expected the {EXPECTED_TARGETS} reviewed acceptance targets, found {len(targets)}"
        )
        if ids != expected:
            message += f" ({_id_diff(expected, ids)})"
        errors.append(message)
    elif acceptance_digest(targets, species, history) != pin["sha256"]:
        errors.append("acceptance target inputs differ from the reviewed set (SHA-256 mismatch)")
    found = {r["id"] for r in open_discrepancies(battles)}
    reviewed = set(pin["discrepancy_ids"])
    if found != reviewed:
        errors.append(
            f"open discrepancies differ from the reviewed set ({_id_diff(reviewed, found)})"
        )
    elif discrepancy_digest(battles) != pin.get("discrepancy_sha256"):
        errors.append("open discrepancy records differ from the reviewed set (SHA-256 mismatch)")
    return errors


def run_acceptance(fixtures_dir, *, check_pin=True):
    """Recompute every target. check_pin=False is for the pin tool only."""
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
        battles, species, history = load_fixtures(fixtures_dir)
        targets = acceptance_targets(battles)
        result["target_count"] = len(targets)
        result["open_discrepancies"] = [dict(r) for r in open_discrepancies(battles)]
        if check_pin:
            result["errors"] += pin_errors(battles, species, history)
        predictor = BattlePredictor(species, history)
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
                                **{k: snap[k] for k in MOVE_FIELDS},
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
    except OSError as exc:
        # load_fixtures rewrites read errors to the file name and error type only.
        result["errors"].append(
            f"fixtures invalid: {exc.args[0] if exc.args else type(exc).__name__}"
        )
    except (ValueError, KeyError, TypeError) as exc:
        result["errors"].append(f"fixtures invalid: {type(exc).__name__}: {exc}")
    blocking = [r for r in result["unavailable"] if r["table"] in GATE_TABLES]
    result["validated"] = not (result["failed"] or result["errors"] or blocking)
    if result["validated"]:
        # What the passing targets actually reproduced. Grades use this together
        # with "validated", so a failed gate leaves nothing fixture-exact.
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
