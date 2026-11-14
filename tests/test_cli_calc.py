"""Calculator CLI uses tiny cached source extracts and never counter services."""

import csv
import hashlib
import io
import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from pogo_analyzer import calc_cli, cli
from pogo_analyzer.lineups import EVENT_INFO_URL, PVPOKE_GM_URL
from pogo_analyzer.pokebattler import PoliteClient
from pogo_analyzer.sim.validation import DEFAULT_FIXTURES

FIXTURES = Path(__file__).parent / "fixtures" / "calc"
SOURCES = {EVENT_INFO_URL: "event-info.json", PVPOKE_GM_URL: "gamemaster.json"}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    client = PoliteClient(root / "sources")
    for url, name in SOURCES.items():
        client._write_cache(
            client.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json"),
            url,
            200,
            json.loads((FIXTURES / name).read_text()),
        )

    def blocked(*args, **kwargs):
        raise AssertionError("cached calculator must not attempt a request")

    monkeypatch.setattr(PoliteClient, "_request", blocked)
    return root


def args(cache, fmt="json"):
    return [
        "calc",
        "--character",
        "fai gru",
        "--trainer-level",
        "50",
        "--attacker",
        "Metagross",
        "--level",
        "43.5",
        "--ivs",
        "15/9/12",
        "--fast",
        "Bullet Punch",
        "--charged",
        "Meteor Mash",
        "--shadow",
        "--cache-dir",
        str(cache),
        "--format",
        fmt,
    ]


def copied_targets(
    tmp_path, *, drop_f2=False, broken=False, swap=False, edit=False, no_discrepancies=False
):
    path = tmp_path / "targets"
    shutil.copytree(DEFAULT_FIXTURES, path)
    rows = json.loads((path / "battles.json").read_text())
    if no_discrepancies:
        rows = [r for r in rows if r["status"] != "open_discrepancy"]
    if swap:
        # Same count: drop one target and add a copy of another under a new ID.
        rows = [r for r in rows if r["id"] != "F2-cyndaquil-hp"]
        rows.append(dict(next(r for r in rows if r["id"] == "F1-kirlia-hits"), id="F1-copy"))
    if edit:
        # Same IDs, a consistent change of input and observation: still passes
        # the arithmetic, but it is not the reviewed target.
        row = next(r for r in rows if r["id"] == "F1-metagross-hp")
        row["player"] = dict(row["player"], ivs=dict(row["player"]["ivs"], hp=13))
        row["observed"] = dict(row["observed"], value=163)
    if drop_f2:
        # A trimmed set (43 targets): must fail the pinned gate.
        rows = [r for r in rows if r["fixture"] != "F2"]
    if broken:
        next(r for r in rows if r["id"] == "F1-metagross-hp")["observed"]["value"] += 1
    (path / "battles.json").write_text(json.dumps(rows))
    return path


def test_json_grades_sources_and_default_gap(cache, capsys):
    assert cli.main(args(cache)) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["validation_label"].startswith("Validated against 44 pre-Oct-2025")
    assert "not covered: F2-cyndaquil-hp" in data["validation_label"]
    assert data["validation"]["target_count"] == 44
    assert len(data["validation"]["open_discrepancies"]) == 2
    assert data["rcpm_note"] == calc_cli.CP_ONLY
    assert "backed by CP readings only" in data["rcpm_note"]
    assert {s["url"] for s in data["sources"]} == set(SOURCES)
    assert all(s["fetched_at"] and s["license"] == "MIT" for s in data["sources"])
    results = data["results"]
    assert len(results) == 7  # 2 Snubbull fast moves in two slots + 3 Kirlia moves.
    assert [r["fast_turns_to_ko"]["value"] for r in results] == sorted(
        r["fast_turns_to_ko"]["value"] for r in results
    )
    row = results[0]
    # Today's Bullet Punch (power 7) differs from the dated snapshot (6) the
    # targets used, so its damage is parity-only, below dec-2025's cp-only.
    assert row["fast_move"]["grade"] == "parity-only"
    assert row["fast_damage"]["grade"] == "parity-only"
    assert row["rocket_hp"]["grade"] == "cp-only"
    assert row["attacker_hp"]["grade"] == "fixture-exact"
    assert row["defender"]["grade"] == "model"
    assert row["fast_turns_to_ko"]["grade"] == "model"
    assert row["row_grade"]["value"] == "model"
    assert row["charged"]["value"][0]["damage"]["grade"] == "parity-only"
    assert row["rocket_charged"]["value"][0]["damage"]["grade"] == "parity-only"
    assert row["moveset_pool"]["grade"] == "model"
    assert row["moveset_pool"]["value"]["frustration_included"] is False
    assert "No extra shadow Frustration" in data["moveset_pool_note"]
    for r in results:
        assert all(set(c) == {"value", "grade"} for c in r.values())


