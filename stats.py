#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import yaml
import re

# Display statistics about the TASing progress
# Most of this file is from Chatgpt

RESET = "\033[0m"
TAS_FILE = "tas/level_data.yml"
RTA_FILE = "tas/level_data_rta.yml"

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

def parse_score(value, score_type="Speedrun"):
    """
    Parse a score value depending on type.
    - Speedrun: frames (e.g., "341 f") → return int frames
    - Highscore: seconds (e.g., "450.825") → return float seconds
    Returns None if parsing fails.
    """
    if value is None:
        return None

    s = str(value).strip().lower()

    # Use regex to find first number
    match = re.search(r"\d+(\.\d+)?", s)
    if not match:
        return None

    num_str = match.group(0)

    try:
        if score_type.lower() == "speedrun":
            return int(float(num_str))
        else:  # Highscore
            return float(num_str)
    except (ValueError, OverflowError):
        return None


def display_time_difference(score_type="Speedrun"):
    """
    Compare TAS vs RTA scores and display total difference.
    - Speedrun: display frames
    - Highscore: display seconds
    """
    with open(TAS_FILE, 'r', encoding='utf-8') as f:
        levels_data = yaml.safe_load(f)
    with open(RTA_FILE, 'r', encoding='utf-8') as f:
        rta_data = yaml.safe_load(f)

    total_tas = 0
    total_rta = 0
    results = []
    missing = []

    for key, value in levels_data.items():
        if score_type not in value:
            continue

        tas_score = parse_score(value[score_type], score_type)
        if tas_score is None:
            continue

        # Find RTA score
        rta_score = None
        if key in rta_data:
            rta_entry = rta_data[key]
            if isinstance(rta_entry, dict):
                # Try top-level 'time'
                if "time" in rta_entry and score_type.lower() != "speedrun":
                    rta_score = parse_score(rta_entry["time"], score_type)
                # Try nested score_type
                elif score_type in rta_entry and "time" in rta_entry[score_type]:
                    rta_score = parse_score(rta_entry[score_type]["time"], score_type)

        if rta_score is None:
            missing.append(key)
            continue

        diff = tas_score - rta_score
        total_tas += tas_score
        total_rta += rta_score
        results.append((key, tas_score, rta_score, diff))

    # Display
    unit = "f" if score_type.lower() == "speedrun" else "s"
    print(f"\nTime differences ({score_type}) — RTA vs TAS:\n")
    for key, tas, rta, diff in sorted(results):
        print(f"{key}: TAS={tas} {unit} \tRTA={rta} {unit}\t{diff} {unit}")

    if results:
        total_diff = total_rta - total_tas
        if score_type == "Speedrun":
            total_diff_s = total_diff * 0.025
            formatted_tas = format_seconds(total_tas * 0.025)
            formatted_rta = format_seconds(total_rta * 0.025)
            print(f"\nTotal TAS: {total_tas} {unit} ({formatted_tas})")
            print(f"Total RTA: {total_rta} {unit} ({formatted_rta})")
            print(f"Total Δ = +{total_diff} {unit}")
        else:
            formatted = format_seconds(total_diff)
            print(f"\nTotal TAS: {total_tas:.3f} {unit}")
            print(f"Total RTA: {total_rta:.3f} {unit}")
            print(f"Total Δ = +{total_diff:.3f} {unit} ({formatted})")
    else:
        print("No valid entries found.")

    if missing:
        print(f"\n⚠ Missing RTA entries for: {', '.join(missing)}")


def format_seconds(seconds: float) -> str:
    """Format a duration in seconds as HhMmS.sss format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h{minutes:02d}m{secs:06.3f}s"
    elif minutes > 0:
        return f"{minutes}m{secs:06.3f}s"
    else:
        return f"{secs:.3f}s"


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
    display_time_difference("Speedrun")
