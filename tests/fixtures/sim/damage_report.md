# Damage checks

Ordinary move damage is ported without fitted constants, rounding changes, or
fixture edits. All available acceptance targets match. The simulator remains
unvalidated: the open discrepancies, the stats checks' unexplained rows, and the
wider acceptance gate remain open.

## Pinned source and precision

Every PvPoke reference below uses commit
`426e5e9f39d3a027849698fb2f5edd9df6056cbf` (MIT). The existing packaged
`src/pogo_analyzer/sim/data/PVPoke-LICENSE` covers the port and type extract.
Sources were fetched from `raw.githubusercontent.com` at that exact SHA and
cached under `.cache/fixture-sources/pvpoke-<sha>/`, preserving these paths:

- `src/js/battle/DamageCalculator.js`: [constants, lines 1–10][constants];
  [damage, lines 20–76][damage]; [type multiplication and chart, lines 138–280][types].
  The multiplier constants and type chart are both defined in this file.
- `src/js/pokemon/Pokemon.js`: [STAB, lines 701–707][stab];
  [effective stats and stage formula, lines 2091–2130][stages];
  [shadow constants assigned, lines 2250–2255][shadow].
- `src/data/gamemaster.json`: [maximum stages and divisor, lines 5–8][settings];
  [Confusion metadata, lines 47141–47152][confusion].
- `src/js/battle/Battle.js`: [shield damage override, lines 1194–1200][shield].
  `src/js/GameMaster.js` was also cached; [lines 853 and 911–913][metadata]
  default and copy `isMegaMove` metadata.

The exact ordinary `damage()` expression, evaluated left to right, is:

```text
floor(power * stab * (attackStat / defenseStat) * effectiveness
      * chargeMultiplier * megaMultiplier * 0.5 * BONUS) + 1
```

| Constant | Pinned literal |
| --- | --- |
| BONUS | 1.2999999523162841796875 |
| STAB | 1.2000000476837158203125 |
| SUPER_EFFECTIVE | 1.60000002384185791015625 |
| RESISTED | 0.625 |
| DOUBLE_RESISTED | 0.390625 |
| SHADOW_ATK (stats.py) | 1.2 |
| SHADOW_DEF (stats.py) | 0.83333331 |
| MEGA_BONUS, levels 1–4 | 1, 1.10000002384185791015625, 1.2000000476837158203125, 1.2999999523162841796875 |

These are JavaScript Number literals. Python uses binary64 operations with no
extra float32 casts of intermediates. The stats module's explicit rCPM table precision choices
remain unchanged. In particular, shadow defence is not replaced with exact 5/6.
The unit knife edge uses neutral power 20 and equal attack/defence: raw
**12.999999523162842**, damage **13**. Replacing BONUS with 1.3 gives raw 13 and
damage 14. This demonstrates why shortened constants cannot be substituted.

`attackStat = attack * (stageMultiplier * shadowAttackMultiplier)`, and likewise
for defence. Stages use divisor 4, with `(4 + stage)/4` above zero and
`4/(4 - stage)` otherwise. For stages -4 through +4 the multipliers are
`1/2, 4/7, 2/3, 4/5, 1, 5/4, 3/2, 7/4, 2`. Rational divisions are evaluated,
not replaced by rounded thirds or sevenths. Defensive types multiply in their
listed order. `none` contributes 1. STAB is applied once if either attacker type
matches. Every Rocket side is explicitly flagged shadow, per ledger g.
The API accepts integer stages -4 through +4. Stage changes and their clamping
belong to the turn loop, not this stat-input calculation.

## Acceptance results by rCPM variant

Counts include F1's six acceptance records, F2 HP from the stats module, F4's 31
`expected_pass` records, and F5's six records. Only recorded/measured plus
`expected_pass` records enter this table. Open discrepancies and weak records are
separate. There are **zero unexplained damage mismatches** and no
`UNEXPLAINED – needs review` marks in the damage tests. New acceptance mismatches fail normally;
reviewed mismatch marks must be fixed IDs, not derived from current predictions.

