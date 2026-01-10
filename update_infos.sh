#!/bin/bash

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

echo "Updating annotations..."
./get_annotations.sh
echo "Updating stats..."
python stats.py github > tas/stats.txt
