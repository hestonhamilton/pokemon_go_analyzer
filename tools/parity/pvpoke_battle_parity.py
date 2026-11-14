"""Run pinned PvPoke Battle.js under Node, with injected decisions, not its AI.

Tool only. First run downloads immutable MIT sources; tests never need the cache
or network. Existing cache files are read only, including on repeated runs.
Run: uv run python tools/parity/pvpoke_battle_parity.py
"""

import hashlib
import json
import random
import subprocess
import tempfile
import urllib.request
from dataclasses import asdict
from pathlib import Path

from pogo_analyzer.sim.battle import ChargedWhenReady, Combatant, FastOnly, simulate
from pogo_analyzer.sim.calculator import BattlePredictor, Move
from pogo_analyzer.sim.stats import player_stats

SHA = "426e5e9f39d3a027849698fb2f5edd9df6056cbf"
SOURCE = Path(".cache/fixture-sources") / f"pvpoke-{SHA}"
# SHA-256 of each pinned file, checked on fetch and on every run (cached or not).
CHECKSUMS = {
    "src/js/battle/Battle.js": "65765dc0214710f6587b4e5d5a07a7bf8d2639090be6a5a59270650d6d5225b4",
    "src/js/battle/DamageCalculator.js": (
        "557b9345367a272e7822b47d346b67ae05d4124050e9d3876fb2446246915f31"
    ),
    "src/js/battle/actions/ActionLogic.js": (
        "9a5a7bb28a01c115e18e5b904646f5fb18bf1b17c2bf8757d2d90144ef7d0e30"
    ),
    "src/js/battle/timeline/TimelineAction.js": (
        "00b77e8e046b74d52d8c385a29ea529bbedfbea0edd7ff64cf49719d2e97cba2"
    ),
    "src/js/battle/timeline/TimelineEvent.js": (
        "a7793ddbc398769cfb6d8a0f539aa96f597eac3127f5cb594cf94eab7bf70f37"
    ),
    "src/js/pokemon/Player.js": "6b2873ebf6dce8b1beae9f213f02b6cd8878a6cbb9b928b29e89653cb0c42199",
    "src/js/pokemon/Pokemon.js": "a3646035edfe30e8136e8121ed3981aec2bcf094dca582354234b79eca34321e",
    "src/data/gamemaster.json": "dff1f13b501c853ec57139cd23c6979b21f671672baa9a9b3085dc1e5377bd52",
    "LICENSE": "3c8500ea8ad3bc42dbaccaf2e0ebfb2950b7db69b3ed56b80d5805dd02078924",
}
FILES = tuple(CHECKSUMS)