@pytest.mark.parametrize("fmt", ["table", "json", "csv"])
@pytest.mark.parametrize("state", ["pass", "missing", "broken"])
def test_validation_header_every_format(cache, capsys, tmp_path, fmt, state):
    if state == "missing":
        path = tmp_path / "absent"
    else:
        path = copied_targets(tmp_path, broken=state == "broken")
    assert cli.main(args(cache, fmt) + ["--fixtures-dir", str(path)]) == 0
    out = capsys.readouterr().out
    label = json.loads(out)["validation_label"] if fmt == "json" else out.splitlines()[0]
    if state == "pass":
        assert label.startswith("Validated against 44 pre-Oct-2025 battle targets under")
    else:
        assert label.startswith("UNVALIDATED:")
        expected = (
            "fixtures not found (missing battles.json, species_moves.json, move_history.json); "
            "validation needs a source checkout or --fixtures-dir"
            if state == "missing"
            else "1 target failed: F1-metagross-hp"
        )
        assert expected in label
        assert str(tmp_path) not in label  # No local path in the public label.
    assert "F3-metagross-remaining" in out or state == "missing"
    assert "F4-ducklett-shadow-tyranitar" in out or state == "missing"
    assert calc_cli.CP_ONLY in out


def test_old_table_and_csv_grades(cache, capsys):
    assert cli.main(args(cache, "csv") + ["--rcpm-table", "venonic-2023", "--slot", "1"]) == 0
    out = capsys.readouterr().out
    assert calc_cli.CP_ONLY not in out
    lines = out.splitlines()
    header_index = next(i for i, line in enumerate(lines) if line.startswith("attacker,"))
    header, grades, row = list(csv.reader(lines[header_index : header_index + 3]))
    assert len(header) == len(grades) == len(row)
    by_column = dict(zip(header, grades, strict=True))
    # venonic-2023 at TL50 is a level the targets used: Rocket stats are exact.
    assert by_column["rocket_hp"] == "fixture-exact"
    assert by_column["attacker_hp"] == "fixture-exact"
    # Today's Bullet Punch differs from the dated snapshot: damage is parity-only.
    assert by_column["fast_damage"] == "parity-only"
    assert by_column["fast_turns_to_ko"] == "model"
    assert by_column["charged"] == "model"


def test_team_rank_sort_and_two_charged(cache, capsys, tmp_path):
    team = tmp_path / "team.json"
    team.write_text(
        json.dumps(
            [
                {
                    "species": "metagross",
                    "level": 43.5,
                    "ivs": "15/9/12",
                    "fast": "BULLET_PUNCH",
                    "charged": ["METEOR_MASH", "PSYCHIC"],
                    "purified": True,
                },
                {
                    "species": "metagross",
                    "level": 50,
                    "ivs": {"atk": 15, "def": 15, "hp": 15},
                    "fast": "BULLET_PUNCH",
                    "charged": ["METEOR_MASH"],
                    "shadow": True,
                },
            ]
        )
    )
    assert (
        cli.main(
            [
                "calc",
                "--defender",
                "snubbull",
                "--rank",
                "giovanni",
                "--trainer-level",
                "50",
                "--team",
                str(team),
                "--cache-dir",
                str(cache),
                "--format",
                "json",
                "--rcpm-table",
                "venonic-2023",
                "--sort",
                "rocket_fast_damage",
            ]
        )
        == 0
    )
    rows = json.loads(capsys.readouterr().out)["results"]
    assert len(rows) == 4
    assert {r["form"]["value"] for r in rows} == {"purified", "shadow"}
    # Giovanni: cp-only at best; today's Bullet Punch lowers damage to parity-only.
    assert all(r["rocket_hp"]["grade"] == "cp-only" for r in rows)
    assert all(r["attacker_hp"]["grade"] == "cp-only" for r in rows)
    assert all(r["fast_damage"]["grade"] == "parity-only" for r in rows)
    assert all(r["character"]["value"] == "" for r in rows)
    assert all(r["rank_multiplier"]["value"] == 1.15 for r in rows)
    assert any(len(r["charged"]["value"]) == 2 for r in rows)
    assert [r["rocket_fast_damage"]["value"] for r in rows] == sorted(
        r["rocket_fast_damage"]["value"] for r in rows
    )


