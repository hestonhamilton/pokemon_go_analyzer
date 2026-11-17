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
Move stat changes follow PvPoke's default: guaranteed effects always apply, while chance effects
use its fixed meter rather than the game's random roll. PvPoke uses that meter in 1v1 battles;
carrying the player's meter across the three Rocket Pokémon is this project's model choice
(PvPoke's 3v3 mode rolls instead). The Python API alternative
`Rules(stat_stages=False)` disables stat changes.

`--per-slot` produces a 1v1 grid and attacker/slot aggregates. It **ignores carried-over shields and
HP between slots**. Each matchup starts with fresh shields and full HP. `--slot 1|2|3` filters only
this grid. Every result carries its era, rules, ledger flags, evidence and grades. A failed acceptance
gate prints UNVALIDATED. Large characters continue with stdlib multiprocessing only after exceeding
120 seconds; result order is preserved. It uses at most four processes in all: three workers plus the
parent, which collects and aggregates results (fewer workers on machines with fewer than four CPUs). See the [win rate report](tests/fixtures/sim/winrate_report.md)
for metric definitions, grade dependencies, pool sizes, runtimes and model choices.

## Exact solo engine

`sim/solo.py` reuses deterministic battle prefixes at Rocket replacements.
It gives exactly the same results as the reference simulator, including floats.
`topn` stage 2, the pause band and overall union completion use it for solo teams.
It supports every era and rank, default policies, and default Rocket rules with any
valid pause-length override and either stat-stage setting. Multi-member teams, other rules and
custom battle functions use the reference simulator. The `sim` command uses the reference too.
When `topn` supplies a trial runner, engine rows report
`execution: {"mode": "exact solo engine", "workers": 1}`.
This counts workers within one aggregate; precompute still maps builds across workers.

Offline CI compares battles and full aggregates against the reference.
On the sources of a measured full run, overall completion for all 26 characters fell
from about 150 core-hours to about 55 CPU-minutes (14 minutes on 4 workers). All 22,750
build × character results were identical. Stage 1 was then the larger part of a
per-character run; it is now the sampled lineup screen described below.

## Top-N counters (estimate)

`topn` ranks solo attackers using the offline calculator and simulator. Every number is an
**estimate**; screening and enumeration do not validate battle mechanics.

```sh
uv run pogo-analyzer topn --character Cliff --k 30
uv run pogo-analyzer topn --all --battle-date 2026-11-14 --level 40 --level 50 \
  --candidates metagross,metagross_shadow --exclude-elite-legacy --format json
```

Stage 1 screens every released PvPoke species and fast × single charged moveset with 32 whole
battles against real lineups: 32 distinct lineups drawn with a seed from the character's pools and
the level, so every build and moveset meets the same battles and runs repeat (characters with 32
or fewer lineups play each once). HP, energy and
shields carry from one Rocket Pokémon to the next, as in a real battle. The score is the share of
those battles won; draws are not wins, and screen scores are not lineup win rates. Per species and
level, the top 2 movesets by fewest turns and the top 2 by HP left go forward. Species are ranked by
their best moveset, and the finalists are the union of the top `--k` (default 30) by each order;
species level with either K-th are kept. On 16 Nov 2026 data (Ghost and Fire grunts, Cliff and
Giovanni, levels 40 and 50) this kept all of the true top 10 in both orders, where the earlier 1v1
grid screen kept as few as 2 of 8.
Stage 2 battles those builds against every full lineup, then ranks by win rate in whole-percent
bands, then turns (or HP left), following `sim`; lists show each species once per order, with its
best moveset in that order. The quick 1v1 grid (`screen` on each finalist) is computed for
finalists only and shown on Battle details.

Leader and Giovanni lists also include builds with two charged moves, for the finalist
species and their finalist fast moves. Only pairs that keep one of the species' finalist
charged moves are tried (that kept 47 of 51 gains in the pgo-c82 experiment). Every such pair is
first screened on the level's 32 shared sample lineups, and only each species' best 2 pairs
per order are battled in full (same lists as battling every pair on 17 Nov data, at 24% of
the cost). They battle with
the `bait_then_best` player policy, a model of how players play: the cheapest move while the
leader's two shields last, then only the move that hits the current Rocket Pokémon hardest.
These rows carry `charged_moves` (two ids), `player_policy` and a pause band, rank in the same
list, and are left out of the overall union and views. Grunts don't shield, so they get none.
See [docs/teams-and-two-charged.md](docs/teams-and-two-charged.md).

Each per-character finalist also gets a `pause_band`: full-battle win rates at
`--pause-band 6,8` (the default) plus the era's charged-attack pause length read from
the rules data. Extra runs override both charged-attack and faint pauses; manual-switch
pauses stay unchanged. The era entry reuses the normal result, and ranking and all other
metrics keep the era rules. The band records its tested `turns`, `win_rate` per length,
`min`, `max`, and `sensitive` when the range exceeds `--pause-threshold` (default
`0.15`, 15 percentage points; the threshold is a model choice, not a source value),
with the threshold and a note naming verification ledger row k. Override battle evidence
labels the length as a sensitivity assumption, not a source value.
Choose other comma-separated integers from 1 to 20, or use `--pause-band none` to disable.
The default costs about two extra stage-2 passes per character; screening is unchanged.
Overall-completion builds get no extra passes, and overall rows carry no band.

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
stderr shows planned stage-1 sample lineup battles (builds × 32, summed over available characters)
and maximum stage-2 lineup battles (at most 8K builds per level: the top K species in each of 2
orders, each sending its top 2 movesets in each order; × levels × lineups, summed over available
characters).
`--all` adds union completion battles. Screening is serial; full enumeration reuses `sim`'s capped
workers: at most three workers plus the parent. Progress goes to stderr.

## Precompute reports (estimate)

`precompute` runs the same two-stage top-N engine for every Rocket character and writes
reports for a later static-site step. Every number is an **estimate**. The level, trainer
level, K, candidate, elite/legacy, rCPM, cache and validation options have the same defaults
and validation as `topn` (levels 40 and 50, trainer level 50, K 30).

`--pause-band` is shared with `topn`: default `6,8`, or `none` to disable. Per-character
reports include the band at a cost of about two extra stage-2 passes per character;
overall rows have no band. The normalized band setting is recorded in `params` and
included in the reuse key, so changing it recomputes reports.

```sh
uv run pogo-analyzer precompute --out reports --battle-date 2026-11-14
uv run pogo-analyzer precompute --out cliff-reports --battle-date 2026-11-14 \
  --character Cliff --workers 2 --nice 10 --level 40 --k 30
```

Use frequent runs to refresh per-type lists as inputs change. Compute the overall union
once a week; that step can take about 14 hours:

```sh
# Frequent runs
uv run pogo-analyzer precompute --out reports --skip-overall
# Weekly full run
uv run pogo-analyzer precompute --out reports
```

`--skip-overall` works only for all-character runs. It never changes `overall.json` or
runs union completion. The manifest records `skip_overall` separately from `params` and
reuse keys. A weekly full run reuses unchanged character files without screening again.
The retained overall has status `reused` when its file matches the current inputs,
`stale` when an older overall remains, or `skipped` when no previous overall is available.
With `--force`, character files recompute and an existing overall is marked `stale`.
The site shows a matching stale overall with a warning and its own computed-for battle
date. It explains that the per-type lists have changed since the overall was computed.

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
Consumers must verify each file's `key` matches its manifest entry and label retained
stale overall results. Orphaned files for removed characters are not pruned. Publish only
files listed in the manifest and skip dotfiles (locks and temporary files left after a forced exit).

`--workers` defaults to 3; 1 runs entirely in the parent. Higher values use that many
worker processes plus the parent to screen candidates, battle finalists and complete
overall coverage, preserving deterministic result order. Full battles inside workers
run serially. Values must be between 1 and the CPU affinity count (`os.sched_getaffinity(0)`),
falling back to `os.cpu_count()` where affinity is unavailable; precompute has no sim worker
cap. `--nice` defaults to 10 and adds that amount to the process niceness before work;
workers inherit it. `--nice 0` leaves priority unchanged. Progress goes only to stderr.
A separate machine setup step runs a daily full run (overall included) with
`--workers 12` at idle priority. This command installs no timer.
The `sim` and `topn` defaults are unchanged.

## Static site (estimate)

Render a precompute directory without running battles or fetching sources:

```sh
uv run pogo-analyzer site --data reports --out public
python -m http.server 8000 --directory public
```

Type icons, sprites, Rocket R artwork and fonts live outside the repo, for example in
a cache directory. A local `site-assets/` directory is also ignored for convenience.
These assets are never committed and are never fetched by the tool.

Use `--type-icons DIR` to add local type PNGs; icons are not shipped in the repo and are not fetched by the tool.
Use `--sprites DIR` for local `<speciesId without _shadow>.png` sprites; sprites are not shipped or fetched by the tool.
For deployment, `pogo-analyzer site-sprites --data reports --cache-dir CACHE --tree TREE.json`
prints sorted `base filename` pairs for the sprites used by the site, using the cached PvPoke
gamemaster and a local GitHub tree response. The deployment script can download those files
from PokeMiners into `DIR/<base>.png`; unavailable species are reported on stderr.
Use `--brand-assets DIR` for `rocket-r.png` and OFL Lato fonts `lato-{400,700,900}.woff2`;
these assets are not shipped or fetched by the tool. Missing assets use a letter R and system fonts.

Open `http://localhost:8000` to view the site. The output is plain static HTML with
inline CSS, optional local fonts, light/dark colors and no remote assets or runtime dependencies.
The theme toggle remembers your choice per browser and defaults to the device setting.
Source URLs appear as visible text only. Each build stages a complete site in a temporary
sibling directory, renames the old output aside, installs the new tree, then removes the
old tree. Rerunning is safe and prunes pages for characters removed from the manifest.
Use a dedicated output directory: `.pogo-site` records the files produced by the build.
Existing nonempty directories without a valid marker, or containing unrelated files,
are refused. When upgrading an older unmarked site, choose a new or empty `--out` path.

- `index.html`: a top-five Best all-round list, followed by Leaders and Grunts grids
  with lead-slot sprites and each character's top three counters. Leaders keep the
  manifest order; grunts sort by type A to Z, female before male, with Mixed and Decoy
  last. The game data's Metal grunts display as Steel grunts; slugs and files keep
  `metal`. "Best against any grunt" and "Best against any leader" link to the overall
  lists. Each counter list says what the % means in one muted line.
- `list/<slug>.html`: a compact Rocket header, possible Pokémon by slot (named under
  each sprite), and ranked
  counters with attacker-type filter chips, moves, type icons, content tags and win rate.
  A Toughest matchup appears when its conditional win rate is under 95%, floored to one
  decimal place. The Battle details link opens expandable results.
- `list/all.html`, `list/grunts.html`, `list/leaders.html`: ranked overall lists with
  attacker-type filter chips. HP left and Rocket KOs appear on desktop (700px and up).
- `counters/<slug>.html`: native expandable battle details in plain words: the quick
  1-on-1 check (computed for finalists), the win chance against each of their Pokémon
  (conditional win rates; battle counts are not shown), the win-chance range over
  tested Rocket pauses and damage ranges over their possible moves.
- `how.html`: a plain summary of at most six lines (what the site is, what the % means,
  one line each for Shadow, Elite TM and Timing-sensitive at `#shadow`, `#elite-tm` and
  `#pause`, the counter settings, the data date and credits), then one collapsed
  “Technical details” section: validation status and label, open discrepancies,
  assumptions per level, the pause explanation once with each character's pause numbers
  on one line, grade vocabulary and rows that differ from the usual grade,
  rCPM/moveset/filter notes, battle dates and rules periods, coverage, sources, credits,
  limitations and source fetch times. Shared
  metadata comes from the overall report or manifest; character sections preserve
  each report's own provenance and assumptions.

Every page has one simulator-estimates disclaimer linking to `how.html`. Per-number
estimate marks, repeated grade chips, trust strips, intro folds and footer notes are
replaced by that bar and the method page. Only Shadow, Elite TM and Timing-sensitive tags
remain; Timing-sensitive links to the explanation of the modelled Rocket pause. Warnings for
stale or unavailable reports stay on the affected pages. When a battle date is newer
than the sources, one amber line on `how.html` warns that rules are assumed unchanged.

Level 40/50 buttons switch the counter sections and character lineups. Without
JavaScript both levels show. Character and overall type filters update visible ranks;
without JavaScript every row shows and filter controls stay hidden. Lists warn when the
current view's best counter wins fewer than half of battles. Settings lines use each
report's level, IVs and shield policies. Missing sprites use lettered circles; missing
optional type images keep accessible type symbols. Older reports with missing metrics
show “not recorded” rather than guessing.

Percentages that would round to 100.0% or 0.0% show “>99.9%” or “<0.1%” when
the underlying rate is strictly between zero and one; exact endpoints retain 0.0%
and 100.0%. Non-integer detail counts keep two decimals, flooring near an integer when
rounding up would imply a full KO.

The renderer checks report keys against the manifest, ignores unlisted files and
dotfiles, and shows missing or unavailable reports with a reason. Key mismatches and
stale character entries never publish rows. A manifest-marked stale overall with a
matching key stays visible with an amber warning and its computed-for battle date.
Each file's own date, date source and era are preserved on `how.html`; the manifest's
current run date does not replace a reused file's date. Dates before 2019-07-22 are rejected.

The landing-page golden is refreshed deliberately with
`POGO_UPDATE_SITE_GOLDEN=1 nice -n19 uv run --frozen pytest -q -p no:xdist tests/test_site.py`;
review `tests/fixtures/site/expected_index.html` after changing the renderer.

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
