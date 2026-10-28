# Leaderboard ghost comparison videos (v4.19)

`tools/encode_leaderboard_ghosts.py` downloads selected speedrun or highscore
replays, then encodes them alongside your primary TAS into a silent H.264 MP4.
Each ghost has its own colour and player-name label. The primary replay drives
the visible objects, enemies and particles; secondary replays supply independent
player animations and optional ghost gold. This creates a comparison video,
not a playable multiplayer demo.

## Setup and launch

Use Python 3.11 or newer. From the extracted optimiser root:

```sh
python -m pip install ".[video]"
python build_native.py
python tools/encode_leaderboard_ghosts.py --help
```

Install FFmpeg with `libx264` separately, either on `PATH` or select it with
`--ffmpeg-path`. The video extra installs Pillow; the native build needs the
usual C compiler/build tools. See [video setup](VIDEO_ENCODING.md#install).
The download-only mode needs only Python's standard library, without Pillow,
FFmpeg or a compiled native extension.

Both of these commands work from the project root:

```sh
python tools/encode_leaderboard_ghosts.py "88-4 TAS.txt" --level 88-4 -o comparison.mp4
python -m tools.encode_leaderboard_ghosts "88-4 TAS.txt" --level 88-4 -o comparison.mp4
```

The tool is included in installed packages as well as the source archive.
After installation, the `python -m tools.encode_leaderboard_ghosts` form is
available from other folders in the same Python environment. To run an
uninstalled source copy from elsewhere, use its full script path, for example:

```powershell
python "C:\N\nv14_tas_replay_optimizer_v4.19\tools\encode_leaderboard_ghosts.py" "88-4 TAS.txt" --level 88-4 -o comparison.mp4
```

Import lookup uses `--optimizer-dir DIR` first if supplied, then looks beside
the script and in its parent directory, then uses the installed optimiser.
For the bundled script this finds the source root above `tools/`. Explicit
`--optimizer-dir` must point to a folder containing `nv14_video.py`.

**All relative paths use your current working directory**, including TAS
files, output, downloads, pose caches, the exclusion file, assets and an
explicit level database. The script does not change directories. Running
from another folder therefore uses another default download cache unless
you pass the same absolute `--cache-dir`.

## Defaults

| Setting | Default |
| --- | --- |
| Leaderboard | `--mode speedrun` |
| Level | `--level 88-4` (`--level-id` is an alias) |
| Number of ghosts | `--count 1` |
| Alignment | `--alignment start` (`--replay-alignment` is an alias) |
| Download policy | Reuse cached files; download only missing files |
| Download cache | `leaderboard_ghost_cache` in the working directory |
| Output | `LEVEL_TAS_topCOUNT_start.mp4`; highscore adds `_highscore` after `TAS`; exit alignment ends in `_exit.mp4` |
| Resolution | `--scale 2` (1584 x 1200) |
| Rendering | `--render-workers 8 --render-quality fast` |
| Encoding | `--fps 40 --crf 18 --preset medium` |
| Labels | Primary `TAS`; ghosts' leaderboard names; `follow`; size 8 |
| Ghost colours | Distinct palette, starting with `#3568a8` |
| Ghost gold | `--secondary-gold off` |
| Effects and simulation | Particles, object animations and enemies enabled |
| Terminal hold | 1 second |
| Pose cache | Disabled until `--replay-cache-dir DIR` is supplied |
| Transport memory / profiling | `--render-memory-mib 128`; profiling off |
| Encoding progress | Enabled; stdout updates about every two seconds |

The default level is always **88-4**, even if the filename mentions another
level. Pass `--level` explicitly for every other level. This selects the
leaderboard and, for packed text/LTM input, the database record. For combined
text you must select a leaderboard matching the embedded map; the tool cannot
verify that association from the leaderboard's packed inputs alone.

The helper has its own arguments and does not load `--config`/TOML settings.
Use `--help` for its complete option list.

## Input formats

| Primary TAS format | Level source and options |
| --- | --- |
| Combined `$name#author#...#replay#` text | Level and credit are embedded. Omit `--levels-file`. |
| Packed-only demo text, such as `150:...` | Supply the original level database with `--levels-file` and select `--level`. |
| libTAS `.ltm` movie | Supply the original level database with `--levels-file` and select `--level`. |

```sh
python tools/encode_leaderboard_ghosts.py "20-0 TAS.txt" --level 20-0
python tools/encode_leaderboard_ghosts.py packed.txt --level 20-0 --levels-file "N v1.4 + NReality levels.txt"
python tools/encode_leaderboard_ghosts.py "20-0.ltm" --level 20-0 --levels-file "N v1.4 + NReality levels.txt"
```

The level database is not bundled. If `--levels-file` is omitted, the optimiser
uses its existing discovery rules: `external/N v1.4 + NReality levels.txt`
relative to the working folder, its parent or the optimiser root, plus locations
beside the input. An explicit path is the clearest choice.

The level name and author at the bottom of the video come from the primary
combined record or selected database record, independently of player labels.
Downloaded ghosts do not replace that credit.

Text demos receive the normal final neutral tick unless `--no-final-neutral`
is set. LTM menus/preroll are removed by the existing loader, its recorded tail
is retained, and it never receives an artificial final tick. Use
`--ltm-postroll N` to trim exactly N recorded trailing frames; it is valid only
for an LTM primary.

## Speedruns and highscores

Speedruns use the n.infunity.com leaderboard, sorted by ascending frame count.
`--count N` is strict: too few entries is an error, and exclusions do not apply.

```sh
python tools/encode_leaderboard_ghosts.py "88-4 TAS.txt" --level 88-4 --count 5 --label-position top-left -o "88-4 comparison.mp4"
```

Highscores use Harvey Cartel's legacy N endpoints, which publish up to 20
slots for episodes 00 through 99. Eligible entries are sorted by descending
score. Excluded names are removed before taking up to `--count`; fewer eligible
entries produces a warning and uses those available. No eligible entries or a
failed selected replay is an error. The tool cannot recover ranks beyond the
published slots.

```sh
python tools/encode_leaderboard_ghosts.py "00-0 HS.txt" --mode highscore --level 00-0 --count 5 --label-position top-left -o "00-0 highscore comparison.mp4"
python tools/encode_leaderboard_ghosts.py "00-0 HS.txt" --mode highscore --level 00-0 --exclude-player AnotherName --exclude-players-file excluded.txt
```

Built-in highscore exclusions are `alllan`, `Marcao`, `JoaoGCNunes`, `asda`,
`dnawrkshp`, `haxYOscoreboard`, `Cuppy33`, `Yvsk` and `JC239`. These are the
supplied user-maintained list, not automatic detection. Names use
case-insensitive exact matching. Repeat `--exclude-player NAME` or provide a
UTF-8 file with one name per line; blank lines and lines beginning with `#`
are ignored. These options add to the built-in list and apply again to cached
leaderboards, including offline runs. They are rejected in speedrun mode.

The highscore wire protocol is adapted from NHigh 2.0.1 by jg9000, with
modifications by eru_bahagon. The tool is self-contained and needs neither
`nhighlib.py` nor Python 2. Legacy requests use HTTP POST to
`http://www.harveycartel.org/metanet/n/data13/`, with
`get_topscores_query_jg.php` for boards and `get_lv_demo.php` for replays.

## Alignment, labels and ghost gold

```sh
python tools/encode_leaderboard_ghosts.py "88-4 TAS.txt" --level 88-4 --count 3 --alignment exit --label-position top-left
python tools/encode_leaderboard_ghosts.py "00-0 HS.txt" --mode highscore --level 00-0 --secondary-gold animated
```

- `--alignment start` starts all runs together. `exit` measures native
  completion ticks and delays shorter runs to finish together; every selected
  replay must complete, including the primary.
- `--label-position follow` moves labels with players. `top-left` creates a
  static legend and appends scores. Speedrun labels show frames (`f`);
  highscore labels show game score in seconds (`s`), not elapsed time.
- `--primary-label "Optimised TAS"` changes the primary caption;
  `--primary-label ""` hides it. `--no-ghost-labels` hides ghost labels.
  `--label-size 6..32` controls game-pixel size, scaled with the video.
- Labels use the N GUI font and player colours. Remote names are made
  single-line and shortened to the 128-character caption limit while cached selection
  metadata retains the original name. Unsupported glyphs appear as `?`.
  Crowded following labels can overlap.
- `--ghost-color "#3568a8"` gives every ghost the specified colour. Otherwise
  the deterministic palette expands without cycling through a fixed list;
  very large groups will still have visually similar colours.
- `--secondary-gold off` hides ghost gold. `static` leaves shaded coloured
  gold after the primary collects it, until the owning ghost collects it.
  `animated` also plays the gold collection tween. Ownership follows selected
  leaderboard order among ghosts still needing that piece. These animations
  are independent of `--particles` and `--object-animations`.

Top-left ghost scores come from the leaderboard. The TAS speedrun score uses
its declared input count for text, or the first completion tick minus the final
check tick for LTM. The TAS highscore is simulated without rendering and uses
`(3600 + gold_bonus_ticks - (completion_tick - 1)) / 40`, with the selected
final-neutral policy. A nonfinishing TAS omits its simulated score.

## Downloads and the two caches

```sh
python tools/encode_leaderboard_ghosts.py --download-only --level 88-4 --count 5
python tools/encode_leaderboard_ghosts.py "88-4 TAS.txt" --level 88-4 --count 5 --offline
python tools/encode_leaderboard_ghosts.py "88-4 TAS.txt" --level 88-4 --online
python tools/encode_leaderboard_ghosts.py "88-4 TAS.txt" --level 88-4 --replay-cache-dir pose_cache
```

| Option | Behaviour |
| --- | --- |
| Neither `--online` nor `--offline` | Read cached boards/replays when present; download missing files. Existing boards are snapshots, with no automatic expiry. |
| `--online` (alias `--refresh`) | Fetch a fresh board and every selected replay even if cached. |
| `--offline` | No network requests; missing required cache files are errors. Mutually exclusive with `--online`/`--refresh`. |
| `--download-only` | Select, download/validate and cache ghosts without a TAS or encoder dependencies. Also usable with `--offline` to validate cached selections. |
| `--cache-dir DIR` | Store downloaded boards, packed demos, highscore responses and selection metadata. |
| `--replay-cache-dir DIR` | Optional native secondary-pose/event cache to reuse simulation work across repeated encodes of the same level/replay and compatible settings. |

Speedrun downloads live in `CACHE/LEVEL/`, containing `leaderboard.html`,
`demo_ID.txt` and `selection.json`. Highscores live in `CACHE/highscore/LEVEL/`,
with `leaderboard.txt`, `demo_ID.response.txt`, `demo_ID.txt` and `selection.json`.
Highscore raw response files are required offline to verify player and score
against the cached board; packed text alone is insufficient. The packed file
can be recreated from a valid cached response.

Download caching saves network requests. Pose caching saves secondary replay
simulation on later encodes; it does not cache finished rendered video frames.
Different levels cannot reuse each other's poses. `--offline` controls only
downloads, and `--online` does not clear pose caches. Existing download-cache
layouts from the standalone script remain valid. If your cache is still named
`speedrun_ghost_cache`, pass that name explicitly with `--cache-dir`.

Malformed or mismatched cached responses are reported rather than silently
used. Refresh them with `--online`. Network requests use a 30-second timeout,
a 0.25-second initial delay and up to three attempts for transient failures;
`--timeout` and `--request-delay` adjust these values.

## Performance and output

The encoding stage prints live progress by default, using the same reporter as
`encode-video`. It announces replay/graphics preparation, rendering and FFmpeg
finalisation, and refreshes the current phase about every two seconds, including
while waiting on workers or FFmpeg. Rendering updates include frames sent to
FFmpeg, average throughput, effective worker count and elapsed time. They are
flushed to stdout, so redirected logs update promptly too.

Use `--no-progress` to hide these encoding updates, or `--progress` to explicitly
enable them. Download/selection messages and the final summary still print.
This is independent of `--profile`; download-only mode never starts an encoding
reporter. See [progress details](VIDEO_ENCODING.md#live-stdout-progress-v419),
including the meaning of the frame count and Python API behaviour.

```sh
python tools/encode_leaderboard_ghosts.py "88-4 TAS.txt" --level 88-4 --render-workers 8 --render-quality fast --replay-cache-dir pose_cache --profile
python tools/encode_leaderboard_ghosts.py "88-4 TAS.txt" --level 88-4 --render-workers 2 --render-memory-mib 64 --scale 1
```

`--render-workers 1` is serial, `0` lets the encoder choose, and `2..64`
requests multiple processes. `--render-quality exact` preserves exact geometry;
`fast` quantises sprite transforms to improve reuse. `--render-memory-mib`
accepts 16 through 65536 MiB and controls RGB frame transport, not total process
memory. `--profile` prints encoder timing and cache statistics to the console. FFmpeg stays at preset `medium` unless explicitly changed.

Use `--scale 1..4`, `--fps 40..240`, `--crf 0..51`, `--preset NAME` and
`--terminal-hold-seconds 0..3600` as in the encoder. Higher FPS repeats gameplay
frames; it does not change the 40 Hz simulation. `--no-particles`,
`--particle-seed N`, `--no-object-animations`, `--assets-path DIR` and
`--no-simulate-enemies` are available. Disabling enemies is a motion-only
visualisation and can change completion and score outcomes.

An encode writes the MP4. From v4.18, it does not create an adjacent
`NAME.ghosts.json` report. Selected runs and per-replay outcomes/offsets are
printed to the console; `--profile` also prints a `performance:` line containing
JSON timing and cache statistics. The download cache's `selection.json` still
records the selected entries, exclusions, cache policy, colours and labels.
Existing `.ghosts.json` files from older releases are left untouched.
Use different `-o` names to retain multiple videos; successful encodes replace
existing video destinations. Output may not overwrite the inputs, the tool,
the exclusions file, or anything beneath the download cache.

If an import fails, keep the script in `tools/`, install this release, or pass
`--optimizer-dir` to its root. If the native backend is unavailable, run
`python build_native.py` from that root with the same Python used for encoding.
An exit-alignment failure means at least one replay does not finish with the
chosen level/inputs/settings. Use start alignment to inspect it, and check that
`--level` matches the primary map. Service availability and leaderboard format
changes can affect online downloads; cached runs can still be used offline.
