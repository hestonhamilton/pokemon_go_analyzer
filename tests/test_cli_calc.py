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


def copied_targets(tmp_path, *, drop_f2=False, broken=False):
    path = tmp_path / "targets"
    shutil.copytree(DEFAULT_FIXTURES, path)
    rows = json.loads((path / "battles.json").read_text())
    if drop_f2:
        # The success branch uses a deliberately smaller, fully evaluable set.
        # Production fixtures keep F2 and must report the missing TL41 coverage.
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
    assert row["fast_damage"]["grade"] == "cp-only"
    assert row["attacker_hp"]["grade"] == "fixture-exact"
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
        path = copied_targets(tmp_path, drop_f2=True, broken=state == "broken")
    assert cli.main(args(cache, fmt) + ["--fixtures-dir", str(path)]) == 0
    out = capsys.readouterr().out
    label = json.loads(out)["validation_label"] if fmt == "json" else out.splitlines()[0]
    if state == "pass":
        assert label.startswith("Validated against 43 pre-Oct-2025 battle targets under")
    else:
        assert label.startswith("UNVALIDATED:")
        assert ("fixtures unavailable" if state == "missing" else "3 target failures") in label
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
    assert by_column["fast_damage"] == "fixture-exact"
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
    assert all(r["fast_damage"]["grade"] == "cp-only" for r in rows)
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
    assert grades[fields.index("fast_damage")] == "cp-only"  # dec-2025 default
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
