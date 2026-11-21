# AI-generated

import argparse
import yaml


def get_demo(file_path, level, mode="sr", author=False):
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

    return level_data[key]["authors" if author else "demo"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("level", help="Level name")
    parser.add_argument("mode", nargs="?", default="sr", choices=["sr", "hs"])
    parser.add_argument(
        "-a", "--author",
        action="store_true",
        help="Return author name instead of demo"
    )

    args = parser.parse_args()

    file_path = "tas/level_data.yml"
    result = get_demo(file_path, args.level, args.mode, args.author)
    print(result)
