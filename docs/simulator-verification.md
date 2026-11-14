# Rocket simulator: verification ledger and acceptance fixtures

Written 2026-11-14, before any simulator code. The bar is that we must be sure of the formulas and the targets.
So every formula and constant the simulator depends on is listed here with its evidence, and real recorded
battles are collected as exact tests.

## Rules

- **Fixtures first:** the simulator must reproduce every fixture below exactly (hits to knock out, damage per
  hit, HP), before it ranks anything.
- **Labelling:** until it passes them, all output is labelled **unvalidated**. Any output that depends on an
  item graded below *measured-reproduced* carries that grade in the output.

**Evidence grades:**

- **official:** Niantic said it.
- **data-mined:** read from the game master.
- **measured-reproduced:** two or more independent measurements agree.
- **measured-once:** one measurement.
- **assumed:** no measurement.

Below *measured-reproduced* is flagged ⚑.

## Ledger

| # | Item | Source | Grade | Independent confirmations | What would falsify it |
|---|---|---|---|---|---|
| a | Damage = floor(0.5 × power × atk/def × STAB × effectiveness × 1.3 × …) + 1, float32 constants | [PvPoke DamageCalculator.js](https://github.com/pvpoke/pvpoke/blob/master/src/js/battle/DamageCalculator.js) (MIT); Bulbapedia *Damage* | measured-reproduced (Rocket) + data-mined constants | GamePress 2019; Venonic and AurumKodEXo 2023; our reproduction of fixtures F1, F4 and F5 | A hit off by 1 that isn't on a knife edge. F8's Zen Headbutt (raw 21.99) would test float precision once a recorded count exists. |
| b | Player CP multiplier (CPM) per level | Game master `PLAYER_LEVEL_SETTINGS`; half levels by square-root interpolation | data-mined | PvPoke's CPM table | A player CP mismatch (rare one-ULP float cases are reported in [1ub6a1h](https://www.reddit.com/r/TheSilphRoad/comments/1ub6a1h/)) |
| c | Rocket CP multiplier (rCPM) by trainer level: the old table (to Oct 2025) and the Dec 2025 table (trainer levels 8–80, 3-decimal float32) | Venonic [122pfk8](https://www.reddit.com/r/TheSilphRoad/comments/122pfk8/); Flyfunner [1puc05x](https://www.reddit.com/r/TheSilphRoad/comments/1puc05x/); not in the game master | measured-reproduced (from CP) | fugerappi [184iqov](https://www.reddit.com/r/TheSilphRoad/comments/184iqov/); Flyfunner [12ib623](https://www.reddit.com/r/TheSilphRoad/comments/12ib623/); eli5questions [1o7syt9](https://www.reddit.com/r/TheSilphRoad/comments/1o7syt9/); 23/23 published trainer-level-50 CPs and 13/13 trainer-level-70 CPs reproduce | A CP outside floor(…) for every float in the stated range |
| d | Rank: 1.0 grunt, 1.05 leader, 1.15 Giovanni | [2021 study](https://www2.pokebattler.com/articles/2021/06/21/cracking-the-rocket-cp-formula-2021-edition/) | measured-reproduced (from CP) | Leader and Giovanni CPs (AurumKodEXo, Pendergirl4). F8's Snorlax 285 HP is a published calculation, not a reading | A leader or Giovanni CP mismatch; a Giovanni hit count that doesn't fit ⚑ (none exist) |
| e | Rocket stats: HP floor(0.6 × (base + 15)), attack IV floor(2/3 × base + 25), defence IV 15; HP floored in battle | Venonic [122pfk8](https://www.reddit.com/r/TheSilphRoad/comments/122pfk8/) | measured-reproduced (before Oct 2025); CP only since ⚑ | 2021 packet capture (attack-IV rule, defence 15); NFL restatement ([1ub6a1h](https://www.reddit.com/r/TheSilphRoad/comments/1ub6a1h/)); fixtures F1, F2, F4, F5 | A post-2025 Yawn count that differs |
| f | 1.3× Trainer Battle bonus on both sides | Game master `COMBAT_SETTINGS` | data-mined + measured-reproduced | It resolved a 2023 damage mismatch; F1's recorded damage taken (4 / 11 / 8) and hit counts match | Rocket damage 1.3× lower than predicted |
| g | Shadow ×1.2 attack, ×0.8333333 defence, both sides | Game master `COMBAT_SETTINGS` | data-mined + measured-reproduced | Venonic 2023 (applies to Rocket Pokémon since late 2022); F1 (shadow player and shadow Rocket) | A non-shadow attacker matching only without the Rocket's defence penalty |
| h | STAB 1.2; type effectiveness 1.6, 0.625, 0.390625 | Game master | data-mined | PvPoke; Bulbapedia | — |
| i | Move power, energy, turns **at the date of the battle** | Game master `combatMove` + season notes ([official](https://pokemongo.com/news/go-battle-league-precious-paths)); move history (Flyfunner [1lu9w8w](https://www.reddit.com/r/TheSilphRoad/comments/1lu9w8w/)) | official / data-mined | PvPoke moves | Fixtures only reproduce with the powers in force then: Bullet Punch 6 in Dec 2022, Smack Down 12 and Razor Leaf 10 in Jan–Feb 2023 (today 7, 11, 9). The simulator needs a dated move table. |
| j | Turn rules since the 2026 rebuild: a fast move can land after a charged attack starts; simultaneous charged attacks both fire; charged attacks start next turn | [9db.jp](https://9db.jp/pokemongo/data/24341); cwizz1 Jan 2026; [official rebuild post](https://pokemongo.com/news/pvp-updates2026) (GO Battle League) | fast move landing: measured-reproduced; simultaneous charged: measured-once ⚑; next-turn start: assumed ⚑ | Bulbapedia still describes the old cancel rule (outdated) | A recorded charged attack on the turn a Rocket fast move lands |
| k | Rocket pauses: after a charged attack, a faint, your switch | [9db.jp](https://9db.jp/pokemongo/data/24341) table; cwizz1 [1vyspr1](https://www.reddit.com/r/TheSilphArena/comments/1vyspr1/) | after a charged attack, 7 turns: measured-reproduced; after a faint, 7: measured-reproduced; after your switch: conflicting (9 or 7) ⚑ | Changed in Dec 2025 (12 turns) and again by Sep 2026 | A frame count of a manual switch |
| l | When the Rocket side fires charged attacks, and their damage | none | assumed ⚑. A 2019 measurement put Rocket charged damage at about 0.5625× the formula: measured-once and outdated ⚑ | Practitioners assume "as soon as it has the energy" | A Rocket Pokémon holding energy past the cost; unshielded charged damage that isn't 1× (or 0.5625×) |
| m | Shields: grunts none; leaders and Giovanni the first two charged attacks | Bulbapedia *Team GO Rocket*; GO Hub | measured-reproduced (community; not official) | Community reports; F8's shielded Power-Up Punch 1 is a calculation | A grunt shielding; a third leader shield |
| n | Timer about 12 min, about 7 s added per charged attack; timeout decided by Pokémon left, then HP% | freezyefc [1q13cga](https://www.reddit.com/r/TheSilphRoad/comments/1q13cga/) (2 videos) | measured-once ⚑ | — | Time a stall battle to the 30-second warning |
| o | Stat stages (±4: 1.25 / 1.5 / 1.75 / 2; 0.8 / 0.667 / …) | Game master `COMBAT_STAT_STAGE_SETTINGS` | data-mined; unmeasured in Rocket ⚑ | F8's Force Palm 17 / 21 / 25 at +0 / +1 / +2 is a calculation; F5's debuffed rows are excluded | A recorded +1 Force Palm that isn't 21 |
| p | Your charged-attack mini-game: 0.25 / 0.5 / 0.75 / 1.0 | Game master `chargeScore*` | data-mined; assumed for Rocket ⚑ | — | Rocket damage from a deliberate "Nice" that isn't 0.5× |
| q | Mega and best-buddy effects in Rocket battles | PvPoke added a mega bonus in Aug 2026; a raid stat bug is reported | unresolved ⚑ | — | A fixture with a Mega attacker that only fits one way |

## Fixtures (real recorded outcomes)

All reproduce with the ledger above (our checks), unless noted. A number the source author *calculated*
(rather than read off the battle) reproducing under the same model proves nothing, so it is kept only as a
weak cross-check, never as an acceptance target. Each fixture record carries this `basis`
(`tests/fixtures/sim/README.md`).

| # | Source, date | rCPM regime | What was recorded | Inputs complete? | Our check |
|---|---|---|---|---|---|
| F1 | AurumKodEXo, [13puajs](https://www.reddit.com/r/TheSilphRoad/comments/13puajs/) + [z3qck5](https://www.reddit.com/r/TheSilphRoad/comments/z3qck5/), video 3 Dec 2022 | old, trainer level 50 | Shadow Metagross (level 43.5, 15/9/12, Bullet Punch) vs a Fairy grunt. **Recorded:** Metagross HP 163; damage taken: Tackle 4, Bite 11, Charge Beam 8; Snubbull still standing after 7 Bullet Punches; Kirlia knocked out in 6. **Calculated** by Venonic, not recorded: Bullet Punch 19 on Snubbull, 134 HP, 1 left after 7. | yes (move powers at the date) | **all match**, re-checked by hand |
| F2 | Venonic, [122pfk8](https://www.reddit.com/r/TheSilphRoad/comments/122pfk8/), Mar 2023 | old, 41 | Grunt Cyndaquil HP 100 | yes | match |
| F3 | AurumKodEXo, [184iqov](https://www.reddit.com/r/TheSilphRoad/comments/184iqov/), Nov 2023 | old, 50 | Shadow Metagross (level 46.5) kills Snubbull in 8, survives "with 1 HP" | partly | **model gives 2 HP**: open, 1 HP off |
| F4 | cwizz1, [10hihvd](https://www.reddit.com/r/TheSilphRoad/comments/10hihvd/), Jan 2023 | old, 50 | 28 Smack Down hit counts (Tyranitar, Rhyperior, Rampardos, Shadow Tyranitar vs Flying and Bug grunt slots 1–2) | yes | **27/28**; the miss (Ducklett vs Shadow Tyranitar) is a knife edge (raw 32.90 vs 33.02) |
| F5 | cwizz1, [10qgrga](https://www.reddit.com/r/TheSilphRoad/comments/10qgrga/), Feb 2023 | old, 50 | 6 Razor Leaf hit counts (Roserade vs Water and Ground grunts) | attack IV not stated (13–15 give the same) | 6/6 |
| F6 | cwizz1 videos, [13u4wnq](https://www.reddit.com/r/TheSilphRoad/comments/13u4wnq/), [13yprjp](https://www.reddit.com/r/TheSilphRoad/comments/13yprjp/), May–Jun 2023 | old, 50 | Mud-Slap and Counter hit counts | IVs not given | not yet checked |
| F7 | RestorerForer, [1uwoshu](https://www.reddit.com/r/TheSilphRoad/comments/1uwoshu/), video 14 Jul 2026 | **new, 76** | Grunt Nidorina: Mega Mewtwo Y 3 Confusions, Shadow Mewtwo 4 | partly (defence and HP IVs, buddy status) | match, but weak: also passes on the old table |
| F8 | cwizz1, [1trpag8](https://www.reddit.com/r/TheSilphRoad/comments/1trpag8/), video 30 May 2026 | **new**, trainer level read from video | **Leader** Cliff's Snorlax: HP 285; Force Palm 17 / 21 / 25 at +0 / +1 / +2; shielded Power-Up Punch 1. **All five are the author's calculations at trainer level 80**, not readings | a hit count would need reading off the linked recordings | calculations reproduce, which proves nothing; weak |
| F9 | cwizz1, Mar 2026 | new | Kartana 3 Razor Leafs vs Magikarp | trainer level missing | match (weak) |
| F10 | GamePress, Nov 2019 | **2019 regime (outdated)** | Yawn HP: Duskull 61, Abra 67, Ralts 70, Zubat 84, Shuppet 88, Larvitar 94 | missing attacker details | historical only |

**Totals:**

- **Before Oct 2025:** 44 recorded or measured numbers in `tests/fixtures/sim/battles.json` (F1 6, F2 1, F4 31,
  F5 6) reproduce, plus three expected failures (F3's 1 HP claim, F4's knife edge). F1's three calculated values
  are weak cross-checks only.
- **Since Oct 2025:** **no strong battle fixture.** F7 is recorded but does not tell the rCPM tables apart; F8 is
  calculated; F9 is inferred. The current regime is checked by CP readings only.
- **CP readings:** about 160 or more before Oct 2025 (comments, spreadsheets), plus 13 paired readings and the NFL collection sheet after.

**Gaps:**

- No Giovanni hit counts.
- One leader case.
- No recorded damage, HP or discriminating hit count since the Oct 2025 change.
- No measurement of Rocket charged-attack damage since 2019, and none of when it fires.
- Nothing numeric on simultaneous charged attacks.
- No fixtures below trainer level 41, none with purified attackers or Rocket-side stat changes.

## Acceptance gate

1. **Fixture suite:** the recorded and measured records of F1, F2, F4 and F5 become exact tests (with the move
   powers at each date), along with the CP readings at trainer levels 50 and 70. Calculated and inferred records
   (F1's three, F8, F9) and F7 run as weak cross-checks that are reported but do not gate. Expected-to-fail cases (F3, F4's knife edge) are kept and
   marked, not silently dropped.
2. **Unvalidated until passing:** the simulator prints rankings only once the suite passes. Before that, every
   output says "unvalidated".
3. **Grades in the output:** any number that depends on an ⚑ item carries its grade. For example, a win rate
   against a leader depends on (l) when the Rocket side fires its charged attacks, so it is labelled "assumed".

## What can honestly be claimed

**"Pretty dang sure" is supported for:**

- damage per hit;
- Rocket Pokémon HP, attack and defence for the pre-Oct-2025 table (by battle fixtures) and by CP only since;
- fast-move hits to knock out;
- grunt shields and leader shields.

These are measured and reproduced, and the simulator can be held to them exactly.

**Not supported yet:**

- **When the Rocket side fires its charged attacks, and how hard they hit:** no measurement exists.
- **Pause after your own switch:** sources conflict.
- **Simultaneous charged attacks:** measured once.
- **Anything about Giovanni beyond CP:** no hit counts exist.
- **Post-Oct-2025 damage and HP:** checked only by CP; no recorded battle number discriminates the new table.
  Check 1 below is the cheapest fix.

So win rates and "slots swept" (which depend on the Rocket side's charged attacks and on the pauses) can be shown
only as labelled estimates until the in-game checks below are done.

## Minimum in-game checks

Each takes a few battles. Screen-record if possible; one turn = 0.5 s.

1. **Exact HP since the level-80 change** (lifts e):
   - **Setup:** a Yawn Snorlax (Yawn always does 1 damage) against a grunt's slot-1 Pokémon, with shields and
     potions.
   - **Count:** Yawns until it faints.
   - **Record:** your trainer level, the species, the count. 1–2 battles.
2. **When the Rocket side fires, and how hard** (lifts l):
   - **Setup:** a bulky lead with known IVs that resists the enemy's fast move; use no charged attacks of your
     own, so no pause interferes.
   - **Count:** the enemy's fast moves, to work out when its energy first reaches its charged move's cost.
   - **Record:** the turn it actually fires, and the damage taken from an unshielded charged attack. 3 or more
     battles.
3. **Pauses** (lifts k): with a 1-turn fast move (Water Gun, Lock-On), count your fast moves from (a) your
   charged attack, (b) your manual switch, (c) knocking out their Pokémon, until the enemy's first move. 5 of
   each, about 3 grunts.
4. **Leader and Giovanni hit counts** (lifts d):
   - **Setup:** at a stated trainer level, with the attacker's level and all three IVs noted.
   - **Count:** fast moves to knock out Giovanni's slot-1 Persian and one leader's slot-1 Pokémon, with no
     buffs. 2 battles.
5. **Optional:**
   - one deliberate "Nice" charged attack against a grunt, noting the damage (lifts p);
   - a stall battle timed to the 30-second warning (lifts n).
