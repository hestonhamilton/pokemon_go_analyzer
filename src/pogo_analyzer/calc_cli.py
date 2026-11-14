"""Lineup calculator I/O. Only the two existing GitHub sources are fetched."""

import csv
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from .lineups import EVENT_INFO_URL, PVPOKE_GM_URL, load_lineups
from .pokebattler import PoliteClient
from .sim.calculator import Move, calculate_matchup
from .sim.grades import COLUMN_MEANINGS, GRADES, grade_row, weakest
from .sim.stats import _data, player_stats, rcpm
from .sim.validation import DEFAULT_FIXTURES, run_acceptance

# Published point tables, including sparse publications. The lower-level interval
# study is not a complete point table; no selection from its intervals is made.
TABLES = tuple(
    name
    for name, table in _data("rcpm.json").items()
    if not any("min" in entry for entry in table["values"].values())
)
SORTS = (
    "fast_turns_to_ko",
    "fast_hits_to_ko",
    "fast_damage",
    "fast_damage_per_turn",
    "rocket_fast_damage",
    "rocket_fast_damage_per_turn",
    "ko_on_incoming_hit",
    "turns_survived",
    "rocket_cp",
    "attacker_hp",
)
CREDITS = "Lineups: WatWowMap event-info (MIT). Species, types and moves: PvPoke (MIT)."
CP_ONLY = "Rocket stats from Oct 2025 on are backed by CP readings only."
LIMITS = (
    "Conditional fast-only arithmetic. Turns to KO and turns survived ignore charged attacks, "
    "pauses, shields and switching. KO occurs on the last counted incoming hit. Charged damage "
    "is unshielded at full charge, with no buffs, timing or turn count. Energy counts start at "
    "zero and ignore real battle behaviour. Stats are before shadow modifiers; damage applies "
    "them once. Purified IVs must already include any purification gain."
)
POOL_NOTE = (
    "Rocket moveset pool: model. Event-info lists species, not moves. All PvPoke species fastMoves "
    "and chargedMoves are hypothetical possibilities, including moves it marks legacy or elite; "
    "no source here establishes which Rocket Pokemon carry. No extra shadow Frustration is "
    "added: neither source settles that addition. Its inclusion in each pool is reported from "
    "PvPoke's chargedMoves verbatim. Conditional damage grades do not validate move availability."
)


def add_parser(commands):
    sub = commands.add_parser("calc", help="Offline conditional lineup arithmetic")
    select = sub.add_mutually_exclusive_group(required=True)
    select.add_argument("--character")
    select.add_argument("--defender")
    sub.add_argument("--rank", choices=("grunt", "leader", "giovanni"))
    sub.add_argument("--slot", type=int, choices=(1, 2, 3))
    sub.add_argument("--trainer-level", type=int, required=True)
    sub.add_argument("--rcpm-table", choices=TABLES, default="dec-2025")
    attack = sub.add_mutually_exclusive_group(required=True)
    attack.add_argument("--attacker")
    attack.add_argument("--team", type=Path)
    sub.add_argument("--level", type=float)
    sub.add_argument("--ivs")
    sub.add_argument("--fast")
    sub.add_argument("--charged", action="append")
    form = sub.add_mutually_exclusive_group()
    form.add_argument("--shadow", action="store_true")
    form.add_argument("--purified", action="store_true")
    sub.add_argument("--fixtures-dir", type=Path, default=DEFAULT_FIXTURES)
    sub.add_argument("--cache-dir", type=Path, default=Path(".cache/pokebattler"))
    sub.add_argument("--format", choices=("table", "json", "csv"), default="table")
    sub.add_argument("--sort", choices=SORTS, default="fast_turns_to_ko")


