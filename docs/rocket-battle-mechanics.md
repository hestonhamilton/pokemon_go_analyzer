# What decides Team GO Rocket battles

Research notes for this tool, collected 2026-11-13. Every claim carries a source tag:

- **OFFICIAL**: Niantic, pokemongo.com, or the in-game help centre.
- **DATAMINED**: the game master (GM), or code that reads it.
- **COMMUNITY**: Pokebattler, PvPoke, GO Hub, GamePress, Reddit research posts.
- **UNSOURCED**: widely believed, but we found no source.

GM values were checked against two data-mines:
[PokeMiners/game_masters](https://github.com/PokeMiners/game_masters) (stale: GM timestamp 2026-08-28) and
[alexelgt/game_masters](https://github.com/alexelgt/game_masters) (uploaded 2026-11-11). Every combat value
below is the same in both.

Short version for picking counters: Rocket battles use the **Trainer Battle (PvP)** rules and move stats, not
the raid ones. The NPC's Pokémon are shadows with heavily boosted stats. Grunts never shield. Leaders and
Giovanni shield your first two charged moves. So the stats that decide the result are type effectiveness,
fast-move damage and energy per turn, and the attacker's effective attack and bulk.

## 1. Battle system: Trainer Battle rules

- Battles are turn-based, using the Trainer Battle combat settings:
  - each turn is 0.5 s;
  - energy caps at 100;
  - STAB (same-type attack bonus) is 1.2;
  - a 1.3 bonus applies to both fast and charged moves (`fastAttackBonusMultiplier`, `chargeAttackBonusMultiplier`);
  - stat stages run from −4 to +4, multipliers `[0.5, 0.571, 0.667, 0.8, 1, 1.25, 1.5, 1.75, 2.0]`.
  - Source: GM templates `COMBAT_SETTINGS` and `COMBAT_STAT_STAGE_SETTINGS` (DATAMINED). The raid settings live in a separate block
    (`BATTLE_SETTINGS`, 99 s rounds), which Rocket battles do not use.
- GO Hub calls the battles turn-based
  ([guide](https://pokemongohub.net/post/guide/go-hub-guide-to-team-go-rocket-battles)) (COMMUNITY).
  GamePress's 2019 research on the grunt stat formula uses the 1.3 PvP bonus
  ([node/1178586](https://pogo.gamepress.gg/node/1178586)) (COMMUNITY). We found no official page that says in
  so many words "Rocket battles use Trainer Battle moves". The help centre only says you battle with Fast and
  Charged Attacks, three Pokémon to a party
  ([FAQ 1190](https://scopelyexplore.helpshift.com/hc/faq/1190-team-go-rocket-grunts/)) (OFFICIAL).
- **Damage formula**, as PvPoke's
  [DamageCalculator.js](https://github.com/pvpoke/pvpoke/blob/master/src/js/battle/DamageCalculator.js)
  implements it (DATAMINED):

  ```
  damage = floor(0.5 × power × (atk / def) × STAB × effectiveness × charge × 1.3) + 1
  atk    = (base_atk + iv_atk) × CPM × shadow_atk × stage_buff
  def    = (base_def + iv_def) × CPM × shadow_def × stage_buff
  ```

  The effectiveness multipliers are 1.6 (super effective), 2.56 (double super effective), 0.625 (resisted) and
  0.390625 (double resisted or immune). They come from the GM `POKEMON_TYPE_*` `attackScalar` arrays
  (DATAMINED). PvPoke uses float32 values for its constants, e.g. 1.2999999523 and 1.2000000477; match them to
  get the same rounding.
- No Rocket- or NPC-specific damage or stat multiplier exists anywhere in the GM. Whatever boosts Rocket
  Pokémon is applied on the server (DATAMINED: we searched every field path in all 18,812 templates).
- **2026 battle timing update**
  ([pokemongo.com/news/pvp-updates2026](https://pokemongo.com/news/pvp-updates2026)) (OFFICIAL):
  - charged attacks begin on the next turn;
  - swaps resolve before damage;
  - quick swaps cost a turn;
  - damage and energy resolve at the end of each turn.

  The post says this applies to "all battle modes" but never names Rocket.

## 2. Shadow modifiers

- Shadows get ×1.2 attack and ×0.8333333 (5/6) defence (DATAMINED: `shadowPokemonAttackBonusMultiplier` and
  `shadowPokemonDefenseBonusMultiplier`, in both the combat and battle settings). PvPoke uses 0.83333331.
  [GO Hub's shadow guide](https://pokemongohub.net/post/guide/shadow-pokemon-guide-stats-levels-ivs-lucky-trading/)
  says "−20% defence", which is wrong: the GM value is −16.7%.
- Purified Pokémon get no bonus against shadows (`purifiedPokemonAttackMultiplierVsShadow` is 1.0, DATAMINED).
  Purifying adds +2 to each IV (capped at 15), sets level 25, and swaps Frustration for Return (COMMUNITY, GO Hub).
- **PvP move values:** Frustration is 10 power / 70 energy; Return is 130 power / 70 energy. In the GM, each
  species' `shadow.shadowChargeMove` field names Frustration and `purifiedChargeMove` names Return (DATAMINED).
- The bonus works in both directions: your shadow attackers hit 20% harder and are about 17% squishier, and the
  NPC's Pokémon are shadows too. Pokebattler models every Rocket opponent as the `*_SHADOW_FORM` of its species
  ([rocket2.json](https://static.pokebattler.com/rocket2.json)) (COMMUNITY).

## 3. Level, CP and the NPC stat boost

**The NPC's Pokémon do not use normal player stats.** Pokebattler's public Rocket endpoint
(`fight.pokebattler.com/rocket`, `tiers[].info`) gives this model (COMMUNITY):

| Pokebattler tier | Who | Level | CPM | ×Atk | ×Def | ×Sta | Battle time |
|---|---|---|---|---|---|---|---|
| RAID_LEVEL_1 | Typed grunts | 27 | 0.6941 | 3.0 | 2.0 | 1.0 | 180 s |
| RAID_LEVEL_2 | Mixed (untyped) grunts | 30 | 0.7317 | 3.0 | 2.0 | 1.0 | 180 s |
| RAID_LEVEL_UNSET | Fallback | 27 | 0.6941 | 2.5 | 2.5 | 2.5 | 180 s |

- The CPMs match the GM's level 27 and level 30 values (DATAMINED).
- In Pokebattler's front end, tier 3 is decoys, tier 4 is leaders and tier 5 is Giovanni. The endpoint does not
  publish parameters for tiers 3 to 5.
- GamePress's 2019 study ([node/1178586](https://pogo.gamepress.gg/node/1178586)) (COMMUNITY) reaches different numbers:
  - grunt Pokémon have 15/15/15 IVs;
  - their attack is about 3.2× that of a level-40 Pokémon with 15 attack IV, an effective CPM of about 2.53,
    compared with about 2.08 in Pokebattler's model;
  - their defence is about 1.6×.
- **Open question:** which model is current, and whether these multipliers already include the shadow
  1.2 / 0.833.

| Rule | Value | Source |
|---|---|---|
| Your own CP or level cap | None. Pokebattler lets you pick attacker level 20 to 50, default 40. | OFFICIAL by omission; COMMUNITY |
| Caught shadow's level | 8, or 13 if weather boosted, for grunts, leaders and Giovanni | COMMUNITY, [GO Hub](https://pokemongohub.net/post/guide/shadow-pokemon-guide-stats-levels-ivs-lucky-trading/) |
| Caught shadow's IV floor | None for grunts; 4/4/4 if weather boosted. Giovanni's legendary is reported at 6/6/6 (sources conflict for leaders). | COMMUNITY |

## 4. Moves: use the PvP stats

Use the GM `COMBAT_V####_MOVE_*` (`combatMove`) entries, not the PvE `moveSettings` entries. They differ: Dragon
Breath is 6 power in PvE but 3 in PvP. A missing `durationTurns` means one turn, and PvPoke's `turns` field is
`durationTurns + 1` (DATAMINED).

| Fast move | Power | Energy gain | Turns | Damage per turn | Energy per turn |
|---|---|---|---|---|---|
| Mud Shot | 3 | 9 | 2 | 1.5 | 4.5 |
| Counter | 8 | 6 | 2 | 4.0 | 3.0 |
| Snarl | 5 | 13 | 3 | 1.67 | 4.33 |
| Dragon Breath | 3 | 4 | 1 | 3.0 | 4.0 |

- Charged moves cost energy, and some have a chance to buff or debuff (Crunch: 70 power, 45 energy, 20% chance
  of −1 to the target's defence).
- The GM also holds charged-attack minigame scores (0.25 / 0.5 / 0.75 / 1.0). Simulators assume every charged
  attack lands as Excellent, and PvPoke forces the multiplier to 1 for AI opponents (COMMUNITY). We could not
  confirm whether the minigame score still scales damage in live Rocket battles today.

## 5. Shields, switching and the NPC's behaviour

- **Grunts** have 2 shields and never use them (COMMUNITY: GO Hub, BGR, Bulbapedia).
- **Leaders and Giovanni** have 2 shields and use them on your first two charged attacks (COMMUNITY:
  [GamePress node/46686](https://gamepress.gg/node/46686), Bulbapedia,
  [GO Hub leader guide](https://pokemongohub.net/post/guide/team-go-rocket-leader-guide/)). Hence the standard
  tactic: bait both shields with your cheapest charged move.
- **Stun window:** GamePress reports the NPC does nothing for 4 turns after any charged move or switch,
  including the switch-in after a faint (COMMUNITY: node/46686, node/84031). One low-quality 2021 source
  disagrees, and nobody has checked whether the 2026 timing changes kept the window.
- **NPC switching:** the NPC sends out slots 1, 2 and 3 in order and never switches voluntarily (UNSOURCED, but
  universally observed). A rematch after a loss keeps the same team (COMMUNITY).
- **When the NPC fires charged moves:** not documented anywhere we found.
- **Your switching:** the GM's PvP settings have a 45 s quick-swap cooldown and a 12 s change-Pokémon timer
  (DATAMINED). Not confirmed for Rocket battles.
- **Battle length:** Pokebattler simulates a 180 s Rocket battle; the GM's PvP round is 270 s. These conflict.
- **Not Rocket data:** the GM's `combatNpcPersonality` entries (`superEffectiveChance`, `specialChance`, and the
  offensive and defensive minimum and maximum scores) belong only to the team-leader training battles (Blanche,
  Candela and Spark, `TRAINER_*_GREAT/ULTRA/MASTER`) (DATAMINED). The Rocket character templates hold only
  display settings, so Rocket AI and shield logic live on the server. Don't model Rocket AI from those fields.

## 6. How established tools score counters

**Pokebattler** (`/rocket/defenders/{P}_SHADOW_FORM/levels/RAID_LEVEL_{1..5}/attackers/levels/{L}`) (COMMUNITY):

- Simulates every moveset of the defender and averages the results (`meta=DUAL_MOVE`, `aggregation=AVERAGE`,
  `dodgeStrategy=DODGE_REACTION_TIME`, one-Pokémon party).
- Shield settings: your shields (`shieldStrategy`) 0, 1 or 2; the defender's (`defenderShieldStrategy`) 0 or 2.
- Sort orders: POWER (the Rocket hub's default), OVERALL, WIN (win ratio), TIME (time to win), TDO, DPS,
  DEATHS, POTIONS, ESTIMATOR.
- The formulas behind POWER and OVERALL are **not published**.
- Its developer page calls the API unofficial, with no SLA, and asks users to cache aggressively. robots.txt
  disallows `/api` and lets crawlers fetch only the default views.

**PvPoke** ([GitHub](https://github.com/pvpoke/pvpoke), MIT):

- No Rocket simulator. Its training AI is its own design
  ([article](https://pvpoke.com/articles/development/developing-trainer-battle-ai/)).
- Its **battle rating** is `floor(500·damageDealt/oppHP + 500·hpLeft/ownHP)`, from 0 to 1000; above 500 is a
  win ([Pokemon.js `getBattleRating`](https://github.com/pvpoke/pvpoke/blob/master/src/js/pokemon/Pokemon.js#L2134)).
  League rankings average battle rating across weighted matchups.
- Its engine could run Rocket one-on-ones if given the NPC stat model above.

**GO Hub, GamePress, LeekDuck:** hand-curated counter lists with no published metric. GamePress supplied the
stat-formula and stun-window research.

## 7. What matters most, ranked

1. **Type effectiveness** against each slot's possible Pokémon: the damage you deal (1.6 / 2.56) and the
   damage you resist from their likely moves (0.625 / 0.39). It multiplies everything else.
2. **Fast-move damage per turn** (PvP power × STAB × effectiveness ÷ turns) at your effective attack. Leaders
   shield your first two charged moves and the stun window slows the pace, so fast moves do most of the work.
3. **Effective attack**, (base + IV) × CPM × 1.2 if shadow, against the NPC's boosted defence. This sets
   breakpoints and turns to knock out.
4. **Bulk** (defence × HP, × 5/6 if shadow) against the NPC's ~3× attack. This sets survival and how many slots
   one Pokémon can sweep. Fewer fainted Pokémon also means more Premier Balls after leader and Giovanni
   battles (help centre).
5. **Energy per turn plus the cost of your cheapest charged move.** Against leaders and Giovanni this sets how
   fast you strip both shields.
6. **Charged-move damage per energy** (power ÷ energy × STAB × effectiveness). This matters most against
   grunts, who never shield, so your nukes always land.
7. **Time to win** (turns to knock out a slot or the whole lineup). This is Pokebattler's TIME sort, the right
   goal when farming grunts.
8. **Coverage:** the share of a slot's possible Pokémon (and their movesets) that a counter beats. This
   approximates Pokebattler's "against every moveset" averaging.

A defensible score: simulate each attacker against each slot Pokémon turn by turn with the PvP rules above.
Rank by win rate first, then by PvPoke-style battle rating (HP left), then by time to win.

## 8. Open questions

1. The NPC stat multipliers for leaders, Giovanni and decoys. Do the ×3 / ×2 multipliers already include the
   shadow 1.2 / 0.833? Which is current: GamePress's ~2.53 effective CPM or Pokebattler's ~2.08?
2. How Pokebattler computes POWER and OVERALL.
3. When the NPC uses charged moves. Did the 4-turn stun window survive the 2026 timing changes?
4. Whether the charged-attack minigame scales damage in Rocket battles.
5. Battle length (180 s or 270 s) and swap cooldowns in Rocket battles.
6. Rocket movesets. Are they random from the species' pool? Is Frustration excluded?
7. IV floors for leader and Giovanni catches.
