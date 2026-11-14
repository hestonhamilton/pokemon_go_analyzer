# pokemon_go_analyzer

Explore active Team GO Rocket lineups and Pokebattler counter simulations, or tally the counters that appear most often across defenders.

Install with `uv sync`, then run:

```sh
uv run pogo-analyzer lineups
uv run pogo-analyzer counters --character 'Fire grunt' --slot 1 --top 10
uv run pogo-analyzer counters --defender WEEZING_SHADOW_FORM --tier RAID_LEVEL_1 --format json
uv run pogo-analyzer tally --character grunt --top 5
```

Counter requests run sequentially at least two seconds apart, use a 24-hour cache (including missing IDs), a default budget of 80 network requests, and a descriptive User-Agent. Requests mirror the parameters of Pokebattler's default Rocket view; sorting happens locally, so there is one request per defender per slot setting per day whatever the sort. `--cache-dir` and `--max-requests` adjust the cache and counter request budget. Lineup sources have a separate cache.

CSV output carries no credits line (it goes to stderr), so credit Pokebattler, WatWowMap event-info and PvPoke when sharing a saved CSV; `--credits-column` adds a `source` credit to every CSV or table row.

Counter simulations: [Pokebattler](https://www.pokebattler.com), through its documented public API ([developer page](https://www.pokebattler.com/developers)); Pokebattler asks for attribution when results are published. Lineups: [WatWowMap event-info](https://github.com/WatWowMap/event-info) (MIT). Species data: [PvPoke](https://github.com/pvpoke/pvpoke) (MIT). See [docs/](docs/) for mechanics and source notes.
