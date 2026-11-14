"""Offline ordinary move damage, ported from PvPoke.

PvPoke is MIT licensed, copyright (c) 2019 pvpoke. The full notice ships as
data/PVPoke-LICENSE next to the ported type chart (data/types.json).

All references are pinned to 426e5e9f39d3a027849698fb2f5edd9df6056cbf:
https://github.com/pvpoke/pvpoke/tree/426e5e9f39d3a027849698fb2f5edd9df6056cbf
DamageCalculator.js refers to src/js/battle/DamageCalculator.js below.
Stats are unmodified totals from stats.py; callers explicitly identify shadow combatants.
Move power/type are supplied by the caller; no current or historical move lookup
is performed here. Form changes and percentMaxHP moves are outside this API.
"""

import json
import math
import numbers
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from .stats import SHADOW_ATK, SHADOW_DEF

# DamageCalculator.js lines 3–10. These are JS Number literals (binary64
# arithmetic), not instructions to round intermediate operations to float32.
BONUS = 1.2999999523162841796875
SUPER_EFFECTIVE = 1.60000002384185791015625
RESISTED = 0.625
DOUBLE_RESISTED = 0.390625
STAB = 1.2000000476837158203125
MEGA_BONUS = (1, 1.10000002384185791015625, 1.2000000476837158203125, BONUS)


@cache
def _types() -> dict:
    return json.loads(files(__package__).joinpath("data", "types.json").read_text())["types"]


def _type(name: str) -> str:
    name = name.lower()
    if name != "none" and name not in _types():
        raise ValueError(f"unknown type: {name}")
    return name


def _move_type(name: str) -> str:
    # "none" is PvPoke's empty second slot for a Pokemon, never a move's type.
    # Accepting it would also give a typeless move STAB from that empty slot.
    name = _type(name)
    if name == "none":
        raise ValueError("a move must have a real type, not none")
    return name


def _type_list(types: Sequence[str], role: str) -> tuple[str, ...]:
    if isinstance(types, str):
        raise ValueError(f"{role} types must be a list of type names, not one string")
    names = tuple(_type(t) for t in types)
    if not 1 <= len(names) <= 2 or all(n == "none" for n in names):
        raise ValueError(f"{role} needs one or two real types")
    return names


def effectiveness(move_type: str, defender_types: Sequence[str]) -> float:
    """DamageCalculator.js lines 140–158; multiply once per defensive type."""
    move_type = _move_type(move_type)
    value = 1.0
    for name in _type_list(defender_types, "defender"):
        name = _type(name)
        if name == "none":
            continue
        traits = _types()[name]
        if move_type in traits["weaknesses"]:
            value *= SUPER_EFFECTIVE
        elif move_type in traits["resistances"]:
            value *= RESISTED
        elif move_type in traits["immunities"]:
            value *= DOUBLE_RESISTED
    return value


def stage_multiplier(stage: int) -> float:
    """Pokemon.js lines 2113–2130; gamemaster.json lines 7–8: max/divisor 4."""
    if isinstance(stage, bool) or not isinstance(stage, int) or not -4 <= stage <= 4:
        raise ValueError("stat stage must be an integer from -4 to +4")
    return (4 + stage) / 4 if stage > 0 else 4 / (4 - stage)


@dataclass(frozen=True)
class DamageResult:
    raw: float  # Before floor/+1 and before any shield override.
    damage: int


def calculate_damage(
    power: float,
    attack: float,
    defence: float,
    move_type: str,
    attacker_types: Sequence[str],
    defender_types: Sequence[str],
    *,
    attacker_shadow: bool,
    defender_shadow: bool,
    attack_stage: int = 0,
    defence_stage: int = 0,
    charged: bool = False,
    shielded: bool = False,
    attacker_mega: bool = False,
    is_mega_move: bool = False,
    mega_level: int = 3,
) -> DamageResult:
    """Port DamageCalculator.damage's ordinary branch (line 68), charge=1.

    Shadow and stage ordering: Pokemon.js lines 2091–2108, 2250–2255.
    STAB: Pokemon.js lines 701–707. Shield override: Battle.js 1194–1200.
    Mega flag AND move metadata gate the bonus (DamageCalculator.js 40–41).
    The caller supplies a shield decision; this function defines no shield policy.
    Both shadow flags are required, with no default: Rocket Pokemon are shadow
    (ledger g), and a caller that forgot the flag would be about 20% off.
    """
    if not math.isfinite(power) or power < 0:
        raise ValueError("power must be finite and nonnegative")
    if any(not math.isfinite(x) or x <= 0 for x in (attack, defence)):
        raise ValueError("attack and defence must be finite and positive")
    if shielded and not charged:
        raise ValueError("only charged attacks can be shielded")
    if isinstance(mega_level, bool) or not isinstance(mega_level, int) or not 1 <= mega_level <= 4:
        raise ValueError("mega level must be 1–4")
    move_type = _move_type(move_type)
    stab = STAB if move_type in _type_list(attacker_types, "attacker") else 1
    attack_multiplier = stage_multiplier(attack_stage)
    defence_multiplier = stage_multiplier(defence_stage)
    if attacker_shadow:
        attack_multiplier *= SHADOW_ATK
    if defender_shadow:
        defence_multiplier *= SHADOW_DEF
    attack_stat = attack * attack_multiplier
    defence_stat = defence * defence_multiplier
    mega_multiplier = MEGA_BONUS[mega_level - 1] if attacker_mega and is_mega_move else 1
    # Preserve the exact left-to-right operation order of damage(), not
    # damageByStats() (line 104), which orders Mega before effectiveness.
    raw = (
        power
        * stab
        * (attack_stat / defence_stat)
        * effectiveness(move_type, defender_types)
        * 1  # chargeMultiplier: fully charged fast/charged attacks.
        * mega_multiplier
        * 0.5
        * BONUS
    )
    return DamageResult(raw=raw, damage=1 if shielded else math.floor(raw) + 1)


def hits_to_ko(damage: int, hp: int) -> int:
    """ceil(hp / damage), using exact integer arithmetic."""
    # numbers.Integral also admits numpy integers; bool is still refused.
    if any(
        isinstance(x, bool) or not isinstance(x, numbers.Integral) or x <= 0 for x in (damage, hp)
    ):
        raise ValueError("damage and HP must be positive integers")
    return int((hp + damage - 1) // damage)