ORACLE = r"""
const fs = require('fs'), vm = require('vm');
const base = process.argv[2], input = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const read = name => fs.readFileSync(base + '/' + name, 'utf8');
const gm = {data:JSON.parse(read('src/data/gamemaster.json'))};
const pokemon = read('src/js/pokemon/Pokemon.js');
function method(name) {
 const start = pokemon.indexOf('this.' + name + ' = function');
 if (start < 0) throw new Error('Missing Pokemon method: ' + name);
 const end = pokemon.indexOf('\n\t}', start) + 3;
 return pokemon.slice(start, end);
}
// A stat/move adapter: no species initialization, CP selection, forms or move AI.
// Stat methods, reset and native-buff application are the actual Pokemon.js code.
const wrap = `function P(c, index) {
 const self = this;
 self.stats = {atk:c.attack,def:c.defence,hp:c.hp};
 self.types = c.types; self.index = index; self.speciesId = 'ordinary_' + index;
 self.shadowType = index === 1 || c.shadow ? 'shadow' : 'normal';
 self.shadowAtkMult = DamageMultiplier.SHADOW_ATK;
 self.shadowDefMult = DamageMultiplier.SHADOW_DEF;
 self.startHp = c.hp; self.startEnergy = c.energy; self.startCooldown = 0;
 self.startingShields = 0; self.startStatBuffs = [0,0]; self.nativeStatBuffs = [0,0];
 self.priority = 0; self.hasTag = () => false; self.setBattle = () => {};
 self.resetMoves = () => {}; // Supplied ordinary moves already initialized below.
 ${['getEffectiveStat','getStatBuffMultiplier','getStab','applyStatBuffs','reset'].map(method).join('\n')}
 function move(m) {
  const out = {...m,moveId:m.id,name:m.id,cooldown:m.turns*500,
               energyGain:m.energy_gain,category:m.energy ? 'charged' : 'fast',
               hasTag:() => false};
  out.stab = self.getStab(out); return out;
 }
 self.fastMove = move(c.fast); self.chargedMoves = c.charged.map(move);
 self.extraChargedMovePool = []; self.turns = c.fast.turns;
 self.typeEffectiveness = Object.fromEntries([...new Set(gm.data.moves.map(m => m.type))].map(
  t => [t,DamageCalculator.getEffectiveness(t,c.types)]));
}`;
// Load the entire pinned Battle.js. The sole source insertion is a passive
// observation callback at queue submission (382); no timing or validation edits.
let battleSource = read('src/js/battle/Battle.js');
const marker = 'queuedActions.push(action);';
if (battleSource.split(marker).length !== 2) throw new Error('Queue observer marker changed');
battleSource = battleSource.replace(marker,
 marker + ' if(self.observeQueue) self.observeQueue(action);');
const ctx = {gm,GameMaster:{getInstance:() => gm}, console};
vm.createContext(ctx);
vm.runInContext([
 read('src/js/battle/DamageCalculator.js'),
 read('src/js/battle/timeline/TimelineAction.js'),
 read('src/js/battle/timeline/TimelineEvent.js'),
 read('src/js/battle/actions/ActionLogic.js'), battleSource, wrap,
 'this.B = Battle; this.P = P; this.TA = TimelineAction; this.AL = ActionLogic;'
].join('\n'),ctx);
const output = input.map(c => {
 const battle = new ctx.B();
 const pokes = c.sides.map((p,i) => new ctx.P(p,i));
 pokes.forEach((p,i) => battle.setNewPokemon(p,i,false));
 // The ONLY replaced PvPoke behavior: external decisions, as in Python.
 ctx.AL.decideAction = (b,p,o) => {
  if (c.policy === 'fast_only') return null;
  const i = p.chargedMoves.findIndex(m => p.energy >= m.energy);
  return i < 0 ? null : new ctx.TA('charged',p.index,b.getTurns(),i,
                  {priority:0,shielded:false,buffs:false,charge:1});
 };
 const moveOf = a => a.type === 'fast' ? pokes[a.actor].fastMove :
                    pokes[a.actor].chargedMoves[a.value];
 let row;
 battle.observeQueue = a => row.actions[a.actor].push(a.type + ':start:' + moveOf(a).moveId);
 const process = battle.processAction;
 battle.processAction = (a,p,o) => {
  if (!a.valid) row.actions[a.actor].push(a.type + ':cancel:' + moveOf(a).moveId);
  return process(a,p,o);
 };
 const use = battle.useMove;
 battle.useMove = (p,o,m,...args) => {
  const out = use(p,o,m,...args);
  row.actions[p.index].push(m.category + ':hit:' + m.moveId);
  row.damage[p.index] += m.damage;
  return out;
 };
 battle.start();
 const rows = [];
 while (pokes.every(p => p.hp > 0) && rows.length < c.max_turns) {
  row = {number:battle.getTurns(),actions:[[],[]],damage:[0,0]};
  battle.step();
  row.hp = pokes.map(p => p.hp); row.energy = pokes.map(p => p.energy);
  rows.push(row);
 }
 return rows;
});
console.log(JSON.stringify(output));
"""


