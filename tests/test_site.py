"""Offline static-site contract and a deliberately refreshed landing-page golden."""

import json
import os
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path

import pytest
from test_precompute import cache as cache
from test_precompute import characters as characters
from test_precompute import priority as priority
from test_precompute import run

from pogo_analyzer import cli, site

GOLDEN = Path(__file__).parent / "fixtures" / "site" / "expected_index.html"
FETCHED = "2026-11-14T00:00:00+00:00"


@pytest.fixture
def reports(characters, tmp_path):
    root = tmp_path / "reports"
    run(characters, root, "--level", "50")
    # Source fetch times are provenance; freeze them for a reproducible golden.
    for path in root.rglob("*.json"):
        data = json.loads(path.read_text())
        for source in data.get("sources", []):
            source["fetched_at"] = FETCHED
        path.write_text(json.dumps(data))
    return root


def read(root, relative):
    return json.loads((root / relative).read_text())


def change(root, relative, callback):
    data = read(root, relative)
    callback(data)
    (root / relative).write_text(json.dumps(data))


def build(root, out):
    assert cli.main(["site", "--data", str(root), "--out", str(out)]) == 0
    return {str(p.relative_to(out)): p.read_text() for p in out.rglob("*.html")}


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_pages_labels_resources_and_rerun(reports, tmp_path):
    manifest = read(reports, "manifest.json")
    pages = build(reports, tmp_path / "site")
    expected = {"index.html", "list/all.html", "list/grunts.html", "list/leaders.html"}
    for entry in manifest["characters"]:
        expected.update(f"{kind}/{entry['slug']}.html" for kind in ("list", "counters"))
    assert pages.keys() == expected
    assert build(reports, tmp_path / "site") == pages
    overall = read(reports, "overall.json")
    # Check every page, including both unavailable page types, rather than one sample.
    for path, html in pages.items():
        for label in (
            "every number is an estimate",
            escape(overall["validation_label"]),
            escape(overall["rcpm_note"]),
            escape(overall["moveset_pool_note"]),
            escape(overall["weighting_note"]),
            escape(overall["credits"]),
            "open discrepancies:",
            "battle_date_source: explicit",
            "valid_for era:",
            "2026-11-14",
            escape(overall["era"]),
            "extrapolated forward",
            "2019-07-22",
            "IVs 15/15/15",
            "trainer level 50",
            "Mega excluded",
            "elite/legacy included and badged",
            "uses charged moves when ready",
            "shields the first two charged attacks",
            escape(site.PAUSE_NOTE),
            escape(overall["limitations"]),
        ):
            assert label in html, (path, label)
        for discrepancy in overall["validation"]["open_discrepancies"]:
            assert escape(discrepancy["id"]) in html
        for source in overall["sources"]:
            assert escape(source["name"]) in html
            assert escape(source["url"]) in html
            assert f"fetched_at {FETCHED}" in html
        for tag, attrs in Elements(html).elements:
            for key in ("src", "href"):
                assert not re.search(r"https?://", attrs.get(key, ""), re.I), (path, tag)
        assert not re.search(r"url\s*\(\s*['\"]?https?://", html, re.I)
        if path.startswith("counters/"):
            assert "<script>" not in html  # Native details never need script.
        if path.startswith(("list/", "counters/")):
            if path in ("list/all.html", "list/grunts.html", "list/leaders.html"):
                assert "pause band not computed for the overall list" in html
            else:
                assert "pause-sensitive: the win rate moves more than" in html
                assert "threshold is a model choice" in html
    for entry in manifest["characters"]:
        data = read(reports, entry["file"])
        if data["character"].get("reason"):
            for path in (
                "index.html",
                f"list/{entry['slug']}.html",
                f"counters/{entry['slug']}.html",
            ):
                assert "not calculated" in pages[path]
                assert escape(data["character"]["reason"]) in pages[path]
        else:
            for rows in data["character"]["finalists"].values():
                for row in rows:
                    for path in (
                        "index.html",
                        f"list/{entry['slug']}.html",
                        f"counters/{entry['slug']}.html",
                    ):
                        for part in row["grade"].split("; "):
                            assert escape(part) in pages[path]
                    detail = pages[f"counters/{entry['slug']}.html"]
                    assert '<details class="counter">' in detail
                    assert escape(row["screen"]["grid_limitation"]) in detail
                    for part in row["screen"]["grade"].split("; "):
                        assert escape(part) in detail
                    assert "data-calc-summary" in detail
    assert 'data-filter="steel"' in pages["list/all.html"]
    assert "types not recorded" not in pages["list/all.html"]
    assert "not recorded" not in pages["list/all.html"]


