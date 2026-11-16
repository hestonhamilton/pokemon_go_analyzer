# Stat stages: prior art and recommendations

Researched 2026-11-16. Research only: no engine code changes until the owner picks an option.

## The problem

The Rocket simulator applies no stat stages. `sim/battle.py`'s header says only ordinary, unbuffed
moves are represented, and the report's limitations line says move effects are unsupported.
Our damage function already takes `attack_stage` and `defence_stage` (`sim/damage.py` 82–86,
105–106), but the battle loop always passes 0.

How this shows in the 2026-11-16 level-50 reports (figures from the bead):

- 70 of the 260 top-10 entries use a charged move that changes a stat.
- 48 of those moves always weaken the user: Close Combat 15, Wild Charge 12, Superpower 11,
  Mind Blown 7, Brave Bird 2, Glaive Rush 1, Dragon Ascent 1.
- Blacephalon with Mind Blown (90 power, 35 energy, self −4 Defence) ranks #1 against the Bug,
  Fairy and Psychic grunts. Its defence penalty costs it nothing in our model.
- Buffs and opponent debuffs earn no credit either: Flame Charge (+1 Attack), Power-Up Punch
  (+1 Attack), Icy Wind and Mystical Fire (−1 to the target's Attack), Bulldoze (−1 to the target's
  Defence).

The Rocket side is affected too. Our Rocket pools enumerate every fast × charged pair in PvPoke's
learnset (`sim_cli.py` 140–170). Using today's event-info lineups, mapped to base forms (an
approximation of `lineups.py`'s resolution), 859 of 2,746 Rocket moveset options (31%) carry a
stat-changing charged move. 377 of those are chance-based, led by Crunch (20%, −1 Defence to the
target), Psychic (10%) and Scorching Sands (10%). The guaranteed ones include Rock Tomb, Brick Break and
Psychic Fangs on the target, and Superpower, Close Combat and Overheat on the user.

## Game data (data-mined)

