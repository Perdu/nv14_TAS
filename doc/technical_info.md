# Technical information for submission

Some stuff relevant for the final submission

## Submission
https://tasvideos.org/SubmissionInstructions

Approved platform : libTAS + Ruffle https://tasvideos.org/Platforms#AdobeFlash

Attribution could be an issue if we're using submitted runs https://tasvideos.org/MovieRules#MovieMustBeProperlyAttributed

## libTAS config

libTAS configs that have to be set for the TAS to run properly (done in [ruffle_desktop.ini](docker/ruffle_desktop.ini)):
- Frames per second: 40
- Settings → Runtime → clock_gettime() monotonic
- Settings → Audio → Audio Control → Disable (to avoid savestates crashes)

## Framerate

While the game displays a framerate of 120 (in `exiftool` or ruffle for instance), it's actually *40* since `1/0.025 = 40`.

Using the `Runtime -> Debug -> Uncontrolled time` option in libTAS does give a framerate of around 40, not 120.

Framerate seems to be 60 for Nv2.

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
