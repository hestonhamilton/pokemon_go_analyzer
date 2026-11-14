"""Command line interface for Rocket lineups and counters."""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from pogo_analyzer.lineups import default_shields, load_lineups, resolve_defender
from pogo_analyzer.pokebattler import BudgetExceeded, PoliteClient, RateLimitedOrBlocked
from pogo_analyzer.rocket_counters import parse_rocket_response, rank

CREDITS = (
    "Counter simulations: Pokebattler (pokebattler.com). "
    "Lineups: WatWowMap event-info. Species data: PvPoke."
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
            "--attacker-shields", choices=("SHIELD_0", "SHIELD_1", "SHIELD_2"), default="SHIELD_2"
        )
        sub.add_argument("--defender-shields", choices=("SHIELD_0", "SHIELD_2"))
        sub.add_argument(
            "--sort",
            choices=("overall_rating", "power", "win_ratio", "tdo", "time"),
            default="overall_rating",
        )
        sub.add_argument("--top", type=int, default=10 if command == "counters" else 5)
        sub.add_argument("--format", choices=("table", "json", "csv"), default="table")
        sub.add_argument("--cache-dir", type=Path, default=Path(".cache/pokebattler"))
        sub.add_argument("--max-requests", type=int, default=80)
    return root


def output(rows, fields, fmt):
    if fmt == "json":
        print(json.dumps({"results": rows, "credits": CREDITS}, indent=2))
    elif fmt == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        print(CREDITS)
    else:
        print(" | ".join(fields))
        for row in rows:
            print(" | ".join(str(row[field]) for field in fields))
        print(CREDITS)


def main(argv=None):
    arg_parser = parser()
    args = arg_parser.parse_args(argv)
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
            selections = [([args.defender], args.tier)]
        else:
            characters = [
                c for c in load_lineups(source) if args.character.lower() in c.name.lower()
            ]
            selections = [
                (e.candidates, c.tier)
                for c in characters
                for i, pool in enumerate(c.slots, 1)
                if args.slot is None or args.slot == i
                for e in pool
            ]
        rows, tally, seen = [], defaultdict(set), set()
        sort_key = "effective_combat_time_ms" if args.sort == "time" else args.sort
        for candidates, tier in selections:
            key = (tuple(candidates), tier)
            if key in seen:
                continue
            seen.add(key)
            resolved = resolve_defender(
                client,
                candidates,
                tier,
                args.attacker_level,
                # Always the default view: one cached URL per defender, ranked locally.
                sort="OVERALL",
                attacker_shields=args.attacker_shields,
                defender_shields=args.defender_shields or default_shields(tier),
            )
            if resolved is None:
                print(f"Unresolved defender: {', '.join(candidates)} ({tier})", file=sys.stderr)
                continue
            defender, data = resolved
            for index, counter in enumerate(
                rank(parse_rocket_response(data).counters, sort_key)[: args.top], 1
            ):
                best = counter.best
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
                tally[counter.pokemon_id].add(defender)
        if args.command == "tally":
            fields = ("counter_id", "count", "defenders")
            rows = [
                dict(counter_id=k, count=len(v), defenders=", ".join(sorted(v)))
                for k, v in sorted(tally.items(), key=lambda item: (-len(item[1]), item[0]))
            ]
        else:
            fields = FIELDS
        output(rows, fields, args.format)
        return 0
    except RateLimitedOrBlocked as exc:
        requests = client.network_requests + source.network_requests
        print(
            f"HTTP {exc.status}; {requests} requests made; "
            "stopping; fall back to the browser option only on the owner's decision",
            file=sys.stderr,
        )
        return 3
    except BudgetExceeded as exc:
        print(exc, file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
