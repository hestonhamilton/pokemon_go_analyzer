"""Source and output adapter for offline Rocket estimates."""

import csv
import json
import math
import multiprocessing
import os
import re
import signal
import sys
import time
from dataclasses import asdict
from datetime import date
from functools import partial
from pathlib import Path

from . import calc_cli as calc
from .sim.calculator import calculate_matchup
from .sim.grades import GRADES, grade_row, weakest
from .sim.rocket import DEFAULT_ROCKET_RULES, rocket_combatant, simulate_rocket
from .sim.stats import rcpm
from .sim.validation import DEFAULT_FIXTURES, run_acceptance
from .sim.winrate import (
    GRID_NOTE,
    SORT_NOTE,
    Option,
    aggregate,
    battle_summary,
    grid,
    lineups,
    moveset_ids,
    player_combatant,
    sort_results,
)

LIMITATIONS = (
    "Every number is an estimate until the in-game checks are done. "
    "Rocket lineups and movesets are weighted equally because no appearance-rate source exists "
    "(model choice). Player ChargedWhenReady (first affordable move in supplied order) and "
    "first_two shields are model choices. Both sides start at full HP and zero energy. "
    "Every ledger flag applies. Move effects, voluntary switching, Mega and special moves are "
    "unsupported. Battle date selects rules, not historical moves: cached moves and the explicit "
    "rCPM table are used. Purified IVs must already include their gain."
)
STAT_CELLS = (
    "attacker_attack",
    "attacker_defence",
    "attacker_hp",
    "rocket_attack",
    "rocket_defence",
    "rocket_hp",
    "rocket_cp",
    "rank",
    "rank_multiplier",
    "rocket_cpm",
    "rcpm_table",
    "trainer_level",
    "fast_damage",
    "fast_damage_per_turn",
    "rocket_fast_damage",
    "rocket_fast_damage_per_turn",
)
GRADE_NOTE = (
    "stats_grade is the weakest grade_row grade over "
    + ", ".join(STAT_CELLS)
    + ", and every nested damage cell in charged and rocket_charged, for every used matchup. "
    "Rules stay estimate; any unverified battle flag makes rules_grade unverified (ledger l). "
    "The headline always starts with estimate and reports both grades."
)
SWEEP_NOTE = (
    "A Rocket faint is credited to the player member active on its turn, including a same-turn "
    "double knockout. Lead sweep requires all three Rocket faints credited to player slot 1."
)
PARALLEL_AFTER = 120.0
# At most four processes in all, counting this parent, which collects and
# aggregates the results in order: three workers plus the parent.
MAX_PROCESSES = 4


LARGE_SELECTION = 500_000


def _cpus():
    # CPUs this process may use (affinity, cgroup cpusets), where the OS reports it.
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count()


def _workers():
    return min(MAX_PROCESSES - 1, (_cpus() or 1) - 1)


def _ignore_interrupt():
    # Workers ignore Ctrl-C; the parent stops the pool, so no worker tracebacks print.
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def _pool_context():
    # fork starts only the workers. spawn and forkserver also start a POSIX
    # helper process, so they are used only where fork is unavailable.
    methods = multiprocessing.get_all_start_methods()
    return multiprocessing.get_context("fork" if "fork" in methods else "spawn")


def _iso_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("--battle-date must be an ISO date YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid --battle-date: {exc}") from None
    return value


def add_parser(commands):
    sub = commands.add_parser("sim", help="Offline Rocket win rate and slots swept (estimate)")
    sub.add_argument("--character", required=True)
    sub.add_argument("--battle-date", required=True)
    sub.add_argument("--per-slot", action="store_true")
    sub.add_argument("--slot", type=int, choices=(1, 2, 3))
    sub.add_argument("--exclude-elite-legacy", action="store_true")
    sub.add_argument("--trainer-level", type=int, required=True)
    sub.add_argument("--rcpm-table", choices=calc.TABLES, default="dec-2025")
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


