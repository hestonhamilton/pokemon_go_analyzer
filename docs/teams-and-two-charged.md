# Two charged moves and teams of 2–3 (experiment, 16 Nov 2026)

Bead pgo-c82. These are measurements on the merged engine with stat stages (cbe2708) at
level 50, against that evening's refreshed lists, for Giovanni, Cliff, Arlo, Sierra and the
male Ghost grunt. Every number is an estimate.

## Owner decisions

- Two charged moves: leaders and Giovanni only, for every finalist species, after the normal
  ranking (option 1A).
- Teams: no team ranking for now (option 2A).

## Two charged moves

Under the default player policy, the first affordable charged move is the one that fires.
That is almost always the cheaper move, so a second, bigger move would rarely be used. The
experiment used a different player policy instead, "bait, then best hit":

1. While the leader still has shields, fire the cheapest affordable move. Leaders and
   Giovanni shield the first two charged attacks.
2. After that, fire only the move that does the most damage to the current Rocket Pokémon
   (power × STAB × type effectiveness), and wait until it is affordable.

This is a model of how players play, not a measurement.

Results:

- Out of each top 20, the number of species that improved was: Giovanni 11, Arlo 12,
  Sierra 10, Cliff 7. Each leader's top 10 gained 1–3 new species.
- The largest gains were on Giovanni:
  - Kyurem Black: 60% → 100% (Dragon Tail with Freeze Shock + Fusion Bolt).
  - Ursaluna: 62% → 100% (Scratch with High Horsepower + Trailblaze).
  - Florges: 77% → 97%.
- Elsewhere the gain was mostly speed, 2–12 s faster wins.
- The Ghost grunt was a control. Its top 10 did not change and no species improved. Grunts
  do not shield, so baiting buys nothing there.
- Pruning: the shipped version only tries charged pairs that keep one of the species'
  finalist charged moves. That kept 47 of the 51 improvements the experiment found, and each
  miss was worth under a point or speed only. It costs about 9.7 CPU-hours per refresh for
  the four leaders with the pause band, against 27 CPU-hours for every pair.

## Teams of 2–3

- With stat stages on, each leader's best single counter already wins 100% (Sierra 99.7%).
- Every top team wins in exactly the same time as its lead, so the second and third
  Pokémon never enter. A team ranking would only be the solo #1 plus anything.
- Cost is small. 150 ordered pairs and trios, drawn from a pool of the top 6 solo species
  plus the best specialist for each Rocket slot, screened on 1,000 shared lineups in about
  25 s. The exact finals took 10–40 s on 4 workers. The reference simulator takes 0.38 ms
  per battle with one Pokémon and 0.65 ms with three.

Engine team model, for later switch-strategy work:

- Order is fixed and the next Pokémon comes in only on a faint. There is no voluntary
  switch.
- Shields are counted per battle (two).
- Stat stages reset on switch-in.
- Your own switch pauses the Rocket for functionally 6 turns. That is a reading in the
  1vyspr1 thread (ledger k), not modelled.

A future option is a team card for players who lack the top counters: the best team when
the top N solo counters are excluded. It would need its own experiment and a rule for what
a player "has".

## Prior art

- Pokémon GO Hub's Giovanni guide leads with a best team of three with roles, then gives a
  counter table for each Rocket Pokémon.
- PvPoke's Team Builder grades a reader-entered team on Coverage, Bulk, Safety and
  Consistency.
- Most guides list counters by slot.
