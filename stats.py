#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import yaml

# Display statistics about the TASing progress

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


def color_for_progress(done, total=5, use_gradient=True):
    """
    Return a color code representing progress.
    If use_gradient=True, uses smooth red→yellow→green RGB gradient.
    If use_gradient=False, uses simple discrete colors.
    """
    if not use_gradient:
        if done == 0:
            return "\033[91m"  # Red
        elif done < total:
            return "\033[93m"  # Yellow
        else:
            return "\033[92m"  # Green

    # --- Gradient mode ---
    ratio = done / total
    # Red (255,0,0) → Yellow (255,255,0) → Green (0,255,0)
    if ratio < 0.5:
        # Red → Yellow
        r = 255
        g = int(510 * ratio)  # 0 → 255
    else:
        # Yellow → Green
        g = 255
        r = int(510 * (1 - ratio))  # 255 → 0
    return f"\033[38;2;{r};{g};0m"


def display_episode_grid(filename, score_type="Speedrun", use_gradient=True):
    """
    Display a grid of episodes (00–99), colored according to how many levels (0–4)
    have the given score_type ("Speedrun" or "Highscore").

    Args:
        filename (str): Path to the YAML file.
        score_type (str): "Speedrun" or "Highscore".
        use_gradient (bool): Whether to use RGB gradient colors.
    """
    with open(filename, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    # Each episode has 5 levels: 0–4
    episodes = {f"{i:02d}": [False]*5 for i in range(100)}

    for key, value in data.items():
        if '-' not in key:
            continue
        episode, level = key.split('-')
        if episode in episodes and level.isdigit():
            lvl = int(level)
            if 0 <= lvl < 5 and score_type in value:
                episodes[episode][lvl] = True

    print(f"Episode {score_type} Grid:\n")
    for row in range(10):
        line = []
        for col in range(10):
            ep = f"{col}{row}"
            if ep not in episodes:
                display = ep
            else:
                done = sum(episodes[ep])
                color = color_for_progress(done, total=5, use_gradient=use_gradient)
                display = f"{color}{ep}{RESET}"
            line.append(display)
        print(" ".join(line))

    print("\nLegend:")
    for i in range(6):
        color = color_for_progress(i, total=5, use_gradient=use_gradient)
        print(f"{color}{i}/5{RESET}", end=" ")
    print(f"→ levels with {score_type}")


if __name__ == "__main__":
    filename = "tas/level_data.yml"
    highscores, speedruns = count_highscores_and_speedruns(filename)
    print("Levels already TASed:")
    print(f"Highscores: {highscores}")
    print(f"Speedruns: {speedruns}")
    display_episode_grid(filename, "Highscore", use_gradient=False)
    display_episode_grid(filename, "Speedrun", use_gradient=False)