def test_pool_flags_preserved():
    p = calc_cli._pool(
        {
            "fastMoves": ["A"],
            "chargedMoves": ["B", "FRUSTRATION"],
            "eliteMoves": ["A"],
            "legacyMoves": ["B"],
        }
    )
    assert p["fast"] == [{"move": "A", "elite": True, "legacy": False}]
    assert p["charged"][0] == {"move": "B", "elite": False, "legacy": True}
    assert p["frustration_included"] is True


def test_uncached_fetch_only_two_raw_sources(tmp_path, monkeypatch, capsys):
    requested = []

    class Response(io.StringIO):
        status = 200

    def opener(request, **kwargs):
        url = request.full_url
        requested.append(url)
        assert urlsplit(url).netloc == "raw.githubusercontent.com"
        assert "pokebattler" not in url
        return Response((FIXTURES / SOURCES[url]).read_text())

    real_client = PoliteClient

    def source_client(*a, **kw):
        return real_client(*a, **kw, opener=opener)

    monkeypatch.setattr(calc_cli, "PoliteClient", source_client)
    assert cli.main(args(tmp_path / "empty")) == 0
    capsys.readouterr()
    assert requested == [EVENT_INFO_URL, PVPOKE_GM_URL]
    # Re-running uses the two source cache entries without any further requests.
    assert cli.main(args(tmp_path / "empty")) == 0
    capsys.readouterr()
    assert requested == [EVENT_INFO_URL, PVPOKE_GM_URL]


@pytest.mark.parametrize(
    "extra,expected",
    [
        (["--trainer-level", "47", "--rcpm-table", "venonic-2023"], "no trainer level 47"),
        (["--ivs", "16/15/15"], "IV must be 0–15"),
        (["--level", "20.25"], "half-level"),
        (["--fast", "PSYCHIC"], "invalid fast move"),
        (["--charged", "PSYCHIC", "--charged", "EARTHQUAKE"], "one or two charged"),
    ],
)
def test_bad_inputs_are_errors(cache, capsys, extra, expected):
    with pytest.raises(SystemExit) as exc:
        cli.main(args(cache) + extra)
    assert exc.value.code == 2
    assert expected in capsys.readouterr().err


def test_exact_move_identity_precedes_punctuation_matching():
    ordinary = {"moveId": "BRICK_BREAK", "name": "Brick Break"}
    special = {"moveId": "BRICK_BREAK_PLUS", "name": "Brick Break+"}
    for query in ("BRICK_BREAK", "Brick Break", "brick-break"):
        assert calc_cli._resolve(query, [ordinary, special], "moveId", "name") == ordinary
    assert calc_cli._resolve("Brick Break+", [ordinary, special], "moveId", "name") == special


def test_table_shows_headline_columns_with_a_grade_row(cache, capsys):
    assert cli.main(args(cache, "table")) == 0
    lines = capsys.readouterr().out.splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith("character "))
    fields = [f.strip() for f in lines[header].split("|")]
    assert fields == list(calc_cli.TABLE_FIELDS)
    grades = [g.strip() for g in lines[header + 1].split("|")]
    assert set(grades) <= {"fixture-exact", "cp-only", "parity-only", "model"}
    assert grades[fields.index("rocket_hp")] == "cp-only"  # dec-2025 default
    assert grades[fields.index("fast_damage")] == "parity-only"  # today's Bullet Punch
    out = "\n".join(lines)
    for column in calc_cli.TABLE_FIELDS:
        assert f"{column}: " in out
        assert calc_cli.COLUMN_MEANINGS[column] in out


def test_csv_legend_has_every_column_meaning(cache, capsys):
    assert cli.main(args(cache, "csv")) == 0
    err = capsys.readouterr().err
    for column, meaning in calc_cli.COLUMN_MEANINGS.items():
        assert f"{column}: " in err
        assert meaning in err


def test_alola_template_alias_only():
    species = [{"speciesId": "vulpix_alolan"}, {"speciesId": "vulpix"}]
    assert calc_cli._rocket_species("vulpix_alola", species) == species[0]
    assert calc_cli._rocket_species("vulpix", species) == species[1]
    with pytest.raises(ValueError):
        calc_cli._rocket_species("vulpix_galar", species)


def test_unresolved_lineup_species_is_reported(cache, capsys):
    url = EVENT_INFO_URL
    path = cache / "sources" / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    entry = json.loads(path.read_text())
    entry["body"]["14"]["encounters"]["third"] = [{"id": 9999}]
    path.write_text(json.dumps(entry))
    assert cli.main(args(cache, "table")) == 0
    out = capsys.readouterr().out
    assert "NOT CALCULATED Fairy grunt (female) slot 3: dex_9999 is not in PvPoke" in out
    assert cli.main(args(cache)) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["unresolved"] == [
        {"character": "Fairy grunt (female)", "slot": 3, "species": "dex_9999"}
    ]


