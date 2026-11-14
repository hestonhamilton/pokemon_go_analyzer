"""The pin tool refuses to re-pin a failing gate, a changed count or a dropped discrepancy.

Every test points the tool at a temporary copy of the pin; the real pin is never written.
"""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from pogo_analyzer.sim.validation import DEFAULT_FIXTURES

TOOL = Path(__file__).resolve().parents[1] / "tools" / "fixtures" / "acceptance_pin.py"


@pytest.fixture
def tool():
    spec = importlib.util.spec_from_file_location("acceptance_pin", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pin(tool, tmp_path):
    copy = tmp_path / "acceptance_pin.json"
    shutil.copyfile(tool.PIN_PATH, copy)
    return copy


def fixtures(tmp_path, change):
    path = tmp_path / "fixtures"
    shutil.copytree(DEFAULT_FIXTURES, path)
    rows = json.loads((path / "battles.json").read_text())
    (path / "battles.json").write_text(json.dumps(change(rows)))
    return path


def test_unchanged_fixtures_report_an_unchanged_pin(tool, pin, capsys):
    assert tool.main(["--pin", str(pin)]) == 0
    assert "pin unchanged" in capsys.readouterr().out


def test_refuses_when_the_gate_fails(tool, pin, tmp_path, capsys):
    def break_one(rows):
        next(r for r in rows if r["id"] == "F1-metagross-hp")["observed"]["value"] += 1
        return rows

    before = pin.read_text()
    path = fixtures(tmp_path, break_one)
    assert tool.main(["--fixtures-dir", str(path), "--pin", str(pin), "--write"]) == 1
    assert "refusing: the gate fails" in capsys.readouterr().err
    assert pin.read_text() == before


def test_refuses_a_count_change_without_the_flag(tool, pin, tmp_path, capsys):
    def trim(rows):
        return [r for r in rows if r["id"] != "F2-cyndaquil-hp"]

    before = pin.read_text()
    path = fixtures(tmp_path, trim)
    assert tool.main(["--fixtures-dir", str(path), "--pin", str(pin), "--write"]) == 1
    captured = capsys.readouterr()
    assert "target_ids removed: F2-cyndaquil-hp" in captured.out
    assert "refusing: 43 targets, not 44" in captured.err
    assert pin.read_text() == before
    # With the flag it only reports (no --write): the gate still needs EXPECTED_TARGETS.
    assert tool.main(["--fixtures-dir", str(path), "--pin", str(pin), "--allow-count-change"]) == 0
    assert "pin differs" in capsys.readouterr().out


def test_refuses_to_drop_a_discrepancy_without_the_flag(tool, pin, tmp_path, capsys):
    def drop(rows):
        return [r for r in rows if r["id"] != "F3-metagross-remaining"]

    before = pin.read_text()
    path = fixtures(tmp_path, drop)
    assert tool.main(["--fixtures-dir", str(path), "--pin", str(pin), "--write"]) == 1
    assert (
        "refusing: open discrepancies removed (F3-metagross-remaining)" in capsys.readouterr().err
    )
    assert pin.read_text() == before
    flags = ["--allow-discrepancy-removal", "--write"]
    assert tool.main(["--fixtures-dir", str(path), "--pin", str(pin), *flags]) == 0
    assert json.loads(pin.read_text())["discrepancy_ids"] == ["F4-ducklett-shadow-tyranitar"]
