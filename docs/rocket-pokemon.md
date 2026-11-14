# Team GO Rocket Pokémon: what they really are

Plain-language summary, researched 2026-11-13/14 in three passes. Everything here is about the game itself, not
any one tool. Each point says how sure we are and how it was measured; the sources are linked under each
section.

- **Measured:** players recorded it (CP readings, damage per hit, hit counts, video).
- **Official:** Niantic or The Pokémon Company said it.
- **Unverified:** stated somewhere, but we found no measurement.

Niantic has never published Rocket stats, and the game master holds none: they are set on the server. So every
stat figure below was reverse-engineered by players.

**How the sources were read:** Reddit posts were read through the Arctic Shift archive, and the key posts were
re-checked for this page. Links of the form `r/TheSilphRoad/<id>` mean
`https://www.reddit.com/r/TheSilphRoad/comments/<id>/`.

## The short version

1. **Rocket Pokémon have no normal level.** Their strength follows **your trainer level**: the higher you are,
   the stronger they get.
2. **They are not just normal Pokémon with the shadow bonus.** They get a special Rocket-only stat boost, and
   **on top of that** the usual shadow effect: they hit 1.2× harder and take 1.2× more damage.
3. **Leaders are 5% stronger than grunts, and Giovanni 15% stronger.** Leaders and Giovanni shield your first
   two charged attacks; grunts never shield.
4. **What you catch afterwards is unrelated to what you fought.** It's an ordinary level-8 Pokémon (level 13 in
   boosting weather) with normal random IVs. Giovanni's legendary has every IV at least 6.
5. **The rules changed recently.**
   - The stat formula was last refit in 2023 and re-indexed for the level-80 update in Oct 2025.
   - Rocket battles moved to the new server-run battle system around Dec 2025.
   - The pause after charged attacks and faints is now about 7 turns.
   - Battles time out after about 12 minutes.

   Anything older than 2023 is outdated.

## 1. How strong they are, and why it depends on you

