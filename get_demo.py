# AI-generated

import sys
import yaml

def get_demo(file_path, level, mode="sr"):
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if level not in data:
        raise ValueError(f"Level '{level}' not found")

    level_data = data[level]

    if mode.lower() == "hs":
        key = "Highscore"
    else:
        key = "Speedrun"

    if key not in level_data:
        raise ValueError(f"{key} data not found for level '{level}'")

    return level_data[key]["demo"]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <level> [sr|hs]")
        sys.exit(1)

    file_path = "tas/level_data.yml"
    level = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "sr"

    demo = get_demo(file_path, level, mode)
    print(demo)
