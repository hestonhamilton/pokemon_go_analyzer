"""Check damage.py against PvPoke's own JavaScript at the pinned commit.

A verification aid, not a test dependency. Needs Node.js and network access the
first time: it fetches three pinned PvPoke files (MIT) into
.cache/fixture-sources/pvpoke-<sha>/. Run from the repository root:

    uv run python tools/parity/pvpoke_damage_parity.py

It compares raw (pre-floor) damage and final damage exactly for seeded
cases across every attack/defence stage, shadow flag and Mega level, and the
type effectiveness of all 6,156 move/dual-type combinations.
"""

import json
import random
import subprocess
import urllib.request
from pathlib import Path

from pogo_analyzer.sim.damage import _types, calculate_damage, effectiveness

SHA = "426e5e9f39d3a027849698fb2f5edd9df6056cbf"
FILES = (
    "src/js/battle/DamageCalculator.js",
    "src/js/pokemon/Pokemon.js",
    "src/data/gamemaster.json",
)
ROOT = Path(".cache/fixture-sources")
SOURCE = ROOT / f"pvpoke-{SHA}"
HEADERS = {"User-Agent": "pokemon_go_analyzer-parity"}

# Loads the pinned DamageCalculator.js and the three Pokemon.js methods it relies
# on, records the value passed to Math.floor (the raw damage), and prints results.
ORACLE = r"""
const fs = require('fs'), vm = require('vm');
const base = process.argv[2];
const input = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const calc = fs.readFileSync(base + '/src/js/battle/DamageCalculator.js', 'utf8');
const pokemon = fs.readFileSync(base + '/src/js/pokemon/Pokemon.js', 'utf8');
const gm = JSON.parse(fs.readFileSync(base + '/src/data/gamemaster.json', 'utf8'));
function method(name) {
 const start = pokemon.indexOf('this.' + name + ' = function');
 const end = pokemon.indexOf('\n\t}', start) + 3;
 return pokemon.slice(start, end);
}
const wrap = `function P(stats, buffs, shadow, mega, megaLevel, types) {
 const self = this;
 self.stats = stats; self.statBuffs = buffs; self.shadowType = shadow ? 'shadow' : 'normal';
 self.shadowAtkMult = DamageMultiplier.SHADOW_ATK;
 self.shadowDefMult = DamageMultiplier.SHADOW_DEF;
 self.megaLevel = megaLevel; self.types = types; self.hasTag = () => mega;
 ${method('getEffectiveStat')}
 ${method('getStatBuffMultiplier')}
 ${method('getStab')}
}`;
let raw;
const math = Object.create(Math);
math.floor = x => { raw = x; return Math.floor(x); };
const ctx = {Math:math, gm:{data:gm}, input};
vm.createContext(ctx);
vm.runInContext(calc + '\n' + wrap + '\nthis.DC = DamageCalculator; this.P = P;', ctx);
const results = input.cases.map(c => {
 const [power, atk, def, type, aTypes, dTypes] = c.args, o = c.options;
 const a = new ctx.P({atk}, [o.attack_stage,0], o.attacker_shadow,
                     o.attacker_mega, o.mega_level, aTypes);
 const d = new ctx.P({def}, [0,o.defence_stage], o.defender_shadow, false, 3, dTypes);
 d.typeEffectiveness = {[type]:ctx.DC.getEffectiveness(type,dTypes)};
 const move = {power,type,isMegaMove:o.is_mega_move}; move.stab = a.getStab(move);
 const damage = ctx.DC.damage(a,d,move);
 return {damage,raw};
});
const types = input.type_cases.map(c => ctx.DC.getEffectiveness(...c));
console.log(JSON.stringify({results, types}));
"""


def fetch_sources():
    for name in FILES:
        path = SOURCE / name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/pvpoke/pvpoke/{SHA}/{name}"
        request = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=90) as response:
            path.write_bytes(response.read())


def build_cases():
    rng = random.Random(426)
    types = list(_types())
    cases = []
    for attack_stage in range(-4, 5):
        for defence_stage in range(-4, 5):
            for attacker_shadow in (False, True):
                for defender_shadow in (False, True):
                    for mega_level in range(1, 5):
                        options = dict(
                            attacker_shadow=attacker_shadow,
                            defender_shadow=defender_shadow,
                            attack_stage=attack_stage,
                            defence_stage=defence_stage,
                            attacker_mega=True,
                            is_mega_move=True,
                            mega_level=mega_level,
                        )
                        args = [
                            rng.randint(0, 200),
                            rng.uniform(10, 600),
                            rng.uniform(10, 600),
                            rng.choice(types),
                            rng.sample(types, 2),
                            rng.sample(types, 2),
                        ]
                        result = calculate_damage(*args, **options)
                        cases.append(
                            dict(args=args, options=options, raw=result.raw, damage=result.damage)
                        )
    # Mega off: every flag combination where the Mega bonus must not apply.
    for attacker_mega, is_mega_move in ((False, False), (True, False), (False, True)):
        for mega_level in range(1, 5):
            for _ in range(8):
                options = dict(
                    attacker_shadow=rng.random() < 0.5,
                    defender_shadow=rng.random() < 0.5,
                    attack_stage=rng.randint(-4, 4),
                    defence_stage=rng.randint(-4, 4),
                    attacker_mega=attacker_mega,
                    is_mega_move=is_mega_move,
                    mega_level=mega_level,
                )
                args = [
                    rng.randint(0, 200),
                    rng.uniform(10, 600),
                    rng.uniform(10, 600),
                    rng.choice(types),
                    rng.sample(types, 2),
                    rng.sample(types, 2),
                ]
                result = calculate_damage(*args, **options)
                cases.append(dict(args=args, options=options, raw=result.raw, damage=result.damage))
    # Extreme stats: tiny and huge attack/defence ratios, power 0 and 1000.
    for power in (0, 1, 1000):
        for attack in (0.01, 1, 5000, 1e6):
            for defence in (0.01, 1, 5000, 1e6):
                options = dict(
                    attacker_shadow=True,
                    defender_shadow=True,
                    attack_stage=4,
                    defence_stage=-4,
                    attacker_mega=False,
                    is_mega_move=False,
                    mega_level=1,
                )
                args = [power, attack, defence, "water", ["water", "none"], ["fire", "rock"]]
                result = calculate_damage(*args, **options)
                cases.append(dict(args=args, options=options, raw=result.raw, damage=result.damage))
    type_cases = [[m, [t1, t2]] for m in types for t1 in types for t2 in [*types, "none"]]
    return cases, type_cases


def main():
    fetch_sources()
    cases, type_cases = build_cases()
    oracle = ROOT / "pvpoke-damage-parity.js"
    payload = ROOT / "pvpoke-damage-parity-input.json"
    oracle.write_text(ORACLE)
    payload.write_text(json.dumps(dict(cases=cases, type_cases=type_cases)))
    run = subprocess.run(
        ["node", str(oracle), str(SOURCE), str(payload)],
        check=True,
        text=True,
        capture_output=True,
    )
    actual = json.loads(run.stdout)
    for index, (case, got) in enumerate(zip(cases, actual["results"], strict=True)):
        assert got == {"raw": case["raw"], "damage": case["damage"]}, (index, case, got)
    for (move, defenders), got in zip(type_cases, actual["types"], strict=True):
        assert effectiveness(move, defenders) == got, (move, defenders, got)
    print(
        f"Exact raw/damage parity: {len(cases)} cases; type parity: {len(type_cases)} combinations"
    )


if __name__ == "__main__":
    main()
