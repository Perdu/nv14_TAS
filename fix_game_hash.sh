#!/bin/bash

# Fix hash in all ltm file to avoid having a warning on game start

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

HASH="fcc2c6d4912aa52b8c4f68a31a6eab74"

for i in volume/n_levels/[0-9][0-9]-[0-9].ltm ; do
    echo "$i"
    if $(tar xOzf "$i" config.ini | grep -vq md5=$HASH); then
        echo "Fixing $i"
        rm extract/*
        tar xzf "$i" -C extract/
        sed -i "s/md5=.*/md5=$HASH/" extract/config.ini
        tar czf "$i" -C extract . --transform='s|^\./||'
    fi
done