def _pools(character, species, moves, args):
    pools, unresolved, records = [], [], {}
    for slot, encounters in enumerate(character.slots, 1):
        pool = []
        for encounter in encounters:
            try:
                item = calc._rocket_species(encounter.species, species)
                calc._check_rocket_species(item)
                pairs = moveset_ids(item, exclude_elite_legacy=args.exclude_elite_legacy)
            except ValueError as exc:
                unresolved.append(
                    {
                        "character": character.name,
                        "slot": slot,
                        "species": encounter.species,
                        "reason": str(exc),
                    }
                )
                continue
            # Special move rejection is the calculator's rejection, not a filtered pool.
            for f, c in pairs:
                fast = calc._move(calc._resolve(f, moves, "moveId", "name"))
                charged = calc._move(calc._resolve(c, moves, "moveId", "name"))
                combatant = rocket_combatant(
                    item["baseStats"],
                    item["types"],
                    fast,
                    (charged,),
                    trainer_level=args.trainer_level,
                    rank=calc.character_rank(character),
                    table=args.rcpm_table,
                )
                pool.append(Option(item["speciesId"], combatant))
                records[item["speciesId"]] = item
        pools.append(pool)
        if not encounters:
            unresolved.append(
                {
                    "character": character.name,
                    "slot": slot,
                    "species": None,
                    "reason": "empty event-info slot",
                }
            )
    return pools, unresolved, records


def _stats_grade(attacker, option, defender, args, rank, validation):
    item, fast, charged = attacker
    row = calculate_matchup(
        item,
        defender,
        fast,
        charged,
        option.combatant.fast,
        option.combatant.charged,
        trainer_level=args.trainer_level,
        rank=rank,
        table=args.rcpm_table,
    )
    graded = grade_row(row, validation, {"fast": fast, "rocket_fast": option.combatant.fast})
    grades = [graded[k]["grade"] for k in STAT_CELLS]
    grades += [
        m["damage"]["grade"] for k in ("charged", "rocket_charged") for m in graded[k]["value"]
    ]
    return weakest(*grades)


def _grade(row, stats):
    row["stats_grade"] = stats
    parts = ["estimate"]
    if row["rules_grade"] == "unverified":
        parts.append("unverified (l)")
    if "extrapolated" in row["flags"]:
        parts.append("extrapolated forward")
    row["grade"] = "; ".join([*parts, f"stats {stats}"])
    if not row["pool_complete"]:
        # Resolved options only: the headline must not read as full-pool coverage.
        row["grade"] += "; pool incomplete"
    return row


def _trial(lineup, *, team, rank, battle_date, rules):
    result = simulate_rocket(
        team, tuple(o.combatant for o in lineup), rank=rank, battle_date=battle_date, rules=rules
    )
    return lineup, battle_summary(result, team)


def _timed_trials(team, pools, *, rank, battle_date, execution):
    """Serial until this character actually exceeds two minutes; preserve result order."""
    pending = lineups(pools)
    run = partial(_trial, team=team, rank=rank, battle_date=battle_date, rules=DEFAULT_ROCKET_RULES)
    start = time.perf_counter()
    execution.update(mode="serial", workers=1)
    workers = _workers()
    for lineup in pending:
        yield run(lineup)
        if workers >= 1 and time.perf_counter() - start > PARALLEL_AFTER:
            execution.update(
                mode="serial then stdlib multiprocessing",
                workers=workers,
                processes=workers + 1,
            )
            print(
                "estimate: character exceeded 120 seconds; continuing full enumeration with "
                f"stdlib multiprocessing ({workers} workers plus this process, "
                f"{workers + 1} in all), in serial result order.",
                file=sys.stderr,
            )
            with _pool_context().Pool(workers, initializer=_ignore_interrupt) as pool:
                yield from pool.imap(run, pending, chunksize=32)
            break
    execution["runtime_seconds"] = time.perf_counter() - start


