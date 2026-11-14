"""Deterministic, estimated 1v1 turn mechanics. No Rocket decision model.

Ported from PvPoke (MIT, copyright 2019 pvpoke), commit
426e5e9f39d3a027849698fb2f5edd9df6056cbf. Bare line numbers below cite
src/js/battle/Battle.js; citations into other files name the file (for
example Pokemon.js). Full notice: data/PVPoke-LICENSE.
Only ordinary, unbuffed moves are represented by calculator.Move. Forms,
move effects, switching, Rocket pauses, shield inventories and timers are absent.
"""

import math
from dataclasses import dataclass
from typing import Protocol

from .calculator import Move
from .damage import calculate_damage

TURN_SECONDS = 0.5  # Battle.js 38, 405: deltaTime = 500 ms.
ENERGY_CAP = 100  # Battle.js 1337–1340.
BASE_LEDGER_ROWS = ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j")


@dataclass(frozen=True)
class Combatant:
    """Unmodified stats. The second combatant is the Rocket side, always shadow.

    ``shadow`` applies to the player only. The Rocket side is shadow by rule
    (ledger g), so simulate() rejects a Rocket combatant with shadow=True rather
    than appear to honour a flag it ignores.
    """

    attack: float
    defence: float
    hp: int
    types: tuple[str, ...]
    fast: Move
    charged: tuple[Move, ...] = ()
    shadow: bool = False
    energy: int = 0

    def __post_init__(self):
        if any(not math.isfinite(v) or v <= 0 for v in (self.attack, self.defence)):
            raise ValueError("attack and defence must be finite and positive")
        if isinstance(self.hp, bool) or not isinstance(self.hp, int) or self.hp <= 0:
            raise ValueError("HP must be a positive integer")
        if isinstance(self.energy, bool) or not isinstance(self.energy, int):
            raise ValueError("energy must be an integer")
        if not 0 <= self.energy <= ENERGY_CAP:
            raise ValueError("starting energy must be 0–100")
        if any(
            isinstance(m.power, bool) or not math.isfinite(m.power) or m.power < 0
            for m in (self.fast, *self.charged)
        ):
            raise ValueError("move power must be finite and nonnegative")
        if (
            not math.isfinite(self.fast.turns)
            or self.fast.turns < 1
            or int(self.fast.turns) != self.fast.turns
            or self.fast.energy != 0
            or isinstance(self.fast.energy_gain, bool)
            or not isinstance(self.fast.energy_gain, int)
            or self.fast.energy_gain < 0
        ):
            raise ValueError("fast moves need whole positive turns, no cost and nonnegative gain")
        if any(
            isinstance(m.energy, bool)
            or not isinstance(m.energy, int)
            or not 0 < m.energy <= ENERGY_CAP
            or m.energy_gain != 0
            for m in self.charged
        ):
            raise ValueError("charged moves need cost 1–100 and no energy gain")


@dataclass(frozen=True)
class State:
    """Read-only policy input. Move decisions share the state before resolution."""

    combatant: Combatant
    hp: int
    energy: int
    cooldown: int


class ShieldPolicy(Protocol):
    def shield(self, own: State, opponent: State, move: Move, turn: int) -> bool: ...


class Policy(ShieldPolicy, Protocol):
    def choose_charged(self, own: State, opponent: State, turn: int) -> int | None: ...


class NeverShield:
    name = "never_shield"

    def shield(self, own: State, opponent: State, move: Move, turn: int) -> bool:
        return False


class FastOnly(NeverShield):
    name = "fast_only"

    def choose_charged(self, own: State, opponent: State, turn: int) -> int | None:
        return None


class ChargedWhenReady(NeverShield):
    """First affordable move in Combatant.charged, preserving caller order."""

    name = "charged_when_ready"

    def choose_charged(self, own: State, opponent: State, turn: int) -> int | None:
        return next(
            (i for i, move in enumerate(own.combatant.charged) if own.energy >= move.energy),
            None,
        )


