#!/bin/bash

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

EXTRACT_FOLDER="extract"  # also change in builder.py for markers
DOCKER_VOLUME_PATH="volume"
LTM_FILE="n_base_for_levels.ltm"

mkdir -p $EXTRACT_FOLDER

tar xzf $DOCKER_VOLUME_PATH/$LTM_FILE -C $EXTRACT_FOLDER
if [ -e $DOCKER_VOLUME_PATH/n_levels/"$1".ltm ]; then
    echo "$1.ltm already exists, not creating"
else
    python start_tas_level.py $@
    tar czf $DOCKER_VOLUME_PATH/n_levels/"$1".ltm -C $EXTRACT_FOLDER .
fi

# Commented out as we already created all of them
# if [ -e $DOCKER_VOLUME_PATH/n_levels/"$1"_rta.ltm ]; then
#     echo "$1_rta.ltm already exists, not creating"
# else
#     python start_tas_level.py $@ rta
#     tar czf $DOCKER_VOLUME_PATH/n_levels/"$1"_rta.ltm -C $EXTRACT_FOLDER .
# fi
