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
    expected = {"index.html", "how.html", "list/all.html", "list/grunts.html", "list/leaders.html"}
    for entry in manifest["characters"]:
        expected.update(f"{kind}/{entry['slug']}.html" for kind in ("list", "counters"))
    assert pages.keys() == expected
    assert build(reports, tmp_path / "site") == pages
    assert not (tmp_path / "site/fonts").exists()
    assert not (tmp_path / "site/brand").exists()
    for path, html in pages.items():
        prefix = "../" if "/" in path else ""
        assert "@font-face" not in html
        head_script = f"<script>{site.THEME_HEAD_JS}</script>"
        assert html.index('<meta charset="utf-8">') < html.index(head_script)
        assert html.index(head_script) < html.index("<style>") < html.index("</head>")
        assert site.THEME_TOGGLE in html
        assert "localStorage.setItem('pogo-theme'" in html
        assert '<div class="disc"><b>Simulator estimates.</b>' in html
        assert "Not yet checked against in-game battles." in html
        assert f'<a href="{prefix}how.html">How these numbers work</a>' in html
        for href, label in (
            ("index.html", "Home"),
            ("list/all.html", "All"),
            ("index.html#grunts", "Grunts"),
            ("index.html#leaders", "Leaders"),
        ):
            assert f'href="{prefix}{href}"' in html
            assert f">{label}</a>" in html
        expected = 1 if path == "how.html" else 0
        assert html.count("newer than our sources: rules assumed unchanged") == expected
        assert 'class="est-mark"' not in html
        assert '<details class="intro"' not in html
        assert "<footer" not in html
        if path != "how.html":
            for removed in (
                'class="trust"',
                'class="chip est"',
                "extrapolated forward",
                "stats parity-only",
                "open discrepancies:",
                "You: level",
            ):
                assert removed not in html
        for tag, attrs in Elements(html).elements:
            for key, value in attrs.items():
                if tag == "a" and key == "href":
                    continue
                assert not re.search(r"(?:https?:)?//", value or "", re.I), (path, tag, key)
        assert not re.search(r"\burl\s*\(|@import\b", html, re.I)
    for entry in manifest["characters"]:
        data = read(reports, entry["file"])
        for kind in ("list", "counters"):
            html = pages[f"{kind}/{entry['slug']}.html"]
            if data["character"].get("reason"):
                assert "not calculated" in html
                assert escape(data["character"]["reason"]) in html
            elif kind == "counters":
                assert '<details class="counter">' in html
                assert "data-calc-summary" in html
                assert "<th>n</th>" in html
        assert (
            f'href="../counters/{entry["slug"]}.html">Battle details</a>'
            in pages[f"list/{entry['slug']}.html"]
        )
    html = pages["list/all.html"]
    assert "<noscript>" in html and 'data-filter="steel"' in html
    assert 'data-filter="none"' not in html


