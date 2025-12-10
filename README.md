# N v1.4 TAS

Info & tooling for making a Tool-Assisted Speedrun (TAS) for the popular 1.4 version of [Metanet N - the way of the Ninja](https://www.metanetsoftware.com/game/n).

![Screenshot of N running in libTAS](screenshot.png)

## What this repository contains

- Information about TASing N v1.4 (this file)
- [python script to convert N demos into libTAS inputs](converter.py)
- [bash](build_demo.sh) and [python](builder.py) scripts working together to recreate the libTAS demo from [level demo data](tas/level_data.yml)
- [Data to build the TAS](tas/): info for each level (including demos), loading times, click coordinates
- [Script to create level data from a local database](make_rta_level_data.py) (used to create [RTA data](tas/level_data_rta.yml))
- [Lua script to display overlay information](display_infos.lua.template) (demo information, real-time inputs)
- [Other Lua scripts to help TASing](volume/lua)
- [Python script to get demo data from .sol file](sol_to_demo.py)
- [Other tools and informations from external sources](external/)

## Links
### Instruction pages
- https://tasvideos.org/EmulatorResources/LibTAS
- https://tasvideos.org/EmulatorResources/LibTAS/Usage
- https://tasvideos.org/EmulatorResources/Ruffle
- https://tasvideos.org/Platforms#AdobeFlash
### Tools & their bugtrackers
- https://github.com/clementgallet/libTAS
- https://github.com/clementgallet/libTAS/issues
- https://github.com/ruffle-rs/ruffle/issues
### Forums
- [TAS thread on N forum](https://forum.droni.es/viewtopic.php?f=20&t=4468&p=177293&sid=6f5f179201d5b44d889afbe5865cb685#p177293)
- [tasvideos.org: N TAS](https://tasvideos.org/Forum/Topics/9371)
- [tasvideos.org: Running Flash games in libTAS](https://tasvideos.org/Forum/Topics/20547)
### Documentation
- [Thread on air speed](https://forum.droni.es/viewtopic.php?f=20&t=10336&sid=569eab4beeecd814135f67b0fa574a3a)
- [Stumbles](https://discord.com/channels/197765375503368192/199460839252688896/1431062811903266957)

## Todo
- dump_ghost: dump speed information as well
- resulting speed vector
- extract all ghost information automatically
- Sort Readme into several files for better readability
- automatically update README with current progress/stats
- TAS the remaining 414 levels ;)

## Optimization level

Jumping gives slightly more speed than running. As I was not aware that this kind of subpixel optimization was possible in this game (and because it takes a lot of time to optimize), this is not done for a lot of level. I indicate this in the [level demo data](tas/level_data.yml) file, with `optimization_level`:
- 1 (or nothing): level TASed without subpixel optimization
- 2: level TASed with subpixel optimization

## Run

After building the container (`docker build --tag libtas .`) using the [Dockerfile](Dockerfile):
```
docker run -it --rm -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix -v $HOME/.Xauthority:/root/.Xauthority:rw --net=host -v /home/$whoami/nv14_TAS/volume:/home/ libtas
```

Inside container:
```
/root/src/libTAS/build/AppDir/usr/bin/libTAS /root/src/ruffle/target/release/ruffle_desktop -g gl --no-gui /home/n_v14.swf &
```
(Or just press up arrow, as these commands are saved as previous command in bash history)

## Usage
https://github.com/clementgallet/libTAS?tab=readme-ov-file#run

https://tasvideos.org/EmulatorResources/LibTAS/Usage
- frame advancing, using the V key
- pause/play, using the pause key
- fast forward, using the tab key

Use Shift+F1-10 to save state and F1-10 to reload state.

You can press on individual frames to go there, provided you have a saved state before

## Movie format
https://clementgallet.github.io/libTAS/guides/format/

Extracting save file: `tar xzf n.ltm`

## Game source
### n v1.4
https://archive.org/details/n_v1pc → .zip with a .exe

or here: https://www.thewayoftheninja.org/n_history.html

Or the .swf directly from NReality: https://n.infunity.com/

### n v2
https://www.thewayoftheninja.org/n.html -> the Linux download contains a .swf

## Extraction
https://flashpointarchive.org/datahub/Extracting_Flash_Games

```
ffdec n_v14.exe
```

Click on the file on the left, the Save as...

## Running (without Docker)
I used ruffle-nightly-bin from AUR. Guidelines require to use nightly build: https://tasvideos.org/EmulatorResources/Ruffle

I used libtas-git

Procedure:
- Ensure you have no .sol file (careful: this is your save file, you probably want to back it up as the following command deletes it):
```
$ rm ~/.local/share/ruffle/SharedObjects/localhost/n_v14b_userdata.sol

```
- libTAS. Set executable to `/bin/ruffle` and CLI options to `--no-gui /<path>/n_v14.swf`
- in libTAS, `clock_gettime() monotonic` must be enabled in Runtime->Time tracking for Ruffle to work in libTAS
- Set up the Movie recording section
- Movie->Input Editor
- Pause
- Start !!!

Then see the Usage section

## Framerate
While the game displays a framerate of 120 (in `exiftool` or ruffle for instance), it's actually *40* since `1/0.025 = 40`.

Using the `Runtime -> Debug -> Uncontrolled time` option in libTAS does give a framerate of around 40, not 120.

Framerate seems to be 60 for Nv2.


## Submission
https://tasvideos.org/SubmissionInstructions

Approved platform : libTAS + Ruffle https://tasvideos.org/Platforms#AdobeFlash

Attribution could be an issue if we're using submitted runs https://tasvideos.org/MovieRules#MovieMustBeProperlyAttributed

## Checksums

From archive.org:
```
$ sha1sum n_v14.exe 
b74b9c92471ee86b05e6ddaf9199bb2fca50cc34  n_v14.exe
```
Matches the metanet-found one.

[Extracted one](external/n_v14.swf):
```
$ sha1sum 3.swf
75a82ce33cda9770e773a64c585c14bb5a8f8478  3.swf
```

Nreality & n_v14_200_v4b ones:
```
$ sha1sum n_v14.swf 
cf3d9ef6eb5762cbfca362bc72b6ff0c03455c31  n_v14.swf
```

## libTAS config
libTAS configs that have to be set for the TAS to run properly (done in [ruffle_desktop.ini](docker/ruffle_desktop.ini)):
- Frames per second: 40
- Settings → Runtime → clock_gettime() monotonic
- Settings → Audio → Audio Control → Disable (to avoid savestates crashes, see below)

## Video encoding

I used default settings for encoding.

Since youtube will downgrade videos smaller than 720p to 30fps, I upscaled the video to ensure it stays in 60fps:

```
ffmpeg -i 'n_rta_hs.mkv' -vf scale=-1:720 'n_rta_hs_upscaled.mkv'
```

This significantly *reduced* the size of the video because the fixed bitrate is removed.

Disable Settings → Audio → Audio Control → Disable to have sound in encoding.

## Sound
Getting sound to work in libTAS is not really useful, as you don't need sound during the TASing process (it breaks savestates) and sound in encoding will work regardless.

If you want it regardless, you can use the [Dockerfile_sound](Dockerfile_sound) I made and run it with:

```
docker run -it --rm -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix -v $HOME/.Xauthority:/root/.Xauthority:rw --net=host -v /home/$whoami/nv14_TAS/volume:/home/taser/tas/ -v /run/user/$UID/pulse:/run/user/$UID/pulse -e PULSE_SERVER=unix:/run/user/$UID/pulse/native -v /etc/machine-id:/etc/machine-id:ro --group-add audio --cap-add=cap_checkpoint_restore libtas_sound
```

(this is more restrictive as it's not running with root user inside the container)

## Tutorials
- Undertale https://www.youtube.com/watch?v=EFCnTeTdD2k&t=712s
- HK https://www.youtube.com/watch?v=qQAJk5_LUvg

## Troubleshoot
- I bypassed the [Ruffle crash on startup when using an nvidia card](https://github.com/clementgallet/libTAS/issues/656) by using Docker instead
- if savestates-related crashes -> use -g gl
- [inputs are not passed to the game](https://github.com/clementgallet/libTAS/issues/652): build from latest commit (1.4.6 is broken)
- crash after loading a savestate: if running with RUST_BACKTRACE=1 gives an audio crash backlog, try with audio set to Disable (besides of Mute)

## Known issues
### Broken determinism
On one of my machine, there is a random number of lag frames at startup, and the loaded background level at startup is different on each playback. In other words, determinism is broken. [This is a known issue with monotonic](https://discord.com/channels/726811446498820198/726811447262183477/1352571040684969988).

Fix: launch ruffle with a game once before opening libTAS so it downloads libopenh264.
### Texture problem
Reported [here](https://github.com/ruffle-rs/ruffle/issues/21776)
Ruffle does not properly display all textures
Adding -g gl removes error in stdout, but doesn't solve the issue
N2 (swf Linux version) does not have the issue
