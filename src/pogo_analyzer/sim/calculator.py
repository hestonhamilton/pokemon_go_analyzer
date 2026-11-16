"""Pure conditional matchup arithmetic. No battle clock, move selection, or I/O.

Trainer Battle move stats and cooldown / 500 follow verification ledger i and f.
Rocket shadow modifiers follow ledger g and are applied only by damage.py.
"""

import math
from dataclasses import dataclass

from .damage import calculate_damage, hits_to_ko
from .stats import RANKS, player_cpm, player_stats, rcpm, rocket_stats


@dataclass(frozen=True)
class Move:
    id: str
    type: str
    power: float
    turns: float
    energy: int = 0
    energy_gain: int = 0
    self_stages: tuple[int, int] = (0, 0)
    opponent_stages: tuple[int, int] = (0, 0)
    stage_chance: float = 1.0

    @classmethod
    def from_pvpoke(cls, item):
        """Parse effects from PvPoke GameMaster.js 874-881, commit
        426e5e9f39d3a027849698fb2f5edd9df6056cbf.
        """
        # Ledger i: Trainer Battle metadata, not raid move stats.
        self_stages = opponent_stages = (0, 0)
        chance = 1.0
        if item.get("buffs"):

            def stages(key):
                value = item.get(key)
                if (
                    not isinstance(value, (list, tuple))
                    or len(value) != 2
                    or any(type(delta) is not int or not -4 <= delta <= 4 for delta in value)
                ):
                    raise ValueError(f"{item['moveId']}: invalid {key}")
                return tuple(value)

            target = item.get("buffTarget")
            if target == "self":
                self_stages = stages("buffs")
            elif target == "opponent":
                opponent_stages = stages("buffs")
            elif target == "both":
                self_stages = stages("buffsSelf")
                opponent_stages = stages("buffsOpponent")
            else:
                raise ValueError(f"{item['moveId']}: invalid buffTarget")
            try:
                chance = float(item["buffApplyChance"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{item['moveId']}: invalid buffApplyChance") from exc
            if not 0 < chance <= 1:
                raise ValueError(f"{item['moveId']}: invalid buffApplyChance")
        return cls(
            item["moveId"],
            item["type"],
            item["power"],
            item["cooldown"] / 500,
            item["energy"],
            item["energyGain"],
            self_stages,
            opponent_stages,
            chance,
        )


def move_damage(move, attack, defence, attacker_types, defender_types, **options):
    """Full, unshielded damage unless a historical fixture explicitly says shielded."""
    return calculate_damage(
        move.power,
        attack,
        defence,
        move.type,
        attacker_types,
        defender_types,
        charged=move.energy > 0,
        **options,
    )


def fast_metrics(damage, hp, turns):
    """Conditional fast-only arithmetic; KO occurs on the last counted hit."""
    if not math.isfinite(turns) or turns <= 0:
        raise ValueError("fast move turns must be positive")
    hits = hits_to_ko(damage, hp)
    return {
        "damage": damage,
        "damage_per_turn": damage / turns,
        "hits": hits,
        "turns": hits * turns,
    }


def energy_hits(cost, gain):
    """From zero energy, ignoring battle behaviour; None means unreachable."""
    if cost <= 0 or gain < 0:
        raise ValueError("charged cost must be positive and fast energy nonnegative")
    return math.ceil(cost / gain) if gain else None


def calculate_matchup(
    attacker,
    defender,
    fast,
    charged,
    rocket_fast,
    rocket_charged,
    *,
    trainer_level,
    rank,
    table,
):
    """One attacker configuration against one species and hypothetical Rocket fast move.

    Species entries are PvPoke records. Attacker adds level, ivs, form. Moves are
    Move objects. Stat totals are before shadow modifiers, exactly as in S1/S2.
    """
    ps = player_stats(
        attacker["baseStats"],
        attacker["ivs"],
        attacker["level"],
        form=attacker.get("form", "normal"),
        # PvPoke species records carry dex; Shedinja (292) then gets its 10 HP.
        dex=attacker.get("dex"),
    )
    rs = rocket_stats(defender["baseStats"], trainer_level, rank, table)
    out = dict(attacker_shadow=ps.form == "shadow", defender_shadow=True)
    incoming = dict(attacker_shadow=True, defender_shadow=ps.form == "shadow")

    def dealt(move):
        return move_damage(
            move, ps.attack, rs.defence, attacker["types"], defender["types"], **out
        ).damage

    def taken(move):
        return move_damage(
            move, rs.attack, ps.defence, defender["types"], attacker["types"], **incoming
        ).damage

    attack = fast_metrics(dealt(fast), rs.hp, fast.turns)
    defence = fast_metrics(taken(rocket_fast), ps.hp, rocket_fast.turns)
    return {
        "attacker": attacker["speciesId"],
        "level": attacker["level"],
        "ivs": attacker["ivs"],
        "form": ps.form,
        "defender": defender["speciesId"],
        "fast_move": fast.id,
        "rocket_fast_move": rocket_fast.id,
        "fast_damage": attack["damage"],
        "fast_damage_per_turn": attack["damage_per_turn"],
        "fast_hits_to_ko": attack["hits"],
        "fast_turns_to_ko": attack["turns"],
        "charged": [
            {
                "move": m.id,
                "damage": dealt(m),
                "energy_cost": m.energy,
                "fast_moves_to_energy": energy_hits(m.energy, fast.energy_gain),
            }
            for m in charged
        ],
        "rocket_fast_damage": defence["damage"],
        "rocket_fast_damage_per_turn": defence["damage_per_turn"],
        "ko_on_incoming_hit": defence["hits"],
        "turns_survived": defence["turns"],
        "rocket_charged": [{"move": m.id, "damage": taken(m)} for m in rocket_charged],
        "attacker_attack": ps.attack,
        "attacker_defence": ps.defence,
        "attacker_hp": ps.hp,
        "rocket_attack": rs.attack,
        "rocket_defence": rs.defence,
        "rocket_hp": rs.hp,
        "rocket_cp": rs.cp,
        "rank": rank,
        "rank_multiplier": RANKS[rank],
        "rcpm_table": table,
        "rocket_cpm": rcpm(trainer_level, table),
        "trainer_level": trainer_level,
    }


class BattlePredictor:
    """Shared S2 predictions using dated inputs, without inventing unknown IVs.

    Sparse move snapshots require an exact date. Never carry forward or use today.
    This adapter supports partial fixture inputs independently of the complete CLI
    inputs. All damage goes through the calculator's move_damage function.
    """

    def __init__(self, species, moves):
        self.species = species
        self.moves = moves

    def dated_move(self, move_id, date):
        matches = [m for m in self.moves[move_id] if m["as_of"] == date]
        if len(matches) != 1:
            raise ValueError(f"no unique exact-date move snapshot: {move_id} on {date}")
        return matches[0]

    def move(self, move_id, date):
        m = self.dated_move(move_id, date)
        return Move(move_id, m["type"], m["power"], m["turns"], m["energy"], m["energy_gain"])

    def rocket(self, row, table, trainer_level=None):
        r = row["rocket"]
        return rocket_stats(
            self.species[r["species"]]["baseStats"],
            row["trainer_level"] if trainer_level is None else trainer_level,
            r["rank"],
            table,
        )

    def dealt(self, row, table, *, attack_iv=None, trainer_level=None, level=None, mega_rule=False):
        p, r = row["player"], row["rocket"]
        move = self.move(row["observed"].get("move", p["fast_move"]), row["battle_date"])
        iv = p["ivs"]["atk"] if attack_iv is None else attack_iv
        if iv is None:
            raise ValueError("attack IV missing: sweep explicitly")
        attack = (self.species[p["species"]]["baseStats"]["atk"] + iv) * player_cpm(
            p["level"] if level is None else level
        )
        return move_damage(
            move,
            attack,
            self.rocket(row, table, trainer_level).defence,
            self.species[p["species"]]["types"],
            self.species[r["species"]]["types"],
            attacker_shadow=p["form"] == "shadow",
            defender_shadow=True,
            attack_stage=p["stat_stage"]["atk"],
            shielded=row["observed"].get("shielded", False),
            attacker_mega=p["form"] == "mega" and mega_rule,
            # Pinned gamemaster: none of the fixture moves has isMegaMove.
            is_mega_move=False,
            mega_level=p.get("mega_level", 3),
        )

    def iv_counts(self, row, table, trainer_level=None):
        hp = self.rocket(row, table, trainer_level).hp
        return {
            iv: hits_to_ko(
                self.dealt(row, table, attack_iv=iv, trainer_level=trainer_level).damage, hp
            )
            for iv in range(16)
        }

    def predict(self, row, table):
        obs, p, r = row["observed"], row["player"], row["rocket"]
        kind = obs["kind"]
        rs = self.rocket(row, table)
        if kind == "rocket_hp":
            return rs.hp
        if kind == "player_hp":
            return player_stats(self.species[p["species"]]["baseStats"], p["ivs"], p["level"]).hp
        if kind == "damage_per_hit_taken":
            move = self.move(obs["move"], row["battle_date"])
            defence = (self.species[p["species"]]["baseStats"]["def"] + p["ivs"]["def"]) * (
                player_cpm(p["level"])
            )
            return move_damage(
                move,
                rs.attack,
                defence,
                self.species[r["species"]]["types"],
                self.species[p["species"]]["types"],
                attacker_shadow=True,
                defender_shadow=p["form"] == "shadow",
                defence_stage=p["stat_stage"]["def"],
            ).damage
        if row["fixture"] == "F5":
            return self.iv_counts(row, table)
        damage = self.dealt(row, table).damage
        if kind == "damage_per_hit_dealt":
            return damage
        if kind == "hits_to_ko":
            return hits_to_ko(damage, rs.hp)
        if kind == "survives_hits":
            return damage * obs["value"] < rs.hp
        if kind == "remaining_hp_after" and obs["subject"] == "rocket":
            return rs.hp - damage * obs["hits"]
        raise ValueError(f"requires the turn loop: {row['id']}")


def matches(row, prediction):
    if row["fixture"] == "F5":
        return all(prediction[iv] == row["observed"]["value"] for iv in (13, 14, 15))
    if row["observed"]["kind"] == "survives_hits":
        return prediction is True
    return prediction == row["observed"]["value"]
