"""Offline, escaped static HTML views over manifest-listed precompute reports."""

import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import date
from html import escape
from pathlib import Path

PAUSE_NOTE = (
    "Rankings depend strongly on the modelled Rocket pause after each charged attack "
    "(verification ledger row k); its trigger is an owner observation and not measured."
)
CSS = """
:root{--bg:#eef0ec;--panel:#fbfbf8;--ink:#1d2321;--muted:#5d6762;--line:#d3d8d2;
--accent:#1f5f8b;--win:#2f7d4f;--amber:#9a6200;--violet:#6a4c9c;
--display:"Arial Narrow",sans-serif;--body:system-ui,sans-serif;--mono:ui-monospace,monospace}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
--bg:#121615;--panel:#1a1f1d;--ink:#e3e8e4;
--muted:#99a49e;--line:#2d3532;--accent:#6fb0dc;--win:#5cc086;--amber:#e3a646;
--violet:#ad94dd;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#121615;--panel:#1a1f1d;--ink:#e3e8e4;--muted:#99a49e;
--line:#2d3532;--accent:#6fb0dc;--win:#5cc086;--amber:#e3a646;--violet:#ad94dd;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 var(--body)}main{max-width:1180px;margin:auto;padding:28px 16px 80px;
display:grid;gap:18px}h1,h2,h3{font-family:var(--display);margin:0;letter-spacing:.01em}
h1{font-size:2rem}h2{font-size:1.45rem}h3{font-size:1.1rem}p{margin:0}a{color:var(--accent)}
nav,.controls{display:flex;flex-wrap:wrap;gap:8px}nav a{font:600 .85rem var(--display);
text-decoration:none;border:1px solid var(--line);padding:4px 10px;border-radius:4px}
a:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);
outline-offset:2px}.screen{background:var(--panel);border:1px solid var(--line);
border-radius:8px;overflow:hidden}.screen-title{padding:12px 14px 8px}.sub,.moves{
color:var(--muted);font-size:.84rem}.trust{display:flex;flex-wrap:wrap;gap:6px;
padding:8px 14px;border-block:1px solid var(--line);background:var(--bg)}
.chip{display:inline-block;font:500 .74rem var(--mono);border:1px solid var(--line);
border-radius:3px;padding:1px 6px;background:var(--panel);overflow-wrap:anywhere}
.chip.est{border-color:var(--ink);font-weight:600}.warn{color:var(--amber)}
.chip.warn{border-color:var(--amber)}.assume{padding:6px 14px;color:var(--muted);font-size:.86rem}
.body{padding:12px 14px;display:grid;gap:12px}.wrap{overflow-x:auto}table{border-collapse:collapse;
width:100%;font-variant-numeric:tabular-nums;font-size:.9rem}th,td{padding:6px 8px;
border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font:600 .78rem
var(--display);color:var(--muted);text-transform:uppercase;white-space:nowrap}
.num{font-family:var(--mono);text-align:right;white-space:nowrap}.est-mark{font:500 .62rem
var(--mono);color:var(--muted);vertical-align:super;margin-left:2px}.mon{font-weight:600}
.notes{padding:10px 14px 14px;border-top:1px solid var(--line);display:grid;gap:5px;
font-size:.82rem;color:var(--muted);overflow-wrap:anywhere}.notes b{color:var(--ink)}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px}
.tile{border:1px solid var(--line);border-radius:6px;padding:10px;display:grid;gap:6px;
align-content:start;min-width:0}.tile.overall{border:2px solid var(--accent)}
.tile ol{margin:0;padding-left:1.2em}.tile li{font-size:.88rem}.tile .trust,.tile .notes{
padding:6px}.legend{font-size:.78rem;color:var(--muted)}button.t{font:500 .78rem var(--mono);
border:1px solid var(--line);background:var(--panel);color:var(--ink);padding:3px 8px;
border-radius:12px;cursor:pointer}button[aria-pressed=true]{background:var(--ink);
color:var(--panel)}details.counter{border-bottom:1px solid var(--line)}summary{cursor:pointer}
summary.row{display:list-item;padding:8px 0}.metrics{display:grid;
grid-template-columns:32px 2.4fr repeat(6,minmax(74px,1fr)) 1.8fr;gap:8px;align-items:start;
min-width:960px}.counter-head{font:600 .78rem var(--display);color:var(--muted);
text-transform:uppercase}.detail{padding:12px;background:var(--bg);display:grid;gap:12px}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
clip:rect(0,0,0,0);white-space:nowrap;border:0}
[hidden]{display:none!important}@media(max-width:640px){main{padding-inline:8px}}
"""
# Filtering only hides server-rendered rows. Without JS all rows and levels remain available.
FILTER_JS = """document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{
const s=b.closest('section'),t=b.dataset.filter;
s.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',x===b));
s.querySelectorAll('tr[data-types]').forEach(r=>r.hidden=t!==''&&!JSON.parse(r.dataset.types).includes(t));
const rows=[...s.querySelectorAll('tr[data-types]')].filter(r=>!r.hidden);
const best=Number(rows[0]?.dataset.win||0);
rows.forEach((r,i)=>{r.querySelector('[data-rank]').textContent=i+1;
r.querySelector('[data-best]').textContent=best?(Number(r.dataset.win)/best*100).toFixed(1)+'%':'—';});
});"""


