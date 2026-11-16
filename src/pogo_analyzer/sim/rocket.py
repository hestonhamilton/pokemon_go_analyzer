"""Offline, estimated fixed-order Rocket teams, using battle.py's turn core.

Move stat changes follow PvPoke's default, including its deterministic chance
meter; Rules(stat_stages=False) disables them. No lineup fetching, voluntary
switches or player AI. Supplied Combatants have unmodified stats; use
rocket_combatant for stats.rocket_stats.
Sources and evidence grades are also recorded in data/rocket_rules.json and
tests/fixtures/sim/rocket_report.md. No Rocket-only acceptance targets exist.
"""

import json
import math
import warnings
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
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
    # None selects any_charged: a charged attack from either side starts the pause.
    # player_charged is the narrower option. Neither is measured (ledger k).
    pause_trigger: str | None = None
    # None selects any_replacement: either side's faint and replacement starts
    # the pause (owner reading; the 9db row names no side). rocket_replacement
    # is the narrower option.
    faint_trigger: str | None = None
    # True applies the era's 9db slip-in and simultaneous-charge rows.
    era_turn_rules: bool = True
    rocket_charged: str = "when_ready"
    rocket_charged_damage_scale: float = 1.0
    rocket_shields: bool = True
    player_shield_policy: str = "first_two"
    player_shield_threshold: float = 0.5
    timer: bool = True
    turn_rules: Rules = PVPOKE_RULES
    # Sensitivity only: replace charged/faint pauses, keeping manual switch unchanged.
    pause_turns_override: int | None = None

    def __post_init__(self):
        for name in ("pauses", "era_turn_rules", "rocket_shields", "timer"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        if self.pause_reading not in ("9db", "cwizz1"):
            raise ValueError("pause_reading must be 9db or cwizz1")
        if self.pause_turns_override is not None and (
            type(self.pause_turns_override) is not int or not 1 <= self.pause_turns_override <= 20
        ):
            raise ValueError("pause_turns_override must be an integer between 1 and 20 or None")
        if self.pause_trigger not in (None, "player_charged", "any_charged"):
            raise ValueError("pause_trigger must be player_charged or any_charged")
        if self.faint_trigger not in (None, "rocket_replacement", "any_replacement"):
            raise ValueError("faint_trigger must be rocket_replacement or any_replacement")
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
        return self.pause_trigger or "any_charged"

    @property
    def faint(self) -> str:
        return self.faint_trigger or "any_replacement"


DEFAULT_ROCKET_RULES = RocketRules()


def rules_dict(rules: RocketRules) -> dict:
    """Record enabled stat stages; preserve absent-means-off historical JSON."""
    result = asdict(rules)
    if rules.pause_turns_override is None:
        result.pop("pause_turns_override")
    if not rules.turn_rules.stat_stages:
        # Outputs from before stat stages carry no key; absent means off.
        result["turn_rules"].pop("stat_stages")
    return result


@dataclass(frozen=True)
class Evidence:
    row: str
    grade: str
    option: str
    source: str


def _stat_stage_evidence(teams, rules):
    """Static input dependencies, including moves on untouched reserves."""
    if not rules.turn_rules.stat_stages:
        return ()
    moves = [
        move
        for team in teams
        for member in team
        for move in (member.fast, *member.charged)
        if any(move.self_stages) or any(move.opponent_stages)
    ]
    if not moves:
        return ()
    evidence = [
        Evidence(
            "o",
            "owner observation (applies in Rocket battles); multipliers data-mined, "
            "not measured in Rocket",
            "stat_stages",
            "docs/simulator-verification.md#ledger",
        )
    ]
    if any(move.stage_chance < 1 for move in moves):
        evidence.append(
            Evidence(
                "o", "model choice", "chance_schedule:pvpoke_meter", "docs/stat-stages-research.md"
            )
        )
    return tuple(evidence)


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
    faint_trigger: str
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
    start = data["rocket_battles_start"]
    if stamp < start["date"]:
        raise ValueError(
            f"battle_date {stamp} is before Team GO Rocket battles began ({start['date']})"
        )
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
        self.teams, self.rules, self.era, self.rank = teams, rules, era, rank
        self.hp = [[p.hp for p in team] for team in teams]
        self.energy = [[p.energy for p in team] for team in teams]
        self.active = [0, 0]
        self.rocket_shield_policy = (
            "first_two" if rank != "grunt" and rules.rocket_shields else "never"
        )
        # A side that never shields reports none, rather than two unused.
        self.shields = [2, 2 if self.rocket_shield_policy == "first_two" else 0]
        reading = era if rules.pause_reading == "9db" else data["cwizz1"]
        self.lengths = tuple(reading[k] for k in ("charged", "faint", "manual_switch"))
        if rules.pause_turns_override is not None:
            self.lengths = (rules.pause_turns_override, rules.pause_turns_override, self.lengths[2])
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
            # Trigger resolves on t. The core suppresses t+1; the pause then
            # suppresses t+2 .. t+N+1 (the two add), so the Rocket resumes t+N+2.
            self.pause_through = max(self.pause_through, turn + 1 + self.lengths[0])

    def nullify(self, actor):
        # 9db, before Dec 2025: an opponent fast move not yet registered is void
        # (no slip-in), and only the first of two simultaneous charges fires.
        # Applying both to either side, and keeping the void charge's energy,
        # is this project's reading.
        if not self.rules.era_turn_rules:
            return False, False
        return not self.era["fast_slip_in"], not self.era["both_charged_fire"]

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
            if self.era["leader_timeout_loss"] and self.rank != "grunt":
                # Timer post: "Previously, a timeout vs the Rocket Leaders counts
                # as a loss." Giovanni is treated as a leader (this project's reading).
                self.winner = "rocket"
        else:
            for side in range(2):
                if row.hp[side] == 0:
                    self.active[side] += 1
                    replacements[side] = self.teams[side][self.active[side]]
            # Faint pause starts at replacement arrival, after row t. Whose
            # replacement counts is the faint_trigger reading.
            if self.rules.pauses and (
                replacements[1] is not None
                or (replacements[0] is not None and self.rules.faint == "any_replacement")
            ):
                # Owner test, 16 Nov 2026: a charged attack's pause does not carry over to
                # the next Pokémon; the switch-in pause replaces whatever pause is running.
                self.pause_through = row.number + self.lengths[1]
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

    battle_date is mandatory. Passing None explicitly selects the static
    mar-2026 default era, never today's date. The era chooses pauses, the 9db
    slip-in and simultaneous-charge rows, and the leader timeout rule only: the
    caller must supply dated moves and an explicit stat table via rocket_combatant.
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
    if rules.pauses and rules.pause_reading == "cwizz1" and era["id"] not in data["cwizz1"]["eras"]:
        raise ValueError("the cwizz1 reading describes the mar-2026 era only")
    turn_rules = rules.turn_rules
    overridden = (
        rules.era_turn_rules
        and turn_rules.ledger_j_both_charged_fire
        and not era["both_charged_fire"]
    )
    if overridden:
        warnings.warn(
            f"era_turn_rules sets ledger_j_both_charged_fire=False for {era['id']}; "
            "pass era_turn_rules=False to keep the caller's turn_rules",
            stacklevel=2,
        )
    if rules.era_turn_rules:
        turn_rules = replace(turn_rules, ledger_j_both_charged_fire=era["both_charged_fire"])
    battle = _RocketBattle(teams, rank, rules, era, data)
    core = _simulate(
        teams[0][0],
        teams[1][0],
        player_policy=player_policy or ChargedWhenReady(),
        rocket_policy=ChargedWhenReady() if rules.rocket_charged == "when_ready" else FastOnly(),
        player_shield_policy=_Shields(battle, 0),
        rocket_shield_policy=_Shields(battle, 1),
        rules=turn_rules,
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
    if rules.pauses and rules.pause_turns_override is not None:
        evidence.append(
            Evidence(
                "k",
                "pause length override (sensitivity run, not a source value)",
                f"pause_turns_override:{rules.pause_turns_override}",
                "docs/simulator-verification.md#ledger",
            )
        )
    # Mar 2026 accounts support the trigger and the sum; earlier eras extend them.
    extension = (
        "" if era["id"] in data["cwizz1"]["eras"] else f" (applied to {era['id']} by extension)"
    )
    if rules.pauses:
        reading = era if rules.pause_reading == "9db" else data["cwizz1"]
        source = data["source"] if rules.pause_reading == "9db" else data["cwizz1"]["source"]
        for event in ("charged", "faint", "manual_switch"):
            if rules.pause_turns_override is not None and event in ("charged", "faint"):
                continue
            evidence.append(
                Evidence(
                    "k",
                    reading["grades"][event],
                    f"pause_reading:{rules.pause_reading}:{era['id']}:{event}",
                    source,
                )
            )
        evidence.append(
            Evidence(
                "k",
                data["trigger_grade"] + extension
                if rules.trigger == "any_charged"
                else "narrower reading of the 9db row; not measured",
                f"pause_trigger:{rules.trigger}",
                "docs/rocket-pokemon.md#4-how-the-rocket-side-battles",
            )
        )
        evidence.append(
            Evidence(
                "k",
                data["composition_grade"] + extension,
                "pause_composition:sum",
                data["cwizz1"]["source"],
            )
        )
        evidence.append(
            Evidence(
                "k",
                data["faint_grade"]
                if rules.faint == "any_replacement"
                else "narrower reading of the 9db row; not measured",
                f"faint_trigger:{rules.faint}",
                data["source"],
            )
        )
        interpretations += [
            "Pause suppresses only new Rocket inputs. Whether an in-flight fast move "
            "still lands follows the era's 9db slip-in row when era_turn_rules is on.",
            "A charged pause counts t+2 through t+N+1, after the core's post-charge turn; "
            "a faint pause counts t+1 through t+N after replacement. Overlapping pauses "
            "take the later end.",
            data["boundary_note"],
            data["faint_note"],
        ]
        if extension:
            interpretations.append(data["extension_note"])
    if rules.era_turn_rules:
        for row, option in (
            ("fast_slip_in", "fast_slip_in"),
            ("simultaneous_charged", "both_charged_fire"),
        ):
            evidence.append(
                Evidence(
                    "j",
                    era["grades"][row],
                    f"era_turn_rules:{era['id']}:{option}:{era[option]}",
                    data["source"],
                )
            )
        if not era["fast_slip_in"]:
            interpretations.append(
                "Before Dec 2025: an opponent fast move not yet registered when a charged move "
                "fires is void, on either side; only the first of two simultaneous charged "
                "moves fires, and the void one keeps its energy. This applies 9db's rows as "
                "this project reads them."
            )
        if overridden:
            interpretations.append(
                "era_turn_rules replaced the caller's ledger_j_both_charged_fire=True "
                "with the era's value."
            )
    else:
        interpretations.append(
            "era_turn_rules is off: PvPoke's fast-move slip-in and turn_rules apply in every era."
        )
    rocket_charge_used = battle.fired[1] or any(p.charged for p in teams[1])
    if rocket_charge_used:
        evidence += [
            Evidence(
                "l",
                "assumed",
                f"rocket_charged:{rules.rocket_charged}",
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
            data["timer"]["era_note"],
            "Timeout HP fraction is the sum of each team member's current HP / maximum HP.",
        ]
    evidence.extend(_stat_stage_evidence(teams, rules))
    # Dates past the newest source run the newest era's rules, flagged as such.
    forward = stamp is not None and stamp > data["latest_source_date"]
    if forward:
        interpretations.append(data["forward_note"])
    rows = (
        *BASE_LEDGER_ROWS,
        *(r for r in ("k", "l", "m", "n", "o") if any(e.row == r for e in evidence)),
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
        rules.faint,
        rules.player_shield_policy,
        battle.rocket_shield_policy,
        rules,
        rows,
        tuple(evidence),
        ("unverified",) * rocket_charge_used + ("extrapolated",) * forward,
        tuple(interpretations),
    )
