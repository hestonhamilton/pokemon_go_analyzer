"""Exact solo Rocket aggregation with memoized lineup prefixes.

The reference is sim/battle.py::_simulate with sim/rocket.py::_RocketBattle.
At a Rocket replacement the reference clears the queue and both cooldowns.
The boundary below therefore contains all state needed for the next opponent.
No timeline is built here; at most four reference battles supply metadata strings.
"""

from collections import Counter
from dataclasses import replace
from fractions import Fraction
from functools import lru_cache
from math import prod
from typing import NamedTuple

from . import winrate
from .damage import calculate_damage
from .rocket import DEFAULT_ROCKET_RULES, _era, rule_data, simulate_rocket


@lru_cache(maxsize=32768)
def _damage_cached(
    power,
    attack,
    defence,
    move_type,
    attacker_types,
    defender_types,
    *,
    attacker_shadow,
    defender_shadow,
    attack_stage=0,
    defence_stage=0,
    charged=False,
    shielded=False,
    attacker_mega=False,
    is_mega_move=False,
    mega_level=3,
):
    """Every calculate_damage argument is in the cache key, including defaults."""
    return calculate_damage(
        power,
        attack,
        defence,
        move_type,
        attacker_types,
        defender_types,
        attacker_shadow=attacker_shadow,
        defender_shadow=defender_shadow,
        attack_stage=attack_stage,
        defence_stage=defence_stage,
        charged=charged,
        shielded=shielded,
        attacker_mega=attacker_mega,
        is_mega_move=is_mega_move,
        mega_level=mega_level,
    )


def supports(team, pools, rules=DEFAULT_ROCKET_RULES) -> bool:
    """Accept a solo player, full pools and default rules plus a pause override.

    Implements the default ChargedWhenReady player and Rocket policies only.
    Callers must separately check their battle function is simulate_rocket.
    Multi-member teams and every other rule variation use the reference.
    """
    return (
        len(team) == 1
        and len(pools) == 3
        and all(pools)
        and replace(rules, pause_turns_override=None) == DEFAULT_ROCKET_RULES
        and all(
            not o.combatant.shadow and len(o.combatant.charged) <= 1 for pool in pools for o in pool
        )
    )


class _Boundary(NamedTuple):
    """State after replacement, with empty queue and zero cooldowns."""

    turn: int
    hp: int
    energy: int
    faint_source: str
    previous_charged: bool
    player_shields: int
    rocket_shields: int
    pause_through: int
    deadline: int
    slot: int  # zero-based new Rocket slot; queue/cooldowns reset at this point


class _Terminal(NamedTuple):
    winner: str | None
    ended_by: str
    turns: int
    hp: int
    fainted: int  # solo fixed order: precisely slots 1..fainted


class _Segment(NamedTuple):
    end: _Boundary | _Terminal
    fired: tuple[int, int]  # resolved charges in just this segment


