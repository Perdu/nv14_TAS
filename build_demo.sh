#!/bin/bash

# This script recreates the libTAS inputs .ltm file

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

EXTRACT_FOLDER="extract"  # also change in builder.py for markers
DOCKER_VOLUME_PATH="docker_volume"
# LTM_FILE="n_recomp.ltm"
LTM_FILE="n_recomp_rta.ltm"

mkdir -p $EXTRACT_FOLDER

tar xzf $DOCKER_VOLUME_PATH/$LTM_FILE -C $EXTRACT_FOLDER
python builder.py $@
tar czf $DOCKER_VOLUME_PATH/$LTM_FILE -C $EXTRACT_FOLDER .
