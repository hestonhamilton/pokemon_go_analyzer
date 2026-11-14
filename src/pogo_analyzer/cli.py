"""Command line interface for Rocket lineups and counters."""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from pogo_analyzer.calc_cli import add_parser, main_calc
from pogo_analyzer.lineups import default_shield_strategy, load_lineups, resolve_defender
from pogo_analyzer.pokebattler import (
    BadResponse,
    BudgetExceeded,
    CacheError,
    CacheMiss,
    NetworkError,
    NotFound,
    PoliteClient,
    RateLimitedOrBlocked,
    UnexpectedStatus,
)
from pogo_analyzer.rocket_counters import parse_rocket_response, rank

CREDITS = (
    "Counter simulations: Pokebattler (pokebattler.com). "
    "Lineups: WatWowMap event-info. Species data: PvPoke."
)
SHORT_CREDIT = "Pokebattler; WatWowMap event-info; PvPoke"
STOP_ERRORS = (
    BudgetExceeded,
    RateLimitedOrBlocked,
    NetworkError,
    UnexpectedStatus,
    BadResponse,
    CacheError,
)
FIELDS = (
    "defender",
    "rank",
    "counter_id",
    "fast_move",
    "charged_move",
    "overall_rating",
    "power",
    "win_ratio",
    "tdo",
    "time_s",
)


def parser():
    root = argparse.ArgumentParser(prog="pogo-analyzer")
    commands = root.add_subparsers(dest="command", required=True)
    add_parser(commands)
    lineup = commands.add_parser("lineups")
    lineup.add_argument("--cache-dir", type=Path, default=Path(".cache/pokebattler"))
    for command in ("counters", "tally"):
        sub = commands.add_parser(command)
        select = sub.add_mutually_exclusive_group(required=True)
        select.add_argument("--character")
        select.add_argument("--defender")
        sub.add_argument("--tier", choices=[f"RAID_LEVEL_{n}" for n in range(1, 6)])
        sub.add_argument("--slot", type=int, choices=(1, 2, 3))
        sub.add_argument(
            "--attacker-level", type=int, choices=(20, 25, 30, 35, 40, 45, 50), default=40
        )
        sub.add_argument(
            "--shield-strategy",
            choices=("SHIELD_0", "SHIELD_1", "SHIELD_2"),
            help="Passed to Pokebattler as shieldStrategy; the per-slot default copies its site.",
        )
        sub.add_argument(
            "--defender-shield-strategy",
            choices=("SHIELD_0", "SHIELD_1", "SHIELD_2"),
            default="SHIELD_2",
            help="Passed to Pokebattler as defenderShieldStrategy; the default copies its site.",
        )
        sub.add_argument(
            "--sort",
            choices=("overall_rating", "power", "win_ratio", "tdo", "time"),
            default="overall_rating",
        )
        sub.add_argument("--top", type=int, default=10 if command == "counters" else 5)
        sub.add_argument("--format", choices=("table", "json", "csv"), default="table")
        sub.add_argument(
            "--credits-column",
            action="store_true",
            help="Add a source credit to every CSV or table row.",
        )
        sub.add_argument("--cache-dir", type=Path, default=Path(".cache/pokebattler"))
        sub.add_argument("--max-requests", type=int, default=80)
    return root


def output(rows, fields, fmt, credits_column=False):
    if credits_column and fmt in ("csv", "table"):
        fields = (*fields, "source")
        rows = [dict(row, source=SHORT_CREDIT) for row in rows]
    if fmt == "json":
        print(json.dumps({"results": rows, "credits": CREDITS}, indent=2))
    elif fmt == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        print(CREDITS, file=sys.stderr)
    else:
        print(" | ".join(fields))
        for row in rows:
            print(" | ".join(str(row[field]) for field in fields))
        print(CREDITS)


def stopped(exc, requests):
    if isinstance(exc, RateLimitedOrBlocked):
        print(f"stopped: {exc} after {requests} requests; try again later", file=sys.stderr)
        return 3
    if isinstance(exc, BudgetExceeded):
        print(f"stopped: {exc} after {requests} requests", file=sys.stderr)
        return 4
    print(f"stopped: {exc}", file=sys.stderr)
    return 6 if isinstance(exc, CacheError) else 5