def _normal(value):
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _resolve(value, items, id_key, name_key):
    # Preserve exact IDs and names before punctuation-insensitive convenience
    # matching: Brick Break and Brick Break+ are distinct moves in PvPoke.
    found = [item for item in items if value.casefold() == item[id_key].casefold()]
    if not found:
        found = [
            item
            for item in items
            if value.casefold() == item.get(name_key, item[id_key]).casefold()
        ]
    if not found:
        found = [item for item in items if _normal(value) == _normal(item[id_key])]
    if not found:
        found = [
            item for item in items if _normal(value) == _normal(item.get(name_key, item[id_key]))
        ]
    if len(found) != 1:
        raise ValueError(f"unknown or ambiguous {id_key}: {value}")
    return found[0]


def _ivs(value):
    if isinstance(value, str):
        parts = value.split("/")
        if len(parts) != 3:
            raise ValueError("IVs must be A/D/H")
        return dict(zip(("atk", "def", "hp"), map(int, parts), strict=True))
    if isinstance(value, dict) and set(value) == {"atk", "def", "hp"}:
        return value
    raise ValueError("IVs must be A/D/H or an atk/def/hp object")


def _team(args):
    if args.team:
        if any(v is not None for v in (args.level, args.ivs, args.fast, args.charged)) or (
            args.shadow or args.purified
        ):
            raise ValueError("--team cannot be combined with individual attacker options")
        entries = json.loads(args.team.read_text())
        if not isinstance(entries, list) or not entries:
            raise ValueError("team must be a nonempty JSON list")
    else:
        if any(v is None for v in (args.level, args.ivs, args.fast, args.charged)):
            raise ValueError("--attacker requires --level, --ivs, --fast and --charged")
        entries = [
            {
                "species": args.attacker,
                "level": args.level,
                "ivs": args.ivs,
                "fast": args.fast,
                "charged": args.charged,
                "shadow": args.shadow,
                "purified": args.purified,
            }
        ]
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("each team entry must be an object")
        extra = set(entry) - {"species", "level", "ivs", "fast", "charged", "shadow", "purified"}
        if extra:
            raise ValueError("unknown team fields: " + ", ".join(sorted(extra)))
        if entry.get("shadow") and entry.get("purified"):
            raise ValueError("shadow and purified are mutually exclusive")
        for key in ("shadow", "purified"):
            if key in entry and not isinstance(entry[key], bool):
                raise ValueError(f"{key} must be boolean")
        if any(key not in entry for key in ("species", "level", "ivs", "fast", "charged")):
            raise ValueError("team entry requires species, level, ivs, fast and charged")
        if not isinstance(entry["charged"], list) or not 1 <= len(entry["charged"]) <= 2:
            raise ValueError("provide one or two charged moves")
        entry["ivs"] = _ivs(entry["ivs"])
        # Validate numbers and form before any source fetch.
        entry["form"] = (
            "shadow" if entry.get("shadow") else ("purified" if entry.get("purified") else "normal")
        )
        player_stats(
            {"atk": 1, "def": 1, "hp": 1}, entry["ivs"], entry["level"], form=entry["form"]
        )
    return entries


def _fetch_time(client, url):
    path = client.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    entry = json.loads(path.read_text())
    if entry["url"] != url or entry["status"] != 200:
        raise ValueError(f"missing successful source cache entry: {url}")
    return datetime.fromtimestamp(entry["fetched_at"], UTC).isoformat()


def _move(item):
    if item.get("percentMaxHP") or item.get("isMegaMove"):
        raise ValueError(f"unsupported special move: {item['moveId']}")
    return Move.from_pvpoke(item)


def _pool(species):
    def info(move):
        return {
            "move": move,
            "elite": move in species.get("eliteMoves", []),
            "legacy": move in species.get("legacyMoves", []),
        }

    return {
        "fast": [info(m) for m in species["fastMoves"]],
        "charged": [info(m) for m in species["chargedMoves"]],
        "frustration_included": "FRUSTRATION" in species["chargedMoves"],
    }


# Event-info spells regional forms with the game's template suffix; PvPoke's
# speciesId uses the adjective. Only this one exact suffix is aliased.
FORM_ALIASES = (("_alola", "_alolan"),)


