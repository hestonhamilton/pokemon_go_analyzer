#!/usr/bin/env python3

pokemon_names = [
    "Gothita", "Solosis", "Wobbuffet", "Gothorita", "Ralts", "Gallade", "Metagross", "Reuniclus",
    "Pidgey", "Starly", "Gligar", "Staravia", "Pidgeot", "Dragonite", "Skarmory",
    "Mawile", "Ralts", "Vulpix_Alola", "Kirlia", "Snubbull", "Granbull", "Ninetales_Alola", "Gardevoir",
    "Sneasel_Hisuian", "Foongus", "Nidorina", "Nidorino", "Toxicroak", "Weezing", "Amoonguss",
    "Snover", "Turtwig", "Grotle", "Ferrothorn", "Cacturne", "Amoonguss", "Torterra",
    "Darumaka", "Chimchar", "Houndoom", "Monferno", "Darmanitan", "Infernape",
    "Mareep", "Blitzle", "Joltik", "Geodude_Alola", "Voltorb", "Electabuzz", "Galvantula", "Ampharos", "Luxray",
    "Scyther", "Shuckle", "Dwebble", "Weedle", "Skorupi", "Scizor", "Forretress", "Beedrill",
    "Misdreavus", "Drifloon", "Golett", "Dusclops", "Banette", "Froslass", "Gengar", "Marowak_Alola",
    "Cranidos", "Shieldon", "Onix", "Lileep", "Anorith", "Graveler", "Golem", "Rampardos", "Bastiodon",
    "Glameow", "Teddiursa", "Stantler", "Rattata", "Meowth", "Purugly", "Ursaring", "Bibarel",
    "Bagon", "Gible", "Dratini", "Dragonair", "Gabite", "Exeggutor_Alola", "Salamence", "Dragonite", "Garchomp",
    "Piplup", "Totodile", "Crawdaunt", "Prinplup", "Whiscash", "Wailord", "Empoleon", "Magikarp", "Gyarados",
    "Makuhita", "Machop", "Hitmontop", "Hitmonlee", "Hitmonchan", "Machamp", "Toxicroak", "Infernape",
    "Diglett_Alola", "Wooper", "Drilbur", "Rhyhorn", "Whiscash", "Quagsire", "Torterra",
    "Ferroseed", "Skarmory", "Sandshrew_Alola", "Lairon", "Metang", "Sandslash_Alola", "Scizor"
]
pokemon_names.sort()
print(list(dict.fromkeys(pokemon_names)))
