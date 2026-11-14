"""Dependency grades. The data file defines the grade vocabulary and strength order.

A cell never claims more than its weakest input. fixture-exact needs all of:
- the acceptance gate passed on this run (its own "validated" result, passed in);
- a grunt (no leader or Giovanni target exists);
- for Rocket stats, a gate table at a trainer level where passing targets
  checked that same quantity (HP, attack or defence); for the shared scaling
  inputs (rCPM, rank, table, level), a level where every quantity was checked;
- for damage, every move it uses has today's stats equal to a dated snapshot
  the passing targets used.
Otherwise: Rocket stats fall to cp-only (CP readings back the formula and
tables); damage and player stats fall to parity-only (PvPoke's own code) when
the gate failed or a move differs; leader and Giovanni cells are cp-only at best.
"""

import json
from dataclasses import dataclass
from importlib.resources import files

from .validation import GATE_TABLES, QUANTITIES

GRADES = json.loads(files(__package__).joinpath("data", "grades.json").read_text())
ORDER = [g["id"] for g in GRADES]
MOVE_FIELDS = ("type", "power", "energy_gain", "energy", "turns")

MODEL_COLUMNS = {
    "fast_turns_to_ko",
    "turns_survived",
    "fast_moves_to_energy",
    "moveset_pool",
    "rocket_fast_move",
    "rocket_charged_move",
    "character",
    "slot",
    "defender",
}
# Rocket stats a target can check one by one (see validation.KIND_QUANTITIES).
ROCKET_QUANTITY_COLUMNS = {"rocket_attack", "rocket_defence", "rocket_hp"}
# Scaling inputs shared by every Rocket stat. A level where only one quantity
# was checked (TL41: one floored HP reading) bounds rCPM only loosely, so these
# need every quantity checked at that level.
ROCKET_STAT_COLUMNS = {
    "rank",
    "rank_multiplier",
    "rocket_cpm",
    "rcpm_table",
    "trainer_level",
}
PLAYER_COLUMNS = {
    "attacker",
    "level",
    "ivs",
    "form",
    "attacker_attack",
    "attacker_defence",
    "attacker_hp",
}
PARITY_COLUMNS = {"energy_cost", "charged_move"}


def weakest(*grades):
    return max(grades, key=ORDER.index)


@dataclass(frozen=True)
class GradeContext:
    validated: bool
    rank: str
    table: str
    trainer_level: int
    # Per Rocket quantity: {"rocket_hp": frozenset({(table, level), ...}), ...}.
    levels: tuple = ()
    fast_move_covered: bool = False
    rocket_fast_move_covered: bool = False

    @classmethod
    def for_row(cls, row, coverage, moves=None, *, validated):
        """validated: the gate's own result. coverage: validation["coverage"].

        moves: {"fast": Move, "rocket_fast": Move}. Any coverage entry that is not
        a known quantity holding (table, level) pairs is ignored (fails closed).
        """
        validated = validated is True
        coverage = coverage if isinstance(coverage, dict) else {}
        raw = coverage.get("levels")
        raw = raw if isinstance(raw, dict) else {}
        by_quantity = {}
        for quantity in QUANTITIES:
            covered = raw.get(quantity)
            pairs = covered if isinstance(covered, list) else []
            by_quantity[quantity] = frozenset(
                tuple(pair)
                for pair in pairs
                if isinstance(pair, list | tuple)
                and len(pair) == 2
                and isinstance(pair[0], str)
                and isinstance(pair[1], int)
                and not isinstance(pair[1], bool)
            )
        levels = tuple(sorted(by_quantity.items()))
        moves_list = coverage.get("moves")
        moves_list = moves_list if isinstance(moves_list, list) else []
        snapshots = {
            (m["move"], *(m[k] for k in MOVE_FIELDS))
            for m in moves_list
            if isinstance(m, dict) and all(k in m for k in ("move", *MOVE_FIELDS))
        }

        def covered(move):
            if move is None or not validated:
                return False
            return (move.id, *(getattr(move, k) for k in MOVE_FIELDS)) in snapshots

        moves = moves or {}
        return cls(
            validated=validated,
            rank=row["rank"],
            table=row["rcpm_table"],
            trainer_level=row["trainer_level"],
            levels=levels,
            fast_move_covered=covered(moves.get("fast")),
            rocket_fast_move_covered=covered(moves.get("rocket_fast")),
        )

    @property
    def grunt_checked(self):
        return self.validated and self.rank == "grunt"

    def rocket(self, *quantities):
        """quantities: the Rocket stats a cell uses; none means all (scaling inputs)."""
        levels = dict(self.levels)
        key = (self.table, self.trainer_level)
        level_ok = all(key in levels.get(q, ()) for q in quantities or QUANTITIES)
        exact = self.grunt_checked and self.table in GATE_TABLES and level_ok
        return "fixture-exact" if exact else "cp-only"

    def player(self):
        if not self.validated:
            return "parity-only"  # PvPoke's CPM table and stat formula, unchecked here.
        return "fixture-exact" if self.rank == "grunt" else "cp-only"

    def damage(self, move_covered, *quantities):
        base = weakest(self.player(), self.rocket(*quantities))
        return base if move_covered else weakest(base, "parity-only")


