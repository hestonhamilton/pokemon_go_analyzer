"""Offline, escaped static HTML views over manifest-listed precompute reports."""

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from html import escape
from math import floor
from pathlib import Path

from .lineups import PVPOKE_GM_URL
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
    bands = [
        row["pause_band"]
        for rows in data.get("character", {}).get("finalists", {}).values()
        for row in rows
        if row.get("pause_band", {}).get("turns")
    ]
    ledger = (
        '<a href="https://github.com/hestonhamilton/pokemon_go_analyzer/blob/main/'
        'docs/simulator-verification.md#ledger">verification ledger row k</a>'
    )
    note = (
        "Pause band is a sensitivity check over assumed pause lengths, not a measured range "
        f"({ledger}); ranking uses the era value. "
    )
    if params.get("pause_band") == [] or not bands:
        return note + "band not computed for this run."
    descriptions = {}
    for band in bands:
        threshold = band.get("threshold", params.get("pause_threshold", 0.15))
        points = format((Decimal(str(threshold)) * 100).normalize(), "f")
        turns = band["turns"]
        description = (
            f"Timing-sensitive means a row's win rate moves more than {e(points)} percentage "
            f"points between {e(min(turns))} and {e(max(turns))} turns; "
            f"threshold: {e(points)} percentage points "
            f"({e(band.get('threshold_note', 'model choice'))})."
        )
        descriptions[description] = None
    return note + " ".join(descriptions)