PvPoke's game master, at the commit the engine is pinned to
([426e5e9](https://github.com/pvpoke/pvpoke/tree/426e5e9f39d3a027849698fb2f5edd9df6056cbf)) and at
master ([2ad2682](https://github.com/pvpoke/pvpoke/tree/2ad2682e6a6bb65d96aff151fe4feaad81383133),
2026-11-16):

- `settings.maxBuffStages = 4`, `settings.buffDivisor = 4`.
- For each move: `buffs` as [attack, defence], `buffTarget` (`self`, `opponent` or `both`, with
  `buffsSelf` and `buffsOpponent` for `both`), and `buffApplyChance` (a string, "1" when guaranteed).
- 102 charged moves change a stat; 39 of them only by chance.
- Mind Blown [0, −4] self, chance 1. Close Combat and Wild Charge [0, −2] self. Brave Bird [0, −3]
  self. Superpower (`SUPER_POWER`) [−1, −1] self. Crunch [0, −1] opponent, chance 0.2.
  Obstruct: self [0, +1], opponent [0, −1].

The game master's `COMBAT_STAT_STAGE_SETTINGS` gives the same ladder (ledger row o): ×1.25, 1.5, 1.75, 2
going up and ×0.8, 0.667, 0.571, 0.5 going down. In PvPoke's code this is `(4 + s) / 4` for a positive
stage and `4 / (4 − s)` for a negative one, clamped to ±4 per stat. Our `stage_multiplier` already
ports it.

## Prior art

### PvPoke (the engine we port)

All line numbers are at the pinned commit 426e5e9. They are identical at master 2ad2682 for every
line cited.

- **State.** Each Pokémon holds `statBuffs = [attack, defence]`
  ([Pokemon.js 47](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/pokemon/Pokemon.js#L47)).
  `applyStatBuffs` adds the move's stages and clamps each one to ±`maxBuffStages`
  ([Pokemon.js 2077–2085](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/pokemon/Pokemon.js#L2077)).
  `getStatBuffMultiplier` is the ladder above
  ([Pokemon.js 2113–2126](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/pokemon/Pokemon.js#L2113)).
- **Order.** A move's damage is dealt first, then its stat change is applied
  ([Battle.js 1389](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1389)
  and after). A self-debuff therefore does not weaken the hit that causes it.
- **Guaranteed effects** (chance 1) always apply outside sandbox mode, even when chance effects are
  turned off: "Force guaranteed buffs even when they're disabled"
  ([Battle.js 1403–1404](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1403)).
- **Chance effects** depend on `buffChanceModifier`
  ([Battle.js 74](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L74):
  "-1 prevents buffs, 1 guarantees buffs"):
  - **Default single battles and rankings** (modifier −1) use a deterministic "buff apply meter".
    Each use adds the chance to a counter, and the effect fires when the counter crosses a whole number
    ([Battle.js 1407–1416](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1407)).
    The meter starts at the chance itself, except at 0 for 50% moves: "For moves with a 50% chance,
    apply on the second activation"
    ([Pokemon.js 737–746](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/pokemon/Pokemon.js#L737)).
    With float addition, a 50% or 33% move fires on its 2nd use, 30% on its 3rd, 20% on its 4th,
    12.5% on its 7th and 10% on its 10th. The web UI also sets −1 before its single battle
    ([Interface.js 2545](https://github.com/pvpoke/pvpoke/blob/2ad2682e6a6bb65d96aff151fe4feaad81383133/src/js/interface/Interface.js#L2545), master).
  - **Multi-battle "bulk" runs** set the modifier to 0, which is a true random roll:
    `Math.random() > 1 − chance`
    ([Interface.js 1785](https://github.com/pvpoke/pvpoke/blob/2ad2682e6a6bb65d96aff151fe4feaad81383133/src/js/interface/Interface.js#L1785), master;
    [Battle.js 1397, 1419](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1397)).
    The code's own comment calls this "Totally not Really Random but just to get off the ground for now".
  - **Sandbox** (user-scripted) battles apply a move's effect only when the user ticks it (`forceBuff`,
    [Battle.js 1399–1400](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1399)).
    Users can also set a Pokémon's starting stages (`startStatBuffs`).
  - **Move ranking**, not the battle itself, uses expected value: it scales a buff move's
    damage-per-energy by `(4 + stages × chance × 80 / energy) / 4`, "a rough number of times the move
    will be used in battle"
    ([Pokemon.js 900–912](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/pokemon/Pokemon.js#L900)).
- **Switching** resets the outgoing Pokémon's stages: "Reset the outgoing Pokemon's buffs and debuffs"
  ([Battle.js 995–997](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L995)).
- **Shields.** A shielded debuff still applies. The "Don't debuff if it shields" branch sets a modifier
  that is already 0, so it changes nothing
  ([Battle.js 1049, 1229–1232](https://github.com/pvpoke/pvpoke/blob/426e5e9f39d3a027849698fb2f5edd9df6056cbf/src/js/battle/Battle.js#L1229)).
  PvPoke's AI also avoids shielding early self-buffing moves and holds shields against users of
  defence-dropping nukes (Battle.js 1091–1112). That is shield policy, which we do not port.

### Other sources

- **GamePress** (via search snippet): stat changes "happen even if the move is shielded. This is true for
  buffs (like Power-Up Punch) and debuffs (like Acid Spray)". The page could not be opened (404), so the
  quote is from the snippet only.
- **9db.jp** [buff moves](https://9db.jp/pokego/data/50) (updated 2021-11-21): the same ladder, and
  effects apply "even if opponent uses shield". It also says a buff survives switching out and back in.
  That conflicts with PvPoke and Bulbapedia. It may describe the 2019 period when switching briefly
  changed: [GO Hub, July 2019](https://pokemongohub.net/post/news/niantic-removes-the-new-switching-mechanic-from-trainer-battles/)
  lists "buffs and debuffs clearing out during the switching process" among that change's bugs.
- **Bulbapedia** *Trainer Battle (GO)* (via search snippet; the page returned 403): "Switching Pokémon
  also resets all stat changes."
- **Official 2026 rebuild post** ([pokemongo.com](https://pokemongo.com/news/pvp-updates2026)):
  "Charged Attacks that cause stat changes will be applied before the Fast Attack is applied", and
  outcomes are consistent "barring chance-based effects such as stat changes from attacks like
  Night Slash". So since the rebuild, a fast move that lands during the charged sequence uses the
  new stages. The game rolls chance effects; it does not use PvPoke's meter.
- **GO Hub mechanics guide** ([2018–2019](https://pokemongohub.net/post/pvp/comprehensive-pvp-mechanics-guide-in-pokemon-go/)):
  the ±4 stage range from the game master, written before the feature went live. Its listed multipliers
  (0.33 to 3) predate today's ladder, so the guide is of historical interest only.
- **Pokebattler**: we found no public description of how its Rocket or PvP simulations treat stat
  changes. Unknown, not "ignored".
- **GO Battle Log**: no public simulator or documentation turned up. Nothing to cite.

### Rocket battles specifically

We found **no measurement** of stat stages in Rocket battles: not of a player's buff, not of a
self-debuff, and not of a Rocket Pokémon's effect landing on the player. Neither 9db's Rocket timing page
([24341](https://9db.jp/pokemongo/data/24341)) nor the Rocket guides mention them. Practitioners assume
Trainer Battle rules apply, as they do for damage (ledger rows a and f). Rocket guides credit
Power-Up Punch's value to the pause it triggers, not to its buff
([GO Hub Rocket guide](https://pokemongohub.net/post/guide/team-go-rocket-battle-guide/)). Ledger row o
stays "data-mined; unmeasured in Rocket ⚑".

## Gaps against our engine and ledger

| Item | Grade | Our engine today | Needed |
|---|---|---|---|
| Ladder, ±4 cap (ledger o) | data-mined; unmeasured in Rocket | `stage_multiplier` ported and tested; the battle loop always passes 0 | Track stages per combatant |
| Damage first, then the stat change | PvPoke code; consistent with the official rebuild wording | — | Apply after `calculate_damage` |
| Fast moves landing during the charge use the new stages | official (2026 rebuild post) | — | Order it in the charge resolution |
| Effect applies through a shield | GamePress, 9db, PvPoke code (community + port) | Grunts never shield; leaders and Giovanni do (ledger m) | Apply regardless of the shield |
| Reset on switch | Bulbapedia, PvPoke; 9db 2021 disagrees | The player never switches voluntarily; Rocket switches only on a faint | Reset on faint or switch. A solo player's stages **carry across Rocket slots**, as its HP and energy already do (`rocket.py` 285) |
| Chance effects | game: random roll (official post); PvPoke: meter or roll | — | A policy choice (below) |
| Rocket side uses the same rules | assumed | Rocket fires any pooled charged move when ready (ledger l) | Same code path for both sides |
| Shield and charged-move AI that knows about stages | PvPoke heuristics | Not ported (single charged move, fixed shield policy) | Out of scope |

Fixtures: F5's debuffed rows are excluded today (ledger o), and no fixture records a Rocket-side
stat change (`simulator-verification.md` line 82).

## Options

### A. PvPoke default parity (recommended)

Track stages on both sides. Guaranteed effects always apply. Chance effects follow PvPoke's
deterministic meter (Battle.js 1407–1416). Damage is dealt before the change. Stages reset when a
Pokémon faints or switches, and the player's stages carry across Rocket slots.

- **Why:** the engine is a PvPoke port, and this is the mode PvPoke's own rankings and single battles
  run in. The existing battle-parity oracle (`tools/parity/pvpoke_battle_parity.py`) already executes
  PvPoke's own `applyStatBuffs`, `getEffectiveStat` and `getStatBuffMultiplier`, so parity is directly
  testable. It stays deterministic, so common random numbers and whole-percent bands are untouched.
- **Against:** the meter is a PvPoke device, not the game; the game rolls. A 10% move (Psychic on the
  Rocket side) fires only on its 10th use, which in practice means never. A 50% move always fires on
  its 2nd.

### B. Guaranteed effects only

As A, except chance effects never apply.

- **Why:** this is the part that fixes the reported bias. Every always-on self-weakening move in the
  top 10 is guaranteed (chance 1). Simplest to explain: "chance effects are ignored".
- **Against:** it diverges from PvPoke's default for 39 moves, so parity holds only for moves with
  guaranteed or no effects. Crunch is the most common chance move in the Rocket pools, and its
  defence drop on the player would never count.

### C. Roll chance effects (Monte Carlo or branch enumeration)

Guaranteed effects as in A. Chance effects are rolled with a seeded random draw, or every outcome is
enumerated with its probability.

- **Why:** closest to the game, which rolls (official rebuild post). It yields a true expected win rate.
- **Against:** the cost multiplies. Sampling needs about 32 or more draws per battle that uses a chance
  move to keep whole-percent bands stable. Enumeration doubles with every chance activation. The
  weekly overall union takes about 14 hours today (README "Precompute reports"), so this puts it into
  days. Results become noisy near band edges, and seeds must be shared across builds to keep common
  random numbers.

### D. Keep ignoring stat changes; badge the affected entries

No engine change. The site marks every build or Rocket option with a stat-changing move ("Stat change
not modelled") and the limitations line names it.

- **Why:** cheapest, and honest about the gap.
- **Against:** the ranking stays wrong. Blacephalon stays #1 against three grunts with a −4 Defence it
  never pays for.

**Ruled out:** expected-value fractional stages (for example −0.2 Defence per Crunch). The game has no
fractional stages, and EV stages misstate breakpoints. PvPoke uses EV only to rank moves, never inside
a battle.

## Cost

- **Engine:** per-combatant `[attack, defence]` stages in the battle state, applied after damage and
  reset on faint. Move data needs `buffs`, `buffTarget`, `buffsSelf`/`buffsOpponent` and
  `buffApplyChance` from the PvPoke game master we already load. For A, the meter per move must also be
  initialised and reset per battle.
- **Runtime:** A and B add constant work per charged move, so the battle count is unchanged and run
  time should change by a few percent at most (to be measured). C multiplies work, as above.
- **Recompute:** any of A–C invalidates every cached report and screen. Per-type runs, the overall
  completion (about 14 minutes on 4 workers) and the weekly overall union (about 14 hours) all need a
  full rerun. The pogo-ui track owns the refresh and the site; this is sequenced through orch.
- **Tests:** unit tests for clamping, damage-then-change order, faint reset, carry-over across Rocket
  slots and a shielded debuff (leaders). For A, the meter schedule (use numbers 2, 3, 4, 7, 10 for
  chances 0.5, 0.3, 0.2, 0.125, 0.1). Existing battle and aggregate reference outputs change only for
  battles that use a stat-changing move; regenerating them is part of the slice.

## Validation plan

1. **PvPoke parity (A; B for guaranteed moves).** Extend the battle-parity oracle's adapter to give
   moves their `buffs`, `buffTarget` and `buffApplyChance` and to initialise `buffApplyMeter` as
   Pokemon.js 737–746 does (`resetMoves` is a no-op today). Run Battle.js with the default
   `buffChanceModifier = −1`. Cases:
   - Blacephalon (Incinerate / Mind Blown) against a Bug grunt's slot Pokémon: a −4 Defence
     self-debuff, with the cap reached on the first use;
   - Machamp with Close Combat: −2 then −4, hitting the cap;
   - Lucario with Power-Up Punch: stacking up to +4;
   - a Rocket Crunch user against the player: the meter fires on the 4th use;
   - a shielded Icy Wind against a leader slot: the debuff still applies.
   Pass: identical timelines (HP, energy, stages per turn).
2. **Game checks (owner, optional).** These lift ledger row o from "unmeasured in Rocket":
   - Power-Up Punch: count Counter or Force Palm damage on a grunt before and after one Power-Up Punch
     (the falsifier is already in the ledger: a +1 Force Palm that isn't 21);
   - self-debuff: note the damage taken from the same Rocket fast move before and after one Close
     Combat or Mind Blown.
   About three battles each.

## Recommendation

**A**, behind a `Rules` flag that defaults to on once parity passes, with B kept as a named option.
A is the only option that is both parity-testable against the engine we port and cheap to recompute.
It also fixes the bias the reports show (free self-debuffs) without adding noise. The meter's
artificial schedule for chance moves is disclosed in the limitations line; C remains possible later if
measured Rocket data ever show it matters.
