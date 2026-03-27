#!/bin/bash

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

ffdec -importScript volume/n_v14.swf volume/n_v14_patched.swf decompiled_source/