| Variant | Passed | Failed | Unexplained | Unavailable |
| --- | ---: | ---: | ---: | ---: |
| venonic-2023 | 44 | 0 | 0 | 0 |
| fugerappi-2023 | 44 | 0 | 0 | 0 |
| flyfunner-old-50-2025 | 43 | 0 | 0 | 1 |

The retrospective table has no TL41 entry, so F2 is a tested lookup error plus
an explicit skip, not a fabricated HP prediction. All 42 damage-dependent
acceptance records pass under each of the three tables. F1 player HP 163 also
passes under all three. F2 battle HP 100 passes under the two 2023 tables.

F1 incoming Tackle/Bite/Charge Beam are **4 / 11 / 8** under every old variant.
Snubbull has battle HP **134**; Bullet Punch does **19**, so **7 × 19 = 133 < 134**.
Kirlia has battle HP **102**, Bullet Punch does **18**, and `ceil(102/18) = 6`.
Kirlia's HP/damage here are predictions supporting its recorded count, not new
fixture observations.

All F4 predicted counts are identical across the three old variants:

| Rocket | Tyranitar | Rhyperior | Rampardos | Shadow Tyranitar |
| --- | ---: | ---: | ---: | ---: |
| ducklett | 5 | 5 | 5 | 5 (recorded 4; expected fail) |
| starly | 3 | 3 | 3 | 3 |
| natu | 4 | 4 | 4 | 3 |
| staravia | 5 | 5 | 4 | 4 |
| golbat | 9 | 9 | 7 | 7 |
| weedle | 3 | 3 | 2 | 2 |
| skorupi | 6 | 6 | 5 | 5 |
| shuckle | 10 | 10 | 9 | 9 |

F4 therefore reproduces **31/32** cells; its one mismatch is the recorded
Ducklett cell, an open discrepancy. Golbat's `9*` is tested as the fixture's
numeric count 9. Third-slot rows excluded from the corpus are not reintroduced.

## F5: all attack IVs, without filling unknown defence/HP IVs

Roserade is level 50 with dated Razor Leaf **power 10**. Every attack IV **0–15**
is computed per record, per variant. The following complete partitions are
identical under **venonic-2023, fugerappi-2023, and flyfunner-old-50-2025**.
The acceptance assertion requires **each of 13, 14, and 15**, not merely one
convenient IV, to give the recorded count. All six assertions pass.

| Rocket | Recorded hits | Consistent attack IVs | Other IVs → predicted hits |
| --- | ---: | --- | --- |
| totodile | 6 | 4–15 | 0–3 → 7 |
| wailmer | 8 | 0–15 | none |
| croconaw | 9 | 4–15 | 0–3 → 10 |
| wailord | 12 | 3–15 | 0–2 → 13 |
| hippopotas | 8 | 0–15 | none |
| diglett_alolan | 4 | 0–15 | none |

Thus the corpus's assumed attack-IV range 13–15 gives the observed count for every row. It does not identify
the attack IV uniquely; **4–15** is consistent with all six rows together.
No missing player defence or HP IV is replaced with a perfect or zero IV.

## F4 open discrepancy: Shadow Tyranitar versus Ducklett

The recorded attack IV is **14**. Ducklett's battle HP is **135** under every
old variant. The relevant pre-floor boundary is **33**, yielding damage 34 and
four hits. At IV 14, damage is 33: four hits deal only 132, so five are required.

| Variant | Attack IV | Raw damage before floor/+1 | Raw minus 33 | Damage | Hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| venonic-2023 | 14 | 32.899042345227592 | -0.100957654772408 | 33 | 5 |
| venonic-2023 | 15 | 33.023189674832224 | +0.023189674832224 | 34 | 4 |
| fugerappi-2023 | 14 | 32.899542710890643 | -0.100457289109357 | 33 | 5 |
| fugerappi-2023 | 15 | 33.023691928667581 | +0.023691928667581 | 34 | 4 |
| flyfunner-old-50-2025 | 14 | 32.899031337354110 | -0.100968662645890 | 33 | 5 |
| flyfunner-old-50-2025 | 15 | 33.023178625419597 | +0.023178625419597 | 34 | 4 |

