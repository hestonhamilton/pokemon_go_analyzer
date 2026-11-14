# Rocket win rate report

Every number is an **estimate** until the in-game checks in the
[verification ledger](../../../docs/simulator-verification.md#minimum-in-game-checks) are done.
No rule, value, weight or input is fitted. Synthetic outcomes check aggregation arithmetic and
wiring. They do not validate Rocket behaviour. A reported gap remains a gap.

## Trials and weighting

The default trial uses the supplied team of one to three Pokémon in fixed order against three
Rocket Pokémon. Both sides start at full HP and zero energy. `simulate_rocket` uses its default
`RocketRules` and `ChargedWhenReady` player policy. The player shields the first two incoming
charged attacks. The Rocket fires its supplied charged move when ready. These are model choices,
not an optimal player strategy or a measured Rocket strategy. All existing ledger flags apply.

A Rocket member is a species, a fast move and one charged move. Each slot contains every
PvPoke `fastMoves × chargedMoves` pair for every event-info species in that slot. A full lineup
chooses one member from each slot. The full Cartesian product is enumerated with weight one per
lineup. There is no sampling or lineup cap. No appearance-rate source exists. Equal weighting
is therefore a model choice, not a claim about actual encounter frequencies. Species with more
movesets occupy more options. Species are not given a second, equal-species weight.

The moveset pool is the calculator's model: event-info lists species, not moves. Elite and legacy
moves are included by default. `--exclude-elite-legacy` removes membership in either PvPoke list
from both fast and charged pools. The output states whether the filter applies. A species whose
pool empties is unresolved, with the reason. No extra shadow Frustration is added. A special move
that the calculator rejects is rejected here too, rather than silently excluded.

Unresolved species remain visible. When every slot still has options, the estimate covers the
resolved options only and says `pool_complete: false` and `resolved options only; incomplete pool`.
The headline grade then ends `; pool incomplete`. This is conditional coverage, not an estimate over unknown options. If any slot has no resolved
options, there is no full battle result. The character is listed as unavailable with zero battles.
No probability is invented for that character. Other matched characters can still have results.

## Metric definitions

Each mean and share uses all enumerated lineups for that character, with denominator `battles`.
Counts are exact within the model; the output still labels every number estimate.

| Metric | Definition |
| --- | --- |
| `lineups`, `battles` | Number of fully enumerated lineups and completed battles. One battle per lineup. |
| `wins`, `losses`, `draws` | Battles whose winner is player, Rocket, or neither. Draws are not wins. |
| `win_rate`, `draw_rate` | Wins or draws divided by battles. No draws are removed from the denominator. |
| `timeout_wins`, `timeout_losses`, `timeout_draws` | Corresponding outcomes with `ended_by: timeout`. |
| `knockout_wins`, `knockout_losses`, `knockout_draws` | Corresponding outcomes with `ended_by: knockout`, including final double knockouts. |
| `mean_rocket_knocked_out` | Mean count of Rocket Pokémon that fainted, from zero to three. |
| `lead_sweep_probability` | Share in which all three Rocket Pokémon fainted and player slot 1 was active for every Rocket faint. A final double knockout can qualify even though the battle is a draw. |
| `slots_swept[].mean` | Mean Rocket faints credited to that player member, including zero in battles where they never become active. |
| `slots_swept[].shares` | Shares of battles with exactly zero, one, two or three credited Rocket faints. Member means sum to mean Rocket knockouts. |
| `mean_player_hp_fraction_left` | For each battle, sum each player's remaining HP / maximum HP, then divide by the supplied team size. Average these fractions over battles. Fainted members contribute zero; untouched reserves contribute one. |
| `mean_turns` | Mean elapsed turns over all battles, including losses, draws and timeouts. It is not conditional time to win or an animation clock. |
| `per_slot[].knockout_share` | Share in which that Rocket slot fainted. A slot never reached contributes zero. |
| `per_slot[].species[].conditional_win_rate` | Player wins among lineups containing that species in that slot, divided by those lineups. The accompanying battles count is that conditional denominator. |

Credit a Rocket faint to the player member active **on the turn it happened**. Use the timeline's
`active_slots` before replacements. This includes a same-turn double knockout. A faint is counted
once per Rocket slot. No credit is transferred to the arriving replacement. A lead sweep means
three lead credits and a fully fainted Rocket team; it does not require a surviving lead.

Rows sort by win rate descending, mean player HP fraction left descending, then mean turns ascending.
Ties keep source character order. This follows the mechanics guide's win rate, HP left, time order.
The chosen time metric includes every outcome, as defined above. No combined score or weight is added.
An `observation_limit` ending raises an error. It cannot become a draw or enter any denominator.

## Isolated slot grid

`--per-slot` is a 1v1 grid: each supplied member against each option in each Rocket slot.
It **ignores carried-over shields and HP between slots**. Every 1v1 starts at full HP, zero energy
and fresh shields. The battle date, rank, stats and rules match the full team mode.
`--slot 1|2|3` restricts this grid; it cannot restrict a full battle.

Rows report character, Rocket slot, species and moveset, player slot and species, winner,
ending reason, elapsed turns and both remaining HP fractions. Each row has one lineup and battle.
Each `(player member, slot)` aggregate reports its option count, battles, wins, losses, draws,
win rate and draw rate, uniformly over that slot's options. Duplicate player species remain separate
by one-based player slot. Draws stay in the denominator. These probabilities are not full team win
rates. The limitation is prominent in table, JSON and CSV, and attached to every grid row and aggregate.

## Evidence and grades

Each result carries its battle date, era, rules, the union of ledger rows and flags, and distinct
`(row, grade, option, source)` evidence tuples from its battles. Interpretations are also unioned.
No evidence is promoted by repeating it across many battles. Era boundaries and Rocket-only
assumptions retain the [Rocket report](rocket_report.md)'s grades and limitations.

`rules_grade` is `unverified` if any battle has the `unverified` flag. Otherwise it is `estimate`.
Every supplied Rocket charged move exercises ledger l, even if it never fires. Full pools therefore
remain unverified. The headline always starts with `estimate` and states the weaker grades once each,
for example `estimate; unverified (l); stats parity-only`. A battle date after the newest rules source
(29 Sep 2026) adds `extrapolated forward`, and an incomplete pool adds `pool incomplete`.

`stats_grade` uses `calculate_matchup`, then `grade_row` with this run's `run_acceptance` result,
for every player build and Rocket species/moveset pair represented by the result. It takes the
weakest grade in the calculator vocabulary over these cells:

- `attacker_attack`, `attacker_defence`, `attacker_hp`;
- `rocket_attack`, `rocket_defence`, `rocket_hp`, `rocket_cp`;
- `rank`, `rank_multiplier`, `rocket_cpm`, `rcpm_table`, `trainer_level`;
- `fast_damage`, `fast_damage_per_turn`, `rocket_fast_damage`, `rocket_fast_damage_per_turn`;
- every nested `damage` cell in both `charged` and `rocket_charged`.

This is the weakest stat and damage grade, not the calculator's overall row grade, which also
contains pool and timing models. It includes all supplied charged moves even if the selected policy
never reaches them. Charged damage is parity-only at best, so current supplied charged builds give
stats parity-only, even when their Rocket stat cells are cp-only or some old stat cells are
fixture-exact. Availability and policy uncertainty remain separate and explicit. A grade never
claims more than its weakest input. No new acceptance target is added.

A failing acceptance gate labels every format UNVALIDATED. A passing gate validates only its existing
pre-Oct-2025 targets. It does not validate a win rate. The dec-2025 table carries the calculator's
note that current Rocket stats are backed by CP readings only. Every output retains the calculator's
credits and both source fetch times. The calculator's pool note is reused verbatim; when the exclusion
filter is active its adjacent filter note states the change from the default pool.

## Real source pools and measured runtime

The cached GitHub sources were fetched on 2026-11-14 at 02:01:54 UTC:
[WatWowMap event-info](https://raw.githubusercontent.com/WatWowMap/event-info/main/grunts/formatted.json)
and [PvPoke game master](https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/gamemaster.json).
The moving URLs have no pinned commit in their cache envelopes. No unresolved species occurred in
these counts. Counts were measured before implementation. A character has one battle per lineup,
regardless of the number of supplied player members. Eighteen characters exceed 20,000 lineups.

| Character | Default slot option counts | Default lineups | Lineups excluding elite/legacy |
| --- | --- | ---: | ---: |
| Mixed grunt (male) | 18 × 21 × 55 | 20,790 | 9,072 |
| Mixed grunt (female) | 56 × 76 × 76 | 323,456 | 100,980 |
| Bug grunt (male) | 9 × 27 × 39 | 9,477 | 7,560 |
| Dark grunt (female) | 18 × 24 × 18 | 7,776 | 6,336 |
| Dragon grunt (female) | 18 × 22 × 59 | 23,364 | 17,280 |
| Fairy grunt (female) | 20 × 31 × 37 | 22,940 | 19,040 |
| Fighting grunt (female) | 20 × 44 × 32 | 28,160 | 15,000 |
| Fire grunt (female) | 22 × 47 × 45 | 46,530 | 32,800 |
| Flying grunt (female) | 14 × 29 × 51 | 20,706 | 11,760 |
| Grass grunt (male) | 26 × 23 × 39 | 23,322 | 18,144 |
| Ground grunt (male) | 24 × 42 × 62 | 62,496 | 59,472 |
| Ice grunt (female) | 28 × 34 × 38 | 36,176 | 20,026 |
| Metal grunt (male) | 16 × 29 × 50 | 23,200 | 20,416 |
| Normal grunt (male) | 136 × 21 × 33 | 94,248 | 40,803 |
| Poison grunt (female) | 28 × 26 × 42 | 30,576 | 25,688 |
| Psychic grunt (male) | 15 × 60 × 104 | 93,600 | 86,400 |
| Rock grunt (male) | 24 × 24 × 48 | 27,648 | 20,160 |
| Water grunt (female) | 20 × 24 × 48 | 23,040 | 17,160 |
| Water grunt (male) | 3 × 1 × 25 | 75 | 39 |
| Cliff | 6 × 46 × 54 | 14,904 | 10,764 |
| Arlo | 6 × 35 × 56 | 11,760 | 4,752 |
| Sierra | 6 × 49 × 40 | 11,760 | 10,320 |
| Giovanni | 10 × 52 × 10 | 5,200 | 2,048 |
| Decoy grunt (female) | 6 × 15 × 34 | 3,060 | 1,944 |
| Ghost grunt (male) | 24 × 30 × 52 | 37,440 | 23,040 |
| Electric grunt (female) | 20 × 24 × 98 | 47,040 | 33,696 |

Runtime inputs are fixed: battle date 2026-11-14, trainer level 50, dec-2025 rCPM, ordinary Metagross
at level 50 with 15/15/15 IVs, Bullet Punch and Meteor Mash, default rules. The three-member benchmark
repeats that build in all three player slots. These builds are stated benchmark inputs, not fitted
recommendations. No outcome statistic is inferred from an unfinished benchmark.

| Character and team | Enumeration completed | Measured elapsed seconds | Execution |
| --- | ---: | ---: | --- |
| Water grunt (male), three Metagross | 75 / 75 | 0.053 | Serial direct battles |
| Mixed grunt (female), three Metagross | 131,346 / 323,456 | 121.000 | Serial direct battles; unfinished at this duration |
| Water grunt (male), one Metagross | 75 / 75 | 0.055 | CLI battle and aggregation iterator, serial |
| Mixed grunt (female), three Metagross | 323,456 / 323,456 | 179.963 | CLI battle and aggregation iterator; serial for 120 seconds, then three forked worker processes plus the parent (four in all) |

The measured serial run exceeded two minutes for one character. The CLI therefore continues with
stdlib multiprocessing only after that character actually exceeds 120 seconds. It uses at most four
processes in all, counting the parent: up to three workers (one fewer than the CPUs this process may
use, from `os.sched_getaffinity` where available, so affinity and cpusets apply) plus the
parent, which collects and aggregates results. It uses the `fork` start method where available, because
`spawn` and `forkserver` also start a helper process. Results use ordered `imap` with 32-item chunks.
A process listing during that run showed the parent and its three workers only. Launching through
`uv run` adds the idle `uv` launcher around them. Workers ignore Ctrl-C, so an interrupt stops the
pool from the parent without worker tracebacks. A selection of more than 500,000 lineups across its
matched characters prints an up-front warning with the count. These are execution choices,
not probability weights or caps on battles. The serial prefix and all remaining lineups are retained.
Ordered results preserve floating-point accumulation order as well as outcome counts. Offline tests
compare serial and multiprocessing aggregate records exactly. Every full result reports its execution
mode, worker count and elapsed iterator time. Iterator timings exclude source loading, acceptance
checks, calculator grading and rendering. Other characters' runtimes were not measured.

## Remaining judgement calls and gaps

- Battle dates before 22 July 2019, when Team GO Rocket grunt battles first appeared, are rejected.
  Dates after the newest rules source (9db, 29 Sep 2026) run the newest era's rules and carry the
  `extrapolated` flag and a note; later rule changes are unknown.

- The required calendar date selects the existing rules era only. Cached moves and the explicitly
  selected stat table are used even for older dates. No historical move values are inferred.
- Player stats follow `calculate_matchup` exactly, including dex-specific HP and a shadow flag on
  unmodified stats. Purified uses the supplied post-purification IVs without another gain.
- Rank follows the shared character tier mapping: RAID_LEVEL_5 Giovanni, RAID_LEVEL_4 leader,
  otherwise grunt. There is no free rank override or explicit defender in `sim`.
- Mean HP gives each supplied member equal weight after normalising by its own maximum HP.
  It is not pooled raw HP. The denominator is supplied team size, including untouched reserves.
- A drawn final double knockout can count as a lead sweep and three slots swept. Those metrics
  count faints, while win rate counts the battle winner.
- Grid aggregates distinguish repeated species by player slot. They do not combine different
  builds or assume their shields would reset during a real three-slot battle.
- Unresolved options have unknown outcomes. Reported partial coverage is conditional on resolved
  pools. An empty pool is an explicit error in pure enumeration, and an unavailable character in
  full CLI output. No probability is assigned to omitted unknowns.
- Table scalar floats display two decimals using the calculator's rendering helper. JSON and CSV
  retain Python numeric precision. Nested distributions and evidence retain their full records.
- Move effects and stat stages, voluntary switching, Mega and special-move mechanics remain absent.
  Rocket charged timing/damage, pauses, timer interpretations, post-2025 battle stats and the
  existing open discrepancies remain evidence gaps. Large enumeration does not close them.
