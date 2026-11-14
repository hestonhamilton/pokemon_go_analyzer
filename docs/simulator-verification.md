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
| c | Rocket CP multiplier (rCPM) by trainer level: the old table (to Oct 2025) and the Dec 2025 table (trainer levels 8–80, 3-decimal float32) | Venonic [122pfk8](https://www.reddit.com/r/TheSilphRoad/comments/122pfk8/); Flyfunner [1puc05x](https://www.reddit.com/r/TheSilphRoad/comments/1puc05x/); not in the game master | measured-reproduced (from CP) | fugerappi [184iqov](https://www.reddit.com/r/TheSilphRoad/comments/184iqov/); Flyfunner [12ib623](https://www.reddit.com/r/TheSilphRoad/comments/12ib623/); eli5questions [1o7syt9](https://www.reddit.com/r/TheSilphRoad/comments/1o7syt9/); 23/23 published trainer-level-50 CPs and 13/13 trainer-level-70 CPs reproduce. The rCPM values were themselves measured from CP readings, some of them in our corpus (Venonic credits AurumKodEXo and Pendergirl4). So these matches confirm the formula's shape across about 150 species with one value per level; they do not confirm each rCPM value independently | A CP outside floor(…) for every float in the stated range |
| d | Rank: 1.0 grunt, 1.05 leader, 1.15 Giovanni | [2021 study](https://www2.pokebattler.com/articles/2021/06/21/cracking-the-rocket-cp-formula-2021-edition/) | measured-reproduced (from CP) | Leader and Giovanni CPs (AurumKodEXo, Pendergirl4). F8's Snorlax 285 HP is a published calculation, not a reading | A leader or Giovanni CP mismatch; a Giovanni hit count that doesn't fit ⚑ (none exist) |
| e | Rocket stats: HP floor(0.6 × (base + 15)), attack IV floor(2/3 × base + 25), defence IV 15; HP floored in battle | Venonic [122pfk8](https://www.reddit.com/r/TheSilphRoad/comments/122pfk8/) | measured-reproduced (before Oct 2025); CP only since ⚑ | 2021 packet capture (attack-IV rule, defence 15); NFL restatement ([1ub6a1h](https://www.reddit.com/r/TheSilphRoad/comments/1ub6a1h/)); fixtures F1, F2, F4, F5 | A post-2025 Yawn count that differs |
| f | 1.3× Trainer Battle bonus on both sides | Game master `COMBAT_SETTINGS` | data-mined + measured-reproduced | It resolved a 2023 damage mismatch; F1's recorded damage taken (4 / 11 / 8) and hit counts match | Rocket damage 1.3× lower than predicted |
| g | Shadow ×1.2 attack, ×0.8333333 defence, both sides | Game master `COMBAT_SETTINGS` | data-mined + measured-reproduced | Venonic 2023 (applies to Rocket Pokémon since late 2022); F1 (shadow player and shadow Rocket) | A non-shadow attacker matching only without the Rocket's defence penalty |
| h | STAB 1.2; type effectiveness 1.6, 0.625, 0.390625 | Game master | data-mined | PvPoke; Bulbapedia | — |
| i | Move power, energy, turns **at the date of the battle** | Game master `combatMove` + season notes ([official](https://pokemongo.com/news/go-battle-league-precious-paths)); move history (Flyfunner [1lu9w8w](https://www.reddit.com/r/TheSilphRoad/comments/1lu9w8w/)) | official / data-mined | PvPoke moves | Fixtures only reproduce with the powers in force then: Bullet Punch 6 in Dec 2022, Smack Down 12 and Razor Leaf 10 in Jan–Feb 2023 (today 7, 11, 9). The simulator needs a dated move table. |
| j | Turn rules since the 2026 rebuild: a fast move can land after a charged attack starts; simultaneous charged attacks both fire; charged attacks start next turn | [9db.jp](https://9db.jp/pokemongo/data/24341); cwizz1 Jan 2026; [official rebuild post](https://pokemongo.com/news/pvp-updates2026) (GO Battle League) | fast move landing: measured-reproduced; simultaneous charged: measured-once ⚑; next-turn start: assumed ⚑ | Bulbapedia still describes the old cancel rule (outdated) | A recorded charged attack on the turn a Rocket fast move lands |
| k | Rocket pauses: after a charged attack, a faint, your switch | [9db.jp](https://9db.jp/pokemongo/data/24341) table; cwizz1 [1vyspr1](https://www.reddit.com/r/TheSilphArena/comments/1vyspr1/) | since Mar 2026: after a charged attack, 7 turns, measured-reproduced; after a faint, 7, measured-reproduced; after your switch, conflicting (9 or 7). Older eras: 9db alone (old charged 5 conflicts with one player's recalled 4). Trigger, either side's charged attack: owner observation, agrees with cwizz1; not measured. Either side's faint: owner reading; not measured. The pause adds to PvPoke's post-charge turn: practitioner-reproduced (2 accounts), not measured ⚑ | Changed about 10 Dec 2025 (12 turns) and again about 12 Mar 2026 | A frame count of a manual switch; a pause after the Rocket's own charged attack |
| l | When the Rocket side fires charged attacks, and their damage | none | assumed ⚑. A 2019 measurement put Rocket charged damage at about 0.5625× the formula: measured-once and outdated ⚑ | Practitioners assume "as soon as it has the energy" | A Rocket Pokémon holding energy past the cost; unshielded charged damage that isn't 1× (or 0.5625×) |
| m | Shields: grunts none; leaders and Giovanni the first two charged attacks | Bulbapedia *Team GO Rocket*; GO Hub | observed in play (consistent community reports; not measured or official) ⚑ | Community reports; F8's shielded Power-Up Punch 1 is a calculation | A grunt shielding; a third leader shield |
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
| F3 | AurumKodEXo, [184iqov](https://www.reddit.com/r/TheSilphRoad/comments/184iqov/), Nov 2023 | old, 50 | Shadow Metagross (level 46.5, 15/9/12) as the lead survives Bite Snubbull "with 1 HP" (recorded). The 8 Bullet Punches are the author's expectation (calculated) | yes for the lead matchup; turn order needed | **our hand calculation gives 2 HP**: open discrepancy, 1 HP off |
| F4 | cwizz1, [10hihvd](https://www.reddit.com/r/TheSilphRoad/comments/10hihvd/), Jan 2023 | old, 50 | 32 Smack Down hit counts (Tyranitar, Rhyperior, Rampardos, Shadow Tyranitar vs 8 Flying and Bug grunt Pokémon, slots 1–2) | yes | **31/32**; the miss (Ducklett vs Shadow Tyranitar, recorded 4) is an open discrepancy: our calculation gives raw 32.90 at attack IV 14, about 0.1 short of the next damage point |
| F5 | cwizz1, [10qgrga](https://www.reddit.com/r/TheSilphRoad/comments/10qgrga/), Feb 2023 | old, 50 | 6 Razor Leaf hit counts (Roserade vs Water and Ground grunts) | attack IV not stated (13–15 give the same) | 6/6 |
| F6 | cwizz1 videos, [13u4wnq](https://www.reddit.com/r/TheSilphRoad/comments/13u4wnq/), [13yprjp](https://www.reddit.com/r/TheSilphRoad/comments/13yprjp/), May–Jun 2023 | old, 50 | Mud-Slap and Counter hit counts | IVs not given | not yet checked |
| F7 | RestorerForer, [1uwoshu](https://www.reddit.com/r/TheSilphRoad/comments/1uwoshu/), video 14 Jul 2026 | **new, 76** | Grunt Nidorina: Mega Mewtwo Y 3 Confusions, Shadow Mewtwo 4 | partly (defence and HP IVs, buddy status) | match, but weak: also passes on the old table |
| F8 | cwizz1, [1trpag8](https://www.reddit.com/r/TheSilphRoad/comments/1trpag8/), video 30 May 2026 | **new**, trainer level read from video | **Leader** Cliff's Snorlax: HP 285; Force Palm 17 / 21 / 25 at +0 / +1 / +2; shielded Power-Up Punch 1. **All five are the author's calculations at trainer level 80**, not readings | a hit count would need reading off the linked recordings | calculations reproduce, which proves nothing; weak |
| F9 | cwizz1, Mar 2026 | new | Kartana 3 Razor Leafs vs Magikarp | trainer level missing | match (weak) |
| F10 | GamePress, Nov 2019 | **2019 regime (outdated)** | Yawn HP: Duskull 61, Abra 67, Ralts 70, Zubat 84, Shuppet 88, Larvitar 94 | missing attacker details | historical only |

**Totals:**

- **Before Oct 2025:** 44 recorded or measured numbers in `tests/fixtures/sim/battles.json` (F1 6, F2 1, F4 31,
  F5 6) reproduce, plus two open discrepancies (F3's 1 HP survival, F4's Ducklett cell). Calculated values
  (F1's three, F3's 8 hits, F8) are weak cross-checks only.
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
   (F1's three, F3's 8 hits, F8, F9) and F7 run as weak cross-checks that are reported but do not gate. A recorded
   value our model misses (F3's 1 HP, F4's Ducklett cell) is never downgraded to an expected failure: it stays an
   open discrepancy that every run reports. CP readings with an unstated rank, or that conflict, are weak.
2. **Unvalidated until passing:** the simulator prints rankings only once the suite passes. Before that, every
   output says "unvalidated".
3. **Grades in the output:** any number that depends on an ⚑ item carries its grade. For example, a win rate
   against a leader depends on (l) when the Rocket side fires its charged attacks, so it is labelled "assumed".

### Stats results

Offline stats are implemented. No constants were fitted. Mismatches keep strict xfail tests; the acceptance
gate is still open. Counts are over all 171 CP readings. Expected fail and Unexplained partition mismatches of
target readings. Weak readings (the disputed and unstated-rank five) are reported, never gating. Unavailable
levels are separate.

| Table variant | Match | Mismatch | Expected fail | Unexplained | Weak (reported) | Unavailable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| venonic-2023 | 149 | 1 | 0 | 1 | 5 | 16 |
| fugerappi-2023 | 123 | 30 | 0 | 30 | 5 | 13 |
| flyfunner-old-50-2025 (retrospective TL50 only) | 147 | 0 | 0 | 0 | 4 | 20 |
| flyfunner-lower-2023 | 0 | 0 | 0 | 0 | 0 | 171 |
| dec-2025 (October TL70 readings) | 13 | 0 | 0 | 0 | 0 | 0 |
| October TL40 hypothesis: fugerappi-2023 | 13 | 0 | 0 | 0 | 0 | 0 |
| October TL40 hypothesis: flyfunner-lower-2023 | 12 | 1 | 1 | 0 | 0 | 0 |

F1 HP is 163 under both old variants. F2 exact HP is 100.33158 with Venonic and 100.33 with fugerappi;
both floor to 100 and fit the measured bracket. No old table lists TL70. The separate TL40 hypothesis
comes from the October source; no regime or fixture is relabelled. Gallade matches dec-2025. Unknown-rank
Staraptor and Murkrow 6145 each match leader uniquely (weak: a consistency check only). The lower-level table has 16 entries, including a TL34 estimate below
its stated minimum. TL32 and TL48 in fugerappi retain the author's lost-data flags.

The December source explicitly describes three-decimal values cast to float32. Its retrospective old TL50
value (1.31502044) differs from both 2023 publications and fixes Steelix's one-CP mismatch, leaving no unexplained
reading under it. Player CPMs have 49 literal game-master differences above 1e-9 (none after float32 conversion)
and no half-level interpolation differences above 1e-9. See the [stats report](../tests/fixtures/sim/stats_report.md)
for every unresolved row, precision decision, cross-check difference, and reproduction command.

### Damage results

Ordinary damage is ported from the same pinned PvPoke commit as the stats module. No constants or inputs were fitted.
Venonic and fugerappi each pass all 44 acceptance targets. The retrospective old TL50 table passes 43;
F2 needs its missing TL41 entry. This includes the two HP checks from the stats module. All 42 damage-dependent targets pass
under each table. F5's six rows agree for every attack IV 13–15; all IVs 0–15 were checked.

The Shadow Tyranitar/Ducklett cell, an open discrepancy, still needs five hits at the stated attack IV 14,
against four recorded; at IV 15 it gives four, so a misreported IV is one plausible explanation. It keeps
three strict xfails. F3's calculated eight-hit claim reproduces as a weak check. Its recorded remaining-HP
claim needs the turn loop and is skipped. Weak F1, F7 and F8 checks match. F9 matches only conditionally on its
missing trainer level and IV. The Mega flag does not boost Confusion in pinned PvPoke. Ledger q stays open.
The port matches pinned JavaScript exactly in 1,440 raw-damage cases (Mega-off and extreme stats included) and 6,156 type combinations.
See the [damage report](../tests/fixtures/sim/damage_report.md) for variant results, IV ranges, boundary distances,
source lines and interpretation calls. The simulator remains unvalidated.

### Calculator

The lineup calculator uses the stats and damage formulas above. It adds no battle mechanics.
It recomputes acceptance targets with dated moves on every run. Venonic and fugerappi each pass 44.
Both publish every trainer level the targets use, so they gate. The TL50-only table passes the 43 it
covers. It has no TL41 for F2, which is reported as not covered. Any failure, or a gap in a gate table,
labels the output UNVALIDATED. Both open discrepancies are reported with their reasons.

Cells carry fixture-exact, cp-only, parity-only or model grades, in that order of strength.
A grade never claims more than its weakest input. fixture-exact needs this run's gate to pass, a grunt,
a gate table at a trainer level where targets checked that quantity (HP at TL41 or TL50; attack and
defence at TL50), and move stats equal to the dated
snapshots the targets used. Today's move values often differ, so most current damage is parity-only.
Current Rocket stats, other levels, the TL50-only table, and every leader and Giovanni cell are backed
by CP readings at most. Charged damage is a PvPoke parity result, without a battle target. If the gate
fails, nothing is fixture-exact. The lineup's species, timing and energy counts in a real battle are
models. They ignore charged attacks, pauses, shields and switching. The gate is pinned to the
reviewed 44 target IDs, the open-discrepancy IDs and a hash of the targets' inputs. A pin change is
defended only by review. The shared Rocket scaling inputs need every quantity checked at a level, so
they are fixture-exact at TL50 only. The gate needs the source checkout's fixtures.

The Rocket move pool copies the PvPoke species lists, including elite and legacy flags.
Event-info lists species, not moves. The pool is a model. Neither source settles extra shadow
Frustration, so none is added. Source fetch times accompany every output.

### Turn loop

The offline 1v1 turn loop is an estimate. It ports the pinned PvPoke turn core.
Fast damage, energy and charged priority match its JavaScript turn by turn.
Injected policies choose moves and shields. Rocket charged timing remains unknown.
Named options expose ledger j's next-turn charged start and both charged attacks firing.
The default follows PvPoke. Rocket pauses, shield inventories, switching and timers are absent.
F3 ends in a double knockout with 0 HP, against 1 recorded. The discrepancy stays open.
F1's calculated 1 HP after seven hits reproduces as a weak check.
See the [turn report](../tests/fixtures/sim/battle_report.md) for source lines,
parity coverage, fixture traces and assumptions. The calculator and CLI are unchanged.

### Rocket rules

Fixed-order teams of three are an estimate. Dated pauses use ledger k.
The battle date picks the era. Boundaries are about 10 Dec 2025 and 12 Mar 2026, both approximate.
Dates before 22 Jul 2019, when Rocket battles began, are rejected. Dates after 29 Sep 2026 are flagged as extrapolated.
The default is the March 2026 era. Every result carries its era's grades.
A charged attack from either side starts the pause. That is the owner's observation, agreeing with cwizz1; not measured.
Either side's faint and replacement starts it too. That is the owner's reading; not measured.
The pause starts after PvPoke's post-charge turn, so the two add. Two players' accounts support this.
Both readings come from the March 2026 era. Older eras use them by extension, and their grades say so.
Named options keep the narrower triggers and the alternate cwizz1 reading.
A pause blocks new Rocket inputs. The era's 9db rows decide fast-move slip-in and simultaneous charges.
Rocket charged timing and damage remain unverified (l).
Shields belong to each side (m). The player's default shields the first two incoming charges.
The timer uses 1440 turns plus 14 per resolved charge on either side (n, measured-once).
Timeout compares survivors, then member HP fractions. This last reading is an interpretation.
Before Dec 2025, a leader timeout is a loss.
Results report the era, policies, evidence and ending reason. No Rocket-only target is added.
The original 514-case turn parity is unchanged. Three native PvPoke team cases also check
replacement order and shared shields. They do not establish full team turn parity.
See the [Rocket report](../tests/fixtures/sim/rocket_report.md) for sources and judgement calls.

### Win rate

Win rates and slots swept are estimates. Every complete lineup and moveset has equal weight.
No appearance-rate source exists. The move pool and player policies are models.
The CLI requires a battle date. It uses the default Rocket rules and fixed team order.
A faint belongs to the player member active on that turn, including a double knockout.
Rows sort by win rate, then HP left, then turns. Draws count as not-wins.
Timeout wins, losses and draws are separate from knockouts.
The 1v1 grid ignores carried-over shields and HP between slots. Each battle starts fresh.
Every result carries the union of its ledger flags and evidence. Charged Rocket moves keep l unverified.
The stats grade is the weakest calculator stat or damage cell used, under this run's gate.
A failing gate prints UNVALIDATED. No acceptance target is added.
See the [win rate report](../tests/fixtures/sim/winrate_report.md) for definitions and model choices.

## What can honestly be claimed

**"Pretty dang sure" is supported for:**

- damage per hit;
- Rocket Pokémon HP, attack and defence for the pre-Oct-2025 table (by battle fixtures) and by CP only since;
- fast-move hits to knock out.

These are measured and reproduced, and the simulator can be held to them exactly.

**Not supported yet:**

- **When the Rocket side fires its charged attacks, and how hard they hit:** no measurement exists.
- **Pause after your own switch:** sources conflict.
- **Simultaneous charged attacks:** measured once.
- **Shields:** grunts none, leaders and Giovanni the first two. These are consistent community reports from play,
  not measurements; F8's shielded 1 damage is a calculation. The simulator uses them as stated rules.
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
