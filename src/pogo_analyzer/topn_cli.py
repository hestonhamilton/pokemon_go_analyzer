"""Source and JSON adapter for two-stage offline counter estimates."""

import json
import sys
from datetime import date
from functools import partial
from math import prod
from pathlib import Path

from . import calc_cli as calc
from . import memlog, topn
from . import sim_cli as sim
from .sim.calculator import calculate_matchup
from .sim.grades import GRADES, grade_row, weakest
from .sim.rocket import DEFAULT_ROCKET_RULES, _era, rule_data, rules_dict
from .sim.stats import player_stats, rcpm
from .sim.validation import DEFAULT_FIXTURES, run_acceptance
from .sim.winrate import SORT_NOTE


def add_parser(commands):
    sub = commands.add_parser("topn", help="Two-stage offline solo counter ranking (estimate)")
    select = sub.add_mutually_exclusive_group(required=True)
    select.add_argument("--character")
    select.add_argument("--all", action="store_true")
    add_options(sub)
    sub.add_argument("--format", choices=("json",), default="json")


def add_options(sub):
    """Shared ranking inputs; command selection and execution options stay separate."""
    sub.add_argument("--battle-date", help="ISO date (default: today's local date)")
    sub.add_argument("--level", type=float, action="append")
    sub.add_argument("--trainer-level", type=int, default=50)
    sub.add_argument("--k", type=int, default=30)
    sub.add_argument(
        "--pause-band", type=topn.parse_pause_band, default="6,8", help="Pause lengths, or none"
    )
    sub.add_argument(
        "--pause-threshold",
        type=topn.parse_pause_threshold,
        default=topn.PAUSE_BAND_THRESHOLD,
        help="Win-rate spread that marks a row pause-sensitive (model choice; default 0.15)",
    )
    sub.add_argument("--candidates", help="Comma-separated PvPoke species IDs or names")
    sub.add_argument("--exclude-elite-legacy", action="store_true")
    sub.add_argument("--rcpm-table", choices=calc.TABLES, default="dec-2025")
    sub.add_argument("--fixtures-dir", type=Path, default=DEFAULT_FIXTURES)
    sub.add_argument("--cache-dir", type=Path, default=Path(".cache/pokebattler"))


def _decorate(row, candidate, context, pools, records, args, validation):
    """Keep calc's cell structure and sim's exact stat-grade dependencies."""
    rows, grades = [], []
    attacker, fast, charged = candidate.attacker
    for slot, pool in enumerate(pools, 1):
        for option in pool:
            defender = records[option.species]
            matchup = calculate_matchup(
                attacker,
                defender,
                fast,
                charged,
                option.combatant.fast,
                option.combatant.charged,
                trainer_level=args.trainer_level,
                rank=context["rank"],
                table=args.rcpm_table,
            )
            matchup.update(
                character=context["character"], slot=slot, moveset_pool=calc._pool(defender)
            )
            graded = grade_row(
                matchup, validation, {"fast": fast, "rocket_fast": option.combatant.fast}
            )
            grades.extend(graded[k]["grade"] for k in sim.STAT_CELLS)
            grades.extend(
                move["damage"]["grade"]
                for key in ("charged", "rocket_charged")
                for move in graded[key]["value"]
            )
            rows.append(graded)
    row.update(context, calc_rows=rows)
    row["team"] = [
        {
            "species": attacker["speciesId"],
            "level": attacker["level"],
            "ivs": dict(attacker["ivs"]),
            "fast": fast.id,
            "charged": [move.id for move in charged],
            "form": attacker["form"],
            "shadow": attacker["form"] == "shadow",
        }
    ]
    return sim._grade(row, weakest(*grades))


def _screen_stats_grade(candidate, context, pools, records, args, validation):
    """Screen grades depend on every resolved option, just as full sim grades do."""
    return weakest(
        *(
            sim._stats_grade(
                candidate.attacker,
                option,
                records[option.species],
                args,
                context["rank"],
                validation,
            )
            for pool in pools
            for option in pool
        )
    )