@dataclass(frozen=True)
class Rules:
    """Defaults are pinned PvPoke. Alternatives are ledger-j estimates, not parity.

    ledger_j_next_turn_charged: a charge submitted on turn t starts and resolves
    on t + 1. Decisions still come before resolution, so the opponent may submit
    its own charge on t + 1, while the first one resolves; that second charge then
    resolves on t + 2, the turn after a charge, which accepts no new inputs.
    Example: t1 player submits, t2 player's charge hits and the Rocket submits,
    t3 the Rocket's charge hits, t4 no inputs. This is an estimate of ledger j,
    not a measured Rocket timeline.
    """

    ledger_j_next_turn_charged: bool = False
    ledger_j_both_charged_fire: bool = False


PVPOKE_RULES = Rules()


@dataclass(frozen=True)
class Turn:
    number: int
    # Per side: kind:queue/start/hit/cancel:move ID. Empty = cooldown/idle.
    actions: tuple[tuple[str, ...], tuple[str, ...]]
    damage: tuple[int, int]  # Nominal damage, including overkill, like TimelineEvent.
    hp: tuple[int, int]
    energy: tuple[int, int]


@dataclass(frozen=True)
class Result:
    winner: str | None
    turns_elapsed: int
    hp: tuple[int, int]
    damage: tuple[int, int]
    timeline: tuple[Turn, ...]
    limit_reached: bool
    rules: Rules
    label: str = "estimate"
    ledger_rows: tuple[str, ...] = BASE_LEDGER_ROWS


@dataclass(frozen=True)
class _Action:
    actor: int
    turn: int
    move: Move
    priority: int


