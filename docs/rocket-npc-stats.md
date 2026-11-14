# Rocket NPC stats: Pokebattler's model compared with the real game

Research from 2026-11-13. Three things are kept apart on purpose:

1. **Pokebattler's model**: what its simulator assumes, read from its API and its own articles.
2. **The real game**: independent evidence only, with how each figure was measured.
3. **Whether 1 matches 2**, figure by figure.

> **Update 2026-11-14:** a broader research pass found later measurements. The 2021 formula was
> replaced in late 2022 (fit in March 2023, with damage tests), and the rocket-CPM table was re-indexed
> for the level-80 update in Oct 2025. The current picture is in [rocket-pokemon.md](rocket-pokemon.md).
> Where this page calls the 2021 formula "best available", read "superseded".

A figure that only Pokebattler gives is marked **unverified, Pokebattler only**. Tags: **POKEBATTLER** (their
pages or staff), **COMMUNITY** (player research), **DATAMINED** (game master), **OFFICIAL** (Niantic or The
Pokémon Company), **OURS** (our own API observations or arithmetic).

**Sources we couldn't reach:** Reddit, Bulbapedia and pogo.gamepress.gg could not be fetched, so the claims
marked "snippet" rest on search-result excerpts. Pokebattler's articles render without JavaScript at
`www2.pokebattler.com/articles/...`.

## 1. Pokebattler's model

**Three generations of the model exist, and the API still publishes the oldest one.**

