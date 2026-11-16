"""Pure two-stage counter ranking over the existing offline calculator and simulator."""

from collections import Counter
from dataclasses import dataclass, replace
from fractions import Fraction
from functools import partial
from math import prod
from random import Random
from statistics import mean

from . import calc_cli as calc
from .sim import solo, winrate
from .sim.grades import weakest
from .sim.rocket import DEFAULT_ROCKET_RULES, RocketRules, _era, rule_data, simulate_rocket

SCREEN_NOTE = (
    "Stage 1 plays each build against the same 32 real lineups per level (drawn with a fixed"
    " seed; every lineup once when there are 32 or fewer),"
    " carrying HP, energy and shields from one opponent to the next; its score is the share"
    " of those battles won, draws are not wins, and it is not a lineup win rate."
    " Per species and level the top 2 movesets in each order go forward. Species are ranked"
    " by their best moveset; finalists are the union of the top K by fewest turns and the"
    " top K by HP left, and species level with either K-th are kept."
    " The quick 1-on-1 check on each counter is computed for finalists only."
)
SAMPLES = 32
MOVESETS = 2
WEIGHTING_NOTE = (
    "Equal weight per character is a model choice; no encounter-rate source exists. "
    "Characters without a full result are excluded, never counted as zero."
)
UNAVAILABLE = "not calculated: at least one slot has no resolved options"
IVS = {"atk": 15, "def": 15, "hp": 15}
PAUSE_BAND_THRESHOLD = 0.15
PAUSE_BAND_NOTE = (
    "Pause band is a sensitivity check over assumed pause lengths, not a measured range "
    "(ledger row k); ranking uses the era value."
)


def parse_pause_threshold(value):
    """A win-rate spread in (0, 1); the default 0.15 is a model choice, not a source value."""
    try:
        threshold = float(value)
    except ValueError as exc:
        raise ValueError("--pause-threshold must be a number") from exc
    if not 0 < threshold < 1:
        raise ValueError("--pause-threshold must be between 0 and 1")
    return threshold


def parse_pause_band(value):
    """Normalize CLI lengths so order and duplicates do not change reuse keys."""
    if value.strip().lower() == "none":
        return ()
    try:
        turns = tuple(sorted({int(part.strip()) for part in value.split(",")}))
        for turn in turns:
            RocketRules(pause_turns_override=turn)
    except ValueError:
        raise ValueError(
            "--pause-band must be comma-separated integers from 1 to 20, or none"
        ) from None
    return turns


def validate_pause_band(turns, era):
    if turns and set(turns) == {era["charged"]}:
        raise ValueError("--pause-band must include a length other than the era's charged length")


@dataclass
class Candidate:
    species_id: str
    attacker: tuple
    move_flags: dict

    @property
    def key(self):
        item, fast, charged = self.attacker
        return self.species_id, item["level"], fast.id, charged[0].id

    @property
    def team(self):
        return (winrate.player_combatant(*self.attacker),)

    def output(self):
        item, fast, charged = self.attacker
        return {
            "speciesId": self.species_id,
            "species": item["speciesId"],
            "form": item["form"],
            "types": list(item["types"]),
            "level": item["level"],
            "ivs": dict(item["ivs"]),
            "fast_move": fast.id,
            "charged_move": charged[0].id,
            "move_flags": self.move_flags,
        }


