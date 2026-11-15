"""Pure two-stage counter ranking over the existing offline calculator and simulator."""

from collections import Counter
from dataclasses import dataclass
from functools import partial
from statistics import mean

from . import calc_cli as calc
from .sim import winrate
from .sim.grades import weakest
from .sim.rocket import simulate_rocket

SCREEN_NOTE = (
    "Stage 1 score is the mean of the three slot 1v1 win rates; draws are not wins. "
    "The grid ignores carried-over shields and HP between slots. "
    "Screen numbers are not lineup win rates."
    " Ties at the K cut break by species id alphabetically."
)
WEIGHTING_NOTE = (
    "Equal weight per character is a model choice; no encounter-rate source exists. "
    "Characters without a full result are excluded, never counted as zero."
)
UNAVAILABLE = "not calculated: at least one slot has no resolved options"
IVS = {"atk": 15, "def": 15, "hp": 15}


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
        "slot_win_rates": rates,
        "slot_aggregates": groups,
        "grid_limitation": winrate.GRID_NOTE,
        "note": SCREEN_NOTE,
    }


def screen_candidates(
    candidates,
    pools,
    *,
    rank,
    battle_date,
    grid=winrate.grid,
    stats_grade=None,
    pool_complete=True,
    mapper=map,
):
    """Best moveset for each source species and level, with deterministic ties."""
    candidates = list(candidates)
    best = {}
    run = partial(
        screen_candidate,
        pools=pools,
        rank=rank,
        battle_date=battle_date,
        grid=grid,
        stats_grade=stats_grade if stats_grade is not None else "model",
        pool_complete=pool_complete,
    )
    for candidate, screen in zip(candidates, mapper(run, candidates), strict=True):
        if screen["score"] is None:
            continue
        order = (-screen["score"], *candidate.key)
        key = candidate.species_id, candidate.key[1]
        if key not in best or order < best[key][0]:
            best[key] = order, candidate, screen
    return [(c, s) for _, c, s in sorted(best.values(), key=lambda entry: entry[0])]


def full_result(candidate, pools, *, rank, battle_date, battle=simulate_rocket, trial_runner=None):
    """The same lineup enumeration and aggregate as full sim; inject trials or battles."""
    team = candidate.team
    execution = {}
    if trial_runner is None:
        trials = winrate.trials(team, pools, rank=rank, battle_date=battle_date, battle=battle)
    else:
        trials = trial_runner(team, pools, rank=rank, battle_date=battle_date, execution=execution)
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
    battle=simulate_rocket,
    trial_runner=None,
    stats_grade=None,
    pool_complete=True,
    mapper=map,
):
    """Run stage 2 only for the top K species per level, before full-result sorting."""
    if k < 1:
        raise ValueError("--k must be positive")
    screened = screen_candidates(
        candidates,
        pools,
        rank=rank,
        battle_date=battle_date,
        grid=grid,
        stats_grade=stats_grade,
        pool_complete=pool_complete,
        mapper=mapper,
    )
    counts = {}
    finalists = []
    for candidate, screen in screened:
        level = candidate.key[1]
        if counts.get(level, 0) >= k:
            continue
        counts[level] = counts.get(level, 0) + 1
        finalists.append((candidate, screen))
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
    for (candidate, screen), row in zip(finalists, rows, strict=True):
        levels[candidate.key[1]].append({**row, **candidate.output(), "screen": screen})
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
