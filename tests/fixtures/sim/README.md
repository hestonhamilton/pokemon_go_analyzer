# Offline Rocket acceptance fixtures (slice S0)

These are community measurements and published claims, cited and quoted per record.
They are acceptance targets for a future simulator, not proof of a formula. This
slice contains no simulator, damage calculation, stat calculation, or network test.
`expected_pass` describes the intended future acceptance result; it does not mean
that S0 ran or validated a battle model. Published calculations and inferred
counts are distinguished from direct observations by each record's `basis`: only
`recorded` and `measured` records may be `expected_pass`. A published calculation
reproducing under our model is circular, so it is never an acceptance target.

## Files and schemas

All JSON is UTF-8. Unknown inputs are `null`, never filled with perfect IVs or a
trainer level chosen to fit a formula. Species use PvPoke `speciesId`; moves use
PvPoke `moveId` (uppercase with underscores). Shadow players use the base species
and `form: "shadow"`; Mega Mewtwo Y uses `mewtwo_mega_y` and `form: "mega"`.
Rocket species always refer to the non-shadow form.

### `battles.json`

A list of 58 records, one per retained numeric target:

```json
{
  "id": "F1-bite-taken",
  "fixture": "F1",
  "source": "https://www.reddit.com/r/TheSilphRoad/comments/13puajs/",
  "evidence": "damage values of 4(\\*15), 11(\\*8) and 8(\\*1) from respective moves",
  "battle_date": "2022-12-03",
  "regime": "rcpm-old",
  "trainer_level": 50,
  "rocket": {
    "species": "snubbull", "rank": "grunt", "slot": 2,
    "fast_move": "BITE", "charged_move": null
  },
  "player": {
    "species": "metagross", "form": "shadow", "level": 43.5,
    "ivs": {"atk": 15, "def": 9, "hp": 12},
    "fast_move": "BULLET_PUNCH", "charged_move": null,
    "stat_stage": {"atk": 0, "def": 0}
  },
  "observed": {
    "kind": "damage_per_hit_taken", "value": 11, "hits": null,
    "move": "BITE"
  },
  "basis": "recorded",
  "status": "expected_pass", "status_reason": null
}
```

All example fields are required except `observed.move`; the example is the real
abbreviated from the real record. Extra fields are documented
below. `evidence` is an exact substring of the archived selftext or comment body;
Markdown escapes and asterisks in table rows are retained. A table-row quote is read
under the original column headers, described in the source inventory below.

- `id`: unique stable string, prefixed with `fixture` and a hyphen.
- `fixture`: F1, F2, F3, F4, F5, F7, F8, or F9. F6 and F10 are deferred.
- `battle_date`: ISO calendar date, with date precision and proxies described below.
- `regime`: `rcpm-old` or `rcpm-dec-2025`. This is a source-era label, not a
  calculated multiplier. No battle in this file is from October/November 2025.
- `trainer_level`: integer 1–80 or `null` if unstated.
- `rocket.rank`: `grunt`, `leader`, or `giovanni`; `slot`: 1, 2, 3, or `null`.
  `fast_move` is a move ID or `null`; `charged_move` is currently always `null`.
- `player.species`, `form`, `level`, `fast_move`, and `charged_move` may be `null`
  when unknown. Known forms: `normal`, `shadow`, `purified`, `mega`. `level` is the
  base Pokemon level, including half levels. Each of `ivs.atk`, `ivs.def`, and
  `ivs.hp` independently permits an integer 0–15 or `null`.
- `player.stat_stage`: `atk` and `def` integers from -4 to +4; neutral is 0.
  Optional `mega_level` and `effective_level` preserve the author's stated mega
  inputs without interpreting their mechanics. F7 is base level 50, mega level 4,
  effective level 52; base level is not overwritten with 52.
