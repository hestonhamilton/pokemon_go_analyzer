# pokemon_go_analyzer

Explore active Team GO Rocket lineups and Pokebattler counter simulations, or tally the counters that appear most often across defenders.

Install with `uv sync`, then run:

```sh
uv run pogo-analyzer lineups
uv run pogo-analyzer counters --character 'Fire grunt' --slot 1 --top 10
uv run pogo-analyzer counters --defender WEEZING_SHADOW_FORM --tier RAID_LEVEL_1 --format json
uv run pogo-analyzer tally --character grunt --top 5
```

Character selectors match whole words or prefixes of at least 3 letters, e.g. `--character gio`.

Exit codes:

- 0: ok
- 2: bad arguments
- 3: blocked or rate-limited
- 4: request budget spent
- 5: network or bad reply
- 6: cache error
- 7: no matching character

Counter requests run sequentially at least two seconds apart, use a 24-hour cache (including missing IDs), a default budget of 80 network requests, and a descriptive User-Agent. Requests mirror the parameters of Pokebattler's default Rocket view; sorting happens locally, so there is one request per defender per slot setting per day whatever the sort. `--cache-dir` and `--max-requests` adjust the cache and counter request budget. Lineup sources have a separate cache.

CSV output carries no credits line (it goes to stderr), so credit Pokebattler, WatWowMap event-info and PvPoke when sharing a saved CSV; `--credits-column` adds a `source` credit to every CSV or table row.

