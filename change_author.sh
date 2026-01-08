#!/bin/bash

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

EXTRACT_FOLDER="extract"
DOCKER_VOLUME_PATH="volume"

if [ $# -eq 0 ]; then
    echo "Usage: $0 LEVEL AUTHOR"
fi

mkdir -p $EXTRACT_FOLDER

tar xzf volume/n_levels/"$1".ltm -C extract/
sed -i "s/authors=.*/authors=$2/" extract/config.ini
tar czf $DOCKER_VOLUME_PATH/n_levels/"$1".ltm -C $EXTRACT_FOLDER .