def build_output(args):
    stamp = _iso_date(args.battle_date)
    if args.slot is not None and not args.per_slot:
        raise ValueError("--slot requires --per-slot; full battles always use all three slots")
    rcpm(args.trainer_level, args.rcpm_table)
    configs = calc._team(args)
    if not 1 <= len(configs) <= 3:
        raise ValueError("sim team must contain one to three Pokemon")
    characters, species, moves, sources = calc.load_sources(args.cache_dir)
    selected = calc.matching_characters(args.character, characters)
    attackers = calc.build_attackers(configs, species, moves)
    team = tuple(player_combatant(*a) for a in attackers)
    validation = run_acceptance(args.fixtures_dir)
    rows, aggregates, unresolved, unavailable = [], [], [], []
    planned = [(c, _pools(c, species, moves, args)) for c in selected]
    if not args.per_slot:
        total = sum(math.prod(len(p) for p in pools) for _, (pools, _, _) in planned)
        if total > LARGE_SELECTION:
            print(
                f"estimate: this selection enumerates {total:,} lineups across "
                f"{len(planned)} characters; a narrower --character runs faster.",
                file=sys.stderr,
            )
    for character, (pools, missing, records) in planned:
        rank = calc.character_rank(character)
        unresolved.extend(missing)
        context = {
            "character": character.name,
            "rank": rank,
            "trainer_level": args.trainer_level,
            "rcpm_table": args.rcpm_table,
            "team": [
                dict(config, species=a[0]["speciesId"])
                for config, a in zip(configs, attackers, strict=True)
            ],
            "exclude_elite_legacy": args.exclude_elite_legacy,
            "pool_complete": not missing,
            "pool_scope": "resolved options only; incomplete pool" if missing else "all options",
            "slot_option_counts": [len(p) for p in pools],
        }
        used_slots = [j for j in range(3) if args.slot is None or args.slot == j + 1]
        if not args.per_slot and any(not p for p in pools):
            unavailable.append(
                {
                    **context,
                    "label": "estimate (every number)",
                    "lineups": 0,
                    "battles": 0,
                    "reason": "not calculated: at least one slot has no resolved options",
                }
            )
            continue
        grades = {}
        for i, attacker in enumerate(attackers, 1):
            for j, pool in enumerate(pools, 1):
                if args.per_slot and j - 1 not in used_slots:
                    continue
                for option in pool:
                    key = (
                        i,
                        j,
                        option.species,
                        option.combatant.fast.id,
                        option.combatant.charged[0].id,
                    )
                    grades[key] = _stats_grade(
                        attacker, option, records[option.species], args, rank, validation
                    )
        if args.per_slot:
            results, groups = grid(team, pools, rank=rank, battle_date=stamp, slot=args.slot)
            for row in results:
                i, j = row["player_slot"], row["slot"]
                row.update(context, attacker=attackers[i - 1][0]["speciesId"])
                key = i, j, row["species"], row["rocket_fast_move"], row["rocket_charged_move"]
                rows.append(_grade(row, grades[key]))
            for row in groups:
                i, j = row["player_slot"], row["slot"]
                row.update(context, attacker=attackers[i - 1][0]["speciesId"])
                aggregates.append(
                    _grade(row, weakest(*(g for k, g in grades.items() if k[:2] == (i, j))))
                )
        else:
            execution = {}
            row = aggregate(
                team, _timed_trials(team, pools, rank=rank, battle_date=stamp, execution=execution)
            )
            row.update(context, execution=execution)
            rows.append(_grade(row, weakest(*grades.values())))
    if not args.per_slot:
        rows = sort_results(rows)
    return {
        "validation_label": validation["label"],
        "estimate_label": "estimate (every number)",
        "battle_date": stamp,
        "rules": asdict(DEFAULT_ROCKET_RULES),
        "player_policy": "ChargedWhenReady",
        "player_shield_policy": "first_two",
        "mode": "per-slot 1v1 grid" if args.per_slot else "full fixed-order team battles",
        "grid_limitation": GRID_NOTE if args.per_slot else None,
        "exclude_elite_legacy": args.exclude_elite_legacy,
        "sort": SORT_NOTE if not args.per_slot else "attacker order, slot order, source move order",
        "validation": validation,
        "sources": sources,
        "credits": calc.CREDITS,
        "limitations": LIMITATIONS,
        "moveset_pool_note": calc.POOL_NOTE,
        "filter_note": "PvPoke eliteMoves and legacyMoves excluded from Rocket pools"
        if args.exclude_elite_legacy
        else "PvPoke eliteMoves and legacyMoves included",
        "rcpm_note": calc.CP_ONLY if args.rcpm_table == "dec-2025" else None,
        "grades": GRADES,
        "grade_note": GRADE_NOTE,
        "slots_swept_note": SWEEP_NOTE,
        "unresolved": unresolved,
        "unavailable": unavailable,
        "results": rows,
        "aggregates": aggregates,
    }


