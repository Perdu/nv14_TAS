#!/bin/bash

# This script encodes a given level fully automatically (unlike build_demo.sh)

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

DOCKER_VOLUME_PATH="volume"

YOUTUBE=0
GHOST=0
OPEN_MPV=0
PASSTHROUGH_ARGS=()
# extract --record or -r from arguments
for arg in "$@"; do
    case "$arg" in
        --youtube|-y)
            YOUTUBE=1
            ;;
        --mpv|--open-mpv|-m)
            OPEN_MPV=1
            ;;
        --ghost|-g)
            GHOST=1
            ;;
        *)
            LEVEL="$arg"
            ;;
    esac
done

if [ "$LEVEL" == "" ]; then
    echo "Usage: $0 [--youtube|-y] [--ghost|-g] [--mpv|--open-mpv|-m] LEVEL"
    exit 1
fi

if [ "$YOUTUBE" -eq 1 ]; then
    IMAGE="libtas_n_recording_youtube"
else
    IMAGE="libtas_n_recording"
fi
docker run --rm -it -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix -v $HOME/.Xauthority:/root/.Xauthority:rw --net=host -v $SCRIPT_DIR/volume:/home/ $IMAGE bash -c "/root/src/libTAS/build/AppDir/usr/bin/libTAS -n -r /home/n_levels/$LEVEL.ltm --lua /home/lua/n_ghost.lua -d /home/n_demos/$LEVEL.mp4 /root/src/ruffle/target/release/ruffle_desktop -g gl --no-gui --width 792 /home/n_v14.swf ; while ffprobe /home/n_demos/$LEVEL.mp4 2>&1 | grep -q 'moov atom not found'; do sleep 1 ; done "

if [ $OPEN_MPV -eq 1 ]; then
    mpv volume/n_demos/$LEVEL.mp4
fi