def prepare_output(args):
    """Validate inputs and prepare shared provenance and character pools, without battles."""
    stamp = sim._iso_date(
        args.battle_date if args.battle_date is not None else date.today().isoformat()
    )
    era, _ = _era(stamp, rule_data())
    topn.validate_pause_band(args.pause_band, era)
    if args.k < 1:
        raise ValueError("--k must be positive")
    levels = sorted(
        {float(level) for level in (args.level if args.level is not None else (40, 50))}
    )
    for level in levels:
        player_stats({"atk": 1, "def": 1, "hp": 1}, topn.IVS, level)
    rcpm(args.trainer_level, args.rcpm_table)
    selectors = None
    if args.candidates is not None:
        selectors = [s.strip() for s in args.candidates.split(",")]
        if not all(selectors):
            raise ValueError("--candidates must be a nonempty comma-separated species list")
    characters, species, moves, sources = calc.load_sources(args.cache_dir)
    selected = characters if args.all else calc.matching_characters(args.character, characters)
    topn.validate_character_names(c.name for c in selected)
    candidates, skipped = topn.build_candidates(
        species,
        moves,
        levels,
        selectors=selectors,
        exclude_elite_legacy=args.exclude_elite_legacy,
    )
    validation = run_acceptance(args.fixtures_dir)
    reports, unresolved, unavailable, planned = [], [], [], {}
    for character in selected:
        pools, missing, records = sim._pools(character, species, moves, args)
        unresolved.extend(missing)
        context = {
            "character": character.name,
            "rank": calc.character_rank(character),
            "trainer_level": args.trainer_level,
            "rcpm_table": args.rcpm_table,
            "exclude_elite_legacy": args.exclude_elite_legacy,
            "pool_complete": not missing,
            "pool_scope": "resolved options only; incomplete pool" if missing else "all options",
            "slot_option_counts": [len(p) for p in pools],
        }
        report = {
            "name": character.name,
            "rank": context["rank"],
            "slot_option_counts": context["slot_option_counts"],
            "pool_complete": context["pool_complete"],
            "finalists": {f"{level:g}": [] for level in levels},
        }
        reports.append(report)
        planned[character.name] = context, pools, records
        if any(not p for p in pools):
            report["reason"] = topn.UNAVAILABLE
            unavailable.append(
                {
                    **context,
                    "label": "estimate (every number)",
                    "lineups": 0,
                    "battles": 0,
                    "reason": topn.UNAVAILABLE,
                }
            )
    eligible = [report for report in reports if "reason" not in report]
    screen_battles = len(candidates) * topn.SAMPLES * len(eligible)
    lineup_battles = sum(
        # K species per order (two orders), each sending its top MOVESETS movesets in each order:
        # at most 4 x MOVESETS x K builds per level (12K at 3); ties at the cut can add more.
        args.k * 2 * 2 * topn.MOVESETS * len(levels) * prod(report["slot_option_counts"])
        for report in eligible
    )
    print(
        f"estimate: planned stage-1 sample lineup battles: {screen_battles}; "
        f"maximum stage-2 lineup battles: {lineup_battles}. "
        "--all adds union completion battles.",
        file=sys.stderr,
    )
    data = {
        "validation_label": validation["label"],
        "estimate_label": "estimate (every number)",
        "battle_date": stamp,
        "battle_date_source": "default: run date" if args.battle_date is None else "explicit",
        "era": era["id"],
        "rules": rules_dict(DEFAULT_ROCKET_RULES),
        "player_policy": "ChargedWhenReady",
        "player_shield_policy": "first_two",
        "mode": "two-stage solo counter ranking",
        "sort": SORT_NOTE,
        "validation": validation,
        "sources": sources,
        "credits": calc.CREDITS,
        "limitations": sim.LIMITATIONS,
        "moveset_pool_note": calc.POOL_NOTE,
        "filter_note": "PvPoke eliteMoves and legacyMoves excluded from candidate and Rocket pools"
        if args.exclude_elite_legacy
        else "PvPoke eliteMoves and legacyMoves included",
        "exclude_elite_legacy": args.exclude_elite_legacy,
        "rcpm_note": calc.CP_ONLY if args.rcpm_table == "dec-2025" else None,
        "grades": GRADES,
        "grade_note": sim.GRADE_NOTE,
        "slots_swept_note": sim.SWEEP_NOTE,
        "unresolved": unresolved,
        "unavailable": unavailable,
        "params": {
            "levels": levels,
            "ivs": dict(topn.IVS),
            "trainer_level": args.trainer_level,
            "k": args.k,
            "pause_band": list(args.pause_band),
            "pause_threshold": args.pause_threshold,
            "exclude_elite_legacy": args.exclude_elite_legacy,
            "candidate_count": len({c.species_id for c in candidates}),
        },
        "screen_note": topn.SCREEN_NOTE,
        "weighting_note": topn.WEIGHTING_NOTE,
        "skipped": skipped,
        "characters": reports,
    }
    return data, planned, candidates


