"""Parse and rank Rocket counter simulation results."""

from dataclasses import dataclass
from math import isfinite

RANK_KEYS = {"overall_rating", "power", "win_ratio", "tdo", "effective_combat_time_ms"}


@dataclass
class CounterResult:
    pokemon_id: str
    fast_move: str
    charged_move: str
    win_ratio: float
    overall_rating: float
    power: float
    tdo: float
    effective_combat_time_ms: float


@dataclass
class CounterSummary:
    pokemon_id: str
    best: CounterResult
    movesets: list[CounterResult]

    def best_for(self, key: str) -> CounterResult:
        """Select a moveset for a ranking key; best remains the overall-rating best."""
        if key not in RANK_KEYS:
            raise ValueError(f"invalid ranking key: {key}")
        if key == "effective_combat_time_ms":
            winners = [move for move in self.movesets if move.win_ratio > 0]
            return (
                min(winners, key=lambda move: move.effective_combat_time_ms)
                if winners
                else self.best
            )
        return max(self.movesets, key=lambda move: getattr(move, key))


@dataclass
class DefenderCounters:
    defender_id: str
    tier: str | None
    defender_cp: int | None
    moveset: tuple[str, str] | None
    counters: list[CounterSummary]


def parse_rocket_response(data: dict, *, moveset="random", tier=None) -> DefenderCounters:
    if not isinstance(data, dict) or not isinstance(data.get("attackers"), list):
        raise ValueError("missing attackers")
    if not data["attackers"] or not isinstance(data["attackers"][0], dict):
        raise ValueError("empty or malformed attackers")
    defender = data["attackers"][0]
    if not defender.get("pokemonId"):
        raise ValueError("missing defender ID")
    if moveset == "random":
        selected = defender.get("randomMove")
        selected_moveset = None
    else:
        if not isinstance(moveset, tuple) or len(moveset) != 2:
            raise ValueError("moveset must be 'random' or a (fast, charged) tuple")
        selected = next(
            (
                m
                for m in (defender.get("byMove") or [])
                if isinstance(m, dict) and (m.get("move1"), m.get("move2")) == moveset
            ),
            None,
        )
        if selected is None:
            raise ValueError(f"defender moveset not found: {moveset}")
        selected_moveset = moveset
    if not isinstance(selected, dict) or not isinstance(selected.get("defenders"), list):
        raise ValueError("missing or malformed defender moveset results")
    counters = []
    for counter in selected["defenders"]:
        if not isinstance(counter, dict) or not isinstance(counter.get("pokemonId"), str):
            continue
        results = []
        moves = counter.get("byMove")
        if not isinstance(moves, list):
            continue
        for move in moves:
            if not isinstance(move, dict) or not all(
                isinstance(move.get(key), str) for key in ("move1", "move2")
            ):
                continue
            result = move.get("result")
            if not isinstance(result, dict):
                continue
            win_ratio = result.get("winRatio", 1.0 if result.get("win", False) else 0.0)
            values = [
                result.get(key) for key in ("overallRating", "power", "tdo", "effectiveCombatTime")
            ] + [win_ratio]
            if not all(isinstance(value, (int, float)) and isfinite(value) for value in values):
                continue
            results.append(
                CounterResult(
                    pokemon_id=counter["pokemonId"],
                    fast_move=move["move1"],
                    charged_move=move["move2"],
                    win_ratio=win_ratio,
                    overall_rating=result["overallRating"],
                    power=result["power"],
                    tdo=result["tdo"],
                    effective_combat_time_ms=result["effectiveCombatTime"],
                )
            )
        if results:
            counters.append(
                CounterSummary(
                    counter["pokemonId"], max(results, key=lambda r: r.overall_rating), results
                )
            )
    return DefenderCounters(
        defender["pokemonId"],
        defender.get("boss", tier),
        defender.get("cp"),
        selected_moveset,
        counters,
    )


def rank(counters: list[CounterSummary], key: str) -> list[CounterSummary]:
    if key not in RANK_KEYS:
        raise ValueError(f"invalid ranking key: {key}")
    if key == "effective_combat_time_ms":

        def time_key(counter):
            move = counter.best_for(key)
            return (
                (0, move.effective_combat_time_ms)
                if move.win_ratio > 0
                else (1, -move.overall_rating)
            )

        return sorted(counters, key=time_key)
    return sorted(
        counters,
        key=lambda counter: getattr(counter.best_for(key), key),
        reverse=True,
    )
