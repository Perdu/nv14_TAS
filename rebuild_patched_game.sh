#!/bin/bash

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

which ffdec >/dev/null
if [ $? -ne 0 ]; then
    echo "ffdec (JPEXS) missing, installing it..."
    wget https://github.com/jindrapetrik/jpexs-decompiler/releases/download/version25.1.3/ffdec_25.1.3.deb
    sudo apt-get install ./ffdec_25.1.3.deb
fi

ffdec -importScript volume/n_v14.swf volume/n_v14_patched.swf decompiled_source/
