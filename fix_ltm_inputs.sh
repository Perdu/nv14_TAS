#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

FILE="extract/editor.ini"

function usage() {
    echo "Usage: $0 LTM_FILE"
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
18\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\01)
18\name=r1
19\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\02)
19\name=r2
2\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xffQ)
2\name=Left
20\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\03)
20\name=r3
21\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\04)
21\name=r4
22\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\05)
22\name=r5
23\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\06)
23\name=r6
24\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0w)
24\name=w
25\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\xb0)
25\name=1
26\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\xb01)
26\name=2
27\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\xb02)
27\name=3
28\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\xb03)
28\name=4
29\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\xb04)
29\name=5
3\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xffS)
3\name=Right
30\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\xb05)
30\name=6
31\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\x1\0\0\0\x1)
31\name=Mouse X coord
32\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\x2\0\0\0\x1)
32\name=Mouse Y coord
33\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\x5\0\0\0\0)
33\name=Mouse button 1
34\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0y)
34\name=y
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
size=34
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

if ! tar xOzf "$i" editor.ini | grep -F '34\name=y' >/dev/null; then
    echo "Fixing $i"
    rm extract/*
    tar xzf "$i" -C extract/
    replace_editor_inputs
    tar czf "$i" -C extract . --transform='s|^\./||'
else
    echo "Already up-to-date"
fi
