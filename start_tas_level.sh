#!/bin/bash

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

EXTRACT_FOLDER="extract"  # also change in builder.py for markers
DOCKER_VOLUME_PATH="docker_volume"
LTM_FILE="n_base_for_levels.ltm"

mkdir -p $EXTRACT_FOLDER

tar xzf $DOCKER_VOLUME_PATH/$LTM_FILE -C $EXTRACT_FOLDER
python start_tas_level.py $@
tar czf $DOCKER_VOLUME_PATH/n_levels/"$1".ltm -C $EXTRACT_FOLDER .