The source states attack IV 14, and at IV 15 the recorded 4 hits reproduce. So a
misreported IV is one plausible explanation, but the source is not overruled: IV 15
is a labelled sensitivity check, never a replacement input. The cell is an
`open_discrepancy` in the corpus, tested as **three strict xfails** (one per
table) so a model change that reproduces it surfaces as XPASS.
The roughly 0.101 shortfall at IV 14 is not erased by using the pinned literals.
Neither the shadow multiplier nor the rCPM is fitted to cross the boundary.

## Weak cross-checks and source-status disagreements

| Record group | Table | Predictions | Result (non-gating) |
| --- | --- | --- | --- |
| F1 calculated Bullet Punch / Snubbull HP / HP after 7 | each old variant | 19 / 134 / 1 | 3/3 match per variant |
| F7 Mega Y / Shadow Mewtwo versus Nidorina | dec-2025 TL76 | 3 / 4 hits | 2/2 match; see alternatives below |
| F8 Snorlax HP / Force Palm +0,+1,+2 / shielded Power-Up Punch | dec-2025 TL80 leader | 285 / 17,21,25 / 1 | 5/5 match |
| F9 Kartana versus Magikarp | dec-2025, TL/IV sweep | conditional 1–3 hits | matches 3 only for the ranges below |

Weak tests use `xfail(strict=False)` with the source's `status_reason`; matching
ones appear as non-strict XPASS. They never become acceptance targets. F9 uses a
report-only test because neither trainer level nor attack IV is known. These
conditional results must not be counted as a single validated observation.

**F3:** the "8 Bullet Punches" is the author's expectation, so the corpus grades it
`calculated` and `weak`; it reproduces (damage **19**, HP **134**, `ceil(134/19) = 8`)
under all three tables, as a cross-check only. The recorded 1 HP survival
(`F3-metagross-remaining`, an `open_discrepancy`) is skipped under all three
tables: remaining player HP depends on turn order and needs the turn loop.

### F7 Mega alternatives (ledger q remains unresolved)

PvPoke's Mega rule is **not a blanket boost to all moves**. DamageCalculator.js
lines 40–41 require both the attacker `mega` tag and move `isMegaMove` metadata.
Confusion lacks that metadata. The production API exposes both flags and Mega
level explicitly. Enabling the attacker Mega rule therefore leaves these
Confusion numbers unchanged. Unit tests separately exercise the metadata gate
and all four literal Mega multipliers.

| Attacker | Player level | Mega rule off: raw / damage / hits | Mega rule on: raw / damage / hits |
| --- | ---: | --- | --- |
| mewtwo_mega_y | 50 | 49.293590874625984 / 50 / 3 | 49.293590874625984 / 50 / 3 |
| mewtwo_mega_y | 52 | 49.880209254761319 / 50 / 3 | 49.880209254761319 / 50 / 3 |
| mewtwo | 50 | 43.396787480278192 / 44 / 4 | 43.396787480278192 / 44 / 4 |

Nidorina has battle HP **145**. Level 50 is the fixture's base input. Level 52
is a separately reported author-claimed effective level, not an automatic stat
change or a selected best-buddy interpretation. Pokemon.js [lines 294–297][mega-cap]
set a level cap of 52 under a level-4 Mega condition; this does not establish a
Rocket-specific automatic level gain. Unknown buddy status is not filled.
Neither flag nor level alternative changes the hit count. The fixture therefore
settles neither ledger q nor an old/new rCPM equivalence. Old tables have no
TL76 entry; no old TL50 value is substituted for TL76.

### F9 missing trainer level and attack IV

Use dated Razor Leaf **power 9**, level-50 Kartana, every attack IV 0–15, and
every published dec-2025 trainer level 8–80. No trainer level is selected.

| Trainer level | Predicted hits across IVs 0–15 | IVs consistent with inferred 3 hits |
| --- | --- | --- |
| 8–19 | 1 | none (fail) |
| 20–21 | 1–2 | none (fail) |
| 22–50 | 2 | none (fail) |
| 51 | 2–3 | 0–3 (conditional pass) |
| 52 | 2–3 | 0–5 (conditional pass) |
| 53 | 2–3 | 0–8 (conditional pass) |
| 54 | 2–3 | 0–10 (conditional pass) |
| 55–80 | 3 | 0–15 (conditional pass) |

