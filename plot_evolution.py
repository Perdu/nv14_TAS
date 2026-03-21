# AI-generated
# Plots number of TASed levels along time

import subprocess
import re
import matplotlib.pyplot as plt
from datetime import datetime

FILE_PATH = "README.md"
TOTAL_LEVELS = 500

# Regex to extract remaining levels
pattern = re.compile(r"TAS the remaining (\d+) levels")

# Get commits touching README.md
log_cmd = [
    "git", "log", "--follow", "--format=%H|%ct", "--", FILE_PATH
]
log_output = subprocess.check_output(log_cmd, text=True)

dates = []
values = []

for line in log_output.strip().split("\n"):
    commit_hash, timestamp = line.split("|")

    try:
        show_cmd = ["git", "show", f"{commit_hash}:{FILE_PATH}"]
        content = subprocess.check_output(show_cmd, text=True)

        match = pattern.search(content)
        if match:
            remaining = int(match.group(1))
            done = TOTAL_LEVELS - remaining
            if done < 10:
                continue

            dates.append(datetime.fromtimestamp(int(timestamp)))
            values.append(done)

    except subprocess.CalledProcessError:
        continue

# Chronological order
dates.reverse()
values.reverse()

# Optional: remove duplicate consecutive values (cleaner graph)
filtered_dates = []
filtered_values = []

last_val = None
for d, v in zip(dates, values):
    if v != last_val:
        filtered_dates.append(d)
        filtered_values.append(v)
        last_val = v

# Plot
plt.figure(figsize=(10, 5))
plt.plot(filtered_dates, filtered_values, marker='o')

plt.xlabel("Date")
plt.ylabel("Levels TASed")
plt.title("Progression of TAS Completion Over Time")
plt.grid()

plt.tight_layout()
plt.show()