CSS = """
:root{--bg:#f1f2f5; --panel:#fff; --ink:#1d2230; --muted:#5d6475; --line:#dfe2ea; --accent:#c8282c;
--win:#2f8f57; --amber:#9a6200; --violet:#6a4c9c; --nav-bg:#1c2030; --nav-ink:#e6e8ef;
--rocket:#1c2030; --rocket-red:#e0302a; --display:Lato,system-ui,sans-serif;
--body:Lato,system-ui,sans-serif; --mono:ui-monospace,monospace}
/* Values sampled from the Pokémon GO type icons. */ :root{--ty-normal:#9098a0; --ty-fire:#fca84c;
--ty-water:#4c90d4; --ty-electric:#f4d03c; --ty-grass:#60b854; --ty-ice:#74ccc0;
--ty-fighting:#cc4068; --ty-poison:#a464c4; --ty-ground:#d49060; --ty-flying:#90a8dc;
--ty-psychic:#f86c74; --ty-bug:#90c02c; --ty-rock:#d0c490; --ty-ghost:#5468ac; --ty-dragon:#0868c0;
--ty-dark:#585064; --ty-steel:#50849c; --ty-fairy:#ec8ce4; } .ty{display:inline-flex;
align-items:center; gap:4px; font:600 .76rem var(--body); padding:1px 8px; border-radius:999px;
border:1px solid color-mix(in srgb,var(--ty) 55%,transparent);
background:color-mix(in srgb,var(--ty) 18%,transparent); color:var(--ink);
text-transform:capitalize; white-space:nowrap} .ty:has(img){padding-left:2px} .ty img{width:18px;
height:18px} .tys{display:flex; flex-wrap:wrap; gap:4px} .ty-normal{--ty:var(--ty-normal)}
.ty-fire{--ty:var(--ty-fire)} .ty-water{--ty:var(--ty-water)} .ty-electric{--ty:var(--ty-electric)}
.ty-grass{--ty:var(--ty-grass)} .ty-ice{--ty:var(--ty-ice)} .ty-fighting{--ty:var(--ty-fighting)}
.ty-poison{--ty:var(--ty-poison)} .ty-ground{--ty:var(--ty-ground)}
.ty-flying{--ty:var(--ty-flying)} .ty-psychic{--ty:var(--ty-psychic)} .ty-bug{--ty:var(--ty-bug)}
.ty-rock{--ty:var(--ty-rock)} .ty-ghost{--ty:var(--ty-ghost)} .ty-dragon{--ty:var(--ty-dragon)}
.ty-dark{--ty:var(--ty-dark)} .ty-steel{--ty:var(--ty-steel)} .ty-fairy{--ty:var(--ty-fairy)}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1118; --panel:#191c27;
--ink:#e8e9ee; --muted:#9a9fb0; --line:#2b3042; --sprite-tint:45%;
--accent:#ff8585; --win:#5cc086; --amber:#e3a646;
--violet:#ad94dd; --nav-bg:#1c2030; --nav-ink:#e6e8ef; --rocket:#0a0b10; --rocket-red:#ff3b30;
color-scheme:dark} } :root[data-theme="dark"]{--bg:#0f1118; --panel:#191c27; --ink:#e8e9ee;
--muted:#9a9fb0; --line:#2b3042; --sprite-tint:45%;
--accent:#ff8585; --win:#5cc086; --amber:#e3a646;
--violet:#ad94dd; --nav-bg:#1c2030; --nav-ink:#e6e8ef; --rocket:#0a0b10; --rocket-red:#ff3b30;
color-scheme:dark} *{box-sizing:border-box} body{margin:0; font:15px/1.45 var(--body);
background:var(--bg); color:var(--ink)} a{color:inherit} main{max-width:1080px; margin:auto;
padding:0 14px 60px} h1,h2,h3{margin:0; font-weight:900} p{margin:0} .top{display:flex;
align-items:center; gap:8px; padding:10px 14px; max-width:1080px; margin:auto}
.top a{text-decoration:none; font-weight:700; padding:6px 12px; border-radius:999px}
.top .theme-toggle{margin-left:auto; width:32px; height:32px; border-radius:50%; border:0;
display:grid; place-items:center} .disc{font-size:.82rem; padding:8px 14px; text-align:center}
.disc a{font-weight:700} .rmark{height:.85em; vertical-align:-.05em; margin-right:.3em}
.spr{border-radius:50%; flex:none} .ph{width:var(--sprite-size);height:var(--sprite-size);
border-radius:50%;background:var(--line);display:inline-grid; place-items:center;
color:var(--muted); font-size:.7rem} .mini{width:22px; height:22px; vertical-align:middle}
.tag{font-size:.68rem; font-weight:700; border-radius:4px; padding:0 5px; vertical-align:2px;
margin-left:4px} .tag.sh{background:#7b4fb0; color:#fff} .tag.el{background:#e9e3c8; color:#5a4b00}
.tag.warn{background:#f6e2b8; color:#7a4c00} .rows{list-style:none; margin:0; padding:0}
.row{display:grid; grid-template-columns:20px 44px minmax(0,1fr) 58px; gap:2px 10px;
align-items:center} .row .spr{width:44px; height:44px} .row .rk{font-weight:900;
color:var(--muted); text-align:right} .row .nm{font-weight:900} .row .mv{font-size:.8rem;
color:var(--muted)} .row .tys{display:inline-flex; gap:3px; vertical-align:-3px}
.row .tys .ty{padding:1px} .row .tys .ty img{width:16px; height:16px} .row .score{text-align:right;
line-height:1.05} .row .score b{font-size:1.25rem; font-weight:900; display:block}
.row .score span{font-size:.68rem; color:var(--muted)} .row .sec{grid-column:3/-1; display:none;
gap:12px; font-size:.75rem; color:var(--muted)} .tough{display:block; font-size:.75rem;
color:var(--muted); margin-top:2px} .set{font-size:.8rem; color:var(--muted); margin:2px 0 10px}
.lv{display:flex; gap:4px} .lv button{font:700 .78rem var(--body); border-radius:999px;
padding:4px 12px; border:1px solid var(--line); background:transparent; color:var(--ink)}
.lv button[aria-pressed=true]{background:var(--ink); color:var(--bg)} .bar{display:flex;
align-items:center; justify-content:space-between; gap:10px; margin-bottom:4px}
.lineup{display:grid; gap:6px} .slot{display:flex; align-items:center; gap:6px; flex-wrap:wrap}
.sn{font-weight:900; width:22px; text-align:center; font-size:1.1rem; opacity:.7} .lsp{width:44px;
height:44px} .more{font-size:.8rem; opacity:.75} .grid{display:grid;
grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:12px} .cc{display:block;
text-decoration:none} .cch{text-decoration:none; display:flex; align-items:center; gap:8px}
.cch h3{font-size:1rem;
flex:1} .lead{display:flex} .lead .lsp{width:30px; height:30px; margin-left:-8px}
.top3{list-style:none; margin:8px 0 0; padding:0; display:grid; gap:4px} .top3 li{display:grid;
grid-template-columns:32px minmax(0,1fr) auto; gap:8px; align-items:center; font-size:.88rem}
.top3 li>span{min-width:0; overflow-wrap:anywhere}
.top3 b{font-weight:900} .grp{margin:22px 0 10px; font-size:1.2rem} .hint{font-size:.8rem;
color:var(--muted)} .more-link{display:inline-block; margin-top:8px; font-weight:700;
color:var(--accent)} .rk-badge{font-size:.7rem; font-weight:900; background:var(--rocket-red);
color:#fff; border-radius:4px; padding:1px 6px; text-transform:uppercase}
@media(min-width:700px){.row .sec{display:flex; grid-column:auto; flex-direction:column; gap:0;
text-align:right; min-width:86px} .row{grid-template-columns:28px 48px minmax(0,1fr) 110px 70px}
.row .spr{width:48px; height:48px} } .topwrap{background:#1c2030} .top a{color:#e6e8ef}
.top a[aria-current="page"]{background:#e0302a; color:#fff} .top .theme-toggle{background:#2c3246;
color:#fff} .disc{background:#2a2f42; color:#cfd3e0} .disc a{color:#fff}
.hero{padding:26px 16px 22px; margin:0 -14px;
background:radial-gradient(120% 140% at 0 0,#3a2030,#1c2030 60%); color:#fff}
.hero h1{font-size:2rem} .hero p{color:#c9cdda} .card{background:var(--panel); border-radius:14px;
padding:14px; margin-top:14px; border:1px solid var(--line)} .rows{margin-top:6px}
.row{padding:8px 2px; border-bottom:1px solid var(--line)} .row:last-child{border:0}
.row .score b{color:var(--ink)} .cc{background:var(--panel); border-radius:14px; overflow:hidden;
border:1px solid var(--line)} .cch{background:linear-gradient(100deg,#1c2030 0 75%,#3a2a3a);
color:#fff; padding:10px 12px} .cch .ty{color:#fff} .top3{padding:4px 12px 10px}
.charhead{margin:0 -14px; padding:18px 16px; color:#fff;
background:linear-gradient(160deg,#1c2030 0 65%,color-mix(in srgb,var(--t1) 60%,#1c2030))}
.charhead .ct{display:flex; align-items:center; gap:10px; margin-bottom:10px}
.charhead h1{font-size:1.8rem} .charhead .hint{color:#b9bdca; margin-bottom:6px}
.charhead .ty{color:#fff} .slot{background:rgba(255,255,255,.08);
border:1px solid rgba(255,255,255,.12); border-radius:12px; padding:4px 8px}
.lsp{background:radial-gradient(circle,rgba(160,110,220,.45) 0 55%,transparent 62%)}
.top{flex-wrap:wrap} .top a{font-size:.85rem} .theme-toggle{cursor:pointer} a{color:var(--accent)}
.cc{color:inherit} main{min-width:0} .card h2{font-size:1.25rem} .who{min-width:0}
.row{font-variant-numeric:tabular-nums} .nm,.mv,.tough{overflow-wrap:anywhere}
.row .spr{background:radial-gradient(circle,
color-mix(in srgb,var(--t1) var(--sprite-tint,40%),var(--panel)) 0 60%,transparent 61%)}
.ty-icon{padding:1px!important; width:20px; height:20px; justify-content:center}
.ty-icon .type-symbol{font-size:.7rem; line-height:16px} .tag{white-space:nowrap}
.tag.warn{color:var(--amber); background:transparent; border:1px solid var(--amber);
text-decoration:none} .notice{padding:5px 14px; font-size:.8rem; color:var(--amber);
background:color-mix(in srgb,var(--amber) 10%,var(--panel)); border-block:1px solid var(--amber)}
.controls{display:flex; flex-wrap:wrap; gap:8px; margin:10px 0}
button.t{font:700 .78rem var(--body); border:1px solid var(--line); border-radius:999px;
background:var(--panel); color:var(--ink); padding:3px 8px; cursor:pointer}
button.t:has(.ty),button.t:has(.ty)[aria-pressed=true]{padding:0; border:0; background:none}
button[aria-pressed=true] .ty{outline:2px solid var(--ink); outline-offset:1px} .lv{flex-wrap:wrap}
.level-title{font-size:.9rem; color:var(--muted); margin-top:10px} .rmark{display:inline-block;
vertical-align:-.08em; margin-right:.35em} .rmark.letter{background:var(--rocket-red); color:#fff;
font:900 .8em var(--display); padding:0 .28em; transform:skew(-10deg)} .rmark img{height:.9em;
width:auto; display:block} .charhead .ct{flex-wrap:wrap} .charhead{--t1:var(--rocket)}
.wrap{overflow-x:auto; position:relative} table{border-collapse:collapse; width:100%;
font-size:.9rem} th,td{padding:6px 8px; border-bottom:1px solid var(--line); text-align:left}
.num{text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums}
.moves,.legend,.assume,.notes{font-size:.82rem; color:var(--muted)} .method{display:grid; gap:12px;
grid-template-columns:minmax(0,1fr); overflow-wrap:anywhere}
.method h2{margin-top:8px} .method .notes{display:grid; gap:6px} .chip{display:inline-block;
border:1px solid var(--line); border-radius:6px; padding:1px 6px} .warn{color:var(--amber)}
.detail{padding:12px; background:var(--bg); display:grid; gap:12px} .metrics{display:grid;
grid-template-columns:24px 2.4fr repeat(6,minmax(74px,1fr)); gap:8px; align-items:start;
min-width:870px} .counter-head{font-size:.78rem; color:var(--muted)}
details.counter{border-bottom:1px solid var(--line)} summary{cursor:pointer}
summary.detail-row{padding:8px 0; display:flex; gap:6px; align-items:baseline; list-style:none}
summary.detail-row::-webkit-details-marker{display:none}
summary.detail-row::before{content:"\\25B8"; width:12px; flex:none}
details[open]>summary.detail-row::before{content:"\\25BE"}
.detail-row .metrics{flex:1} .detail-row .spr{vertical-align:middle}
@media(max-width:699px){.metrics{min-width:0; grid-template-columns:22px minmax(0,1fr) auto}
.metrics>:nth-child(n+4){display:none} .counter-head{padding-left:18px}}
.sr-only{position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden;
clip:rect(0,0,0,0); white-space:nowrap; border:0}
a:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);
outline-offset:2px} [hidden]{display:none!important}
.tyfilter{margin:2px 0 8px} .tyfilter>summary{cursor:pointer; font-weight:700; font-size:.85rem;
color:var(--muted)} .tyfilter .controls{margin-top:8px} @media(max-width:699px){.top{gap:2px;
padding:6px 10px} .top a{padding:6px 9px} .disc{padding:6px 14px} .charhead{padding:10px 14px}
.charhead h1{font-size:1.3rem} .charhead .ct{gap:6px; margin-bottom:4px}
.charhead .hint{margin-bottom:3px} .lineup{gap:3px} .slot{gap:4px; padding:2px 6px;
border-radius:8px} .charhead .lsp{width:32px; height:32px} .sn{font-size:.9rem; width:16px}
.card{padding:10px; margin-top:10px} .bar{gap:4px} .card h2{font-size:1.1rem}
.lv button{padding:4px 8px} .row{gap:2px 6px; padding:7px 0;
grid-template-columns:16px 36px minmax(0,1fr) 58px} .row .spr{width:36px; height:36px}
.row .nm{font-size:.9rem} .row .score b{font-size:1.1rem} .row .mv{font-size:.75rem}
.set{font-size:.75rem; margin-bottom:4px} .tough{font-size:.7rem} }
"""
# Filtering only hides server-rendered rows. Without JS all rows and levels remain available.
FILTER_JS = """
document.querySelectorAll('.tyfilter').forEach(c=>c.hidden=false);
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{
const s=b.closest('[data-level]'),t=b.dataset.filter;
s.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',x===b));
s.querySelector('[data-filter-label]').textContent=t?': '+b.textContent.trim():'';
s.querySelectorAll('[data-types]').forEach(r=>{
r.hidden=t!==''&&!JSON.parse(r.dataset.types).includes(t);
});
const rows=[...s.querySelectorAll('[data-types]')].filter(r=>!r.hidden);
const warning=s.querySelector('[data-best-warning]');
warning.hidden=rows.length===0||Number(rows[0].dataset.win)>=0.5;
rows.forEach((r,i)=>r.querySelector('[data-rank]').textContent=i+1);
});"""
LEVEL_JS = """
document.querySelectorAll('[data-levels]').forEach(card=>{
const buttons=[...card.querySelectorAll('[data-show-level]')];
function show(level){
buttons.forEach(b=>b.setAttribute('aria-pressed',b.dataset.showLevel===level));
card.querySelectorAll('[data-level]').forEach(s=>s.hidden=s.dataset.level!==level);
document.querySelectorAll('[data-lineup-level]').forEach(s=>{
s.hidden=s.dataset.lineupLevel!==level;
});
}
buttons.forEach(b=>b.onclick=()=>show(b.dataset.showLevel));
show(buttons[0].dataset.showLevel);
card.querySelector('.lv').hidden=false;
card.querySelectorAll('.level-title').forEach(h=>h.hidden=true);
});"""