Counter simulations: [Pokebattler](https://www.pokebattler.com), through its documented public API ([developer page](https://www.pokebattler.com/developers)); Pokebattler asks for attribution when results are published. Lineups: [WatWowMap event-info](https://github.com/WatWowMap/event-info) (MIT). Species data, and the simulator's damage formula, type chart and player CP multipliers, which are ported from it: [PvPoke](https://github.com/pvpoke/pvpoke) (MIT, copyright 2019 pvpoke; notice in `src/pogo_analyzer/sim/data/PVPoke-LICENSE`). See [docs/](docs/) for mechanics and source notes.

## Lineup calculator

`calc` computes conditional matchup arithmetic locally with the existing stats and damage formulas.
It reads only the two GitHub raw sources used by `lineups`, through the source cache. It makes no
counter-service requests. It uses Trainer Battle move stats, not raid stats. No runtime dependencies
are needed.

```sh
uv run pogo-analyzer calc --character 'Fairy grunt' --slot 2 --trainer-level 50 \
  --attacker metagross --level 50 --ivs 15/15/15 --fast BULLET_PUNCH --charged METEOR_MASH
uv run pogo-analyzer calc --defender snubbull --rank grunt --trainer-level 50 \
  --rcpm-table venonic-2023 --team team.json --format json
```

Character matching works like `counters`. Rank is derived from the character: grunt 1, leader 1.05,
Giovanni 1.15. Explicit defenders require `--rank grunt|leader|giovanni`; their rows leave `character` blank. Use base species: PvPoke `_shadow` and `_mega` IDs are refused on both sides. `--slot` restricts character
pools; on an explicit defender it labels the row. `--trainer-level` is required. `--rcpm-table` defaults
to `dec-2025`. Choices are published point tables: `venonic-2023`, `fugerappi-2023`,
`flyfunner-old-50-2025`, and `dec-2025`. Sparse tables retain their missing levels. The lower-level
interval study is excluded. A missing level is an error, with no interpolation or replacement.

Individual attackers require `--attacker`, `--level`, `--ivs A/D/H`, `--fast`, and one or two repeated
`--charged` options. Species and moves accept PvPoke IDs or unambiguous names. `--shadow` and
`--purified` are mutually exclusive. Normal is the default. Purified uses plain stats; supply the IVs
after purification. Rocket damage always applies both shadow modifiers as appropriate. Reported
attack and defence totals are before shadow modifiers, which damage applies exactly once.

`--team FILE` replaces all individual attacker options. Its schema is a nonempty JSON list. Each
object requires `species` (string), `level` (number, half levels 1–55), `ivs` (an `A/D/H` string or an
object with integer `atk`, `def`, `hp`, each 0–15), `fast` (string), and `charged` (one or two strings).
Optional `shadow` and `purified` are booleans and cannot both be true. For example:

```json
[
  {
    "species": "metagross",
    "level": 50,
    "ivs": "15/15/15",
    "fast": "BULLET_PUNCH",
    "charged": ["METEOR_MASH", "PSYCHIC"],
    "shadow": true
  }
]
```

Each row represents one attacker configuration, Rocket slot, species and hypothetical Rocket fast
move. `--sort` defaults to `fast_turns_to_ko`, ascending. Other choices include `fast_hits_to_ko`,
`fast_damage`, `fast_damage_per_turn`, `rocket_fast_damage`, `rocket_fast_damage_per_turn`,
`ko_on_incoming_hit`, `turns_survived`, `rocket_cp`, and `attacker_hp` (all ascending).

| Columns | Meaning | Grade dependencies |
| --- | --- | --- |
| `attacker`, `level`, `ivs`, `form`, `attacker_attack`, `attacker_defence`, `attacker_hp` | Given build and the player totals used | Player formula path (HP checked by F1): fixture-exact on grunt rows when the gate passes |
| `defender` | Rocket species from the lineup source or `--defender` | No fixture checks the lineup; model |
| `fast_move` | Attacker's chosen move | fixture-exact only if today's stats equal a dated snapshot the targets used; otherwise parity-only |
| `rocket_attack`, `rocket_defence`, `rocket_hp` | Rocket totals (HP floored for battle) | fixture-exact only for a grunt, a gate table, and a trainer level where passing targets checked that quantity (HP at TL41 or TL50; attack and defence at TL50); otherwise cp-only |
| `rank`, `rank_multiplier`, `rcpm_table`, `rocket_cpm`, `trainer_level` | Rocket scaling inputs, shared by every Rocket stat | fixture-exact only at a level where targets checked every quantity (TL50). TL41 rests on one floored HP reading, which bounds its rCPM only to about 1%, so it is cp-only there |
| `rocket_cp` | Display CP, calculated with unfloored stamina | CP readings; cp-only at best |
| `fast_damage`, `fast_hits_to_ko` | Damage per hit; ceil(Rocket HP / damage) | Weakest of player path, Rocket stats and the fast move's snapshot match |
| `rocket_fast_damage`, `ko_on_incoming_hit` | Incoming damage; ceil(player HP / damage) | Same, with the Rocket fast move's snapshot match; KO occurs on the counted hit |
| `fast_damage_per_turn`, `rocket_fast_damage_per_turn` | Nominal damage / (cooldown / 500 ms) | Damage plus PvPoke duration metadata; parity-only at best |
| `fast_turns_to_ko`, `turns_survived` | Fast hits × move turns, counting the KO hit | Behaviour assumptions; model |
| `charged` | Each chosen charged move: move, unshielded damage, energy cost, fast moves to energy from zero | Move/cost parity-only; damage parity-only; energy count model; aggregate model |
| `rocket_charged` | Every pool charged move and unshielded damage; excluded from all turn counts | Move availability model; damage parity-only; aggregate model |
| `character`, `slot`, `rocket_fast_move`, `moveset_pool` | Encounter labels and hypothetical move availability | Model |
| `row_grade` | Weakest cell in the row | Model when any timing or pool assumption is present |

The four grades, strongest first, are defined in `src/pogo_analyzer/sim/data/grades.json`. A grade never
claims more than its weakest input; when in doubt the weaker grade applies.

- **fixture-exact:** reproduced on this run by the recorded or measured pre-Oct-2025 grunt targets
  (F1, F2, F4, F5). It needs all of: the gate passed; a grunt; for Rocket stats, a gate table
  (`venonic-2023` or `fugerappi-2023`) at a trainer level where passing targets checked that same
  quantity (the TL41 target checks HP only); for damage, move
  stats equal to a dated snapshot the passing targets used. Today's PvPoke values often differ from
  those snapshots (Bullet Punch 6 → 7, Smack Down 12 → 11), and then the damage is parity-only. This
  grade does not claim a recorded battle for each possible build.
- **cp-only:** Rocket stats from a table, trainer level or rank backed by CP readings only. This covers
  every Rocket cell under `dec-2025` (Rocket stats from Oct 2025 on are backed by CP readings only), the
  TL50-only `flyfunner-old-50-2025` table, gate-table levels no target used, and every leader and
  Giovanni cell: no recorded leader or Giovanni hit count exists yet.
- **parity-only:** pinned PvPoke code or metadata, with no passing battle target for this quantity
  with these move stats. This includes charged damage on both sides; no modern measurement establishes
  Rocket charged damage. Damage and player stats fall to this grade when the gate fails.
- **model:** unverified behaviour, move availability or lineup species. Timing, energy counts in
  battle, Rocket move pools and the lineup's species receive this grade.

If the gate fails, no cell is fixture-exact.

Cells take the weakest grade of their dependencies. Conditional damage assumes the named move is
present; it does not prove move availability. The Rocket move pool copies every PvPoke species
`fastMoves` and `chargedMoves` entry, flagging `eliteMoves` and `legacyMoves` membership. Event-info
lists species, not moves. Neither source establishes Rocket-specific Frustration additions. No extra
Frustration is added; each pool reports whether its PvPoke list already includes it.

Every run recomputes recorded/measured `expected_pass` battle targets using the dated move and
species fixtures. `--fixtures-dir` defaults to `tests/fixtures/sim` relative to the package source.
The fixtures are not in the wheel, so validation needs a source checkout (or `--fixtures-dir`); an
installed package without them reports UNVALIDATED, naming the missing files. The gate is pinned to
the reviewed corpus (`src/pogo_analyzer/sim/data/acceptance_pin.json`): the exact target IDs, the
open-discrepancy IDs and a SHA-256 of their records, and a SHA-256 of what decides each target (its source, inputs and observation,
and the base stats, types and dated moves it uses). The target count, 44, is a code constant
(`validation.EXPECTED_TARGETS`), not read from the pin. Free prose such as evidence notes is not
pinned. A trimmed, padded, swapped or edited target set, or a deleted discrepancy, reports
UNVALIDATED.

The pin catches accidental or unreviewed drift. It does **not** stop a deliberate change made together
with a regenerated pin: that is defended only by the owner reviewing the pin's diff. `.github/CODEOWNERS`
marks the file but does not enforce review here (the owner's own account opens these PRs, so GitHub
cannot require the owner's review). `tools/fixtures/acceptance_pin.py` shows the id changes and the
old and new hash, refuses to write while the gate fails (ignoring the pin), refuses to drop an open
discrepancy without `--allow-discrepancy-removal`, and refuses a count change without
`--allow-count-change` (the gate then still fails until `EXPECTED_TARGETS` changes in a
reviewed commit). A failure names the failing targets.
Every target must pass under both gate tables, `venonic-2023` and `fugerappi-2023`, which publish every
trainer level the targets use. Targets that the TL50-only `flyfunner-old-50-2025` covers must pass too;
a level it lacks is listed as not covered and is never filled from another table. Missing fixtures, a
failing target, or a gate-table gap produce **UNVALIDATED** with the reason. Success prints
`Validated against N pre-Oct-2025 battle targets under venonic-2023 and fugerappi-2023 (...); M open
discrepancies: <ids>`.
All open discrepancies and their reasons remain in every report when the fixture files are readable;
deleting one, or changing its status, fails the gate.
Today all 44 targets pass under both gate tables. The TL50-only table covers 43 and passes them; it has
no TL41 for F2. Missing entries never count as passes.

`--format table|json|csv` always carries the validation label, both source fetch times, and credits.
Table output shows the headline columns (character, slot, Rocket species and fast move, attacker and
fast move, damage both ways, hits and turns, Rocket HP and CP, row grade), with a grade row under the
header and a legend; JSON and CSV carry every column. Event-info's `_alola` form names map to PvPoke's
`_alolan` IDs. A lineup species PvPoke lacks is listed as `NOT CALCULATED` (JSON: `unresolved`), never
dropped silently. JSON starts with `validation_label`, then includes validation
records, sources, limitations, grades, and per-cell `{value, grade}` results, including nested charged
move cells. CSV has a validation/source/discrepancy preamble, then column names, a second header of
grades, and values only. Read CSV from its `attacker,` header onward; legends and credits go to stderr.
Composite CSV values are JSON strings without grade wrappers. Table/CSV column legends use the
weakest grade across displayed rows; JSON retains each cell's own grade.

These are fast-only calculations. They ignore charged attacks in turn counts, pauses, shields,
switching and charged timing. Charged damage assumes full charge and no stat changes. Energy counts
start at zero and ignore real battle behaviour. There is no turn loop or win prediction. Mega and
special-move mechanics are unsupported. See the [verification ledger](docs/simulator-verification.md)
for the supporting evidence and unresolved gaps.

## Rocket simulator (estimate)

`sim` enumerates every lineup and hypothetical moveset for each matched character. The supplied team
has one to three members in fixed order. These win rates and slots swept are **estimates** until the
[in-game checks](docs/simulator-verification.md#minimum-in-game-checks) are done.

```sh
uv run pogo-analyzer sim --character 'Fairy grunt' --battle-date 2026-11-14 --trainer-level 50 \
  --attacker metagross --level 50 --ivs 15/15/15 --fast BULLET_PUNCH --charged METEOR_MASH
uv run pogo-analyzer sim --character Cliff --battle-date 2026-11-14 --trainer-level 50 \
  --team team.json --format json
uv run pogo-analyzer sim --character Cliff --battle-date 2026-11-14 --trainer-level 50 \
  --team team.json --per-slot --slot 1 --exclude-elite-legacy --format csv
```

Team input, character matching, rank from tier, source caching, `--rcpm-table`, `--fixtures-dir`,
`--cache-dir`, and `--format table|json|csv` follow `calc`. `--battle-date YYYY-MM-DD` is required.
It selects the rules era; moves come from the cached source, not a historical move table.
Dates before 22 July 2019 (when Rocket battles began) are rejected. Dates after the newest rules
source (29 Sep 2026) are flagged `extrapolated forward`.
`--exclude-elite-legacy` removes PvPoke elite and legacy moves from Rocket pools and reports the filter.
Unresolved species remain visible. Incomplete results explicitly cover resolved options only.
An empty slot prevents a full battle result.

Full battles start with full HP and zero energy. They use the default Rocket rules, the player's
first affordable charged move and first-two shield policy. Every lineup has equal weight because
no appearance-rate source exists. Rows sort by win rate descending, mean player HP fraction left
descending, then mean turns ascending. Draws count as not-wins. Timeout outcomes are separate.
A Rocket faint is credited to the player member active on that turn, including a double knockout.

`--per-slot` produces a 1v1 grid and attacker/slot aggregates. It **ignores carried-over shields and
HP between slots**. Each matchup starts with fresh shields and full HP. `--slot 1|2|3` filters only
this grid. Every result carries its era, rules, ledger flags, evidence and grades. A failed acceptance
gate prints UNVALIDATED. Large characters continue with stdlib multiprocessing only after exceeding
120 seconds; result order is preserved. It uses at most four processes in all: three workers plus the
parent, which collects and aggregates results (fewer workers on machines with fewer than four CPUs). See the [win rate report](tests/fixtures/sim/winrate_report.md)
for metric definitions, grade dependencies, pool sizes, runtimes and model choices.

## Top-N counters (estimate)

`topn` ranks solo attackers using the offline calculator and simulator. Every number is an
**estimate**; screening and enumeration do not validate battle mechanics.

```sh
uv run pogo-analyzer topn --character Cliff --k 30
uv run pogo-analyzer topn --all --battle-date 2026-11-14 --level 40 --level 50 \
  --candidates metagross,metagross_shadow --exclude-elite-legacy --format json
```

Stage 1 screens every released PvPoke species and fast × single charged moveset with a solo 1v1
grid. Its score is the mean of the three slot win rates; draws are not wins. The grid ignores
carried-over shields and HP between slots, so screen scores are not lineup win rates. Each species
keeps its best moveset per level; ties at the K cut break by species id alphabetically.
Stage 2 battles the top `--k` species (default 30) against every full lineup, then ranks by
win rate, HP left and turns, following `sim`.

IVs are 15/15/15; levels default to 40 and 50, ranked separately (`--level` is repeatable).
Trainer level defaults to 50 and rCPM to `dec-2025`. Shadows are separate candidates built with
the calculator's base-species shadow form. Mega and Primal forms and calculator rejections appear
in `skipped` with reasons. Elite and legacy membership is recorded for each move;
`--exclude-elite-legacy` filters both attacker and Rocket pools. `--candidates` restricts source
species IDs or names.
Battle date defaults to today's local date; `--battle-date` overrides it. Output echoes the date
and `battle_date_source` (`default: run date` or `explicit`). Source caching, rules, player policies
and evidence limitations follow `sim`. Duplicate selected character names fail before battles run.

Output is JSON only. `characters[].finalists` contains ranked lists keyed by level, with full sim
metrics, headline grades, screen rates and calculator per-cell graded `calc_rows`. Each screen keeps
its slot aggregates' rules grades, flags and labels, plus its own headline grade using the weakest
calculator stat grade across that build's slot options and any incomplete-pool warning. With `--all`,
the union of finalists is battled against every available character. `overall` gives `all`,
`grunts`, and `leaders` (including Giovanni) views with `results` keyed by level. Each entry uses
equal weight per character, a model choice with no encounter-rate source. Coverage lists missing
characters and states how many are covered; an empty resolved slot excludes its character rather
than counting it as zero. Overall rows retain the estimate label and union of contributing ledger
evidence. Incomplete pools and the weakest contributing grades remain explicit. Before battles run,
stderr shows planned stage-1 1v1 battles (builds × slot options, summed over available characters)
and maximum stage-2 lineup battles (K × levels × lineups, summed over available characters).
`--all` adds union completion battles. Screening is serial; full enumeration reuses `sim`'s capped
workers: at most three workers plus the parent. Progress goes to stderr.

## Precompute reports (estimate)

`precompute` runs the same two-stage top-N engine for every Rocket character and writes
reports for a later static-site step. Every number is an **estimate**. The level, trainer
level, K, candidate, elite/legacy, rCPM, cache and validation options have the same defaults
and validation as `topn` (levels 40 and 50, trainer level 50, K 30).

```sh
uv run pogo-analyzer precompute --out reports --battle-date 2026-11-14
uv run pogo-analyzer precompute --out cliff-reports --battle-date 2026-11-14 \
  --character Cliff --workers 2 --nice 10 --level 40 --k 30
```

All files use compact JSON and are replaced atomically after flushing and syncing,
with permissions `0666 & ~umask` (0644 under umask 022):

- `characters/<slug>.json`: shared top-N provenance, policies, notes and grades; that
  character's unresolved/unavailable records; its `character` report with finalists per
  level and graded `calc_rows`; and its reuse `key`.
- `overall.json`: shared provenance plus the top-N `all`, `grunts`, `leaders`, `coverage`
  and `weighting_note` sections, with a reuse `key`. `--character` restricts matching
  characters and skips this file.
- `manifest.json`: written last, listing character names, slugs, ranks, files, keys,
  computed/reused/unavailable status and runtimes; overall status; tool version, code
  hash and shared reuse key; parameters, run date, era and validation label; source URLs,
  fetch times and body SHA-256 hashes; worker count, resulting niceness, total runtime, and parent/maximum
  child peak RSS in KiB. RSS is the process-lifetime high-water mark reported by the OS.

A character file is reused when its key matches, unless `--force` is supplied. Shared
inputs hash the gamemaster body (canonical JSON), all installed package `.py` and `.json`
bytes in sorted path order, result parameters (including rCPM table and candidate
identities), era, extrapolation flag and the entire validation dictionary. Each character
key combines that shared key with its name, rank, resolved species and move IDs per slot,
unresolved entries and the defender records it uses. An event-info change affecting only
one character therefore recomputes only that character. Overall is recomputed if any
character was computed, its file is missing, or its key (the hash of sorted character
name/key pairs) differs.

The raw battle date does not invalidate reuse; the era and extrapolated flag do. Character
and overall files and their manifest entries record `computed_for_battle_date`,
`computed_for_battle_date_source` and `valid_for: {era, extrapolated}`. Reused files retain
their original computation dates, row dates and source fetch times without being rewritten.
The manifest's `battle_date` and `battle_date_source` describe the current run separately.

When `--character` targets a directory with a manifest, matching shared keys allow its
entries to be merged while preserving other characters and the overall entry. If any
selected character changes or is recomputed, the retained overall entry is marked `stale`;
run all characters to refresh it. A different shared key causes an error before any report
is written, even with `--force`; use a separate output directory or run all characters.

An exclusive nonblocking lock on `DIR/.lock` rejects concurrent runs into the same
directory. A failed run can leave completed character files beside an older manifest.
Consumers must verify each file's `key` matches its manifest entry and skip stale overall
results. Orphaned files for removed characters are not pruned; publish only files listed
in the manifest and skip dotfiles (locks and any temporary files left after a forced exit).

`--workers` defaults to 3; 1 runs entirely in the parent. Higher values use that many
worker processes plus the parent to screen candidates, battle finalists and complete
overall coverage, preserving deterministic result order. Full battles inside workers
run serially. Values must be between 1 and the CPU affinity count (`os.sched_getaffinity(0)`),
falling back to `os.cpu_count()` where affinity is unavailable; precompute has no sim worker
cap. `--nice` defaults to 10 and adds that amount to the process niceness before work;
workers inherit it. `--nice 0` leaves priority unchanged. Progress goes only to stderr.
The nightly timer is a separate machine setup step that passes `--workers 12` at idle
priority; this command does not install a timer. The `sim` and `topn` defaults are unchanged.

## Development checks

- `uv run pytest -q` runs offline. An autouse fixture blocks the network, and the calculator and
  simulator tests read small cached source extracts under `tests/fixtures/`.
- `pre-commit run --all-files` runs ruff, the JSON and secret checks, and a commit-message check.
  Both it and `pytest` are required checks on `main`.
- The PvPoke parity tools are verification aids, not test dependencies. They need Node.js. The
  first run downloads the pinned, checksummed MIT sources into `.cache/fixture-sources/`, and
  later runs read that cache only:
  - `uv run python tools/parity/pvpoke_damage_parity.py`: exact raw and final damage, and every
    type combination;
  - `uv run python tools/parity/pvpoke_battle_parity.py`: the 1v1 turn loop turn by turn, plus
    the native 3v3 component cases.
- `tools/fixtures/acceptance_pin.py` regenerates the acceptance pin. Only the owner's review of
  its diff defends a pin change.
