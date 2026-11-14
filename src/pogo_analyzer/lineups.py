"""Load current Rocket lineups and resolve their Pokebattler IDs."""

import sys
from dataclasses import dataclass

from pogo_analyzer.pokebattler import NotFound, build_rocket_url

EVENT_INFO_URL = "https://raw.githubusercontent.com/WatWowMap/event-info/main/grunts/formatted.json"
PVPOKE_GM_URL = "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/gamemaster.json"


@dataclass
class Encounter:
    species: str
    candidates: list[str]


@dataclass
class Character:
    name: str
    tier: str
    slots: list[list[Encounter]]


def default_shield_strategy(slot):
    return "SHIELD_0" if slot == 3 else "SHIELD_1"


def load_lineups(client):
    entries = client.get_json(EVENT_INFO_URL)
    pokemon = client.get_json(PVPOKE_GM_URL)["pokemon"]
    species = {}
    for item in pokemon:
        name = item["speciesId"]
        dex = item["dex"]
        if "_shadow" not in name and "_mega" not in name:
            if dex not in species or len(name) < len(species[dex]):
                species[dex] = name
    characters = []
    for entry in entries.values():
        if not entry["active"]:
            continue
        kind, typ = entry["grunt"], entry["type"]
        level = (
            5
            if kind == "Giovanni"
            else 4
            if kind == "Executive"
            else (3 if typ == "Decoy" else 2 if typ == "Mixed" else 1)
        )
        name = (
            typ
            if kind == "Executive"
            else "Giovanni"
            if kind == "Giovanni"
            else (f"{typ} grunt ({ {1: 'male', 2: 'female'}.get(entry.get('gender'), 'unknown') })")
        )
        slots = []
        for slot in ("first", "second", "third"):
            pool = []
            for encounter in (entry.get("encounters") or {}).get(slot, []):
                if not isinstance(encounter, dict) or "id" not in encounter:
                    print(
                        f"Skipping malformed encounter in {name}, {slot}: missing id",
                        file=sys.stderr,
                    )
                    continue
                template = encounter.get("template")
                base = species.get(encounter["id"])
                if base is None and not template:
                    # Dex number PvPoke doesn't list yet: keep it visible, unresolvable.
                    pool.append(Encounter(f"dex_{encounter['id']}", []))
                    continue
                base_id = template or base.upper()
                candidates = [base_id, f"{base_id}_FORM"]
                pool.append(Encounter(template.lower() if template else base, candidates))
            slots.append(pool)
        characters.append(Character(name, f"RAID_LEVEL_{level}", slots))
    return characters


def resolve_defender(client, candidates, tier, attacker_level, **options):
    """Return the first candidate and response that exists, or None."""
    for candidate in candidates:
        try:
            response = client.get_json(build_rocket_url(candidate, tier, attacker_level, **options))
        except NotFound:
            continue
        return candidate, response
    return None