def e(value):
    return escape(str(value), quote=True)


def chip(value, kind=""):
    return f'<span class="chip {kind}">{e(value)}</span>'


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
    return e(formatted)


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
    )


def shield_policy(data):
    shields = data.get("player_shield_policy", "not recorded")
    return {
        "first_two": "shields the first two charged attacks",
        "never": "never shields",
        "threshold": "shields according to the configured HP threshold",
    }.get(shields, str(shields).replace("_", " "))


def settings(data, level):
    params = data.get("params", {})
    ivs = params.get("ivs", {})
    iv_text = "/".join(str(ivs.get(k, "not recorded")) for k in ("atk", "def", "hp"))
    rocket = data.get("rules", {}).get("rocket_shields")
    rocket_text = {True: "as in game", False: "disabled"}.get(rocket, "not recorded")
    return (
        f'<p class="set">Your counter: level {e(level)} · {e(iv_text)} · '
        f"you {e(shield_policy(data).replace('shields', 'shield'))} · "
        f"Rocket shields {e(rocket_text)}</p>"
    )


def assumptions(data, level):
    params = data.get("params", {})
    ivs = params.get("ivs", {})
    iv_text = "/".join(str(ivs.get(k, "not recorded")) for k in ("atk", "def", "hp"))
    policy = data.get("player_policy", "not recorded")
    shields = shield_policy(data)
    policy = {
        "ChargedWhenReady": "uses charged moves when ready (first affordable move)",
        "FastOnly": "uses fast moves only",
    }.get(policy, str(policy).replace("_", " "))
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
    return f'<div class="method-meta">{strip}</div>'


def page_legends():
    return (
        '<p class="legend" id="elite-tm">Elite TM: the move can\'t be taught by a normal TM and '
        "needs an Elite TM, or was only available at a Community Day or event. PvPoke's elite "
        "and legacy moves are both included. Ranked by win rate, HP left, then turns. "
        "Type filters show counters of the selected attacker type. "
        "Expand a counter for its details.</p>"
    )


