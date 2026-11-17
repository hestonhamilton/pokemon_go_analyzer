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
        ids = [a["id"] for _, a in Elements(html).elements if "id" in a]
        assert len(ids) == len(set(ids)), (path, ids)
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
                assert "<th>Win chance vs this Pokémon</th>" in html
                assert "<th>n</th>" not in html
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


def test_pause_target_uses_row_band_data_and_grid_notes_have_one_home(reports, tmp_path):
    entry = read(reports, "manifest.json")["characters"][0]

    def mutate(data):
        for rows in data["character"]["finalists"].values():
            for row in rows:
                row["pause_band"].update(
                    turns=[4, 7, 9], threshold=0.125, threshold_note="custom <threshold> choice"
                )
                row["screen"]["grid_limitation"] = "Grid caveat: fixture ignores HP"
                row["screen"]["note"] = "Fixture screen sensitivity check"

    change(reports, entry["file"], mutate)
    pages = build(reports, tmp_path / "site")
    how = pages["how.html"]
    pause = re.search(r'id="pause-detail">(.*?)(?=<h2)', how, re.S).group(1)
    assert "Pause band is a sensitivity check" in pause
    assert "Timing-sensitive means a row's win rate moves more than the threshold" in pause
    assert (
        "more than 12.5 percentage points between 4 and 9 turns (custom &lt;threshold&gt; choice)"
        in pause
    )
    assert "pause band not computed for the overall list" not in pause
    for note in ("Grid caveat: fixture ignores HP", "Fixture screen sensitivity check"):
        assert how.count(note) == 1
        assert all(note not in html for path, html in pages.items() if path != "how.html")
    counters = pages[f"counters/{entry['slug']}.html"]
    assert "Win chance if Rocket pauses 4–9 turns:" in counters
    assert "Lineup spot 1:" in counters


@pytest.mark.parametrize("slug", ["pause", "elite-tm", "row-grades"])
def test_character_method_anchors_cannot_collide(reports, tmp_path, slug):
    change(reports, "manifest.json", lambda d: d["characters"][0].update(slug=slug))
    pages = build(reports, tmp_path / "site")
    assert f'id="c-{slug}"' in pages["how.html"]
    for path, html in pages.items():
        ids = [a["id"] for _, a in Elements(html).elements if "id" in a]
        assert len(ids) == len(set(ids)), (path, ids)


def uniform_row_grades(reports):
    # The ordinary fixture intentionally has incomplete grunt pools and complete leader pools.
    def mutate(data):
        views = (
            [data["character"]["finalists"]]
            if "character" in data
            else [data[view].get("results", {}) for view in ("all", "grunts", "leaders")]
        )
        for results in views:
            for rows in results.values():
                for row in rows:
                    row.update(grade="estimate; usual fixture grade", pool_complete=True)

    change(reports, "overall.json", mutate)
    for entry in read(reports, "manifest.json")["characters"]:
        change(reports, entry["file"], mutate)


def test_no_rows_differ_from_usual_grade(reports, tmp_path):
    uniform_row_grades(reports)
    how = build(reports, tmp_path / "site")["how.html"]
    assert "Rows that differ from the usual grade" in how
    assert "<p>None: every published row carries the usual grade.</p>" in how