# Native emulator, not a sequence of restarted 1v1s. Replace browser timers with
# a deterministic clock; all phase transitions, switches and shield consumption
# execute the pinned sources. Only attack/switch/shield decisions are injected.
TEAM_ORACLE = (
    ORACLE.split("const output = input.map(c => {")[0]
    .replace(
        "'getStab','applyStatBuffs','reset'",
        "'getStab','applyStatBuffs','reset','fullReset','resetBattleStats'",
    )
    .replace(
        "const ctx = {gm,GameMaster:{getInstance:() => gm}, console};",
        r"""
let now = 0, serial = 0, jobs = new Map();
function schedule(fn, delay, repeat) {
 const id = ++serial; jobs.set(id,{fn,at:now+delay,repeat}); return id;
}
function tick() {
 const pair = [...jobs].sort((a,b) => a[1].at-b[1].at || a[0]-b[0])[0];
 if (!pair) throw new Error('emulator has no pending callback');
 const [id,j] = pair; now=j.at;
 if (j.repeat) j.at+=j.repeat; else jobs.delete(id);
 j.fn();
}
const ctx = {gm,GameMaster:{getInstance:() => gm},console:{log:() => {}},
 setTimeout:(fn,ms) => schedule(fn,ms,0),clearTimeout:id => jobs.delete(id),
 setInterval:(fn,ms) => schedule(fn,ms,ms),clearInterval:id => jobs.delete(id)};
""",
    )
    .replace(
        "read('src/js/battle/DamageCalculator.js'),",
        "read('src/js/pokemon/Player.js'),read('src/js/battle/DamageCalculator.js'),",
    )
    .replace("self.startingShields = 0", "self.startingShields = 2")
    .replace("this.B = Battle;", "this.PL = Player; this.B = Battle;")
    + r"""
const output = input.map(c => {
 jobs.clear(); now=0;
 const battle = new ctx.B();
 const teams = c.teams.map((team,i) => team.map(p => new ctx.P(p,i)));
 const players = teams.map((team,i) => {
  const player = new ctx.PL(i,false,battle);
  player.setPriority(0); player.setTeam(team);
  player.ai = {
   evaluateMatchup:() => {},hasStrategy:() => false,
   decideSwitch:() => team.findIndex(p => p.hp>0),
   decideShield:() => c.shields[i],
   decideAction:(turn,p,o) => {
    if(c.policy[i] === 'fast_only') return null;
    const m = p.chargedMoves.findIndex(m => p.energy >= m.energy);
    return m<0 ? null : new ctx.TA('charged',i,turn,m,
                    {priority:0,shielded:false,buffs:false,charge:1});
   }
  };
  return player;
 });
 battle.setPlayers(players);
 const activations = [[],[]], charges=[[],[]];
 const set = battle.setNewPokemon;
 battle.setNewPokemon = (p,i,initialize) => {
  set(p,i,initialize);
  activations[i].push({slot:teams[i].indexOf(p)+1,shields:players[i].getShields()});
 };
 teams.forEach((team,i) => battle.setNewPokemon(team[0],i,false));
 const use = battle.useMove;
 battle.useMove = (p,o,m,...args) => {
  const hp=o.hp, shields=players[o.index].getShields();
  const out=use(p,o,m,...args);
  if(m.category==='charged') charges[p.index].push({
   shielded:players[o.index].getShields()<shields,damage:hp-o.hp});
  return out;
 };
 let finished=false;
 battle.emulate(data => {
  if(data.phase==='suspend_charged') battle.setChargeAmount(1);
  if(data.phase==='suspend_switch') battle.forceSwitch();
  if(data.phase==='game_over') finished=true;
 });
 let steps=0;
 while(!finished && steps++ < 100000) tick();
 if(!finished) throw new Error('emulator callback limit: '+c.name);
 // This projection checks components, not emulator wall time or turn parity.
 return {activations,charges:charges.map(cs=>cs.slice(0,3)),
         shields:players.map(p=>p.getShields())};
});
console.log(JSON.stringify(output));
"""
)


