# Spike: Rocket counters from Pokebattler's public API

Run on 2026-11-13. The owner picked the documented-API option over a headless browser. This page records what
works, what breaks, and what it means for the tool.

## What was built

- `pogo-analyzer lineups | counters | tally` (see the README).
- **Lineups:** [WatWowMap event-info](https://github.com/WatWowMap/event-info) (MIT).
- **Dex number → species:** [PvPoke](https://github.com/pvpoke/pvpoke) (MIT).
- **Counters:** `fight.pokebattler.com/rocket/defenders/...`. Requests go out one at a time, at least 2 s apart,
  with a 24 h disk cache that also remembers 404s. The User-Agent carries only the repo URL. A request budget
  stops a run before it goes over, and a 403, 429 or 5xx stops the run with no retry.
- **Requests copy the site's default Rocket view.** The parameters are the ones the site's own request builder
  sends (read from its JavaScript bundle):
  - `sort=POWER`, `view=GROUPED`;
  - `shieldStrategy` by slot: slots 1 and 2 → `SHIELD_1`, slot 3 → `SHIELD_0`;
  - `defenderShieldStrategy=SHIELD_2`;
  - `meta=DUAL_MOVE`, `aggregation=AVERAGE`, `attackerTypes=POKEMON_TYPE_ALL`;
  - `dodgeStrategy=DODGE_REACTION_TIME`;
  - `includeLegendary`, `includeMegas` and `includeShadow` all `true`;
  - `numParty=1`, `weatherCondition=NO_WEATHER`.

  Sorting happens locally, so a defender costs one request a day whatever the sort.

## What works

- **Load:** about 40 API requests across two live runs, with no 403, 429 or 5xx.
- **Speed:** a 7-defender leader lineup takes about 14 s cold. Rerunning with `--max-requests 0` is served
  entirely from the cache.
- **Defender IDs:** the site strips `_SHADOW_FORM` and adds `_FORM` for regional forms. `WEEZING_GALARIAN` is a
  404 and `WEEZING_GALARIAN_FORM` resolves; `VULPIX_ALOLA_FORM` and `NINETALES_ALOLA_FORM` likewise. Both ID
  styles return 200 for plain species.
- **Coverage:** all 26 active lineups come from event-info with no scraping. Slot pools resolve except for dex
  numbers PvPoke doesn't list yet; those are reported as unresolved and the run continues.

## What breaks or surprises

1. **Pokebattler's simulations look pessimistic for grunt Pokémon.**
   - With the site's defaults, almost every counter's win ratio against grunt and leader slot Pokémon is 0.
   - Against shadow Ralts (a slot-1 grunt Pokémon, `RAID_LEVEL_1`), every counter faints in 2–3 s. Mega
     Lucario, which resists Psychic, takes 515 damage.
   - The response reports the defender's `stats.level` as `"100"`, or `"105"` for leaders.
   - This happens with our own parameters and with the site's exact parameters, so it is Pokebattler's output,
     not our parsing. Players beat these Pokémon easily, so the absolute numbers aren't credible for grunts.
     `power` and `overallRating` still give a relative order.
2. **The results depend heavily on the shield settings, and their meaning isn't documented.**
   - Golurk (Cliff, slot 2): Urshifu wins 95% with `shieldStrategy=SHIELD_2, defenderShieldStrategy=SHIELD_2`;
     with the site's defaults (`SHIELD_1`/`SHIELD_2`) the best counter, Scyther, wins only 45%.
   - The site's page text calls its shield selector "the grunt's shields". But responses fill
     `defenderShields` (the Rocket side's shields used) only when `defenderShieldStrategy` is non-zero.
   - Which side each parameter controls is therefore unclear. The CLI passes both through under their API
     names, defaulting to the site's values.
3. **Win ratio is sparse.** A per-moveset result carries `win`/`winRatio` only when the counter wins. The
   parser reads a missing value as 0, which is right for these 100-sim results. Counter totals carry
   `numWins`/`numLosses`.
4. **The candidates aren't a player's box.** The ranked counters include legendaries, megas and event-only
   forms (Eternatus, Zamazenta, Genesect). The site's `includeLegendary`, `includeMegas` and `includeShadow`
   flags could filter them, or a signed-in "Pokebox" view could limit them to what the player owns; that needs
   an account.
5. **Polite-use friction.**
   - `fight.pokebattler.com/robots.txt` disallows every agent except listed AI assistants, while the developer
     page invites API use. We follow the developer page, at low volume.
   - Responses run to about 0.5 MB. Pokebattler suggests its MCP server for trimmed results.

## What this means

The plumbing is sound and polite. The part that matters, though (which counter wins, and by how much), now
depends on a model we can't inspect and whose grunt numbers look wrong. That supports the offline simulator
bead (`pgo-2xn`). Pokebattler then becomes a cross-check rather than the source of truth: compare the relative
order of its `power` against our simulated battle rating for the same defender.

Options if the scraper path continues:

- **Filter candidates:** use the site's include flags to drop legendaries and megas.
- **Rank by relative scores:** rank by `power`/`overallRating`, and show win ratio only for leaders, where it
  looks credible.
- **Ask Pokebattler:** they invite contact on the developer page, about the Rocket NPC model and the meaning
  of the shield parameters.
