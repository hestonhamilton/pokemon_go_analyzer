"""Pure two-stage counter ranking over the existing offline calculator and simulator."""

from dataclasses import dataclass
from statistics import mean

from . import calc_cli as calc
from .sim import winrate
from .sim.grades import weakest
from .sim.rocket import simulate_rocket

SCREEN_NOTE = (
    "Stage 1 score is the mean of the three slot 1v1 win rates; draws are not wins. "
    "The grid ignores carried-over shields and HP between slots. "
    "Screen numbers are not lineup win rates."
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
        elif "_mega" in name or "mega" in source.get("tags", []):
            reason = "Mega is unsupported by the simulator"
        if reason:
            skipped.append({"speciesId": name, "reason": reason})
            continue
        try:
            pairs = winrate.moveset_ids(source, exclude_elite_legacy=exclude_elite_legacy)
        except ValueError as exc:
            skipped.append({"speciesId": name, "reason": str(exc)})
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
                            "reason": str(exc),
                        }
                    )
                    continue
                candidates.append(candidate)
    return candidates, skipped


def screen_candidate(candidate, pools, *, rank, battle_date, grid=winrate.grid):
    """One member against each slot option; empty slots cannot produce a score."""
    _, groups = grid(candidate.team, pools, rank=rank, battle_date=battle_date)
    slots = {g["slot"]: g["win_rate"] for g in groups}
    rates = [slots.get(i) for i in range(1, 4)]
    return {
        "score": mean(rates) if all(r is not None for r in rates) else None,
        "slot_win_rates": rates,
        "grid_limitation": winrate.GRID_NOTE,
        "note": SCREEN_NOTE,
    }


def screen_candidates(candidates, pools, *, rank, battle_date, grid=winrate.grid):
    """Best moveset for each source species and level, with deterministic ties."""
    best = {}
    for candidate in candidates:
        screen = screen_candidate(candidate, pools, rank=rank, battle_date=battle_date, grid=grid)
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
        row["execution"] = execution
    return row


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
):
    """Run stage 2 only for the top K species per level, before full-result sorting."""
    if k < 1:
        raise ValueError("--k must be positive")
    screened = screen_candidates(candidates, pools, rank=rank, battle_date=battle_date, grid=grid)
    levels = {}
    for candidate, screen in screened:
        rows = levels.setdefault(candidate.key[1], [])
        if len(rows) >= k:
            continue
        row = full_result(
            candidate,
            pools,
            rank=rank,
            battle_date=battle_date,
            battle=battle,
            trial_runner=trial_runner,
        )
        rows.append({**row, **candidate.output(), "screen": screen})
    return {level: winrate.sort_results(rows) for level, rows in levels.items()}


def row_key(row):
    return row["speciesId"], row["level"], row["fast_move"], row["charged_move"]


def overall_view(characters, results, *, ranks=None):
    """Equal character means, retaining full contributing records and missing coverage."""
    selected = [c for c in characters if ranks is None or c["rank"] in ranks]
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
                "mean_player_hp_fraction_left": mean(
                    r["mean_player_hp_fraction_left"] for r in contributions
                ),
                "mean_turns": mean(r["mean_turns"] for r in contributions),
                "characters_with_result": len(contributions),
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
        },
        "results": {
            f"{level:g}": winrate.sort_results([r for r in rows if r["level"] == level])
            for level in sorted({r["level"] for r in rows})
        },
    }
