"""Print or write the acceptance pin for tests/fixtures/sim.

The pin (src/pogo_analyzer/sim/data/acceptance_pin.json) lists the reviewed
target IDs and a SHA-256 of what decides each target. The calculator's gate
fails if either differs. Regenerate it only together with a fixture review:

    uv run python tools/fixtures/acceptance_pin.py          # print
    uv run python tools/fixtures/acceptance_pin.py --write  # update the pin
"""

import json
import sys
from pathlib import Path

from pogo_analyzer.sim.validation import DEFAULT_FIXTURES, acceptance_digest

PIN_PATH = Path(__file__).resolve().parents[2] / "src/pogo_analyzer/sim/data/acceptance_pin.json"


def build(fixtures=DEFAULT_FIXTURES):
    battles = json.loads((fixtures / "battles.json").read_text())
    targets = [
        r
        for r in battles
        if r["basis"] in ("recorded", "measured") and r["status"] == "expected_pass"
    ]
    species = json.loads((fixtures / "species_moves.json").read_text())["species"]
    history = json.loads((fixtures / "move_history.json").read_text())
    return {
        "note": "Reviewed acceptance targets. Regenerate only with a fixture review.",
        "target_ids": sorted(r["id"] for r in targets),
        "sha256": acceptance_digest(targets, species, history),
    }


if __name__ == "__main__":
    pin = json.dumps(build(), indent=2) + "\n"
    if "--write" in sys.argv[1:]:
        PIN_PATH.write_text(pin)
    print(pin, end="")
