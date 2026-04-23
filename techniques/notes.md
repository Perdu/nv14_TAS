# Workflow

- Get demo
```
python get_demo.py 27-2 | xclip -selection clipboard
```
- Record screen and play demo
```
sleep 1 ; ffmpeg -y -video_size 1920x1080 -framerate 25 -f x11grab -i :0.0 -vf "crop=in_w:in_h-50:0:0,format=yuv420p" output.mp4
```
- Use mpv to create video and find start timestamp
```
mpv 'output.mp4' | ./create_encode_command.sh
```
- Use output command to create the gif (add `setpts=2*PTS,fps=30` for half speed if necessary)
- Check gif with eog and adjust duration if necessary
```
eog gifs/chimney_jumps_02-4.gif
```

# Some commands

## Palette
```
ffmpeg -i output.mp4 -filter_complex "crop=800:615:559:240,fps=15,palettegen" palette.png
```

## Half speed
```
ffmpeg -ss 00:00.240 -t 2 -i output.mp4 -i palette.png -filter_complex 'crop=96:122:574:523,setpts=2*PTS,fps=30 [x]; [x][1:v] paletteuse=dither=sierra2_4a' -loop 0 gifs/bwj_turn_01-4.gif
```

## 05-4
```
ffmpeg -ss 00:03.040 -t 1.4 -i '/home/tohwi/github/nv14_TAS/techniques/output.mp4' -i palette.png -filter_complex "crop=130:168:618:660,fps=15 [x]; [x][1:v] paletteuse=dither=sierra2_4a" -loop 0 gifs/rcj_05-4.gif
```

## 06-4
```
ffmpeg -ss 00:05 -t 2.8 -i output.mp4 -i palette.png -filter_complex "crop=173:202:1168:570,fps=15 [x]; [x][1:v] paletteuse=dither=sierra2_4a" -loop 0 gifs/thwump_bwj_06-4.gif
```
