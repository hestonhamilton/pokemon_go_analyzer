"""Pure, uniformly enumerated Rocket estimates. No sources or acceptance targets."""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from itertools import product

from .battle import Combatant
from .rocket import DEFAULT_ROCKET_RULES, rules_dict, simulate_rocket

GRID_NOTE = "ignores carried-over shields and HP between slots"
SORT_NOTE = "win_rate descending, mean player HP fraction left descending, mean turns ascending"


@dataclass(frozen=True)
class Option:
    species: str
    combatant: Combatant


def moveset_ids(species, *, exclude_elite_legacy=False):
    """All fast × single charged pairs. Empty species pools are explicit errors."""
    excluded = (
        set(species.get("eliteMoves", []) + species.get("legacyMoves", []))
        if exclude_elite_legacy
        else set()
    )
    fast = [m for m in species["fastMoves"] if m not in excluded]
    charged = [m for m in species["chargedMoves"] if m not in excluded]
    if not fast or not charged:
        reason = " after --exclude-elite-legacy" if exclude_elite_legacy else ""
        raise ValueError(f"empty fast or charged move pool{reason}")
    return tuple(product(fast, charged))


def lineups(pools):
    if len(pools) != 3 or any(not pool for pool in pools):
        raise ValueError("a full lineup needs three nonempty slot pools")
    return product(*pools)


def player_combatant(attacker, fast, charged):
    """Exactly calculator.calculate_matchup's player stats and shadow handling."""
    from .stats import player_stats

    ps = player_stats(
        attacker["baseStats"],
        attacker["ivs"],
        attacker["level"],
        form=attacker.get("form", "normal"),
        dex=attacker.get("dex"),
    )
    return Combatant(
        ps.attack,
        ps.defence,
        ps.hp,
        tuple(attacker["types"]),
        fast,
        tuple(charged),
        shadow=ps.form == "shadow",
    )


def battle_summary(result, team):
    """Credit each Rocket faint to the active player, even on a double KO turn."""
    if result.ended_by == "observation_limit":
        raise ValueError("observation_limit: incomplete battle cannot enter estimates")
    credited = [0] * len(team)
    fainted = set()
    for turn in result.timeline:
        player, rocket = turn.active_slots
        if turn.core.hp[1] == 0 and rocket not in fainted:
            credited[player - 1] += 1
            fainted.add(rocket)
    return {
        "winner": result.winner,
        "ended_by": result.ended_by,
        "turns": result.turns_elapsed,
        "hp_fraction": sum(h / p.hp for h, p in zip(result.hp[0], team, strict=True)) / len(team),
        "credited": credited,
        "fainted": sorted(fainted),
        "battle_date": result.battle_date,
        "era": result.era,
        "rules": rules_dict(result.rules),
        "ledger_rows": result.ledger_rows,
        "flags": result.flags,
        "evidence": [asdict(e) for e in result.evidence],
        "interpretations": result.interpretations,
    }


class _Metadata:
    def __init__(self):
        self.rows, self.flags, self.evidence, self.interpretations = set(), set(), set(), set()
        self.context = None

    def add(self, summary):
        context = {k: summary[k] for k in ("battle_date", "era", "rules")}
        if self.context is not None and context != self.context:
            raise ValueError("battles must have identical dates, eras and rules")
        self.context = context
        self.rows.update(summary["ledger_rows"])
        self.flags.update(summary["flags"])
        self.evidence.update(
            tuple(e[k] for k in ("row", "grade", "option", "source")) for e in summary["evidence"]
        )
        self.interpretations.update(summary["interpretations"])

    def output(self):
        return {
            **(self.context or {}),
            "label": "estimate (every number)",
            "ledger_rows": sorted(self.rows),
            "flags": sorted(self.flags),
            "evidence": [
                dict(zip(("row", "grade", "option", "source"), e, strict=True))
                for e in sorted(self.evidence)
            ],
            "interpretations": sorted(self.interpretations),
            "rules_grade": "unverified" if "unverified" in self.flags else "estimate",
        }


def trials(team, pools, *, rank, battle_date, rules=DEFAULT_ROCKET_RULES, battle=simulate_rocket):
    """Stream serial trials; inject a battle function for independent arithmetic checks."""
    for lineup in lineups(pools):
        result = battle(
            team,
            tuple(o.combatant for o in lineup),
            rank=rank,
            battle_date=battle_date,
            rules=rules,
        )
        yield lineup, battle_summary(result, team)