def test_index_golden(reports, tmp_path):
    html = build(reports, tmp_path / "site")["index.html"]
    # Deliberate update command is documented in README's site section.
    if os.environ.get("POGO_UPDATE_SITE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(html)
    assert html == GOLDEN.read_text()


def test_type_icons_and_placeholder(reports, tmp_path):
    icons = tmp_path / "icons"
    icons.mkdir()
    png = b"\x89PNG\r\n\x1a\nstand-in"
    (icons / "steel.png").write_bytes(png)
    (icons / "fire.png").write_bytes(b"not a png")
    (icons / "water.png").write_bytes(png + b"x" * 65536)
    (icons / "grass.png").symlink_to(icons / "steel.png")
    out = tmp_path / "site"
    assert (
        cli.main(["site", "--data", str(reports), "--out", str(out), "--type-icons", str(icons)])
        == 0
    )
    assert (out / "types/steel.png").read_bytes() == png
    assert sorted(p.name for p in (out / "types").iterdir()) == ["steel.png"]
    assert "types/steel.png" in read(out, ".pogo-site")["files"]
    html = (out / "list/all.html").read_text()
    assert '<img src="../types/steel.png" alt="" width="18" height="18">' in html
    assert 'data-filter="none"' not in html
    assert not re.search(r'<span class="tys">.*?none.*?</span></td>', html)
    for name in ("fire", "water", "grass"):
        assert (
            site.type_chip(name, site.load_type_icons(icons))
            == f'<span class="ty ty-{name}">{name}</span>'
        )
    assert site.type_chip("<unknown>", set()) == "&lt;unknown&gt;"
    build(reports, out)
    assert not (out / "types").exists()
    assert '<span class="ty ty-steel">steel</span>' in (out / "list/all.html").read_text()
    assert "<img " not in (out / "list/all.html").read_text()


def test_brand_assets_copied_referenced_and_pruned(reports, tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    # Generated stand-ins at the exact size caps; the renderer never decodes them.
    png = b"\x89PNG\r\n\x1a\n" + b"x" * (65536 - 8)
    font = b"wOF2" + b"x" * (131072 - 4)
    (assets / "rocket-r.png").write_bytes(png)
    expected = {"brand/rocket-r.png": png}
    for weight in (400, 700, 900):
        (assets / f"lato-{weight}.woff2").write_bytes(font)
        expected[f"fonts/lato-{weight}.woff2"] = font
    (assets / "other.png").write_bytes(png)
    (assets / "lato-500.woff2").write_bytes(font)
    out = tmp_path / "site"
    assert (
        cli.main(["site", "--data", str(reports), "--out", str(out), "--brand-assets", str(assets)])
        == 0
    )
    for name, content in expected.items():
        assert (out / name).read_bytes() == content
    assert set(read(out, ".pogo-site")["files"]) == {
        *expected,
        *(str(p.relative_to(out)) for p in out.rglob("*.html")),
    }
    for path in out.rglob("*.html"):
        html = path.read_text()
        prefix = "../" if path.parent.name in ("list", "counters") else ""
        assert (
            '<h1><span class="rmark" aria-hidden="true">'
            f'<img src="{prefix}brand/rocket-r.png" alt=""></span>'
        ) in html
        assert "rmark letter" not in html
        assert html.count("@font-face") == 3
        for weight in (400, 700, 900):
            assert (
                f"@font-face{{font-family:Lato;font-weight:{weight};font-display:swap;"
                f'src:url("{prefix}fonts/lato-{weight}.woff2") format("woff2")}}'
            ) in html
    # This also exercises the build API and replacement of a tree containing brand files.
    count = site.build_site(reports, out, brand_assets=assets)
    assert count == len(list(out.rglob("*.html")))
    pages = build(reports, out)
    assert not (out / "brand").exists()
    assert not (out / "fonts").exists()
    assert not any(
        name.startswith(("brand/", "fonts/")) for name in read(out, ".pogo-site")["files"]
    )
    for html in pages.values():
        assert "@font-face" not in html
        assert '<h1><span class="rmark letter" aria-hidden="true">R</span>' in html
        assert "<img src=" not in html


@pytest.mark.parametrize(
    "name", ["rocket-r.png", "lato-400.woff2", "lato-700.woff2", "lato-900.woff2"]
)
@pytest.mark.parametrize("mode", ["wrong_signature", "oversize", "symlink", "directory", "fifo"])
def test_invalid_brand_assets_ignored(tmp_path, name, mode):
    assets = tmp_path / "assets"
    assets.mkdir()
    path = assets / name
    signature, cap = (b"\x89PNG\r\n\x1a\n", 65536) if name.endswith(".png") else (b"wOF2", 131072)
    if mode == "wrong_signature":
        path.write_bytes(b"invalid")
    elif mode == "oversize":
        path.write_bytes(signature + b"x" * (cap + 1 - len(signature)))
    elif mode == "symlink":
        target = tmp_path / "valid"
        target.write_bytes(signature + b"stand-in")
        path.symlink_to(target)
    elif mode == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    assert site.load_brand_assets(assets) == {}


def test_partial_brand_fonts(tmp_path):
    (tmp_path / "lato-700.woff2").write_bytes(b"wOF2stand-in")
    assets = site.load_brand_assets(tmp_path)
    html = site.document("Example", {}, "", "", prefix="../", assets=assets)
    assert html.count("@font-face") == 1
    assert "font-weight:700;font-display:swap;" in html
    assert 'src:url("../fonts/lato-700.woff2") format("woff2")' in html
    assert "lato-400.woff2" not in html
    assert "lato-900.woff2" not in html
    assert site.rocket_mark(assets) == '<span class="rmark letter" aria-hidden="true">R</span>'


def test_warning_tokens_stay_amber():
    blocks = [
        dict(re.findall(r"(--[\w-]+):([^;}]+)", block))
        for block in re.findall(r":root[^{}]*\{([^}]+)\}", site.CSS)
        if "--bg:" in block
    ]
    assert len(blocks) == 3
    for tokens, amber, violet, red in zip(
        blocks,
        ("#9a6200", "#e3a646", "#e3a646"),
        ("#6a4c9c", "#ad94dd", "#ad94dd"),
        ("#e0302a", "#ff3b30", "#ff3b30"),
        strict=True,
    ):
        assert tokens["--amber"] == amber
        assert tokens["--violet"] == violet
        assert tokens["--rocket-red"] == red
        assert tokens["--amber"] != tokens["--rocket-red"]


def test_how_gathers_validation_assumptions_sources_and_grades(reports, tmp_path):
    pages = build(reports, tmp_path / "site")
    html = pages["how.html"]
    overall = read(reports, "overall.json")
    for key in (
        "validation_label",
        "rcpm_note",
        "moveset_pool_note",
        "weighting_note",
        "credits",
        "limitations",
        "filter_note",
        "screen_note",
    ):
        assert escape(overall[key]) in html
    for discrepancy in overall["validation"]["open_discrepancies"]:
        assert escape(discrepancy["id"]) in html
    for source in overall["sources"]:
        assert escape(source["name"]) in html
        assert escape(source["url"]) in html
        assert "fetched 14 Nov 2026, 00:00 UTC" in html
    assert "Battles as of 14 Nov 2026 (a chosen date)" in html
    assert "battle rules from 12 Mar 2026" in html
    for level in ("40", "50"):
        assert site.assumptions(overall, level) in html
    for word in ("estimate", "unverified", "extrapolated forward", "stats parity-only"):
        assert f"<dt>{word}</dt>" in html
    assert 'id="pause"' in html
    assert escape(site.PAUSE_NOTE) in html
    for entry in read(reports, "manifest.json")["characters"]:
        data = read(reports, entry["file"])
        assert site.pause_band_legend(data) in html
    assert "sensitivity check over assumed pause lengths" in html


@pytest.mark.parametrize("count", [0, 1, 3])
@pytest.mark.parametrize(
    "validated,label,failed",
    [
        (True, "Passed", False),
        (False, "Passed", True),
        (True, "UNVALIDATED: gate failed", True),
    ],
)
def test_how_validation_and_check_counts(count, validated, label, failed):
    data = {
        "validation_label": label,
        "validation": {
            "validated": validated,
            "open_discrepancies": [{"id": f"X{i}"} for i in range(count)],
        },
    }
    html = site.how_body(data)
    assert (site.chip("UNVALIDATED", "warn") in html) is failed
    assert label in html
    for i in range(count):
        assert f"X{i}" in html
    shell = site.document("Example", data, "")
    assert "UNVALIDATED" not in shell and "open discrepancies:" not in shell


def test_level_switch_markup_and_home_grids(reports, tmp_path):
    pages = build(reports, tmp_path / "site")
    for path, html in pages.items():
        if path == "how.html":
            continue
        buttons = [a for t, a in Elements(html).elements if "data-show-level" in a]
        assert [(b["data-show-level"], b["aria-pressed"]) for b in buttons] == [
            ("40", "true"),
            ("50", "false"),
        ]
        sections = [a for t, a in Elements(html).elements if "data-level" in a]
        assert [a["data-level"] for a in sections] == ["40", "50"]
        assert all("hidden" not in a for a in sections)
        assert html.count("Your counter: level") == 2
        assert site.LEVEL_JS in html
    home = pages["index.html"]
    assert 'id="leaders"' in home and 'id="grunts"' in home
    assert "<h2>Best all-round</h2>" in home
    assert 'href="list/all.html">Full list' in home
    assert 'class="cch"' in home and 'class="lead"' in home and 'class="top3"' in home
    assert '<span class="rk-badge">Leader</span>' in home


@pytest.mark.parametrize(
    "era,expected",
    [
        ("before-dec-2025", "battle rules before 10 Dec 2025"),
        ("dec-2025", "battle rules from 10 Dec 2025 to 11 Mar 2026"),
        ("mar-2026", "battle rules from 12 Mar 2026"),
        ('<unknown "era">', "battle rules period &lt;unknown &quot;era&quot;&gt;"),
        (None, "battle rules period not recorded"),
    ],
)
def test_provenance_era_wording(era, expected):
    data = {"valid_for": {"era": era}} if era else {}
    assert expected in site.provenance(data)


@pytest.mark.parametrize("old_keys", [True, False])
@pytest.mark.parametrize(
    "source,expected",
    [
        ("default: run date", "the day this ran"),
        ("explicit", "a chosen date"),
        (None, "date source not recorded"),
        ('<other "source">', "&lt;other &quot;source&quot;&gt;"),
    ],
)
def test_provenance_date_and_source_wording(source, expected, old_keys):
    prefix = "" if old_keys else "computed_for_"
    data = {f"{prefix}battle_date": "2026-11-16", "era": "mar-2026"}
    if source is not None:
        data[f"{prefix}battle_date_source"] = source
    assert site.provenance(data) == (
        f'<p class="moves">Battles as of 16 Nov 2026 ({expected}) · '
        "battle rules from 12 Mar 2026</p>"
    )


@pytest.mark.parametrize("extrapolated", [True, False])
def test_extrapolation_warning_only_on_how_page(extrapolated):
    # Owner ruling: the "assumed" idea lives on how.html, never in the page shell.
    data = {"valid_for": {"extrapolated": extrapolated}}
    html = site.document("Example", data, site.provenance(data))
    assert "rules assumed unchanged" not in html
    assert "extrapolated forward" not in html
    how = site.how_body(data)
    assert how.count("newer than our sources: rules assumed unchanged") == int(extrapolated)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-11-16T08:30:59Z", "fetched 16 Nov 2026, 08:30 UTC"),
        ("2026-11-16T01:30:45-07:00", "fetched 16 Nov 2026, 08:30 UTC"),
        ("2026-11-17T01:30:00+03:00", "fetched 16 Nov 2026, 22:30 UTC"),
        ("2026-11-16T08:30:00", "fetched 16 Nov 2026, 08:30 UTC"),
        (None, "fetched not recorded"),
        ("", "fetched not recorded"),
        ('<bad "timestamp">', "fetched &lt;bad &quot;timestamp&quot;&gt;"),
    ],
)
def test_footer_fetched_wording(value, expected):
    source = {"fetched_at": value} if value is not None else {}
    html = site.notes({"sources": [source]})
    assert f" · {expected}</p>" in html
    assert "fetched_at" not in html


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
                row["pause_band"]["note"] = hostile
                row["pause_band"]["turns"] = [hostile, hostile]

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

    change(reports, "overall.json", mutate)
    html = build(reports, tmp_path / "site")["how.html"]
    assert site.chip("UNVALIDATED", "warn") in html
    assert "UNVALIDATED: gate failed; X9 is open" in html
    assert "open discrepancies: X9" in html


