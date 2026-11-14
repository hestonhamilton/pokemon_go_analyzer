# Turn loop verification

The turn loop is an **estimate**. JavaScript parity checks a port, not the game.
Rocket charged timing and damage remain unknown (ledger l). The fixture gate remains open.
No input, formula, timing or constant was fitted to a battle outcome. `battles.json` is unchanged.

## Pinned source and ported rules

All PvPoke references below use commit `426e5e9f39d3a027849698fb2f5edd9df6056cbf` (MIT).
The existing full notice is in `src/pogo_analyzer/sim/data/PVPoke-LICENSE`.
The tool caches missing source files under `.cache/fixture-sources/pvpoke-<sha>/`.
Existing entries are never overwritten. Its temporary oracle and payload live outside the cache.

| Rule | Pinned source | Python behavior |
| --- | --- | --- |
| Turn clock | [Battle.js 38](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L38), [405](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L405) | One turn is 500 ms. Convert fast cooldown to turns by dividing by 500. |
| Initial state | [Pokemon.js 1924–1931](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/pokemon/Pokemon.js#L1924), [1944–1947](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/pokemon/Pokemon.js#L1944) | Caller supplies HP and energy; cooldown starts at zero, faint source empty. |
| Decision boundary | [Battle.js 303–311](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L303), [332–391](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L332), [732](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L732) | Decrement cooldown first. Decide at zero cooldown, before either side changes HP or energy. Fast submission adds its full duration; charged submission adds one turn. |
| Fast registration | [Battle.js 405–409](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L405) | A fast move submitted on turn t lands on t + duration − 1. A 1-turn move lands immediately. Next submission is on t + duration. |
| Charged start and resolution | [Battle.js 377–382](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L377), [407–409](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L407), [878–880](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L878) | Simulation starts and resolves the charge on its submission turn; it does not simulate the minigame clock. |
| Priority | [Battle.js 434](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L434), [780–785](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L780) | Charged moves have +10 priority; higher unmodified attack adds 1. Shadow multipliers do not determine priority. Stable ties keep queue insertion order. Ordinary base priority is zero on both sides. |
| Simultaneous charged KOs | [Battle.js 262–265](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L262), [473–481](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L473) | With unequal attacks, a charged KO cancels the fainted user's charged reply. Equal attacks disable this cancellation, so both fire. |
| Fast versus faint | [Battle.js 451–460](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L451), [1683–1684](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1683) | Fast replies can land after a fast KO, but not after a charged KO. A fast move cannot damage an already-fainted opponent. Faint source records the last lethal move category. |
| Fast in progress during charge | [Battle.js 409](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L409), [546–549](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L546) | Keep the queued fast move. If due on the charge turn, resolve after charged priority subject to faint checks. Otherwise flush it on the following turn, even before its original due turn. Reset both cooldowns to one after a resolved charge. |
| Post-charge input | [Battle.js 341–343](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L341), [498](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L498) | No attack submissions on the turn after a charged action. Floating fast moves still resolve. This also follows a cancelled charge because previousTurnActions retains it. This is not ledger k's Rocket pause. |
| Energy | [Battle.js 1058](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1058), [1329–1340](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1329) | Fast gain occurs only on a valid hit and caps at **100**. Charge cost is paid on valid resolution, not on submission or cancellation. |
| Damage and HP | [Battle.js 1045](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1045), [1194–1200](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1194), [1365](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1365), [1526](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1526) | Only `damage.calculate_damage` computes damage, with both shadow keywords explicit. Rocket is shadow for attack and defence. Full charge multiplier is 1. Injected shield decisions use that calculator's 1-damage override. HP floors at zero; reported damage includes overkill, as in TimelineEvent. |
| Faint turn and battle end | [Battle.js 439–495](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L439), [528–543](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L528), [625–629](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L625) | Complete the eligible action list, then end at the first faint. A double KO has no winner. Future queued moves do not land after battle end. |

## Ledger j comparison

| Ledger j statement | Pinned behavior | Named option |
| --- | --- | --- |
| Fast move can land after charged attack starts | Already allowed for a surviving attacker. Due fast moves land after the charge in the same turn; unfinished ones flush on the next turn. Charged KO still cancels fast retaliation. The ledger does not specify an alternative flush schedule or post-faint delivery. | No alternative is invented for this statement; default preserves the source checks and flush. |
| Simultaneous charged attacks both fire | Both fire at equal attack. At unequal attack, lower-attack reply is cancelled only if charged KO'd first. | `Rules(ledger_j_both_charged_fire=True)` disables that cancellation. |
| Charged attacks start next turn | Default starts and resolves on the submission turn. | `Rules(ledger_j_next_turn_charged=True)` queues the input on t and starts/resolves it on t+1. Pending charge prevents another input by its owner. |

The two options compose. They are ledger-j estimates, **not JavaScript parity results**.
They retain PvPoke's remaining queue, cooldown, priority and post-charge rules. This is a minimal
interpretation of the ledger, not a claim to reproduce the complete 2026 game rebuild.
There is no measured Rocket timeline here that decides between these modes.

## JavaScript parity

Run `uv run python tools/parity/pvpoke_battle_parity.py` from the repository root.
Node is a tool dependency only. There are no runtime dependencies.

The oracle evaluates the **entire** pinned `Battle.js`, `DamageCalculator.js`, `ActionLogic.js`,
`TimelineAction.js` and `TimelineEvent.js`. It runs `start()` and repeated `step()` calls in simulate
mode, avoiding the display-time timeout in `simulate()`. `GameMaster.getInstance()` returns the
pinned game master. No DOM or interface initialization is needed. This is executable parity,
not a hand trace or a second JavaScript implementation of the turn rules.

The Pokemon adapter supplies already-calculated stats and initialized ordinary moves. It executes
the verbatim `Pokemon.js` methods `reset`, `applyStatBuffs`, `getEffectiveStat`,
`getStatBuffMultiplier` and `getStab`. `resetMoves` and `setBattle` are adapter no-ops: there is no
species initialization or move selection to repeat. Form changes and special move tags are absent.
Shields start at zero. The sole behavior override is `ActionLogic.decideAction`, replaced by the
same two injected attack policies as Python. No PvPoke AI output is compared or ported.

A passive callback is inserted immediately after `queuedActions.push(action)` at Battle.js 382
to record accepted submissions. Wrappers around `processAction` and `useMove` record cancellations
and actual resolutions, without changing their behavior. After every `step()`, the oracle reads
both Pokemon's HP and energy. Python compares every row, including starts, cancellations,
resolutions and nominal damage. A mismatch prints its case and first differing turn and exits 1.

The deterministic seed is 426. Both policies cover all 25 pairs of 1- to 5-turn moves,
ten stat/HP/energy configurations each. Only the player side is ever shadow; the Rocket side is
shadow by rule. Named cases cover equal/unequal-attack lethal charged
ties, surviving charged ties, double fast KOs and repeated energy overflow. The same run checks
F3 and F1 under both complete old tables. Random cases include fast/charged races, unfinished fast
moves and 0/29/95/100 initial energy. Unit tests separately pin the ordering rules by hand.

`Battle.js parity: 514 cases; 20817 turns; 0 mismatches (HP, energy, actions, damage)`

The tool checks the SHA-256 of every pinned source file, fetched or cached, before running.
The shield callback is covered by unit tests only: the oracle starts with zero shields, so it is
not part of this parity result.

## F3: recorded Metagross remaining HP

Exact record: `F3-metagross-remaining`, 2023-11-27. Shadow Metagross level 46.5, IVs 15/9/12,
against grunt lead Bite Snubbull at trainer level 50. Both complete old tables
(`venonic-2023`, `fugerappi-2023`) give the same trace below. No pause or charged attack is added.
The dated snapshot supplies Bullet Punch power 6, gain 7, duration 2; Bite power 4, gain 2,
duration 1. Stats give Metagross **166 HP**, Snubbull **134 HP**. Damage is **19 / 11**.

Odd turns submit Bullet Punch; even turns register it. Bite submits and registers every turn.
The older hand claim of 2 HP does not reproduce from these exact inputs. The intermediate 1 HP
on turn 15 is not survival of the completed matchup. The recorded outcome remains a discrepancy.

| Turn | Metagross action | Snubbull action | Damage P/R | HP P/R | Energy P/R |
| ---: | --- | --- | --- | --- | --- |
| 1 | BP start | Bite start + hit | 0 / 11 | 155 / 134 | 0 / 2 |
| 2 | BP hit | Bite start + hit | 19 / 11 | 144 / 115 | 7 / 4 |
| 3 | BP start | Bite start + hit | 0 / 11 | 133 / 115 | 7 / 6 |
| 4 | BP hit | Bite start + hit | 19 / 11 | 122 / 96 | 14 / 8 |
| 5 | BP start | Bite start + hit | 0 / 11 | 111 / 96 | 14 / 10 |
| 6 | BP hit | Bite start + hit | 19 / 11 | 100 / 77 | 21 / 12 |
| 7 | BP start | Bite start + hit | 0 / 11 | 89 / 77 | 21 / 14 |
| 8 | BP hit | Bite start + hit | 19 / 11 | 78 / 58 | 28 / 16 |
| 9 | BP start | Bite start + hit | 0 / 11 | 67 / 58 | 28 / 18 |
| 10 | BP hit | Bite start + hit | 19 / 11 | 56 / 39 | 35 / 20 |
| 11 | BP start | Bite start + hit | 0 / 11 | 45 / 39 | 35 / 22 |
| 12 | BP hit | Bite start + hit | 19 / 11 | 34 / 20 | 42 / 24 |
| 13 | BP start | Bite start + hit | 0 / 11 | 23 / 20 | 42 / 26 |
| 14 | BP hit | Bite start + hit | 19 / 11 | 12 / 1 | 49 / 28 |
| 15 | BP start | Bite start + hit | 0 / 11 | 1 / 1 | 49 / 30 |
| 16 | BP hit, KO | Bite start + hit after own fast KO | 19 / 11 | 0 / 0 | 56 / 32 |

On turn 16 the previously queued BP precedes the newly queued Bite at equal fast priority.
BP KOs Snubbull. Battle.js 451–460 still permits Bite because its faint source is **fast**.
Bite KOs Metagross. The battle ends in a double KO: **0 HP**, 16 turns, nominal damage 152 / 176.
The test against the recorded 1 HP is a strict `OPEN DISCREPANCY` xfail for each old table,
with computed 0 HP in its reason. Separate passing hand-trace tests pin the source behavior.
`battles.json` retains `open_discrepancy`; this result does not qualify for re-grading as a match.

## F1: weak Snubbull remaining HP

Exact record: `F1-snubbull-remaining`, 2022-12-03. Shadow Metagross level 43.5, IVs 15/9/12,
trainer level 50. The dated BP is power 6, gain 7, duration 2. Metagross starts at 163 HP;
Snubbull at 134. BP damage is 19. This record does **not** specify Snubbull's fast move.
Tackle and Bite are explicit sensitivity cases, not recovered battle facts. Charge Beam belongs
to the separate Kirlia damage record and is not assigned to Snubbull.

The observation ends at turn 14, after seven BP hits. It is not a whole-battle result.
Both complete old tables agree, with Snubbull at **1 HP**: 134 − 7 × 19 = 1.
These four tests are non-strict xfails and report XPASS; a calculated number remains weak.

| Turn | Metagross action | BP damage | Snubbull HP | Metagross energy | Metagross HP Tackle / Bite | Snubbull energy Tackle / Bite |
| ---: | --- | ---: | ---: | ---: | --- | --- |
| 1 | BP start | 0 | 134 | 0 | 159 / 152 | 3 / 2 |
| 2 | BP hit | 19 | 115 | 7 | 155 / 141 | 6 / 4 |
| 3 | BP start | 0 | 115 | 7 | 151 / 130 | 9 / 6 |
| 4 | BP hit | 19 | 96 | 14 | 147 / 119 | 12 / 8 |
| 5 | BP start | 0 | 96 | 14 | 143 / 108 | 15 / 10 |
| 6 | BP hit | 19 | 77 | 21 | 139 / 97 | 18 / 12 |
| 7 | BP start | 0 | 77 | 21 | 135 / 86 | 21 / 14 |
| 8 | BP hit | 19 | 58 | 28 | 131 / 75 | 24 / 16 |
| 9 | BP start | 0 | 58 | 28 | 127 / 64 | 27 / 18 |
| 10 | BP hit | 19 | 39 | 35 | 123 / 53 | 30 / 20 |
| 11 | BP start | 0 | 39 | 35 | 119 / 42 | 33 / 22 |
| 12 | BP hit | 19 | 20 | 42 | 115 / 31 | 36 / 24 |
| 13 | BP start | 0 | 20 | 42 | 111 / 20 | 39 / 26 |
| 14 | BP hit | 19 | 1 | 49 | 107 / 9 | 42 / 28 |

Snubbull submits and registers its 1-turn fast move every turn: Tackle does 4, Bite 11.

## Decisions, limits and checks

- Exactly three concrete policies ship: `FastOnly` (`fast_only`), `ChargedWhenReady`
  (`charged_when_ready`) and `NeverShield` (`never_shield`). Charged selection walks the
  caller's move list in order, taking the first affordable move. The attack policies also
  default to no shield. Shield callbacks can be injected independently. No shield inventory
  or rank rule is asserted. This is a decision boundary, not Rocket AI or an estimate of it.
- All timeline events are per side: `kind:start:ID`, `kind:hit:ID`, `kind:cancel:ID`.
  The next-turn option additionally uses `charged:queue:ID` at input time. Empty actions mean
  cooldown or input suppression. HP and energy are after all eligible actions for that turn.
  Charged animations do not add simulated turns or wall-clock seconds.
- Every result carries `label="estimate"` and ledger dependencies a–j. Rows b–e conservatively
  describe supplied stat provenance. Row l is added when Rocket selects a charge, p when the
  player selects one (full minigame charge), and m when an injected shield is used.
  The selected `Rules` also travels with the result. Parity does not promote those evidence grades.
- Only ordinary moves without effects or form changes are represented. Buffs, percent-max-HP
  moves, Mega interactions and special tags such as `instant` or `ignoresFaint` are outside this
  loop. The Cramorant equal-attack exception at Battle.js 262–263 is a form-specific mechanic
  outside these ordinary combatants. No tag or form behavior is silently reconstructed from IDs.
- Players are fixed at base priority zero, matching Pokemon.js 65. No custom sandbox priority,
  switching, waits or player AI is ported. FIFO ties follow JavaScript's stable sort.
- There is no ledger-k pause, ledger-n timeout or PvPoke four-minute display timeout (635–637).
  `max_turns` is an explicit observation/resource limit. If reached with both alive, the result
  has `limit_reached=True` and no winner. It is not a battle timeout decision.
- Tests use checked-in fixture data and no ignored cache. The autouse network block is unchanged.
  The old F3 skips in the damage-only tests remain; the new turn tests report it separately.
  Calculator outputs, CLI, fixture grading and existing test expectations are unchanged.

The turn-loop tests add two strict xfails, the F3 recorded mismatch under both gate tables, and
four non-strict XPASS reports, F1's weak record under two moves and both gate tables. F1's turn
structure (the observation limit and the energy after seven hits) is a plain test that can fail.
Running the suite with `--ignore=tests/test_sim_battle.py` gives the same results as without the
turn loop.
