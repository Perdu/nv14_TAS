#!/bin/bash

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

function usage() {
    echo "Usage: $0 LEVEL START"
    exit $1
}

if [ $# -lt 1 ]; then
    usage 1
fi

if [ ! -d ../splices/$1 ] ; then
    echo "No known splice files for level $1"
    exit 1
fi

# Clean previous runs
rm wip/$1_*.ltm

ORIG="../n_levels/$1.ltm"
while IFS= read -r i; do
    splice_ext=$(basename $i)
    splice=${splice_ext%.txt}

    # If $2 is provided, skip files with a number <= $2
    if [[ -n ${2:-} && $splice_ext =~ ^([0-9]+)(_|[.]) ]]; then
        num=${BASH_REMATCH[1]}
        if (( 10#$num <= 10#$2 )); then
            continue
        fi
    fi

    echo -e "\033[32m************** Running ${splice_ext}\033[0m"
    python3 optimize_replay.py local "$ORIG" --config "$i" --output wip/$1_$splice.ltm --replay-output wip/$1_$splice.txt --stagnation-rounds 1 --workers 15
    ORIG=wip/$1_$splice.ltm
    cp $ORIG wip/optim.ltm
done < <(printf '%s\n' ../splices/"$1"/*.txt ../splices/"$1"/*.toml | sort -V)
