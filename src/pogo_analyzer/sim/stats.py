"""Pure stat formulas. No damage, networking, IV purification, or table extrapolation.

Base stats and IVs are mappings with keys ``atk``, ``def``, ``hp``. CP inputs
are already scaled totals, including *unfloored* stamina, not battle HP.
Tables must be selected explicitly; their provenance is in data/rcpm.json.

PvPoke references use commit 426e5e9f39d3a027849698fb2f5edd9df6056cbf (MIT).
"""

import json
import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from types import MappingProxyType

# Literal JavaScript constants, not additional stat multipliers. damage.py applies them.
# https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/DamageCalculator.js#L8-L9
# 0.83333331 is the published decimal literal; do not replace it with exact 5/6
# or silently cast either constant to float32 here.
SHADOW_ATK = 1.2
SHADOW_DEF = 0.83333331
RANKS = MappingProxyType({"grunt": 1.0, "leader": 1.05, "giovanni": 1.15})


@dataclass(frozen=True)
class PlayerStats:
    attack: float
    defence: float
    hp: int
    hp_exact: float
    form: str


@dataclass(frozen=True)
class RocketStats:
    attack: float
    defence: float
    hp: int
    hp_exact: float
    cp: int
    rank: str
    table: str


@cache
def _data(filename: str) -> dict:
    return json.loads(files(__package__).joinpath("data", filename).read_text(encoding="utf-8"))


def player_cpm(level: float) -> float:
    """PvPoke's verbatim CPM table, levels 1–55 inclusive, in half levels."""
    if (
        isinstance(level, bool)
        or not isinstance(level, (int, float))
        or not math.isfinite(level)
        or not 1 <= level <= 55
        or level * 2 != int(level * 2)
    ):
        raise ValueError("player level must be 1–55 in half-level steps")
    return _data("player_cpm.json")["values"][int((level - 1) * 2)]


def _stats(values: Mapping[str, int], *, ivs: bool = False) -> None:
    # Extra keys are ignored, so PvPoke baseStats mappings pass as they are.
    for key in ("atk", "def", "hp"):
        if key not in values:
            raise ValueError(f"missing {'IV' if ivs else 'base stat'} {key}")
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < (0 if ivs else 1):
            raise ValueError(f"{key} must be a {'nonnegative' if ivs else 'positive'} integer")
        if ivs and value > 15:
            raise ValueError(f"{key} IV must be 0–15")


def player_stats(
    base: Mapping[str, int],
    ivs: Mapping[str, int],
    level: float,
    *,
    form: str = "normal",
    dex: int | None = None,
) -> PlayerStats:
    """Unrounded attack/defence, floored battle HP; shadow/purified retain IV stats.

    PvPoke Pokemon.js lines 380–382 at the pinned commit implements these stats.
    Lines 384–388 set Shedinja (dex 292) to 10 HP; pass ``dex`` to apply that.
    Form is metadata only. Purified IVs must already include any purification gain.
    """
    _stats(base)
    _stats(ivs, ivs=True)
    if form not in ("normal", "shadow", "purified"):
        raise ValueError("form must be normal, shadow, or purified")
    cpm = player_cpm(level)
    hp_exact = (base["hp"] + ivs["hp"]) * cpm
    return PlayerStats(
        attack=(base["atk"] + ivs["atk"]) * cpm,
        defence=(base["def"] + ivs["def"]) * cpm,
        hp=10 if dex == 292 else max(10, math.floor(hp_exact)),
        hp_exact=hp_exact,
        form=form,
    )


def _cp(attack_total: float, defence_total: float, hp_total: float) -> int:
    return math.floor(math.sqrt(hp_total) * attack_total * math.sqrt(defence_total) * 0.1)


def cp(attack_total: float, defence_total: float, hp_total: float) -> int:
    """Standard CP, minimum 10. Inputs include CPM, but stamina is not floored.

    Formula: https://www.reddit.com/r/TheSilphRoad/comments/122pfk8/
    Equivalent player formula: pinned PvPoke Pokemon.js line 426.
    Minimum: pinned PvPoke Pokemon.js lines 400–401.
    """
    if any(not math.isfinite(x) or x < 0 for x in (attack_total, defence_total, hp_total)):
        raise ValueError("CP inputs must be finite and nonnegative")
    return max(10, _cp(attack_total, defence_total, hp_total))


def rcpm(trainer_level: int, table: str) -> float:
    """Look up a published value. No interpolation, extrapolation, or fallback.

    Only dec-2025 prescribes a float32 cast. Older tables retain their published
    decimals (including the lower-level table's explicitly estimated column).
    Missing trainer levels raise ValueError, even when a nearby level is known.
    Trainer levels are whole numbers, so a float such as 50.0 is rejected, unlike
    player_cpm, whose half levels need floats.
    """
    tables = _data("rcpm.json")
    if table not in tables:
        raise ValueError(f"unknown rCPM table: {table}")
    if isinstance(trainer_level, bool) or not isinstance(trainer_level, int):
        raise ValueError("trainer level must be an integer")
    source = tables[table]
    entry = source["values"].get(str(trainer_level))
    if entry is None:
        raise ValueError(f"{table} has no trainer level {trainer_level}; no extrapolation")
    value = float(entry["decimal"])
    return struct.unpack("<f", struct.pack("<f", value))[0] if source["float32"] else value


def rocket_stats(base: Mapping[str, int], trainer_level: int, rank: str, table: str) -> RocketStats:
    """Venonic's March 2023 formula, with the selected published rCPM table.

    https://www.reddit.com/r/TheSilphRoad/comments/122pfk8/
    HP = Floor(0.6 * (Base_HP + 15)) * rCPM * Rank
    ATK = (Base_ATK + Floor(2/3 * Base_ATK + 25)) * rCPM * Rank
    DEF = (Base_DEF + 15) * rCPM * Rank
    CP = Floor(sqrt(HP) * ATK * sqrt(DEF) * 0.1)

    CP uses hp_exact; only battle HP is floored. No shadow multiplier is used
    here. No extra float32 rounding of intermediates is asserted by the source.
    Unlike cp(), no minimum of 10 is applied, because no source states one for
    Rocket Pokemon.
    """
    _stats(base)
    if rank not in RANKS:
        raise ValueError(f"unknown Rocket rank: {rank}")
    multiplier = rcpm(trainer_level, table)
    rank_multiplier = RANKS[rank]
    hp_exact = math.floor(0.6 * (base["hp"] + 15)) * multiplier * rank_multiplier
    attack = (base["atk"] + math.floor(2 / 3 * base["atk"] + 25)) * multiplier * rank_multiplier
    defence = (base["def"] + 15) * multiplier * rank_multiplier
    return RocketStats(
        attack=attack,
        defence=defence,
        hp_exact=hp_exact,
        hp=math.floor(hp_exact),
        cp=_cp(attack, defence, hp_exact),
        rank=rank,
        table=table,
    )
