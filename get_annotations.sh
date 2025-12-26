#!/bin/bash

# Mostly AI-generated

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

ROOT_DIR="volume/n_levels"
OUTPUT_FILE="tas/annotations.md"

mkdir -p extract

# Empty or create the output file
> "$OUTPUT_FILE"

# Loop through all .ltm files matching the pattern
for file in "$ROOT_DIR"/*-*.ltm; do
    # Extract the base filename (e.g., 00-0.ltm -> 00-0)
    base=$(basename "$file" .ltm)
    
    if [[ $base =~ ^[0-9]{2}-[0-9]$ ]]; then
        # Extract annotations content from the .ltm file
        # Assuming annotations are stored in a file named "annotations" inside the .ltm archive (zip format)
        if tar xOzf "$file" annotations.txt &>/dev/null; then
            annotations=$(tar xOzf "$file" annotations.txt)
        else
            annotations=""
        fi
    
        # Append to output file with markdown format
        {
            echo "# $base"
            echo "$annotations"
            echo ""
        } >> "$OUTPUT_FILE"
    fi
done

echo "Annotations extracted to $OUTPUT_FILE"
