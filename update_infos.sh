#!/bin/bash

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

echo "Updating annotations..."
./get_annotations.sh
echo "Updating stats..."
python stats.py github > tas/stats.txt
echo "Updating Readme with number of remaining levels"
nb_levels_done=$(grep 'Speedruns:' tas/stats.txt  | cut -d ' ' -f 2)
remaining=$((500 - nb_levels_done))
sed -i "s/- TAS the remaining.*/- TAS the remaining $remaining levels ;)/" README.md