**Current stat formula** (Measured, March 2023): Venonic,
[r/TheSilphRoad/122pfk8](https://www.reddit.com/r/TheSilphRoad/comments/122pfk8/).

```
HP      = floor(0.6 × (base HP + 15))       × rCPM × rank
Attack  = (base attack + attack IV)         × rCPM × rank
Defence = (base defence + 15)               × rCPM × rank
attack IV = floor(2/3 × base attack + 25)        (Rocket only; normal IVs stop at 15)
rank    = 1.0 grunt, 1.05 leader, 1.15 Giovanni
```

- **What rCPM is:** a Rocket-only multiplier that rises with your trainer level.
- **How it was found:** stat ranges from damage-per-hit tests on 13 species, then checked against about 40 CP
  readings, which all matched. One check: Snorlax at trainer level 50 gives CP 11508, the figure two players
  reported independently.
- **When the previous formula broke:** the late-2022 change was first noticed when the 2021 formula overshot CP
  by about 3,000 ([z3qck5](https://www.reddit.com/r/TheSilphRoad/comments/z3qck5/), Nov 2022).
- **Still current:** the same formula was restated in June 2026 in an equivalent form ("everything is as
  expected"; [1ub6a1h](https://www.reddit.com/r/TheSilphRoad/comments/1ub6a1h/)).

**rCPM by trainer level, since the level-80 update** (Measured from CP readings, Dec 2025): Flyfunner,
[1puc05x](https://www.reddit.com/r/TheSilphRoad/comments/1puc05x/).

| Your trainer level | 8 | 30 | 40 | 50 | 60 | 70 | 80 |
|---|---|---|---|---|---|---|---|
| rCPM | 0.299 | ≈0.91 | 1.016 | 1.111 | 1.191 | 1.265 | 1.315 |

- **The level-80 update:** it raised the cap from 50 to 80 on 15 Oct 2025
  ([Official](https://pokemongo.com/news/pgo-leveling-update-details-2025)).
- **Values moved down the table:** the old level-40 value is now the level-70 value, and the old level-50 value
  (1.315) is now level 80. A level-50 trainer therefore meets weaker Rocket Pokémon than before.
- **Players noticed:** on 16 Oct 2025 they reported easier knock-outs, e.g. Tyranitar two-shotting a Taillow
  (Unverified, [1o7syt9](https://www.reddit.com/r/TheSilphRoad/comments/1o7syt9/)).

**Does the formula still hold after Oct 2025?** As far as anyone has checked, yes.

- CP matches at every trainer level from 8 to 80.
- One recorded battle at trainer level 76 (July 2026) also matches
  ([1uwoshu](https://www.reddit.com/r/TheSilphRoad/comments/1uwoshu/), Measured, one video):
  - Mega Mewtwo Y knocked out a grunt's Nidorina in 3 Confusions; Shadow Mewtwo took 4.
  - Our check: the formula predicts exactly 3 and 4. Dropping either the 1.3× bonus or the shadow defence
    penalty would predict 4 and 5, so both are supported.
- Nobody has run a deliberate HP test since the update.

**How that compares with your own Pokémon:** a level-40 Pokémon has a CP multiplier of 0.79. At trainer level
70 (rCPM 1.265), a grunt's Pokémon therefore has:

- about 1.6× the attack before its inflated attack IV;
- about 1.6× the defence;
- about the same HP as your level-40 Pokémon.

That's our arithmetic from the formula, not a measurement.

**Older models (outdated):**

- **Jul 2019:** Pokebattler's model.
- **Nov 2019:** GamePress / skewtr: attack ×4, defence ×2, ranks 1.2 / 1.25
  ([e4sw2n](https://www.reddit.com/r/TheSilphRoad/comments/e4sw2n/)).
- **Jun 2021:** attack ×2, defence ×0.8, HP ×1.1
  ([Pokebattler-hosted study](https://www2.pokebattler.com/articles/2021/06/21/cracking-the-rocket-cp-formula-2021-edition/)).
  The 2021 study's attack-IV rule survives in the 2023 formula.

Bulbapedia's Rocket page still shows the 2021 formula (snapshot May 2026).

## 2. Shadow bonus versus the Rocket boost

**Your own shadow Pokémon:**

- Deal 1.2× damage and take 1.2× damage (defence × 5/6), in every battle type.
- This isn't shown in their CP.
- Official since 2 Mar 2020 ([Niantic](https://pokemongo.com/news/shadowpokemonupdate)).
- The game master has `shadowPokemonAttackBonusMultiplier` 1.2 and `shadowPokemonDefenseBonusMultiplier`
  0.8333333.

**The Rocket side's Pokémon:**

- They get the Rocket formula above **and** the same shadow 1.2× / 1.2× on top, applied when damage is dealt.
- **Measured** (Venonic 2023): with the shadow terms left out, the stats that matched observed damage gave the
  wrong CP. With them included, the CP matched.
- The CP formulas therefore *exclude* the shadow effect.

**Direct HP checks** (Measured):

- Yawn and Splash always do 1 damage, so the number of hits to knock out equals HP. GamePress used this in 2019,
  and Pokebattler's 2021 study did too.
- In May 2023, hit counts from video frames matched the 2023 formula once the shadow effect and the 1.3×
  Trainer Battle bonus were included ([13puajs](https://www.reddit.com/r/TheSilphRoad/comments/13puajs/)).
- No Yawn or Splash counts since Oct 2025.

## 3. IVs and moves of the Pokémon you fight

**IVs** (Measured, but thin):

- A June 2021 packet capture showed attack IVs far above 15 (Vulpix 89, Houndoom 174), defence 15 and HP 9.
  Attack fits the floor(2/3 × base + 25) rule.
- That is one capture, from an anonymous source.

**Moves:**

- Each Rocket Pokémon has one fast and one charged move from the species' current move pool. Never
  Frustration; the battled charged move "is not Frustration" (GO Hub, Oct 2026).
- Bulbapedia says moves are "randomly selected from the species' current move pool". Practitioners count
  combinations that way, e.g. Snorlax's 2 fast × 7 charged moves.
- **Legacy or Community Day moves:** probably never; no one has documented a case. **Unverified.**

**Rematches:** a lost battle can be retried against the same team. Your Pokémon are not healed.

## 4. How the Rocket side battles

**The basic pattern:** it sends Pokémon out in a fixed order and never switches until one faints. Grunts never
shield. Leaders and Giovanni shield your first two charged attacks.

**Rocket now runs on the new server-run battle system** (player reports, not confirmed by Niantic):

- **Niantic's rebuild:** it published the rebuild on 17 Feb 2026 ([Official](https://pokemongo.com/news/pvp-updates2026)):
  - damage resolves at the end of each turn;
  - swaps resolve before damage;
  - charged attacks start on the next turn;
  - battles carry on if you disconnect.

  It went live for GO Battle League on 23 Jun 2026. Neither announcement names Rocket.
- **Players saw it in Rocket earlier:**
  - From Oct to Dec 2025, players reported Rocket battles running "server side… like in PvP"
    ([1o7syt9](https://www.reddit.com/r/TheSilphRoad/comments/1o7syt9/),
    [1ov3h3v](https://www.reddit.com/r/TheSilphRoad/comments/1ov3h3v/)).
  - In Jan 2026, closing the app no longer ended a Rocket battle
    ([1qlekt0](https://www.reddit.com/r/TheSilphRoad/comments/1qlekt0/)).
  - In July 2026, a practitioner wrote "with rockets using the new pvp system"
    ([1uxdafv](https://www.reddit.com/r/TheSilphRoad/comments/1uxdafv/)).
- **What changed in Rocket battles since Dec 2025**, per a Japanese data site
  ([9db.jp](https://9db.jp/pokemongo/data/24341), table dated 2026-03-12; method not stated):
  - a fast move can now land after the opponent's charged attack starts (before, it was cancelled);
  - simultaneous charged attacks both fire.

**The pause** (the Rocket Pokémon stops attacking for a moment):

- **Official:** the pause is intended. Niantic said so when it fixed a bug that removed it in Dec 2021
  ([report](https://bleedingcool.com/games/its-not-just-you-team-go-rocket-battles-are-broken-in-pokemon-go)).
- **Its length has changed several times** (one turn = 0.5 s; 9db.jp table, method not stated):

  | Pause after… | Before Dec 2025 | Dec 2025 | Sep 2026 |
  |---|---|---|---|
  | a charged attack (the table doesn't say whose; we read it as yours) | 5 turns | 8 | 7 |
  | a faint and replacement | 7 | 12 | 7 |
  | your manual switch | 7 | 12 | 9 |

- **A practitioner's counts agree** (cwizz1, [r/TheSilphArena/1vyspr1](https://www.reddit.com/r/TheSilphArena/comments/1vyspr1/),
  Aug 2026): "7 turns after any charged move or switch", with your own switch effectively 6.
- **Sources disagree** on the manual switch (9 turns or 7) and on how to count; one player says 6 turns is the
  safe maximum.
- **Earlier claims of "4 turns" were about charged attacks**, and are outdated.

**When it uses its charged attack:**

- The working assumption is: as soon as it has the energy and isn't paused. It has only one charged move, so
  there is no choice to make.
- At least one public simulator assumes exactly this (a tool model, not a measurement).
- No one has measured it, and one practitioner asked "how often a Rocket throws a charged move assuming they've
  reached the energy" (Nov 2026), so there is no consensus. **Unverified.**

## 5. Leaders and Giovanni

- **Strength:** the only stat difference from grunts is the rank multiplier (1.05 and 1.15). Measured through
  CP fits since 2021; in 2019 the ranks were 1.2 and 1.25.
- **Giovanni:**
  - His third Pokémon is the shadow legendary you catch. Since 3 Mar 2026 it can be shiny (Bulbapedia).
  - The Super Rocket Radar no longer guarantees him: since 25 Jun 2026 it reveals stops that are often decoy
    grunts, and it is used up only when you beat the real Giovanni (Bulbapedia, edited 28 Jun 2026).
- **Leader teams:** fixed per PokéStop per day for everyone (Bulbapedia).

## 6. What you catch, and purifying it

**Every Rocket catch, Giovanni's included:**

- Level 8, or 13 in boosting weather, since 7 Nov 2019 (Bulbapedia, Shadow Pokémon page, Nov 2026 snapshot).
- A June 2026 note on how purified Rocket catches behave agrees
  ([1ub6a1h](https://www.reddit.com/r/TheSilphRoad/comments/1ub6a1h/)).
- IVs are rolled like a wild Pokémon: no floor, or at least 4 in boosting weather.

**Giovanni's legendary:**

- Every IV is at least 6, since July 2020, and the first Premier Ball that hits always catches it. Bulbapedia
  cites a Niantic support post for both; we couldn't retrieve that post.
- **One conflicting report** (June 2026,
  [1ug9g00](https://www.reddit.com/r/TheSilphRoad/comments/1ug9g00/)): a weather-boosted Reshiram showed "1300s"
  CP. That fits neither level 8 (about 900) nor 13 (about 1600). Unverified.
- An earlier claim of level 15 (a single player, 2020) is outdated or wrong.

**Purifying:**

- +2 to each IV (capped at 15), raises the Pokémon to your trainer level (up to 25), and replaces Frustration
  with Return.
- It loses the shadow bonus and gains no bonus against shadows (game master:
  `purifiedPokemonAttackMultiplierVsShadow` = 1.0).

## 7. Other things that change the result

- **The 1.3× Trainer Battle bonus** applies to every attack, on both sides (Measured: needed to match hit
  counts in 2023 and 2026).
- **No team boosts:** no weather boost, no friendship boost, no mega boost to the team. A Mega Pokémon fights on
  its own stats.
- **Your charged attacks** scale with the charge-up mini-game, 0.25× to 1×.
- **Party and timers:** a party of three, 12 s to pick a replacement, a 45 s switch cooldown.
- **Battle timer:** about 12 minutes, not GO Battle League's 4:30 (Measured, two videos,
  [1q13cga](https://www.reddit.com/r/TheSilphRoad/comments/1q13cga/), Jan 2026). Each charged attack seems to add
  about 7 s. A countdown shows only in the last 30 s.
- **What a timeout means:** since late 2025 it is decided like GO Battle League (more Pokémon left wins, then
  HP%); before that it counted as a loss.
- **Premier Balls:** more for each of your Pokémon still standing, plus medal bonuses.
- **Your trainer level** is the only thing on your side that changes the opponent.

## What this means for the analyser

- **A simulator has solid ground:**
  - the 2023 formula with the Dec 2025 rCPM table;
  - the shadow 1.2× / 1.2× and the 1.3× bonus on top;
  - trainer level as an input;
  - the current 7-turn pauses, the new turn rules and the 12-minute timer.
- **Shadow Battler**, an open-source Rocket simulator (Nov 2026): not used here; its results are disputed in
  [1xsz8v1](https://www.reddit.com/r/TheSilphRoad/comments/1xsz8v1/).
- **Pokebattler's published tier block** (×3 attack, ×2 defence) and the 2021 formula are both outdated.

## Open questions, and how to answer them cheaply

| Question | What's known | Cheap check in the game |
|---|---|---|
| Does the 2023 formula hold after Oct 2025? | Yes for CP at every level, and one video hit count matches. No deliberate HP test. | **Exact HP:** bring a Yawn Snorlax (Yawn always does 1 damage) against a grunt's slot-1 Pokémon such as Magikarp, with shields and potions. Count Yawns until it faints and compare with floor(0.6 × (base HP + 15)) × rCPM at your trainer level. Note your trainer level, the species and the count. 1–2 battles. |
| Did the 2026 rebuild reach Rocket? | Almost certainly, around Dec 2025 (player reports; Niantic never said). | None needed; the pause and timer checks below would show it. |
| When does it use its charged attack? | Assumed "as soon as it can"; unmeasured. | Lead a Pokémon that resists the enemy's fast move and use no charged attacks. Count the enemy's fast moves, work out when its energy reaches the cost (PvPoke energy values), and note the turn it actually fires. 5–10 times, about 2–3 battles. Any gap outside a pause means it holds energy. |
| Pause after a faint: 4 or 7–8 turns? | About 7 turns now (two sources, Aug–Sep 2026), give or take one depending on how you count. | With a 1-turn fast move (Water Gun, Lock-On), count your fast moves between (a) knocking out their Pokémon, (b) your charged attack, (c) your manual switch, and their first damage. 5 of each, about 3 grunts. Screen-record if possible. |
| Giovanni's catch level and IV floor | Level 8 (13 in weather), IVs at least 6, per the wiki; one odd weather report. | Right after the catch, note the weather icon, CP, appraisal and the first power-up stardust cost: shadow costs are 960 at level 8 and 1920 at level 13. Cross-check with CP, since the cost display sometimes lags a level. |
| Legacy moves on Rocket Pokémon? | Probably never; no documented case. | Passive: during takeovers, note every charged move a Rocket Pokémon uses and check it against PvPoke's legacy list. |
| Battle timer | About 12 minutes, plus about 7 s per charged attack; timeouts are decided by Pokémon left, then HP. | Optional: in a naturally long leader battle, note the elapsed time when the 30 s countdown appears and how many charged attacks were used. |
