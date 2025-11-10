# AI-generated

import re

input_path = "external/N v1.4 + NReality levels.txt"
output_path = "volume/lua/levels.lua"

# Regex patterns for the pieces we care about
level_id_re = re.compile(r"\$(\d\d-\d)")
ninja_re = re.compile(r"5\^(\d+),(\d+)")
door_re = re.compile(r"11\^(\d+),(\d+),(\d+),(\d+)")

levels = {}

with open(input_path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line.startswith("$"):
            continue  # skip non-level lines

        # Extract level ID (e.g. 00-0)
        level_id_match = level_id_re.search(line)
        if not level_id_match:
            continue
        level_id = level_id_match.group(1)

        # Extract ninja spawn (5^x,y)
        ninja_match = ninja_re.search(line)
        n_x = None
        n_y = None
        if ninja_match:
            n_x, n_y = ninja_match.groups()

        # Extract door and switch info (11^xdoor,ydoor,xswitch,yswitch)
        door_match = door_re.search(line)
        door_x = door_y = doorswitch_x = doorswitch_y = None
        if door_match:
            door_x, door_y, doorswitch_x, doorswitch_y = door_match.groups()

        levels[level_id] = {
            "n_x": n_x,
            "n_y": n_y,
            "door_x": door_x,
            "door_y": door_y,
            "doorswitch_x": doorswitch_x,
            "doorswitch_y": doorswitch_y,
        }

# --- Write out levels.lua ---
with open(output_path, "w", encoding="utf-8") as out:
    out.write("levels = {\n")
    for lid, data in levels.items():
        out.write(
            f'   ["{lid}"] = {{ '
            f'n_x = {data["n_x"] or "nil"}, n_y = {data["n_y"] or "nil"}, '
            f'door_x = {data["door_x"] or "nil"}, door_y = {data["door_y"] or "nil"}, '
            f'doorswitch_x = {data["doorswitch_x"] or "nil"}, doorswitch_y = {data["doorswitch_y"] or "nil"} }},\n'
        )
    out.write("}\n")

print(f"✅ Parsed {len(levels)} levels and saved to {output_path}")
