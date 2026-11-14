"""Load current Rocket lineups and resolve their Pokebattler IDs."""

import sys
from dataclasses import dataclass
from urllib.parse import urlsplit

from pogo_analyzer.pokebattler import BadResponse, CacheMiss, NotFound, build_rocket_url

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
    game_master = client.get_json(PVPOKE_GM_URL)
    if not isinstance(entries, dict):
        raise BadResponse(urlsplit(EVENT_INFO_URL).netloc)
    if not isinstance(game_master, dict) or not isinstance(game_master.get("pokemon"), list):
        raise BadResponse(urlsplit(PVPOKE_GM_URL).netloc)
    species = {}
    for item in game_master["pokemon"]:
        if not isinstance(item, dict):
            continue
        name, dex = item.get("speciesId"), item.get("dex")
        if not isinstance(name, str) or type(dex) is not int:
            continue
        if "_shadow" not in name and "_mega" not in name:
            if dex not in species or len(name) < len(species[dex]):
                species[dex] = name
    characters = []
    for key, entry in entries.items():
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("active"), bool)
            or not isinstance(entry.get("grunt"), str)
            or not isinstance(entry.get("type"), str)
        ):
            print(f"Skipping malformed entry {key}", file=sys.stderr)
            continue
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
        gender = entry.get("gender")
        gender_name = "male" if gender == 1 else "female" if gender == 2 else "unknown"
        name = (
            typ
            if kind == "Executive"
            else "Giovanni"
            if kind == "Giovanni"
            else f"{typ} grunt ({gender_name})"
        )
        slots = []
        encounters = entry.get("encounters")
        if not isinstance(encounters, dict):
            encounters = {}
            print(f"Skipping malformed encounters in entry {key}", file=sys.stderr)
        for slot in ("first", "second", "third"):
            pool = []
            slot_encounters = encounters.get(slot, [])
            if not isinstance(slot_encounters, list):
                print(f"Skipping malformed encounters in {name}, {slot}", file=sys.stderr)
                slot_encounters = []
            for encounter in slot_encounters:
                if (
                    not isinstance(encounter, dict)
                    or type(encounter.get("id")) is not int
                    or ("form" in encounter and type(encounter["form"]) is not int)
                    or (
                        "template" in encounter
                        and (
                            not isinstance(encounter["template"], str) or not encounter["template"]
                        )
                    )
                ):
                    print(
                        f"Skipping malformed encounter in {name}, {slot}",
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
    cache_miss = False
    for candidate in candidates:
        try:
            response = client.get_json(build_rocket_url(candidate, tier, attacker_level, **options))
        except NotFound:
            continue
        except CacheMiss:
            cache_miss = True
            continue
        return candidate, response
    if cache_miss:
        raise CacheMiss(", ".join(candidates))
    return None