def _rocket_species(name, species):
    ids = {item["speciesId"] for item in species}
    for suffix, pvpoke in FORM_ALIASES:
        if name not in ids and name.endswith(suffix) and name + pvpoke[len(suffix) :] in ids:
            name = name + pvpoke[len(suffix) :]
    return _resolve(name, species, "speciesId", "speciesName")


def build_output(args):
    if args.defender and args.rank is None:
        raise ValueError("--defender requires --rank")
    if args.character and args.rank is not None:
        raise ValueError("--rank is derived from --character")
    rcpm(args.trainer_level, args.rcpm_table)  # No fallback or interpolation.
    team = _team(args)
    source = PoliteClient(args.cache_dir / "sources", min_interval=0, max_requests=2)
    characters = load_lineups(source)
    gm = source.get_json(PVPOKE_GM_URL)
    species, moves = gm["pokemon"], gm["moves"]
    sources = [
        {"name": name, "url": url, "fetched_at": _fetch_time(source, url), "license": "MIT"}
        for name, url in (("PvPoke", PVPOKE_GM_URL), ("WatWowMap event-info", EVENT_INFO_URL))
    ]
    if args.defender:
        selections = [(None, args.slot, args.defender, args.rank)]
    else:
        # Same word/prefix matching as counters.
        words = set(re.findall(r"\w+", args.character.casefold()))
        found = [
            c
            for c in characters
            if words
            and all(
                any(
                    word == w or (len(word) >= 3 and w.startswith(word))
                    for w in re.findall(r"\w+", c.name.casefold())
                )
                for word in words
            )
        ]
        if not found:
            raise ValueError(
                "No matching character. Available characters: "
                + ", ".join(c.name for c in characters)
            )
        selections = [
            (
                c.name,
                i,
                e.species,
                "giovanni"
                if c.tier == "RAID_LEVEL_5"
                else "leader"
                if c.tier == "RAID_LEVEL_4"
                else "grunt",
            )
            for c in found
            for i, pool in enumerate(c.slots, 1)
            if args.slot is None or args.slot == i
            for e in pool
        ]
    attackers = []
    for config in team:
        item = _resolve(config["species"], species, "speciesId", "speciesName")
        if "_shadow" in item["speciesId"] or "_mega" in item["speciesId"]:
            raise ValueError("use the base species and --shadow; Mega is unsupported")
        fast = _resolve(config["fast"], moves, "moveId", "name")
        charged = [_resolve(m, moves, "moveId", "name") for m in config["charged"]]
        if fast["moveId"] not in item["fastMoves"] or fast["energy"] != 0:
            raise ValueError(f"invalid fast move for {item['speciesId']}")
        if any(m["moveId"] not in item["chargedMoves"] or m["energy"] <= 0 for m in charged):
            raise ValueError(f"invalid charged move for {item['speciesId']}")
        attackers.append(
            (
                dict(item, **{k: config[k] for k in ("level", "ivs", "form")}),
                _move(fast),
                [_move(m) for m in charged],
            )
        )
    rows = []
    unresolved = []
    for character, slot, name, rank in selections:
        try:
            defender = _rocket_species(name, species)
        except ValueError:
            if args.defender:
                raise
            # A lineup species PvPoke lacks stays visible instead of vanishing.
            unresolved.append({"character": character, "slot": slot, "species": name})
            continue
        pool = _pool(defender)
        for fast_id in defender["fastMoves"]:
            fast = _move(_resolve(fast_id, moves, "moveId", "name"))
            charged = [
                _move(_resolve(m, moves, "moveId", "name")) for m in defender["chargedMoves"]
            ]
            for attacker, own_fast, own_charged in attackers:
                row = calculate_matchup(
                    attacker,
                    defender,
                    own_fast,
                    own_charged,
                    fast,
                    charged,
                    trainer_level=args.trainer_level,
                    rank=rank,
                    table=args.rcpm_table,
                )
                row.update(character=character, slot=slot, moveset_pool=pool)
                rows.append(row)
    if not rows:
        raise ValueError("no calculator matchups in the selected slots")
    rows.sort(key=lambda r: r[args.sort])
    return {
        "validation": run_acceptance(args.fixtures_dir),
        "sources": sources,
        "credits": CREDITS,
        "limitations": LIMITS,
        "moveset_pool_note": POOL_NOTE,
        "rcpm_note": CP_ONLY if args.rcpm_table == "dec-2025" else None,
        "grades": GRADES,
        "unresolved": unresolved,
        "results": [grade_row(row) for row in rows],
    }


