from pathlib import Path
import re

import yaml

INPUT_FILE = Path("tas/level_data.yml")
OUTPUT_DIR = Path("volume/splices/")

with INPUT_FILE.open("r", encoding="utf-8") as f:
    levels = yaml.safe_load(f)

for level, data in levels.items():
    speedrun = data.get("Speedrun")

    if not speedrun:
        continue

    level_dir = OUTPUT_DIR / level
    output_file = level_dir / "end.toml"

    # Skip if either end.toml or end.txt already exists.
    if output_file.exists() or (level_dir / "end.txt").exists():
        print(f"Skipping {level}: end.toml or end.txt already exists")
        continue

    # Extract the number of frames from values such as "335 f".
    match = re.fullmatch(r"\s*(\d+)\s*f\s*", str(speedrun["time"]))
    if not match:
        print(f"Skipping {level}: invalid time {speedrun['time']!r}")
        continue

    frames = int(match.group(1))
    start_frame = max(0, frames - 100)

    config = f'''[local]
search = "population"
target_frame = {frames}
range = "{start_frame}:{frames}"
simulate-enemies = false
objective = "earliest-interaction"
target-object = "exit:0"
# secondary_objective = "max-x"
# require-interaction = ["testdoor:0"]
'''

    level_dir.mkdir(parents=True, exist_ok=True)

    output_file.write_text(config, encoding="utf-8")

    print(f"Generated {output_file}")
