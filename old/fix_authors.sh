#!/bin/bash

# Fix hash in all ltm file to avoid having a warning on game start

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

for i in volume/n_levels/[0-9][0-9]-[0-9].ltm n_base_for_levels.ltm ; do
    echo "$i"
    if $(tar xOzf "$i" config.ini | grep authors | grep -q ','); then
        echo "Fixing $i"
        rm extract/*
        tar xzf "$i" -C extract/
        sed -i 's/authors=\(.*\)/authors="\1"/' extract/config.ini
        tar czf "$i" -C extract . --transform='s|^\./||'
    fi
done
