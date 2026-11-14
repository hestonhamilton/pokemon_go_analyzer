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
| Turn timing | [Turn report](battle_report.md), pinned PvPoke | Ledger j grades unchanged | `turn_rules=Rules()` preserves PvPoke. Existing `ledger_j_next_turn_charged` and `ledger_j_both_charged_fire` remain opt-in estimates. Selecting an old pause era does not select a complete historical turn system. |
| Charged and faint pauses | [9db table](https://9db.jp/pokemongo/data/24341), [research notes, section 4](../../../docs/rocket-pokemon.md#4-how-the-rocket-side-battles) | k: measured-reproduced | `pauses=True`, `pause_reading="9db"`; lengths below. `pauses=False` disables the extra suppression. |
| Manual switch pause | Same table; [cwizz1](https://www.reddit.com/r/TheSilphArena/comments/1vyspr1/) | k: conflicting | Stored in each reading. No manual switch action exercises it. |
| Charged pause trigger | Same sources | k: measured-reproduced for pause length; the trigger is an **interpretation** | 9db's row reads "enemy freeze time (immediately after a charged move activates)" and does not say whose charged move. `pause_trigger="player_charged"` is this project's reading of that row and the 9db default. `"any_charged"` follows cwizz1's wording. `None` resolves to the reading's default and the result reports the resolved name. |
| Alternate pause reading | cwizz1, Aug 2026, excerpt preserved in the research notes | k: charged/faint measured-reproduced; switch conflicting | `pause_reading="cwizz1"`: charged 7, faint replacement 7, manual player switch effectively 6; defaults to `any_charged`. The reported general switch count is 7. |
| Rocket charged timing | Ledger l; [research notes, section 4](../../../docs/rocket-pokemon.md#4-how-the-rocket-side-battles) | l: assumed, **unverified** | `rocket_charged="when_ready"` takes the supplied charged move at the first eligible input with enough energy. `"never"` uses fast moves only. No timing measurement supports the default. |
| Rocket charged damage | [Ledger l](../../../docs/simulator-verification.md#ledger) | l: default 1.0 assumed; 0.5625 measured-once and outdated (2019); **unverified** | `rocket_charged_damage_scale=1.0` or `0.5625`. The ledger does not identify a retrievable original for the 2019 number or specify rounding placement. This is an evidence gap. |
| Shields | Sources and policies below | m: observed in play for NPC inventory/use; player choice is a model choice, not a measurement | `rocket_shields`, `player_shield_policy`, `player_shield_threshold`. Both resolved policies accompany every result. |
| Timer and timeout winner | [freezyefc, Jan 1 2026, two linked videos](https://www.reddit.com/r/TheSilphRoad/comments/1q13cga/) | n: measured-once | `timer=True`: 1440 turns plus 14 for each resolved charged attack on either side. `timer=False` disables it. |

The caller supplies species, moves and stat tables. Nothing fetches lineups or selects missing inputs.
A full battle is three against three. Teams of one or two are allowed for isolated rule checks.
`battle_date` is a required keyword. An ISO date or calendar date selects the pause era.
Explicit `battle_date=None` selects the static September 2026 default. It never consults today's date.
The result carries both the supplied date and selected era. Move dating remains the caller's responsibility.
Player attack selection defaults to `ChargedWhenReady`, taking the first affordable move in caller order.
An injected player policy can choose charges instead. This is a model decision, with no claim to optimal play.
Rocket members accept at most one charged move; an empty list represents a fast-only input.

## Dated pauses

The dated evidence includes the original Japanese rows in `sim/data/rocket_rules.json`.
The page is dated September 29 2026; its table also retains a March 12 update label.
Its columns identify months, with no precise changeover days. Selection boundaries December 1 2025
and September 1 2026 are explicitly **approximate**, not measured transition dates.

| Era | Charged move (player only by default) | Rocket faint and replacement | Unused manual player switch |
| --- | ---: | ---: | ---: |
| Before Dec 2025 | 5 | 7 | 7 |
| Dec 2025 | 8 | 12 | 12 |
| Sep 2026, default | 7 | 7 | 9 |

Values are turns, converted from the source's seconds at 0.5 seconds per turn.
The alternative preserves cwizz1's “7 turns after any charged move or switch” and the research notes'
effectively-six-turn own-switch qualification. The live cwizz1 thread could not be retrieved;
that excerpt's provenance is the checked-in research notes. It is not a new independent confirmation.
The 9/7/6 manual-switch disagreement is retained. No value was chosen by matching a battle fixture.

## Pause interpretation and exact turn convention

A trigger resolves on turn t. The Rocket submits no new move on t+1 through t+N, inclusive.
Its next eligible input is t+N+1. A replacement arrives after the completed faint turn t;
the replacement itself consumes no extra simulated turn. The default faint trigger requires a
Rocket replacement. Under cwizz1, a player replacement also triggers the seven-turn pause.
That extension interprets “any ... switch”; it is not a separately measured player-faint count.

The pause suppresses **new inputs only**. Keeping an already submitted fast move in flight is an
**interpretation**, retaining PvPoke's due/flush/cancellation rules. It does not guarantee a hit after
a charged knockout: the core still cancels that fainted attacker's fast reply. For example, a five-turn
Rocket fast move submitted on t1 remains queued when a surviving Rocket takes a player charge on t2.
PvPoke flushes it on t3. The extra pause blocks new inputs on t3–t9; input resumes on t10.

PvPoke independently suppresses inputs on the turn after a charged sequence. Both restrictions
apply to the same turns, so the larger applies, never the sum. A t1 player charge with a seven-turn
pause allows the next Rocket input on t9, not t10. Player inputs resume on t3. Repeated pause triggers
extend the inclusive deadline using `max(old_deadline, t+N)`. With the next-turn charge option,
a charge queued on t1 resolves on t2, so the seven paused turns are t3–t9.

On a faint, finish all eligible resolutions before replacement. Clear pending actions and both active
cooldowns, following the emulator's faint handling (Battle.js 553–610). Surviving HP and energy stay
with their Pokémon. The next member uses its supplied starting HP and energy. Shields stay with the side.
The zero-additional-turn replacement is a model convention. The emulator's switch/animation schedule
is not claimed as turn parity for this convention.

## Charged damage interpretation

Every result with a resolved Rocket charged attack includes ledger l and `flags=("unverified",)`.
The timing and damage evidence are reported separately. `never` does not acquire l merely because a
move was available. Cancelled or merely queued attacks do not extend the timer or trigger pauses.

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
The inventory is two per side. Grunts retain that inventory but never spend it. Leaders and Giovanni
spend it on the first two resolved player charged attacks, including lethal ones. A third is unshielded.
`rocket_shields=False` disables that policy for core comparison. A shielded charged attack deals 1,
through damage.py's existing override (pinned Battle.js 1194–1200).

The owner chose `player_shield_policy="first_two"` as the default. It shields the first two incoming
Rocket charges. `"never"` spends none. `"threshold"` spends an available shield when unshielded damage
is at least `player_shield_threshold * current_HP`. The parameter defaults to 0.5 and must lie in (0, 1].
These player policies are explicit assumptions chosen by the owner, not observed Rocket AI rules.
Inventories survive replacements on either side. An attack reduced to 1 can still knock out a member
with only 1 HP; its shield remains spent for the rest of the team.

## Timer interpretations

The timer source says “It's set to around 12mins” and “7s are added per charge move used”.
The model treats those approximate measurements as exact parameters: 12×60/0.5 = 1440 turns,
and 7/0.5 = 14 additional turns per resolved charge. Either side counts, including shielded attacks.
Both charges resolving together add 28. No charged-animation turns are added to the turn loop.
This maps the reported allowance to a turn deadline; it is not an independently measured animation clock.
The same timeout policy is used for every pause era; the source describes the newer behavior.
Old-era runs therefore do not reconstruct the historical automatic timeout loss.

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
After these rules: `1660 passed, 4 skipped, 46 xfailed, 39 xpassed in 2.37s`.
There are 52 new passing rule checks and no new expected failures. The existing network block remains active.

Strict expected failures retain reviewed CP mismatches (including the October TL40 Gallade hypothesis),
F4's Ducklett mismatch in damage/calculator reconstruction, and F3's recorded remaining-HP mismatch.
They still require review if they start passing. Weak-source non-strict outcomes remain reported;
39 XPASS results do not upgrade their evidence. The four skips and all previous outcomes are unchanged.
F3 still ends in a double knockout at 0 HP against 1 recorded. F1's weak one-HP Snubbull result still
reproduces under both old tables and both explicit fast-move sensitivities.

Hand traces cover each era's charged/faint pauses, both pause readings and trigger modes, pending fast
moves, overlapping suppression, shield inventory across replacements, all player shield policies,
charged timing disabled, both damage scales, timeout count/HP/tie decisions, and fixed-order wins/losses.
Every arithmetic input is synthetic and stated. No constant, formula, fixture or input was fitted.

Recorded in-game checks remain necessary: Rocket charge readiness and unshielded damage, pause frame
counts including manual switches, and the timer warning against a count of charged attacks.
Post-2025 HP and damage evidence, Giovanni battle counts, simultaneous-charge measurements, effects,
forms and Mega interactions remain open as described in the verification ledger. These estimates do
not enable the calculator or CLI to claim additional validation.
