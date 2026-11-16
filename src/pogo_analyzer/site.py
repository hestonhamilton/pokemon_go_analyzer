"""Offline, escaped static HTML views over manifest-listed precompute reports."""

import json
import os
import re
import shutil
import stat
import tempfile
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from html import escape
from math import floor
from pathlib import Path

from .sim.rocket import rule_data

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

TYPES = (
    "normal",
    "fire",
    "water",
    "electric",
    "grass",
    "ice",
    "fighting",
    "poison",
    "ground",
    "flying",
    "psychic",
    "bug",
    "rock",
    "ghost",
    "dragon",
    "dark",
    "steel",
    "fairy",
)

PAUSE_NOTE = (
    "Rankings depend strongly on the modelled Rocket pause after each charged attack "
    "(verification ledger row k); its trigger is an owner observation and not measured."
)


def pause_band_legend(data):
    """Escaped legend HTML with a fixed ledger link and the rows' actual band span."""
    params = data.get("params", {})
    threshold = params.get("pause_threshold", 0.15)
    turns = [
        turn
        for rows in data.get("character", {}).get("finalists", {}).values()
        for row in rows
        for turn in row.get("pause_band", {}).get("turns", [])
    ]
    ledger = (
        '<a href="https://github.com/hestonhamilton/pokemon_go_analyzer/blob/main/'
        'docs/simulator-verification.md#ledger">verification ledger row k</a>'
    )
    note = (
        "Pause band is a sensitivity check over assumed pause lengths, not a measured range "
        f"({ledger}); ranking uses the era value. "
    )
    if params.get("pause_band") == [] or not turns:
        return note + "band not computed for this run."
    span = f"{e(min(turns))} and {e(max(turns))} turns"
    points = format((Decimal(str(threshold)) * 100).normalize(), "f")
    return (
        note + f"pause-sensitive: the win rate moves more than {e(points)} percentage points "
        f"between {span}; "
        "threshold is a model choice."
    )