def build_candidates(species, moves, levels, *, selectors=None, exclude_elite_legacy=False):
    """Preserve source entry identity, but construct shadows as base species + form.

    PvPoke entries marked unreleased are omitted. Extracts without release metadata
    retain their entries. Every rejection, including a rejected move pair, is reported.
    """
    selected = (
        {calc._resolve(s, species, "speciesId", "speciesName")["speciesId"] for s in selectors}
        if selectors is not None
        else None
    )
    candidates, skipped = [], []
    for source in sorted(species, key=lambda s: s["speciesId"]):
        name = source["speciesId"]
        if selected is not None and name not in selected:
            continue
        reason = None
        if source.get("released") is False or "unreleased" in source.get("tags", []):
            reason = "unreleased PvPoke entry"
        elif "_mega" in name or "_primal" in name or "mega" in source.get("tags", []):
            reason = "Mega is unsupported by the simulator"
        if reason:
            skipped.append({"speciesId": name, "reason": reason})
            continue
        try:
            pairs = winrate.moveset_ids(source, exclude_elite_legacy=exclude_elite_legacy)
        except ValueError as exc:
            reason = f"{name}: {exc}" if "_shadow" in name else str(exc)
            skipped.append({"speciesId": name, "reason": reason})
            continue
        shadow = "_shadow" in name
        base = name.replace("_shadow", "", 1) if shadow else name
        flags = {m["move"]: m for group in ("fast", "charged") for m in calc._pool(source)[group]}
        for level in levels:
            for fast, charged in pairs:
                config = {
                    "species": base,
                    "level": level,
                    "ivs": dict(IVS),
                    "fast": fast,
                    "charged": [charged],
                    "shadow": shadow,
                    "form": "shadow" if shadow else "normal",
                }
                try:
                    (attacker,) = calc.build_attackers([config], species, moves)
                    candidate = Candidate(name, attacker, {m: flags[m] for m in (fast, charged)})
                    # Validate player stats here so calculator rejections stay visible.
                    _ = candidate.team
                except ValueError as exc:
                    skipped.append(
                        {
                            "speciesId": name,
                            "level": level,
                            "fast_move": fast,
                            "charged_move": charged,
                            "reason": f"{name}: {exc}" if shadow else str(exc),
                        }
                    )
                    continue
                candidates.append(candidate)
    return candidates, skipped


def screen_candidate(
    candidate,
    pools,
    *,
    rank,
    battle_date,
    grid=winrate.grid,
    stats_grade="model",
    pool_complete=True,
):
    """One member against each slot option; empty slots cannot produce a score."""
    if callable(stats_grade):
        stats_grade = stats_grade(candidate)
    _, groups = grid(candidate.team, pools, rank=rank, battle_date=battle_date)
    slots = {g["slot"]: g["win_rate"] for g in groups}
    rates = [slots.get(i) for i in range(1, 4)]
    rules_grade = (
        "unverified" if any(g["rules_grade"] == "unverified" for g in groups) else "estimate"
    )
    flags = sorted({flag for g in groups for flag in g["flags"]})
    parts = ["estimate"]
    if rules_grade == "unverified":
        parts.append("unverified (l)")
    if "extrapolated" in flags:
        parts.append("extrapolated forward")
    parts.append(f"stats {stats_grade}")
    if not pool_complete:
        parts.append("pool incomplete")
    return {
        "label": "estimate (every number)",
        "rules_grade": rules_grade,
        "flags": flags,
        "stats_grade": stats_grade,
        "pool_complete": pool_complete,
        "grade": "; ".join(parts),
        "score": mean(rates) if all(r is not None for r in rates) else None,
        "hp_left": _slot_mean(groups, "mean_player_hp_fraction_left"),
        "turns": _slot_mean(groups, "mean_turns"),
        "slot_win_rates": rates,
        "slot_aggregates": groups,
        "grid_limitation": winrate.GRID_NOTE,
        "note": SCREEN_NOTE,
    }


def _slot_mean(groups, field):
    values = [g.get(field) for g in groups]
    return mean(values) if values and None not in values else None


def screen_margin(screen, order="speed"):
    """Win rate, then the margin: fewer turns first (Pokebattler Time to Win) by default, or
    more HP left first (PvPoke Battle Rating's HP term) for the site's alternative order."""
    hp, turns = -(screen.get("hp_left") or 0), screen.get("turns") or 0
    return (-screen["score"], turns, hp) if order == "speed" else (-screen["score"], hp, turns)