def test_index_golden(reports, tmp_path):
    html = build(reports, tmp_path / "site")["index.html"]
    # Deliberate update command is documented in README's site section.
    if os.environ.get("POGO_UPDATE_SITE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(html)
    assert html == GOLDEN.read_text()


def test_hostile_data_is_escaped(reports, tmp_path):
    hostile = '<script>alert("x")</script>'
    manifest = read(reports, "manifest.json")
    entry = manifest["characters"][0]

    def mutate(data):
        data["credits"] = hostile
        data["sources"][0]["url"] = hostile
        for rows in data["character"]["finalists"].values():
            for row in rows:
                row["speciesId"] = hostile
                row["types"] = [hostile]
                row["fast_move"] = hostile
                row["screen"]["grid_limitation"] = hostile
                row["calc_rows"][0]["defender"]["value"] = hostile
                row["pause_band"]["note"] = hostile
                row["pause_band"]["turns"] = [hostile, hostile]

    change(reports, entry["file"], mutate)
    pages = build(reports, tmp_path / "site")
    for path in ("index.html", f"list/{entry['slug']}.html", f"counters/{entry['slug']}.html"):
        assert hostile not in pages[path]
        assert escape(hostile) in pages[path]


def test_unvalidated_and_discrepancies_are_data_driven(reports, tmp_path):
    def mutate(data):
        data["validation_label"] = "UNVALIDATED: gate failed; X9 is open"
        data["validation"]["validated"] = False
        data["validation"]["open_discrepancies"] = [{"id": "X9"}]

    for path in [
        "overall.json",
        *(e["file"] for e in read(reports, "manifest.json")["characters"]),
    ]:
        change(reports, path, mutate)
    for html in build(reports, tmp_path / "site").values():
        assert ">UNVALIDATED</span>" in html
        assert "UNVALIDATED: gate failed; X9 is open" in html
        assert "open discrepancies: X9" in html
        assert "open discrepancies: F3" not in html


@pytest.mark.parametrize("mode", ["key", "missing", "hidden", "name"])
def test_stale_character_never_publishes_rows(reports, tmp_path, mode):
    manifest = read(reports, "manifest.json")
    entry = manifest["characters"][0]
    if mode == "key":
        change(reports, entry["file"], lambda d: d.update(key="wrong"))
    elif mode == "missing":
        (reports / entry["file"]).unlink()
    elif mode == "hidden":
        change(reports, "manifest.json", lambda d: d["characters"][0].update(file=".temp.json"))
        (reports / ".temp.json").write_text("not JSON: must not be read")
    else:
        change(reports, entry["file"], lambda d: d["character"].update(name="Wrong name"))
    pages = build(reports, tmp_path / "site")
    html = pages[f"counters/{entry['slug']}.html"]
    assert "not calculated" in html
    assert '<details class="counter">' not in html
    assert "not calculated" in pages[f"list/{entry['slug']}.html"]


@pytest.mark.parametrize("mode", ["key", "status"])
def test_stale_overall_is_visible(reports, tmp_path, mode):
    if mode == "key":
        change(reports, "overall.json", lambda d: d.update(key="wrong"))
    else:
        change(reports, "manifest.json", lambda d: d["overall"].update(status="stale"))
    pages = build(reports, tmp_path / "site")
    for path in ("index.html", "list/all.html", "list/grunts.html", "list/leaders.html"):
        assert "stale report:" in pages[path]
        assert "not calculated" in pages[path]
    assert "data-win=" not in pages["list/all.html"]


def test_per_file_dates_and_ignored_orphans(reports, tmp_path):
    manifest = read(reports, "manifest.json")
    entry = manifest["characters"][0]
    change(
        reports,
        entry["file"],
        lambda d: d.update(
            computed_for_battle_date="2026-10-01",
            computed_for_battle_date_source="default: run date",
            valid_for={"era": "file-specific-era", "extrapolated": True},
        ),
    )
    for path in (".lock", ".tmp.json", "characters/.partial.json", "characters/orphan.json"):
        (reports / path).write_text("not JSON: must not be read")
    pages = build(reports, tmp_path / "site")
    for path in ("index.html", f"list/{entry['slug']}.html", f"counters/{entry['slug']}.html"):
        assert "Computed for battle date 2026-10-01" in pages[path]
        assert "battle_date_source: default: run date" in pages[path]
        assert "valid_for era: file-specific-era" in pages[path]


def test_calc_ranges_have_weakest_column_grades_and_one_row_per_species():
    def row(damage, grade, incoming):
        return {
            "slot": {"value": 1},
            "defender": {"value": "target"},
            "fast_damage": {"value": damage, "grade": grade},
            "fast_hits_to_ko": {"value": 3, "grade": "cp-only"},
            "charged": {
                "value": [
                    {"damage": {"value": 8, "grade": "parity-only"}},
                    {"damage": {"value": 9, "grade": "parity-only"}},
                ]
            },
            "rocket_fast_damage": {"value": incoming, "grade": "cp-only"},
            "turns_survived": {"value": 12, "grade": "model"},
        }

    html = site.calc_summary(
        [row(2, "fixture-exact", 4), row(6, "parity-only", 7)],
        ["fixture-exact", "cp-only", "parity-only", "model"],
    )
    assert html.count("data-calc-summary") == 1
    assert f"{site.estimate(2)}–{site.estimate(6)}<br>{site.chip('parity-only')}" in html
    assert f"{site.estimate(4)}–{site.estimate(7)}<br>{site.chip('cp-only')}" in html
    # Equal ends collapse to one value.
    assert f"{site.estimate(9)}–{site.estimate(9)}" not in html
    assert f"{site.estimate(9)}<br>" in html
    assert site.chip("model") in html
    assert html.count('title="estimate"') == 7  # 2 ranges x 2 ends + 3 single values


@pytest.mark.parametrize("target", ["manifest.json", "overall.json", "character"])
def test_pre_rocket_dates_rejected(reports, tmp_path, target):
    if target == "character":
        target = read(reports, "manifest.json")["characters"][0]["file"]
    change(reports, target, lambda d: d.update(computed_for_battle_date="2019-07-21"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["site", "--data", str(reports), "--out", str(tmp_path / "site")])
    assert exc.value.code == 2
    assert not list((tmp_path / "site").rglob("*.html"))


def test_output_symlink_cannot_escape(reports, tmp_path):
    out, outside = tmp_path / "site", tmp_path / "outside"
    out.mkdir()
    outside.mkdir()
    (out / "list").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside --out"):
        site.build_site(reports, out)
    assert not list(outside.iterdir())


@pytest.mark.parametrize("existing", [True, False])
def test_atomic_failure_cleans_temp_and_preserves_target(tmp_path, monkeypatch, existing):
    target = tmp_path / "index.html"
    if existing:
        target.write_text("complete old page")

    def fail(*args):
        raise OSError("injected replace failure")

    monkeypatch.setattr(site.os, "replace", fail)
    with pytest.raises(OSError, match="injected"):
        site.atomic_text(target, "new page")
    assert list(tmp_path.iterdir()) == ([target] if existing else [])
    if existing:
        assert target.read_text() == "complete old page"


def test_estimate_marks_cover_all_rendered_simulator_numbers(reports, tmp_path):
    manifest = read(reports, "manifest.json")
    pages = build(reports, tmp_path / "site")
    numeric = (
        ("win_rate", True),
        ("draw_rate", True),
        ("mean_rocket_knocked_out", False),
        ("lead_sweep_probability", True),
        ("mean_player_hp_fraction_left", True),
        ("mean_turns", False),
    )
    for entry in manifest["characters"]:
        data = read(reports, entry["file"])
        html = pages[f"counters/{entry['slug']}.html"]
        rows = [r for rows in data["character"]["finalists"].values() for r in rows]
        expected_summary_rows = 0
        for row in rows:
            for key, percent in numeric:
                assert site.estimate(row[key], percent=percent) in html
            for rate in row["screen"]["slot_win_rates"]:
                assert site.estimate(rate, percent=True) in html
            for slot in row["per_slot"]:
                for species in slot["species"]:
                    assert site.estimate(species["conditional_win_rate"], percent=True) in html
            expected_summary_rows += len(
                {(r["slot"]["value"], r["defender"]["value"]) for r in row["calc_rows"]}
            )
        assert html.count("data-calc-summary") == expected_summary_rows
        # Every numeric table cell is a simulator value; each one carries its own mark.
        for cell in re.findall(r'<td class="num">(.*?)</td>', html, re.S):
            assert 'title="estimate"' in cell
    for path, html in pages.items():
        if path.startswith("list/"):
            for cell in re.findall(r'<td class="num">(.*?)</td>', html, re.S):
                assert 'title="estimate"' in cell or "not recorded" in cell


def test_move_badges_shadow_and_excluded_filter(reports, tmp_path):
    entry = read(reports, "manifest.json")["characters"][0]

    def mutate(data):
        data["exclude_elite_legacy"] = True
        data["filter_note"] = "fixture: elite and legacy excluded by request"

    change(reports, entry["file"], mutate)
    pages = build(reports, tmp_path / "site")
    for path in ("index.html", f"list/{entry['slug']}.html", f"counters/{entry['slug']}.html"):
        assert "elite/legacy excluded" in pages[path]
        assert "fixture: elite and legacy excluded by request" in pages[path]
    marked = site.counter_name(
        {
            "speciesId": "example",
            "form": "shadow",
            "fast_move": "A",
            "charged_move": "B",
            "move_flags": {"A": {"elite": True}, "B": {"legacy": True}},
        }
    )
    for label in ("shadow", "elite", "legacy"):
        assert site.chip(label) in marked


def test_old_reports_without_types_or_overall_kos_are_explicit(reports, tmp_path):
    def mutate(data):
        for view in ("all", "grunts", "leaders"):
            for rows in data[view]["results"].values():
                for row in rows:
                    row.pop("types", None)
                    row.pop("mean_rocket_knocked_out", None)

    change(reports, "overall.json", mutate)
    html = build(reports, tmp_path / "site")["list/all.html"]
    assert "types not recorded" in html
    assert '<td class="num"><span class="moves">not recorded</span></td>' in html


def test_pause_band_range_chip_and_old_reports(reports, tmp_path):
    entry = read(reports, "manifest.json")["characters"][0]

    def mutate(data):
        for rows in data["character"]["finalists"].values():
            for row in rows:
                row["win_rate"] = 0.97
                row["pause_band"].update(min=0.80, max=1.0, sensitive=True)

    change(reports, entry["file"], mutate)
    pages = build(reports, tmp_path / "site")
    paths = [f"list/{entry['slug']}.html", f"counters/{entry['slug']}.html"]
    for path in paths:
        html = pages[path]
        assert site.estimate(0.97, percent=True) in html
        assert "(6–8 turns:" in html
        assert site.estimate(0.80, percent=True) in html
        assert site.estimate(1.0, percent=True) in html
        assert site.chip("pause-sensitive", "warn") in html
        assert "threshold is a model choice" in html
        assert "moves more than 0.15 between" in html
        assert "verification ledger row k" in html

    def remove(data):
        for rows in data["character"]["finalists"].values():
            for row in rows:
                row.pop("pause_band")

    change(reports, entry["file"], remove)
    pages = build(reports, tmp_path / "old-site")
    for path in paths:
        assert "band not computed" in pages[path]
        assert site.chip("pause-sensitive", "warn") not in pages[path]


def test_single_character_precompute_without_overall(reports, tmp_path):
    change(
        reports,
        "manifest.json",
        lambda d: d.update(
            characters=d["characters"][:1],
            overall={"file": None, "key": None, "status": "unavailable"},
        ),
    )
    (reports / "overall.json").unlink()
    pages = build(reports, tmp_path / "site")
    assert len(pages) == 6
    assert "report file unavailable" in pages["list/all.html"]
    assert "every number is an estimate" in pages["index.html"]
    assert "Computed for battle date not recorded" in pages["list/all.html"]
    assert escape(read(reports, "manifest.json")["validation_label"]) in pages["index.html"]