CSS = """
:root{--bg:#eef0ec;--panel:#fbfbf8;--ink:#1d2321;--muted:#5d6762;--line:#d3d8d2;
--accent:#1f5f8b;--win:#2f7d4f;--amber:#9a6200;--violet:#6a4c9c;
--display:"Arial Narrow",sans-serif;--body:system-ui,sans-serif;--mono:ui-monospace,monospace}
/* Values sampled from the Pokémon GO type icons. */
:root{--ty-normal:#9098a0;--ty-fire:#fca84c;--ty-water:#4c90d4;--ty-electric:#f4d03c;--ty-grass:#60b854;--ty-ice:#74ccc0;--ty-fighting:#cc4068;--ty-poison:#a464c4;--ty-ground:#d49060;--ty-flying:#90a8dc;--ty-psychic:#f86c74;--ty-bug:#90c02c;--ty-rock:#d0c490;--ty-ghost:#5468ac;--ty-dragon:#0868c0;--ty-dark:#585064;--ty-steel:#50849c;--ty-fairy:#ec8ce4;}
.ty{display:inline-flex;align-items:center;gap:4px;font:600 .76rem var(--body);padding:1px 8px;
border-radius:999px;border:1px solid color-mix(in srgb,var(--ty) 55%,transparent);
background:color-mix(in srgb,var(--ty) 18%,transparent);color:var(--ink);
text-transform:capitalize;white-space:nowrap}
.ty:has(img){padding-left:2px}.ty img{width:18px;height:18px}
.tys{display:flex;flex-wrap:wrap;gap:4px}
.ty-normal{--ty:var(--ty-normal)}.ty-fire{--ty:var(--ty-fire)}.ty-water{--ty:var(--ty-water)}.ty-electric{--ty:var(--ty-electric)}.ty-grass{--ty:var(--ty-grass)}.ty-ice{--ty:var(--ty-ice)}.ty-fighting{--ty:var(--ty-fighting)}.ty-poison{--ty:var(--ty-poison)}.ty-ground{--ty:var(--ty-ground)}.ty-flying{--ty:var(--ty-flying)}.ty-psychic{--ty:var(--ty-psychic)}.ty-bug{--ty:var(--ty-bug)}.ty-rock{--ty:var(--ty-rock)}.ty-ghost{--ty:var(--ty-ghost)}.ty-dragon{--ty:var(--ty-dragon)}.ty-dark{--ty:var(--ty-dark)}.ty-steel{--ty:var(--ty-steel)}.ty-fairy{--ty:var(--ty-fairy)}
button.t:has(.ty),button.t:has(.ty)[aria-pressed=true]{padding:0;border:0;background:none}
button[aria-pressed=true] .ty{outline:2px solid var(--ink);outline-offset:1px}
h2 .ty{vertical-align:.2em}
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
.chip.warn{border-color:var(--amber)}td .chip{white-space:nowrap;overflow-wrap:normal}
.assume{padding:6px 14px;color:var(--muted);font-size:.86rem}
.intro-info{padding:8px 14px 0;display:grid;gap:6px;justify-items:start}
.intro-chips{display:flex;flex-wrap:wrap;gap:6px}
.intro>summary{font-weight:600;padding:12px 14px;cursor:pointer}
.intro-legends{padding:12px 14px;display:grid;gap:12px}
.body{padding:12px 14px;display:grid;gap:12px;grid-template-columns:minmax(0,1fr)}
.wrap{overflow-x:auto;position:relative}table{border-collapse:collapse;
width:100%;font-variant-numeric:tabular-nums;font-size:.9rem}th,td{padding:6px 8px;
border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font:600 .78rem
var(--display);color:var(--muted);text-transform:uppercase;white-space:nowrap}
.num{font-family:var(--mono);text-align:right;white-space:nowrap}.est-mark{font:500 .62rem
var(--mono);color:var(--muted);vertical-align:super;margin-left:2px}.mon{font-weight:600}
.pause-band{display:block;white-space:normal;font-size:.74rem}
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
INTRO_JS = """if(matchMedia('(max-width:640px)').matches){
document.currentScript.previousElementSibling.open=false;
}"""
# Filtering only hides server-rendered rows. Without JS all rows and levels remain available.
FILTER_JS = """const percent=v=>{
const text=(v*100).toFixed(1);
return v>0&&text==='0.0'?'<0.1%':v<1&&text==='100.0'?'>99.9%':text+'%';
};
document.querySelectorAll('.controls').forEach(c=>c.hidden=false);
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{
const s=b.closest('section'),t=b.dataset.filter;
s.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',x===b));
s.querySelectorAll('tr[data-types]').forEach(r=>r.hidden=t!==''&&!JSON.parse(r.dataset.types).includes(t));
const rows=[...s.querySelectorAll('tr[data-types]')].filter(r=>!r.hidden);
const best=Number(rows[0]?.dataset.win||0);
s.querySelector('[data-best-warning]').hidden=rows.length===0||best>=0.5;
rows.forEach((r,i)=>{r.querySelector('[data-rank]').textContent=i+1;
r.querySelector('[data-best]').textContent=best?percent(Number(r.dataset.win)/best):'—';});
});"""


def e(value):
    return escape(str(value), quote=True)


def chip(value, kind=""):
    return f'<span class="chip {kind}">{e(value)}</span>'


def grades(value, flags=()):
    parts = str(value).split("; ") if value else []
    if not parts:
        parts.append("grade not recorded")
    if "extrapolated" in flags and "extrapolated forward" not in parts:
        parts.append("extrapolated forward")
    return " ".join(
        chip(
            p,
            "est"
            if p == "estimate"
            else "warn"
            if any(
                word in p for word in ("unverified", "incomplete", "extrapolated", "not recorded")
            )
            else "",
        )
        for p in parts
    )


def percentage(value):
    formatted = f"{value * 100:.1f}"
    if value > 0 and formatted == "0.0":
        return "<0.1%"
    if value < 1 and formatted == "100.0":
        return ">99.9%"
    return formatted + "%"


def estimate(value, *, percent=False):
    if value is None:
        return '<span class="moves">not recorded</span>'
    if percent:
        formatted = percentage(value)
    elif value == int(value):
        formatted = str(int(value))
    else:
        formatted = f"{value:.2f}"
        # Floor to 2dp near an integer when rounding up would suggest a full KO.
        if float(formatted).is_integer() and float(formatted) > value:
            formatted = f"{floor(value * 100) / 100:.2f}"
    return f'{e(formatted)}<span class="est-mark" title="estimate">est</span>'


def win_rate(row, *, overall=False):
    text = estimate(row.get("win_rate"), percent=True)
    if overall:
        return text
    band = row.get("pause_band")
    if not band:
        return text + '<span class="pause-band">band not computed</span>'
    first, last = band["turns"][0], band["turns"][-1]
    text += (
        f'<span class="pause-band" title="{e(band.get("note", ""))}">'
        f"({e(first)}–{e(last)} turns: {estimate(band['min'], percent=True)}"
        f"–{estimate(band['max'], percent=True)})"
    )
    if band.get("sensitive"):
        text += " " + chip("pause-sensitive", "warn")
    return text + "</span>"


def english_date(value):
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def battle_date(value):
    try:
        return english_date(date.fromisoformat(value))
    except (TypeError, ValueError):
        return str(value) if value else "not recorded"


def era_label(identifier):
    if not identifier or identifier == "not recorded":
        return "battle rules period not recorded"
    for era in rule_data()["eras"]:
        if era["id"] != identifier:
            continue
        start, until = era.get("from"), era.get("until")
        if start:
            text = f"battle rules from {battle_date(start)}"
            if until:
                text += f" to {english_date(date.fromisoformat(until) - timedelta(days=1))}"
            return text
        if until:
            return f"battle rules before {battle_date(until)}"
    return f"battle rules period {identifier}"


def fetched_label(value):
    if not value or value == "not recorded":
        return "fetched not recorded"
    try:
        stamp = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return f"fetched {value}"
    # Older timestamps without an offset are treated as UTC, never the host timezone.
    stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
    return f"fetched {english_date(stamp)}, {stamp:%H:%M} UTC"


def provenance(data):
    stamp = data.get("computed_for_battle_date", data.get("battle_date", "not recorded"))
    source = data.get(
        "computed_for_battle_date_source", data.get("battle_date_source", "not recorded")
    )
    source = {
        "default: run date": "the day this ran",
        "explicit": "a chosen date",
        "not recorded": "date source not recorded",
        None: "date source not recorded",
        "": "date source not recorded",
    }.get(source, source)
    valid = data.get("valid_for", {})
    era = valid.get("era", data.get("era", "not recorded"))
    return (
        f'<p class="moves">Battles as of {e(battle_date(stamp))} ({e(source)}) · '
        f"{e(era_label(era))}</p>"
        + (
            chip("newer than our sources: rules assumed unchanged", "warn")
            if valid.get("extrapolated")
            else ""
        )
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
        f'<div class="assume">You: {"levels" if "/" in level else "level"} {e(level)} '
        f"· IVs {e(iv_text)} · trainer level "
        f"{e(params.get('trainer_level', 'not recorded'))} · Mega excluded (unsupported) · "
        f"{e(move_note)} · player {e(policy)} · player {e(shields)}. "
        f"{e(data.get('filter_note', 'Filter note not recorded'))}</div>"
    )


def validation_status(data):
    validation = data.get("validation", {})
    label = data.get("validation_label", "Validation label not recorded")
    if not isinstance(label, str):
        raise ValueError("validation_label must be a string")
    failed = validation.get("validated") is not True or any(
        word in label.casefold() for word in ("unvalidated", "gate failed")
    )
    discrepancies = validation.get("open_discrepancies", [])
    return label, failed, discrepancies


def trust_strip(data):
    label, failed, discrepancies = validation_status(data)
    ids = [str(r.get("id", r.get("fixture", ""))) for r in discrepancies]
    strip = chip("every number is an estimate", "est") + chip(label)
    if failed:
        strip += chip("UNVALIDATED", "warn")
    strip += chip("open discrepancies: " + (", ".join(ids) or "none recorded"), "warn")
    strip += chip(data.get("rcpm_note") or "rCPM note not recorded")
    strip += chip(PAUSE_NOTE, "warn")
    return f'<div class="trust">{strip}</div>'


def trust(data, level):
    return f"{trust_strip(data)}{provenance(data)}{assumptions(data, level)}"


def intro(data, legends):
    _, failed, discrepancies = validation_status(data)
    visible = chip("every number is an estimate", "est")
    if failed:
        visible += chip("UNVALIDATED", "warn")
    count = len(discrepancies)
    if count:
        visible += chip(f"{count} open {'check' if count == 1 else 'checks'}", "warn")
    return (
        f'<div class="intro-info"><div class="intro-chips">{visible}</div>'
        f"{provenance(data)}</div>"
        '<details class="intro" open><summary>How these numbers work</summary>'
        f"{trust_strip(data)}{assumptions(data, '40/50 (per section)')}"
        + (f'<div class="intro-legends">{legends}</div>' if legends else "")
        + f"</details><script>{INTRO_JS}</script>"
    )


def page_legends(data, *, overall=False, counters=False):
    ranking = (
        "Expand a counter for its details."
        if counters
        else "% of best uses the current filtered view."
    )
    pause = "pause band not computed for the overall list" if overall else pause_band_legend(data)
    return (
        '<p class="legend">Badges: elite = elite move; legacy = legacy move. '
        f"Ranked by win rate, HP left, then turns. {ranking}</p>"
        f'<p class="legend">{pause}</p>'
    )


def notes(data, coverage_view=None):
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
    body += coverage(data if coverage_view is None else coverage_view)
    body += f"<p>{e(PAUSE_NOTE)}</p><p>Dates before 2019-07-22 are rejected.</p>"
    for source in data.get("sources", []):
        body += (
            "<p><b>Source.</b> "
            + " · ".join(e(source.get(k, "not recorded")) for k in ("name", "license", "url"))
            + f" · {e(fetched_label(source.get('fetched_at')))}</p>"
        )
    return f'<footer class="notes">{body}</footer>'


def document(title, data, body, nav, *, script=False, coverage_view=None, legends=""):
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{e(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
        f'<nav aria-label="Pages">{nav}</nav>\n<div class="screen">'
        f'<header class="screen-title"><h1>{e(title)}</h1></header>\n'
        f"{intro(data, legends)}\n"
        f'<div class="body">{body}</div>\n{notes(data, coverage_view)}\n</div>\n</main>\n'
        + (f"<script>{FILTER_JS}</script>\n" if script else "")
        + "</body>\n</html>\n"
    )


def heading(identifier):
    """Readable PvPoke id: DRAGON_BREATH -> Dragon Breath; the shadow chip carries the form."""
    words = str(identifier).removesuffix("_shadow").replace("_", " ").split()
    return " ".join(w.capitalize() for w in words)


def counter_name(row):
    def move(key):
        name = row.get(key, "not recorded")
        flags = row.get("move_flags", {}).get(name, {})
        return f'<span title="{e(name)}">{e(heading(name))}</span>' + "".join(
            chip(k) for k in ("elite", "legacy") if flags.get(k)
        )

    species = row.get("speciesId", row.get("species", "not recorded"))
    return (
        f'<span class="mon" title="{e(species)}">{e(heading(species))}</span> '
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


def type_chip(t, icons, *, prefix=""):
    if t not in TYPES:
        return e(t)
    icon = f'<img src="{prefix}types/{t}.png" alt="" width="18" height="18">' if t in icons else ""
    return f'<span class="ty ty-{t}">{icon}{e(t)}</span>'


def list_body(data, results, reason, extra="", *, overall=False, icons=frozenset()):
    level_keys = levels(data, results)
    body = (
        extra
        + '<nav aria-label="Levels">'
        + "".join(f'<a href="#level-{e(v)}">Level {e(v)}</a>' for v in level_keys)
        + "</nav>"
    )
    for level in level_keys:
        rows = ordered(results.get(level, []))
        body += (
            f'<section id="level-{e(level)}"><h2>Level {e(level)}</h2>{assumptions(data, level)}'
        )
        if not rows:
            body += unavailable(reason or "no full results at this level") + "</section>"
            continue
        types = sorted({t for row in rows for t in row.get("types", []) if t != "none"})
        body += '<div class="controls" role="group" aria-label="Attacker types" hidden>'
        body += '<button class="t" data-filter="" aria-pressed="true">All types</button>'
        body += "".join(
            f'<button class="t" data-filter="{e(t)}" aria-pressed="false">'
            f"{type_chip(t, icons, prefix='../')}</button>"
            for t in types
        )
        body += (
            '</div><noscript><p class="moves">Without JavaScript all types are shown.'
            "</p></noscript>"
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
            types_text = [t for t in row.get("types", []) if t != "none"]
            body += f"<td data-rank>{rank}</td><td>{counter_name(row)}</td>"
            body += (
                '<td><span class="tys">'
                + (
                    "".join(type_chip(t, icons, prefix="../") for t in types_text)
                    or "types not recorded"
                )
                + "</span></td>"
            )
            body += f'<td class="num">{win_rate(row, overall=overall)}</td>'
            ratio_text = percentage(ratio) if ratio is not None else "—"
            body += (
                f'<td class="num"><span data-best>{e(ratio_text)}</span>'
                '<span class="est-mark" title="estimate">est</span></td>'
            )
            body += f'<td class="num">{estimate(row.get("mean_rocket_knocked_out"))}</td>'
            hp = estimate(row.get("mean_player_hp_fraction_left"), percent=True)
            body += f'<td class="num">{hp}</td>'
            body += f"<td>{grades(row.get('grade'), row.get('flags', []))}</td></tr>"
        body += "</tbody></table></div>"
        body += (
            f"<p data-best-warning{' hidden' if best >= 0.5 else ''}>"
            f"{chip('best counter loses most battles', 'warn')}</p>"
        )
        body += "</section>"
    return body


def calc_summary(rows, grade_order):
    """Retain ranges and weakest known grades, or every distinct grade if any is unknown."""
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
            f'<td title="{e(species)}">{e(heading(species))}</td>'
        )
        for key in columns:
            cells = group[key]
            if not cells:
                body += "<td>not recorded</td>"
                continue
            values, cell_grades = zip(*cells, strict=True)
            # Unknown grade vocabularies fail visibly rather than claiming a stronger grade.
            if any(g not in grade_order for g in cell_grades):
                grade_chips = " ".join(chip(g) for g in sorted(set(cell_grades)))
            else:
                grade_chips = chip(max(cell_grades, key=grade_order.index))
            body += (
                f'<td class="num">{estimate(min(values))}'
                + ("" if min(values) == max(values) else f"–{estimate(max(values))}")
                + f"<br>{grade_chips}</td>"
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
        '<div class="wrap"><table><caption>Conditional win rates · '
        f"{grades(row.get('grade'), row.get('flags', []))}</caption>"
        "<thead><tr><th>Slot</th><th>Rocket species</th>"
        "<th>Conditional win rate</th><th>n</th></tr></thead><tbody>"
    )
    for slot in row.get("per_slot", []):
        for species in slot.get("species", []):
            body += (
                f"<tr><td>{e(slot['slot'])}</td><td>{e(heading(species['species']))}</td>"
                f'<td class="num">{estimate(species["conditional_win_rate"], percent=True)}'
                f"</td><td>{e(species.get('battles', 'n not recorded'))}</td></tr>"
            )
    body += "</tbody></table></div>"
    body += calc_summary(row.get("calc_rows", []), [g["id"] for g in data.get("grades", [])])
    return body + "</div>"


def counters_body(data, results, reason):
    level_keys = levels(data, results)
    body = (
        '<nav aria-label="Levels">'
        + "".join(f'<a href="#level-{e(v)}">Level {e(v)}</a>' for v in level_keys)
        + "</nav>"
    )
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
                value = (
                    win_rate(row) if key == "win_rate" else estimate(row.get(key), percent=percent)
                )
                body += f'<span class="num"><span class="sr-only">{label}: </span>{value}</span>'
            body += (
                '<span><span class="sr-only">Grade: </span>'
                f"{grades(row.get('grade'), row.get('flags', []))}</span></span></summary>"
            )
            body += counter_detail(row, data) + "</details>"
        body += "</div></section>"
    return body


def tile(
    title,
    href,
    data,
    results,
    reason,
    *,
    overall=False,
    extra="",
    coverage_view=None,
    type_name=None,
    icons=frozenset(),
):
    body = (
        f'<article class="tile{" overall" if overall else ""}"><h2>'
        f"{type_chip(type_name, icons) + ' ' if type_name else ''}"
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
        f"{trust(data, '40')}{notes(data, coverage_view)}</details></article>"
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


def read_report(root, entry, *, overall=False):
    """Read safe manifest entries; only overall may display matching stale results."""
    filename = entry.get("file")
    if not filename:
        if overall and entry.get("status") == "skipped":
            return {}, "overall list not computed on this run (--skip-overall)"
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
    if not entry.get("key") or not data.get("key") or data["key"] != entry["key"]:
        return data, "stale report: key does not match manifest entry"
    if entry.get("status") == "stale" and not overall:
        return data, "stale report: manifest marks results stale"
    return data, ""


def check_dates(data):
    for key in ("battle_date", "computed_for_battle_date"):
        if key in data and date.fromisoformat(data[key]) < date(2019, 7, 22):
            raise ValueError(f"{key} before Team GO Rocket: dates before 2019-07-22 are rejected")


def check_destination(destination):
    """Only replace empty directories or trees whose files a previous build recorded."""
    if not destination.exists():
        return
    if not destination.is_dir():
        raise ValueError("--out must be a directory")
    children = list(destination.iterdir())
    if any(p.is_symlink() for p in children):
        raise ValueError("output symlink may point outside --out")
    if not children:
        return
    marker = destination / ".pogo-site"
    refusal = "refusing to replace --out: missing or invalid .pogo-site build marker"
    try:
        recorded = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(refusal) from exc
    if not isinstance(recorded, dict) or recorded.get("version") != 1:
        raise ValueError(refusal)
    files = recorded.get("files")
    if not isinstance(files, list) or not all(
        isinstance(name, str)
        and re.fullmatch(
            r"(?:(?:index|(?:list|counters)/[a-z0-9]+(?:-[a-z0-9]+)*)\.html|types/[a-z]+\.png)",
            name,
        )
        for name in files
    ):
        raise ValueError(refusal)
    allowed = {".pogo-site", *files}
    directories = {str(Path(name).parent) for name in files} - {"."}
    for path in destination.rglob("*"):
        relative = str(path.relative_to(destination))
        if path.is_symlink():
            raise ValueError(f"output path outside --out: {relative}")
        if (path.is_dir() and relative in directories) or (path.is_file() and relative in allowed):
            continue
        raise ValueError(f"refusing to replace --out: file not produced by site build: {relative}")


def publish_pages(destination, pages):
    """Stage a complete tree beside --out, swap it in, then remove the owned old tree."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=f".{destination.name}.new-", dir=destination.parent))
    old = None
    try:
        # mkdtemp starts private; publish with ordinary directory permissions.
        umask = os.umask(0)
        os.umask(umask)
        staged.chmod(0o777 & ~umask)
        for relative, body in pages.items():
            if isinstance(body, bytes):
                path = staged / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            else:
                atomic_text(staged / relative, body)
        atomic_text(staged / ".pogo-site", json.dumps({"version": 1, "files": sorted(pages)}))
        # Recheck ownership immediately before moving anything out of --out.
        check_destination(destination)
        if destination.exists():
            old = Path(tempfile.mkdtemp(prefix=f".{destination.name}.old-", dir=destination.parent))
            try:
                os.replace(destination, old)
            except OSError:
                old.rmdir()
                old = None
                raise
        try:
            os.replace(staged, destination)
        except OSError:
            if old is not None:
                os.replace(old, destination)
            raise
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    if old is not None:
        shutil.rmtree(old)