def notes(data, coverage_view=None):
    fields = (
        ("Model notes", "limitations"),
        ("Rocket moveset pool", "moveset_pool_note"),
        ("Equal-weight model", "weighting_note"),
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
    return f'<div class="notes">{body}</div>'


THEME_HEAD_JS = (
    "try{var t=localStorage.getItem('pogo-theme');"
    "if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}catch(e){}"
)
THEME_TOGGLE = (
    '<button type="button" class="theme-toggle" hidden aria-label="Switch to dark theme">'
    '<svg class="moon" viewBox="0 0 24 24" width="18" height="18" '
    'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" fill="none" '
    'aria-hidden="true">'
    '<path d="M21 12.8A9 9 0 1 1 11.2 3 7.1 7.1 0 0 0 21 12.8Z"/></svg>'
    '<svg class="sun" viewBox="0 0 24 24" width="18" height="18" '
    'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" fill="none" '
    'aria-hidden="true" style="display:none">'
    '<circle cx="12" cy="12" r="4"/>'
    '<path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.93 4.93l1.42 1.42'
    'M17.65 17.65l1.42 1.42M19.07 4.93l-1.42 1.42M6.35 17.65l-1.42 1.42"/>'
    "</svg></button>"
)
THEME_JS = """
(function(){
  var button=document.querySelector('.theme-toggle');
  var root=document.documentElement;
  var preference=window.matchMedia('(prefers-color-scheme: dark)');
  var dark=root.dataset.theme ? root.dataset.theme==='dark' : preference.matches;
  function update(){
    button.setAttribute('aria-label',dark?'Switch to light theme':'Switch to dark theme');
    button.querySelector('.moon').style.display=dark?'none':'';
    button.querySelector('.sun').style.display=dark?'':'none';
  }
  preference.addEventListener('change',function(event){
    if(!root.dataset.theme){dark=event.matches;update()}
  });
  button.addEventListener('click',function(){
    dark=!dark;
    root.dataset.theme=dark?'dark':'light';
    try{localStorage.setItem('pogo-theme',root.dataset.theme)}catch(e){}
    update();
  });
  update();
  button.hidden=false;
})();
"""


def rocket_mark(assets=frozenset(), prefix=""):
    if "brand/rocket-r.png" in assets:
        return (
            '<span class="rmark" aria-hidden="true">'
            f'<img src="{e(prefix)}brand/rocket-r.png" alt=""></span>'
        )
    return '<span class="rmark letter" aria-hidden="true">R</span>'


def navigation(prefix="", current=""):
    links = (
        ("index.html", "Home"),
        ("list/all.html", "All"),
        ("index.html#grunts", "Grunts"),
        ("index.html#leaders", "Leaders"),
    )
    return "".join(
        f'<a href="{e(prefix + href)}"'
        + (' aria-current="page"' if label == current else "")
        + f">{e(label)}</a>"
        for href, label in links
    )


def document(title, data, body, nav=None, *, script=False, prefix="", assets=frozenset()):
    """Render with asset output names and a prefix relative to this page's directory."""
    validation_status(data)  # Preserve clean validation errors before publishing any page.
    fonts = "".join(
        f"@font-face{{font-family:Lato;font-weight:{weight};font-display:swap;"
        f'src:url("{e(prefix)}fonts/lato-{weight}.woff2") format("woff2")}}\n'
        for weight in (400, 700, 900)
        if f"fonts/lato-{weight}.woff2" in assets
    )
    stamp = data.get("computed_for_battle_date", data.get("battle_date"))
    when = f" · Data: {e(battle_date(stamp))}" if stamp else ""
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<script>{THEME_HEAD_JS}</script>\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{e(title)}</title>\n<style>{fonts}{CSS}</style>\n</head>\n<body>\n"
        '<div class="topwrap"><nav class="top" aria-label="Pages">'
        f"{navigation(prefix) if nav is None else nav}{THEME_TOGGLE}</nav></div>\n"
        '<div class="disc"><b>Simulator estimates.</b> Not yet checked against in-game battles. '
        f'<a href="{e(prefix)}how.html">How these numbers work</a>{when}</div>\n'
        f"<main>{body}</main>\n"
        + (f"<script>{FILTER_JS}</script>\n" if script else "")
        + f"<script>{LEVEL_JS}</script>\n<script>{THEME_JS}</script>\n"
        + "</body>\n</html>\n"
    )


def heading(identifier):
    """Readable PvPoke id: DRAGON_BREATH -> Dragon Breath; the shadow chip carries the form."""
    words = str(identifier).removesuffix("_shadow").replace("_", " ").split()
    return " ".join(w.capitalize() for w in words)


def tag(text, kind="", title=""):
    return f'<span class="tag {e(kind)}" title="{e(title)}">{e(text)}</span>'


def content_tags(row, prefix=""):
    species = row.get("speciesId", "")
    body = tag("Shadow", "sh") if row.get("form") == "shadow" or species.endswith("_shadow") else ""
    if row.get("pause_band", {}).get("sensitive") is True:
        body += (
            f'<a class="tag warn" href="{e(prefix)}how.html#pause" '
            'title="Win rate swings with how long Rocket pauses after a charged attack">'
            "Timing-sensitive</a>"
        )
    return body


def moves(row):
    def move(key):
        name = row.get(key, "not recorded")
        flags = row.get("move_flags", {}).get(name, {})
        kinds = [k for k in ("elite", "legacy") if flags.get(k)]
        badge = (
            tag("Elite TM", "el", f"{kinds[0].capitalize()} move: needs an Elite TM")
            if kinds
            else ""
        )
        return f'<span title="{e(name)}">{e(heading(name))}</span>' + badge

    return f"{move('fast_move')} · {move('charged_move')}"


def counter_name(row, prefix=""):
    species = row.get("speciesId", row.get("species", "not recorded"))
    return (
        f'<span class="mon" title="{e(species)}">{e(heading(species))}</span> '
        + content_tags(row, prefix)
        + f'<span class="moves" style="display:block">{moves(row)}</span>'
    )


class Sprites:
    """Load only sprites actually rendered, through the same bounded asset reader."""

    def __init__(self, directory=None):
        self.directory = directory
        self.assets = {}
        self.checked = set()
        self.requested = set()

    def render(self, species, *, prefix="", size=44, cls="spr"):
        base = str(species).removesuffix("_shadow")
        self.requested.add(base)
        if re.fullmatch(r"[a-z0-9_]+", base) and base not in self.checked:
            self.checked.add(base)
            self.assets.update(
                load_assets(
                    self.directory,
                    [(f"{base}.png", f"sprites/{base}.png", b"\x89PNG\r\n\x1a\n", 131072)],
                )
            )
        key = f"sprites/{base}.png"
        if key in self.assets:
            return (
                f'<img class="{e(cls)}" src="{e(prefix + key)}" alt="" '
                f'width="{e(size)}" height="{e(size)}" loading="lazy">'
            )
        return (
            f'<span class="{e(cls)} ph" aria-hidden="true" '
            f'style="--sprite-size:{e(size)}px">'
            f"{e(heading(base)[:2].upper())}</span>"
        )


def lineup_species(rows):
    return (
        [
            (slot.get("slot", index), [v["species"] for v in slot.get("species", [])])
            for index, slot in enumerate(rows[0].get("per_slot", []), 1)
        ]
        if rows
        else []
    )


