#!/bin/bash

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

zip -r chatgpt_package.zip tas\ optimiser/ volume/n_v14.swf volume/n_v14_patched.swf $(which libTAS) $(which libtas.so) $(which libtas32.so) $(which ruffle 2>/dev/null) $(which ruffle_desktop 2>/dev/null) techniques/README.md
