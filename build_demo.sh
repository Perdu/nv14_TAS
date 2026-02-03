#!/bin/bash

# This script recreates the libTAS inputs .ltm file

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

EXTRACT_FOLDER="extract"  # also change in builder.py for markers
DOCKER_VOLUME_PATH="volume"
BASE_LTM_FILE="n_base_for_levels.ltm"
LTM_FILE="n_speedrun.ltm"

RECORD=0
YOUTUBE=0
PASSTHROUGH_ARGS=()
# extract --record or -r from arguments
for arg in "$@"; do
    case "$arg" in
        --record|-r)
            RECORD=1
            ;;
        --youtube|-y)
            YOUTUBE=1
            ;;
        *)
            PASSTHROUGH_ARGS+=("$arg")
            ;;
    esac
done

mkdir -p $EXTRACT_FOLDER

tar xzf $BASE_LTM_FILE -C $EXTRACT_FOLDER
python3 builder.py "${PASSTHROUGH_ARGS[@]}"
tar czf $DOCKER_VOLUME_PATH/$LTM_FILE -C $EXTRACT_FOLDER .

if [ "$RECORD" -eq 1 ]; then
    if [ "$YOUTUBE" -eq 1 ]; then
        IMAGE="libtas_recording_youtube"
    else
        IMAGE="libtas_recording"
    fi
    docker run --rm -it -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix -v $HOME/.Xauthority:/root/.Xauthority:rw --net=host -v $SCRIPT_DIR/volume:/home/ $IMAGE
fi