def load_type_icons(directory):
    icons = {}
    if directory is None:
        return icons
    for name in TYPES:
        try:
            fd = os.open(
                Path(directory) / f"{name}.png", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            )
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                    continue
                content = stream.read(65537)
                if len(content) <= 65536 and content.startswith(b"\x89PNG\r\n\x1a\n"):
                    icons[name] = content
        except OSError:
            continue
    return icons


def build_site(data_dir, out, type_icons=None):
    if Path(out).is_symlink():
        raise ValueError("output symlink points outside --out")
    root, destination = Path(data_dir).resolve(), Path(out).resolve()
    check_destination(destination)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    check_dates(manifest)
    slugs = {"all", "grunts", "leaders"}
    for entry in manifest["characters"]:
        slug = entry["slug"]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or slug in slugs:
            raise ValueError(f"unsafe or duplicate character slug: {slug}")
        slugs.add(slug)
    overall_entry = manifest.get("overall", {})
    overall, overall_reason = read_report(root, overall_entry, overall=True)
    check_dates(overall)
    fallback = overall or manifest
    if not overall:
        for entry in manifest["characters"]:
            first, why = read_report(root, entry)
            if first and not why:
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

    overall_meta = metadata(overall, overall_entry)
    overall_notice = ""
    if not overall_reason and overall_entry.get("status") == "stale":
        stamp = overall.get("computed_for_battle_date", overall.get("battle_date", "not recorded"))
        overall_notice = chip("stale", "warn") + (
            f"<p>This overall list was computed for battle date {e(stamp)} and is older than "
            "the per-type lists, which have changed since it was computed.</p>"
        )
    icon_data = load_type_icons(type_icons)
    icons = set(icon_data)
    pages = {f"types/{name}.png": content for name, content in icon_data.items()}
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
        extra=overall_notice + coverage(all_view),
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
        index_body += tile(
            name,
            f"list/{slug}.html",
            meta,
            results,
            reason,
            coverage_view=all_view,
            type_name=slug.split("-")[0]
            if entry.get("rank") == "grunt" and slug.split("-")[0] in TYPES
            else None,
            icons=icons,
        )
        pages[f"list/{slug}.html"] = document(
            f"{name} · top counters",
            meta,
            list_body(meta, results, reason, icons=icons),
            home + overall_nav + f'<a href="../counters/{e(slug)}.html">Counter details</a>',
            script=True,
            coverage_view=all_view,
            legends=page_legends(meta),
        )
        pages[f"counters/{slug}.html"] = document(
            f"{name} · counters",
            meta,
            counters_body(meta, results, reason),
            home + f'<a href="../list/{e(slug)}.html">Ranked list</a>',
            coverage_view=all_view,
            legends=page_legends(meta, counters=True),
        )
        del data, report, results, meta
    for view, title in (("all", "All Rocket"), ("grunts", "Grunts"), ("leaders", "Leaders")):
        data = overall.get(view, {}) if not overall_reason else {}
        pages[f"list/{view}.html"] = document(
            f"{title} · top counters",
            overall_meta,
            list_body(
                overall_meta,
                data.get("results", {}),
                overall_reason,
                overall_notice + coverage(data),
                overall=True,
                icons=icons,
            ),
            home + overall_nav,
            script=True,
            coverage_view=data,
            legends=page_legends(overall_meta, overall=True),
        )
    pages["index.html"] = document(
        "Rocket counters · top 3",
        overall_meta,
        index_body + "</div>",
        '<a href="list/all.html">All Rocket</a><a href="list/grunts.html">Grunts</a>'
        '<a href="list/leaders.html">Leaders</a>',
        coverage_view=all_view,
    )
    publish_pages(destination, pages)
    return len(pages) - len(icon_data)


def add_parser(commands):
    sub = commands.add_parser("site", help="Render precompute reports as offline static HTML")
    sub.add_argument("--data", type=Path, required=True)
    sub.add_argument("--out", type=Path, required=True)
    sub.add_argument("--type-icons", type=Path)


def main_site(args, arg_parser):
    try:
        build_site(args.data, args.out, args.type_icons)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        arg_parser.error(str(exc))
    return 0
