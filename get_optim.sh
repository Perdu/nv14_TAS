#!/bin/bash

# Get result of latest optimisation run and add it to clipboard

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

EXTRACT_FOLDER="extract"
#OPTIM_FILE="tas optimiser/wip/optim.ltm"
OPTIM_FILE="volume/n_levels/57-3_optimised.ltm"

tar xzf $OPTIM_FILE -C $EXTRACT_FOLDER
tail -n +41 $EXTRACT_FOLDER/inputs | xclip -selection clipboard
