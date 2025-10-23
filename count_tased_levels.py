#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import yaml

# Counts the number of levels already TASed

def count_highscores_and_speedruns(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    highscores = 0
    speedruns = 0

    # Loop through all top-level entries (like '00-0', '00-1', etc.)
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        if 'Highscore' in value:
            highscores += 1
        if 'Speedrun' in value:
            speedruns += 1

    return highscores, speedruns


if __name__ == "__main__":
    filename = "tas/level_data.yml"
    highscores, speedruns = count_highscores_and_speedruns(filename)
    print("Levels already TASed:")
    print(f"Highscores: {highscores}")
    print(f"Speedruns: {speedruns}")
