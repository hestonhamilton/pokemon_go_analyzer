"""Hand arithmetic checks model aggregation, never new game acceptance targets."""

from dataclasses import replace
from itertools import product
from types import SimpleNamespace

import pytest

from pogo_analyzer.sim.battle import Combatant
from pogo_analyzer.sim.calculator import Move, calculate_matchup
from pogo_analyzer.sim.rocket import Evidence, RocketRules, simulate_rocket
from pogo_analyzer.sim.winrate import (
    Option,
    battle_summary,
    estimate,
    grid,
    lineups,
    moveset_ids,
    player_combatant,
    sort_results,
)

FAST = Move("F", "normal", 2, 1)
CHARGE = Move("C", "normal", 4, 1, energy=50)
MEMBER = Combatant(100, 100, 100, ("normal",), FAST, (CHARGE,))
TEAM = (MEMBER, MEMBER)
POOLS = tuple(
    tuple(Option(s, MEMBER) for s in names) for names in (("A", "B"), ("C",), ("D", "E", "F"))
)


def fake_result(winner, ended_by, turns, hp, credits, *, double=False, flag=False):
    timeline = tuple(
        SimpleNamespace(
            active_slots=(player, rocket),
            core=SimpleNamespace(hp=(0 if double else 10, 0)),
        )
        for rocket, player in enumerate(credits, 1)
    )
    return SimpleNamespace(
        winner=winner,
        ended_by=ended_by,
        turns_elapsed=turns,
        hp=(hp, (0, 0, 0)),
        timeline=timeline,
        battle_date="2026-11-14",
        era="mar-2026",
        rules=RocketRules(),
        ledger_rows=("a", "l") if flag else ("a",),
        flags=("unverified",) if flag else (),
        evidence=(Evidence("l" if flag else "a", "assumed", "test", "synthetic"),),
        interpretations=("synthetic",),
    )


def test_hand_aggregation():
    # Six equally weighted lineups in product order, not equally weighted species:
    # ACD: KO win, lead 3, HP fractions 1,1; ACE: timeout win, credits 1,1, HP .5,1;
    # ACF: KO draw, credits 1,2 (final same-turn double KO), HP 0,0;
    # BCD: KO loss, member 2 knocks out slot 1; BCE: timeout loss, no KO, HP 0,.5;
    # BCF: timeout draw, no KO, HP .25,.25. Turns 10,20,30,40,50,60.
    outcomes = iter(
        [
            fake_result("player", "knockout", 10, (100, 100), (1, 1, 1)),
            fake_result("player", "timeout", 20, (50, 100), (1, 2)),
            fake_result(None, "knockout", 30, (0, 0), (1, 2, 2), double=True, flag=True),
            fake_result("rocket", "knockout", 40, (0, 0), (2,)),
            fake_result("rocket", "timeout", 50, (0, 50), ()),
            fake_result(None, "timeout", 60, (25, 25), ()),
        ]
    )
    seen = []
    rules = RocketRules()

    def battle(team, rocket, **kwargs):
        assert team == TEAM and len(rocket) == 3
        assert kwargs == dict(rank="leader", battle_date="2026-11-14", rules=rules)
        seen.append(rocket)
        return next(outcomes)

    row = estimate(TEAM, POOLS, rank="leader", battle_date="2026-11-14", rules=rules, battle=battle)
    assert len(seen) == row["lineups"] == row["battles"] == 6
    assert (row["wins"], row["losses"], row["draws"]) == (2, 2, 2)
    assert row["win_rate"] == row["draw_rate"] == 1 / 3
    for ending, outcome in product(("knockout", "timeout"), ("wins", "losses", "draws")):
        assert row[f"{ending}_{outcome}"] == 1
    assert row["mean_rocket_knocked_out"] == 1.5
    assert row["lead_sweep_probability"] == 1 / 6
    assert row["mean_player_hp_fraction_left"] == 0.375
    assert row["mean_turns"] == 35
    assert row["slots_swept"] == [
        {"player_slot": 1, "mean": 5 / 6, "shares": {"0": 0.5, "1": 1 / 3, "2": 0, "3": 1 / 6}},
        {"player_slot": 2, "mean": 4 / 6, "shares": {"0": 0.5, "1": 1 / 3, "2": 1 / 6, "3": 0}},
    ]
    assert [s["knockout_share"] for s in row["per_slot"]] == [4 / 6, 3 / 6, 2 / 6]
    conditional = {
        (s["slot"], r["species"]): r["conditional_win_rate"]
        for s in row["per_slot"]
        for r in s["species"]
    }
    assert conditional == {
        (1, "A"): 2 / 3,
        (1, "B"): 0,
        (2, "C"): 1 / 3,
        (3, "D"): 0.5,
        (3, "E"): 0.5,
        (3, "F"): 0,
    }
    assert row["flags"] == ["unverified"] and row["ledger_rows"] == ["a", "l"]
    assert len(row["evidence"]) == 2  # distinct tuples, not one copy per battle
    assert row["rules_grade"] == "unverified"


def test_sort_order():
    rows = [
        dict(id=name, win_rate=w, mean_player_hp_fraction_left=h, mean_turns=t)
        for name, w, h, t in (
            ("slow", 0.5, 0.8, 30),
            ("win", 0.6, 0, 100),
            ("hurt", 0.5, 0.2, 1),
            ("fast", 0.5, 0.8, 20),
        )
    ]
    # Owner ruling: fewest turns first by default; HP left first is the alternative order.
    assert [r["id"] for r in sort_results(rows)] == ["win", "hurt", "fast", "slow"]
    assert [r["id"] for r in sort_results(rows, "hp")] == ["win", "fast", "slow", "hurt"]