def main(argv=None):
    arg_parser = parser()
    args = arg_parser.parse_args(argv)
    if args.command == "calc":
        try:
            return main_calc(args, arg_parser)
        except STOP_ERRORS as exc:
            return stopped(exc, 0)
    if args.command != "lineups":
        if args.defender and not args.tier:
            arg_parser.error("--defender requires --tier")
        if args.top < 1 or args.max_requests < 0:
            arg_parser.error("--top must be positive and --max-requests nonnegative")
    source = PoliteClient(args.cache_dir / "sources", min_interval=0)
    client = PoliteClient(args.cache_dir, max_requests=getattr(args, "max_requests", None))
    try:
        if args.command == "lineups":
            for character in load_lineups(source):
                print(f"{character.name} | {character.tier}")
                for i, pool in enumerate(character.slots, 1):
                    print(f"  {i}: {', '.join(e.species for e in pool)}")
            print(CREDITS)
            return 0
        if args.defender:
            selections = [([args.defender], args.tier, None)]
        else:
            available = load_lineups(source)
            words = set(re.findall(r"\w+", args.character.casefold()))
            characters = [
                c
                for c in available
                if words
                and all(
                    any(
                        word == name_word or (len(word) >= 3 and name_word.startswith(word))
                        for name_word in re.findall(r"\w+", c.name.casefold())
                    )
                    for word in words
                )
            ]
            if not characters:
                print(
                    "No matching character. Available characters: "
                    + ", ".join(c.name for c in available),
                    file=sys.stderr,
                )
                return 7
            selections = [
                (e.candidates, c.tier, i)
                for c in characters
                for i, pool in enumerate(c.slots, 1)
                if args.slot is None or args.slot == i
                for e in pool
            ]
        pending, seen = [], set()
        for candidates, tier, slot in selections:
            shield_strategy = args.shield_strategy or default_shield_strategy(slot)
            key = (tuple(candidates), tier, shield_strategy)
            if key not in seen:
                seen.add(key)
                pending.append((candidates, tier, shield_strategy))
        rows, tally = [], defaultdict(set)
        stop = None
        remaining = []
        sort_key = "effective_combat_time_ms" if args.sort == "time" else args.sort

        def fetch(candidates, tier, shield_strategy):
            return resolve_defender(
                client,
                candidates,
                tier,
                args.attacker_level,
                # Use the site sort and rank results locally.
                sort="POWER",
                shield_strategy=shield_strategy,
                defender_shield_strategy=args.defender_shield_strategy,
            )

        for candidates, tier, shield_strategy in pending:
            try:
                resolved = fetch(candidates, tier, shield_strategy)
            except CacheMiss:
                remaining.append((candidates, tier, shield_strategy))
                continue
            except STOP_ERRORS as exc:
                if stop is None:
                    stop = exc
                client.cache_only = True
                # The failing candidate may have a cached alternative ID.
                try:
                    resolved = fetch(candidates, tier, shield_strategy)
                except (CacheMiss, CacheError):
                    remaining.append((candidates, tier, shield_strategy))
                    continue
            if resolved is None:
                print(f"Unresolved defender: {', '.join(candidates)} ({tier})", file=sys.stderr)
                continue
            defender, data = resolved
            try:
                counters = parse_rocket_response(data, tier=tier).counters
            except ValueError:
                counters = []
            if not counters:
                print(
                    f"Unresolved defender: {defender} ({tier}): no usable results", file=sys.stderr
                )
                continue
            for index, counter in enumerate(rank(counters, sort_key)[: args.top], 1):
                best = counter.best_for(sort_key)
                rows.append(
                    dict(
                        defender=defender,
                        rank=index,
                        counter_id=counter.pokemon_id,
                        fast_move=best.fast_move,
                        charged_move=best.charged_move,
                        overall_rating=best.overall_rating,
                        power=best.power,
                        win_ratio=best.win_ratio,
                        tdo=best.tdo,
                        time_s=best.effective_combat_time_ms / 1000,
                    )
                )
                tally[counter.pokemon_id].add((defender, tier))
        if args.command == "tally":
            fields = ("counter_id", "count", "defenders")
            rows = [
                dict(
                    counter_id=k,
                    count=len(v),
                    defenders=", ".join(f"{defender} ({tier})" for defender, tier in sorted(v)),
                )
                for k, v in sorted(tally.items(), key=lambda item: (-len(item[1]), item[0]))
            ]
        else:
            fields = FIELDS
        output(rows, fields, args.format, args.credits_column)
        if stop is not None:
            code = stopped(stop, client.network_requests + source.network_requests)
            for candidates, tier, _ in remaining:
                print(f"Not fetched: {', '.join(candidates)} ({tier})", file=sys.stderr)
            return code
        return 0
    except STOP_ERRORS as exc:
        return stopped(exc, client.network_requests + source.network_requests)
    except NotFound as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())
