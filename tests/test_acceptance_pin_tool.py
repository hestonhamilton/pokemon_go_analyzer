"""The pin tool refuses to re-pin a failing gate or a changed count."""

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


def fixtures(tmp_path, change):
    path = tmp_path / "fixtures"
    shutil.copytree(DEFAULT_FIXTURES, path)
    rows = json.loads((path / "battles.json").read_text())
    (path / "battles.json").write_text(json.dumps(change(rows)))
    return path


def test_unchanged_fixtures_report_an_unchanged_pin(tool, capsys):
    assert tool.main([]) == 0
    assert "pin unchanged" in capsys.readouterr().out


def test_refuses_when_the_gate_fails(tool, tmp_path, capsys):
    def break_one(rows):
        next(r for r in rows if r["id"] == "F1-metagross-hp")["observed"]["value"] += 1
        return rows

    pin_before = tool.PIN_PATH.read_text()
    assert tool.main(["--fixtures-dir", str(fixtures(tmp_path, break_one)), "--write"]) == 1
    assert "refusing: the gate fails" in capsys.readouterr().err
    assert tool.PIN_PATH.read_text() == pin_before


def test_refuses_a_count_change_without_the_flag(tool, tmp_path, capsys):
    def trim(rows):
        return [r for r in rows if r["id"] != "F2-cyndaquil-hp"]

    pin_before = tool.PIN_PATH.read_text()
    path = fixtures(tmp_path, trim)
    assert tool.main(["--fixtures-dir", str(path), "--write"]) == 1
    captured = capsys.readouterr()
    assert "target_ids removed: F2-cyndaquil-hp" in captured.out
    assert "refusing: 43 targets, not 44" in captured.err
    assert tool.PIN_PATH.read_text() == pin_before
    # With the flag it only reports (no --write): the gate still needs EXPECTED_TARGETS.
    assert tool.main(["--fixtures-dir", str(path), "--allow-count-change"]) == 0
    assert "pin differs" in capsys.readouterr().out
