#!/usr/bin/env python3
import sys
import argparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

def selenium_init():
    chrome_options = Options()
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36"
    chrome_options.add_argument(f'user-agent={user_agent}')
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    service = Service('./chromedriver-linux64/chromedriver')
    return service, chrome_options

def build_url(pokemon_name, args):
    pokemon_name = pokemon_name.upper()
    url_template = (
        f"https://www.pokebattler.com/rocket/defenders/{pokemon_name}_SHADOW_FORM"
        f"/levels/RAID_LEVEL_{args.raid_level}/attackers/levels/{args.attacker_level}"
        f"?sort={args.sort}&view=GROUPED&shieldStrategy={args.attacker_shields}"
        f"&defenderShieldStrategy={args.defender_shields}&meta=DUAL_MOVE"
    )
    return url_template

def parse_arguments():
    parser = argparse.ArgumentParser(description="Generate URLs for Pokémon battle simulations.")
    parser.add_argument("--file", help="File containing a list of Pokémon names, one per line")
    parser.add_argument("--raid-level", choices=["UNSET", "1", "2", "3", "4", "5"], default="UNSET", help="Raid level")
    parser.add_argument("--attacker-level", choices=["20", "30", "35", "40", "45", "50"], default="50", help="Attacker level")
    parser.add_argument("--sort", choices=["WIN", "OVERALL", "POWER", "TIME"], default="OVERALL", help="Sorting criteria")
    parser.add_argument("--attacker-shields", choices=["SHIELD_0", "SHIELD_1", "SHIELD_2"], default="SHIELD_2", help="Attacker shields")
    parser.add_argument("--defender-shields", choices=["SHIELD_0", "SHIELD_2"], default="SHIELD_0", help="Defender shields")
    parser.add_argument("-o", "--output", help="Output file to write results")
    return parser.parse_args()

def get_counters(url, driver):
    driver.get(url)
    WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located((By.CLASS_NAME, 'flex-grid-item')))
    pokemon_elements = driver.find_elements(By.CLASS_NAME, 'flex-grid-item')
    counters = {}
    for element in pokemon_elements:
        try:
            svg_element = element.find_element(By.TAG_NAME, 'svg')
            pokemon_name = svg_element.get_attribute('aria-label')
            moves_div = element.find_element(By.XPATH, ".//div[contains(@style, 'font-size: 11px') and contains(@style, 'line-height: 12px') and contains(@style, 'height: 48px')]")
            fast_move = moves_div.find_element(By.XPATH, "./div[1]").text
            charge_move = moves_div.find_element(By.XPATH, "./div[2]").text
        
        except NoSuchElementException:
            fast_move, charge_move = "Unknown", "Unknown"

        counters.setdefault(url, []).append({
            'name': pokemon_name,
            'fast_move': fast_move,
            'charge_move': charge_move
        })

    return counters

def read_urls_from_file(file_path):
    with open(file_path, 'r') as file:
        return [line.strip() for line in file if line.strip()]

def write_results_to_file(output_file, counters):
    with open(output_file, 'a') as file:  # Note the 'a' mode for appending
        for url, counters in counters.items():
            file.write(f"Counters for {url}:\n")
            for idx, counter in enumerate(counters, start=1):
                file.write(f"Counter #{idx}: {counter}\n")
            file.write("\n")

def main():
    args = parse_arguments()
    if args.file:
        pokemon_names = read_urls_from_file(args.file)
    else:
        print("No file provided. Using default Pokémon list.")
        pokemon_names = ['Amoonguss', 'Ampharos', 'Anorith', 'Bagon', 'Banette', 'Bastiodon', 'Beedrill', 'Bibarel', 'Blitzle', 'Cacturne', 'Chimchar', 'Cranidos', 'Crawdaunt', 'Darmanitan', 'Darumaka', 'Diglett_Alola', 'Dragonair', 'Dragonite', 'Dratini', 'Drifloon', 'Drilbur', 'Dusclops', 'Dwebble', 'Electabuzz', 'Empoleon', 'Exeggutor_Alola', 'Ferroseed', 'Ferrothorn', 'Foongus', 'Forretress', 'Froslass', 'Gabite', 'Gallade', 'Galvantula', 'Garchomp', 'Gardevoir', 'Gengar', 'Geodude_Alola', 'Gible', 'Glameow', 'Gligar', 'Golem', 'Golett', 'Gothita', 'Gothorita', 'Granbull', 'Graveler', 'Grotle', 'Gyarados', 'Hitmonchan', 'Hitmonlee', 'Hitmontop', 'Houndoom', 'Infernape', 'Joltik', 'Kirlia', 'Lairon', 'Lileep', 'Luxray', 'Machamp', 'Machop', 'Magikarp', 'Makuhita', 'Mareep', 'Marowak_Alola', 'Mawile', 'Meowth', 'Metagross', 'Metang', 'Misdreavus', 'Monferno', 'Nidorina', 'Nidorino', 'Ninetales_Alola', 'Onix', 'Pidgeot', 'Pidgey', 'Piplup', 'Prinplup', 'Purugly', 'Quagsire', 'Ralts', 'Rampardos', 'Rattata', 'Reuniclus', 'Rhyhorn', 'Salamence', 'Sandshrew_Alola', 'Sandslash_Alola', 'Scizor', 'Scyther', 'Shieldon', 'Shuckle', 'Skarmory', 'Skorupi', 'Sneasel_Hisuian', 'Snover', 'Snubbull', 'Solosis', 'Stantler', 'Staravia', 'Starly', 'Teddiursa', 'Torterra', 'Totodile', 'Toxicroak', 'Turtwig', 'Ursaring', 'Voltorb', 'Vulpix_Alola', 'Wailord', 'Weedle', 'Weezing', 'Whiscash', 'Wobbuffet', 'Wooper']
    service, chrome_options = selenium_init()
    with webdriver.Chrome(service=service, options=chrome_options) as driver:
        if args.output:
            for pokemon_name in pokemon_names:
                url = build_url(pokemon_name, args)
                print(f"Processing URL: {url}")
                counters = get_counters(url, driver)
                write_results_to_file(args.output, counters)
                print(f"Results written to {args.output}")
        else:
            for pokemon_name in pokemon_names:
                url = build_url(pokemon_name, args)
                print(f"Processing URL: {url}")
                counters = get_counters(url, driver)
                print(f"Counters for {url}:")
                for idx, counter in enumerate(counters, start=1):
                    print(f"Counter #{idx}: Name: {counter['name']} - Fast Move: {counter['fast_move']}, Charge Move: {counter['charge_move']}")

if __name__ == "__main__":
    main()
