#!/bin/bash

# This script extracts a libTAS movie file (.ltm)

mkdir -p extract

tar xzf docker_volume/n_recomp.ltm -C extract