def screen_lineups(pools, level, samples=SAMPLES):
    """The lineups every build at one level meets: all of them when there are at most
    `samples`, otherwise `samples` distinct lineups drawn with a seed from the level and the
    pools, so every build and moveset faces the same battles (common random numbers)."""
    sizes = [len(pool) for pool in pools]
    total = prod(sizes)
    if total <= samples:
        indices = range(total)
    else:
        seed = repr(
            (
                f"{level:g}",
                [
                    [
                        (o.species, o.combatant.fast.id, [m.id for m in o.combatant.charged])
                        for o in pool
                    ]
                    for pool in pools
                ],
            )
        )
        indices = sorted(Random(seed).sample(range(total), samples))
    lineups = []
    for index in indices:
        picks = []
        for pool, size in zip(reversed(pools), reversed(sizes), strict=True):
            index, pick = divmod(index, size)
            picks.append(pool[pick].combatant)
        lineups.append(tuple(reversed(picks)))
    return tuple(lineups)


def sample_screen(
    candidate, pools, *, rank, battle_date, lineups_by_level=None, battle=simulate_rocket
):
    """Whole battles against the level's screen lineups: HP, energy and shields carry over."""
    if not pools or not all(pools):
        return {"score": None, "hp_left": None, "turns": None, "samples": 0}
    level = candidate.key[1]
    lineups = (lineups_by_level or {}).get(level) or screen_lineups(pools, level)
    team = candidate.team
    wins = hp = turns = 0
    for lineup in lineups:
        summary = winrate.battle_summary(
            battle(team, lineup, rank=rank, battle_date=battle_date), team
        )
        wins += summary["winner"] == "player"
        hp += summary["hp_fraction"]
        turns += summary["turns"]
    n = len(lineups)
    return {"score": wins / n, "hp_left": hp / n, "turns": turns / n, "samples": n}


def screen_candidates(candidates, pools, *, rank, battle_date, sampler=None, mapper=map):
    """Stage 1 for every build, in input order; builds without a score are dropped."""
    candidates = list(candidates)
    shared = (
        {level: screen_lineups(pools, level) for level in {c.key[1] for c in candidates}}
        if pools and all(pools)
        else {}
    )
    run = partial(
        sampler or sample_screen,
        pools=pools,
        rank=rank,
        battle_date=battle_date,
        lineups_by_level=shared,
    )
    return [
        (candidate, screen)
        for candidate, screen in zip(candidates, mapper(run, candidates), strict=True)
        if screen["score"] is not None
    ]


def pick_finalists(screened, k, *, movesets=MOVESETS, orders=("speed", "hp")):
    """Top movesets per species in each order; then, per level, the top K species in each
    order (by their best moveset) plus exact ties with each K-th. Returns every kept moveset
    of every kept species, in screen order."""

    def order_key(index, order):
        candidate, screen = screened[index]
        return screen_margin(screen, order), candidate.key

    groups = {}
    for index, (candidate, _) in enumerate(screened):
        groups.setdefault((candidate.key[1], candidate.species_id), []).append(index)
    picks = {}
    for group, indices in groups.items():
        chosen = set()
        for order in orders:
            chosen.update(sorted(indices, key=lambda i, o=order: order_key(i, o))[:movesets])
        picks[group] = chosen
    keep = set()
    for order in orders:
        best = {group: min(order_key(i, order) for i in chosen) for group, chosen in picks.items()}
        counts, cut = {}, {}
        for group in sorted(best, key=best.get):
            level, margin = group[0], best[group][0]
            if counts.get(level, 0) >= k and margin != cut[level]:
                continue
            counts[level] = counts.get(level, 0) + 1
            cut[level] = margin
            keep.add(group)
    kept = [i for group in keep for i in picks[group]]
    return [screened[i] for i in sorted(kept, key=lambda i: order_key(i, "speed"))]