def e(value):
    return escape(str(value), quote=True)


def chip(value, kind=""):
    return f'<span class="chip {kind}">{e(value)}</span>'


def grades(value, flags=()):
    parts = str(value).split("; ") if value else []
    if "extrapolated" in flags and "extrapolated forward" not in parts:
        parts.append("extrapolated forward")
    return " ".join(
        chip(
            p,
            "est"
            if p == "estimate"
            else "warn"
            if any(word in p for word in ("unverified", "incomplete", "extrapolated"))
            else "",
        )
        for p in parts
    )


def estimate(value, *, percent=False):
    if value is None:
        return '<span class="moves">not recorded</span>'
    formatted = f"{value * 100:.1f}%" if percent else f"{value:.2f}".rstrip("0").rstrip(".")
    return f'{e(formatted)}<span class="est-mark" title="estimate">est</span>'


def provenance(data):
    stamp = data.get("computed_for_battle_date", data.get("battle_date", "not recorded"))
    source = data.get(
        "computed_for_battle_date_source", data.get("battle_date_source", "not recorded")
    )
    valid = data.get("valid_for", {})
    era = valid.get("era", data.get("era", "not recorded"))
    return (
        f'<p class="moves">Computed for battle date {e(stamp)} · battle_date_source: '
        f"{e(source)} · valid_for era: {e(era)}</p>"
        + (chip("extrapolated forward", "warn") if valid.get("extrapolated") else "")
    )


def assumptions(data, level):
    params = data.get("params", {})
    ivs = params.get("ivs", {})
    iv_text = "/".join(str(ivs.get(k, "not recorded")) for k in ("atk", "def", "hp"))
    policy = data.get("player_policy", "not recorded")
    shields = data.get("player_shield_policy", "not recorded")
    policy = {
        "ChargedWhenReady": "uses charged moves when ready (first affordable move)",
        "FastOnly": "uses fast moves only",
    }.get(policy, str(policy).replace("_", " "))
    shields = {
        "first_two": "shields the first two charged attacks",
        "never": "never shields",
        "threshold": "shields according to the configured HP threshold",
    }.get(shields, str(shields).replace("_", " "))
    move_note = (
        "elite/legacy excluded"
        if data.get("exclude_elite_legacy")
        else "elite/legacy included and badged"
    )
    return (
        f'<div class="assume">You: level {e(level)} · IVs {e(iv_text)} · trainer level '
        f"{e(params.get('trainer_level', 'not recorded'))} · Mega excluded (unsupported) · "
        f"{e(move_note)} · player {e(policy)} · player {e(shields)}. "
        f"{e(data.get('filter_note', 'Filter note not recorded'))}</div>"
    )


def trust(data, level):
    validation = data.get("validation", {})
    label = data.get("validation_label", "Validation label not recorded")
    failed = validation.get("validated") is False or any(
        word in label.casefold() for word in ("unvalidated", "gate failed")
    )
    discrepancies = validation.get("open_discrepancies", [])
    ids = [str(r.get("id", r.get("fixture", ""))) for r in discrepancies]
    strip = chip("every number is an estimate", "est") + chip(label)
    if failed:
        strip += chip("UNVALIDATED", "warn")
    strip += chip("open discrepancies: " + (", ".join(ids) or "none recorded"), "warn")
    strip += chip(data.get("rcpm_note") or "rCPM note not recorded")
    strip += chip(PAUSE_NOTE, "warn")
    return f'<div class="trust">{strip}</div>{provenance(data)}{assumptions(data, level)}'


