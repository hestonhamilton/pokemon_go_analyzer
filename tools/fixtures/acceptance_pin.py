"""Show, and on request rewrite, the acceptance pin for tests/fixtures/sim.

The pin (src/pogo_analyzer/sim/data/acceptance_pin.json) lists the reviewed
target IDs, the open-discrepancy IDs and a SHA-256 of what decides each target.
The calculator's gate fails if any of them differs.

The pin catches accidental or unreviewed drift. It cannot stop a deliberate
change made together with a new pin: that is defended only by the owner
reviewing the pin diff (CODEOWNERS marks the file but does not enforce review
here). So this tool:
- refuses (exit 1) unless every target passes on both gate tables, ignoring the
  pin, with no gate-table gap;
- prints the id changes and the old and new hash before anything is written;
- refuses a target count other than validation.EXPECTED_TARGETS unless
  --allow-count-change is given (and the gate still fails until that code
  constant is changed in a reviewed commit);
- refuses to drop an open discrepancy unless --allow-discrepancy-removal is given.

    uv run python tools/fixtures/acceptance_pin.py            # check and show the diff
    uv run python tools/fixtures/acceptance_pin.py --write    # rewrite the pin
"""

import argparse
import json
import sys
from pathlib import Path

from pogo_analyzer.sim import validation

ROOT = Path(__file__).resolve().parents[2]
PIN_PATH = ROOT / "src/pogo_analyzer/sim/data/acceptance_pin.json"
FIXTURES = ROOT / "tests/fixtures/sim"


def build(fixtures):
    battles, species, history = validation.load_fixtures(fixtures)
    targets = validation.acceptance_targets(battles)
    return {
        "note": "Reviewed acceptance targets. Regenerate only with a fixture review.",
        "target_ids": sorted(r["id"] for r in targets),
        "discrepancy_ids": sorted(r["id"] for r in validation.open_discrepancies(battles)),
        "discrepancy_sha256": validation.discrepancy_digest(battles),
        "sha256": validation.acceptance_digest(targets, species, history),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixtures-dir", type=Path, default=FIXTURES)
    parser.add_argument("--write", action="store_true", help="rewrite the pin file")
    parser.add_argument("--allow-count-change", action="store_true")
    parser.add_argument("--allow-discrepancy-removal", action="store_true")
    parser.add_argument("--pin", type=Path, default=PIN_PATH, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    pin_path = args.pin

    gate = validation.run_acceptance(args.fixtures_dir, check_pin=False)
    if not gate["validated"]:
        print(f"refusing: the gate fails without the pin: {gate['label']}", file=sys.stderr)
        return 1
    new = build(args.fixtures_dir)
    old = json.loads(pin_path.read_text()) if pin_path.exists() else {}
    for key in ("target_ids", "discrepancy_ids"):
        before, after = set(old.get(key, [])), set(new[key])
        for label, ids in (("added", after - before), ("removed", before - after)):
            if ids:
                print(f"{key} {label}: {', '.join(sorted(ids))}")
    print(f"sha256 old: {old.get('sha256', '(none)')}")
    print(f"sha256 new: {new['sha256']}")
    count = len(new["target_ids"])
    if count != validation.EXPECTED_TARGETS and not args.allow_count_change:
        print(
            f"refusing: {count} targets, not {validation.EXPECTED_TARGETS}; a count change "
            "needs --allow-count-change and a reviewed change to EXPECTED_TARGETS",
            file=sys.stderr,
        )
        return 1
    dropped = set(old.get("discrepancy_ids", [])) - set(new["discrepancy_ids"])
    if dropped and not args.allow_discrepancy_removal:
        print(
            f"refusing: open discrepancies removed ({', '.join(sorted(dropped))}); "
            "this needs --allow-discrepancy-removal and a reviewed reason",
            file=sys.stderr,
        )
        return 1
    if new == old:
        print("pin unchanged")
    elif args.write:
        pin_path.write_text(json.dumps(new, indent=2) + "\n")
        print(f"wrote {pin_path.name}; the diff needs the owner's review")
    else:
        print("pin differs; rerun with --write to update it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
