# Stats checks

Stats only. The simulator remains unvalidated. No target, table entry, rounding rule,
or constant was adjusted to obtain a match.

## Results

Counts are individual CP readings, retaining repeated publications. Expected fail
and Unexplained partition Mismatched. Both categories use fixed `xfail(strict=True)`
marks. Unavailable means a tested lookup error, not a CP match. New mismatches fail
normally; an improvement to a marked reading produces strict XPASS.

| Variant | Matched | Mismatched | Expected fail | Unexplained | Weak (reported) | Unavailable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| venonic-2023 | 149 | 1 | 0 | 1 | 5 | 16 |
| fugerappi-2023 | 123 | 30 | 0 | 30 | 5 | 13 |
| flyfunner-old-50-2025 | 147 | 0 | 0 | 0 | 4 | 20 |
| flyfunner-lower-2023 | 0 | 0 | 0 | 0 | 0 | 171 |
| dec-2025 | 13 | 0 | 0 | 0 | 0 | 0 |
| october-tl40-hypothesis:fugerappi-2023 | 13 | 0 | 0 | 0 | 0 | 0 |
| october-tl40-hypothesis:flyfunner-lower-2023 | 12 | 1 | 1 | 0 | 0 | 0 |

The 158 old readings run under both 2023 old tables and the retrospective
TL50 alternative. The lower table has none of their levels. The 13 October TL70
readings run under dec-2025 and all old alternatives. Every old TL70 lookup fails
because no old table lists it. Venonic additionally omits the three TL47 readings;
the retrospective alternative additionally omits TL41 and TL47. No fixture was
relabelled. There are no December-labelled CP readings in the corpus.

The separate TL40 comparisons test the October source's hypothesis explicitly,
using a different trainer-level input in the test only. No production lookup maps
TL70 to TL40. Rounded fugerappi TL40 matches 13/13; the lower table's 1.26502
matches 12/13 and produces Gallade 10215 instead of 10214. The December TL70
float32 value matches all 13, including Gallade. These checks do not establish
equivalence of the entire October and December tables. They also do not test the
float32 cast: fugerappi's 1.265 in double precision matches the same 13, and no
reading exercises any dec-2025 level other than TL70. The cast follows the source
text; only unit tests check it.

| Battle target | venonic-2023 | fugerappi-2023 |
| --- | --- | --- |
| F1-metagross-hp | Pass: 163 | Pass: 163 |
| F2-cyndaquil-hp | Pass: exact 100.33158, battle 100 | Pass: exact 100.33, battle 100 |

F1's exact player HP is 163.17638041906605, independent of Rocket table. F2's
measured bracket is 100 to 100.99999. These are the only recorded/measured,
expected-pass battle records that need no damage calculation. F2 has no applicable
TL41 lookup in the lower table or retrospective TL50-only alternative; dec-2025
is outside this old-regime battle's scope.

## Source disagreements and decisions

