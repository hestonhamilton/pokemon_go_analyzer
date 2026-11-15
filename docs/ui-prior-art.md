# UI prior art: how counter tools present results

Researched 2026-11-14. This page covers how existing Pokémon GO tools present two things:

- counters for one Team GO Rocket character (grunt, leader or Giovanni);
- "top N attackers per type" lists.

It feeds the design of our own views. Our simulator reports, for each counter, a win rate, draw rate,
lead-sweep probability, slots swept, HP left and turns. Each value carries a confidence grade and the word
"estimate".

Pokebattler was not fetched directly. Its section relies on search-result snippets, a third-party app-store
listing and this repo's own [API spike notes](spike-pokebattler-api.md). Anything marked **unverified**
could not be confirmed from a page that was actually read.

## Pokebattler

**Rocket counters.**

- The Rocket page is indexed as "Team GO Rocket Counters". Its snippet says grunts "do not shield" and that
  leaders ("Executives") and Giovanni "have higher stats and will shield the first two specials used". A beta
  snippet describes the counter tool as listing the top 30 counters
  ([www2 snippet](https://www2.pokebattler.com/rocket), [beta snippet](https://beta.pokebattler.com/rocket);
  search snippets only).
- **One result list per defender per slot.** Indexed URLs have the form `/rocket/<DEFENDER>/<TIER>/<slot>`,
  for example [`/rocket/NUZLEAF_SHADOW_FORM/RAID_LEVEL_1/2`](https://www.pokebattler.com/rocket/NUZLEAF_SHADOW_FORM/RAID_LEVEL_1/2)
  (URL seen in search results). That points to one page per possible slot Pokémon, not one page per lineup
  (**unverified** as a UI claim).
- **Default view.** This comes from the site's request builder, read in our [spike](spike-pokebattler-api.md):
  - `sort=POWER`, `view=GROUPED`;
  - the player's shields change by slot: 1 shield for slots 1–2, 0 for slot 3;
  - the defender has 2 shields;
  - no weather, party of 1, and legendaries, megas and shadows all included;
  - the defender's `stats.level` comes back as 100 (105 for leaders), so absolute win ratios against grunts
    look implausible.

  The meaning of the shield parameters is undocumented.
- **Personal box.** Counters can be filtered to the user's own Pokébox, according to a search snippet of
  Pokebattler's [2019 custom-counters post](https://www.pokebattler.com/articles/2019/11/21/custom-counters-to-beat-team-rocket)
  (snippet only).

**Raid counters.**

- **Columns:**
  - **Estimator:** about how many trainers are needed. Under 1 means "you probably win". It is computed from
    the top six counters ([raid-advice help page, snippet](https://articles.pokebattler.com/help/raid-advice/)).
  - **Time to Win:** 2 s is added per faint.
  - **Deaths.**
- **Sort options:** Overall, Estimator, Power, Time to Win, Potions, Deaths and Win % (search snippets of the
  same help pages and the [Raid Party app listing](https://apps.apple.com/app/id1499435805)).
- **Simulation.** It uses a Monte Carlo simulator; the app listing (read directly) says Raid Party "runs on the
  same Monte Carlo battle simulator as Pokebattler.com".
- **Two fidelity levels.** One snippet says the counter list uses "bronze level sims" while the drill-down uses
  "gold level", "so your results may differ" (**unverified**: the source article is unclear). This is a rare
  case of the tool admitting a fidelity tier.
- **Settings.** Weather is selectable (snippet). Defaults for friendship, dodging and level are **unverified**.
- **Mega level.** Megas are ranked at Mega Level 4, and the ranking level can be changed in Advanced Settings
  (app listing, read directly).

## PvPoke

- **Rankings** ([rankings page](https://pvpoke.com/rankings/all/1500/overall/)):
  - one sortable list per league with a 0–100 Score, where 100 is the #1 Pokémon;
  - category tabs: Overall, Leads (2v2 shields), Closers (0v0), Switches, Chargers, Attackers (0v2) and
    Consistency;
  - Overall is a geometric mean of the categories;
  - each row expands into Key Wins and Key Losses with a Battle Rating per matchup, plus a CSV export.
- **Caveats.** The page calls its rankings "subject to change" as the simulator improves and "a best guess"
  (search snippet of the rankings page). It names no date, only a version number.
- **Battle Rating** ([battle page](https://pvpoke.com/battle/)):
  - a 0–1000 score: up to 500 for damage dealt and up to 500 for HP left;
  - "Above 500 is a win and under 500 is a loss";
  - a shield matrix shows every shield combination for a single battle.
- **Multi Battle.**
  - One Pokémon is run against a league, cup or custom group.
  - It shows a win/loss histogram and an Individual Matchups list sorted worst to best, with a Battle Rating
    for each opponent.
  - Tabs switch between Battle Rating, Breakpoints, Bulkpoints and Attack, and results export to CSV.
- **Matrix Battle.** Two groups are shown as a grid. A "Differences" table shows each row against the first
  Pokémon. The cell display can be changed on the Settings page.
- **Opponent IVs.** Opponents in Multi Battle use "typical" IVs
  ([settings](https://pvpoke.com/settings/), snippet).
- **Uncertainty.**
  - Results "may differ from actual gameplay" because of connectivity, device and player decisions.
  - Simultaneous knockouts depend on which Charged Move goes first.
  - Auto move selection is right "the majority of the time".

## Pokémon GO Hub

- **Giovanni article** ([guide](https://pokemongohub.net/post/guide/rocket-boss-giovanni-counters/)):
  - **Lineup:** a two-column table (Slot | Pokémon), where slot 2 is "a random pick" of three.
  - **Counters:** one counter table per possible slot Pokémon (Pokémon | Moves), plus a "best team" list of
    three.
  - **No metric column.** The article ranks for "viability" over damage and gives no method, level or IV
    assumptions.
  - **Unexplained markers.** Moves carry an asterisk that is never explained, and moves are never flagged as
    unconfirmed.
  - **Dates.** It shows "Last update" and "Fully updated with the start of" a named event; the date ties the
    content to an era.
- **Grunt guide** ([guide](https://pokemongohub.net/post/guide/team-go-rocket-battle-guide/)):
  - a #1/#2/#3 × three-column sprite table per grunt;
  - a bullet list of catchable Pokémon, with notes like "can be caught from the second slot";
  - counters given as types plus example species, with no numbers;
  - lineup data credited to a player-submitted research project.
- **DB best attackers by type**
  ([Dragon](https://db.pokemongohub.net/pokemon-list/best-per-type/dragon)):
  - **Columns:** Tier, #, Pokémon, Fast, Charged, **eDPS** (the sort), DPS, TDO, TTW, Faints and % of best.
  - **Stated assumptions:** L40, 15/15/15, no weather, no friendship, no Party Power, a 10 s relobby, Mega
    level 4, and a pool of tier 4+ bosses weak to the type.
  - **Settings.** A settings gear changes the assumptions; the page warns this can re-rank the list, while
    search does not change the numbers.
  - **Picks.** "At a glance" picks, including "Best without Elite TMs".
  - **Date.** A timestamp: "Updated Nov 12, 2026, 16:42 UTC".
- **DB raid counters** ([example boss](https://db.pokemongohub.net/pokemon/949/counters)):
  - the same columns, with tiers from SS to F;
  - "Scores average over the boss's possible moves";
  - legacy moves marked with an asterisk;
  - an estimated group size (top 12 regular counters at 75% weight, top 2 Megas at 25%);
  - the caveat "Results are simulations", listing IVs, dodging, the boss's moves and lag as sources of
    difference;
  - defaults are L50 here, against L40 on the per-type page, with no data date shown.

## DialgaDex

The home page was read directly ([dialgadex.com](https://dialgadex.com/)). Its settings panel is the most
complete of the per-type tools:

- **Metric:** DPS, TDO or eDPS.
- **Level:** 30, 40 or 50, plus a "Budget50" option.
- **Other settings:** Super Mega level, Party Power, and team size (6-Stack, Solo or MegaSolo) with a relobby
  time.
- **Species filters:** Unreleased, Mega/Primal, Shadow and Legendary.
- **Move filters:** Elite Moves, Mixed Types, Off Types and Suboptimal Moves.
- **Baseline.** A setting picks which Pokémon counts as 100%, with presets Budget, ESpace and Best.
- **Tiers.** Three schemes are selectable: Jenks (algorithmic), ESpace (a cut every 10%) and Absolute (for
  comparing across types).
- **Data Preview** is a site setting.
- Table column names and a data date were not visible (**unverified**).

## Leek Duck and DittoBase (lineups only)

- **Leek Duck** ([rocket-lineups](https://leekduck.com/rocket-lineups/)):
  - one stacked card per character (portrait, name, role label, and for grunts a type icon and taunt);
  - three numbered slot rows, each a horizontal strip of sprites (1–3 options);
  - "Click/Tap on any row to see type weaknesses";
  - a page date: "Updated on October 2, 2026";
  - no counters and no filters.
- **DittoBase** ([rocket-lineups](https://www.dittobase.com/pokemon-go/rocket-lineups)):
  - the same 3-slot structure with a Grid/List toggle;
  - catchable (Premier Ball) and shiny icons per Pokémon;
  - shiny and hundo odds;
  - a timestamp: "updated Oct 2, 2026 at 10:01 pm UTC";
  - lineups worded as what a member "might" bring.
- **DittoBase per-type list** ([Ghost](https://www.dittobase.com/pokemon-go/best-attackers/ghost)):
  - mirrors the Hub DB (eDPS sort, % of best, tiers SSS–C, an asterisk for legacy moves);
  - quick-pick cards that "always use the default baseline" even when the settings change;
  - a "Copy link" for the current settings and a "Change Log".

## GamePress (now served from pokebase.app)

- **Best attackers by type**
  ([page](https://pokebase.app/pokemon-go/p/best-attackers-by-type)):
  - prose plus a bulleted list per type (sprite, type icons, name), with no numeric columns;
  - ordered by ER, "heavy weight on DPS, some on TDO";
  - **manually adjusted** by the editors for practical use;
  - five colour tiers;
  - "Latest Update: July 3, 2026";
  - no level or IV assumptions stated.
- **Comprehensive DPS/TDO spreadsheet.**
  - Every Pokémon and moveset, with DPS and TDO and sortable columns.
  - A "Best" filter keeps each Pokémon's top moveset, and "Swap Dscnt" adds the time lost swapping.
  - An enemy and weather selector is available.
  - Source: [search snippet](https://pokemongo.gamepress.gg/comprehensive-dps-spreadsheet). The live URL
    under pokebase.app returned 404, so the layout is **unverified**.
  - **Metric history.** GamePress moved from DPS×TDO to DPS³×TDO because the old formula overweighted bulk
    ([how DPS is calculated](https://gamepress.gg/pokemongo/how-calculate-comprehensive-dps), snippet).
- **Rocket guides.** The grunt and leader guide pages returned 404 or failed DNS, so their layout is
  **unverified**.

## Others

- **Doctor PokeGoGo** ([raid guide](https://doctorpokegogo.com/en/raid-guide/)):
  - separate "best overall DPS" and "best with endurance" picks for each boss;
  - a dated guide index;
  - published methodology pages.

  Seen in search results only.
- **"PoGo Raid counters" and "Pogo Calc".** No site matching these names was found, so nothing is recorded.

## Comparison

| Tool / view | Layout | Ranking metric | Assumptions shown | Filters | Uncertainty / provenance |
|---|---|---|---|---|---|
| Pokebattler Rocket | list per slot Pokémon, top ~30 (snippet) | Power (default sort) | grunt/leader shield rule in text; per-slot shields in params | box, legendary, mega, shadow, shields | Monte Carlo, but no grade; grunt numbers look implausible |
| Pokebattler raid | table | Estimator (trainers), TTW, Deaths, Win % | weather, party; others unverified | weather, box, mega level | "bronze vs gold sims" (unverified) |
| PvPoke rankings | sortable list + expand | Score 0–100 (% of #1), from Battle Rating | shields per category tab | league, category, rich search | "best guess", "subject to change"; version, no date |
| PvPoke multi / matrix | sorted list + histogram; grid + diffs | Battle Rating 0–1000 (500 = win line) | shields, IV rank, level cap | shields, baiting, IVs | "may differ from actual gameplay" |
| Hub Rocket articles | slot table; counter table per slot Pokémon | none (editorial "viability") | Giovanni shield rule only | none | dated; asterisk unexplained |
| Hub DB per type / raid | sortable table + tiers + picks | eDPS, % of best | full defaults panel | level, weather, friendship, relobby, mega, shadow, legacy | "Results are simulations"; averaged over boss moves; timestamp |
| DialgaDex | ranked list + tiers | DPS / TDO / eDPS, % of chosen baseline | level, team size, relobby | species, elite, mixed/off-type, unreleased | baseline and tier scheme selectable; no date seen |
| Leek Duck lineups | card per character, 3 slot rows | n/a | n/a | none | page date |
| DittoBase | cards / grid; table per type | eDPS, % of best | full defaults | weather, level, friendship, legacy, mega | timestamp, change log, "might" wording |
| GamePress | prose + bullets; spreadsheet | ER (manually adjusted); DPS³×TDO | barely (list); enemy and weather (sheet) | Best moveset, swap discount | dated; editors' overrides stated |

## Patterns worth borrowing

1. **Put the assumptions above the table, and let them be changed (Hub DB, DittoBase, DialgaDex).** Our
   numbers depend on level, IVs, shields and NPC tier, the same as theirs. A visible defaults strip makes it
   clear what "estimate" is an estimate *of*.
2. **Use the lineup grid of slot rows × option sprites (Leek Duck, DittoBase, Hub).** Players already read
   Rocket lineups this way. We can hang a per-slot summary (best counter, win rate, grade) on each row
   instead of inventing a new shape.
3. **Rank against one possible slot Pokémon, then roll up (Pokebattler, Hub articles).** Slot pools are
   random, so per-option results are the honest unit. A lineup view can then aggregate: expected slots swept
   over the pool, with the pool weights stated.
4. **Show "% of best" plus tiers (Hub DB, DittoBase, DialgaDex, PvPoke's score).** This works for top N per
   type: a relative column is easier to read than raw eDPS. Tier cut-offs should be stated, as DialgaDex
   does, or the tiers look like data.
5. **State a win line (PvPoke: "Above 500 is a win").** Our win rate and draw rate need the same explicit
   threshold language, and a draw needs its own colour, not a midpoint.
6. **Expand a row to show key wins and losses (PvPoke).** In our case, a counter row expands into its
   per-slot-option results and turns, so the summary row can stay short.
7. **Time-stamp the data, and name the battle era (Leek Duck, Hub "Fully updated with…", DittoBase change
   log).** Lineups rotate. Every result view should show the lineup snapshot date and the game-master date it
   used, and flag results computed against an older rotation.
8. **Average over unknown moves and say so (Hub DB: "average over the boss's possible moves").** Rocket NPC
   movesets are random. We should say whether a number is an average over moves or a worst case, next to
   the grade.
9. **Copy-link and CSV export (DittoBase, PvPoke).** These make results reproducible and shareable, and they
   carry the assumptions with them.

## Patterns to avoid

1. **Unexplained markers.** The Hub's move asterisk is never defined. Every badge we use (grade, "estimate",
   legacy move) needs a legend on the page.
2. **Editorial order with no metric (Hub Rocket articles, GamePress's manual ER adjustments).** This hides
   whether an order is simulated or opinion. If we ever hand-tune anything, it should be labelled as an
   override.
3. **Absolute numbers from an NPC model nobody can check (Pokebattler grunt win ratios near 0).** Show
   absolute win rates only where the confidence grade supports them. Otherwise fall back to the relative
   order, and say so.
4. **Different fidelity in the list and the drill-down (Pokebattler "bronze vs gold", unverified).** If the
   summary and the detail come from different sample counts, the grade must reflect that, or the numbers will
   disagree with no explanation.
5. **Quick picks frozen at the defaults while the table changes (DittoBase).** Two numbers for the same
   Pokémon on one page look like a bug. Either recompute the picks or label them "at defaults".
6. **Mixing Mega, Shadow and legendary entries with no toggle (GamePress list).** For top N per type, offer
   toggles in the style of DialgaDex's Budget preset, so N isn't filled with Pokémon the player can't field.
7. **No data date (PvPoke rankings, Hub DB raid counters).** A version number alone doesn't tell a player
   which rotation or balance patch a result reflects.

## Sources that failed

- **Not fetched by rule:** every `pokebattler.com` host. Snippets only.
- **Fetch blocked:** `web.archive.org` ("unable to fetch").
- **404:** `pokebase.app/pokemon-go/comprehensive-dps-spreadsheet`,
  `pokebase.app/pokemon-go/p/team-rocket-dragon-type-grunt-guide` and `gamepress.gg/node/84016`.
- **DNS failure:** `pogoold.gamepress.gg`.
- **Not found:** "PoGo Raid counters", "Pogo Calc", and DialgaDex's column names and data date.