def lineup_block(rows, sprites, prefix="../"):
    body = '<p class="hint">Their possible Pokémon</p><div class="lineup">'
    for slot, species in lineup_species(rows):
        body += f'<div class="slot"><span class="sn">{e(slot)}</span>'
        body += "".join(
            f'<span class="lm" title="{e(heading(s))}">'
            f"{sprites.render(s, prefix=prefix, size=32, cls='lsp')}</span>"
            for s in species[:6]
        )
        if len(species) > 6:
            body += f'<span class="more">+{e(len(species) - 6)}</span>'
        body += "</div>"
    return body + "</div>"


def character_header(name, type_name, icons, assets, *, lineup="", prefix="../"):
    tint = f' style="--t1:var(--ty-{e(type_name)})"' if type_name in TYPES else ""
    return (
        f'<header class="charhead"{tint}><div class="ct">'
        f"<h1>{rocket_mark(assets, prefix)}{e(name)}</h1>"
        + (type_chip(type_name, icons, prefix=prefix) if type_name else "")
        + f"</div>{lineup}</header>"
    )


def coverage(view):
    text = view.get("coverage", {}).get("text", "coverage not recorded")
    return f"<p>{e(text)}</p>{chip('equal weights: model choice')}"


def unavailable(reason):
    reason = str(reason)
    return notice(reason if reason.startswith("not calculated") else "not calculated · " + reason)


def ordered(rows):
    return sorted(
        rows,
        key=lambda r: (
            -r["win_rate"],
            -r.get("mean_player_hp_fraction_left", 0),
            r.get("mean_turns", 0),
        ),
    )


# Owner ruling: pages open on level 50; other levels are a tap away.
DEFAULT_LEVEL = "50"


def levels(data, results):
    """Level keys with the default level first, then ascending."""
    return sorted(
        {"40", "50", *results, *(f"{v:g}" for v in data.get("params", {}).get("levels", []))},
        key=lambda v: (v != DEFAULT_LEVEL, float(v)),
    )


def type_chip(t, icons, *, prefix="", small=False):
    if t not in TYPES:
        return e(t)
    icon = (
        f'<img src="{e(prefix)}types/{e(t)}.png" alt="" width="18" height="18">'
        if t in icons
        else ""
    )
    if small:
        # The local image is optional; keep an accessible icon-only fallback too.
        icon = icon or f'<span class="type-symbol" aria-hidden="true">{e(t[:1].upper())}</span>'
        return (
            f'<span class="ty ty-{e(t)} ty-icon" title="{e(t)}" aria-label="{e(t)}">{icon}</span>'
        )
    return f'<span class="ty ty-{e(t)}">{icon}{e(t)}</span>'


def notice(text):
    return f'<p class="notice">{e(text)}</p>'


def counter_rows(rows, sprites, *, icons=frozenset(), prefix="../", toughest=False):
    body = '<ol class="rows">'
    for rank, row in enumerate(rows, 1):
        species = row.get("speciesId", "not recorded")
        types = [t for t in row.get("types", []) if t != "none"]
        tint = next((t for t in types if t in TYPES), "normal")
        body += (
            f'<li class="row" style="--t1:var(--ty-{e(tint)})" '
            f'data-types="{e(json.dumps(types))}" data-win="{e(row["win_rate"])}">'
            f'<span class="rk" data-rank>{e(rank)}</span>'
            f'{sprites.render(species, prefix=prefix)}<div class="who">'
            f'<div class="nm">{e(heading(species))} <span class="tys">'
            + "".join(type_chip(t, icons, prefix=prefix, small=True) for t in types)
            + f'</span>{content_tags(row, prefix)}</div><div class="mv">{moves(row)}</div>'
        )
        worst = (
            min(
                (v for slot in row.get("per_slot", []) for v in slot.get("species", [])),
                key=lambda v: v["conditional_win_rate"],
                default=None,
            )
            if toughest
            else None
        )
        if worst and worst["conditional_win_rate"] < 0.95:
            body += (
                '<span class="tough">Toughest: '
                + sprites.render(worst["species"], prefix=prefix, size=22, cls="mini")
                + f" {e(heading(worst['species']))} "
                f"({floor(worst['conditional_win_rate'] * 1000) / 10:.1f}% win)</span>"
            )
        hp = row.get("mean_player_hp_fraction_left")
        kos = row.get("mean_rocket_knocked_out")
        hp_text = f"{hp * 100:.0f}% HP left" if hp is not None else "HP not recorded"
        ko_text = f"{kos:.1f} KOs" if kos is not None else "KOs not recorded"
        body += (
            f'</div><div class="sec"><span>{e(hp_text)}</span><span>{e(ko_text)}</span></div>'
            f'<div class="score"><b>{e(percentage(row["win_rate"]))}</b><span>win</span></div></li>'
        )
    return body + "</ol>"


def level_buttons(level_keys):
    return (
        '<div class="lv" role="group" aria-label="Counter level" hidden>'
        + "".join(
            f'<button type="button" data-show-level="{e(v)}" '
            f'aria-pressed="{"true" if i == 0 else "false"}">Level {e(v)}</button>'
            for i, v in enumerate(level_keys)
        )
        + "</div>"
    )


def list_body(
    data,
    results,
    reason,
    extra="",
    *,
    overall=False,
    icons=frozenset(),
    sprites=None,
    prefix="../",
    limit=None,
    title="Best counters",
    footer="",
):
    sprites = sprites or Sprites()
    level_keys = levels(data, results)
    body = (
        extra + '<section class="card" data-levels><div class="bar">'
        f"<h2>{e(title)}</h2>{level_buttons(level_keys)}</div>"
    )
    if reason:
        body += unavailable(reason)
    for level in level_keys:
        rows = ordered(results.get(level, []))
        if limit:
            rows = rows[:limit]
        body += (
            f'<section id="level-{e(level)}" data-level="{e(level)}">'
            f'<h3 class="level-title">Level {e(level)}</h3>{settings(data, level)}'
        )
        if not rows:
            if not reason:
                body += unavailable("no full results at this level")
            body += "</section>"
            continue
        if limit is None:
            types = sorted({t for row in rows for t in row.get("types", []) if t in TYPES})
            # Owner ruling: collapsed by default, like PvPoke and Pokebattler's filter controls.
            body += (
                '<details class="tyfilter" hidden><summary>Filter by type'
                "<span data-filter-label></span></summary>"
                '<div class="controls" role="group" aria-label="Attacker types">'
            )
            body += '<button class="t" data-filter="" aria-pressed="true">All types</button>'
            body += "".join(
                f'<button class="t" data-filter="{e(t)}" aria-pressed="false">'
                f"{type_chip(t, icons, prefix=prefix)}</button>"
                for t in types
            )
            body += (
                '</div></details><noscript><p class="moves">Without JavaScript all types are shown.'
                "</p></noscript>"
            )
        body += counter_rows(rows, sprites, icons=icons, prefix=prefix, toughest=not overall)
        body += (
            f'<p class="notice" data-best-warning'
            f"{' hidden' if rows[0]['win_rate'] >= 0.5 else ''}>"
            "best counter loses most battles</p></section>"
        )
    return body + footer + "</section>"