def test_enumeration_and_filter():
    assert len(list(lineups(POOLS))) == 2 * 1 * 3
    species = dict(
        fastMoves=["A", "B"], chargedMoves=["C", "D", "E"], eliteMoves=["B"], legacyMoves=["D"]
    )
    assert len(moveset_ids(species)) == 6
    assert moveset_ids(species, exclude_elite_legacy=True) == (("A", "C"), ("A", "E"))
    with pytest.raises(ValueError, match="empty.*--exclude-elite-legacy"):
        moveset_ids(dict(species, eliteMoves=["A", "B"]), exclude_elite_legacy=True)
    with pytest.raises(ValueError, match="empty"):
        moveset_ids(dict(species, chargedMoves=[]))
    with pytest.raises(ValueError, match="three nonempty"):
        list(lineups((POOLS[0], (), POOLS[2])))


def test_observation_limit_is_an_error():
    with pytest.raises(ValueError, match="observation_limit"):
        estimate(
            TEAM,
            POOLS,
            rank="grunt",
            battle_date="2026-11-14",
            battle=lambda *a, **k: fake_result(None, "observation_limit", 1, (100, 100), ()),
        )


def test_real_three_vs_three_wiring():
    # Each player fast hit does floor(.5*2*100/1*1.2*1.3/(5/6))+1 > 1 HP.
    # Opponent power zero still does 1. One Rocket faints each turn; faint pauses
    # prevent subsequent new Rocket inputs. This is a synthetic trace, not a target.
    own = replace(MEMBER, defence=10000)
    enemy = Combatant(1, 1, 1, ("normal",), Move("zero", "normal", 0, 1), (CHARGE,))
    pools = tuple((Option(str(i), enemy),) for i in range(3))
    rules = RocketRules(rocket_shields=False)
    direct = simulate_rocket(
        (own,) * 3, (enemy,) * 3, rank="leader", battle_date="2026-03-12", rules=rules
    )
    row = estimate((own,) * 3, pools, rank="leader", battle_date="2026-03-12", rules=rules)
    assert row["win_rate"] == row["lead_sweep_probability"] == 1
    assert row["mean_turns"] == direct.turns_elapsed == 3
    assert row["mean_rocket_knocked_out"] == 3
    assert row["battle_date"] == "2026-03-12" and row["era"] == direct.era
    assert row["rules"]["rocket_shields"] is False
    assert row["slots_swept"][0]["shares"]["3"] == 1
    assert row["mean_player_hp_fraction_left"] == sum(h / own.hp for h in direct.hp[0]) / 3


@pytest.mark.parametrize("form", ["normal", "shadow", "purified"])
def test_player_stats_follow_calculator(form):
    attacker = dict(
        speciesId="synthetic",
        dex=292,
        baseStats={"atk": 200, "def": 100, "hp": 1},
        ivs={"atk": 15, "def": 10, "hp": 15},
        level=40,
        types=["normal"],
        form=form,
    )
    defender = dict(
        speciesId="other", baseStats={"atk": 100, "def": 100, "hp": 100}, types=["normal"]
    )
    row = calculate_matchup(
        attacker,
        defender,
        FAST,
        (CHARGE,),
        FAST,
        (CHARGE,),
        trainer_level=50,
        rank="grunt",
        table="dec-2025",
    )
    combatant = player_combatant(attacker, FAST, (CHARGE,))
    assert (combatant.attack, combatant.defence, combatant.hp) == (
        row["attacker_attack"],
        row["attacker_defence"],
        row["attacker_hp"],
    )
    assert combatant.hp == 10  # dex passthrough matters for Shedinja
    assert combatant.shadow is (form == "shadow")
    assert combatant.energy == 0


def test_grid_is_fresh_and_uniform():
    enemy = replace(MEMBER, hp=1)
    pools = ((Option("tiny", enemy), Option("large", MEMBER)), (), ())
    rows, groups = grid(TEAM, pools, rank="grunt", battle_date="2026-11-14", slot=1)
    assert len(rows) == 4 and len(groups) == 2
    for i, member in enumerate(TEAM, 1):
        matching = [r for r in rows if r["player_slot"] == i]
        for r, option in zip(matching, pools[0], strict=True):
            result = simulate_rocket(
                (member,), (option.combatant,), rank="grunt", battle_date="2026-11-14"
            )
            assert (r["winner"], r["ended_by"], r["turns"]) == (
                result.winner,
                result.ended_by,
                result.turns_elapsed,
            )
        assert groups[i - 1]["win_rate"] == sum(r["winner"] == "player" for r in matching) / 2
        assert groups[i - 1]["draws"] == sum(r["winner"] is None for r in matching)
        assert groups[i - 1]["battles"] == groups[i - 1]["lineups"] == 2
    assert all(
        "ignores carried-over shields and HP between slots" in r["grid_limitation"]
        for r in rows + groups
    )


def test_no_unverified_flag_keeps_rules_estimate():
    row = estimate(
        TEAM,
        POOLS,
        rank="grunt",
        battle_date="2026-11-14",
        battle=lambda *a, **k: fake_result("player", "knockout", 1, (100, 100), ()),
    )
    assert row["rules_grade"] == "estimate"


def test_double_ko_credit_precedes_replacement():
    result = fake_result(None, "knockout", 1, (0, 0), (2,), double=True)
    assert battle_summary(result, TEAM)["credited"] == [0, 1]