def notes(data):
    fields = (
        ("Model notes", "limitations"),
        ("Rocket moveset pool", "moveset_pool_note"),
        ("Equal-weight model", "weighting_note"),
        ("Screen caveat", "screen_note"),
        ("Validation", "validation_label"),
        ("Credits", "credits"),
    )
    body = "".join(
        f"<p><b>{title}.</b> {e(data.get(key, 'not recorded'))}</p>" for title, key in fields
    )
    body += f"<p>{e(PAUSE_NOTE)}</p><p>Dates before 2019-07-22 are rejected.</p>"
    for source in data.get("sources", []):
        body += (
            "<p><b>Source.</b> "
            + " · ".join(e(source.get(k, "not recorded")) for k in ("name", "license", "url"))
            + f" · fetched_at {e(source.get('fetched_at', 'not recorded'))}</p>"
        )
    return f'<footer class="notes">{body}</footer>'


def document(title, data, body, nav, *, level="40", script=False):
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{e(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
        f'<nav aria-label="Pages">{nav}</nav>\n<div class="screen">'
        f'<header class="screen-title"><h1>{e(title)}</h1></header>\n{trust(data, level)}\n'
        f'<div class="body">{body}</div>\n{notes(data)}\n</div>\n</main>\n'
        + (f"<script>{FILTER_JS}</script>\n" if script else "")
        + "</body>\n</html>\n"
    )


def label(identifier):
    """Readable PvPoke id: DRAGON_BREATH -> Dragon Breath; the shadow chip carries the form."""
    words = str(identifier).removesuffix("_shadow").replace("_", " ").split()
    return " ".join(w.capitalize() for w in words)


def counter_name(row):
    def move(key):
        name = row.get(key, "not recorded")
        flags = row.get("move_flags", {}).get(name, {})
        return f'<span title="{e(name)}">{e(label(name))}</span>' + "".join(
            chip(k) for k in ("elite", "legacy") if flags.get(k)
        )

    species = row.get("speciesId", row.get("species", "not recorded"))
    return (
        f'<span class="mon" title="{e(species)}">{e(label(species))}</span> '
        + (chip("shadow") if row.get("form") == "shadow" else "")
        + '<span class="moves" style="display:block">'
        + f"{move('fast_move')} · {move('charged_move')}</span>"
    )


def coverage(view):
    text = view.get("coverage", {}).get("text", "coverage not recorded")
    return f"<p>{e(text)}</p>{chip('equal weights: model choice')}"


def unavailable(reason):
    return f"<p>{chip('not calculated', 'warn')} {e(reason)}</p>"


def ordered(rows):
    return sorted(
        rows,
        key=lambda r: (
            -r["win_rate"],
            -r.get("mean_player_hp_fraction_left", 0),
            r.get("mean_turns", 0),
        ),
    )


def levels(data, results):
    return sorted(
        {"40", "50", *results, *(f"{v:g}" for v in data.get("params", {}).get("levels", []))},
        key=float,
    )


def list_body(data, results, reason, extra=""):
    level_keys = levels(data, results)
    body = (
        extra
        + '<nav aria-label="Levels">'
        + "".join(f'<a href="#level-{e(v)}">Level {e(v)}</a>' for v in level_keys)
        + '</nav><p class="legend">Badges: elite = elite move; legacy = legacy move. '
    )
    body += "Ranked by win rate, HP left, then turns. % of best uses the current filtered view.</p>"
    for level in level_keys:
        rows = ordered(results.get(level, []))
        body += (
            f'<section id="level-{e(level)}"><h2>Level {e(level)}</h2>{assumptions(data, level)}'
        )
        if not rows:
            body += unavailable(reason or "no full results at this level") + "</section>"
            continue
        types = sorted({t for row in rows for t in row.get("types", [])})
        body += '<div class="controls" role="group" aria-label="Attacker types">'
        body += '<button class="t" data-filter="" aria-pressed="true">All types</button>'
        body += "".join(
            f'<button class="t" data-filter="{e(t)}" aria-pressed="false">{e(t)}</button>'
            for t in types
        )
        body += (
            '</div><p class="moves">Without JavaScript all types are shown.</p>'
            '<div class="wrap"><table><thead><tr>'
        )
        body += "".join(
            f"<th>{t}</th>"
            for t in (
                "#",
                "Counter",
                "Types",
                "Win rate",
                "% of best",
                "Rocket KOs",
                "HP left",
                "Grade",
            )
        )
        body += "</tr></thead><tbody>"
        best = rows[0]["win_rate"]
        for rank, row in enumerate(rows, 1):
            ratio = row["win_rate"] / best if best else None
            body += (
                f'<tr data-types="{e(json.dumps(row.get("types", [])))}" '
                f'data-win="{e(row["win_rate"])}">'
            )
            types_text = " / ".join(row.get("types", [])) or "types not recorded"
            body += f"<td data-rank>{rank}</td><td>{counter_name(row)}</td>"
            body += f"<td>{e(types_text)}</td>"
            body += f'<td class="num">{estimate(row["win_rate"], percent=True)}</td>'
            ratio_text = f"{ratio * 100:.1f}%" if ratio is not None else "—"
            body += (
                f'<td class="num"><span data-best>{e(ratio_text)}</span>'
                '<span class="est-mark" title="estimate">est</span></td>'
            )
            body += f'<td class="num">{estimate(row.get("mean_rocket_knocked_out"))}</td>'
            hp = estimate(row.get("mean_player_hp_fraction_left"), percent=True)
            body += f'<td class="num">{hp}</td>'
            body += f"<td>{grades(row.get('grade'), row.get('flags', []))}</td></tr>"
        body += "</tbody></table></div></section>"
    return body


def calc_summary(rows, grade_order):
    """Retain only ranges and weakest cell grades, never individual moveset rows."""
    grouped = defaultdict(lambda: defaultdict(list))
    columns = ("fast_damage", "fast_hits_to_ko", "charged", "rocket_fast_damage", "turns_survived")
    for row in rows:
        group = grouped[row["slot"]["value"], row["defender"]["value"]]
        for key in columns:
            cells = [row[key]]
            if key == "charged":
                damage = [m["damage"] for m in row[key]["value"]]
                if not damage:
                    continue
                best = max(c["value"] for c in damage)
                cells = [c for c in damage if c["value"] == best]
            group[key].extend((c["value"], c["grade"]) for c in cells)
    body = '<h3>Calc summary · ranges over Rocket movesets</h3><div class="wrap"><table><thead><tr>'
    body += (
        "".join(
            f"<th>{name}</th>"
            for name in (
                "Slot",
                "Rocket species",
                "Fast damage",
                "Fast hits to KO",
                "Best charged damage",
                "Rocket fast damage",
                "Turns survived",
            )
        )
        + "</tr></thead><tbody>"
    )
    for (slot, species), group in sorted(grouped.items()):
        body += (
            f"<tr data-calc-summary><td>{e(slot)}</td>"
            f'<td title="{e(species)}">{e(label(species))}</td>'
        )
        for key in columns:
            cells = group[key]
            if not cells:
                body += "<td>not recorded</td>"
                continue
            values, cell_grades = zip(*cells, strict=True)
            # Unknown grade vocabularies fail visibly rather than claiming a stronger grade.
            grade = max(
                cell_grades,
                key=lambda g: grade_order.index(g) if g in grade_order else len(grade_order),
            )
            body += (
                f'<td class="num">{estimate(min(values))}'
                + ("" if min(values) == max(values) else f"–{estimate(max(values))}")
                + f"<br>{chip(grade)}</td>"
            )
        body += "</tr>"
    return body + "</tbody></table></div>"


def counter_detail(row, data):
    body = '<div class="detail">'
    screen = row.get("screen", {})
    if screen:
        body += "<h3>Stage-1 screen · slot 1v1 win rates</h3>"
        body += f"<p>{grades(screen.get('grade'), screen.get('flags', []))}</p>"
        caveat = screen.get("grid_limitation", data.get("screen_note", "not recorded"))
        body += f'<p class="warn">Grid caveat: {e(caveat)}</p>'
        body += f'<p class="moves">{e(screen.get("note", data.get("screen_note", "")))}</p>'
        for slot, rate in enumerate(screen.get("slot_win_rates", []), 1):
            body += f"<p>Screen slot {slot}: {estimate(rate, percent=True)}</p>"
    body += "<h3>Full battle · conditional win rate per Rocket species in each slot</h3>"
    body += (
        '<div class="wrap"><table><thead><tr><th>Slot</th><th>Rocket species</th>'
        "<th>Conditional win rate</th></tr></thead><tbody>"
    )
    for slot in row.get("per_slot", []):
        for species in slot.get("species", []):
            body += (
                f"<tr><td>{e(slot['slot'])}</td><td>{e(label(species['species']))}</td>"
                f'<td class="num">{estimate(species["conditional_win_rate"], percent=True)}'
                "</td></tr>"
            )
    body += "</tbody></table></div>"
    body += calc_summary(row.get("calc_rows", []), [g["id"] for g in data.get("grades", [])])
    return body + "</div>"


def counters_body(data, results, reason):
    level_keys = levels(data, results)
    body = (
        '<nav aria-label="Levels">'
        + "".join(f'<a href="#level-{e(v)}">Level {e(v)}</a>' for v in level_keys)
        + '</nav><p class="legend">Badges: elite = elite move; legacy = legacy move. '
    )
    body += "Ranked by win rate, HP left, then turns. Expand a counter for its details.</p>"
    for level in level_keys:
        body += (
            f'<section id="level-{e(level)}"><h2>Level {e(level)}</h2>{assumptions(data, level)}'
        )
        rows = ordered(results.get(level, []))
        if not rows:
            body += unavailable(reason or "no full results at this level") + "</section>"
            continue
        body += '<div class="wrap"><div class="metrics counter-head" aria-hidden="true">'
        body += (
            "".join(
                f"<span>{name}</span>"
                for name in (
                    "#",
                    "Counter",
                    "Win rate",
                    "Draw",
                    "Rocket KOs",
                    "Solo sweep",
                    "HP left",
                    "Turns",
                    "Grade",
                )
            )
            + "</div>"
        )
        columns = (
            ("win_rate", "Win rate", True),
            ("draw_rate", "Draw", True),
            ("mean_rocket_knocked_out", "Rocket KOs", False),
            ("lead_sweep_probability", "Solo sweep", True),
            ("mean_player_hp_fraction_left", "HP left", True),
            ("mean_turns", "Turns", False),
        )
        for rank, row in enumerate(rows, 1):
            body += (
                '<details class="counter"><summary class="row"><span class="metrics">'
                f"<span>{rank}.</span><span>{counter_name(row)}</span>"
            )
            for key, label, percent in columns:
                body += (
                    f'<span class="num"><span class="sr-only">{label}: </span>'
                    f"{estimate(row.get(key), percent=percent)}</span>"
                )
            body += (
                f"<span>{grades(row.get('grade'), row.get('flags', []))}</span></span></summary>"
            )
            body += counter_detail(row, data) + "</details>"
        body += "</div></section>"
    return body


def tile(title, href, data, results, reason, *, overall=False, extra=""):
    body = (
        f'<article class="tile{" overall" if overall else ""}"><h2>'
        f'<a href="{e(href)}">{e(title)}</a></h2>{extra}'
    )
    rows = ordered(results.get("40", []))[:3]
    if rows:
        body += (
            "<ol>"
            + "".join(
                f"<li>{counter_name(r)} {estimate(r['win_rate'], percent=True)}"
                f"<div>{grades(r.get('grade'), r.get('flags', []))}</div></li>"
                for r in rows
            )
            + "</ol>"
        )
    else:
        body += unavailable(reason or "no full results at level 40")
    body += provenance(data)
    body += (
        "<details><summary>Assumptions, validation and sources</summary>"
        f"{trust(data, '40')}{notes(data)}</details></article>"
    )
    return body


def atomic_text(path, value):
    """Flush and sync beside the destination, then replace it (same as atomic_json)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(value)
            stream.flush()
            umask = os.umask(0)
            os.umask(umask)
            os.fchmod(stream.fileno(), 0o666 & ~umask)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_report(root, entry):
    """Read only manifest entries; ignore dotfiles, orphans, stale and mismatched files."""
    filename = entry.get("file")
    if not filename:
        return {}, "report file unavailable"
    relative = Path(filename)
    if relative.is_absolute() or any(part.startswith(".") for part in relative.parts):
        return {}, "report file skipped: hidden or unsafe path"
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        return {}, "report file skipped: path outside data directory"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, f"report file unreadable ({type(exc).__name__})"
    if not isinstance(data, dict):
        return {}, "report file invalid: expected a JSON object"
    if data.get("key") != entry.get("key"):
        return data, "stale report: key does not match manifest entry"
    if entry.get("status") == "stale":
        return data, "stale report: manifest marks results stale"
    return data, ""


def check_dates(data):
    for key in ("battle_date", "computed_for_battle_date"):
        if key in data and date.fromisoformat(data[key]) < date(2019, 7, 22):
            raise ValueError(f"{key} before Team GO Rocket: dates before 2019-07-22 are rejected")


def build_site(data_dir, out):
    root, destination = Path(data_dir).resolve(), Path(out).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    check_dates(manifest)
    slugs = {"all", "grunts", "leaders"}
    for entry in manifest["characters"]:
        slug = entry["slug"]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or slug in slugs:
            raise ValueError(f"unsafe or duplicate character slug: {slug}")
        slugs.add(slug)
    overall, overall_reason = read_report(root, manifest.get("overall", {}))
    check_dates(overall)
    fallback = overall or manifest
    if not overall:
        for entry in manifest["characters"]:
            first, _ = read_report(root, entry)
            if first:
                fallback = {k: v for k, v in first.items() if k != "character"}
                del first
                break

    # A missing file still has visible assumptions from shared provenance, and its own
    # manifest-entry computation date. Never substitute another file's date silently.
    def metadata(data, entry):
        return data or {
            **fallback,
            "computed_for_battle_date": entry.get("computed_for_battle_date", "not recorded"),
            "computed_for_battle_date_source": entry.get(
                "computed_for_battle_date_source", "not recorded"
            ),
            "valid_for": entry.get("valid_for", {"era": "not recorded"}),
        }

    overall_meta = metadata(overall, manifest.get("overall", {}))
    pages = {}
    home = '<a href="../index.html">Home</a>'
    overall_nav = "".join(
        f'<a href="{view}.html">{title}</a>'
        for view, title in (("all", "All Rocket"), ("grunts", "Grunts"), ("leaders", "Leaders"))
    )
    index_body = (
        '<p class="sub">Top 3 per character · level 40 · open a tile for the full list</p>'
        '<div class="tiles">'
    )
    all_view = overall.get("all", {}) if not overall_reason else {}
    index_body += tile(
        "All Rocket",
        "list/all.html",
        overall_meta,
        all_view.get("results", {}),
        overall_reason,
        overall=True,
        extra=coverage(all_view),
    )
    # Process one character at a time: a real report can contain megabytes of calc cells.
    for entry in manifest["characters"]:
        data, reason = read_report(root, entry)
        check_dates(data)
        report = data.get("character", {})
        if report.get("name") != entry["name"] and not reason:
            reason = "stale report: character name does not match manifest entry"
        reason = reason or report.get("reason", "")
        meta = metadata(data, entry)
        results = data.get("character", {}).get("finalists", {}) if not reason else {}
        slug, name = entry["slug"], entry["name"]
        index_body += tile(name, f"list/{slug}.html", meta, results, reason)
        pages[f"list/{slug}.html"] = document(
            f"{name} · top counters",
            meta,
            list_body(meta, results, reason),
            home + overall_nav + f'<a href="../counters/{e(slug)}.html">Counter details</a>',
            script=True,
        )
        pages[f"counters/{slug}.html"] = document(
            f"{name} · counters",
            meta,
            counters_body(meta, results, reason),
            home + f'<a href="../list/{e(slug)}.html">Ranked list</a>',
        )
        del data, report, results, meta
    for view, title in (("all", "All Rocket"), ("grunts", "Grunts"), ("leaders", "Leaders")):
        data = overall.get(view, {}) if not overall_reason else {}
        pages[f"list/{view}.html"] = document(
            f"{title} · top counters",
            overall_meta,
            list_body(overall_meta, data.get("results", {}), overall_reason, coverage(data)),
            home + overall_nav,
            script=True,
        )
    pages["index.html"] = document(
        "Rocket counters · top 3",
        overall_meta,
        index_body + "</div>",
        '<a href="list/all.html">All Rocket</a><a href="list/grunts.html">Grunts</a>'
        '<a href="list/leaders.html">Leaders</a>',
    )
    for relative in pages:
        target = destination / relative
        if not target.resolve().is_relative_to(destination):
            raise ValueError(f"output path outside --out: {relative}")
    for relative, body in pages.items():
        atomic_text(destination / relative, body)
    return len(pages)


def add_parser(commands):
    sub = commands.add_parser("site", help="Render precompute reports as offline static HTML")
    sub.add_argument("--data", type=Path, required=True)
    sub.add_argument("--out", type=Path, required=True)


def main_site(args, arg_parser):
    try:
        build_site(args.data, args.out)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        arg_parser.error(str(exc))
    return 0
