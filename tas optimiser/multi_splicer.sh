#!/bin/bash

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

function usage() {
    echo "Usage: $0 LEVEL"
    exit $1
}

if [ $# -lt 1 ]; then
    usage 1
fi

if [ ! -d levels/$1 ] ; then
    echo "No known splice files for level $1"
    exit 1
fi

ORIG="../n_levels/$1.ltm"
for i in levels/$1/*.txt ; do
    splice_ext=$(basename $i)
    splice=${splice_ext%.txt}
    echo -e "\033[32m************** Running ${splice_ext}\033[0m"
    python3 optimize_replay.py local "$ORIG" --config "$i" --output wip/$1_$splice.ltm --replay-output wip/$1_$splice.txt --stagnation-rounds 1 --workers 15
    ORIG=wip/$1_$splice.ltm
done

cp $ORIG wip/optim.ltm
