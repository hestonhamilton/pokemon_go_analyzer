"""Parse and rank Rocket counter simulation results."""

from dataclasses import dataclass


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


@dataclass
class DefenderCounters:
    defender_id: str
    tier: str
    defender_cp: int
    moveset: tuple[str, str] | None
    counters: list[CounterSummary]


def parse_rocket_response(data: dict, *, moveset="random") -> DefenderCounters:
    defender = data["attackers"][0]
    if moveset == "random":
        selected = defender["randomMove"]
        selected_moveset = None
    else:
        if not isinstance(moveset, tuple) or len(moveset) != 2:
            raise ValueError("moveset must be 'random' or a (fast, charged) tuple")
        selected = next(
            (m for m in defender["byMove"] if (m["move1"], m["move2"]) == moveset), None
        )
        if selected is None:
            raise ValueError(f"defender moveset not found: {moveset}")
        selected_moveset = moveset
    counters = []
    for counter in selected["defenders"]:
        results = []
        for move in counter["byMove"]:
            result = move["result"]
            results.append(
                CounterResult(
                    pokemon_id=counter["pokemonId"],
                    fast_move=move["move1"],
                    charged_move=move["move2"],
                    win_ratio=result.get("winRatio", 1.0 if result.get("win", False) else 0.0),
                    overall_rating=result["overallRating"],
                    power=result["power"],
                    tdo=result["tdo"],
                    effective_combat_time_ms=result["effectiveCombatTime"],
                )
            )
        counters.append(
            CounterSummary(
                counter["pokemonId"], max(results, key=lambda r: r.overall_rating), results
            )
        )
    return DefenderCounters(
        defender["pokemonId"], defender["boss"], defender["cp"], selected_moveset, counters
    )


def rank(counters: list[CounterSummary], key: str) -> list[CounterSummary]:
    if key not in {"overall_rating", "power", "win_ratio", "tdo", "effective_combat_time_ms"}:
        raise ValueError(f"invalid ranking key: {key}")
    return sorted(
        counters,
        key=lambda counter: getattr(counter.best, key),
        reverse=key != "effective_combat_time_ms",
    )
