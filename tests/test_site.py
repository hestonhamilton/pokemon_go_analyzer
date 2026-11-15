"""Offline static-site contract and a deliberately refreshed landing-page golden."""

import json
import os
import re
import shutil
import subprocess
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
            "levels 40/50 (per section)",
            "trainer level 50",
            "Mega excluded",
            "elite/legacy included and badged",
            "uses charged moves when ready",
            "shields the first two charged attacks",
            escape(site.PAUSE_NOTE),
            escape(overall["limitations"]),
        ):
            assert label in html, (path, label)
        footers = re.findall(r'<footer class="notes">(.*?)</footer>', html, re.S)
        assert footers
        view = path.removeprefix("list/").removesuffix(".html")
        coverage_view = view if view in ("all", "grunts", "leaders") else "all"
        for footer in footers:
            assert escape(overall[coverage_view]["coverage"]["text"]) in footer, path
        if path.startswith(("list/", "counters/")):
            for level in (40, 50):
                assert f"You: level {level} · IVs" in html
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
                    assert '<span class="sr-only">Grade: </span>' in detail
    for view in ("all", "grunts", "leaders"):
        for rows in overall[view]["results"].values():
            for row in rows:
                assert site.grades(row["grade"], row.get("flags", [])) in pages[f"list/{view}.html"]
    controls = [
        attrs
        for tag, attrs in Elements(pages["list/all.html"]).elements
        if tag == "div" and attrs.get("class") == "controls"
    ]
    assert controls and all("hidden" in attrs for attrs in controls)
    assert "<noscript>" in pages["list/all.html"]
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
        data["limitations"] = hostile
        data["character"]["name"] = hostile
        data["sources"][0]["url"] = hostile
        for rows in data["character"]["finalists"].values():
            for row in rows:
                row["speciesId"] = hostile
                row["types"] = [hostile]
                row["fast_move"] = hostile
                row["charged_move"] = hostile
                row["screen"]["note"] = hostile
                row["screen"]["grid_limitation"] = hostile
                row["calc_rows"][0]["defender"]["value"] = hostile

    change(reports, entry["file"], mutate)
    change(reports, "manifest.json", lambda d: d["characters"][0].update(name=hostile))
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


@pytest.mark.parametrize(
    "mode", ["key", "missing", "hidden", "name", "file_key", "manifest_key", "both_keys"]
)
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
    elif mode in ("file_key", "manifest_key", "both_keys"):
        if mode in ("file_key", "both_keys"):
            change(reports, entry["file"], lambda d: d.pop("key"))
        if mode in ("manifest_key", "both_keys"):
            change(reports, "manifest.json", lambda d: d["characters"][0].pop("key"))
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
    for html in pages.values():
        for footer in re.findall(r'<footer class="notes">(.*?)</footer>', html, re.S):
            assert "coverage not recorded" in footer


def test_page_metadata_skips_stale_first_character(reports, tmp_path):
    entries = read(reports, "manifest.json")["characters"]
    change(reports, "manifest.json", lambda d: d.update(overall={}))
    change(
        reports,
        entries[0]["file"],
        lambda d: d.update(key="stale", validation_label="OLD STALE LABEL"),
    )
    change(reports, entries[1]["file"], lambda d: d.update(validation_label="CURRENT LABEL"))
    pages = build(reports, tmp_path / "site")
    for path in ("list/all.html", "list/grunts.html", "list/leaders.html"):
        assert "OLD STALE LABEL" not in pages[path]
        assert "CURRENT LABEL" in pages[path]
    # Index tile metadata remains file specific; only the page-wide strip uses fallback.
    assert "CURRENT LABEL" in pages["index.html"].split('<div class="tiles">')[0]


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "0.0%"),
        (1, "100.0%"),
        (0.9995, ">99.9%"),
        (0.9996, ">99.9%"),
        (0.9994, "99.9%"),
        (0.0004, "<0.1%"),
        (0.00049, "<0.1%"),
        (0.0006, "0.1%"),
    ],
)
def test_percentage_edges_in_estimates_and_percent_of_best(value, expected):
    assert site.percentage(value) == expected
    assert site.estimate(value, percent=True).startswith(escape(expected) + "<span")
    html = site.list_body({}, {"40": [{"win_rate": 1}, {"win_rate": value}]}, "")
    assert f"<span data-best>{escape(expected)}</span>" in html


