"""Dependency grades. The data file defines the grade vocabulary and strength order."""

import json
from importlib.resources import files

# The old tables the runtime acceptance gate checks (validation.OLD_TABLES).
FIXTURE_TABLES = frozenset({"venonic-2023", "fugerappi-2023", "flyfunner-old-50-2025"})
GRADES = json.loads(files(__package__).joinpath("data", "grades.json").read_text())
ORDER = [g["id"] for g in GRADES]

# Dependencies describe conditional arithmetic, not the likelihood of a Rocket
# carrying the selected move. That separate claim is moveset_pool (always model).
ROCKET_COLUMNS = {
    "fast_damage",
    "fast_damage_per_turn",
    "fast_hits_to_ko",
    "rocket_fast_damage",
    "rocket_fast_damage_per_turn",
    "ko_on_incoming_hit",
    "rocket_attack",
    "rocket_defence",
    "rocket_hp",
    "rank",
    "rank_multiplier",
    "rocket_cpm",
    "rcpm_table",
    "trainer_level",
}
MODEL_COLUMNS = {
    "fast_turns_to_ko",
    "turns_survived",
    "fast_moves_to_energy",
    "moveset_pool",
    "rocket_fast_move",
    "rocket_charged_move",
    "character",
    "slot",
}
PARITY_COLUMNS = {"charged_damage", "energy_cost", "fast_move", "charged_move"}
INPUT_COLUMNS = {"attacker", "defender", "level", "ivs", "form"}
PLAYER_COLUMNS = {"attacker_attack", "attacker_defence", "attacker_hp"}


COLUMN_MEANINGS = {
    "attacker": "Given attacker species",
    "level": "Given attacker level",
    "ivs": "Given attacker attack/defence/HP IVs",
    "form": "Given normal, shadow or purified form; purification IV gain is already included",
    "defender": "Rocket species, conditional on this encounter",
    "fast_move": "Attacker's selected Trainer Battle fast move",
    "rocket_fast_move": "Hypothetical Rocket fast move; availability is unverified",
    "fast_damage": "Attacker damage per fast hit, conditional on the matchup",
    "fast_damage_per_turn": "Nominal attacker damage / (cooldown / 500 ms)",
    "fast_hits_to_ko": "Fast-only ceil(Rocket battle HP / attacker fast damage)",
    "fast_turns_to_ko": "Fast hits × turns; ignores charged attacks, pauses and switching",
    "charged": "Chosen charged moves: full unshielded damage, energy cost and fast moves from zero",
    "rocket_fast_damage": "Rocket damage per fast hit, conditional on carrying the named move",
    "rocket_fast_damage_per_turn": "Nominal Rocket damage / (cooldown / 500 ms)",
    "ko_on_incoming_hit": "Fast-only ceil(attacker HP / incoming damage); KO occurs on this hit",
    "turns_survived": "Incoming KO hit × turns; ignores charged attacks, pauses and switching",
    "rocket_charged": "Hypothetical charged pool: full unshielded parity damage, no timing",
    "attacker_attack": "Attacker attack before shadow modifier (formula path checked indirectly)",
    "attacker_defence": "Attacker defence before shadow modifier (formula path checked indirectly)",
    "attacker_hp": "Floored attacker battle HP; F1 checks this formula path directly",
    "rocket_attack": "Rocket attack before shadow modifier",
    "rocket_defence": "Rocket defence before shadow modifier",
    "rocket_hp": "Floored Rocket battle HP",
    "rocket_cp": "Display CP using unfloored stamina; checked by CP readings",
    "rank": "Rocket rank; leaders and Giovanni have no hit-count target",
    "rank_multiplier": "S1 rank scaling: grunt 1, leader 1.05, Giovanni 1.15",
    "rcpm_table": "Selected published Rocket CPM point table",
    "rocket_cpm": "Published Rocket CPM at the given trainer level; no interpolation",
    "trainer_level": "Given trainer level used for Rocket scaling",
    "character": "Event-info character; move availability remains unverified",
    "slot": "Encounter slot; explicit defender slots are given labels",
    "moveset_pool": "All PvPoke species moves with elite/legacy flags; no Rocket moveset source",
    "row_grade": "Weakest grade among this row's cells",
}


def weakest(*grades):
    return max(grades, key=ORDER.index)


def column_grade(column, rank, table):
    """Derive strength from dependencies; never assign a grade to a particular row."""
    # Only the old tables the acceptance targets check can be fixture-exact; any
    # other table (dec-2025, or one added later) is backed by CP readings at most.
    fixture = rank == "grunt" and table in FIXTURE_TABLES
    rocket = "fixture-exact" if fixture else "cp-only"
    if column in MODEL_COLUMNS:
        return weakest(rocket, "model")
    if column in {"charged_damage", "fast_damage_per_turn", "rocket_fast_damage_per_turn"}:
        return weakest(rocket, "parity-only")
    if column == "rocket_cp":
        return weakest(rocket, "cp-only")
    if column in ROCKET_COLUMNS:
        return rocket
    if column in PARITY_COLUMNS:
        return "parity-only"
    if column in INPUT_COLUMNS | PLAYER_COLUMNS:
        # Given inputs; stats are the same formula path exercised by F1/F4/F5.
        return "fixture-exact"
    raise ValueError(f"no grade dependency rule for {column}")


def cell(value, column, rank, table):
    return {"value": value, "grade": column_grade(column, rank, table)}


def grade_row(row):
    rank, table = row["rank"], row["rcpm_table"]
    result = {}
    for key, value in row.items():
        if key in ("charged", "rocket_charged"):
            nested = []
            for move in value:
                nested.append(
                    {
                        k: cell(
                            v,
                            "charged_damage"
                            if k == "damage"
                            else "rocket_charged_move"
                            if k == "move" and key == "rocket_charged"
                            else "charged_move"
                            if k == "move"
                            else k,
                            rank,
                            table,
                        )
                        for k, v in move.items()
                    }
                )
            grades = [c["grade"] for m in nested for c in m.values()]
            result[key] = {"value": nested, "grade": weakest(*grades) if grades else "model"}
        else:
            result[key] = cell(value, key, rank, table)
    result["row_grade"] = {
        "value": weakest(*(c["grade"] for c in result.values())),
        "grade": weakest(*(c["grade"] for c in result.values())),
    }
    return result
