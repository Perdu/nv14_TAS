#!/bin/bash

# This script extracts a libTAS movie file (.ltm)

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

mkdir -p extract

rm extract/*

tar xzf volume/n_recomp.ltm -C extract
