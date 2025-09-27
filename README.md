# N v1.4 TAS

Info & tooling for making a Tool-Assisted Speedrun (TAS) for the popular 1.4 version of [Metanet N - the way of the Ninja](https://www.metanetsoftware.com/game/n).

![Screenshot of N running in libTAS](screenshot.png)

## What this repository contains

- Information about TASing N v1.4: this file + [meaningful_data.md](meaningful_data.md)
- [python script to convert N demos into libTAS inputs](converter.py)
- [libTAS inputs for each part of the TAS](tas/)
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

## Todo
- save libTAS config
- audio unmute crashes

## Run

After building the container (`docker build --tag libtas .`) using the [Dockerfile](Dockerfile):
```
docker run -it -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix -v $HOME/.Xauthority:/root/.Xauthority:rw --net=host -v /home/$whoami/nv14_TAS/docker:/home/ libtas
```

Inside container:
```
/root/src/libTAS/build/AppDir/usr/bin/libTAS /root/src/ruffle/target/release/ruffle_desktop -g gl --no-gui /home/n_v14.swf &
```
(Or just press up arrow, as this command is saved as previous command in bash history)

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
### Texture problem
Reported [here](https://github.com/ruffle-rs/ruffle/issues/21776)
Ruffle does not properly display all textures
Adding -g gl removes error in stdout, but doesn't solve the issue
N2 (swf Linux version) does not have the issue