def full_result(
    candidate,
    pools,
    *,
    rank,
    battle_date,
    battle=simulate_rocket,
    trial_runner=None,
    rules=DEFAULT_ROCKET_RULES,
):
    """Exact solo aggregation where supported, otherwise the reference simulator.

    When solo.supports() accepts the input and battle is simulate_rocket, the solo engine
    runs and a supplied trial_runner is skipped; only its execution field is filled in.
    Tests that stub or count trials must force the reference path.
    """
    team = candidate.team
    execution = {}
    if battle is simulate_rocket and solo.supports(team, pools, rules):
        row = solo.aggregate(team, pools, rank=rank, battle_date=battle_date, rules=rules)
        execution.update(mode="exact solo engine", workers=1)
    else:
        if trial_runner is None:
            trials = winrate.trials(
                team, pools, rank=rank, battle_date=battle_date, battle=battle, rules=rules
            )
        else:
            trials = trial_runner(
                team, pools, rank=rank, battle_date=battle_date, execution=execution, rules=rules
            )
        row = winrate.aggregate(team, trials)
    if trial_runner is not None:
        # Keep repeated topn JSON stable without changing sim's timing reports.
        execution.pop("runtime_seconds", None)
        row["execution"] = execution
    return row


def full_results(candidates, pools, *, mapper=map, **kwargs):
    """Map independent candidate battles in input order; trials stay serial by default."""
    return mapper(partial(full_result, pools=pools, **kwargs), candidates)


def rank_character(
    candidates,
    pools,
    *,
    k,
    rank,
    battle_date,
    grid=winrate.grid,
    sampler=None,
    battle=simulate_rocket,
    trial_runner=None,
    stats_grade=None,
    pool_complete=True,
    mapper=map,
    pause_band=(),
    pause_threshold=PAUSE_BAND_THRESHOLD,
):
    """Stage 2 (full battles) for the top movesets of the top K species per level and order."""
    if k < 1:
        raise ValueError("--k must be positive")
    era, _ = _era(battle_date, rule_data())
    validate_pause_band(pause_band, era)
    screened = screen_candidates(
        candidates, pools, rank=rank, battle_date=battle_date, sampler=sampler, mapper=mapper
    )
    finalists = pick_finalists(screened, k)
    counts = {candidate.key[1]: True for candidate, _ in finalists}
    # The quick 1-on-1 table on each counter's details: finalists only.
    grids = list(
        mapper(
            partial(
                screen_candidate,
                pools=pools,
                rank=rank,
                battle_date=battle_date,
                grid=grid,
                stats_grade=stats_grade if stats_grade is not None else "model",
                pool_complete=pool_complete,
            ),
            [c for c, _ in finalists],
        )
    )
    rows = full_results(
        [c for c, _ in finalists],
        pools,
        mapper=mapper,
        rank=rank,
        battle_date=battle_date,
        battle=battle,
        trial_runner=trial_runner,
    )
    levels = {level: [] for level in counts}
    for (candidate, sample), grid_screen, row in zip(finalists, grids, rows, strict=True):
        levels[candidate.key[1]].append(
            {**row, **candidate.output(), "screen": grid_screen, "sample_screen": sample}
        )
    if pause_band and finalists:
        era_turns = era["charged"]
        turns = sorted({era_turns, *pause_band})
        by_key = {row_key(row): row for rows in levels.values() for row in rows}
        reuse_era = era["charged"] == era["faint"]
        runs = {key: {str(era_turns): row} if reuse_era else {} for key, row in by_key.items()}
        builds = [c for c, _ in finalists]
        for turn in turns:
            if turn == era_turns and reuse_era:
                continue
            band_rows = full_results(
                builds,
                pools,
                mapper=mapper,
                rank=rank,
                battle_date=battle_date,
                battle=battle,
                trial_runner=trial_runner,
                rules=replace(DEFAULT_ROCKET_RULES, pause_turns_override=turn),
            )
            for candidate, row in zip(builds, band_rows, strict=True):
                runs[candidate.key][str(turn)] = row
        for key, row in by_key.items():
            band_rows = {str(turn): runs[key][str(turn)] for turn in turns}
            values = {turn: result["win_rate"] for turn, result in band_rows.items()}
            exact_rates = [Fraction(r["wins"], r["battles"]) for r in band_rows.values()]
            low, high = min(values.values()), max(values.values())
            row["pause_band"] = {
                "turns": turns,
                "win_rate": values,
                "wins": {turn: result["wins"] for turn, result in band_rows.items()},
                "battles": {turn: result["battles"] for turn, result in band_rows.items()},
                "flags": sorted({flag for r in band_rows.values() for flag in r["flags"]}),
                "min": low,
                "max": high,
                "sensitive": max(exact_rates) - min(exact_rates) > Fraction(str(pause_threshold)),
                "threshold": pause_threshold,
                "threshold_note": "model choice",
                "note": PAUSE_BAND_NOTE,
            }
    return {level: winrate.sort_results(rows) for level, rows in levels.items()}


