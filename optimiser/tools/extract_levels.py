"""Extract built-in LevelData(name, level_string) entries from n_v14_codedump.as."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PATTERN = re.compile(r"new LevelData\('((?:\\'|[^'])*)', '((?:\\'|[^'])*)'\)")


def extract(text: str) -> list[dict[str, str]]:
    levels: list[dict[str, str]] = []
    for match in PATTERN.finditer(text):
        name = match.group(1).replace("\\'", "'")
        level = match.group(2).replace("\\'", "'")
        # Real levels have a 31*23 map and an object separator.
        if "|" in level and len(level.split("|", 1)[0]) == 31 * 23:
            levels.append({"name": name, "level": level})
    return levels


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("codedump", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("levels"))
    parser.add_argument("--index", type=Path, default=Path("levels.json"))
    args = parser.parse_args()

    levels = extract(args.codedump.read_text(encoding="utf-8", errors="replace"))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, object]] = []
    for number, item in enumerate(levels):
        safe = re.sub(r"[^a-z0-9]+", "_", item["name"].lower()).strip("_") or f"level_{number}"
        filename = f"{number:03d}_{safe}.txt"
        (args.out_dir / filename).write_text(item["level"], encoding="utf-8")
        index.append({"index": number, "name": item["name"], "file": filename})
    args.index.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"extracted {len(levels)} levels")


if __name__ == "__main__":
    main()