def rank_report(
    report,
    planned,
    candidates,
    args,
    validation,
    *,
    mapper=map,
    trial_runner=None,
    battle_date=None,
):
    """Fill one prepared report with the engine's decorated finalists."""
    if "reason" in report:
        return
    context, pools, records = planned
    stamp = battle_date or sim._iso_date(
        args.battle_date if args.battle_date is not None else date.today().isoformat()
    )
    by_key = {c.key: c for c in candidates}
    species = moves = None
    if context["rank"] != "grunt":
        _, species, moves, _ = calc.load_sources(args.cache_dir)
    ranked = topn.rank_character(
        candidates,
        pools,
        k=args.k,
        rank=context["rank"],
        battle_date=stamp,
        trial_runner=trial_runner,
        mapper=mapper,
        pause_band=args.pause_band,
        pause_threshold=args.pause_threshold,
        # The worker receives a module-level callable over picklable source inputs.
        stats_grade=partial(
            _screen_stats_grade,
            context=context,
            pools=pools,
            records=records,
            args=args,
            validation=validation,
        ),
        pool_complete=context["pool_complete"],
        two_charged=context["rank"] != "grunt",
        species=species,
        moves=moves,
        exclude_elite_legacy=args.exclude_elite_legacy,
    )
    if species is not None:
        grouped = {
            level: [by_key[topn.row_key(row)] for row in rows if len(row["charged_moves"]) == 1]
            for level, rows in ranked.items()
        }
        pairs = topn.two_charged_candidates(
            species, moves, grouped, exclude_elite_legacy=args.exclude_elite_legacy
        )
        by_key.update({c.key: c for c in pairs})
    for level, rows in ranked.items():
        for row in rows:
            key = topn.row_key(row)
            _decorate(row, by_key[key], context, pools, records, args, validation)
        report["finalists"][f"{level:g}"] = rows


def complete_overall(data, planned, candidates, args, *, mapper=map, trial_runner=None):
    """Complete the finalist union across all available characters."""
    reports = data["characters"]
    stamp, validation = data["battle_date"], data["validation"]
    by_key = {c.key: c for c in candidates}
    results = {
        report["name"]: {
            topn.row_key(row): row
            for rows in report["finalists"].values()
            for row in rows
            if len(row.get("charged_moves", [row["charged_move"]])) == 1
        }
        for report in reports
    }
    union = sorted({key for rows in results.values() for key in rows})
    for report in reports:
        name = report["name"]
        context, pools, records = planned[name]
        if "reason" in report:
            continue
        pending = [key for key in union if key not in results[name]]
        print(f"estimate: {name}: completing {len(pending)} overall builds.", file=sys.stderr)
        memlog.log(f"overall, before {name}")
        builds = [by_key[key] for key in pending]
        rows = topn.full_results(
            builds,
            pools,
            mapper=mapper,
            rank=context["rank"],
            battle_date=stamp,
            trial_runner=trial_runner,
        )
        for candidate, row in zip(builds, rows, strict=True):
            row.update(
                candidate.output(),
                screen=topn.screen_candidate(
                    candidate,
                    pools,
                    rank=context["rank"],
                    battle_date=stamp,
                    stats_grade=_screen_stats_grade(
                        candidate, context, pools, records, args, validation
                    ),
                    pool_complete=context["pool_complete"],
                ),
            )
            row = _decorate(row, candidate, context, pools, records, args, validation)
            # Overall-only builds keep their grade, not the per-option calc cells.
            row.pop("calc_rows")
            results[name][candidate.key] = row
    overall = {"weighting_note": topn.WEIGHTING_NOTE}
    for name, ranks in (
        ("all", None),
        ("grunts", {"grunt"}),
        ("leaders", {"leader", "giovanni"}),
    ):
        view = topn.overall_view(reports, results, ranks=ranks)
        for rows in view["results"].values():
            for row in rows:
                sim._grade(row, row["stats_grade"])
        overall[name] = view
    overall["coverage"] = overall["all"]["coverage"]
    return overall


def build_output(args):
    data, planned, candidates = prepare_output(args)
    for report in data["characters"]:
        rank_report(
            report,
            planned[report["name"]],
            candidates,
            args,
            data["validation"],
            trial_runner=sim._timed_trials,
            battle_date=data["battle_date"],
        )
    if args.all:
        data["overall"] = complete_overall(
            data,
            planned,
            candidates,
            args,
            trial_runner=sim._timed_trials,
        )
    return data


def main_topn(args, arg_parser):
    try:
        data = build_output(args)
    except (ValueError, OSError) as exc:
        arg_parser.error(str(exc))
    print(json.dumps(data, indent=2))
    return 0