| Generation | Source | Model |
|---|---|---|
| July 2019 | ["Team Rocket Update"](https://www2.pokebattler.com/articles/2019/07/28/team-rocket-update/) (Pokebattler's founder) (POKEBATTLER) | Typed grunts level 27, untyped grunts level 30, "attack multiplier of x3 and a defense multiplier of x2", plus a trainer-level factor. The same post: "It seems that Team Rocket's Pokemon are not as effective as they should be given their enormous stats." |
| July 2019 | ["Cracking the Case"](https://www2.pokebattler.com/articles/2019/07/25/cracking-the-case-cp-formula-for-team-rocket-shadow-pokemon/) (POKEBATTLER) | Four tiers, with an edit: "a 2.5x multiplier seems to fit the tier 1 invasions". |
| June 2021 | ["Cracking the Rocket CP Formula – 2021 edition"](https://www2.pokebattler.com/articles/2021/06/21/cracking-the-rocket-cp-formula-2021-edition/) (POKEBATTLER-hosted, community research) | See below. The article says the changes are "already implemented in Pokebattler". |
| Nov 2023 | [Release notes](https://www2.pokebattler.com/news), v7.16.14: "Update team rocket rCPM", citing [r/TheSilphRoad 184iqov](https://www.reddit.com/r/TheSilphRoad/comments/184iqov/team_rocket_cp_formulamaybe_its_perfect_data/) (POKEBATTLER) | Retuned rocket CPM; we couldn't read the Reddit post. |

The 2021 formula, quoted from the article:

> Attack IV = Floor (2/3 * Pokémon Base ATK + 25), Defense IV = 15, Stamina IV = 9
>
> Attack = 2 * (baseAttack + Attack IV) * rCPM * Rank
> Defense = 0.8 * (baseDefense + 15) * rCPM * Rank
> Stamina = 1.1 * (baseStamina + 9) * rCPM * Rank
>
> Rank equals 1.0 for a Grunt, 1.05 for a Leader and 1.15 for Giovanni.

rCPM (a "rocket CPM") rises with the trainer's level. The article gives 1.0 at trainer level 50, 0.9565 at 40
and 0.7719 at 30, times a constant 0.85374104.

**What the API shows (OURS, from 40 cached responses):**

- **`/rocket` still publishes the 2019 tier block:**

  | Tier | Level | CPM | Atk × | Def × | Sta × | HP |
  |---|---|---|---|---|---|---|
  | `RAID_LEVEL_1` | 27 | 0.6941 | 3.0 | 2.0 | 1.0 | 0 |
  | `RAID_LEVEL_2` | 30 | 0.7317 | 3.0 | 2.0 | 1.0 | 0 |
  | `RAID_LEVEL_UNSET` | 27 | 0.6941 | 2.5 | 2.5 | 2.5 | 0 |

  This matches the 2019 articles, not the 2021 formula.
- **The defender's `stats` block, by contrast, follows the 2021 formula:**
  - `level` is the 2021 rank × 100: 100 for every grunt, 105 for every leader, 115 for every Giovanni Pokémon.
    It is not a Pokémon level.
  - `attack` is the 2021 attack IV minus 1, i.e. floor(2/3·base) + 24: Ralts 76, Kirlia 102, Snubbull 115,
    Granbull 165.
  - `defense` is 14, the 2021 defence IV of 15 minus 1 (13 at attacker level 20).
  - `stamina` comes back negative (−32 to −136), which matches neither model. **Not decoded.**
- **The defender's CP scales with the attacker level we send:** shadow Ralts is CP 701 at level 20, 1153 at 40
  and 1365 at 50. This fits rCPM being driven by trainer level, using our attacker level as the trainer level.
- **The tier in the URL barely changes the results.** Ralts at tier 1, tier 2 and `UNSET` gives the same CP and
  near-identical damage. Galarian Weezing at the grunt and leader tiers differs in CP (4922 and 5427) but not in
  damage.
- **The simulated damage is implausible for grunts.**
  - Under the 2021 model at trainer level 50, shadow Ralts has about 266 attack, 50 defence and 101 HP
    (arithmetic, OURS).
  - A level-40 Mega Lucario has about 150 defence and 147 HP and resists Psychic, so it should outlast several
    hits.
  - The API reports Lucario fainting in 2.5 s after 515 damage, more than three times its HP pool.
  - Possible causes: the stale ×3/×2 block stacked on top of the 2021 stats, raid-style accounting (the result
    carries `potions`, and damage taken exceeds HP), or a unit bug. **Not settled.**

**Shields:**

- Pokebattler's Rocket hub says grunts "do not shield" and that leaders and Giovanni "will shield the first two
  specials used".
- Its custom-counters tool defaults both "Shield Strategy" and "Defender Shield Strategy" to "Shield Twice"
  ([rocket hub](https://www2.pokebattler.com/rocket)).
- The developer page and `llms.txt` don't document either parameter.
- From our data, wins appear mainly with `shieldStrategy=SHIELD_2`, which suggests `shieldStrategy` is the
  player's shields. Results also report `defenderShields` only when `defenderShieldStrategy` is non-zero. Best
  reading: `shieldStrategy` is the player's shields, `defenderShieldStrategy` the Rocket side's (OURS,
  inference).
- Setting `defenderShieldStrategy=SHIELD_0` for grunts does not fix the 0% results: Ralts still loses to every
  counter.

## 2. The real game (independent evidence)

**The game master has no Rocket stat data (DATAMINED).** The Rocket character templates hold display settings
only. The only NPC combat entries (`combatNpcTrainer`, `combatNpcPersonality`) belong to the team-leader
training battles, and `combatSettings` holds global PvP values (the 1.3 bonus, shadow ×1.2 / ×0.833) but no NPC
multipliers. Checked in [alexelgt/game_masters](https://github.com/alexelgt/game_masters) (2026-11-11) and
[Hazels-Lab/pogo-masterfile](https://github.com/Hazels-Lab/pogo-masterfile). Rocket stats are set by the
server, so every stat figure below is reverse-engineered.

**Niantic has made no statement** about Rocket Pokémon stats, HP or levels that we could find.

| Study | Date | How it was measured | Finding |
|---|---|---|---|
| GamePress / r/TheSilphRoad, "Cracking the Team GO Rocket Grunt CP formula – solved!" ([GamePress](https://pogo.gamepress.gg/cracking-team-go-rocket-grunt-cp-formula), [thread](https://www.reddit.com/r/TheSilphRoad/comments/duw92a/analysis_cracking_the_team_go_rocket_grunt_cp/), snippets) | ~Nov 2019 | Displayed CP of grunt Pokémon, fitted against level-40 trainers | For level-40 trainers: a global multiplier of 0.63251, then attack ×4 and defence ×2; IVs 15/15/15; HP = floor(0.63251 × (2·floor(base/2) + 14)). Leaders ×1.2 ("EXACT match"), Giovanni ×1.25. |
| Devreugkx with Pokebattler's founder, "2021 edition" ([article](https://www2.pokebattler.com/articles/2021/06/21/cracking-the-rocket-cp-formula-2021-edition/)) | June 2021 | 433 CP readings across trainer levels (8 at level 50, 63 at level 44, none at 19 or below), linear fit; HP checked by chip damage (1-damage hits); defence by counting fast moves to knock out; attack from single hits; one packet capture from an anonymous source | The 2021 formula above; ">98% accuracy" claimed for CP. The HP and damage checks are described but their data isn't published. |
| r/TheSilphRoad 184iqov ([post](https://www.reddit.com/r/TheSilphRoad/comments/184iqov/team_rocket_cp_formulamaybe_its_perfect_data/)) | ~Nov 2023 | Unknown: we couldn't read it | Prompted Pokebattler's rocket CPM update. |
| Bulbapedia, [Team GO Rocket](https://bulbapedia.bulbagarden.net/wiki/Team_GO_Rocket) (snippet) | current | Secondary write-up | Same structure as the 2021 study (rocket CPM rising with trainer level; ranks 1 / 1.05 / 1.15). Likely derived from it, so not independent. |

**Shield behaviour is well attested:**

- **Grunts never shield.**
  - GO Hub battle guides: "Team Rocket Grunts do not use shields"
    ([2026-10-31](https://pokemongohub.net/post/guide/team-go-rocket-battle-guide/)), "Grunts will not put up
    shields" ([2023/24](https://pokemongohub.net/post/guide/go-hub-guide-to-team-go-rocket-battles)).
  - Bulbapedia (snippet) agrees.
- **Leaders and Giovanni** shield the player's first two charged attacks: The Pokémon Company's strategy page,
  Spring 2023, now removed (snippet, OFFICIAL-TPCi), and Bulbapedia.
- **Dissent:** one GamePress snippet ([node/84031](https://gamepress.gg/node/84031)) says grunts "always
  shield the first two Charged Moves". Probably an old or misattributed leader guide.
- **Method:** observation in play, not measurement.

**Player comparisons of Pokebattler's Rocket simulations against real battles:** none on any page we could
read. Reddit was blocked, so this is a gap in our search, not proof that none exist.

## 3. Does the model match the game?

| Figure | Pokebattler | Independent evidence | Verdict |
|---|---|---|---|
| Tier block: level 27/30, ×3 atk, ×2 def, ×1 sta (`UNSET` 2.5) | Published by `/rocket` today | Superseded by both community studies (2019: ×4/×2 at 0.63251; 2021: ×2/×0.8/×1.1 with boosted IVs) | **Stale. Matches no current study.** Don't use. |
| 2021 formula (IVs, ×2 / ×0.8 / ×1.1, rank 1 / 1.05 / 1.15) | Matches the `stats` block | One CP study with 433 readings and a described method; Bulbapedia repeats it | **Superseded** by the March 2023 formula (see [rocket-pokemon.md](rocket-pokemon.md)); its attack-IV rule survives. The study involved Pokebattler's founder, so it isn't fully independent. |
| Rocket CPM rising with trainer level | Yes (CP tracks attacker level) | Both studies, from CP readings | **Consistent.** CP-based evidence only. |
| HP | 1.1 × (base + 9) × rCPM × rank (2021) | 2023: floor(0.6 × (base + 15)) × rCPM × rank, checked by damage and hit counts (May 2023) | **Pokebattler's 2021 HP is outdated.** The 2023 HP is measured, but only by CP since Oct 2025. |
| Nov 2023 rocket CPM retune | Applied | [184iqov](https://www.reddit.com/r/TheSilphRoad/comments/184iqov/): an rCPM table back-solved from CP; re-indexed again for level 80 in Dec 2025 ([1puc05x](https://www.reddit.com/r/TheSilphRoad/comments/1puc05x/)) | **Measured by CP.** Whether Pokebattler has adopted the Dec 2025 table is unknown. |
| Grunts don't shield; leaders and Giovanni shield the first two | Stated on its hub page | GO Hub, Bulbapedia, TPCi | **Matches.** But the API's default `defenderShieldStrategy` is SHIELD_2 even for grunts. |
| Simulated grunt results (0% win, 515 damage in 2.5 s) | API output | Contradicts every stat model above, by our arithmetic | **Doesn't match.** Cause not settled. |

## What this means for the offline simulator

Superseded by the conclusions in [rocket-pokemon.md](rocket-pokemon.md):

- use the March 2023 formula with the Dec 2025 rocket-CPM table;
- apply the shadow 1.2× / 1.2× and the 1.3× bonus on top;
- take trainer level as an input;
- confirm with a small damage check, because only CP has been tested since Oct 2025.

Pokebattler's CP values and rank encoding remain useful as a cross-check.

## Open questions

1. What the negative `stamina` values encode, and which HP the simulator actually uses.
2. Whether Pokebattler stacks the 2019 ×3/×2 block on top of the 2021 stats, which would explain the damage.
3. What the Nov 2023 Silph Road post changed, and whether it includes measured data.
4. Whether anyone has measured HP or damage directly since 2021.
5. Whether the 2026 battle timing changes altered Rocket battles.