def render(data, fmt):
    if fmt == "json":
        print(json.dumps(data, indent=2))
        return
    print(data["validation_label"])
    print(data["estimate_label"])
    print(f"Battle date: {data['battle_date']} | {data['mode']}")
    if data["grid_limitation"]:
        print(data["grid_limitation"] + "; each 1v1 starts with fresh shields and full HP.")
    if data["rcpm_note"]:
        print(data["rcpm_note"])
    for source in data["sources"]:
        print(f"{source['name']} fetched {source['fetched_at']} | {source['url']}")
    for row in data["validation"]["open_discrepancies"]:
        print(f"OPEN DISCREPANCY {row['id']}: {row['status_reason']}")
    for row in data["unresolved"]:
        print(
            f"NOT CALCULATED {row['character']} slot {row['slot']}: "
            f"{row['species']}: {row['reason']}"
        )
    for row in data["unavailable"]:
        print(f"NOT CALCULATED {row['character']}: {row['reason']}")
    for name in ("results", "aggregates"):
        rows = data[name]
        if not rows:
            continue
        print(f"{name} (estimate):")
        if fmt == "csv":
            writer = csv.writer(sys.stdout, lineterminator="\n")
            fields = list(rows[0])
            writer.writerow(fields)
            for row in rows:
                writer.writerow(
                    [
                        json.dumps(row[k], ensure_ascii=False)
                        if isinstance(row[k], (dict, list, tuple))
                        else row[k]
                        for k in fields
                    ]
                )
        else:
            if data["grid_limitation"] and name == "results":
                fields = (
                    "character",
                    "slot",
                    "species",
                    "rocket_fast_move",
                    "rocket_charged_move",
                    "player_slot",
                    "attacker",
                    "winner",
                    "ended_by",
                    "turns",
                    "player_hp_fraction_left",
                    "rocket_hp_fraction_left",
                    "grade",
                )
            elif name == "aggregates":
                fields = (
                    "character",
                    "player_slot",
                    "attacker",
                    "slot",
                    "battles",
                    "win_rate",
                    "draws",
                    "grade",
                )
            else:
                fields = (
                    "character",
                    "battles",
                    "win_rate",
                    "draw_rate",
                    "mean_rocket_knocked_out",
                    "lead_sweep_probability",
                    "mean_player_hp_fraction_left",
                    "mean_turns",
                    "grade",
                )
            table = [list(fields)] + [[calc._cell_text(row[k]) for k in fields] for row in rows]
            widths = [max(len(row[i]) for row in table) for i in range(len(fields))]
            for line in table:
                print(
                    " | ".join(
                        value.ljust(width) for value, width in zip(line, widths, strict=True)
                    ).rstrip()
                )
            # Full records retain less prominent metrics and per-result evidence.
            for row in rows:
                print(f"Details: {row['character']} | {row['grade']}")
                for key, value in row.items():
                    if key not in fields:
                        print(f"  {key}: {calc._cell_text(value)}")
    stream = sys.stderr if fmt == "csv" else sys.stdout
    for key in (
        "sort",
        "filter_note",
        "grade_note",
        "slots_swept_note",
        "limitations",
        "moveset_pool_note",
        "credits",
    ):
        print(data[key], file=stream)


def main_sim(args, arg_parser):
    try:
        data = build_output(args)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        arg_parser.error(str(exc))
    render(data, args.format)
    return 0