## Interpretation calls and scope

- Port the ordinary **`damage()` line 68** operation order. `damageByStats()`
  line 104 puts Mega before effectiveness; that separate helper is not used.
- Resolve effective stats before damage: multiply stage by shadow, then multiply
  the stat. Do not round attack/defence, cast all operations to float32, or apply
  shadow a second time to power. Stats from stats.py remain unmodified.
- The data file copies the 18 defensive trait lists verbatim from
  DamageCalculator.js. Unknown type names raise an error instead of silently
  inheriting PvPoke's empty default traits. `none` is the documented neutral slot.
- `chargeMultiplier` is exactly **1**. No Nice/Great scaling is invented. Charged
  damage uses the same ordinary formula; a caller-supplied charged shield
  decision overrides final damage to **1**, as in Battle.js. Raw diagnostics
  retain the pre-shield, pre-floor amount. No shield policy is implemented.
- Mega rules require their two source conditions. No raid aura bonus is imported.
  The code does not infer effective levels or buddy status from Mega level.
- The caller supplies **move power and type**. The test helper requires an
  exact-date history snapshot and errors when absent. Bullet Punch 6, Smack Down
  12, and Razor Leaf 10 are historical inputs, never today's 7, 11, and 9.
- `hits_to_ko` uses exact positive-integer ceiling division against **battle HP**,
  not unfloored stamina. F1's rocket remaining HP needs only supplied hit count
  and damage; F3's player remaining HP needs the turn loop and is deferred.
- This API handles ordinary power moves. PvPoke's percentMaxHP branch and
  species-specific form changes (e.g. Aegislash) are not represented by these
  inputs and are explicitly outside the API. No turn loop, pauses,
  Rocket charged multiplier, or Rocket shield rules were added.

## Verification and hygiene

[`tools/parity/pvpoke_damage_parity.py`](../../../tools/parity/pvpoke_damage_parity.py)
executes the **actual pinned** DamageCalculator.js and the Pokemon.js methods it
uses under Node, not a second handwritten damage formula. With seed 426, all
**1,296** combinations of nine attack stages, nine defence stages, two attacker
shadow flags, two defender shadow flags and four Mega levels match **raw binary64
values and final damage exactly**. Random powers, stats and types vary across these
cases. All **6,156** move/dual-type combinations (18 × 18 × 19, including a `none`
second slot) also match exactly. Node and the fetched sources are not test or
runtime dependencies.

The species extract also matches historical cached game masters for all
**30 species/snapshot pairs** used by these battles, for both base stats and
types. No current base stat or type silently replaces a different historical
value. A wheel built offline includes damage.py, types.json, and the MIT notice;
an isolated import from that wheel successfully calculates damage and reads
the packaged chart.

The offline tests use only committed fixtures and packaged resources. The
existing autouse network block is unchanged. The runtime remains stdlib only.

```sh
uv run python tests/test_sim_damage.py
uv run pytest -q
pre-commit run --all-files
uv run python tools/parity/pvpoke_damage_parity.py   # needs Node.js
```

`uv run pytest -q`: **1,348 passed, 4 skipped, 41 xfailed, 35 xpassed**. The 41
xfails are 35 strict (the stats checks' 32 reviewed cases and the 3 Ducklett open
discrepancy variants) and 6 non-strict weak CP readings. Every XPASS is a non-strict
weak check: 27 weak battle records and F7 alternatives, and 8 weak CP readings that
match. The four skips are F3 remaining HP under three
tables and F2 under the TL50-only table.

[constants]: https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/DamageCalculator.js#L1-L10
[damage]: https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/DamageCalculator.js#L20-L76
[types]: https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/DamageCalculator.js#L138-L280
[stab]: https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/pokemon/Pokemon.js#L701-L707
[stages]: https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/pokemon/Pokemon.js#L2091-L2130
[shadow]: https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/pokemon/Pokemon.js#L2250-L2255
[settings]: https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/data/gamemaster.json#L5-L8
[confusion]: https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/data/gamemaster.json#L47141-L47152
[shield]: https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1194-L1200
[metadata]: https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/GameMaster.js#L853-L913
[mega-cap]: https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/pokemon/Pokemon.js#L294-L297
