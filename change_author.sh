#!/bin/bash

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

EXTRACT_FOLDER="extract"
DOCKER_VOLUME_PATH="volume"

if [ $# -eq 0 ]; then
    echo "Usage: $0 LEVEL AUTHOR [hs]"
    exit
fi

hs_prefix=""
if [ $# -ge 3 -a "$3" == "hs" ]; then
    hs_prefix="_hs"
fi

mkdir -p $EXTRACT_FOLDER

tar xzf volume/n_levels/"$1"${hs_prefix}.ltm -C extract/
sed -i "s/authors=.*/authors=$2/" extract/config.ini
tar czf $DOCKER_VOLUME_PATH/n_levels/"$1"${hs_prefix}.ltm -C $EXTRACT_FOLDER . --transform='s|^\./||'
