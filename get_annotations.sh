#!/bin/bash

# Mostly AI-generated

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

ROOT_DIR="volume/n_levels"
OUTPUT_FILE="tas/annotations.md"

mkdir -p extract

# Empty or create the output file
> "$OUTPUT_FILE"

total_rerecords=0

# Loop through all .ltm files matching the pattern
for file in "$ROOT_DIR"/*-*.ltm; do
    # Extract the base filename (e.g., 00-0.ltm -> 00-0)
    base=$(basename "$file" .ltm)
    
    if [[ $base =~ ^[0-9]{2}-[0-9]$ ]]; then
        # To verify broken archives:
        # echo "$base"
        # tar tzf "$file" | grep './'
        # continue

        # Extract annotations content from the .ltm file
        # Assuming annotations are stored in a file named "annotations" inside the .ltm archive (zip format)
        if tar xOzf "$file" annotations.txt &>/dev/null; then
            annotations=$(tar xOzf "$file" annotations.txt)
        else
            annotations=""
        fi

        if tar xOzf "$file" config.ini &>/dev/null; then
            rerecords=$(tar xOzf "$file" config.ini | grep rerecord_count | cut -d '=' -f 2)
        else
            rerecords=""
        fi
    
        # Append to output file with markdown format
        {
            echo "# $base"
            if [ "$rerecords" != "" ]; then
                echo "rerecords: $rerecords"
                echo ""
            fi
            echo "$annotations"
            echo ""
        } >> "$OUTPUT_FILE"

        (( total_rerecords += rerecords ))
    fi
done

echo "# Total rerecords: $total_rerecords" >> "$OUTPUT_FILE"

echo "Annotations extracted to $OUTPUT_FILE"
echo "Total rerecords: $total_rerecords"
