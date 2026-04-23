#!/bin/bash

# To be used with mpv and mpv-scripts https://github.com/occivink/mpv-scripts
# Run like this: mpv output.mp4 | ./create_encode_command.sh

grep 'encode' | while read -r dummy1 dummy2 dummy3 ss rest dummy4 dummy5 dummy6 dummy7 dummy8 dummy9 crop rest; do
    echo "ss: $ss"
    # Remove surrounding quotes
    crop=${crop#\'}
    crop=${crop%\'}
    echo "crop: $crop"
    # echo "Rest: $rest"
    echo "ffmpeg -ss $ss -t 2 -i output.mp4 -i palette.png -filter_complex '$crop,fps=15 [x]; [x][1:v] paletteuse=dither=sierra2_4a' -loop 0 gifs/TODO.gif"
    echo "ffmpeg -ss $ss -t 2 -i output.mp4 -i palette.png -filter_complex '$crop,fps=15 [x]; [x][1:v] paletteuse=dither=sierra2_4a' -loop 0 gifs/TODO.gif" | xclip
done
