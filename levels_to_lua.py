# AI-generated

import re

input_path = "external/N v1.4 + NReality levels.txt"
output_path = "volume/lua/levels.lua"

# Regex patterns
level_id_re = re.compile(r"\$(\d\d-\d)")
ninja_re = re.compile(r"5\^(\d+(?:\.\d+)?),(\d+(?:\.\d+)?)")
door_re = re.compile(r"11\^(\d+),(\d+),(\d+),(\d+)")
mine_re = re.compile(r"12\^(\d+),(\d+)")
drone_re = re.compile(r"6\^(\d+),(\d+)")
floorguard_re = re.compile(r"4\^(\d+),(\d+)")
gold_re = re.compile(r"0\^(\d+),(\d+)")
launchpad_re = re.compile(r"!2\^(\d+),(\d+)")
switch_re = re.compile(r"9\^(\d+),(\d+)")

levels = {}

with open(input_path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line.startswith("$"):
            continue

        # Extract level ID
        match = level_id_re.search(line)
        if not match:
            continue
        level_id = match.group(1)

        # Extract ninja spawn
        ninja_match = ninja_re.search(line)
        n_x = n_y = None
        if ninja_match:
            n_x, n_y = ninja_match.groups()

        # Extract lists of entities
        doors = [tuple(m) for m in door_re.findall(line)]
        mines = [tuple(m) for m in mine_re.findall(line)]
        drones = [tuple(d) for d in drone_re.findall(line)]
        guards = [tuple(g) for g in floorguard_re.findall(line)]
        gold = [tuple(g) for g in gold_re.findall(line)]
        launchpads = [tuple(l) for l in launchpad_re.findall(line)]
        switches = [tuple(s) for s in switch_re.findall(line)]

        levels[level_id] = {
            "n_x": n_x,
            "n_y": n_y,
            "doors": doors,
            "mines": mines,
            "drones": drones,
            "floorguards": guards,
            "gold": gold,
            "launchpads": launchpads,
            "switches": switches,
        }


# --- Write levels.lua ---
with open(output_path, "w", encoding="utf-8") as out:
    out.write("levels = {\n")

    for lid, data in levels.items():
        out.write(f'   ["{lid}"] = {{\n')
        out.write(f'      n_x = {data["n_x"]}, n_y = {data["n_y"]},\n')

        def write_list(name, lst, nb_items=2):
            out.write(f"      {name} = {{ ")
            if nb_items == 2:
                for x, y in lst:
                    out.write(f"{{x={x}, y={y}}}, ")
            else:
                for x, y, sx, sy in lst:
                    out.write(f"{{x={x}, y={y}, sx={sx}, sy={sy}}}, ")
            out.write("},\n")

        write_list("doors", data["doors"], nb_items=4)
        write_list("mines", data["mines"])
        write_list("drones", data["drones"])
        write_list("floorguards", data["floorguards"])
        write_list("gold", data["gold"])
        write_list("launchpads", data["launchpads"])
        write_list("switches", data["switches"])

        out.write("   },\n")

    out.write("}\nreturn levels\n")

print(f"✅ Parsed {len(levels)} levels and saved to {output_path}")