def fetch_sources():
    for name in FILES:
        path = SOURCE / name
        if path.exists():
            continue
        request = urllib.request.Request(
            f"https://raw.githubusercontent.com/pvpoke/pvpoke/{SHA}/{name}",
            headers={"User-Agent": "pokemon_go_analyzer-parity"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also protects a concurrently copied cache entry.
        try:
            with path.open("xb") as stream:
                stream.write(data)
        except FileExistsError:
            pass
    for name, expected in CHECKSUMS.items():
        digest = hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
        if digest != expected:
            raise SystemExit(f"checksum mismatch for pinned {name}: {digest}")


def fixture_sides(row, table, rocket_fast=None):
    """Exact dated fixture inputs. Unknown Rocket fast move must be explicit."""
    root = Path("tests/fixtures/sim")
    species = json.loads((root / "species_moves.json").read_text())["species"]
    predictor = BattlePredictor(species, json.loads((root / "move_history.json").read_text()))
    p, r = row["player"], row["rocket"]
    ps = player_stats(species[p["species"]]["baseStats"], p["ivs"], p["level"], form=p["form"])
    rs = predictor.rocket(row, table)
    return (
        Combatant(
            ps.attack,
            ps.defence,
            ps.hp,
            tuple(species[p["species"]]["types"]),
            predictor.move(p["fast_move"], row["battle_date"]),
            shadow=p["form"] == "shadow",
        ),
        Combatant(
            rs.attack,
            rs.defence,
            rs.hp,
            tuple(species[r["species"]]["types"]),
            predictor.move(rocket_fast or r["fast_move"], row["battle_date"]),
        ),
    )


def build_cases():
    rng = random.Random(426)
    cases = []

    def add(name, sides, policy="fast_only", max_turns=2000):
        cases.append(
            dict(name=name, sides=[asdict(s) for s in sides], policy=policy, max_turns=max_turns)
        )

    for policy in ("fast_only", "charged_when_ready"):
        for a_turns in range(1, 6):
            for b_turns in range(1, 6):
                for n in range(10):
                    sides = []
                    for side, duration in enumerate((a_turns, b_turns)):
                        fast = Move(
                            "FAST",
                            rng.choice(("normal", "steel", "dark")),
                            rng.randint(0, 15),
                            duration,
                            energy_gain=rng.randint(1, 40),
                        )
                        charged = (
                            Move("C0", "normal", rng.randint(1, 150), 1, energy=45),
                            Move("C1", "dark", rng.randint(1, 100), 1, energy=30),
                        )
                        sides.append(
                            Combatant(
                                rng.choice((100, 101, 150)),
                                rng.uniform(60, 200),
                                rng.randint(1, 300),
                                ("steel", "none"),
                                fast,
                                charged,
                                # Player only: the Rocket side is shadow by rule.
                                shadow=rng.choice((False, True)) and side == 0,
                                energy=rng.choice((0, 29, 95, 100)),
                            )
                        )
                    add(f"seed-{policy}-{a_turns}-{b_turns}-{n}", sides, policy)
    # Named adversarial cases ensure coverage independent of the random sample.
    for atk in (100, 101):
        for hp in (1, 1000):
            fast = Move("F", "normal", 1, 1, energy_gain=40)
            charged = (Move("C", "normal", 100, 1, energy=30),)
            sides = (
                Combatant(atk, 100, hp, ("normal",), fast, charged, energy=100),
                Combatant(100, 100, hp, ("normal",), fast, charged, energy=100),
            )
            add(f"CMP-{atk}-{hp}", sides, "charged_when_ready")
            add(f"overflow-or-double-KO-{atk}-{hp}", sides)
    # Both complete old tables; F1 observes exactly seven Bullet Punches (turn 14).
    rows = json.loads(Path("tests/fixtures/sim/battles.json").read_text())
    for table in ("venonic-2023", "fugerappi-2023"):
        for row in rows:
            if row["id"] == "F3-metagross-remaining":
                add(f"F3-{table}", fixture_sides(row, table))
            if row["id"] == "F1-snubbull-remaining":
                for move in ("TACKLE", "BITE"):
                    add(f"F1-{table}-{move}", fixture_sides(row, table, move), max_turns=14)
    return cases


def python_result(case):
    sides = []
    for side in case["sides"]:
        side = dict(side)
        side["fast"] = Move(**side["fast"])
        side["charged"] = tuple(Move(**m) for m in side["charged"])
        sides.append(Combatant(**side))
    policy = FastOnly if case["policy"] == "fast_only" else ChargedWhenReady
    return simulate(
        *sides, player_policy=policy(), rocket_policy=policy(), max_turns=case["max_turns"]
    )


def team_cases():
    """Three native 3v3s exercise each side's replacements and shared shields."""
    from pogo_analyzer.sim.rocket import RocketRules, simulate_rocket

    cases, expected = [], []
    fast = Move("F", "normal", 0, 1, energy_gain=20)
    charged = (Move("C", "normal", 20, 1, energy=20),)
    for name, player_hp, rocket_hp, policies in (
        ("player-sweep", 1000, 30, ("charged_when_ready", "fast_only")),
        ("rocket-sweep", 30, 1000, ("fast_only", "charged_when_ready")),
        ("both-replace", 120, 120, ("charged_when_ready", "charged_when_ready")),
    ):
        teams = tuple(
            tuple(Combatant(100, 100, hp, ("normal",), fast, charged) for _ in range(3))
            for hp in (player_hp, rocket_hp)
        )
        rules = RocketRules(
            pauses=False,
            timer=False,
            # Native PvPoke comparison: no 9db era rows.
            era_turn_rules=False,
            rocket_charged="never" if policies[1] == "fast_only" else "when_ready",
        )
        result = simulate_rocket(
            *teams,
            battle_date=None,
            rank="leader",
            rules=rules,
            player_policy=FastOnly() if policies[0] == "fast_only" else ChargedWhenReady(),
        )
        activations = [[dict(slot=1, shields=2)], [dict(slot=1, shields=2)]]
        charges = [[], []]
        previous_shields = (2, 2)
        previous_hp = tuple(team[0].hp for team in teams)
        for row in result.timeline:
            for side in range(2):
                if any(a.startswith("charged:hit:") for a in row.core.actions[side]):
                    charges[side].append(
                        dict(
                            shielded=row.shields[1 - side] < previous_shields[1 - side],
                            damage=min(
                                row.core.damage[side],
                                # Only charged damage is delivered by its actor on this turn.
                                previous_hp[1 - side],
                            ),
                        )
                    )
                if row.replacements[side] is not None:
                    activations[side].append(
                        dict(slot=row.replacements[side], shields=row.shields[side])
                    )
            previous_shields = row.shields
            previous_hp = tuple(
                teams[i][row.replacements[i] - 1].hp if row.replacements[i] else row.core.hp[i]
                for i in range(2)
            )
        expected.append(
            dict(
                activations=activations,
                charges=[cs[:3] for cs in charges],
                shields=list(result.shields),
            )
        )
        cases.append(
            dict(
                name=name,
                teams=[[asdict(p) for p in team] for team in teams],
                policy=policies,
                shields=[True, True],
            )
        )
    return cases, expected


def run_oracle(source, cases):
    with tempfile.TemporaryDirectory(prefix="pvpoke-battle-") as temporary:
        root = Path(temporary)
        oracle, payload = root / "oracle.js", root / "input.json"
        oracle.write_text(source)
        payload.write_text(json.dumps(cases))
        run = subprocess.run(
            ["node", str(oracle), str(SOURCE), str(payload)],
            check=False,
            text=True,
            capture_output=True,
        )
        if run.returncode:
            raise SystemExit(run.stderr)
        return json.loads(run.stdout)


def team_parity():
    cases, expected = team_cases()
    actual = run_oracle(TEAM_ORACLE, cases)
    mismatches = [
        (case["name"], want, got)
        for case, want, got in zip(cases, expected, actual, strict=True)
        if want != got
    ]
    print(
        f"Battle.js 3v3 component parity: {len(cases)} cases; {len(mismatches)} mismatches "
        "(activation order, per-side shields, first three charged hit/shield outcomes)"
    )
    for mismatch in mismatches:
        print(json.dumps(mismatch))
    return mismatches


def main():
    fetch_sources()
    cases = build_cases()
    # Never overwrite existing .cache entries, even the oracle/payload on reruns.
    with tempfile.TemporaryDirectory(prefix="pvpoke-battle-") as temporary:
        root = Path(temporary)
        oracle, payload = root / "oracle.js", root / "input.json"
        oracle.write_text(ORACLE)
        payload.write_text(json.dumps(cases))
        run = subprocess.run(
            ["node", str(oracle), str(SOURCE), str(payload)],
            check=False,
            text=True,
            capture_output=True,
        )
        if run.returncode:
            raise SystemExit(run.stderr)
    actual = json.loads(run.stdout)
    count = 0
    mismatches = []
    for case, got in zip(cases, actual, strict=True):
        expected = json.loads(json.dumps([asdict(t) for t in python_result(case).timeline]))
        count += len(expected)
        if got != expected:
            first = next(
                (
                    i
                    for i, pair in enumerate(zip(expected, got, strict=False))
                    if pair[0] != pair[1]
                ),
                min(len(expected), len(got)),
            )
            mismatches.append(
                (case["name"], first + 1, expected[first : first + 1], got[first : first + 1])
            )
    print(
        f"Battle.js parity: {len(cases)} cases; {count} turns; "
        f"{len(mismatches)} mismatches (HP, energy, actions, damage)"
    )
    for mismatch in mismatches:
        print(json.dumps(mismatch))
    team_mismatches = team_parity()
    if mismatches or team_mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
