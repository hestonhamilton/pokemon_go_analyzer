"""Show, and on request rewrite, the acceptance pin for tests/fixtures/sim.

The pin (src/pogo_analyzer/sim/data/acceptance_pin.json) lists the reviewed
target IDs, the open-discrepancy IDs and a SHA-256 of what decides each target.
The calculator's gate fails if any of them differs.

The pin catches accidental or unreviewed drift. It cannot stop a deliberate
change made together with a new pin: that is defended only by reviewing the pin
diff (CODEOWNERS routes it to the owner). So this tool:
- refuses (exit 1) unless every target passes on both gate tables, ignoring the
  pin, with no gate-table gap;
- prints the id changes and the old and new hash before anything is written;
- refuses a target count other than validation.EXPECTED_TARGETS unless
  --allow-count-change is given (and the gate still fails until that code
  constant is changed in a reviewed commit).

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
        "sha256": validation.acceptance_digest(targets, species, history),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixtures-dir", type=Path, default=FIXTURES)
    parser.add_argument("--write", action="store_true", help="rewrite the pin file")
    parser.add_argument("--allow-count-change", action="store_true")
    args = parser.parse_args(argv)

    gate = validation.run_acceptance(args.fixtures_dir, check_pin=False)
    if not gate["validated"]:
        print(f"refusing: the gate fails without the pin: {gate['label']}", file=sys.stderr)
        return 1
    new = build(args.fixtures_dir)
    old = json.loads(PIN_PATH.read_text()) if PIN_PATH.exists() else {}
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
    if new == old:
        print("pin unchanged")
    elif args.write:
        PIN_PATH.write_text(json.dumps(new, indent=2) + "\n")
        print(f"wrote {PIN_PATH.relative_to(ROOT)}; the diff needs review")
    else:
        print("pin differs; rerun with --write to update it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