def calc_summary(rows, grade_order):
    """Retain numeric ranges over Rocket movesets without repeated grade labels."""
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
            values = [v for v, _ in cells]
            body += (
                f'<td class="num">{estimate(min(values))}'
                + ("" if min(values) == max(values) else f"–{estimate(max(values))}")
                + "</td>"
            )
        body += "</tr>"
    return body + "</tbody></table></div>"


def counter_detail(row, data):
    body = '<div class="detail">'
    band = row.get("pause_band")
    if band:
        body += (
            "<p>Pause band: "
            f"{e(band['turns'][0])}–{e(band['turns'][-1])} turns: "
            f"{estimate(band['min'], percent=True)}–{estimate(band['max'], percent=True)}</p>"
        )
    screen = row.get("screen", {})
    if screen:
        body += "<h3>Stage-1 screen · slot 1v1 win rates</h3>"
        for slot, rate in enumerate(screen.get("slot_win_rates", []), 1):
            body += f"<p>Screen slot {slot}: {estimate(rate, percent=True)}</p>"
    body += "<h3>Full battle · conditional win rate per Rocket species in each slot</h3>"
    body += (
        '<div class="wrap"><table><caption>Conditional win rates · '
        "per species</caption>"
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


def counters_body(data, results, reason, *, sprites=None):
    sprites = sprites or Sprites()
    level_keys = levels(data, results)
    body = (
        '<section class="card" data-levels><div class="bar"><h2>Battle details</h2>'
        + level_buttons(level_keys)
        + "</div>"
    )
    if reason:
        body += unavailable(reason)
    for level in level_keys:
        body += (
            f'<section id="level-{e(level)}" data-level="{e(level)}">'
            f'<h3 class="level-title">Level {e(level)}</h3>{settings(data, level)}'
        )
        rows = ordered(results.get(level, []))
        if not rows:
            if not reason:
                body += unavailable("no full results at this level")
            body += "</section>"
            continue
        body += '<div class="wrap"><div class="metrics counter-head" aria-hidden="true">'
        body += (
            "".join(
                f"<span>{e(n)}</span>"
                for n in (
                    "#",
                    "Counter",
                    "Win rate",
                    "Draw",
                    "Rocket KOs",
                    "Solo sweep",
                    "HP left",
                    "Turns",
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
                '<details class="counter"><summary class="detail-row"><span class="metrics">'
                f"<span>{e(rank)}.</span><span>"
                + sprites.render(row.get("speciesId", "not recorded"), prefix="../", size=32)
                + counter_name(row, "../")
                + "</span>"
            )
            for key, label, percent in columns:
                body += (
                    f'<span class="num"><span class="sr-only">{e(label)}: </span>'
                    f"{estimate(row.get(key), percent=percent)}</span>"
                )
            body += "</span></summary>" + counter_detail(row, data) + "</details>"
        body += "</div></section>"
    return body + "</section>"


def tile(
    title,
    href,
    data,
    results,
    reason,
    *,
    rank="grunt",
    type_name=None,
    icons=frozenset(),
    sprites=None,
):
    sprites = sprites or Sprites()
    level = next((v for v in levels({}, results) if results.get(v)), DEFAULT_LEVEL)
    rows = ordered(results.get(level, []))
    rank_label = {"boss": "Boss", "grunt": "Grunt"}.get(rank, "Leader")
    badge = (
        type_chip(type_name, icons, small=True)
        if type_name
        else (f'<span class="rk-badge">{e(rank_label)}</span>')
    )
    lead = lineup_species(rows)
    lead_sprites = "".join(
        sprites.render(s, size=30, cls="lsp") for s in (lead[0][1][:3] if lead else [])
    )
    body = (
        f'<article class="cc"><a class="cch" href="{e(href)}">{badge}'
        f'<h3>{e(title)}</h3><span class="lead">{lead_sprites}</span></a>'
    )
    if rows:
        body += (
            '<ol class="top3">'
            + "".join(
                "<li>"
                + sprites.render(r.get("speciesId", "not recorded"), size=32)
                + f"<span>{e(heading(r.get('speciesId', 'not recorded')))}"
                + content_tags(r)
                + "</span>"
                + f"<b>{e(percentage(r['win_rate']))}</b></li>"
                for r in rows[:3]
            )
            + "</ol>"
        )
    else:
        body += unavailable(reason or f"no full results at level {level}")
    return body + "</article>"


def grade_differences(rows):
    """Describe exceptional published rows without adding tags to ranked lists."""
    body = '<h2 id="row-grades">Rows that differ from the usual grade</h2>'
    if rows:
        usual_grade = Counter(row[3] for row in rows).most_common(1)[0][0]
        usual_pool = Counter(row[4] for row in rows if row[3] == usual_grade).most_common(1)[0][0]
        differences = []
        for name, level, species, grade, pool in rows:
            if grade == usual_grade and pool == usual_pool:
                continue
            pool_text = {True: "pool complete", False: "pool incomplete"}.get(
                pool, "pool completeness not recorded"
            )
            differences.append(
                f"<li>{e(name)} · level {e(level)} · {e(heading(species))}: "
                f"{e(grade or 'grade not recorded')} · {pool_text}.</li>"
            )
        if differences:
            return body + "<ul>" + "".join(differences) + "</ul>"
    return body + "<p>None: every published row carries the usual grade.</p>"


def how_body(data, *, pause_legends=(), screen_notes=(), grade_rows=()):
    body = (
        '<section class="card method"><h2>Validation and provenance</h2>'
        + trust_strip(data)
        + provenance(data)
        + (
            notice("newer than our sources: rules assumed unchanged")
            if data.get("valid_for", {}).get("extrapolated")
            else ""
        )
        + "<h2>Assumptions</h2>"
        + "".join(assumptions(data, level) for level in levels(data, {}))
        + f"<p>{e(data.get('filter_note', 'Filter note not recorded'))}</p>"
        + "<h2>Reading the rows</h2>"
        + page_legends()
        + '<h2 id="pause">Rocket pause and sensitivity</h2>'
        + ("".join(pause_legends) or "<p>Pause band not computed for this run.</p>")
        + "<h2>Stage-1 grid</h2>"
        + "".join(f"<p>{e(note)}</p>" for note in screen_notes)
        + grade_differences(grade_rows)
        + "<h2>Grade vocabulary</h2><dl>"
        "<dt>estimate</dt><dd>A simulator result, not a measurement of in-game battles.</dd>"
        "<dt>unverified</dt><dd>Not yet checked against in-game battles.</dd>"
        "<dt>extrapolated forward</dt><dd>Newer than our sources; rules assumed unchanged.</dd>"
        "<dt>stats parity-only</dt><dd>Stat scaling has parity checks, not battle validation.</dd>"
        "</dl>"
    )
    for grade in data.get("grades", []):
        body += f"<p><b>{e(grade.get('id', ''))}.</b> {e(grade.get('meaning', ''))}</p>"
    for key in ("grade_note", "slots_swept_note"):
        if data.get(key):
            body += f"<p>{e(data[key])}</p>"
    for view in ("all", "grunts", "leaders"):
        body += f"<h3>{e(view.capitalize())} coverage</h3>" + coverage(data.get(view, {}))
    return body + "<h2>Sources, credits and limitations</h2>" + notes(data) + "</section>"


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
            r"(?:(?:index|how|(?:list|counters)/[a-z0-9]+(?:-[a-z0-9]+)*)\.html"
            r"|types/[a-z]+\.png|sprites/[a-z0-9_]+\.png"
            r"|brand/rocket-r\.png|fonts/lato-(?:400|700|900)\.woff2)",
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


def load_assets(directory, specs):
    """Read only named, bounded regular files with the expected signature, without links.

    Each spec supplies the source name, output key, signature and byte limit.
    """
    assets = {}
    if directory is None:
        return assets
    for name, key, signature, limit in specs:
        try:
            fd = os.open(Path(directory) / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                    continue
                content = stream.read(limit + 1)
                if len(content) <= limit and content.startswith(signature):
                    assets[key] = content
        except OSError:
            continue
    return assets


def load_type_icons(directory):
    return load_assets(
        directory, ((f"{name}.png", name, b"\x89PNG\r\n\x1a\n", 65536) for name in TYPES)
    )


def load_brand_assets(directory):
    return load_assets(
        directory,
        [
            ("rocket-r.png", "brand/rocket-r.png", b"\x89PNG\r\n\x1a\n", 65536),
            *(
                (f"lato-{w}.woff2", f"fonts/lato-{w}.woff2", b"wOF2", 131072)
                for w in (400, 700, 900)
            ),
        ],
    )


def render_site(data_dir, type_icons=None, brand_assets=None, sprites=None):
    root = Path(data_dir).resolve()
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
        overall_notice = notice(
            f"stale · This overall list was computed for battle date {stamp} and is older than "
            "the per-type lists, which have changed since it was computed."
        )
    icon_data = load_type_icons(type_icons)
    brand_data = load_brand_assets(brand_assets)
    sprite_store = Sprites(sprites)
    icons = set(icon_data)
    pages = {f"types/{name}.png": content for name, content in icon_data.items()}
    pages.update(brand_data)
    all_view = overall.get("all", {}) if not overall_reason else {}
    index_body = (
        '<section class="hero"><h1>' + rocket_mark(brand_data) + "Rocket counters</h1>"
        "<p>The best Pokémon to beat each Team GO Rocket grunt and leader, "
        "from a battle simulator.</p></section>"
        + list_body(
            overall_meta,
            all_view.get("results", {}),
            overall_reason,
            overall_notice,
            overall=True,
            icons=icons,
            sprites=sprite_store,
            prefix="",
            limit=5,
            title="Best all-round",
            footer='<a class="more-link" href="list/all.html">Full list →</a>',
        )
    )
    grids = {"leaders": [], "grunts": []}
    method_sections, pause_legends, grade_rows = [], [], []
    screen_notes = {}

    def collect_rows(name, results, meta):
        for rows in results.values():
            for row in rows:
                screen = row.get("screen", {})
                for note in (screen.get("grid_limitation"), screen.get("note")):
                    if note:
                        screen_notes[note] = None
        if meta.get("screen_note"):
            screen_notes[meta["screen_note"]] = None
        grade_rows.extend(
            (
                name,
                level,
                row.get("speciesId", "not recorded"),
                row.get("grade"),
                row.get("pool_complete"),
            )
            for level, rows in results.items()
            for row in rows
        )

    for view, title in (("all", "All Rocket"), ("grunts", "Grunts"), ("leaders", "Leaders")):
        results = overall.get(view, {}).get("results", {}) if not overall_reason else {}
        collect_rows(title, results, overall_meta)
    # Process one character at a time: a real report can contain megabytes of calc cells.
    for entry in manifest["characters"]:
        data, reason = read_report(root, entry)
        check_dates(data)
        report = data.get("character", {})
        if report.get("name") != entry["name"] and not reason:
            reason = "stale report: character name does not match manifest entry"
        reason = reason or report.get("reason", "")
        meta = metadata(data, entry)
        results = report.get("finalists", {}) if not reason else {}
        slug, name = entry["slug"], entry["name"]
        type_name = slug.split("-")[0] if entry.get("rank") == "grunt" else None
        if type_name not in TYPES:
            type_name = None
        group = "grunts" if entry.get("rank") == "grunt" else "leaders"
        grids[group].append(
            tile(
                name,
                f"list/{slug}.html",
                meta,
                results,
                reason,
                rank="boss" if slug == "giovanni" else entry.get("rank"),
                type_name=type_name,
                icons=icons,
                sprites=sprite_store,
            )
        )
        # Lineups follow the same level switch as the counter sections. Both render without JS.
        lineup = "<div data-lineups>"
        for level in levels(meta, results):
            rows = ordered(results.get(level, []))
            if rows:
                lineup += (
                    f'<div data-lineup-level="{e(level)}">'
                    + lineup_block(rows, sprite_store)
                    + "</div>"
                )
        lineup += "</div>"
        header = character_header(name, type_name, icons, brand_data, lineup=lineup)
        body = list_body(meta, results, reason, icons=icons, sprites=sprite_store)
        body += f'<a class="more-link" href="../counters/{e(slug)}.html">Battle details</a>'
        pages[f"list/{slug}.html"] = document(
            f"{name} · top counters",
            meta,
            header + body,
            script=True,
            prefix="../",
            assets=brand_data,
        )
        pages[f"counters/{slug}.html"] = document(
            f"{name} · counters",
            meta,
            character_header(name, type_name, icons, brand_data)
            + counters_body(meta, results, reason, sprites=sprite_store)
            + f'<a class="more-link" href="../list/{e(slug)}.html">Ranked list</a>',
            prefix="../",
            assets=brand_data,
        )
        # Preserve file-specific provenance, settings, pause bands and notes in the method page.
        collect_rows(name, results, meta)
        pause_legends.append(f"<p><b>{e(name)}.</b> {pause_band_legend(meta)}</p>")
        method_sections.append(
            f'<section class="card method" id="c-{e(slug)}"><h2>{e(name)}</h2>'
            + (unavailable(reason) if reason else "")
            + trust_strip(meta)
            + provenance(meta)
            + "".join(assumptions(meta, level) for level in levels(meta, results))
            + notes(meta, all_view)
            + "</section>"
        )
        del data, report, results, meta
    for view, title in (("all", "All Rocket"), ("grunts", "Grunts"), ("leaders", "Leaders")):
        data = overall.get(view, {}) if not overall_reason else {}
        pages[f"list/{view}.html"] = document(
            f"{title} · top counters",
            overall_meta,
            character_header(title, None, icons, brand_data)
            + list_body(
                overall_meta,
                data.get("results", {}),
                overall_reason,
                overall_notice,
                overall=True,
                icons=icons,
                sprites=sprite_store,
            ),
            script=True,
            prefix="../",
            assets=brand_data,
        )
    for group, title in (("leaders", "Leaders"), ("grunts", "Grunts")):
        index_body += (
            f'<h2 class="grp" id="{e(group)}">{e(title)}</h2>'
            f'<a class="more-link" href="list/{e(group)}.html">Full '
            f'{"grunt" if group == "grunts" else "leader"} list →</a><div class="grid">'
            + "".join(grids[group])
            + "</div>"
        )
    pages["index.html"] = document(
        "Rocket counters",
        overall_meta,
        index_body,
        navigation(current="Home"),
        assets=brand_data,
    )
    pages["how.html"] = document(
        "How these numbers work",
        overall_meta,
        '<header class="hero"><h1>'
        + rocket_mark(brand_data)
        + "How these numbers work</h1></header>"
        + how_body(
            overall_meta,
            pause_legends=pause_legends,
            screen_notes=screen_notes,
            grade_rows=grade_rows,
        )
        + "".join(method_sections),
        assets=brand_data,
    )
    pages.update(sprite_store.assets)
    return pages, sprite_store.requested


def build_site(data_dir, out, type_icons=None, brand_assets=None, sprites=None):
    if Path(out).is_symlink():
        raise ValueError("output symlink points outside --out")
    destination = Path(out).resolve()
    check_destination(destination)
    pages, _ = render_site(data_dir, type_icons, brand_assets, sprites)
    publish_pages(destination, pages)
    return sum(name.endswith(".html") for name in pages)


# Owner ruling: the form people mean when a species has no plain sprite file.
DEFAULT_SPRITE_FORMS = {"zygarde": "COMPLETE"}


def sprite_files(data_dir, cache_dir, tree_path):
    """Resolve the bases requested by the renderer against cached source and tree data."""
    manifest = json.loads((Path(data_dir) / "manifest.json").read_text())
    if not any(s.get("url") == PVPOKE_GM_URL for s in manifest["sources"]):
        raise ValueError("gamemaster URL missing from report sources")
    digest = hashlib.sha256(PVPOKE_GM_URL.encode()).hexdigest()
    try:
        entry = json.loads((Path(cache_dir) / "sources" / f"{digest}.json").read_text())
        if entry["url"] != PVPOKE_GM_URL or entry["status"] != 200:
            raise ValueError("wrong URL or status")
        body = entry["body"]
        if isinstance(body, str):
            body = json.loads(body)
        pokemon = body["pokemon"]
        if not isinstance(pokemon, list) or not pokemon:
            raise ValueError("pokemon must be a nonempty list")
        dex = {p["speciesId"]: p["dex"] for p in pokemon}
        if any(not isinstance(k, str) or type(v) is not int or v < 1 for k, v in dex.items()):
            raise ValueError("invalid species or dex number")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"missing or invalid gamemaster cache entry: {exc}") from exc
    try:
        tree = json.loads(Path(tree_path).read_text())
        if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
            raise ValueError("expected an object with a tree list")
        if any(
            not isinstance(item, dict) or not isinstance(item.get("path"), str)
            for item in tree["tree"]
        ):
            raise ValueError("tree entries must be objects with string paths")
        names = {item["path"] for item in tree["tree"]}
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid sprite tree: {exc}") from exc
    names = {name for name in names if re.fullmatch(r"pm[0-9]+(?:\.f[A-Z0-9_]+)?\.icon\.png", name)}
    _, bases = render_site(data_dir)
    result, skipped = {}, []
    aliases = {"alolan": "ALOLA", "galarian": "GALARIAN", "hisuian": "HISUIAN", "paldean": "PALDEA"}
    for base in sorted(bases):
        if not re.fullmatch(r"[a-z0-9_]+", base) or base not in dex:
            skipped.append(base)
            continue
        number = dex[base]
        parents = [s for s, n in dex.items() if n == number and base.startswith(s + "_")]
        suffix = base[len(min(parents, key=len)) + 1 :] if parents else base.partition("_")[2]
        prefix = f"pm{number}"
        candidates = []
        if suffix:
            candidates.append(f"{prefix}.f{aliases.get(suffix, suffix.upper())}.icon.png")
        candidates.append(f"{prefix}.icon.png")
        if base in DEFAULT_SPRITE_FORMS:
            candidates.append(f"{prefix}.f{DEFAULT_SPRITE_FORMS[base]}.icon.png")
        candidates.append(f"{prefix}.fNORMAL.icon.png")
        candidates.extend(sorted(name for name in names if name.startswith(prefix + ".f")))
        choice = next((name for name in candidates if name in names), None)
        if choice:
            result[base] = choice
        else:
            skipped.append(base)
    return result, skipped


def add_parser(commands):
    sub = commands.add_parser("site", help="Render precompute reports as offline static HTML")
    sub.add_argument("--data", type=Path, required=True)
    sub.add_argument("--out", type=Path, required=True)
    sub.add_argument("--type-icons", type=Path)
    sub.add_argument("--brand-assets", type=Path)
    sub.add_argument("--sprites", type=Path)
    sub = commands.add_parser("site-sprites", help="List sprite filenames for site species")
    sub.add_argument("--data", type=Path, required=True)
    sub.add_argument("--cache-dir", type=Path, required=True)
    sub.add_argument("--tree", type=Path, required=True)


def main_site(args, arg_parser):
    try:
        build_site(args.data, args.out, args.type_icons, args.brand_assets, args.sprites)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        arg_parser.error(str(exc))
    return 0


def main_site_sprites(args, arg_parser):
    try:
        files, skipped = sprite_files(args.data, args.cache_dir, args.tree)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        arg_parser.error(str(exc))
    if skipped:
        print("skipped sprite bases: " + ", ".join(repr(s) for s in skipped), file=sys.stderr)
    for base, filename in files.items():
        print(base, filename)
    return 0