- [Venonic 122pfk8](https://www.reddit.com/r/TheSilphRoad/comments/122pfk8/)
  publishes only TL41, 45, 49, 50, with values ending in 0.00002. These are kept
  literally; no trend line extends the table.
- [fugerappi 184iqov](https://www.reddit.com/r/TheSilphRoad/comments/184iqov/)
  publishes 43 three-decimal values, TL8–50. Those decimal values are kept
  literally. The author does not prescribe converting this table to float32.
  TL32 and TL48 retain the exact lost-data warning. A comment by Venonic says
  exact float32 values were not resolved and warns of rounding issues in CP.
- [Flyfunner 12ib623](https://www.reddit.com/r/TheSilphRoad/comments/12ib623/)
  **does have a table**: 15 estimated values with min/max bounds, plus a TL40
  reference (16 entries total). The named table selects the published estimate
  column and preserves every bound, remaining-float count, and complete row.
  TL34's estimate 1.116755 is below its own minimum 1.11676025 (maximum
  1.11677086). It is not repaired or replaced by a midpoint. There are no
  acceptance readings at these levels.
- [Flyfunner 1puc05x](https://www.reddit.com/r/TheSilphRoad/comments/1puc05x/)
  publishes the full TL8–80 table. It says the configuration uses three-decimal
  values read as floats, illustrates 1.191 becoming 1.19099998, and describes
  discrete float steps. `dec-2025` therefore converts each published decimal
  through `struct.pack/unpack('f')`. It does not round all later arithmetic to
  float32. The source explicitly says the old values differed from three-decimal
  float casts. The complete precision paragraph is quoted in `rcpm.json`.
- That same paragraph retrospectively gives old TL50 as **1.31502044**. This is
  a third published alternative, `flyfunner-old-50-2025`, with only that level.
  Its eight-decimal literal is preserved, following the old-table convention;
  no missing level is supplied. It reproduces Steelix 11357 where Venonic's
  1.31502 produces 11356. This alternative was taken from the source, not fitted
  from Steelix. Neither 2023 table was modified.
- Rocket CP uses exact scaled HP, while battle HP is floored. The HP floor
  inside the formula occurs before rCPM and rank. The attack-IV floor follows
  the March formula; the post labels its IV equation `ATK`, but the
  surrounding IV definition and attack equation identify it as `ATK_IV`.
  No supported competing attack-IV formula was found in the cited sources.
- The March discussion uses rational shadow modifiers 6/5 and 5/6 when reversing
  damage. The pinned PvPoke constants are decimal literals 1.2 and 0.83333331 in
  [DamageCalculator.js lines 8–9](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/DamageCalculator.js#L8-L9).
  The latter is not exact 5/6. Both literals are exposed unchanged for the damage code; neither
  is folded into player or Rocket stats, and neither is additionally cast here.
  Damage precision belongs to the damage code. There is no shadow stat ambiguity in
  the CP calculation.
- Player attack and defence remain unrounded. Player battle HP and standard CP
  have minimum 10, as in pinned Pokemon.js lines 382 and 400–401. Rocket HP and
  CP follow the March equations without importing a player minimum. The `cp`
  function accepts already scaled totals and unfloored stamina. Form is explicit
  metadata; purified IVs are supplied by the caller without a hidden +2 change.
- All base stats come from the pinned `species_moves.json`. Comparisons with
  cached December 2022 and March 2023 PvPoke game masters found no changed base
  stats for the CP species covered. No historical stat adjustment was made.
- Only null ranks try all three choices, requiring exactly one match. Null-rank
  readings are `weak` in the corpus, so they are reported and never gate: a rank
  recovered by fitting is a consistency check, not evidence for a rank multiplier.
  Staraptor 11100 and Murkrow 6145 each match leader uniquely under Venonic and the
  retrospective TL50 value.

## Failures

Readings whose corpus `status` is `weak` (the Cacnea 4436/4435 conflict, the
Cyndaquil 3579 cell its author disowns, and the two unstated-rank readings) run
with non-strict xfail marks: their results are printed, but they never gate.
[stats_expected_failures.json](stats_expected_failures.json) keeps one entry with a
source quote: Gallade's published `(-1)` under the October TL40 hypothesis. That
reading itself is a target, and the December table reproduces it.

Every unexplained row, observed CP, predicted CP, rank, and source is listed in
[stats_review.json](stats_review.json). Venonic has only Steelix 11357 → 11356. The retrospective alternative has none.
fugerappi has Steelix and these 29 one-CP misses (zero-based row indices in
`cp_readings.json`):

| Row | Species | Observed → predicted |
| ---: | --- | --- |
| 5 | Onix | 3907 → 3906 |
| 11 | Gyarados | 12096 → 12095 |
| 15 | Amoonguss | 8416 → 8415 |
| 18 | Dragonite | 14913 → 14912 |
| 26 | Rhyperior | 17589 → 17588 |
| 29 | Rhyperior (TL47) | 17190 → 17189 |
| 30 | Mewtwo (TL47) | 19277 → 19276 |
| 51 | Crobat | 10387 → 10386 |
| 61 | Bulbasaur | 3955 → 3954 |
| 74 | Electabuzz | 8313 → 8312 |
| 79 | Onix | 3907 → 3906 |
| 90 | Numel | 3776 → 3775 |
| 91 | Quilava | 5884 → 5883 |
| 92 | Camerupt | 7826 → 7825 |
| 107 | Grimer | 4913 → 4912 |
| 108 | Nidorina | 4678 → 4677 |
| 109 | Muk | 9810 → 9809 |
| 110 | Sceptile | 10838 → 10837 |
| 119 | Gloom | 6009 → 6008 |
| 121 | Wailmer | 5231 → 5230 |
| 124 | Makuhita | 2914 → 2913 |
| 135 | Kingdra | 12445 → 12444 |
| 147 | Abomasnow | 8420 → 8419 |
| 151 | Spoink | 4763 → 4762 |
| 153 | Dusclops | 5673 → 5672 |
| 160 | Machamp | 10917 → 10916 |
| 163 | Kingdra | 10375 → 10374 |
| 168 | Hypno | 7448 → 7447 |
| 169 | Dragonite | 14913 → 14912 |

The one-CP misses are consistent with the published tables' precision difference,
but that is not a source-documented explanation for each reading. They retain
`UNEXPLAINED – needs review`, not a source-anomaly exemption.

## Player CPM cross-check

The table is copied verbatim from pinned PvPoke Pokemon.js `cpms`, with its MIT
notice packaged alongside it. Whole levels 1–55 were compared read-only with
`PLAYER_LEVEL_SETTINGS.cpMultiplier` at the game-master URL above. The full
unlicensed game master was not saved. Every difference over 1e-9 is listed in
[player_cpm_crosscheck.json](player_cpm_crosscheck.json), including both values
and their signed difference: **49 differences**, maximum absolute difference
2.9109191057585804e-8 (level 16). Interpreting the game-master decimal literals as
float32 removes all differences over 1e-9. The PvPoke table remains unchanged.
All 54 half-level values match `sqrt((c1²+c2²)/2)` within 1e-9.

## Reproduction and hygiene

Validation: `uv run pytest -q` passes with 1,192 passed, 32 strict xfails
(31 unexplained, 1 source-documented), 6 non-strict weak xfails, and 8 non-strict
xpasses (weak readings that match a CP). Lookups at a trainer level a table lacks are
a separate test that asserts the lookup raises; they never count as a match.
Both pre-commit invocations pass. A wheel build and isolated offline import from
that wheel verify both JSON resources and the packaged MIT notice. Every stored
rCPM source quote was checked against the cached post verbatim.

```sh
uv run python tests/test_sim_stats.py
uv run pytest -q
pre-commit run --all-files
pre-commit run --files src/pogo_analyzer/sim/__init__.py src/pogo_analyzer/sim/stats.py src/pogo_analyzer/sim/data/player_cpm.json src/pogo_analyzer/sim/data/rcpm.json src/pogo_analyzer/sim/data/PVPoke-LICENSE tests/test_sim_stats.py tests/fixtures/sim/stats_expected_failures.json tests/fixtures/sim/stats_review.json tests/fixtures/sim/player_cpm_crosscheck.json tests/fixtures/sim/stats_report.md
```

The runtime uses only the standard library and `importlib.resources`. Tests use no
network or ignored cache. The existing autouse network block is unchanged. Hatch's
package selection includes the data directory in wheels. Reddit fetches used the fixture README's
Arctic Shift endpoints, User-Agent, one-second pause, and ignored cache. No blocked
simulator host was accessed.
