#!/bin/bash

# Get result of latest optimisation run and add it to clipboard so it
# can be copied directly into libTAS

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

EXTRACT_FOLDER="extract"
OPTIM_FILE="tas optimiser/wip/optim.ltm"

tar xzf "$OPTIM_FILE" -C $EXTRACT_FOLDER
sed '0,/^|K20/d' "$EXTRACT_FOLDER/inputs" | xclip -selection clipboard