@pytest.mark.parametrize("view", ["character", "all", "grunts", "leaders"])
@pytest.mark.parametrize("difference", ["grade", "pool", "both"])
def test_differing_rows_are_named_only_on_how(reports, tmp_path, view, difference):
    uniform_row_grades(reports)
    entry = read(reports, "manifest.json")["characters"][0]
    filename = entry["file"] if view == "character" else "overall.json"
    name = (
        entry["name"]
        if view == "character"
        else {"all": "All Rocket", "grunts": "Grunts", "leaders": "Leaders"}[view]
    )

    def mutate(data):
        results = data["character"]["finalists"] if view == "character" else data[view]["results"]
        row = results["40"][0]
        row["speciesId"] = "different_counter"
        if difference in ("grade", "both"):
            row["grade"] = "estimate; fixture <different> grade"
        if difference in ("pool", "both"):
            row["pool_complete"] = False

    change(reports, filename, mutate)
    pages = build(reports, tmp_path / "site")
    how = pages["how.html"]
    assert f"<li>{escape(name)} · level 40 · Different Counter:" in how
    assert "None: every published row carries the usual grade." not in how
    if difference in ("grade", "both"):
        assert "estimate; fixture &lt;different&gt; grade" in how
        assert all(
            "fixture &lt;different&gt; grade" not in html
            for path, html in pages.items()
            if path != "how.html"
        )
    if difference in ("pool", "both"):
        assert "pool incomplete" in how
    # Unpublished rows must not contribute to the exception list or its baseline.
    if view == "character":
        change(reports, "manifest.json", lambda d: d["characters"][0].update(status="stale"))
    else:
        change(reports, "overall.json", lambda d: d.update(key="wrong"))
    how = build(reports, tmp_path / "site")["how.html"]
    assert "<p>None: every published row carries the usual grade.</p>" in how


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
        # Owner ruling: every page opens on level 50, with level 40 a tap away.
        assert [(b["data-show-level"], b["aria-pressed"]) for b in buttons] == [
            ("50", "true"),
            ("40", "false"),
        ]
        sections = [a for t, a in Elements(html).elements if "data-level" in a]
        assert [a["data-level"] for a in sections] == ["50", "40"]
        assert all("hidden" not in a for a in sections)
        assert html.count("Your counter: level") == 2
        assert site.LEVEL_JS in html
    home = pages["index.html"]
    assert 'id="leaders"' in home and 'id="grunts"' in home
    assert "<h2>Best all-round</h2>" in home
    assert 'href="list/all.html">Full list' in home
    assert 'href="list/grunts.html">Best against any grunt →</a>' in home
    assert 'href="list/leaders.html">Best against any leader →</a>' in home
    assert "Full grunt list" not in home and "Full leader list" not in home
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


def hostile_reports(reports):
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
    return hostile, entry


def test_hostile_data_is_escaped(reports, tmp_path):
    hostile, entry = hostile_reports(reports)
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


def stale_character_reports(reports, mode):
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
    return entry


@pytest.mark.parametrize(
    "mode", ["key", "missing", "hidden", "name", "file_key", "manifest_key", "both_keys", "status"]
)
def test_stale_character_never_publishes_rows(reports, tmp_path, mode):
    entry = stale_character_reports(reports, mode)
    pages = build(reports, tmp_path / "site")
    html = pages[f"counters/{entry['slug']}.html"]
    assert "not calculated" in html
    assert '<details class="counter">' not in html
    assert "not calculated" in pages[f"list/{entry['slug']}.html"]
    assert "data-win=" not in pages[f"list/{entry['slug']}.html"]


def stale_overall_reports(reports, mode):
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


