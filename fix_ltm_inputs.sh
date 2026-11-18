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
10\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\x64)
10\name=\x2193
11\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0L)
11\name=\x21c7
12\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0R)
12\name=\x21c9
13\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0U)
13\name=\x21c8
14\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\x44)
14\name=\x21ca
15\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\x65)
15\name=e
16\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0b)
16\name=b
17\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0g)
17\name=g
18\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0t)
18\name=rt
19\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0T)
19\name=T
2\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xffQ)
2\name=Left
20\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0W)
20\name=rw
21\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\x30)
21\name=r0
22\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\x31)
22\name=r1
23\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\x32)
23\name=r2
24\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\x33)
24\name=r3
25\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\x34)
25\name=r4
26\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\x35)
26\name=r5
27\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0\x36)
27\name=r6
28\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0w)
28\name=w
29\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xff\xb0)
29\name=0
3\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xffS)
3\name=Right
30\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xff\xb1)
30\name=1
31\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xff\xb2)
31\name=2
32\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xff\xb3)
32\name=3
33\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xff\xb4)
33\name=4
34\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xff\xb5)
34\name=5
35\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\xff\xb6)
35\name=6
36\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0S)
36\name=S
37\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0V)
37\name=\x21e6
38\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0X)
38\name=\x21e8
39\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0Y)
39\name=\x21e7
4\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0 )
4\name=space
40\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0Z)
40\name=\x21e9
41\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\x1\0\0\0\x1)
41\name=Mouse X coord
42\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\x2\0\0\0\x1)
42\name=Mouse Y coord
43\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\x5\0\0\0\0)
43\name=Mouse button 1
44\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0y)
44\name=y
5\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0s)
5\name=s
6\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0c)
6\name=c
7\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0l)
7\name=\x2190
8\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0r)
8\name=\x2192
9\input=@Variant(\0\0\0\x7f\0\0\0\fSingleInput\0\0\0\0\0\0\0\0u)
9\name=\x2191
size=44
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
