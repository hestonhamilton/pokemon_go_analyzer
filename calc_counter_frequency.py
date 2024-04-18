#!/usr/bin/env python3
import re
from collections import Counter

def extract_pokemon_counters(file_path):
    pattern = re.compile(r"\{[^{}]*\}")  # Adjusted to match the entire dictionary-like string
    counters = []

    with open(file_path, 'r') as file:
        for line in file:
            matches = pattern.findall(line)
            counters.extend(matches)

    return counters

def count_pokemon_counters(counters):
    return Counter(counters)

def main(file_path):
    counters = extract_pokemon_counters(file_path)
    counter_counts = count_pokemon_counters(counters)

    # Display sorted by frequency
    for counter, count in counter_counts.most_common():
        print(f"{counter}: {count}")

if __name__ == "__main__":
    import sys
    file_path = sys.argv[1] if len(sys.argv) > 1 else './data/counters_overall.txt'
    main(file_path)

