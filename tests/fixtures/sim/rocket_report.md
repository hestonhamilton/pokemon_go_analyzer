# Rocket rules report

All results are **estimates**. No Rocket-only acceptance target exists. Synthetic hand traces check
implementation arithmetic. They do not validate the rules in the game. Existing battle targets,
evidence grades and the acceptance gate are unchanged.

## Rules, sources and options

| Rule | Source | Ledger grade | Named option and behavior |
| --- | --- | --- | --- |
| Fixed team order | [Rocket mechanics, section 5](../../../docs/rocket-battle-mechanics.md#5-shields-switching-and-the-npcs-behaviour) | Community, universally observed; no direct measurement | `player_team` and `rocket_team` supply ordered slots. Each side advances only on a faint. No voluntary switching. |
| Rocket stats and rank | [Stats report](stats_report.md), ledger c–e | Existing grades; current stats have CP evidence only | `rocket_combatant(..., trainer_level=..., rank=..., table=...)` calls `stats.rocket_stats`. Rank is `grunt`, `leader` or `giovanni`. No stat formula is added. |
| Rocket is always shadow | Ledger g; [Rocket Pokémon, section 2](../../../docs/rocket-pokemon.md#2-shadow-bonus-versus-the-rocket-boost) | Data-mined + measured-reproduced | The shared core supplies the required shadow flags. Rocket `Combatant.shadow` must remain unset, as in the 1v1 API. Player shadow state follows the active member. |
| Turn timing | [Turn report](battle_report.md), pinned PvPoke | Ledger j grades unchanged | `turn_rules=Rules()` is the base. With `era_turn_rules=True` (default) the era's 9db rows below set fast-move slip-in and simultaneous charges; `ledger_j_both_charged_fire` then follows the era. `ledger_j_next_turn_charged` remains an opt-in estimate. If a caller's `ledger_j_both_charged_fire=True` meets an era where only the first charge fires, the run warns and the result records the replacement. `era_turn_rules=False` keeps PvPoke's behaviour in every era. |
| Charged and faint pauses | [9db table](https://9db.jp/pokemongo/data/24341), [research notes, section 4](../../../docs/rocket-pokemon.md#4-how-the-rocket-side-battles) | k, graded per era: since Mar 2026 measured-reproduced; Dec 2025 single source (9db), method unstated; before Dec 2025 charged conflicting, faint and switch 9db plus one player's recollection | `pauses=True`, `pause_reading="9db"`; lengths below. `pauses=False` disables the extra suppression. Every result carries its era's grades. |
| Manual switch pause | Same table; [cwizz1](https://www.reddit.com/r/TheSilphArena/comments/1vyspr1/) | k: conflicting | Stored in each reading. No manual switch action exercises it. |
| Charged pause trigger | 9db row; cwizz1; the project owner's in-game observation | k: owner observation, agrees with cwizz1; not measured | 9db's row reads "enemy freeze time (immediately after a charged move activates)" and does not say whose charged move. The owner reports from play that a charged attack from either side starts the pause; cwizz1 says "any charged move". These are two independent accounts, but neither is a measurement. Both describe the Mar 2026 era; earlier eras apply the reading by extension, and the grade says so. `pause_trigger="any_charged"` is the default; `"player_charged"` is the narrower option. The result reports the resolved name and grade. |
| Faint pause trigger | 9db row; the project owner's reading | k: owner reading; not measured | 9db's row reads "enemy freeze time (immediately after a swap caused by a faint)" and does not say whose Pokémon fainted. `faint_trigger="any_replacement"` (default) pauses after either side's replacement; `"rocket_replacement"` is the narrower option. The result reports the resolved name and grade. |
| Charged pause composition | cwizz1 and Jason2890, same thread | k: practitioner-reproduced (2 accounts), not measured | The pause starts after PvPoke's post-charge turn without input, so the two add. Both describe 6 fast-move turns between charges as safe and the 7th as the turn the Rocket sneaks a move in. Earlier eras apply it by extension, and the grade says so. |
| Alternate pause reading | [cwizz1](https://www.reddit.com/r/TheSilphArena/comments/1vyspr1/), 26 Aug 2026, comment p609c70 | k: charged/faint measured-reproduced; switch conflicting | `pause_reading="cwizz1"`: charged 7, faint replacement 7, manual player switch effectively 6. It describes the Mar 2026 era only; other dates raise an error. The reported general switch count is 7. |
| Fast-move slip-in | 9db row 「通常技の差し込み \| なし \| あり \| あり」 | j: since Mar 2026 measured-reproduced (ledger j); Dec 2025 single source (9db), with ledger j's GBL measurement after the Feb 2026 rebuild borrowed; before Dec 2025 single source (9db), method unstated | Since Dec 2025, a fast move in flight when the opponent's charged move fires still lands (PvPoke's flush). Before Dec 2025 it is void. Applying it to both sides, with no energy gained, is this project's reading. |
| Simultaneous charged moves | 9db row 「ゲージ技の同時発動 \| 先行側のみ発動 \| 後攻側も発動 \| 後攻側も発動」 | j: since Mar 2026 measured-once (ledger j); Dec 2025 single source (9db), with ledger j's GBL measurement after the Feb 2026 rebuild borrowed; before Dec 2025 single source (9db), method unstated | Since Dec 2025 both fire (`ledger_j_both_charged_fire` on). Before Dec 2025 only the first fires; the second is void and keeps its energy (this project's reading). |
| Rocket charged timing | Ledger l; [research notes, section 4](../../../docs/rocket-pokemon.md#4-how-the-rocket-side-battles) | l: assumed, **unverified** | `rocket_charged="when_ready"` takes the supplied charged move at the first eligible input with enough energy. `"never"` uses fast moves only. No timing measurement supports the default. |
| Rocket charged damage | [Ledger l](../../../docs/simulator-verification.md#ledger) | l: default 1.0 assumed; 0.5625 measured-once and outdated (2019); **unverified** | `rocket_charged_damage_scale=1.0` or `0.5625`. The ledger does not identify a retrievable original for the 2019 number or specify rounding placement. This is an evidence gap. |
| Shields | Sources and policies below | m: observed in play for NPC inventory/use; player choice is a model choice, not a measurement | `rocket_shields`, `player_shield_policy`, `player_shield_threshold`. Both resolved policies accompany every result. |
| Timer and timeout winner | [freezyefc, Jan 1 2026, two linked videos](https://www.reddit.com/r/TheSilphRoad/comments/1q13cga/) | n: measured-once | `timer=True`: 1440 turns plus 14 for each resolved charged attack on either side. `timer=False` disables it. Before Dec 2025, a leader or Giovanni timeout is a Rocket win. |

The caller supplies species, moves and stat tables. Nothing fetches lineups or selects missing inputs.
A full battle is three against three. Teams of one or two are allowed for isolated rule checks.
`battle_date` is a required keyword. An ISO date or calendar date selects the era.
Explicit `battle_date=None` selects the static March 2026 default. It never consults today's date.
Dates before 22 July 2019 are rejected: Team GO Rocket grunt battles first appeared that day
([PokéCommunity](https://daily.pokecommunity.com/2019/07/22/team-rocket-with-shadow-pokemon-launched-unannounced-in-pokemon-go),
[ComicBook](https://comicbook.com/gaming/2019/07/22/pokemon-go-team-rocket/)). Some sources date the main event
later (25 and 28 July); the earliest date is used so no real battle date is rejected. A date after the
newest rules source (9db, 29 Sep 2026) runs the newest era's rules, with the `extrapolated` flag and a note.
The result carries both the supplied date and selected era. Move dating remains the caller's responsibility.
Player attack selection defaults to `ChargedWhenReady`, taking the first affordable move in caller order.
An injected player policy can choose charges instead. This is a model decision, with no claim to optimal play.
Rocket members accept at most one charged move; an empty list represents a fast-only input.

## Dated pauses

The dated evidence includes the original Japanese rows in `sim/data/rocket_rules.json`.
The page is dated September 29 2026. Its columns are states, not changeover days: 2026/9時点 means
"as of Sep 2026". The article dates the latest change to the March 2026 update
(「2026年3月のアップデートで、ロケット団のバトルの挙動に変更が入りました」). Its table is labelled
2026年3月12日(木) 更新, and page comments from 12–15 March describe the shorter faint pause
(「倒した後すぐに次を出してくれる」). The Dec 2025 change is dated by the earliest page comments
retrieved, 10–11 December 2025. The selection boundaries are therefore 10 December 2025 and
12 March 2026. Both are **approximate**, not measured transition dates. The Sep 2026 values are
assumed to hold from the March update.

| Era | Charged move (either side by default) | Faint and replacement (either side by default) | Unused manual player switch |
| --- | ---: | ---: | ---: |
| Before 10 Dec 2025 | 5 | 7 | 7 |
| 10 Dec 2025 to 11 Mar 2026 | 8 | 12 | 12 |
| From 12 Mar 2026, default (`mar-2026`) | 7 | 7 | 9 |

Values are turns, converted from the source's seconds at 0.5 seconds per turn.
Only the latest column is reproduced (cwizz1, Aug 2026). The older columns rest on 9db alone.
OrbitalSong, opening the same thread, recalls that it "used to be 4 turns for using a charge attack
and 7 turns for everything else, with them taking action on the turn after". The 7 agrees with the old
faint and switch values. The 4 conflicts with the old charged 5, possibly a counting difference.
The alternative preserves cwizz1's "It's actually 7 turns after any charged move or switch. On your own
switch, it's functionally 6 turns because switching takes 1 turn." The thread was retrieved from an
archive (Arctic Shift) and the quote is exact.
The 9/7/6 manual-switch disagreement is retained. No value was chosen by matching a battle fixture.

## Pause interpretation and exact turn convention

A charged move resolves on turn t. PvPoke accepts no input on t+1. The Rocket pause then blocks new
Rocket moves on t+2 through t+N+1, inclusive, so its next eligible input is t+N+2. The two add.
cwizz1 ("7 turns means you throw after 6 turns of fast moves") and Jason2890 ("6 turns is the maximum
number of turns you can take between charge moves to ensure the rocket (or team leader) does *not* use
any fast moves") both fit this reading. A test pins the window: with 1-turn fast moves, six between
charges leave the Rocket no new move, and seven let a 3-turn fast move start beside the second charge
and land the turn after.

A faint is different. A replacement arrives after the completed faint turn t; the replacement itself
consumes no extra simulated turn. The pause blocks t+1 through t+N. By default either side's
replacement starts it; `faint_trigger="rocket_replacement"` restricts it to the Rocket's.
Overlapping pauses take the later end. With the next-turn charge option, a charge queued on t1
resolves on t2, PvPoke blocks t3, and the seven paused turns are t4–t10.

The pause suppresses **new inputs only**. A fast move already in flight follows the era's slip-in row.
Since Dec 2025 it lands, retaining PvPoke's due/flush/cancellation rules. It does not guarantee a hit
after a charged knockout: the core still cancels that fainted attacker's fast reply. For example, a
five-turn Rocket fast move submitted on t1 remains queued when a surviving Rocket takes a player charge
on t2. PvPoke flushes it on t3. The pause blocks new inputs on t4–t10; input resumes on t11.
Before Dec 2025, the same fast move is void on t2 and deals nothing.

On a faint, finish all eligible resolutions before replacement. Clear pending actions and both active
cooldowns, following the emulator's faint handling (Battle.js 553–610). Surviving HP and energy stay
with their Pokémon. The next member uses its supplied starting HP and energy. Shields stay with the side.
The zero-additional-turn replacement is a model convention. The emulator's switch/animation schedule
is not claimed as turn parity for this convention.

## Charged damage interpretation

Every result in which a Rocket member holds a charged move includes ledger l and
`flags=("unverified",)`, under `when_ready` and `never` alike: both are unverified assumptions about
when it fires. The timing and damage evidence are reported separately. Cancelled or merely queued
attacks do not extend the timer or trigger pauses.

The 2019 scale's placement is unspecified in the available evidence. The selected **interpretation**
is `floor(raw * scale) + 1`, before the shield override. A final-damage diagnostic is
`floor((floor(raw) + 1) * scale)`. Its final floor is also a diagnostic convention, not a sourced rule.
These readings are not interchangeable:

| Synthetic input: Rocket power 3, attack 100, player defence 100, normal STAB, normal player | Scale | Raw before scale | Selected raw-scale damage | Final-scale diagnostic |
| --- | ---: | ---: | ---: | ---: |
| Default | 1.0 | 2.8080000085830648 | 3 | 3 |
| Historical alternative | 0.5625 | 2.8080000085830648 | 2 | 1 |

The raw value uses the pinned float constants and Rocket shadow attack. Neither row is a game target.
Shields override damage to exactly 1 under both scales. The player's threshold decision compares the
selected scaled **unshielded** damage to the fraction of their current HP, including equality.

## Shields

[Mechanics section 5](../../../docs/rocket-battle-mechanics.md#5-shields-switching-and-the-npcs-behaviour)
cites Bulbapedia, GamePress and the [GO Hub leader guide](https://pokemongohub.net/post/guide/team-go-rocket-leader-guide/).
Leaders and Giovanni hold two shields. Grunts never shield and report none. Leaders and Giovanni
spend it on the first two resolved player charged attacks, including lethal ones. A third is unshielded.
`rocket_shields=False` disables that policy (and reports none) for core comparison. A shielded charged attack deals 1,
through damage.py's existing override (pinned Battle.js 1194–1200).

The default player policy is `player_shield_policy="first_two"`. It shields the first two incoming
Rocket charges. `"never"` spends none. `"threshold"` spends an available shield when unshielded damage
is at least `player_shield_threshold * current_HP`. The parameter defaults to 0.5 and must lie in (0, 1].
These player policies are explicit model assumptions, not observed Rocket AI rules.
Inventories survive replacements on either side. An attack reduced to 1 can still knock out a member
with only 1 HP; its shield remains spent for the rest of the team.

## Timer interpretations

The timer source says “It's set to around 12mins” and “7s are added per charge move used”.
The model treats those approximate measurements as exact parameters: 12×60/0.5 = 1440 turns,
and 7/0.5 = 14 additional turns per resolved charge. Either side counts, including shielded attacks.
Both charges resolving together add 28. No charged-animation turns are added to the turn loop.
This maps the reported allowance to a turn deadline; it is not an independently measured animation clock.
The timer was measured once, in the Dec 2025 era, and is assumed unchanged since. The same post says
"Previously, a timeout vs the Rocket Leaders counts as a loss." Before Dec 2025, a leader timeout is
therefore a Rocket win; Giovanni is treated as a leader. The older timer length and the older grunt
timeout rule are not sourced, so those runs reuse the current values. Results carry this note.

The completed deadline turn can deliver damage and extend the deadline before timeout is checked.
A complete team knockout on that turn takes precedence. Otherwise compare Pokémon left first,
then the sum of each member's `current HP / maximum HP`. Fainted members contribute zero;
untouched reserves contribute one. Exact rational comparisons preserve ties. Equal scores draw.
This interpretation of HP% is explicit: the source does not specify sum of member fractions versus
pooled raw HP. Results mark timeout as `ended_by="timeout"`, never a knockout.

`max_turns` is a separate observation limit. If it truncates a battle, the winner stays unset and
`ended_by="observation_limit"`. It is not another timeout or acceptance rule.

## Executable PvPoke checks

Pinned commit: `426e5e9f39d3a027849698fb2f5edd9df6056cbf`, MIT. Run
`uv run python tools/parity/pvpoke_battle_parity.py`.

```text
Battle.js parity: 514 cases; 20817 turns; 0 mismatches (HP, energy, actions, damage)
Battle.js 3v3 component parity: 3 cases; 0 mismatches (activation order, per-side shields, first three charged hit/shield outcomes)
```

The first comparison retains every prior 1v1 case and compares each turn's actions, HP, energy and
nominal damage. The public core has no hooks enabled. A separate offline test also compares its
rows to a one-member Rocket sequence with extra Rocket options off, under both turn-rule settings.

The additional oracle executes native `Battle.emulate`, `step`, `processAction`, `useMove` and
`forceSwitch`, plus the pinned **entire Player.js**, including shared shield inventory methods.
A deterministic timer queue runs browser interval/timeout callbacks without waiting in real time.
It retains their scheduled order and native phase transitions. Injected decisions choose charges,
shields and the next live slot; no PvPoke AI decisions are asserted. Player priority is zero on both
sides, matching the Python core. The Pokemon adapter also runs native `fullReset` and
`resetBattleStats`, alongside the methods documented in the turn report. Initial shields are set to
two for these team cases. Native fullReset starts energy at zero. Sources, including Player.js,
are hash-checked before execution.

Three full 3v3s cover a player sweep, a Rocket sweep and replacements on both sides. The comparison
projects activation order with remaining side shields at each arrival, final per-side shield inventory,
and each side's first three resolved charged hit/shield outcomes. Hit damage here is actual HP lost,
capped by remaining HP, on both sides of the comparison. This checks the one-damage shield override
and the third unshielded charge. Single-turn fast moves keep those hit observations unambiguous.
These are executable **component** comparisons. They do not compare full 3v3 timelines, final HP,
energy, replacement timing or emulator wall time. No hand trace is presented as JavaScript parity.
PvPoke supplies no evidence for any Rocket-only rule.

## Offline checks and remaining gaps

The full offline suite before these rules: `1608 passed, 4 skipped, 46 xfailed, 39 xpassed in 2.23s`.
After these rules: `1672 passed, 4 skipped, 46 xfailed, 39 xpassed in 2.44s`.
There are 64 new passing rule checks and no new expected failures. The existing network block remains active.

Strict expected failures retain reviewed CP mismatches (including the October TL40 Gallade hypothesis),
F4's Ducklett mismatch in damage/calculator reconstruction, and F3's recorded remaining-HP mismatch.
They still require review if they start passing. Weak-source non-strict outcomes remain reported;
39 XPASS results do not upgrade their evidence. The four skips and all previous outcomes are unchanged.
F3 still ends in a double knockout at 0 HP against 1 recorded. F1's weak one-HP Snubbull result still
reproduces under both old tables and both explicit fast-move sensitivities.

Hand traces cover each era's charged/faint pauses, both pause readings and both trigger modes for
charges and faints, the six-safe/seven-sneaks window, each era's slip-in and simultaneous-charge rows,
the old leader timeout, per-era grades in results, pending fast moves, overlapping suppression, shield inventory across replacements, all player shield policies,
charged timing disabled, both damage scales, timeout count/HP/tie decisions, and fixed-order wins/losses.
Every arithmetic input is synthetic and stated. No constant, formula, fixture or input was fitted.

Recorded in-game checks remain necessary: Rocket charge readiness and unshielded damage, pause frame
counts including manual switches, and the timer warning against a count of charged attacks.
Post-2025 HP and damage evidence, Giovanni battle counts, simultaneous-charge measurements, effects,
forms and Mega interactions remain open as described in the verification ledger. These estimates do
not enable the calculator or CLI to claim additional validation.