def _grades(data):
    return {
        cell["grade"]
        for row in data["results"]
        for cell in row.values()
        if isinstance(cell, dict) and "grade" in cell
    }


@pytest.mark.parametrize(
    "state", ["missing", "broken", "trimmed", "swapped", "edited", "no_discrepancies"]
)
def test_failed_gate_leaves_no_fixture_exact_cell(cache, capsys, tmp_path, state):
    if state == "missing":
        path = tmp_path / "absent"
    else:
        path = copied_targets(
            tmp_path,
            drop_f2=state == "trimmed",
            broken=state == "broken",
            swap=state == "swapped",
            edit=state == "edited",
            no_discrepancies=state == "no_discrepancies",
        )
    extra = ["--rcpm-table", "venonic-2023", "--fixtures-dir", str(path)]
    assert cli.main(args(cache) + extra) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["validation_label"].startswith("UNVALIDATED:")
    label = data["validation_label"]
    if state == "trimmed":
        assert "expected the 44 reviewed acceptance targets, found 43" in label
        assert "missing F2-cyndaquil-hp" in label
    if state == "swapped":
        assert "found 44 (missing F2-cyndaquil-hp; unexpected F1-copy)" in label
    if state == "edited":
        assert "differ from the reviewed set" in label
    if state == "no_discrepancies":
        assert "open discrepancies differ from the reviewed set (missing F3-" in label
        assert "0 open discrepancies" not in label
    assert "fixture-exact" not in _grades(data)
    # The same run with the real fixtures does show fixture-exact cells.
    assert cli.main(args(cache) + ["--rcpm-table", "venonic-2023"]) == 0
    assert "fixture-exact" in _grades(json.loads(capsys.readouterr().out))


def test_uncovered_trainer_level_is_not_fixture_exact(cache, capsys):
    assert cli.main(args(cache) + ["--rcpm-table", "fugerappi-2023", "--trainer-level", "20"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["validation_label"].startswith("Validated")
    assert {r["rocket_hp"]["grade"] for r in data["results"]} == {"cp-only"}


def test_explicit_defender_rows_and_shadow_ids(cache, capsys):
    base = args(cache, "table")
    i = base.index("--character")
    defender = [*base[:i], "--defender", "snubbull", "--rank", "grunt", *base[i + 2 :]]
    assert cli.main(defender) == 0
    out = capsys.readouterr().out
    assert "None" not in out
    # Same rule as attackers: PvPoke _shadow and _mega entries are refused.
    for species_id in ("zekrom_shadow", "gengar_mega"):
        with pytest.raises(ValueError, match="use the base species"):
            calc_cli._check_rocket_species({"speciesId": species_id})
    calc_cli._check_rocket_species({"speciesId": "snubbull"})


@pytest.mark.parametrize(
    "option,value,message",
    [
        ("--ivs", "a/b/c", "three whole numbers"),
        ("--charged", "Meteor Mash", "must differ"),
    ],
)
def test_clean_input_errors(cache, capsys, option, value, message):
    argv = args(cache)
    if option == "--ivs":
        argv[argv.index("--ivs") + 1] = value
    else:
        argv += [option, value]
    with pytest.raises(SystemExit):
        cli.main(argv)
    assert message in capsys.readouterr().err


def test_missing_fixture_file_is_named(cache, capsys, tmp_path):
    path = copied_targets(tmp_path)
    (path / "move_history.json").unlink()
    assert cli.main(args(cache) + ["--fixtures-dir", str(path)]) == 0
    label = json.loads(capsys.readouterr().out)["validation_label"]
    assert label.startswith("UNVALIDATED: fixtures not found (missing move_history.json);")
    assert str(tmp_path) not in label


def test_unreadable_fixture_names_the_file_not_the_path(cache, capsys, tmp_path, monkeypatch):
    path = copied_targets(tmp_path)
    original = Path.read_text

    def read_text(self, *args, **kwargs):
        if self.name == "move_history.json":
            raise PermissionError(13, "Permission denied", str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    assert cli.main(args(cache) + ["--fixtures-dir", str(path)]) == 0
    label = json.loads(capsys.readouterr().out)["validation_label"]
    assert "fixtures invalid: cannot read move_history.json: PermissionError" in label
    assert str(tmp_path) not in label