def simulate(
    player: Combatant,
    rocket: Combatant,
    *,
    player_policy: Policy | None = None,
    rocket_policy: Policy | None = None,
    player_shield_policy: ShieldPolicy | None = None,
    rocket_shield_policy: ShieldPolicy | None = None,
    rules: Rules = PVPOKE_RULES,
    max_turns: int = 10000,
) -> Result:
    """Run to first faint, completing that turn (625–629), or an explicit limit.

    max_turns is a caller observation/safety limit, not a battle timeout rule.
    Winner is player/rocket, or None for a double KO or incomplete observation.
    Shield callbacks supply decisions only; no inventory or Rocket shield rule.
    Rocket attacks and defence always use shadow=True (ledger g).
    Stats provenance rows b–e are conservative dependencies of these supplied totals.
    """
    if isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns < 1:
        raise ValueError("max_turns must be a positive integer")
    if rocket.shadow:
        raise ValueError("the Rocket side is always shadow (ledger g); leave its shadow unset")
    combatants = (player, rocket)
    policies = (player_policy or FastOnly(), rocket_policy or FastOnly())
    shields = (player_shield_policy or policies[0], rocket_shield_policy or policies[1])
    hp = [p.hp for p in combatants]
    energy = [p.energy for p in combatants]
    cooldown = [0, 0]  # Pokemon.js 1924–1931, 1944–1947.
    faint_source = ["", ""]
    queue: list[_Action] = []
    timeline = []
    total = [0, 0]
    previous_charged = False
    used_charged = [False, False]
    used_shield = False
    for turn in range(1, max_turns + 1):
        events: list[list[str]] = [[], []]
        dealt = [0, 0]
        cooldown = [max(0, c - 1) for c in cooldown]  # 303–311.
        views = tuple(State(p, hp[i], energy[i], cooldown[i]) for i, p in enumerate(combatants))
        for i, p in enumerate(combatants):
            # 332–383, 732: simultaneous decisions before any damage/energy changes.
            # 341–343: the turn after a charged sequence accepts no attack inputs.
            pending_charge = any(a.actor == i and a.move.energy for a in queue)
            if cooldown[i] or previous_charged or pending_charge:
                continue
            choice = policies[i].choose_charged(views[i], views[1 - i], turn)
            if choice is not None and (
                isinstance(choice, bool)
                or not isinstance(choice, int)
                or not 0 <= choice < len(p.charged)
            ):
                raise ValueError("policy chose an invalid charged move index")
            move = p.fast if choice is None else p.charged[choice]
            if move.energy > energy[i]:
                raise ValueError("policy chose an unaffordable charged move")
            # 367, 378: cooldown begins at submission, not at damage registration.
            cooldown[i] += 1 if move.energy else int(move.turns)
            # 780–785, 434: charged first, then higher *unmodified* attack. Stable ties.
            priority = 10 + int(p.attack > combatants[1 - i].attack) if move.energy else 0
            queue.append(_Action(i, turn, move, priority))
            kind = "charged" if move.energy else "fast"
            stage = "queue" if move.energy and rules.ledger_j_next_turn_charged else "start"
            events[i].append(f"{kind}:{stage}:{move.id}")
            used_charged[i] |= move.energy > 0

        ready = []
        waiting = []
        for action in queue:
            age = turn - action.turn
            if action.move.energy:
                due = age >= int(rules.ledger_j_next_turn_charged)
            else:
                # 405–409: duration minus one; floating fast moves flush after charge.
                due = age >= action.move.turns - 1 or (previous_charged and age > 0)
            (ready if due else waiting).append(action)
        queue = waiting
        ready.sort(key=lambda a: -a.priority)
        any_charged = any(a.move.energy for a in ready)
        charged_used = False
        for action in ready:
            i = action.actor
            other = 1 - i
            p, opponent = combatants[i], combatants[other]
            move = action.move
            charged = move.energy > 0
            kind = "charged" if charged else "fast"
            if charged and rules.ledger_j_next_turn_charged:
                events[i].append(f"charged:start:{move.id}")
            if charged:
                # 473–481, 262–265: unequal-attack CMP cancels a fainted reply;
                # equal attacks permit both, even when the first charged move KOs.
                valid = energy[i] >= move.energy and not (
                    player.attack != rocket.attack
                    and hp[i] <= 0
                    and faint_source[i] == "charged"
                    and not rules.ledger_j_both_charged_fire
                )
            else:
                # 451–460: fast KO still permits queued retaliation; charged KO doesn't.
                valid = hp[other] > 0 and not (hp[i] < 1 and faint_source[i] == "charged")
            if not valid:
                events[i].append(f"{kind}:cancel:{move.id}")
                continue
            shielded = charged and shields[other].shield(
                State(opponent, hp[other], energy[other], cooldown[other]),
                State(p, hp[i], energy[i], cooldown[i]),
                move,
                turn,
            )
            damage = calculate_damage(
                move.power,
                p.attack,
                opponent.defence,
                move.type,
                p.types,
                opponent.types,
                attacker_shadow=True if i == 1 else player.shadow,
                defender_shadow=True if other == 1 else player.shadow,
                charged=charged,
                shielded=shielded,
            ).damage
            if charged:
                energy[i] -= move.energy  # 1058: cost paid only on resolution.
                charged_used = True
            else:
                energy[i] = min(ENERGY_CAP, energy[i] + move.energy_gain)  # 1329–1340.
            hp[other] = max(0, hp[other] - damage)  # 1365.
            if hp[other] <= 0:
                faint_source[other] = kind  # 1683–1684.
            dealt[i] += damage
            total[i] += damage
            used_shield |= shielded
            events[i].append(f"{kind}:hit:{move.id}")
        if charged_used:
            cooldown = [1, 1]  # 546–549: release both cooldowns, keep queued fast moves.
        timeline.append(
            Turn(turn, tuple(tuple(e) for e in events), tuple(dealt), tuple(hp), tuple(energy))
        )
        previous_charged = any_charged  # 498: includes cancelled charged actions.
        # Complete all eligible actions before ending on a faint: 528–543, 629.
        if min(hp) <= 0:
            break
    incomplete = min(hp) > 0
    winner = None if incomplete or max(hp) == 0 else ("player" if hp[0] > 0 else "rocket")
    rows = BASE_LEDGER_ROWS
    if used_charged[1]:
        rows += ("l",)
    if used_shield:
        rows += ("m",)
    if used_charged[0]:
        rows += ("p",)
    return Result(
        winner, turn, tuple(hp), tuple(total), tuple(timeline), incomplete, rules, ledger_rows=rows
    )