def row_key(row):
    return row["speciesId"], row["level"], row["fast_move"], row["charged_move"]


def validate_character_names(names):
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate character names: {', '.join(duplicates)}")


def overall_view(characters, results, *, ranks=None):
    """Equal character means, retaining full contributing records and missing coverage."""
    selected = [c for c in characters if ranks is None or c["rank"] in ranks]
    validate_character_names(c["name"] for c in selected)
    missing = [
        {"character": c["name"], "reason": c.get("reason", "no eligible candidates")}
        for c in selected
        if not results[c["name"]]
    ]
    grouped = {}
    for character in selected:
        for key, row in results[character["name"]].items():
            grouped.setdefault(key, []).append(row)
    rows = []
    for _key, contributions in sorted(grouped.items()):
        first = contributions[0]
        rows.append(
            {
                **{
                    k: first[k]
                    for k in (
                        "speciesId",
                        "species",
                        "form",
                        "level",
                        "ivs",
                        "fast_move",
                        "charged_move",
                        "move_flags",
                    )
                },
                "win_rate": mean(r["win_rate"] for r in contributions),
                **({"types": first["types"]} if "types" in first else {}),
                **(
                    {
                        "mean_rocket_knocked_out": mean(
                            r["mean_rocket_knocked_out"] for r in contributions
                        )
                    }
                    if all("mean_rocket_knocked_out" in r for r in contributions)
                    else {}
                ),
                "mean_player_hp_fraction_left": mean(
                    r["mean_player_hp_fraction_left"] for r in contributions
                ),
                "mean_turns": mean(r["mean_turns"] for r in contributions),
                "characters_with_result": len(contributions),
                "label": "estimate (every number)",
                "ledger_rows": sorted({v for r in contributions for v in r.get("ledger_rows", [])}),
                "interpretations": sorted(
                    {v for r in contributions for v in r.get("interpretations", [])}
                ),
                "evidence": [
                    dict(zip(("row", "grade", "option", "source"), values, strict=True))
                    for values in sorted(
                        {
                            tuple(e[k] for k in ("row", "grade", "option", "source"))
                            for r in contributions
                            for e in r.get("evidence", [])
                        }
                    )
                ],
                # Compact references; full finalist rows and calc_rows live per character.
                "per_character": [
                    {
                        k: r[k]
                        for k in (
                            "character",
                            "rank",
                            "win_rate",
                            "draw_rate",
                            "mean_player_hp_fraction_left",
                            "mean_turns",
                            "grade",
                        )
                        if k in r
                    }
                    for r in contributions
                ],
                "stats_grade": weakest(*(r["stats_grade"] for r in contributions)),
                "rules_grade": "unverified"
                if any(r["rules_grade"] == "unverified" for r in contributions)
                else "estimate",
                "flags": sorted({f for r in contributions for f in r["flags"]}),
                "pool_complete": all(r["pool_complete"] for r in contributions),
            }
        )
    return {
        "coverage": {
            "characters_with_result": len(selected) - len(missing),
            "total": len(selected),
            "missing": missing,
            "text": f"covers {len(selected) - len(missing)} of {len(selected)} characters"
            + ("; missing: " + ", ".join(c["character"] for c in missing) if missing else ""),
        },
        "results": {
            f"{level:g}": winrate.sort_results([r for r in rows if r["level"] == level])
            for level in sorted({r["level"] for r in rows})
        },
    }