# The terminal table shows the headline columns; JSON and CSV carry every column.
TABLE_FIELDS = (
    "character",
    "slot",
    "defender",
    "rocket_fast_move",
    "attacker",
    "fast_move",
    "fast_damage",
    "fast_hits_to_ko",
    "fast_turns_to_ko",
    "rocket_fast_damage",
    "ko_on_incoming_hit",
    "turns_survived",
    "rocket_hp",
    "rocket_cp",
    "row_grade",
)


def _cell_text(value):
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _values(value):
    if isinstance(value, dict):
        if set(value) == {"value", "grade"}:
            return _values(value["value"])
        return {k: _values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_values(v) for v in value]
    return value


def render(data, fmt):
    if fmt == "json":
        # The validation label is the first field; the whole document remains JSON.
        print(json.dumps({"validation_label": data["validation"]["label"], **data}, indent=2))
        return
    print(data["validation"]["label"])
    if data["rcpm_note"]:
        print(data["rcpm_note"])
    for s in data["sources"]:
        print(f"{s['name']} fetched {s['fetched_at']} | {s['url']}")
    for r in data["validation"]["open_discrepancies"]:
        print(f"OPEN DISCREPANCY {r['id']}: {r['status_reason']}")
    for u in data["unresolved"]:
        print(f"NOT CALCULATED {u['character']} slot {u['slot']}: {u['species']} is not in PvPoke")
    rows = data["results"]
    if not rows:
        print("No calculator rows.")
        return
    fields = list(rows[0]) if fmt == "csv" else [f for f in TABLE_FIELDS if f in rows[0]]
    grades = {key: weakest(*(row[key]["grade"] for row in rows)) for key in fields}
    values = [_values(row) for row in rows]
    if fmt == "csv":
        writer = csv.writer(sys.stdout, lineterminator="\n")
        writer.writerow(fields)
        writer.writerow([grades[f] for f in fields])
        for row in values:
            writer.writerow(
                [
                    json.dumps(row[f], ensure_ascii=False)
                    if isinstance(row[f], (list, dict))
                    else row[f]
                    for f in fields
                ]
            )
    else:
        table = [fields, [grades[f] for f in fields]]
        table += [[_cell_text(row[f]) for f in fields] for row in values]
        widths = [max(len(line[i]) for line in table) for i in range(len(fields))]
        for line in table:
            print(
                " | ".join(
                    text.ljust(width) for text, width in zip(line, widths, strict=True)
                ).rstrip()
            )
        print("Every column, charged moves and the Rocket move pool: --format json or csv.")
    legend_stream = sys.stderr if fmt == "csv" else sys.stdout
    print("Column grades (weakest across displayed rows):", file=legend_stream)
    for field in fields:
        print(f"{field}: {grades[field]} — {COLUMN_MEANINGS[field]}", file=legend_stream)
    for g in GRADES:
        print(f"{g['id']}: {g['meaning']} Evidence: {', '.join(g['evidence'])}", file=legend_stream)
    print(LIMITS, file=legend_stream)
    print(POOL_NOTE, file=legend_stream)
    print(CREDITS, file=legend_stream)


def main_calc(args, arg_parser):
    try:
        data = build_output(args)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        arg_parser.error(str(exc))
    render(data, args.format)
    return 0
