#!/bin/bash

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

if [ $# -ne 2 -o ! -f volume/n_levels/"$1".ltm ]; then
    echo "Usage: $0 LEVEL_NUMBER RERECORDS_COUNT"
    exit 1
fi

mkdir extract
rm extract/*

tar xzf volume/n_levels/"$1".ltm -C extract/
sed -i "s/rerecord_count=.*/rerecord_count=$2/" extract/config.ini
tar czf volume/n_levels/"$1".ltm -C extract . --transform='s|^\./||'