@pytest.mark.parametrize("mode", ["key", "status"])
def test_stale_overall_is_visible(reports, tmp_path, mode):
    stale_overall_reports(reports, mode)
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
            # Lists show each species once per order: its best moveset in that order.
            for row in site.shown(rows):
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
        assert (">Timing-sensitive</a>" in html) is (sensitive is True)
        assert ">Sensitive</a>" not in html
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
def test_filter_js_and_progressive_controls(reports, tmp_path):
    pages = build(reports, tmp_path / "site")
    sections = []
    for path, html in pages.items():
        if not path.startswith("list/"):
            continue
        assert site.FILTER_JS in html, path
        for level, body in re.findall(
            r'<section id="level-([^"]+)" data-level="[^"]+">(.*?)</section>', html, re.S
        ):
            elements = Elements(body).elements
            rows = [a for _, a in elements if "data-types" in a]
            filters = [a["data-filter"] for _, a in elements if "data-filter" in a]
            # Owner ruling: both orders are rendered; the alternative starts hidden.
            orders = {
                order: [a for _, a in Elements(block).elements if "data-types" in a]
                for order, block in re.findall(
                    r'<div data-order="([^"]+)"[^>]*>(.*?)</ol>', body, re.S
                )
            }
            if not rows:
                assert not filters
                continue
            assert level in ("40", "50")
            # Owner ruling: the type filter is collapsed by default and hidden without JS.
            assert '<details class="tyfilter" hidden><summary>Filter by type' in body
            assert '<details class="tyfilter" hidden open' not in body
            assert "<noscript>" in body
            types = {t for row in rows for t in json.loads(row["data-types"]) if t in site.TYPES}
            assert filters == ["", *sorted(types)], (path, level)
            if rows:
                assert set(orders) == {"speed", "hp"}, (path, level)
                assert len(orders["speed"]) == len(orders["hp"]) == len(rows) // 2
                assert '<div data-order="hp" hidden>' in body
            sections.append({"speed": orders["speed"], "hp": orders["hp"], "filters": filters})
    assert len(sections) >= 8  # Overall and character lists, at both levels.
    actual_harness = r"""
const specs=SPECS;
const mk=list=>list.map(r=>({dataset:{types:r['data-types'],win:r['data-win']},
  hidden:false,rank:{textContent:''},querySelector(){return this.rank;}}));
const sections=specs.map(spec=>{
 const speed=mk(spec.speed),hp=mk(spec.hp),rows=[...speed,...hp];
 const ols=[speed,hp].map(list=>({querySelectorAll(){return list;}}));
 const controls={hidden:true},warning={hidden:true};
 const s={rows,speed,hp,controls,warning,querySelector(){return warning;},
  querySelectorAll(q){return q==='[data-filter]'?this.buttons:q==='ol.rows'?ols:
   q==='[data-order="speed"] [data-types]'?speed:rows;}};
 s.buttons=spec.filters.map(t=>({dataset:{filter:t},textContent:t,closest(){return s;},
  setAttribute(k,v){this[k]=v;}}));
 return s;
});
globalThis.document={querySelectorAll(q){return sections.flatMap(s=>
 q==='.tyfilter'?[s.controls]:s.buttons);}};
SCRIPT
const assert=require('node:assert/strict');
for(const s of sections){
 assert.equal(s.controls.hidden,false);
 for(const b of [...s.buttons.slice(1),s.buttons[0]]){
  const others=sections.filter(x=>x!==s).map(x=>x.rows.map(r=>[r.hidden,r.rank.textContent]));
  b.onclick();
  const shown=list=>list.filter(r=>b.dataset.filter===''||
   JSON.parse(r.dataset.types).includes(b.dataset.filter));
  for(const list of [s.speed,s.hp]){
   const visible=shown(list);
   assert.deepEqual(list.filter(r=>!r.hidden),visible);
   assert.deepEqual(visible.map(r=>r.rank.textContent),visible.map((r,i)=>i+1));
  }
  const visible=shown(s.speed);
  assert.equal(s.warning.hidden,visible.length===0||Number(visible[0].dataset.win)>=.5);
  assert.deepEqual(s.buttons.map(x=>x['aria-pressed']),s.buttons.map(x=>x===b));
  assert.deepEqual(sections.filter(x=>x!==s).map(x=>x.rows.map(r=>[r.hidden,r.rank.textContent])),others);
 }
}
""".replace("SPECS", json.dumps(sections)).replace("SCRIPT", site.FILTER_JS)
    subprocess.run(["node", "-e", actual_harness], check=True, capture_output=True, text=True)
    harness = r"""
const rows=[['water',.9],['fire',.4],['fire',.2]].map(([t,v])=>({
 dataset:{types:JSON.stringify([t]),win:String(v)},hidden:false,rank:{textContent:''},
 querySelector(){return this.rank;}}));
const controls={hidden:true},warning={hidden:true};
const label={textContent:''};
const ol={querySelectorAll(){return rows;}};
const section={querySelector(q){return q==='[data-filter-label]'?label:warning;},
 querySelectorAll(s){return s==='[data-filter]'?[button]:s==='ol.rows'?[ol]:rows;}};
const button={dataset:{filter:'fire'},textContent:' fire ',closest(){return section;},
 setAttribute(){}};
globalThis.document={querySelectorAll(s){return s==='.tyfilter'?[controls]:[button];}};
SCRIPT
button.onclick();
console.log(JSON.stringify({hidden:controls.hidden,warning:warning.hidden,label:label.textContent,
 rows:rows.map(r=>[r.hidden,r.rank.textContent])}));
""".replace("SCRIPT", site.FILTER_JS)
    result = subprocess.run(["node", "-e", harness], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == {
        "hidden": False,
        "warning": False,
        "label": ": Fire",
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
    # Consumer red team: battle counts are not shown; only the rates are.
    assert "<th>n</th>" not in html
    assert "17" not in html and "n not recorded" not in html
    assert "999" not in html
    assert "<th>Win chance vs this Pokémon</th>" in html
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
    # Three complete rows at each level, once per order (Fastest and Most HP left).
    assert html.count('class="row"') == 12
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


@pytest.mark.parametrize(
    "rate,shown", [(0, True), (0.9496, True), (0.9499, True), (0.95, False), (1, False)]
)
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
        assert f"Hard ({int(rate * 1000) / 10:.1f}% win)" in html
        assert "95.0% win" not in html
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
    # Consumer red team: names print under the sprites, on a lighter circle.
    assert html.count('<span class="lname">') == 6
    assert '<span class="lname">Mon 0</span>' in html
    assert ".lname{font-size:.68rem;" in site.CSS and "max-width:64px" in site.CSS
    assert ".lineup .lsp{background:radial-gradient(circle,rgba(233,228,245,.7)" in site.CSS


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
    assert body.count('class="row"') == 10  # five per order
    assert "Counter 4" in body and "Counter 5" not in body
    card = site.tile("Giovanni", "list/giovanni.html", {}, {"40": rows}, "", rank="boss")
    assert card.count("<li>") == 6  # three per order
    assert "Counter 2" in card and "Counter 3" not in card
    assert '<span class="rk-badge">Boss</span>' in card


ESTIMATE_WORDS = re.compile(
    r"\b(?:estimates?|est|unverified|extrapolated|parity-only|assumed|not yet checked|"
    r"caveats?|ignores|model choice|sensitivity check)\b",
    re.I,
)


class VisibleText(HTMLParser):
    """Visible text and title/aria-label values outside the disclaimer, scripts and styles."""

    def __init__(self, html):
        super().__init__()
        self.skip, self.depth, self.text, self.bar = [], 0, [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if not self.skip and "disc" not in classes:
            self.text.extend(attrs[key] for key in ("title", "aria-label") if attrs.get(key))
        if tag in ("br", "img", "meta", "link", "input"):
            return
        self.depth += 1
        if tag in ("script", "style") or "disc" in classes:
            self.skip.append(self.depth)

    def handle_endtag(self, tag):
        if tag in ("br", "img", "meta", "link", "input"):
            return
        if self.skip and self.skip[-1] == self.depth:
            self.skip.pop()
        self.depth -= 1

    def handle_data(self, data):
        (self.bar if self.skip else self.text).append(data)


@pytest.mark.parametrize(
    "variant",
    ["normal", "hostile", "overall-key", "overall-status"]
    + [
        f"character-{mode}"
        for mode in (
            "key",
            "missing",
            "hidden",
            "name",
            "file_key",
            "manifest_key",
            "both_keys",
            "status",
        )
    ],
)
def test_estimate_idea_appears_once_per_page_in_the_bar(reports, tmp_path, variant):
    # Owner ruling: "this is an estimate / unverified / assumed" is said once per page, in the
    # site-wide bar linking to how.html. Only how.html explains it in full.
    if variant == "hostile":
        hostile_reports(reports)
    elif variant.startswith("overall-"):
        stale_overall_reports(reports, variant.removeprefix("overall-"))
    elif variant.startswith("character-"):
        stale_character_reports(reports, variant.removeprefix("character-"))
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


@pytest.mark.parametrize(
    "word", ["caveat", "caveats", "ignores", "model choice", "sensitivity check"]
)
@pytest.mark.parametrize(
    "template", ["<p>{}</p>", '<img title="{}">', '<button aria-label="{}"></button>']
)
def test_estimate_check_covers_visible_text_and_attributes(word, template):
    assert ESTIMATE_WORDS.search(" ".join(VisibleText(template.format(word)).text))
    bar = '<div class="disc"><span title="{}" aria-label="{}">{}</span></div>'
    assert not ESTIMATE_WORDS.search(" ".join(VisibleText(bar.format(word, word, word)).text))
    assert not ESTIMATE_WORDS.search("stale; not calculated; older than the per-type lists")


@pytest.mark.parametrize(
    "contents",
    [
        "{",
        "null",
        "[]",
        "{}",
        '{"tree": null}',
        '{"tree": {}}',
        '{"tree": [null]}',
        '{"tree": ["file"]}',
        '{"tree": [{}]}',
        '{"tree": [{"path": 42}]}',
    ],
)
def test_malformed_sprite_tree_has_clean_cli_error(reports, cache, tmp_path, capsys, contents):
    tree = tmp_path / "tree.json"
    tree.write_text(contents)
    with pytest.raises(SystemExit) as exc:
        cli.main(
            ["site-sprites", "--data", str(reports), "--cache-dir", str(cache), "--tree", str(tree)]
        )
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "usage:" in captured.err
    assert "error: invalid sprite tree:" in captured.err
    assert "Traceback" not in captured.err


def test_sprite_file_selection(reports, tmp_path, monkeypatch, capsys):
    import hashlib

    species = {
        "palkia": 484,
        "palkia_origin": 484,
        "giratina_origin": 487,
        "darmanitan_standard": 555,
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
        "zygarde": 718,
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
        "pm487.icon.png",
        "pm487.fALTERED.icon.png",
        "pm487.fORIGIN.icon.png",
        "pm555.fGALARIAN_STANDARD.icon.png",
        "pm555.fSTANDARD.icon.png",
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
        "pm718.fCOMPLETE.icon.png",
        "pm718.fFIFTY_PERCENT.icon.png",
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
        "darmanitan_standard pm555.fSTANDARD.icon.png",
        "forms pm3.fA.icon.png",
        "giratina_origin pm487.fORIGIN.icon.png",
        "growlithe_hisuian pm58.fHISUIAN.icon.png",
        "normal pm2.fNORMAL.icon.png",
        "palkia_origin pm484.fORIGIN.icon.png",
        "plain pm1.icon.png",
        "raichu_alolan pm26.fALOLA.icon.png",
        "wooper_paldean pm194.fPALDEA.icon.png",
        # Owner ruling: Zygarde shows its Complete form (replaces the earlier 50% default).
        "zygarde pm718.fCOMPLETE.icon.png",
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


def test_grunt_order_and_steel_display_name():
    names = [
        "Water grunt (male)",
        "Decoy grunt (female)",
        "Metal grunt (male)",
        "Mixed grunt (male)",
        "Bug grunt (male)",
        "Water grunt (female)",
        "Metal grunt (female)",
        "Mixed grunt (female)",
    ]
    ordered = [site.display_name(n) for n in sorted(names, key=site.grunt_order)]
    assert ordered == [
        "Bug grunt (male)",
        "Steel grunt (female)",
        "Steel grunt (male)",
        "Water grunt (female)",
        "Water grunt (male)",
        "Mixed grunt (female)",
        "Mixed grunt (male)",
        "Decoy grunt (female)",
    ]
    assert site.display_name("Cliff") == "Cliff"
    assert site.display_name("Metalgross grunt") == "Metalgross grunt"


def test_home_grunt_grid_order_and_steel_pages(reports, tmp_path):
    manifest = read(reports, "manifest.json")
    entry = next(e for e in manifest["characters"] if e["name"] == "Fairy grunt (female)")
    leaders = [e["name"] for e in manifest["characters"] if e.get("rank") != "grunt"]

    def rename(data):
        for item in data["characters"]:
            if item["name"] == entry["name"]:
                item.update(name="Metal grunt (male)", slug="metal-grunt-male")

    change(reports, "manifest.json", rename)
    change(reports, entry["file"], lambda d: d["character"].update(name="Metal grunt (male)"))
    pages = build(reports, tmp_path / "site")
    # Slugs and files keep the game data's name; only the display changes.
    assert "list/metal-grunt-male.html" in pages and "counters/metal-grunt-male.html" in pages
    for html in pages.values():
        assert "Metal grunt" not in html
    for kind, suffix in (("list", "top counters"), ("counters", "counters")):
        html = pages[f"{kind}/metal-grunt-male.html"]
        assert f"<title>Steel grunt (male) · {suffix}</title>" in html
        assert "Steel grunt (male)</h1>" in html
        assert 'class="ty ty-steel"' in html
    home = pages["index.html"]
    grunts = home.split('id="grunts"', 1)[1]
    titles = re.findall(r"<h3>([^<]*)</h3>", grunts)
    assert titles == ["Empty grunt (female)", "Steel grunt (male)"]
    assert 'href="list/metal-grunt-male.html"' in grunts
    leader_titles = re.findall(r"<h3>([^<]*)</h3>", home.split('id="leaders"', 1)[1])
    assert leader_titles[: len(leaders)] == leaders


def test_percent_line_and_shadow_tooltip(reports, tmp_path):
    pages = build(reports, tmp_path / "site")
    line = f'<p class="hint pct">{escape(site.PERCENT_LINE)}</p>'
    for path, html in pages.items():
        if path.startswith("list/") or path == "index.html":
            assert html.count(line) == 1, path
            assert html.index("<h2>") < html.index(line)
        else:
            assert line not in html, path
    shadow = site.content_tags({"speciesId": "example_shadow"})
    assert shadow == f'<span class="tag sh" title="{site.SHADOW_TITLE}">Shadow</span>'
    assert "Shadow form: hits harder, takes more damage" == site.SHADOW_TITLE
    assert "Hits harder, takes more damage." in pages["how.html"]


def test_how_is_an_explainer_with_faq_then_one_collapsed_tech_section(reports, tmp_path):
    # Owner ruling: option A (explainer + FAQ) for how.html.
    pages = build(reports, tmp_path / "site")
    how = pages["how.html"]
    tech_at = how.index('<details class="tech">')
    plain = how[:tech_at]
    assert site.PERCENT_LINE.replace("%", "") in plain
    assert plain.count('class="step"') == 3
    for title in ("Quick check", "Full battles", "Win %"):
        assert title in plain, title
    for anchor in ("pause", "elite-tm", "shadow", "two-charged"):
        assert f'id="{anchor}"' in plain
    for question, _ in site.FAQ:
        assert escape(question) in plain, question
    assert plain.count("<details") == len(site.FAQ)
    for words in ("The battle setup", "Level 50 or 40", "Sources", "14 Nov 2026"):
        assert words in plain, words
    assert how.count('<details class="tech"><summary>Full technical notes</summary>') == 1
    tech = how[tech_at:]
    assert "</details></main>" in tech
    for heading in (
        "Validation and provenance",
        "Assumptions",
        "Rocket pause and sensitivity",
        "Rows that differ from the usual grade",
        "Grade vocabulary",
        "coverage",
        "Sources, credits and limitations",
    ):
        assert heading in tech, heading
    characters = read(reports, "manifest.json")["characters"]
    for entry in characters:
        assert f'id="c-{entry["slug"]}"' in tech
    # Notes every character shares are printed once, not once per character.
    limitations = escape(read(reports, "overall.json")["limitations"])
    assert how.count(limitations) <= 2
    # The plain pause sentence and the technical explanation each appear once.
    assert how.count(escape(site.PAUSE_PLAIN)) == 1
    assert how.count("Pause band is a sensitivity check") == 1
    assert len(re.findall(r"<li><b>[^<]*:</b> (?:more than|band not)", how)) == len(characters)
    ids = [a["id"] for _, a in Elements(how).elements if "id" in a]
    assert len(ids) == len(set(ids))


def test_method_notes_print_shared_blocks_once_and_name_differences():
    sections = [
        ("Cliff", "cliff", "", ("<p>same</p>", "<p>cliff only</p>")),
        ("Arlo", "arlo", "", ("<p>same</p>", "<p>arlo only</p>")),
        ("Empty", "empty", "no results", ("<p>same</p>", "<p>cliff only</p>")),
    ]
    html = site.method_notes(sections)
    assert html.count("<p>same</p>") == 1
    assert "Shared by every grunt and leader" in html
    assert html.count("<p>cliff only</p>") == 2
    assert html.count("<p>arlo only</p>") == 1
    for slug in ("cliff", "arlo", "empty"):
        assert f'id="c-{slug}"' in html
    assert "no results" in html
    single = site.method_notes([("Cliff", "cliff", "", ("<p>same</p>",))] * 2)
    assert "Nothing beyond the shared notes." in single
    assert site.method_notes([]) == ""


def test_timing_line_has_card_padding():
    # Owner report: the one-line Timing-sensitive note ran flush to the Giovanni card edge.
    assert ".cc .timing-all{padding:" in site.CSS


def test_battle_details_use_plain_words(reports, tmp_path):
    pages = build(reports, tmp_path / "site")
    checked = 0
    for path, html in pages.items():
        if not path.startswith("counters/") or '<details class="counter">' not in html:
            continue
        checked += 1
        text = " ".join(VisibleText(html).text)
        for jargon in (
            "Stage-1",
            "stage-1",
            "Conditional",
            "conditional",
            "n not recorded",
            "Screen slot",
            "Calc summary",
            "Rocket species",
            "Solo sweep",
            "Rocket KOs",
            "Pause band",
            "grid",
            "1v1",
        ):
            assert jargon not in text, (path, jargon)
        assert "Quick 1-on-1 check" in text
        assert "Win chance vs this Pokémon" in text
        assert "<th>n</th>" not in html
    assert checked


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable for inline JS check")
@pytest.mark.parametrize("stored,expected", [(None, "50"), ("40", "40"), ("99", "50")])
def test_level_switch_remembers_choice_default_50(stored, expected):
    # Owner ruling: remember the last chosen level per browser; level 50 is the default.
    harness = r"""
const store=new Map(STORED===null?[]:[['pogo-level',STORED]]);
globalThis.localStorage={getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>store.set(k,v)};
const buttons=['50','40'].map(level=>({dataset:{showLevel:level},pressed:'',
 setAttribute(k,v){this.pressed=String(v);}}));
const sections=['50','40'].map(level=>({dataset:{level},hidden:false}));
const control={hidden:true};
const card={querySelector(){return control;},querySelectorAll(s){
 return s==='[data-show-level]'?buttons:s==='[data-level]'?sections:[];}};
globalThis.document={querySelectorAll(s){return s==='[data-levels]'?[card]:[];}};
SCRIPT
const shown=sections.find(s=>!s.hidden).dataset.level;
buttons[1].onclick();
console.log(JSON.stringify({shown,saved:store.get('pogo-level')}));
""".replace("STORED", json.dumps(stored)).replace("SCRIPT", site.LEVEL_JS)
    result = subprocess.run(["node", "-e", harness], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == {"shown": expected, "saved": "40"}


def test_timing_sensitive_one_line_when_every_row_has_it():
    # Owner ruling: when every counter in a list is timing-sensitive, show one line instead
    # of the badge on every row; a mixed list keeps per-row badges.
    sensitive = {"pause_band": {"sensitive": True}}
    rows = [
        {
            "speciesId": f"mon{i}",
            "types": ["water"],
            "win_rate": 0.5,
            "fast_move": "A",
            "charged_move": "B",
            **sensitive,
        }
        for i in range(3)
    ]
    html = site.counter_rows(rows, site.Sprites())
    assert html.count("Timing-sensitive</a>") == 1 and "timing-all" in html
    rows[1]["pause_band"] = {"sensitive": False}
    html = site.counter_rows(rows, site.Sprites())
    assert html.count("Timing-sensitive</a>") == 2 and "timing-all" not in html


@pytest.mark.parametrize(
    "saved,expected", [(None, "speed"), ("hp", "hp"), ("speed", "speed"), ("bogus", "speed")]
)
def test_order_switch_defaults_to_fastest_and_remembers(saved, expected):
    # Owner ruling: speed first by default, a remembered "Most HP left" toggle.
    harness = r"""
const store={v:SAVED};
globalThis.localStorage={getItem(){return store.v;},setItem(k,v){store.k=k;store.v=v;}};
const blocks=['speed','hp','speed','hp'].map(o=>({dataset:{order:o},hidden:o!=='speed'}));
const buttons=['speed','hp'].map(o=>({dataset:{sortChoice:o},setAttribute(k,v){this[k]=v;}}));
const sw={hidden:true};
globalThis.document={querySelectorAll(q){return q==='[data-sort-choice]'?buttons:
 q==='[data-order]'?blocks:q==='.sortsw'?[sw]:[];}};
SCRIPT
const first=blocks.filter(b=>!b.hidden).map(b=>b.dataset.order);
const pressed=buttons.map(b=>b['aria-pressed']);
buttons[1].onclick();
console.log(JSON.stringify({first,pressed,sw:sw.hidden,after:blocks.filter(b=>!b.hidden)
 .map(b=>b.dataset.order),stored:[store.k,store.v]}));
""".replace("SAVED", json.dumps(saved)).replace("SCRIPT", site.ORDER_JS)
    result = subprocess.run(["node", "-e", harness], check=True, capture_output=True, text=True)
    out = json.loads(result.stdout)
    assert out["first"] == [expected, expected]
    assert out["pressed"] == [expected == "speed", expected == "hp"]
    assert out["sw"] is False
    assert out["after"] == ["hp", "hp"]
    assert out["stored"] == ["pogo-sort", "hp"]


def test_lists_render_fastest_then_most_hp_orders_with_time():
    rows = [
        {
            "speciesId": "tank",
            "win_rate": 1.0,
            "mean_turns": 40,
            "mean_player_hp_fraction_left": 0.9,
        },
        {
            "speciesId": "fast",
            "win_rate": 1.0,
            "mean_turns": 20,
            "mean_player_hp_fraction_left": 0.5,
        },
        {"speciesId": "loser", "win_rate": 0.5, "mean_turns": 5, "mean_player_hp_fraction_left": 1},
    ]
    body = site.list_body({}, {"40": rows}, "")
    speed, hp = (
        re.search(rf'<div data-order="{o}"[^>]*>(.*?)</ol>', body, re.S).group(1)
        for o in ("speed", "hp")
    )
    assert speed.index("Fast") < speed.index("Tank") < speed.index("Loser")
    assert hp.index("Tank") < hp.index("Fast") < hp.index("Loser")
    assert '<div data-order="hp" hidden>' in body
    assert "<span>~10 s</span>" in speed and "<span>~20 s</span>" in speed
    assert body.count('class="sortsw"') == 1 and "Most HP left" in body
    tile = site.tile("Cliff", "list/cliff.html", {}, {"40": rows}, "")
    first = [
        re.search(r"<li>.*?<span>(\w+)", b, re.S).group(1)
        for b in re.findall(r'<div data-order="[^"]+"[^>]*>(.*?)</div>', tile, re.S)
    ]
    assert first == ["Fast", "Tank"]


def test_lists_show_each_species_once_per_order():
    rows = [
        {
            "speciesId": sp,
            "id": name,
            "win_rate": w,
            "mean_player_hp_fraction_left": h,
            "mean_turns": t,
        }
        for sp, name, w, h, t in (
            ("goodra", "fast", 1.0, 0.5, 20),
            ("goodra", "bulky", 1.0, 0.8, 30),
            ("goodra", "neither", 1.0, 0.4, 40),
            ("palkia", "palkia", 0.982, 0.6, 48),
            ("palkia_shadow", "shadow", 0.981, 0.5, 42),
        )
    ]
    assert [r["id"] for r in site.ordered(rows)] == ["fast", "shadow", "palkia"]
    assert [r["id"] for r in site.ordered(rows, "hp")] == ["bulky", "palkia", "shadow"]
    # Battle details: every row either order shows, in the default order.
    assert [r["id"] for r in site.shown(rows)] == ["fast", "bulky", "shadow", "palkia"]


def test_character_card_top3_picks_each_orders_best_moveset():
    """Reviewer repro: HP order must see goodra's bulky moveset, not the speed-cut list."""
    rows = [
        {
            "speciesId": sp,
            "win_rate": w,
            "mean_player_hp_fraction_left": h,
            "mean_turns": t,
            "fast_move": move,
        }
        for sp, move, w, h, t in (
            ("goodra", "FAST", 1.0, 0.5, 20),
            ("goodra", "BULKY", 1.0, 0.95, 30),
            ("palkia", "P", 1.0, 0.9, 25),
        )
    ]
    html = site.tile("Ghost", "list/ghost.html", {}, {"50": rows}, "")
    hp_block = html.split('data-order="hp"')[1]
    speed_block = html.split('data-order="speed"')[1].split('data-order="hp"')[0]
    # Speed: goodra (fast) then palkia. HP: goodra (bulky, 95%) still first, then palkia.
    assert speed_block.index("Goodra") < speed_block.index("Palkia")
    assert hp_block.index("Goodra") < hp_block.index("Palkia")


def test_two_charged_moves_tag_and_anchor():
    row = {
        "speciesId": "metagross",
        "fast_move": "BULLET_PUNCH",
        "charged_move": "EARTHQUAKE+METEOR_MASH",
        "charged_moves": ["EARTHQUAKE", "METEOR_MASH"],
    }
    markup = site.moves(row, "../")
    assert "Earthquake</span> + <span" in markup
    assert 'href="../how.html#two-charged"' in markup
    assert 'title="Model: cheap move into the leader\'s shields, then the hardest hit"' in markup
    assert ">2 charged</a>" in markup
    assert (
        len(
            site.ordered(
                [
                    {**row, "win_rate": 1, "mean_turns": 1, "mean_player_hp_fraction_left": 1},
                    {**row, "win_rate": 0.5, "mean_turns": 2, "mean_player_hp_fraction_left": 0.5},
                ]
            )
        )
        == 1
    )
