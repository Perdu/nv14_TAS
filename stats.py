#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import yaml

# Display statistics about the TASing progress

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

def count_highscores_and_speedruns(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    highscores = 0
    speedruns = 0

    # Loop through all top-level entries (like '00-0', '00-1', etc.)
    for key, value in data.items():
        if 'Highscore' in value:
            highscores += 1
        if 'Speedrun' in value:
            speedruns += 1

    print("Speedruns done:")
    for key, value in sorted(data.items()):
        if 'Speedrun' in value:
            print(key)

#    for key, value in data.items():
#        if 'Highscore' in value:
#            print(key)

    return highscores, speedruns


def display_episode_grid(filename, score_type):
    with open(filename, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    # Collect info about which episodes have speedruns
    episodes = {f"{i:02d}": [False]*6 for i in range(100)}

    for key, value in data.items():
        # Expect keys like '00-0', '07-5', etc.
        if '-' not in key:
            continue
        episode, level = key.split('-')
        if episode in episodes and level.isdigit():
            lvl = int(level)
            if score_type in value:
                episodes[episode][lvl] = True

    # Display grid
    print("Episode Speedrun Grid:\n")
    for row in range(10):
        line = []
        for col in range(10):
            ep = f"{col}{row}"
            if ep not in episodes:
                color = RESET
                display = ep
            else:
                levels = episodes[ep]
                if all(levels):
                    color = GREEN
                elif any(levels):
                    color = YELLOW
                else:
                    color = RED
                display = f"{color}{ep}{RESET}"
            line.append(display)
        print(" ".join(line))


if __name__ == "__main__":
    filename = "tas/level_data.yml"
    highscores, speedruns = count_highscores_and_speedruns(filename)
    print("Levels already TASed:")
    print(f"Highscores: {highscores}")
    print(f"Speedruns: {speedruns}")
    display_episode_grid(filename, "Highscore")
    display_episode_grid(filename, "Speedrun")
