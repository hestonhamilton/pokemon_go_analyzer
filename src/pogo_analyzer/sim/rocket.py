"""Offline, estimated fixed-order Rocket teams, using battle.py's turn core.

No lineup fetching, voluntary switches, move effects or player AI. Supplied
Combatants have unmodified stats; use rocket_combatant for stats.rocket_stats.
Sources and evidence grades are also recorded in data/rocket_rules.json and
tests/fixtures/sim/rocket_report.md. No Rocket-only acceptance targets exist.
"""

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from importlib.resources import files

from .battle import (
    BASE_LEDGER_ROWS,
    PVPOKE_RULES,
    ChargedWhenReady,
    Combatant,
    FastOnly,
    Policy,
    Rules,
    State,
    Turn,
    _BattleHooks,
    _simulate,
)
from .calculator import Move
from .damage import DamageResult, calculate_damage
from .stats import RANKS, rocket_stats


def rule_data() -> dict:
    """A fresh copy of the dated evidence; callers cannot mutate later runs."""
    return json.loads(files(__package__).joinpath("data", "rocket_rules.json").read_text())


@dataclass(frozen=True)
class RocketRules:
    pauses: bool = True
    pause_reading: str = "9db"
    # None selects player_charged for 9db, any_charged for cwizz1.
    pause_trigger: str | None = None
    rocket_charged: str = "when_ready"
    rocket_charged_damage_scale: float = 1.0
    rocket_shields: bool = True
    player_shield_policy: str = "first_two"
    player_shield_threshold: float = 0.5
    timer: bool = True
    turn_rules: Rules = PVPOKE_RULES

    def __post_init__(self):
        for name in ("pauses", "rocket_shields", "timer"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        if self.pause_reading not in ("9db", "cwizz1"):
            raise ValueError("pause_reading must be 9db or cwizz1")
        if self.pause_trigger not in (None, "player_charged", "any_charged"):
            raise ValueError("pause_trigger must be player_charged or any_charged")
        if self.rocket_charged not in ("when_ready", "never"):
            raise ValueError("rocket_charged must be when_ready or never")
        if isinstance(self.rocket_charged_damage_scale, bool) or (
            self.rocket_charged_damage_scale not in (1.0, 0.5625)
        ):
            raise ValueError("rocket_charged_damage_scale must be 1.0 or 0.5625")
        if self.player_shield_policy not in ("first_two", "never", "threshold"):
            raise ValueError("player_shield_policy must be first_two, never or threshold")
        if (
            isinstance(self.player_shield_threshold, bool)
            or not math.isfinite(self.player_shield_threshold)
            or not 0 < self.player_shield_threshold <= 1
        ):
            raise ValueError("player_shield_threshold must be in (0, 1]")
        if not isinstance(self.turn_rules, Rules):
            raise ValueError("turn_rules must be battle.Rules")

    @property
    def trigger(self) -> str:
        return self.pause_trigger or (
            "any_charged" if self.pause_reading == "cwizz1" else "player_charged"
        )


DEFAULT_ROCKET_RULES = RocketRules()


@dataclass(frozen=True)
class Evidence:
    row: str
    grade: str
    option: str
    source: str


@dataclass(frozen=True)
class RocketTurn:
    core: Turn  # After resolution, before replacements; damage includes overkill.
    active_slots: tuple[int, int]  # One-based, during this turn.
    replacements: tuple[int | None, int | None]  # Arrive after this turn.
    shields: tuple[int, int]
    pause_through: int  # Inclusive; a new input is allowed on pause_through + 1.
    deadline: int | None


@dataclass(frozen=True)
class RocketResult:
    winner: str | None
    ended_by: str  # knockout, timeout, or observation_limit (explicit max_turns).
    turns_elapsed: int
    hp: tuple[tuple[int, ...], tuple[int, ...]]
    energy: tuple[tuple[int, ...], tuple[int, ...]]
    shields: tuple[int, int]
    damage: tuple[int, int]
    timeline: tuple[RocketTurn, ...]
    battle_date: str | None
    era: str
    pause_lengths: tuple[int, int, int]  # Charge, faint, unused manual switch.
    pause_trigger: str
    player_shield_policy: str
    rocket_shield_policy: str
    rules: RocketRules
    ledger_rows: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    flags: tuple[str, ...]
    interpretations: tuple[str, ...]
    label: str = "estimate"


def rocket_combatant(
    base_stats: dict,
    types: Sequence[str],
    fast: Move,
    charged: Sequence[Move] = (),
    *,
    trainer_level: int,
    rank: str,
    table: str,
) -> Combatant:
    """Build an always-shadow opponent using the existing rank/stat tables."""
    stats = rocket_stats(base_stats, trainer_level, rank, table)
    return Combatant(stats.attack, stats.defence, stats.hp, tuple(types), fast, tuple(charged))


def _era(battle_date: date | str | None, data: dict) -> tuple[dict, str | None]:
    if battle_date is None:
        return next(e for e in data["eras"] if e["id"] == data["default_era"]), None
    if isinstance(battle_date, str):
        battle_date = date.fromisoformat(battle_date)
    # datetime is deliberately rejected: the caller must choose the calendar date.
    if type(battle_date) is not date:
        raise ValueError("battle_date must be a calendar date, ISO date or None")
    stamp = battle_date.isoformat()
    return next(
        e
        for e in data["eras"]
        if (e["from"] is None or stamp >= e["from"]) and (e["until"] is None or stamp < e["until"])
    ), stamp


def _damage(own: State, opponent: State, move: Move, actor: int) -> DamageResult:
    return calculate_damage(
        move.power,
        own.combatant.attack,
        opponent.combatant.defence,
        move.type,
        own.combatant.types,
        opponent.combatant.types,
        attacker_shadow=actor == 1 or own.combatant.shadow,
        defender_shadow=actor == 0 or opponent.combatant.shadow,
        charged=bool(move.energy),
    )


class _Shields:
    def __init__(self, battle: "_RocketBattle", side: int):
        self.battle, self.side = battle, side

    def shield(self, own: State, opponent: State, move: Move, turn: int) -> bool:
        b, i = self.battle, self.side
        if not b.shields[i]:
            return False
        if i == 1:
            use = b.rocket_shield_policy == "first_two"
        elif b.rules.player_shield_policy == "threshold":
            raw = _damage(opponent, own, move, 1)
            unshielded = math.floor(raw.raw * b.rules.rocket_charged_damage_scale) + 1
            use = unshielded >= own.hp * b.rules.player_shield_threshold
        else:
            use = b.rules.player_shield_policy == "first_two"
        if use:
            b.shields[i] -= 1
        return use


class _RocketBattle(_BattleHooks):
    def __init__(self, teams, rank, rules, era, data):
        self.teams, self.rules, self.era = teams, rules, era
        self.hp = [[p.hp for p in team] for team in teams]
        self.energy = [[p.energy for p in team] for team in teams]
        self.active = [0, 0]
        self.shields = [2, 2]
        self.rocket_shield_policy = (
            "first_two" if rank != "grunt" and rules.rocket_shields else "never"
        )
        reading = era if rules.pause_reading == "9db" else data["cwizz1"]
        self.lengths = tuple(reading[k] for k in ("charged", "faint", "manual_switch"))
        self.pause_through = 0
        self.deadline = data["timer"]["base_turns"] if rules.timer else None
        self.per_charge = data["timer"]["per_charged_turns"]
        self.timeline: list[RocketTurn] = []
        self.fired = [0, 0]
        self.finished = False
        self.ended_by = "observation_limit"
        self.winner = None

    def allow_input(self, actor, turn):
        # Interpretation: an existing action still resolves while inputs pause.
        return actor == 0 or turn > self.pause_through

    def damage(self, actor, move, result, shielded):
        if actor == 1 and move.energy and not shielded:
            # Ledger l interpretation: source does not locate the scale relative
            # to floor/+1. Scale raw damage; shield override remains exactly 1.
            return math.floor(result.raw * self.rules.rocket_charged_damage_scale) + 1
        return result.damage

    def charged(self, actor, turn):
        self.fired[actor] += 1
        if self.deadline is not None:
            self.deadline += self.per_charge
        if self.rules.pauses and (actor == 0 or self.rules.trigger == "any_charged"):
            # Trigger resolves on t. Suppress t+1 .. t+N inclusive, resume t+N+1.
            # The core independently suppresses t+1; these overlap, never add.
            self.pause_through = max(self.pause_through, turn + self.lengths[0])

    def finish_turn(self, row):
        slots = tuple(i + 1 for i in self.active)
        for side, index in enumerate(self.active):
            self.hp[side][index], self.energy[side][index] = row.hp[side], row.energy[side]
        remaining = [sum(h > 0 for h in team) for team in self.hp]
        replacements = [None, None]
        if 0 in remaining:
            self.finished, self.ended_by = True, "knockout"
            self.winner = None if remaining == [0, 0] else ("player" if remaining[0] else "rocket")
        elif self.deadline is not None and row.number >= self.deadline:
            self.finished, self.ended_by = True, "timeout"
            # Interpretation of HP%: sum of each member's HP/maxHP, including
            # fainted zeros and untouched reserves. Exact rationals avoid ties
            # being broken by floating arithmetic. Equal scores are a draw.
            fractions = [
                sum((Fraction(h, p.hp) for h, p in zip(hps, team, strict=True)), Fraction())
                for hps, team in zip(self.hp, self.teams, strict=True)
            ]
            scores = list(zip(remaining, fractions, strict=True))
            self.winner = (
                None
                if scores[0] == scores[1]
                else ("player" if scores[0] > scores[1] else "rocket")
            )
        else:
            for side in range(2):
                if row.hp[side] == 0:
                    self.active[side] += 1
                    replacements[side] = self.teams[side][self.active[side]]
            # Faint pause starts at Rocket replacement arrival, after row t.
            # Player-only replacement does not trigger it in the 9db reading.
            if replacements[1] is not None and self.rules.pauses:
                self.pause_through = max(self.pause_through, row.number + self.lengths[1])
            elif (
                replacements[0] is not None
                and self.rules.pauses
                and (self.rules.pause_reading == "cwizz1")
            ):
                self.pause_through = max(self.pause_through, row.number + self.lengths[1])
        self.timeline.append(
            RocketTurn(
                row,
                slots,
                tuple(self.active[i] + 1 if p else None for i, p in enumerate(replacements)),
                tuple(self.shields),
                self.pause_through,
                self.deadline,
            )
        )
        return tuple(replacements)


def simulate_rocket(
    player_team: Sequence[Combatant],
    rocket_team: Sequence[Combatant],
    *,
    battle_date: date | str | None,
    rank: str = "grunt",
    rules: RocketRules = DEFAULT_ROCKET_RULES,
    player_policy: Policy | None = None,
    max_turns: int = 100000,
) -> RocketResult:
    """Fixed-order teams of one to three (three for a full battle).

    battle_date is mandatory. Passing None explicitly selects the static Sep
    2026 default era, never today's date. This chooses pauses only: the caller
    must supply dated moves and an explicit stat table via rocket_combatant.
    Player move selection defaults to first affordable charge, a model policy.
    max_turns is a separate observation limit; it cannot award a timeout win.
    """
    teams = tuple(tuple(team) for team in (player_team, rocket_team))
    if any(not 1 <= len(team) <= 3 for team in teams):
        raise ValueError("each team needs one to three Pokemon")
    if rank not in RANKS:
        raise ValueError("rank must be grunt, leader or giovanni")
    if any(p.shadow for p in teams[1]):
        raise ValueError("the Rocket side is always shadow; leave its shadow unset")
    if any(len(p.charged) > 1 for p in teams[1]):
        raise ValueError("Rocket Pokemon have at most one supplied charged move")
    data = rule_data()
    era, stamp = _era(battle_date, data)
    battle = _RocketBattle(teams, rank, rules, era, data)
    core = _simulate(
        teams[0][0],
        teams[1][0],
        player_policy=player_policy or ChargedWhenReady(),
        rocket_policy=ChargedWhenReady() if rules.rocket_charged == "when_ready" else FastOnly(),
        player_shield_policy=_Shields(battle, 0),
        rocket_shield_policy=_Shields(battle, 1),
        rules=rules.turn_rules,
        max_turns=max_turns,
        hooks=battle,
    )
    evidence = [
        Evidence(
            "m",
            "observed in play",
            f"rocket_shields:{battle.rocket_shield_policy}",
            "docs/rocket-battle-mechanics.md#5-shields-switching-and-the-npcs-behaviour",
        ),
        Evidence(
            "m",
            "assumed (model choice)",
            f"player_shield_policy:{rules.player_shield_policy}",
            "tests/fixtures/sim/rocket_report.md#shields",
        ),
    ]
    interpretations = [
        "Fixed order; replacements arrive after the faint turn. "
        "Clear the queue and both cooldowns.",
        "A final knockout takes precedence over timeout on the same turn. "
        "Equal timeout scores draw.",
    ]
    if rules.pauses:
        source = data["source"] if rules.pause_reading == "9db" else data["cwizz1"]["source"]
        for event in ("charged", "faint", "manual_switch"):
            evidence.append(
                Evidence(
                    "k",
                    data["grades"][event],
                    f"pause_reading:{rules.pause_reading}:{event}",
                    source,
                )
            )
        interpretations += [
            "Pause suppresses only new Rocket inputs. "
            "In-flight fast moves retain PvPoke resolution.",
            "Pause counts t+1 through t+N after resolution or replacement. "
            "It overlaps post-charge input suppression by max, never sum.",
            data["boundary_note"],
            "9db faint pause requires a Rocket replacement. "
            "cwizz1 also pauses on player replacement.",
        ]
    if battle.fired[1]:
        evidence += [
            Evidence(
                "l",
                "assumed",
                "rocket_charged:when_ready",
                "docs/rocket-pokemon.md#4-how-the-rocket-side-battles",
            ),
            Evidence(
                "l",
                "assumed"
                if rules.rocket_charged_damage_scale == 1
                else "measured-once and outdated",
                "rocket_charged_damage_scale",
                "docs/simulator-verification.md#ledger",
            ),
        ]
        interpretations.append(
            "Rocket charged damage scale multiplies raw damage before floor + 1. "
            "Shields override to 1."
        )
    if rules.timer:
        evidence.append(Evidence("n", "measured-once", "timer", data["timer"]["source"]))
        interpretations += [
            data["timer"]["interpretation"],
            "Timeout HP fraction is the sum of each team member's current HP / maximum HP.",
        ]
    rows = (
        *BASE_LEDGER_ROWS,
        *(r for r in ("k", "l", "m", "n") if any(e.row == r for e in evidence)),
    )
    if battle.fired[0]:
        rows += ("p",)
    return RocketResult(
        battle.winner,
        battle.ended_by,
        core.turns_elapsed,
        tuple(tuple(h) for h in battle.hp),
        tuple(tuple(e) for e in battle.energy),
        tuple(battle.shields),
        core.damage,
        tuple(battle.timeline),
        stamp,
        era["id"],
        battle.lengths,
        rules.trigger,
        rules.player_shield_policy,
        battle.rocket_shield_policy,
        rules,
        rows,
        tuple(evidence),
        ("unverified",) if battle.fired[1] else (),
        tuple(interpretations),
    )