class _Engine:
    """Per-call prefix memo and exact turn loop; see the reference modules above."""

    def __init__(self, team, pools, *, rank, battle_date, rules=DEFAULT_ROCKET_RULES):
        if not supports(team, pools, rules):
            raise ValueError("unsupported solo engine team, pools or rules")
        if rank not in ("grunt", "leader", "giovanni"):
            raise ValueError("invalid rank")
        self.team, self.player, self.pools = tuple(team), team[0], tuple(tuple(p) for p in pools)
        self.rank, self.battle_date, self.rules = rank, battle_date, rules
        self.data = rule_data()
        self.era, self.stamp = _era(battle_date, self.data)
        self.initial = _Boundary(
            0,
            self.player.hp,
            self.player.energy,
            "",
            False,
            2,
            0 if rank == "grunt" else 2,
            0,
            self.data["timer"]["base_turns"],
            0,
        )
        self.combatants, ids = [], {}
        self.option_ids = []
        for pool in self.pools:
            group = []
            for option in pool:
                c = option.combatant
                if c not in ids:
                    ids[c] = len(self.combatants)
                    self.combatants.append(c)
                group.append(ids[c])
            self.option_ids.append(group)
        self.packets = {}
        self.memo = [{}, {}, {}]

    def packet(self, option_id):
        """Precompute exact shielded and unshielded damage for this opponent."""
        if option_id in self.packets:
            return self.packets[option_id]
        cs = self.player, self.combatants[option_id]
        moves = tuple((c.fast, *c.charged) for c in cs)
        damages = []
        for i in range(2):
            p, opponent = cs[i], cs[1 - i]
            group = []
            for move in moves[i]:
                args = (move.power, p.attack, opponent.defence, move.type, p.types, opponent.types)
                opts = dict(
                    attacker_shadow=i == 1 or p.shadow,
                    defender_shadow=i == 0 or opponent.shadow,
                    attack_stage=0,
                    defence_stage=0,
                    charged=bool(move.energy),
                    shielded=False,
                    attacker_mega=False,
                    is_mega_move=False,
                    mega_level=3,
                )
                plain = _damage_cached(*args, **opts).damage
                shield = plain
                if move.energy:
                    opts["shielded"] = True
                    shield = _damage_cached(*args, **opts).damage
                group.append((plain, shield))
            damages.append(group)
        packet = cs, moves, damages
        self.packets[option_id] = packet
        return packet

    def segment(self, state, option_id):
        depth = state.slot
        key = state, option_id
        memo = self.memo[depth]
        if key in memo:
            return memo[key]
        result = self._segment(state, option_id)
        memo[key] = result
        return result

    def _segment(self, state, option_id):
        """Follow sim/battle.py::_simulate and sim/rocket.py::_RocketBattle order."""
        cs, moves, damages = self.packet(option_id)
        turn, player_hp, player_energy, source, previous_charged, ps, rs, pause, deadline, slot = (
            state
        )
        hp = [player_hp, cs[1].hp]
        energy = [player_energy, cs[1].energy]
        faint_source = [source, ""]
        cooldown, shields, fired = [0, 0], [ps, rs], [0, 0]
        queue = []  # (actor, submission turn, move index, priority)
        fast_off = not self.era["fast_slip_in"]
        charged_off = not self.era["both_charged_fire"]
        both_fire = self.era["both_charged_fire"]
        unequal_attack = cs[0].attack != cs[1].attack
        priorities = [10 + int(cs[i].attack > cs[1 - i].attack) for i in range(2)]
        override = self.rules.pause_turns_override
        charge_pause = self.era["charged"] if override is None else override
        faint_pause = self.era["faint"] if override is None else override
        per_charge = self.data["timer"]["per_charged_turns"]
        # DEFAULT_ROCKET_RULES has immediate charged resolution, first-affordable
        # move choice, and first-two shielding for both sides (none for grunts).
        while turn < 100000:
            turn += 1
            cooldown[0] = max(0, cooldown[0] - 1)
            cooldown[1] = max(0, cooldown[1] - 1)
            for i in range(2):
                if cooldown[i] or previous_charged or (i == 1 and turn <= pause):
                    continue
                # Pending charges never survive a turn under default turn rules.
                choice = 0
                for j in range(1, len(moves[i])):
                    if energy[i] >= moves[i][j].energy:
                        choice = j
                        break
                move = moves[i][choice]
                charged = bool(move.energy)
                cooldown[i] += 1 if charged else int(move.turns)
                queue.append((i, turn, choice, priorities[i] if charged else 0))
            ready, waiting = [], []
            for a in queue:
                move = moves[a[0]][a[2]]
                age = turn - a[1]
                due = bool(move.energy) or age >= move.turns - 1 or (previous_charged and age > 0)
                (ready if due else waiting).append(a)
            queue = waiting
            ready.sort(key=lambda a: -a[3])
            any_charged = any(moves[a[0]][a[2]].energy for a in ready)
            charged_used = False
            nullified = set()
            for index, a in enumerate(ready):
                i, _, choice, _ = a
                other = 1 - i
                move = moves[i][choice]
                charged = bool(move.energy)
                if index in nullified:
                    continue
                if charged:
                    valid = energy[i] >= move.energy and not (
                        unequal_attack
                        and hp[i] <= 0
                        and faint_source[i] == "charged"
                        and not both_fire
                    )
                else:
                    valid = hp[other] > 0 and not (hp[i] < 1 and faint_source[i] == "charged")
                if not valid:
                    continue
                shielded = charged and shields[other] > 0
                if shielded:
                    shields[other] -= 1
                damage = damages[i][choice][int(shielded)]
                if charged:
                    energy[i] -= move.energy
                    charged_used = True
                    fired[i] += 1
                    deadline += per_charge
                    pause = max(pause, turn + 1 + charge_pause)
                    if fast_off or charged_off:
                        for j, b in enumerate(ready):
                            if b[0] == other and (
                                charged_off if moves[other][b[2]].energy else fast_off
                            ):
                                nullified.add(j)
                        if fast_off:
                            queue = [b for b in queue if b[0] != other or moves[other][b[2]].energy]
                else:
                    energy[i] = min(100, energy[i] + move.energy_gain)
                hp[other] = max(0, hp[other] - damage)
                if hp[other] <= 0:
                    faint_source[other] = "charged" if charged else "fast"
            if charged_used:
                cooldown = [1, 1]
            previous_charged = any_charged
            # finish_turn: final KO, then timeout, then replacement (and its pause).
            fainted = slot + int(hp[1] == 0)
            remaining_rocket = 3 - fainted
            if hp[0] == 0 or remaining_rocket == 0:
                winner = (
                    None
                    if hp[0] == 0 and remaining_rocket == 0
                    else ("player" if hp[0] else "rocket")
                )
                return _Segment(_Terminal(winner, "knockout", turn, hp[0], fainted), tuple(fired))
            if turn >= deadline:
                pscore = (1, Fraction(hp[0], cs[0].hp))
                rscore = (remaining_rocket, Fraction(hp[1], cs[1].hp) + (2 - slot))
                winner = None if pscore == rscore else ("player" if pscore > rscore else "rocket")
                if self.era["leader_timeout_loss"] and self.rank != "grunt":
                    winner = "rocket"
                return _Segment(_Terminal(winner, "timeout", turn, hp[0], fainted), tuple(fired))
            if hp[1] == 0:
                pause = max(pause, turn + faint_pause)
                end = _Boundary(
                    turn,
                    hp[0],
                    energy[0],
                    faint_source[0],
                    previous_charged,
                    shields[0],
                    shields[1],
                    pause,
                    deadline,
                    slot + 1,
                )
                return _Segment(end, tuple(fired))
        return _Segment(_Terminal(None, "observation_limit", turn, hp[0], slot), tuple(fired))

    def outcome(self, lineup):
        """Per-lineup fields used for verification, including resolved charge counts."""
        state, fired = self.initial, [0, 0]
        for option in lineup:
            option_id = self.combatants.index(option.combatant)
            part = self.segment(state, option_id)
            fired = [x + y for x, y in zip(fired, part.fired, strict=True)]
            if isinstance(part.end, _Terminal):
                r = part.end
                return dict(
                    winner=r.winner,
                    ended_by=r.ended_by,
                    turns=r.turns,
                    player_hp=r.hp,
                    fainted=list(range(1, r.fainted + 1)),
                    fired=fired,
                )
            state = part.end
        raise AssertionError("no terminal")

    def aggregate(self):
        pools, lengths = self.pools, [len(p) for p in self.pools]
        total = prod(lengths)
        ends, dist = Counter(), [0] * 4
        wins = losses = draws = turns = knocked = 0
        hp = 0.0
        slot_faints = [0] * 3
        # Species counts are outcome independent; win counts propagate back up
        # the DFS. A terminal prefix supplies every untouched suffix option.
        species_counts = [Counter(o.species for o in p) for p in pools]
        species_wins = [Counter() for _ in pools]
        metadata = winrate._Metadata()
        variants = set()
        prefix = []

        def visit(state, player_fired):
            nonlocal wins, losses, draws, turns, knocked, hp
            depth = state.slot
            subtree_wins = 0
            for option, option_id in zip(pools[depth], self.option_ids[depth], strict=True):
                prefix.append(option)
                part = self.segment(state, option_id)
                fired = player_fired or bool(part.fired[0])
                r = part.end
                if isinstance(r, _Boundary):
                    won_count = visit(r, fired)
                else:
                    if r.ended_by == "observation_limit":
                        raise ValueError(
                            "observation_limit: incomplete battle cannot enter estimates"
                        )
                    n = prod(lengths[depth + 1 :])
                    won = r.winner == "player"
                    won_count = n if won else 0
                    wins += won_count
                    losses += n if r.winner == "rocket" else 0
                    draws += n if r.winner is None else 0
                    outcome = "wins" if won else "draws" if r.winner is None else "losses"
                    ends[r.ended_by, outcome] += n
                    dist[r.fainted] += n
                    knocked += r.fainted * n
                    turns += r.turns * n
                    for i in range(r.fainted):
                        slot_faints[i] += n
                    # Repeated binary64 addition in precisely itertools.product order.
                    fraction = r.hp / self.player.hp
                    for _ in range(n):
                        hp += fraction
                    if won:
                        for i in range(depth + 1, 3):
                            scale = n // lengths[i]
                            for name, count in species_counts[i].items():
                                species_wins[i][name] += count * scale
                    # Metadata varies with resolved player charges and supplied
                    # Rocket charges, including untouched suffix reserves.
                    suffix = pools[depth + 1 :]
                    samples = [tuple(p[0] for p in suffix)]
                    uncharged = [tuple(o for o in p if not o.combatant.charged) for p in suffix]
                    if all(uncharged):
                        samples.append(tuple(p[0] for p in uncharged))
                    for i, pool in enumerate(suffix):
                        charged_option = next((o for o in pool if o.combatant.charged), None)
                        if charged_option is not None:
                            sample = list(samples[0])
                            sample[i] = charged_option
                            samples.append(tuple(sample))
                            break
                    for sample in samples:
                        lineup = (*prefix, *sample)
                        variant = fired, any(o.combatant.charged for o in lineup)
                        if variant in variants:
                            continue
                        result = simulate_rocket(
                            self.team,
                            tuple(o.combatant for o in lineup),
                            rank=self.rank,
                            battle_date=self.battle_date,
                            rules=self.rules,
                        )
                        metadata.add(winrate.battle_summary(result, self.team))
                        variants.add(variant)
                species_wins[depth][option.species] += won_count
                subtree_wins += won_count
                prefix.pop()
            return subtree_wins

        visit(self.initial, False)
        return {
            **metadata.output(),
            "lineups": total,
            "battles": total,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "win_rate": wins / total,
            "draw_rate": draws / total,
            **{
                f"{ending}_{outcome}": ends[ending, outcome]
                for ending in ("timeout", "knockout")
                for outcome in ("wins", "losses", "draws")
            },
            "mean_rocket_knocked_out": knocked / total,
            "lead_sweep_probability": dist[3] / total,
            "slots_swept": [
                dict(
                    player_slot=1,
                    mean=sum(k * n for k, n in enumerate(dist)) / total,
                    shares={str(k): dist[k] / total for k in range(4)},
                )
            ],
            "mean_player_hp_fraction_left": hp / total,
            "mean_turns": turns / total,
            "per_slot": [
                dict(
                    slot=i + 1,
                    knockout_share=slot_faints[i] / total,
                    species=[
                        dict(
                            species=name,
                            battles=n * (total // lengths[i]),
                            conditional_win_rate=species_wins[i][name]
                            / (n * (total // lengths[i])),
                        )
                        for name, n in sorted(species_counts[i].items())
                    ],
                )
                for i in range(3)
            ],
        }


def aggregate(team, pools, *, rank, battle_date, rules=DEFAULT_ROCKET_RULES):
    """Return exactly winrate.aggregate(team, winrate.trials(...)) for supported inputs.

    Prefixes follow itertools.product order, including repeated float additions.
    State and packet caches live for this call; the damage LRU is bounded.
    Unsupported inputs raise ValueError; callers should check supports first.
    """
    return _Engine(team, pools, rank=rank, battle_date=battle_date, rules=rules).aggregate()