- `observed.kind`: `damage_per_hit_dealt`, `damage_per_hit_taken`, `hits_to_ko`,
  `rocket_hp`, `player_hp`, `remaining_hp_after`, or `survives_hits` (the subject
  was still standing after `value` player fast-move hits; F1's Snubbull after 7). `value` is an integer, not a
  computed stat or a range. `hits_to_ko` stores the count in `value`, not `hits`.
- `observed.hits`: number of player fast-move hits preceding a remaining-HP
  reading, otherwise `null`. F3 does not assert a measured number of Bites.
- `observed.subject`: required for `remaining_hp_after` and `survives_hits`, either `rocket` (F1's
  Snubbull) or `player` (F3's Metagross). Other HP kinds identify their own subject.
- `observed.move`: required for per-hit damage to identify the move that dealt
  that damage. `player.charged_move` and optional `observed.shielded` distinguish
  F8's shielded Power-Up Punch from Lucario's Force Palm. That record represents
  the first Punch, with attack stage 0 before the buff; it is not unshielded damage.
- `basis`: where the number comes from. `recorded` is read off the battle by the
  person who fought it (screen, video, or move count). `measured` is derived by the
  author from in-game readings (F2's HP bracket). `calculated` is the author's model
  output (F1's Bullet Punch 19 and Snubbull 134 HP, all of F8). `inferred` is our
  reading of the text (F9). Counts: 48 recorded, 1 measured, 8 calculated, 1
  inferred. `calculated` and `inferred` records must be `weak`; tests enforce it.
- `status`: `expected_pass`, `expected_fail`, or `weak`. `status_reason` is always
  present and must be a nonempty explanation for `expected_fail` and `weak`;
  otherwise it may be `null`. F5 also explains its attack-IV equivalence here.
- Optional `evidence_note`: provenance, inference, or an input limitation that
  must accompany the quoted text. It is not itself a quote.

### `cp_readings.json`

A list of 171 published readings. Required keys: `trainer_level` (integer),
`species` (PvPoke ID), `rank` (`grunt`, `leader`, `giovanni`, or `null` when
ambiguous), `cp` (positive integer), `regime`, `source` (URL), and `evidence` (exact
quote). Optional `evidence_note` explains contextual level/rank assignments and
ambiguities. Repeated readings from separate publications are intentionally kept.

CP regimes additionally allow **`rcpm-oct-2025`**: the 13 level-70 measurements
published on 16 October 2025 predate December. Calling them `rcpm-dec-2025` would
assert a regime equivalence that their source does not establish. The 13 paired
pre-update level-50 readings keep `rcpm-old`. This extension preserves chronology
without deciding which future rCPM formula should reproduce them.

### `move_history.json`

An object keyed by each of the nine referenced move IDs. Each value is a list of
snapshots sorted by `as_of`, with unique dates:

```json
{
  "BULLET_PUNCH": [{
    "as_of": "2022-12-03",
    "pvpoke_commit": "a6efe554e40f37782f9fb4b85093c08f4bba035e",
    "type": "steel", "power": 6, "energy_gain": 7, "energy": 0, "turns": 2
  }]
}
```

`as_of` is the fixture's reference date, not the date a move changed. Each move
used by a battle has an **exact-date** entry from the game master selected for
that battle date. Every referenced move also has a snapshot for 2026-11-13 from
current master, making 21 snapshots in total. This is a sparse set of dated
snapshots, not a complete change log: do not carry an entry forward to arbitrary
uncovered battle dates. A fixture with no known moves (F2) requires no move entry.

`pvpoke_commit` is the full 40-character SHA. `type`, `power`, `energy_gain`, and
`energy` copy PvPoke's `type`, `power`, `energyGain`, and `energy` without changing
values. `energy` is a positive charged-move cost (0 for fast moves); `energy_gain`
is positive for fast moves (0 for charged moves). `turns` uses PvPoke's `turns`
where present, otherwise `cooldown / 500`, converting milliseconds into PvP
half-second turns. Charged moves retain PvPoke's 1-turn metadata; this is not a
measurement of the charged-attack animation or a Rocket pause.

### `species_moves.json`

A small reference extract, not a complete game master:

```json
{
  "as_of": "2026-07-14",
  "pvpoke_commit": "caafd09972142cb32bd244dd72957d683d7e56f0",
  "species": {
    "snubbull": {"baseStats": {"atk": 137, "def": 85, "hp": 155}, "types": ["fairy", "none"]}
  },
  "moves": {"BULLET_PUNCH": {"type": "steel"}}
}
```

It contains exactly the 138 species referenced by battles **or CP readings** and
nine referenced moves from the game master at the latest fixture date. Base stats
and two type slots are copied verbatim, including PvPoke's `none` second slot for
monotypes. Move entries contain only their types. No Rocket stats are generated.

## Sources, dates, and transcription decisions

All sources were fetched on **2026-11-13**. The local verification plan was read
with `git show task/pogo-sim-plan:docs/simulator-verification.md` (commit
`9d32bddb58749eae5351d885fb6a772d1234b179`); the requested remote ref
`origin/task/pogo-sim-plan` was absent. No git refs or index entries were changed.

| Fixture | Records | Battle/reference date | Evidence and limitations |
| --- | ---: | --- | --- |
| F1 | 9 | 2022-12-03 | [13puajs](https://www.reddit.com/r/TheSilphRoad/comments/13puajs/), Venonic's [correction](https://www.reddit.com/r/TheSilphRoad/comments/13puajs/comment/jlcrysv/), and original [z3qck5](https://www.reddit.com/r/TheSilphRoad/comments/z3qck5/) discussion establish the inputs. The [video](https://www.youtube.com/watch?v=we_gnAzR1UI) title is `Screen Recording 20221203 223715 Pokmon GO`; its upload date is 2023-05-23, not the battle date. **Recorded** (in the author's post, read off the video): Metagross 163 HP, incoming Tackle 4 / Bite 11 / Charge Beam 8, Snubbull still standing after 7 Bullet Punches ("I nearly killed it with 7"), and Kirlia knocked out in 6. The passage is struck through by its author, because their model lacked the 1.3x bonus; the readings were not retracted. **Calculated** (`weak`): Bullet Punch 19, Snubbull 134 HP, and 1 HP left after 7 hits are Venonic's prediction of what the corrected model gives, not readings. An earlier draft also carried Kirlia 18 damage / 102 HP: no source states either, and they matched our own model output, so they were removed. |
| F2 | 1 | 2023-03-26 | Venonic's [Cyndaquil measurement](https://www.reddit.com/r/TheSilphRoad/comments/122pfk8/comment/jdt4hvd/), Min HP / Max HP table: 100 to 100.99999. Level 41 comes from the surrounding discussion; the publication date is a proxy for the unstated actual battle date. Attacker and moves unknown. |
| F3 | 2 | 2023-11-27 | AurumKodEXo's [comment](https://www.reddit.com/r/TheSilphRoad/comments/184iqov/comment/kb0shio/) explicitly supplies level 46.5 and **15/9/12 IVs**, eight Bullet Punches and 1 HP remaining at trainer level 50. Both records keep the requested fixture-level `expected_fail` label; the stated model discrepancy is the HP claim. Date is the comment date, not the 26 November parent-post date. No model was run in S0. |
| F4 | 32 | 2023-01-21 | [cwizz1's measured table](https://www.reddit.com/r/TheSilphRoad/comments/10hihvd/) has **eight**, not seven, eligible rows: Ducklett, Starly, Natu, Staravia, Golbat, Weedle, Skorupi, Shuckle, across four attackers. Thus **32 cells, not about 28**: 31 `expected_pass`, plus Shadow Tyranitar/Ducklett `expected_fail`, reason `knife edge: raw damage 32.90 at attack IV 14`. Entire row quotes retain the original cells and Golbat's `9*`. Its numeric target is 9; the asterisk denotes a breakpoint caveat, not a fractional hit. Specific slot numbers are not stated per row, so `slot` remains null within the source's stated slot-1/2 group. Third-slot **Crobat, Dragonite and Gyarados** (12 cells) are excluded because the author says they implicitly include a charged move. Publication date is used for the historical snapshot. |
| F5 | 6 | 2023-02-01 | Only the measured Roserade column of [cwizz1's table](https://www.reddit.com/r/TheSilphRoad/comments/10qgrga/): Totodile 6, Wailmer 8, Croconaw 9, **Wailord (RL) 12**, Hippopatas 8, Diglett-A 4. `Hippopatas` is transcribed verbatim in evidence and normalized to `hippopotas` for the ID. Wailord's RL-only third-slot row is included; Feraligatr/Hippowdon RL cells are blank and cannot supply counts. Decimal/charged-move rows and estimated/calculated Kartana columns are excluded. Attack IV is null with `expected_pass` and reason `attack IV 13-15 give the same count`, as requested; that equivalence is not calculated in S0. Publication date is a proxy; these are the previous rotation's battles. |
| F7 | 2 | 2026-07-14 | [RestorerForer's selftext](https://www.reddit.com/r/TheSilphRoad/comments/1uwoshu/) states all preserved mega inputs, trainer level 76, Mega attack IV 15, Shadow attack IV 14, and three versus four Confusions. Both are `weak`: no rCPM discrimination, defence/HP IVs not stated. Mega effective level 52 is an author claim. |
| F8 | 5 | 2026-05-30 | [cwizz1's damage-calcs comment](https://www.reddit.com/r/TheSilphRoad/comments/1trpag8/comment/oopajg7/) explicitly says **trainer level 80**, level 50 Lucario with attack IV 15, Snorlax 285 HP, Force Palm 17/21/25, shielded Power-Up Punch 1. These are the author's published **calculations** ("These calcs are done at trainer level 80"), so all five are `basis: calculated`, `weak`. The post links recordings of the strategy; counting Force Palms to the Snorlax knockout in those recordings, at a stated trainer level, would give a recorded target. Defence/HP IVs are not stated for this attacking Lucario; the separate minimal 0/15/13 example is not substituted. |
| F9 | 1 | 2026-03-12 | [cwizz1's comment](https://www.reddit.com/r/TheSilphRoad/comments/1rs03m9/comment/oa3snbr/) says three Magikarp take nine seconds, three seconds each, and identifies Razor Leaf as a two-turn/one-second move. **Three hits per Magikarp is inferred from this timing**, not literally quoted as three hits. One record represents the repeated per-opponent count, with unknown slot, trainer level and IVs; `weak`. |

F6's uncounted Mud-Slap/Counter videos and F10's historical 2019 Yawn numbers are
outside the requested battle-record content. No values were invented for them.
The ledger a–q provides context; this slice does not implement or verify formulas,
timing, shields, mega effects, or the expected-failure explanations.

CP inventory (no fit-based filtering):

- **31 from z3qck5**: one Persian reading in the post; all 27 populated cells of
  AurumKodEXo's grunt/leader/Giovanni table; three level-47 Giovanni readings from
  the linked-video comparison in that same comment. Calculated alternative CPs
  10996/6997 and the repeated level-50 ratio denominators are not new observations.
- **26 from 1o7syt9**: every cell of the 13 paired level-50/level-70 rows. The
  published Gallade **10214 (-1)** is retained; the hypothetical 10215 in the prose
  is not an observed CP. Both columns quote the full original row.
- **114 from 122pfk8**: all 110 numeric readings in Pendergirl4's comments (including
  later Dragonite/Flygon reports and repeated Dragonite 13526), two Venonic
  Cyndaquil `Real CP` cells, and the post's Wailord/Murkrow CP pair. Pendergirl4's
  trainer level 50 is supported by the later exchange about being "set for level
  50 data now?". Unmarked rows normally use the grunt-collection context, not a
  CP formula. Charizard 11339 and Tyranitar 15100 get leader ranks from identical
  explicitly ranked z3qck5 readings; Regice's Giovanni rank is contextual to the
  adjacent Giovanni report. Staraptor 11100 has `rank: null`: its rank is unstated,
  and the same CP is explicitly assigned to Sierra in the paired source. These
  contextual assignments are disclosed per record. Wailord/Murkrow use the
  author's level-41 measurement campaign as context. Cyndaquil's two comments
  print **3247 versus 3579** under `Real CP`; **both are retained**, including the
  apparent typo. Cacnea **4436** in z3qck5 versus **4435** in Pendergirl4's list
  is also retained. Duplicate, contradictory, and potentially misranked source
  claims are evidence to investigate, not values to repair here.

## Collection and reproduction

Reddit post bodies and complete returned comment trees were read through
[Arctic Shift](https://arctic-shift.photon-reddit.com/), using these endpoint
patterns, with User-Agent `pokemon_go_analyzer-fixtures` and a one-second pause
between requests:

```text
https://arctic-shift.photon-reddit.com/api/posts/ids?ids=<id>
https://arctic-shift.photon-reddit.com/api/comments/tree?link_id=<id>&limit=500
```

The ten IDs are `13puajs`, `z3qck5`, `122pfk8`, `184iqov`, `10hihvd`, `10qgrga`,
`1uwoshu`, `1trpag8`, `1rs03m9`, `1o7syt9`. Responses are cached as
`.cache/fixture-sources/<id>-post.json` and `<id>-comments.json`; successful cache
entries are reused. Exact table rows were copied, known excluded rows omitted,
and species labels normalized to the referenced PvPoke IDs. No blocked simulator
services were called. The cache is ignored by the existing `.cache/` rule and is
not needed to run tests. It also holds the collection/transcription scripts and
YouTube metadata used for the F1 date; these are local collection aids, not test
dependencies.

PvPoke history was selected once for each distinct reference date using:

```text
https://api.github.com/repos/pvpoke/pvpoke/commits?path=src/data/gamemaster.json&until=<date>T23:59:59Z&per_page=1
https://raw.githubusercontent.com/pvpoke/pvpoke/<sha>/src/data/gamemaster.json
```

The end of the UTC day is the convention because exact battle timestamps are
unknown. It is a snapshot at that reference date, not a guarantee of when a game
update went live. One additional GitHub request to
`https://api.github.com/repos/pvpoke/pvpoke/commits/master` pinned current master;
the game master was then read by immutable SHA, not a moving raw-master URL.
Commit responses, raw game masters, and the MIT license are cached locally.
Only nine unauthenticated GitHub API calls were needed. Extracts are deliberately
small; complete game masters remain in the ignored cache.

| Reference date | PvPoke game-master commit |
| --- | --- |
| 2022-12-03 | `a6efe554e40f37782f9fb4b85093c08f4bba035e` |
| 2023-01-21 | `57856ed3e9ce36d3a1b911c5af68ade7979ee4ff` |
| 2023-02-01 | `cd32a1b96f5d64ede5b568a571fb0597d2568006` |
| 2023-03-26 | `4a340589148ae377ce933e9a90bad2edb045f38b` (F2 has no known moves) |
| 2023-11-27 | `cd76a046bbe5b6bc089f7ee5ccfab4595f54cc26` |
| 2026-03-12 | `0cb05158b572be22335e22b0adb01308afe112dc` |
| 2026-05-30 | `b0aab555a36dbdcff3386d062e6b5a8eb4a38edb` |
| 2026-07-14 | `caafd09972142cb32bd244dd72957d683d7e56f0` |
| 2026-11-13 (current master) | `426e5e9f39d3a027849698fb2f5edd9df6056cbf` |

**Historical-power requirement:** F1, F4 and F5 are only intended to reproduce
with their contemporary powers. PvPoke confirms **Bullet Punch 6** in December
2022, **Smack Down 12** in January 2023, and **Razor Leaf 10** in February 2023.
The pinned current values are respectively **7, 11, 9**. There was no disagreement
with the brief on those values. No battle outcomes were recomputed to fit them.

## Offline checks

`tests/test_sim_fixtures.py` checks required fields, numeric ranges, enum values,
unique battle IDs, the fixture inventory, the basis counts, that no `calculated` or
`inferred` record is an acceptance target, exact-date move-history coverage,
consistent SHAs, and every species/move reference across all files. It also checks
that the small extract has exactly the referenced species/moves and that CP pairs
and the published Gallade anomaly were retained. No network or ignored cache is
used; the repository's autouse test fixture blocks accidental network access.
These are data/schema tests, not simulator acceptance executions.

```sh
uv run pytest -q
pre-commit run --all-files
```

`pre-commit --all-files` selects tracked files. To check these initially untracked
new files without staging or changing git state, also run the file hooks using
`pre-commit run --files tests/test_sim_fixtures.py tests/fixtures/sim/README.md tests/fixtures/sim/battles.json tests/fixtures/sim/cp_readings.json tests/fixtures/sim/move_history.json tests/fixtures/sim/species_moves.json`.

## PvPoke attribution

`move_history.json` and `species_moves.json` contain selected data from
[PvPoke](https://github.com/pvpoke/pvpoke), `src/data/gamemaster.json`, under the
[MIT License](https://github.com/pvpoke/pvpoke/blob/caafd09972142cb32bd244dd72957d683d7e56f0/LICENSE).
This notice applies to those extracts; it does not change this repository's license.

```text
MIT License

Copyright (c) 2019 pvpoke

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
