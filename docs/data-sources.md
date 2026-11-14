# Data sources

Checked 2026-11-13. All Pokémon GO data belongs to Niantic and The Pokémon Company. A repo's licence covers
that repo's code and its compilation of the data, not the game data itself. This is a personal, free,
ad-free tool that credits every source.

| Need | Source | Licence / terms | Freshness | Use? |
|---|---|---|---|---|
| Base stats, PvP move stats, shadow list | [PvPoke `src/data/gamemaster.json`](https://github.com/pvpoke/pvpoke/blob/master/src/data/gamemaster.json) | MIT | updated 2026-11-12 | **Primary.** Clean `baseStats` plus `power` / `energy` / `energyGain` / `turns` per move. |
| Raw game master (cross-check, combat settings) | [alexelgt/game_masters](https://github.com/alexelgt/game_masters) | no licence | uploaded 2026-11-11 | Reference only: cite values, don't vendor. |
| Raw game master | [PokeMiners/game_masters](https://github.com/PokeMiners/game_masters) | no licence | GM 2026-08-28 (stale) | No. |
| Current Rocket lineups (slot pools) | [WatWowMap/event-info `grunts/formatted.json`](https://github.com/WatWowMap/event-info/blob/main/grunts/formatted.json) | MIT | file updated 2026-10-04 | **Primary.** Dex id plus form per slot, catch-slot flags; covers grunts, leaders, Giovanni and decoys. No movesets. |
| Current Rocket lineups | [ScrapedDuck `rocketLineups.json`](https://github.com/bigfoott/ScrapedDuck/tree/data) (LeekDuck) | code AGPL-3.0; data allowed if the app has no paywall, no ads, and credits ScrapedDuck and LeekDuck | updated daily | Fallback or cross-check. Same 26 active lineups as event-info on 2026-11-13. |
| NPC stat tiers | Pokebattler `fight.pokebattler.com/rocket` | no licence; developer page says "unofficial, no SLA, cache aggressively" | live | Cite the published numbers in docs and config; don't call it from the tool. |
| Counter rankings | Pokebattler public API, `fight.pokebattler.com/rocket/defenders/...` ([developer page](https://www.pokebattler.com/developers)) | developer page: no auth; cache aggressively, descriptive User-Agent, attribution required. Terms (read 2026-11-13) cover the mobile app and have no scraping or API clause. `fight.pokebattler.com/robots.txt` disallows `*` and allows listed AI assistants. | live | Used by the CLI: sequential, ≥2 s apart, 24 h cache, site-default parameters only (chosen 2026-11-13). Results: [spike notes](spike-pokebattler-api.md). The old scraper and its bot-detection evasion are removed. |
| Various | [pogoapi.net](https://pogoapi.net) | no stated licence | varies | No Rocket lineups; not needed. |

## robots.txt (fetched 2026-11-13)

- **pokebattler.com:**
  - disallows `/api`, `/proxy` and `/fight/attackers`, plus the `sort=TOTAL_HEAL`, `sort=TOTAL_SHIELD` and
    `dodgeStrategy=DODGE_100` permutations;
  - other `/rocket/...` paths are allowed;
  - `Content-Signal: search=yes, ai-input=yes, ai-train=no`.
- **pvpoke.com** and **pogoapi.net:** content-signal comments only, no disallow rules.
- **pokemongohub.net:** disallows only `/wp-admin/`.