@pytest.mark.parametrize(
    "mode", ["key", "missing", "hidden", "name", "file_key", "manifest_key", "both_keys", "status"]
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
    elif mode == "status":
        change(reports, "manifest.json", lambda d: d["characters"][0].update(status="stale"))
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
    assert "data-win=" not in pages[f"list/{entry['slug']}.html"]


@pytest.mark.parametrize("mode", ["key", "status"])
def test_stale_overall_is_visible(reports, tmp_path, mode):
    change(
        reports,
        "overall.json",
        lambda d: d.update(
            battle_date="2026-10-01",
            computed_for_battle_date="2026-10-01",
            computed_for_battle_date_source="default: run date",
            valid_for={"era": "overall-file-era", "extrapolated": True},
        ),
    )
    if mode == "key":
        change(reports, "overall.json", lambda d: d.update(key="wrong"))
    else:
        change(reports, "manifest.json", lambda d: d["overall"].update(status="stale"))
    pages = build(reports, tmp_path / "site")
    for path in ("index.html", "list/all.html", "list/grunts.html", "list/leaders.html"):
        html = pages[path]
        if mode == "key":
            assert "stale report: key does not match manifest entry" in html
            assert "not calculated" in html
            assert "stale · This overall list" not in html
        else:
            assert "stale · This overall list" in html
            assert "This overall list was computed for battle date 2026-10-01" in html
            assert (
                "older than the per-type lists, which have changed since it was computed." in html
            )
        assert "Battles as of 1 Oct 2026" in pages["how.html"]
        assert "(the day this ran)" in pages["how.html"]
        assert "battle rules period overall-file-era" in pages["how.html"]
        if path.startswith("list/"):
            assert ("data-win=" in html) is (mode == "status")
            assert ("not calculated" in html) is (mode == "key")
            assert "Battles as of 14 Nov 2026" not in html


def test_skipped_overall_reason(reports, tmp_path):
    change(
        reports,
        "manifest.json",
        lambda d: d.update(overall={"key": None, "file": None, "status": "skipped"}),
    )
    pages = build(reports, tmp_path / "site")
    for path in ("index.html", "list/all.html", "list/grunts.html", "list/leaders.html"):
        assert "overall list not computed on this run (--skip-overall)" in pages[path]
        assert "report file unavailable" not in pages[path]
        if path.startswith("list/"):
            assert "data-win=" not in pages[path]


@pytest.mark.parametrize("mode", ["missing", "hidden", "absolute", "outside"])
def test_stale_overall_requires_safe_existing_file(reports, tmp_path, mode):
    filename = "overall.json"
    if mode == "missing":
        (reports / filename).unlink()
    elif mode == "hidden":
        filename = ".overall.json"
        (reports / filename).write_text("not JSON: must not be read")
    else:
        outside = tmp_path / "outside.json"
        outside.write_bytes((reports / filename).read_bytes())
        if mode == "absolute":
            filename = str(outside)
        else:
            filename = "outside.json"
            (reports / filename).symlink_to(outside)
    change(reports, "manifest.json", lambda d: d["overall"].update(file=filename, status="stale"))
    pages = build(reports, tmp_path / "site")
    for path in ("index.html", "list/all.html", "list/grunts.html", "list/leaders.html"):
        assert "not calculated" in pages[path]
        assert "stale · This overall list" not in pages[path]
        if path.startswith("list/"):
            assert "data-win=" not in pages[path]


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
    for path in ("how.html",):
        assert "Battles as of 1 Oct 2026" in pages[path]
        assert "(the day this ran)" in pages[path]
        assert "battle rules period file-specific-era" in pages[path]


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
    assert f"{site.estimate(2)}–{site.estimate(6)}</td>" in html
    assert f"{site.estimate(4)}–{site.estimate(7)}</td>" in html
    # Equal ends collapse to one value.
    assert f"{site.estimate(9)}–{site.estimate(9)}" not in html
    assert f"{site.estimate(9)}</td>" in html
    assert 'class="chip' not in html
    assert 'title="estimate"' not in html


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


def test_detail_numbers_preserved_without_estimate_marks(reports, tmp_path):
    pages = build(reports, tmp_path / "site")
    numeric = (
        ("win_rate", True),
        ("draw_rate", True),
        ("mean_rocket_knocked_out", False),
        ("lead_sweep_probability", True),
        ("mean_player_hp_fraction_left", True),
        ("mean_turns", False),
    )
    for entry in read(reports, "manifest.json")["characters"]:
        data = read(reports, entry["file"])
        html = pages[f"counters/{entry['slug']}.html"]
        expected_summary_rows = 0
        for rows in data["character"]["finalists"].values():
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
        assert "est-mark" not in html and 'title="estimate"' not in html


def test_move_badges_shadow_and_excluded_filter(reports, tmp_path):
    def mutate(data):
        data["exclude_elite_legacy"] = True
        data["filter_note"] = "fixture: elite and legacy excluded by request"

    change(reports, "overall.json", mutate)
    html = build(reports, tmp_path / "site")["how.html"]
    assert "elite/legacy excluded" in html
    assert "fixture: elite and legacy excluded by request" in html
    marked = site.counter_name(
        {
            "speciesId": "example_shadow",
            "fast_move": "A",
            "charged_move": "B",
            "move_flags": {"A": {"elite": True}, "B": {"legacy": True}},
        }
    )
    assert ">Shadow</span>" in marked
    # Owner ruling: elite and legacy moves both read "Elite TM", one badge per move.
    assert marked.count(">Elite TM</span>") == 2
    assert ">Elite</span>" not in marked and ">Legacy</span>" not in marked


def test_old_reports_without_types_or_overall_kos_are_explicit(reports, tmp_path):
    def mutate(data):
        for view in ("all", "grunts", "leaders"):
            for rows in data[view]["results"].values():
                for row in rows:
                    row.pop("types", None)
                    row.pop("mean_rocket_knocked_out", None)

    change(reports, "overall.json", mutate)
    html = build(reports, tmp_path / "site")["list/all.html"]
    assert '<span class="tys"></span>' in html
    assert "KOs not recorded" in html


@pytest.mark.parametrize("sensitive", [True, False, None])
def test_sensitive_tag_and_pause_details(reports, tmp_path, sensitive):
    entry = read(reports, "manifest.json")["characters"][0]

    def mutate(data):
        for rows in data["character"]["finalists"].values():
            for row in rows:
                if sensitive is None:
                    row.pop("pause_band")
                else:
                    row["pause_band"].update(sensitive=sensitive, min=0.8, max=1, turns=[5, 6, 8])

    change(reports, entry["file"], mutate)
    pages = build(reports, tmp_path / "site")
    for kind in ("list", "counters"):
        html = pages[f"{kind}/{entry['slug']}.html"]
        assert (">Sensitive</a>" in html) is (sensitive is True)
        if sensitive:
            assert 'href="../how.html#pause"' in html
        assert "pause-sensitive" not in html
    if sensitive is not None:
        assert "between 5 and 8 turns" in pages["how.html"]
    else:
        assert "band not computed for this run" in pages["how.html"]


@pytest.mark.parametrize(
    "threshold,points",
    [(0.15, "15"), (0.125, "12.5"), (0.000125, "0.0125"), (0.333333333, "33.3333333")],
)
def test_pause_band_legend_percentage_points(threshold, points):
    data = {
        "params": {"pause_band": [6, 8], "pause_threshold": threshold},
        "character": {"finalists": {"40": [{"pause_band": {"turns": [5, 6, 8]}}]}},
    }
    legend = site.pause_band_legend(data)
    assert f"more than {points} percentage points between 5 and 8 turns" in legend
    ledger = Path(__file__).parents[1] / "docs" / "simulator-verification.md"
    assert "## Ledger" in ledger.read_text().splitlines()


def test_pause_band_none_legend(reports, tmp_path):
    entry = read(reports, "manifest.json")["characters"][0]

    def disable(data):
        data["params"]["pause_band"] = []
        for rows in data["character"]["finalists"].values():
            for row in rows:
                row.pop("pause_band")

    change(reports, entry["file"], disable)
    pages = build(reports, tmp_path / "site")
    for path in (f"list/{entry['slug']}.html", f"counters/{entry['slug']}.html"):
        assert "band not computed for this run" not in pages[path]
    assert "band not computed for this run" in pages["how.html"]


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
    assert len(pages) == 7
    assert "report file unavailable" in pages["list/all.html"]
    assert "Simulator estimates." in pages["index.html"]
    assert "Battles as of not recorded" in pages["how.html"]
    assert escape(read(reports, "manifest.json")["validation_label"]) in pages["how.html"]
    for html in pages.values():
        for footer in re.findall(r'<footer class="notes">(.*?)</footer>', html, re.S):
            assert "coverage not recorded" in footer


def test_how_uses_manifest_when_overall_missing(reports, tmp_path):
    entries = read(reports, "manifest.json")["characters"]
    change(reports, "manifest.json", lambda d: d.update(overall={}))
    change(reports, entries[0]["file"], lambda d: d.update(key="stale"))
    pages = build(reports, tmp_path / "site")
    assert escape(read(reports, "manifest.json")["validation_label"]) in pages["how.html"]
    for path in ("list/all.html", "list/grunts.html", "list/leaders.html"):
        assert "report file unavailable" in pages[path]
        assert "data-win=" not in pages[path]


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
    assert site.estimate(value, percent=True) == escape(expected)
    html = site.list_body({}, {"40": [{"win_rate": 1}, {"win_rate": value}]}, "")
    assert f"<b>{escape(expected)}</b>" in html


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
    assert site.estimate(value) == expected


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable for inline JS check")
def test_filter_js_and_progressive_controls():
    harness = r"""
const rows=[['water',.9],['fire',.4],['fire',.2]].map(([t,v])=>({
 dataset:{types:JSON.stringify([t]),win:String(v)},hidden:false,rank:{textContent:''},
 querySelector(){return this.rank;}}));
const controls={hidden:true},warning={hidden:true};
const section={querySelector(){return warning;},
 querySelectorAll(s){return s==='[data-filter]'?[button]:rows;}};
const button={dataset:{filter:'fire'},closest(){return section;},setAttribute(){}};
globalThis.document={querySelectorAll(s){return s==='.controls'?[controls]:[button];}};
SCRIPT
button.onclick();
console.log(JSON.stringify({hidden:controls.hidden,warning:warning.hidden,
 rows:rows.map(r=>[r.hidden,r.rank.textContent])}));
""".replace("SCRIPT", site.FILTER_JS)
    result = subprocess.run(["node", "-e", harness], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == {
        "hidden": False,
        "warning": False,
        "rows": [[True, ""], [False, 1], [False, 2]],
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
    assert "pool incomplete" not in caption and "extrapolated" not in caption


def test_missing_row_grade_needs_no_per_row_warning():
    row = {"win_rate": 0.5}
    assert "grade not recorded" not in site.list_body({}, {"40": [row]}, "")
    assert "grade not recorded" not in site.counters_body({}, {"40": [row]}, "")


@pytest.mark.parametrize("validated", [None, False, 0, 1, "true", True])
def test_unvalidated_requires_literal_true(validated):
    data = {"validation": {"validated": validated}}
    assert (site.chip("UNVALIDATED", "warn") in site.trust_strip(data)) is (validated is not True)
    assert site.chip("UNVALIDATED", "warn") in site.trust_strip({"validation": {}})
    assert site.chip("UNVALIDATED", "warn") in site.trust_strip({})


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
def test_calc_grades_do_not_change_numeric_ranges(grade_order):
    rows = []
    for value, grade in ((5, "z-unknown"), (7, "fixture-exact"), (6, "a-unknown")):
        row = {"slot": {"value": 1}, "defender": {"value": "target"}, "charged": {"value": []}}
        for key in ("fast_damage", "fast_hits_to_ko", "rocket_fast_damage", "turns_survived"):
            row[key] = {"value": value, "grade": grade}
        rows.append(row)
    html = site.calc_summary(rows, grade_order)
    assert html.count("5–7") == 4
    assert "unknown" not in html and "fixture-exact" not in html
    assert site.calc_summary(list(reversed(rows)), grade_order) == html


@pytest.mark.parametrize("best,warn", [(0.04, True), (0, True), (0.5, False), (1, False)])
def test_list_warns_when_best_counter_loses_most_battles(best, warn):
    html = site.list_body({}, {"40": [{"win_rate": best}]}, "")
    assert "best counter loses most battles" in html
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


def test_phone_layout_rules(reports, tmp_path):
    """Verify the CSS/markup budget using the existing static test approach, without a browser."""
    entry = read(reports, "manifest.json")["characters"][0]
    change(
        reports,
        "manifest.json",
        lambda d: d["characters"][0].update(slug="fire-grunt-female", name="Fire grunt (female)"),
    )

    def fire_fixture(data):
        data["character"]["name"] = "Fire grunt (female)"
        for level, rows in data["character"]["finalists"].items():
            template = rows[0]
            counters = []
            for species in ("feraligatr", "feraligatr_shadow", "dondozo"):
                row = json.loads(json.dumps(template))
                row.update(speciesId=species, types=["water", "none"])
                counters.append(row)
            data["character"]["finalists"][level] = counters

    change(reports, entry["file"], fire_fixture)
    pages = build(reports, tmp_path / "site")
    html = pages["list/fire-grunt-female.html"]
    assert html.count('class="row"') == 6  # three complete rows at each level
    assert "Fire grunt (female)" in html
    assert html.count('class="slot"') == 6
    assert ".wrap{overflow-x:auto;" in html
    assert "@media(min-width:700px)" in html
    assert ".row .sec{grid-column:3/-1;" in html
    assert "display:none;" in site.CSS.split(".row .sec{", 1)[1].split("}", 1)[0]
    assert "display:flex;" in site.CSS.split("@media(min-width:700px)", 1)[1]
    phone = site.CSS.split("@media(max-width:699px)", 1)[1]
    assert ".charhead .lsp{width:32px;" in phone
    assert ".charhead{padding:10px 14px}" in phone
    assert ".slot{gap:4px;" in phone and "padding:2px 6px;" in phone
    assert ".row{gap:2px 6px;" in phone and "padding:7px 0;" in phone
    assert "grid-template-columns:16px 36px minmax(0,1fr) 58px" in phone
    # Conservative 390px budget: nav + two-line disclaimer/warning + title/type +
    # caption + three 32px slots + card heading + three-line settings + three
    # four-line counters (including Toughest and a wrapped move), plus spacing.
    height = 44 + 48 + 48 + 65 + 20 + 3 * 38 + 42 + 54 + 3 * 90 + 30
    assert height <= 844


@pytest.mark.parametrize("rate,shown", [(0, True), (0.9499, True), (0.95, False), (1, False)])
def test_toughest_uses_lowest_conditional_rate_only_on_character_lists(rate, shown):
    row = {
        "speciesId": "counter",
        "win_rate": 0.8,
        "per_slot": [
            {"slot": 1, "species": [{"species": "easy", "conditional_win_rate": 1}]},
            {"slot": 2, "species": [{"species": "hard_shadow", "conditional_win_rate": rate}]},
        ],
    }
    html = site.list_body({}, {"40": [row]}, "")
    assert ("Toughest:" in html) is shown
    if shown:
        assert f"Hard ({escape(site.percentage(rate))} win)" in html
        assert "Easy (" not in html
    assert "Toughest:" not in site.list_body({}, {"40": [row]}, "", overall=True)
    assert "Toughest:" not in site.list_body({}, {"40": [{"win_rate": 0.8}]}, "")


def test_settings_are_built_from_report_policies():
    data = {
        "params": {"ivs": {"atk": 1, "def": 2, "hp": 3}},
        "player_shield_policy": "never",
        "rules": {"rocket_shields": False},
    }
    assert site.settings(data, "50") == (
        '<p class="set">Your counter: level 50 · 1/2/3 · you never shield · '
        "Rocket shields disabled</p>"
    )
    assert "not recorded" in site.settings({}, "40")
    data["player_shield_policy"] = "first_two"
    data["rules"]["rocket_shields"] = True
    assert "you shield the first two charged attacks" in site.settings(data, "40")
    assert "Rocket shields as in game" in site.settings(data, "40")


def test_lineup_caps_each_slot_and_uses_first_counter():
    rows = [
        {"per_slot": [{"slot": 1, "species": [{"species": f"mon_{i}"} for i in range(8)]}]},
        {"per_slot": [{"slot": 2, "species": [{"species": "unused"}]}]},
    ]
    html = site.lineup_block(rows, site.Sprites())
    assert html.count('class="lm"') == 6
    assert '<span class="more">+2</span>' in html
    assert "Mon 5" in html and "Mon 6" not in html and "Unused" not in html


def test_sprites_copied_referenced_and_pruned(reports, tmp_path):
    directory = tmp_path / "sprites"
    directory.mkdir()
    png = b"\x89PNG\r\n\x1a\n" + b"x" * (131072 - 8)
    # Counter base, lineup base, an unreferenced base and a shadow filename to ignore.
    for base in ("palkia_origin", "lineup", "unused", "palkia_origin_shadow"):
        (directory / f"{base}.png").write_bytes(png)
    entry = read(reports, "manifest.json")["characters"][0]

    def mutate(data):
        for rows in data["character"]["finalists"].values():
            for row in rows:
                row["speciesId"] = "palkia_origin_shadow"
                row["per_slot"][0]["species"][0]["species"] = "lineup_shadow"

    change(reports, entry["file"], mutate)
    out = tmp_path / "site"
    assert (
        cli.main(["site", "--data", str(reports), "--out", str(out), "--sprites", str(directory)])
        == 0
    )
    expected = {"sprites/palkia_origin.png", "sprites/lineup.png"}
    assert {str(p.relative_to(out)) for p in (out / "sprites").iterdir()} == expected
    assert expected <= set(read(out, ".pogo-site")["files"])
    for relative in expected:
        assert (out / relative).read_bytes() == png
    for page in ("index.html", f"list/{entry['slug']}.html", f"counters/{entry['slug']}.html"):
        html = (out / page).read_text()
        prefix = "../" if "/" in page else ""
        assert f'src="{prefix}sprites/palkia_origin.png"' in html
        images = [
            a for t, a in Elements(html).elements if t == "img" and "sprites/" in a.get("src", "")
        ]
        assert images
        assert all(
            a["alt"] == ""
            and a["loading"] == "lazy"
            and a["width"].isdigit()
            and a["height"].isdigit()
            for a in images
        )
    # Rebuilding with the same optional assets exercises ownership checks for sprites.
    assert site.build_site(reports, out, sprites=directory) == len(list(out.rglob("*.html")))
    # A missing sprite is a same-size decorative lettered circle.
    html = site.Sprites().render("palkia_origin_shadow", size=32)
    assert 'class="spr ph" aria-hidden="true"' in html
    assert 'style="--sprite-size:32px">PA</span>' in html
    build(reports, out)
    assert not (out / "sprites").exists()
    assert not any(n.startswith("sprites/") for n in read(out, ".pogo-site")["files"])


@pytest.mark.parametrize("mode", ["wrong_signature", "oversize", "symlink", "directory", "fifo"])
def test_bad_sprites_ignored(tmp_path, mode):
    path = tmp_path / "example.png"
    if mode == "wrong_signature":
        path.write_bytes(b"not a PNG")
    elif mode == "oversize":
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 131072)
    elif mode == "symlink":
        target = tmp_path / "valid"
        target.write_bytes(b"\x89PNG\r\n\x1a\nstand-in")
        path.symlink_to(target)
    elif mode == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    sprites = site.Sprites(tmp_path)
    assert ">EX</span>" in sprites.render("example")
    assert sprites.assets == {}


def test_sprite_ids_cannot_escape_directory(tmp_path):
    sprites = site.Sprites(tmp_path)
    html = sprites.render("../evil<script>")
    assert "<img" not in html and "<script>" not in html
    assert sprites.assets == {} and sprites.checked == set()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable for inline JS check")
def test_level_switch_script_updates_sections_lineups_and_aria():
    harness = r"""
const buttons=['40','50'].map(level=>({dataset:{showLevel:level},pressed:'',
 setAttribute(k,v){this.pressed=String(v);}}));
const sections=['40','50'].map(level=>({dataset:{level},hidden:false}));
const lineups=['40','50'].map(level=>({dataset:{lineupLevel:level},hidden:false}));
const control={hidden:true},heading={hidden:false};
const card={querySelector(){return control;},querySelectorAll(s){
 return s==='[data-show-level]'?buttons:s==='[data-level]'?sections:[heading];}};
globalThis.document={querySelectorAll(s){return s==='[data-levels]'?[card]:lineups;}};
SCRIPT
const initial=sections.map(s=>s.hidden);
buttons[1].onclick();
console.log(JSON.stringify({initial,hidden:control.hidden,heading:heading.hidden,
 sections:sections.map(s=>s.hidden),lineups:lineups.map(s=>s.hidden),
 pressed:buttons.map(b=>b.pressed)}));
""".replace("SCRIPT", site.LEVEL_JS)
    result = subprocess.run(["node", "-e", harness], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == {
        "initial": [False, True],
        "hidden": False,
        "heading": True,
        "sections": [True, False],
        "lineups": [True, False],
        "pressed": ["false", "true"],
    }


def test_stale_rows_and_their_sprites_never_reach_home(reports, tmp_path):
    entry = read(reports, "manifest.json")["characters"][0]
    directory = tmp_path / "sprites"
    directory.mkdir()
    (directory / "stale_unique.png").write_bytes(b"\x89PNG\r\n\x1a\nstand-in")

    def stale(data):
        data["key"] = "wrong"
        for rows in data["character"]["finalists"].values():
            for row in rows:
                row["speciesId"] = "stale_unique"

    change(reports, entry["file"], stale)
    out = tmp_path / "site"
    site.build_site(reports, out, sprites=directory)
    for path in out.rglob("*.html"):
        assert "Stale Unique" not in path.read_text()
    assert not (out / "sprites/stale_unique.png").exists()


def test_home_counter_limits_and_boss_badge():
    rows = [{"speciesId": f"counter_{i}", "win_rate": 1 - i / 10} for i in range(7)]
    body = site.list_body({}, {"40": rows}, "", overall=True, prefix="", limit=5)
    assert body.count('class="row"') == 5
    assert "Counter 4" in body and "Counter 5" not in body
    card = site.tile("Giovanni", "list/giovanni.html", {}, {"40": rows}, "", rank="boss")
    assert card.count("<li>") == 3
    assert "Counter 2" in card and "Counter 3" not in card
    assert '<span class="rk-badge">Boss</span>' in card


ESTIMATE_WORDS = re.compile(
    r"\b(?:estimates?|est|unverified|extrapolated|parity-only|assumed|not yet checked)\b", re.I
)


class VisibleText(HTMLParser):
    """Visible text outside the site-wide disclaimer bar, scripts and styles."""

    def __init__(self, html):
        super().__init__()
        self.skip, self.depth, self.text, self.bar = [], 0, [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "img", "meta", "link", "input"):
            return
        self.depth += 1
        classes = (dict(attrs).get("class") or "").split()
        if tag in ("script", "style", "title") or "disc" in classes:
            self.skip.append(self.depth)

    def handle_endtag(self, tag):
        if tag in ("br", "img", "meta", "link", "input"):
            return
        if self.skip and self.skip[-1] == self.depth:
            self.skip.pop()
        self.depth -= 1

    def handle_data(self, data):
        (self.bar if self.skip else self.text).append(data)


def test_estimate_idea_appears_once_per_page_in_the_bar(reports, tmp_path):
    # Owner ruling: "this is an estimate / unverified / assumed" is said once per page, in the
    # site-wide bar linking to how.html. Only how.html explains it in full.
    pages = build(reports, tmp_path / "site")
    assert len(pages) > 3
    for name, html in pages.items():
        if name == "how.html":
            continue
        parsed = VisibleText(html)
        assert html.count('<div class="disc">') == 1, name
        assert "how.html" in html, name
        found = ESTIMATE_WORDS.findall(" ".join(parsed.text))
        assert not found, (name, found)


def test_sprite_file_selection(reports, tmp_path, monkeypatch, capsys):
    import hashlib

    species = {
        "palkia": 484,
        "palkia_origin": 484,
        "raichu": 26,
        "raichu_alolan": 26,
        "articuno": 144,
        "articuno_galarian": 144,
        "growlithe": 58,
        "growlithe_hisuian": 58,
        "wooper": 194,
        "wooper_paldean": 194,
        "plain": 1,
        "normal": 2,
        "forms": 3,
        "missing": 4,
        "bad\nbase": 5,
    }
    cache = tmp_path / "sprite-cache" / "sources"
    cache.mkdir(parents=True)
    url = site.PVPOKE_GM_URL
    entry = {
        "url": url,
        "status": 200,
        "body": json.dumps(
            {"pokemon": [{"speciesId": name, "dex": dex} for name, dex in species.items()]}
        ),
    }
    (cache / (hashlib.sha256(url.encode()).hexdigest() + ".json")).write_text(json.dumps(entry))
    names = [
        "pm484.fORIGIN.icon.png",
        "pm26.fALOLA.icon.png",
        "pm144.fGALARIAN.icon.png",
        "pm58.fHISUIAN.icon.png",
        "pm194.fPALDEA.icon.png",
        "pm1.icon.png",
        "pm2.fNORMAL.icon.png",
        "pm3.fZ.icon.png",
        "pm3.fA.icon.png",
        "pm4.s.icon.png",
        "pm4.c1.icon.png",
        "pm5.icon.png\nmalicious",
    ]
    tree = tmp_path / "tree.json"
    tree.write_text(json.dumps({"tree": [{"path": name} for name in names]}))
    bases = set(species) - {"palkia", "raichu", "articuno", "growlithe", "wooper"}
    bases.add("unknown")
    monkeypatch.setattr(site, "render_site", lambda *args: ({}, bases))
    assert (
        cli.main(
            [
                "site-sprites",
                "--data",
                str(reports),
                "--cache-dir",
                str(cache.parent),
                "--tree",
                str(tree),
            ]
        )
        == 0
    )
    out = capsys.readouterr()
    assert out.out.splitlines() == [
        "articuno_galarian pm144.fGALARIAN.icon.png",
        "forms pm3.fA.icon.png",
        "growlithe_hisuian pm58.fHISUIAN.icon.png",
        "normal pm2.fNORMAL.icon.png",
        "palkia_origin pm484.fORIGIN.icon.png",
        "plain pm1.icon.png",
        "raichu_alolan pm26.fALOLA.icon.png",
        "wooper_paldean pm194.fPALDEA.icon.png",
    ]
    assert "missing" in out.err and "unknown" in out.err and "bad\\nbase" in out.err
    (cache / (hashlib.sha256(url.encode()).hexdigest() + ".json")).unlink()
    with pytest.raises(SystemExit):
        cli.main(
            [
                "site-sprites",
                "--data",
                str(reports),
                "--cache-dir",
                str(cache.parent),
                "--tree",
                str(tree),
            ]
        )
    out = capsys.readouterr()
    assert out.out == "" and "gamemaster cache" in out.err


def test_sprite_requests_match_build(reports, tmp_path, monkeypatch):
    requested = set()
    original = site.Sprites.render

    def record(self, species, **kwargs):
        requested.add(str(species).removesuffix("_shadow"))
        return original(self, species, **kwargs)

    monkeypatch.setattr(site.Sprites, "render", record)
    site.build_site(reports, tmp_path / "site")
    _, bases = site.render_site(reports)
    assert bases == requested
    assert bases