def aggregate(team, trials):
    """Uniform means over every enumerated lineup, with no outcome-dependent weights."""
    count = wins = losses = draws = lead = knocked = turns = 0
    hp = 0.0
    ends = Counter()
    distributions = [Counter() for _ in team]
    slots = Counter()
    species_counts, species_wins = Counter(), Counter()
    metadata = _Metadata()
    for lineup, result in trials:
        metadata.add(result)
        count += 1
        won = result["winner"] == "player"
        wins += won
        losses += result["winner"] == "rocket"
        draws += result["winner"] is None
        outcome = "wins" if won else "losses" if result["winner"] == "rocket" else "draws"
        ends[result["ended_by"], outcome] += 1
        knocked += len(result["fainted"])
        lead += len(result["fainted"]) == 3 and result["credited"][0] == 3
        turns += result["turns"]
        hp += result["hp_fraction"]
        for i, credit in enumerate(result["credited"]):
            distributions[i][credit] += 1
        slots.update(result["fainted"])
        for i, option in enumerate(lineup, 1):
            species_counts[i, option.species] += 1
            species_wins[i, option.species] += won
    if not count:
        raise ValueError("no complete lineups to aggregate")
    return {
        **metadata.output(),
        "lineups": count,
        "battles": count,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": wins / count,
        "draw_rate": draws / count,
        **{
            f"{ending}_{outcome}": ends[ending, outcome]
            for ending in ("timeout", "knockout")
            for outcome in ("wins", "losses", "draws")
        },
        "mean_rocket_knocked_out": knocked / count,
        "lead_sweep_probability": lead / count,
        "slots_swept": [
            {
                "player_slot": i,
                "mean": sum(k * n for k, n in dist.items()) / count,
                "shares": {str(k): dist[k] / count for k in range(4)},
            }
            for i, dist in enumerate(distributions, 1)
        ],
        "mean_player_hp_fraction_left": hp / count,
        "mean_turns": turns / count,
        "per_slot": [
            {
                "slot": i,
                "knockout_share": slots[i] / count,
                "species": [
                    {
                        "species": name,
                        "battles": n,
                        "conditional_win_rate": species_wins[slot, name] / n,
                    }
                    for (slot, name), n in sorted(species_counts.items())
                    if slot == i
                ],
            }
            for i in range(1, 4)
        ],
    }


def estimate(team, pools, *, rank, battle_date, rules=DEFAULT_ROCKET_RULES, battle=simulate_rocket):
    return aggregate(
        team, trials(team, pools, rank=rank, battle_date=battle_date, rules=rules, battle=battle)
    )


def sort_results(rows):
    return sorted(
        rows, key=lambda r: (-r["win_rate"], -r["mean_player_hp_fraction_left"], r["mean_turns"])
    )


def grid(
    team, pools, *, rank, battle_date, rules=DEFAULT_ROCKET_RULES, slot=None, battle=simulate_rocket
):
    rows, groups = [], defaultdict(list)
    for i, member in enumerate(team, 1):
        for j, pool in enumerate(pools, 1):
            if slot is not None and slot != j:
                continue
            for option in pool:
                result = battle(
                    (member,), (option.combatant,), rank=rank, battle_date=battle_date, rules=rules
                )
                summary = battle_summary(result, (member,))
                metadata = _Metadata()
                metadata.add(summary)
                row = {
                    **metadata.output(),
                    "grid_limitation": GRID_NOTE,
                    "player_slot": i,
                    "slot": j,
                    "species": option.species,
                    "rocket_fast_move": option.combatant.fast.id,
                    "rocket_charged_move": option.combatant.charged[0].id,
                    "winner": result.winner,
                    "ended_by": result.ended_by,
                    "turns": result.turns_elapsed,
                    "player_hp_fraction_left": summary["hp_fraction"],
                    "rocket_hp_fraction_left": result.hp[1][0] / option.combatant.hp,
                    "lineups": 1,
                    "battles": 1,
                }
                rows.append(row)
                groups[i, j].append((row, summary))
    aggregates = []
    for (i, j), values in groups.items():
        metadata = _Metadata()
        for _, summary in values:
            metadata.add(summary)
        n = len(values)
        wins = sum(r["winner"] == "player" for r, _ in values)
        draws = sum(r["winner"] is None for r, _ in values)
        aggregates.append(
            {
                **metadata.output(),
                "grid_limitation": GRID_NOTE,
                "player_slot": i,
                "slot": j,
                "lineups": n,
                "battles": n,
                "wins": wins,
                "losses": n - wins - draws,
                "draws": draws,
                "win_rate": wins / n,
                "draw_rate": draws / n,
            }
        )
    return rows, aggregates
