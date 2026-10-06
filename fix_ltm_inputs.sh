#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

FILE="extract/editor.ini"

function usage() {
    echo "Usage: $0 LTM_FILE [--force]"
    exit $1
}

if [ $# -lt 1 ]; then
    usage 1
fi

function replace_editor_inputs() {

    SECTION="$(mktemp)"
    TMP="$(mktemp)"
    trap 'rm -f "$SECTION" "$TMP"' EXIT

    cat > "$SECTION" <<'EOF'
[input_names]
1\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xff\xe1)
1\name=Shift_L
10\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0L)
10\name=\x21c7
11\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0R)
11\name=\x21c9
12\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0U)
12\name=\x21c8
13\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\x44)
13\name=\x21ca
14\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\x65)
14\name=e
15\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0t)
15\name=rt
16\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0T)
16\name=T
17\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0W)
17\name=rw
18\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\00)
18\name=r0
19\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\01)
19\name=r1
2\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xffQ)
2\name=Left
20\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\02)
20\name=r2
21\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\03)
21\name=r3
22\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\04)
22\name=r4
23\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\05)
23\name=r5
24\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\06)
24\name=r6
25\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0w)
25\name=w
26\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\xb0)
26\name=0
27\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\xb1)
27\name=1
28\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\xb2)
28\name=2
29\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\xb3)
29\name=3
3\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xffS)
3\name=Right
30\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\xb4)
30\name=4
31\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\xb5)
31\name=5
32\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\xb6)
32\name=6
33\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\x1\0\0\0\x1)
33\name=Mouse X coord
34\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\x2\0\0\0\x1)
34\name=Mouse Y coord
35\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\x5\0\0\0\0)
35\name=Mouse button 1
36\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0y)
36\name=y
4\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0 )
4\name=space
5\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0s)
5\name=s
6\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0l)
6\name=\x2190
7\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0r)
7\name=\x2192
8\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0u)
8\name=\x2191
9\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\x64)
9\name=\x2193
size=36
EOF

    # Replace the existing [input_names] section while preserving
    # every other section of editor.ini.
    awk -v section="$SECTION" '
function print_section(line) {
    while ((getline line < section) > 0)
        print line
    close(section)
}

BEGIN {
    in_section = 0
    written = 0
}

$0 == "[input_names]" {
    if (!written) {
        print_section()
        written = 1
    }

    in_section = 1
    next
}

in_section && /^\[/ {
    in_section = 0
}

!in_section {
    print
}

' "$FILE" > "$TMP"

    # Preserve the original file's permissions by writing into it
    # rather than replacing it with the mktemp file.
    cat "$TMP" > "$FILE"

}


#for i in volume/n_levels/[0-9][0-9]-[0-9].ltm n_base_for_levels.ltm ; do
#    echo "$i"

i="$1"

if [[ "${2:-}" == "--force" ]] || ! tar xOzf "$i" editor.ini | grep -F '36\name=y' >/dev/null; then
    echo "Fixing $i"
    rm -f extract/*
    tar xzf "$i" -C extract/
    replace_editor_inputs
    tar czf "$i" -C extract . --transform='s|^\./||'
else
    echo "Already up-to-date"
fi
