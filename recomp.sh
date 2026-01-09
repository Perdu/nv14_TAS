#!/bin/bash

# This script recreates the libTAS movie file (.ltm)

tar czf volume/n_recomp.ltm -C extract . --transform='s|^\./||'