@pytest.mark.parametrize(
    "value,expected",
    [
        (2.996, "2.99"),
        (2.9999, "2.99"),
        (2.995, "2.99"),
        (2.001, "2.00"),
        (2.5, "2.50"),
        (3, "3"),
        (0, "0"),
    ],
)
def test_noninteger_counts_keep_decimals_without_rounding_up_to_integer(value, expected):
    assert site.estimate(value).startswith(expected + "<span")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable for inline JS check")
def test_filter_js_percentage_edges_and_progressive_controls():
    values = [0, 1, 0.9995, 0.9996, 0.9994, 0.0004, 0.00049, 0.0006]
    # Run the actual inline handlers against a minimal DOM, without browser dependencies.
    harness = """
const values=VALUES;
const rows=values.map(v=>({dataset:{win:String(v),types:'[]'},hidden:false,
rank:{textContent:''},best:{textContent:''},
querySelector(s){return s==='[data-rank]'?this.rank:this.best;}}));
rows.unshift({ ...rows[1],rank:{textContent:''},best:{textContent:''} });
const controls={hidden:true};
const warning={hidden:false};
const section={querySelector(){return warning;},
querySelectorAll(s){return s==='[data-filter]'?[button]:rows;}};
const button={dataset:{filter:''},closest(){return section;},setAttribute(){}};
globalThis.document={querySelectorAll(s){return s==='.controls'?[controls]:[button];}};
SCRIPT
button.onclick();
console.log(JSON.stringify({hidden:controls.hidden,best:rows.slice(1).map(r=>r.best.textContent)}));
""".replace("VALUES", json.dumps(values)).replace("SCRIPT", site.FILTER_JS)
    result = subprocess.run(["node", "-e", harness], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == {
        "hidden": False,
        "best": ["0.0%", "100.0%", ">99.9%", ">99.9%", "99.9%", "<0.1%", "<0.1%", "0.1%"],
    }


@pytest.mark.parametrize("recorded", [True, False])
def test_conditional_denominators_and_headline_grades(recorded):
    species = {"species": "target", "conditional_win_rate": 1}
    if recorded:
        species["battles"] = 17
    row = {
        "grade": "estimate; pool incomplete",
        "flags": ["extrapolated"],
        "battles": 999,
        "per_slot": [{"slot": 1, "species": [species]}],
    }
    html = site.counter_detail(row, {})
    assert "<th>n</th>" in html
    assert f"<td>{17 if recorded else 'n not recorded'}</td>" in html
    assert "999" not in html
    caption = re.search(r"<caption>(.*?)</caption>", html).group(1)
    assert site.grades(row["grade"], row["flags"]) in caption


def test_missing_row_grade_is_a_warning():
    warning = site.chip("grade not recorded", "warn")
    assert site.grades(None) == warning
    assert warning in site.grades(None, ["extrapolated"])
    row = {"win_rate": 0.5}
    assert warning in site.list_body({}, {"40": [row]}, "")
    assert warning in site.counters_body({}, {"40": [row]}, "")
    assert warning in site.tile("Example", "list/example.html", {}, {"40": [row]}, "")


@pytest.mark.parametrize("validated", [None, False, 0, 1, "true", True])
def test_unvalidated_requires_literal_true(validated):
    data = {"validation": {"validated": validated}}
    assert (site.chip("UNVALIDATED", "warn") in site.trust(data, "40")) is (validated is not True)
    assert site.chip("UNVALIDATED", "warn") in site.trust({"validation": {}}, "40")
    assert site.chip("UNVALIDATED", "warn") in site.trust({}, "40")


@pytest.mark.parametrize("label", [None, 17, [], {}])
def test_nonstring_validation_label_has_clean_cli_error(reports, tmp_path, capsys, label):
    change(reports, "overall.json", lambda d: d.update(validation_label=label))
    out = tmp_path / "site"
    with pytest.raises(SystemExit) as exc:
        cli.main(["site", "--data", str(reports), "--out", str(out)])
    assert exc.value.code == 2
    stderr = capsys.readouterr().err
    assert "validation_label must be a string" in stderr
    assert "Traceback" not in stderr
    assert not out.exists()


@pytest.mark.parametrize("grade_order", [[], ["fixture-exact"]])
def test_calc_unknown_grades_show_all_distinct_grades_sorted(grade_order):
    rows = []
    for grade in ("z-unknown", "fixture-exact", "a-unknown", "z-unknown"):
        row = {"slot": {"value": 1}, "defender": {"value": "target"}, "charged": {"value": []}}
        for key in ("fast_damage", "fast_hits_to_ko", "rocket_fast_damage", "turns_survived"):
            row[key] = {"value": 5, "grade": grade}
        rows.append(row)
    html = site.calc_summary(rows, grade_order)
    expected = " ".join(site.chip(g) for g in ("a-unknown", "fixture-exact", "z-unknown"))
    assert html.count(expected) == 4
    assert site.calc_summary(list(reversed(rows)), grade_order) == html


@pytest.mark.parametrize("best,warn", [(0.04, True), (0, True), (0.5, False), (1, False)])
def test_list_warns_when_best_counter_loses_most_battles(best, warn):
    html = site.list_body({}, {"40": [{"win_rate": best}]}, "")
    assert site.chip("best counter loses most battles", "warn") in html
    warning = next(attrs for tag, attrs in Elements(html).elements if "data-best-warning" in attrs)
    assert ("hidden" not in warning) is warn


def test_rebuild_prunes_removed_characters_and_cleans_staging(reports, tmp_path):
    out = tmp_path / "site"
    before = build(reports, out)
    removed = read(reports, "manifest.json")["characters"][0]
    change(reports, "manifest.json", lambda d: d.update(characters=d["characters"][1:]))
    after = build(reports, out)
    for kind in ("list", "counters"):
        path = f"{kind}/{removed['slug']}.html"
        assert path in before and path not in after
        assert not (out / path).exists()
    assert (out / ".pogo-site").is_file()
    assert not list(tmp_path.glob(".site.*"))


@pytest.mark.parametrize("mode", ["unmarked", "invalid_marker", "foreign_file", "foreign_dir"])
def test_refuses_to_replace_unowned_output(reports, tmp_path, mode):
    out = tmp_path / "site"
    if mode.startswith("foreign"):
        build(reports, out)
    else:
        out.mkdir()
    if mode == "foreign_dir":
        (out / "private").mkdir()
    else:
        (out / "keep.txt").write_text("unrelated content")
    if mode == "invalid_marker":
        (out / ".pogo-site").write_text("invalid marker")
    before = {str(p.relative_to(out)): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="refusing to replace --out"):
        site.build_site(reports, out)
    assert {
        str(p.relative_to(out)): p.read_bytes() for p in out.rglob("*") if p.is_file()
    } == before
    assert not list(tmp_path.glob(".site.*"))


def test_directory_swap_failure_restores_old_site(reports, tmp_path, monkeypatch):
    out = tmp_path / "site"
    before = build(reports, out)
    marker = (out / ".pogo-site").read_bytes()
    replace = site.os.replace

    def fail_install(source, target):
        if Path(source).is_dir() and ".new-" in Path(source).name:
            # The entire new site and its marker exist before the old tree moves.
            assert (Path(source) / ".pogo-site").is_file()
            assert not out.exists()
            raise OSError("injected directory swap failure")
        return replace(source, target)

    monkeypatch.setattr(site.os, "replace", fail_install)
    with pytest.raises(OSError, match="injected directory swap"):
        site.build_site(reports, out)
    assert {str(p.relative_to(out)): p.read_text() for p in out.rglob("*.html")} == before
    assert (out / ".pogo-site").read_bytes() == marker
    assert not list(tmp_path.glob(".site.*"))


def test_output_root_symlink_cannot_be_replaced(reports, tmp_path):
    outside = tmp_path / "outside"
    build(reports, outside)
    out = tmp_path / "site"
    out.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside --out"):
        site.build_site(reports, out)
    assert out.is_symlink()
    assert (outside / ".pogo-site").is_file()
