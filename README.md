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
- [Discord channel where we discuss this TAS](https://discord.com/channels/197765375503368192/199460839252688896)
- [TAS thread on N forum](https://forum.droni.es/viewtopic.php?f=20&t=4468&p=177293&sid=6f5f179201d5b44d889afbe5865cb685#p177293)
- [tasvideos.org: N TAS](https://tasvideos.org/Forum/Topics/9371)
- [tasvideos.org: Running Flash games in libTAS](https://tasvideos.org/Forum/Topics/20547)
### Documentation
- [Thread on air speed](https://forum.droni.es/viewtopic.php?f=20&t=10336&sid=569eab4beeecd814135f67b0fa574a3a)
- [Stumbles](https://discord.com/channels/197765375503368192/199460839252688896/1431062811903266957)
- [Hitboxes sizes](https://discord.com/channels/197765375503368192/199460839252688896/1437946735665352714)
- [Finding coordinates for tile bwj](https://discord.com/channels/197765375503368192/199460839252688896/1458230806383427790)
- [Drone detection](https://discord.com/channels/197765375503368192/199460839252688896/1458621494224490527)
- [Metanet tutorial on N physical collision system](https://edelkas.github.io/n/index/docs.html)
- [Nclone, Python emulator of the N++ engine (some parts are similar to N v1.4)](https://github.com/SimonV42/nclone)
- [Nclone: Part handling ceiling crushing](https://github.com/SimonV42/nclone/blob/842190b2a216579b5b5c551e0a0b4505fc3381cc/nsim.py#L299-L302)
### TAS Tutorials for other games
- Undertale https://www.youtube.com/watch?v=EFCnTeTdD2k&t=712s
- HK https://www.youtube.com/watch?v=qQAJk5_LUvg

## Todo
- Make script to display information for finale encode: TAS and 0th author, frames and time gain
- Add drone detection frame (for 1st chase)
- speed extraction still doesn't work for some grounded levels: 01-0, 02-0, 03-1, 37-0, 63-1, 80-2, 81-0, 82-0, 87-0, 88-1
- Sort Readme into several files for better readability
- Find drone position in memory and draw raycasting on detection frame
- Figure out something to optimize corner jumps
- automatically update README with current progress/stats
- TAS the remaining 388 levels ;)

## Install

### Linux

Just build the docker container using the [Dockerfile](Dockerfile):

```
docker build --tag libtas .
```

#### Run

```
docker run -it --rm -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix -v $HOME/.Xauthority:/root/.Xauthority:rw --net=host -v /home/$whoami/nv14_TAS/volume:/home/ libtas
```

Inside container:
```
/root/src/libTAS/build/AppDir/usr/bin/libTAS /root/src/ruffle/target/release/ruffle_desktop -g gl --no-gui /home/n_v14.swf &
```
(Or just press up arrow, as these commands are saved as previous command in bash history)

### Windows

In order to make it possible to TAS any game, libTAS uses tools that do not work properly in Windows. For that reason, it only works on Linux. If you're on Windows, you can use the Windows Subsystem for Linux (WSL) to run libTAS.

To install WSL for libTAS, please follow Step 1 of this guide: https://clementgallet.github.io/libTAS/guides/wsl/

Once you have WSL set up, install git to be able to clone this repository:

```
git clone https://github.com/Perdu/nv14_TAS.git
```

Then run the script to install everything:

```
./nv14_TAS/install_windows_wsl.sh
```

#### Run

```
/home/$(whoami)/libTAS/build/AppDir/usr/bin/libTAS /home/$(whoami)/ruffle/target/release/ruffle_desktop -g gl --no-gui /home/$(whoami)/nv14_TAS/volume/n_v14.swf &
```

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

## Optimization level in tas/level_data.yml

Jumping gives slightly more speed than running. As I was not aware that this kind of subpixel optimization was possible in this game (and because it takes a lot of time to optimize), this is not done for a lot of level. I indicate this in the [level demo data](tas/level_data.yml) file, with `optimization_level`:
- 1 (or nothing): level TASed without subpixel optimization
- 2: level TASed with subpixel optimization

## Video encoding

I used default settings for encoding.

Since youtube will downgrade videos smaller than 720p to 30fps, I upscaled the video to ensure it stays in 60fps:

```
ffmpeg -i 'n_rta_hs.mkv' -vf scale=-1:720 'n_rta_hs_upscaled.mkv'
```

This significantly *reduced* the size of the video because the fixed bitrate is removed.

Disable Settings → Audio → Audio Control → Disable to have sound in encoding.

## Known issues

Troubleshooting: see [troubleshoot.md](doc/troubleshoot.md)

No sound: this is normal and you don't need it. See [sound.md](doc/sound.md) if you really want it.

### Texture problem
Reported [here](https://github.com/ruffle-rs/ruffle/issues/21776)

Ruffle does not properly display all textures.

Adding `-g gl` removes error in stdout, but doesn't solve the issue.

N2 (swf Linux version) does not have the issue

## Technical information for submission

See [doc/technical_info.md](doc/technical_info.md)
