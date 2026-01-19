#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
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

#    print("Speedruns done:")
#    for key, value in sorted(data.items()):
#        if 'Speedrun' in value:
#            print(key)

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

# AI-generated
def display_time_difference(score_type="Speedrun", sort=True, use_color=True):
    """
    Compare TAS vs RTA scores and display total difference with bar charts.
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
        
        diff = rta_score - tas_score  # Positive = RTA is slower
        perc_diff =  ((rta_score - tas_score)/rta_score) * 100
        total_tas += tas_score
        total_rta += rta_score
        results.append((key, tas_score, rta_score, diff, perc_diff))
    
    if not results:
        print("No valid entries found.")
        if missing:
            print(f"\n⚠ Missing RTA entries for: {', '.join(missing)}")
        return
    
    # Helper function to create colored bar chart
    def create_bar(value, max_value, width=40, use_color_gradient=False, use_color=True):
        """Create a colored horizontal bar based on value magnitude"""
        # Color codes (ANSI)
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        ORANGE = '\033[38;5;208m'
        RED = '\033[91m'
        RESET = '\033[0m'
        
        # Determine color based on value thresholds
        abs_val = abs(value)
        if use_color_gradient:
            if abs_val < max_value * 0.25:
                color = GREEN
            elif abs_val < max_value * 0.5:
                color = YELLOW
            elif abs_val < max_value * 0.75:
                color = ORANGE
            else:
                color = RED
        else:
            if value > 0:
                color = GREEN
            else:
                color = RED

        # Calculate bar length
        bar_length = int((abs_val / max_value) * width) if max_value > 0 else 0
        bar_length = min(bar_length, width)
        
        bar = '█' * bar_length
        if use_color:
            return f"{color}{bar}{RESET}"
        else:
            return f"{bar}"
    
    # Display with bar charts
    unit = "f" if score_type.lower() == "speedrun" else "s"
    if sort:
        sort_type_text = "time saved over 0th"
    else:
        sort_type_text = "level"
    print(f"\nTime differences ({score_type}) — RTA vs TAS (sorted by {sort_type_text}):\n")

    # Find max difference for scaling bars
    max_diff = max(abs(diff) for _, _, _, diff, _ in results)
    
    # Find max widths for alignment
    max_key_len = max(len(key) for key, _, _, _, _ in results)
    if score_type.lower() == "speedrun":
        max_tas_len = max(len(str(int(tas))) for _, tas, _, _, _ in results)
        max_rta_len = max(len(str(int(rta))) for _, _, rta, _, _ in results)
        max_diff_len = max(len(str(int(abs(diff)))) for _, _, _, diff, _ in results)
        perc_diff_len = max(len(f"{abs(perc_diff):.2f}") for _, _, _, _, perc_diff in results)
    else:
        max_tas_len = max(len(f"{tas:.3f}") for _, tas, _, _, _ in results)
        max_rta_len = max(len(f"{rta:.3f}") for _, _, rta, _, _ in results)
        max_diff_len = max(len(f"{abs(diff):.3f}") for _, _, _, diff, _ in results)
    
    if sort:
        levels = sorted(results, key=lambda x: x[3], reverse=True)
    else:
        levels = results
    
    for key, tas, rta, diff, perc_diff in levels:
        bar = create_bar(diff, max_diff, use_color=use_color)
        
        # Format with fixed widths
        if score_type.lower() == "speedrun":
            diff_s = 0.025 * diff
            original_line = f"{key:<{max_key_len}}: TAS={tas:>{max_tas_len}} {unit}  RTA={rta:>{max_rta_len}} {unit}  {-diff:>{max_diff_len+1}} {unit} ({diff_s:.3f}) (-{perc_diff:>{perc_diff_len}.2f}%)"
        else:
            original_line = f"{key:<{max_key_len}}: TAS={tas:>{max_tas_len}.3f} {unit}  RTA={rta:>{max_rta_len}.3f} {unit}  {diff:>+{max_diff_len+1}.3f} {unit}"
        
        print(f"{original_line} {bar}")
    
    # Display totals
    if results:
        total_diff = total_rta - total_tas
        print("\n" + "─" * 60)
        
        if score_type == "Speedrun":
            total_diff_s = total_diff * 0.025
            formatted_diff = format_seconds(total_diff_s)
            formatted_tas = format_seconds(total_tas * 0.025)
            formatted_rta = format_seconds(total_rta * 0.025)
            print(f"Total TAS: {total_tas} {unit} ({formatted_tas})")
            print(f"Total RTA: {total_rta} {unit} ({formatted_rta})")
            print(f"Total Δ   = +{total_diff} {unit} ({formatted_diff})")
        else:
            formatted = format_seconds(total_diff)
            print(f"Total TAS: {total_tas:.3f} {unit}")
            print(f"Total RTA: {total_rta:.3f} {unit}")
            print(f"Total Δ   = +{total_diff:.3f} {unit} ({formatted})")
    
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


def emoji_for_progress(done, total=5, use_gradient=True):
    """
    Return an emoji representing progress.

    If use_gradient=True, maps progress smoothly from red → yellow → green emojis.
    If use_gradient=False, uses simple discrete emojis.
    """

    # Clamp values to avoid edge cases
    done = max(0, min(done, total))

    if not use_gradient:
        if done == 0:
            return "🔴"   # Red
        elif done < total:
            return "🟡"   # Yellow
        else:
            return "🟢"   # Green

    # --- Gradient mode ---
    ratio = done / total if total else 1

    # Ordered from "bad" → "good"
    gradient = [
        "🔴",  # 0%
        "🟥",
        "🟧",
        "🟨",
        "🟩",
        "🟢",  # 100%
    ]

    index = int(ratio * (len(gradient) - 1))
    return gradient[index]


def display_episode_grid(filename, score_type="Speedrun", use_gradient=True, github=False):
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
                if github:
                    emoji = emoji_for_progress(done, total=5, use_gradient=use_gradient)
                    display = f"{emoji}{ep}"
                else:
                    color = color_for_progress(done, total=5, use_gradient=use_gradient)
                    display = f"{color}{ep}{RESET}"
            line.append(display)
        print(" ".join(line))

    print("\nLegend:")
    for i in range(6):
        if github:
            emoji = emoji_for_progress(i, total=5, use_gradient=use_gradient)
            print(f"{emoji}{i}/5", end=" ")
        else:
            color = color_for_progress(i, total=5, use_gradient=use_gradient)
            print(f"{color}{i}/5{RESET}", end=" ")
    print(f"→ levels with {score_type}")


if __name__ == "__main__":
    filename = "tas/level_data.yml"
    highscores, speedruns = count_highscores_and_speedruns(filename)
    print("Levels already TASed:")
    print(f"Highscores: {highscores}")
    print(f"Speedruns: {speedruns}")
    github = False
    if len(sys.argv) > 1 and sys.argv[1] == "github":
        github = True
    if github:
        use_color = False
    else:
        use_color = True
    display_time_difference("Speedrun", sort=True, use_color=use_color)
    display_time_difference("Speedrun", sort=False, use_color=use_color)
    print()
    display_episode_grid(filename, "Highscore", use_gradient=False, github=github)
    print()
    display_episode_grid(filename, "Speedrun", use_gradient=False, github=github)