def column_grade(column, ctx):
    """Derive strength from dependencies; never assign a grade to a particular row."""
    if column in MODEL_COLUMNS:
        return "model"
    if column in ROCKET_QUANTITY_COLUMNS:
        return ctx.rocket(column)
    if column in ROCKET_STAT_COLUMNS:
        return ctx.rocket()
    if column == "rocket_cp":
        return weakest(ctx.rocket(), "cp-only")
    if column in PLAYER_COLUMNS:
        return ctx.player()
    if column == "fast_move":
        # No leader or Giovanni target used any move: leader rows never earn it.
        return "fixture-exact" if ctx.fast_move_covered and ctx.grunt_checked else "parity-only"
    if column == "fast_damage":
        return ctx.damage(ctx.fast_move_covered, "rocket_defence")
    if column == "fast_hits_to_ko":
        return ctx.damage(ctx.fast_move_covered, "rocket_defence", "rocket_hp")
    if column in ("rocket_fast_damage", "ko_on_incoming_hit"):
        return ctx.damage(ctx.rocket_fast_move_covered, "rocket_attack")
    if column == "fast_damage_per_turn":
        return weakest(ctx.damage(ctx.fast_move_covered, "rocket_defence"), "parity-only")
    if column == "rocket_fast_damage_per_turn":
        return weakest(ctx.damage(ctx.rocket_fast_move_covered, "rocket_attack"), "parity-only")
    if column == "charged_damage":
        return weakest(ctx.damage(False), "parity-only")
    if column in PARITY_COLUMNS:
        return "parity-only"
    raise ValueError(f"no grade dependency rule for {column}")


COLUMN_MEANINGS = {
    "attacker": "Given attacker species",
    "level": "Given attacker level",
    "ivs": "Given attacker attack/defence/HP IVs",
    "form": "Given normal, shadow or purified form; purification IV gain is already included",
    "defender": "Rocket species from the lineup source or --defender; no fixture checks the lineup",
    "fast_move": (
        "Attacker's fast move; fixture-exact only if today's stats equal a target's snapshot"
    ),
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


def cell(value, column, ctx):
    return {"value": value, "grade": column_grade(column, ctx)}


def grade_row(row, validation, moves=None):
    """validation: run_acceptance()'s result; its "validated" decides, not coverage."""
    ctx = GradeContext.for_row(
        row, validation.get("coverage"), moves, validated=validation.get("validated")
    )
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
                            ctx,
                        )
                        for k, v in move.items()
                    }
                )
            grades = [c["grade"] for m in nested for c in m.values()]
            result[key] = {"value": nested, "grade": weakest(*grades) if grades else "model"}
        else:
            result[key] = cell(value, key, ctx)
    result["row_grade"] = {
        "value": weakest(*(c["grade"] for c in result.values())),
        "grade": weakest(*(c["grade"] for c in result.values())),
    }
    return result
