#!/bin/bash

#!/usr/bin/env bash
set -euo pipefail

# Usage: ./create_multi_splicer.sh 88-4
# Run from the directory containing volume/, or set SPLICES_ROOT.
if [[ $# -ne 1 || ! $1 =~ ^[0-9]+-[0-9]+$ ]]; then
    echo "Usage: $0 LEVEL (e.g. 88-4)" >&2
    exit 2
fi

level=$1
splice_dir="${SPLICES_ROOT:-volume/splices}/$level"
output="$splice_dir/multi-splicer.toml"

if [[ ! -d $splice_dir ]]; then
    echo "Error: directory not found: $splice_dir" >&2
    exit 1
fi
if [[ ! -f $splice_dir/end.txt ]]; then
    echo "Error: $splice_dir/end.txt not found" >&2
    exit 1
fi

shopt -s nullglob
numbers=()
for file in "$splice_dir"/*.txt; do
    name=${file##*/}
    name=${name%.txt}
    if [[ $name =~ ^[0-9]+$ ]]; then
        numbers+=("$name")
    fi
done
shopt -u nullglob

if (( ${#numbers[@]} > 0 )); then
    mapfile -t numbers < <(
        printf '%s\n' "${numbers[@]}" | LC_ALL=C sort -n
    )
fi

{
    printf '[multi-splicer]\nsplice-files = ['
    for name in "${numbers[@]}"; do
        printf '"%s", ' "$name"
    done
    printf '"end"]\n'
} > "$output"

echo "Created $output (${#numbers[@]} numbered splices + end)"
