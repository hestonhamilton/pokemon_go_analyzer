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
Giovanni 1.15. Explicit defenders require `--rank grunt|leader|giovanni`. `--slot` restricts character
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
| `attacker`, `defender`, `level`, `ivs`, `form` | Given species and build | Conditional inputs; fixture-exact formula path |
| `fast_move` | Attacker's chosen move | PvPoke metadata; parity-only |
| `attacker_attack`, `attacker_defence`, `attacker_hp` | Player totals used | Fixture-exact formula path; HP directly checked by F1 |
| `rocket_attack`, `rocket_defence`, `rocket_hp` | Rocket totals; HP floored for battle | Old grunt fixture-exact; current table or leader/Giovanni cp-only |
| `rank`, `rank_multiplier`, `rcpm_table`, `rocket_cpm`, `trainer_level` | Rocket scaling inputs | Same Rocket table/rank dependency |
| `rocket_cp` | Display CP, calculated with unfloored stamina | CP readings only; cp-only |
| `fast_damage`, `fast_hits_to_ko` | Damage per hit; ceil(Rocket HP / damage) | Old grunt fixture-exact; current table or leader/Giovanni cp-only |
| `rocket_fast_damage`, `ko_on_incoming_hit` | Incoming damage; ceil(player HP / damage) | Same Rocket dependency; KO occurs on the counted hit |
| `fast_damage_per_turn`, `rocket_fast_damage_per_turn` | Nominal damage / (cooldown / 500 ms) | Damage plus PvPoke duration metadata; parity-only |
| `fast_turns_to_ko`, `turns_survived` | Fast hits × move turns, counting the KO hit | Behaviour assumptions; model |
| `charged` | Each chosen charged move: move, unshielded damage, energy cost, fast moves to energy from zero | Move/cost parity-only; damage parity-only; energy count model; aggregate model |
| `rocket_charged` | Every pool charged move and unshielded damage; excluded from all turn counts | Move availability model; damage parity-only; aggregate model |
| `character`, `slot`, `rocket_fast_move`, `moveset_pool` | Encounter labels and hypothetical move availability | Model |
| `row_grade` | Weakest cell in the row | Model when any timing or pool assumption is present |

The four grades, strongest first, are defined in `src/pogo_analyzer/sim/data/grades.json`:

- **fixture-exact:** a formula path reproduced by recorded or measured pre-Oct-2025 grunt targets
  (F1, F2, F4, F5). This does not claim a recorded battle for each possible build.
- **cp-only:** Rocket stats depend on a table or rank backed by CP readings only. All Rocket-dependent
  results under `dec-2025`, and all leader/Giovanni results under any table, have at least this limit.
  Rocket stats from Oct 2025 on are backed by CP readings only.
- **parity-only:** pinned PvPoke code or metadata, with no battle target for this quantity. This includes
  charged damage on both sides. No modern measurement establishes Rocket charged damage.
- **model:** unverified behaviour or move availability. Timing, energy counts in battle, and Rocket
  move pools receive this grade.

Cells take the weakest grade of their dependencies. Conditional damage assumes the named move is
present; it does not prove move availability. The Rocket move pool copies every PvPoke species
`fastMoves` and `chargedMoves` entry, flagging `eliteMoves` and `legacyMoves` membership. Event-info
lists species, not moves. Neither source establishes Rocket-specific Frustration additions. No extra
Frustration is added; each pool reports whether its PvPoke list already includes it.

Every run recomputes recorded/measured `expected_pass` battle targets using the dated move and
species fixtures. `--fixtures-dir` defaults to `tests/fixtures/sim` relative to the package source.
Every target must pass under both gate tables, `venonic-2023` and `fugerappi-2023`, which publish every
trainer level the targets use. Targets that the TL50-only `flyfunner-old-50-2025` covers must pass too;
a level it lacks is listed as not covered and is never filled from another table. Missing fixtures, a
failing target, or a gate-table gap produce **UNVALIDATED** with the reason. Success prints
`Validated against N pre-Oct-2025 battle targets under venonic-2023 and fugerappi-2023 (...); M open
discrepancies: <ids>`.
All open discrepancies and their reasons remain in every report when the fixture files are readable.
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
