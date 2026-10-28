# Replay video encoding (v4.19)

v4.19 renders a replay directly from the native engine into a **silent H.264
MP4**. It includes terrain, original SWF ninja poses, animated objects,
pickups, doors, moving enemies, rockets, weapon visuals, drone eye easing
and optional particles using original SWF animation clips. It does not launch
Flash or record a desktop window.

The CLI, both video APIs and session methods default to `scale=2`,
`render_workers=8` and `render_quality="fast"`. Explicit arguments and TOML
settings continue to override these values. Output defaults to 1584x1200.

v4.26 adds four-by-four coverage antialiasing to laser drone prefire and
firing beams in both `fast` and `exact` modes. Diagonal beams retain fractional
endpoints and widths; axis-aligned prefire hairlines remain one device pixel.
Clipped beam masks are cached per renderer and can be pasted into partial
redraws without seams. This also applies to comparison/leaderboard encodes.

To download leaderboard ghosts and compare them with a TAS, use the bundled
[`tools/encode_leaderboard_ghosts.py`](LEADERBOARD_GHOSTS.md) helper. It supports
speedruns and highscores, player-name labels, exclusions, download caching and
the comparison encoder's alignment, gold and performance controls. The helper
has its own command-line arguments; it does not read encoder TOML settings.

v4.08.1 changes the first secondary player to darker blue (`#3568a8`) for
better contrast against the stage background.

v4.08 adds any number of secondary player overlays, aligned at the start or
the actual exit completion tick. The primary replay remains the sole source
of visible world state and effects. See [comparison encoding](#comparing-multiple-replays-v408).

v4.07 fixes thin object outlines by retaining original vector paths through the
final output transform. Flash hairlines have a one-device-pixel minimum width;
horizontal/vertical edges are fitted to pixel centres. They are no longer
shrunk with a large source PNG. This restores bounce-block borders, one-way
platform edges, launch-pad outlines, switch markings and exit-door details,
including animated states. Ninja limbs also retain their final pixel width.
Solid fills, curves, holes, opacity, registration and source painting order are
preserved. Four-by-four coverage sampling antialiases vector artwork and terrain.
Increasing `--scale` increases geometry resolution while keeping hairlines thin.

The bundled vector data requires only the existing Pillow dependency. PNGs
remain available for legacy/custom packs without vector metadata; those packs
retain their previous raster appearance. Particles continue to use their
existing PNG/beam path. The v4.07 outline change did not alter native gameplay.
In v4.10, rebuild for complete native ghost-mask rasterisation; compact pose capture
continues to use the v4.09 engine interface. Older
v4.06+ engine extensions retain the per-tick comparison fallback.

## Live stdout progress (v4.19)

`encode-video` prints progress by default. The leaderboard ghost tool uses the
same reporting during its encoding stage. A flushed line announces each major
phase, followed by a heartbeat approximately every two seconds while work
continues. Output is plain text with newlines, so it works in terminals and
redirected logs without requiring `python -u`.

Phases cover replay loading, native preparation, secondary track/cache setup,
exit-alignment measurements where requested, FFmpeg checks, graphics setup,
rendering, terminal holds, queued-frame completion, FFmpeg finalisation and
the final output save. Slow worker startup, rendering waits and FFmpeg's final
flush still receive heartbeats. Secondary preparation identifies the current
replay when several are being processed.

During rendering the messages include cumulative video frames sent to FFmpeg,
average frames per second after the first second, effective worker count and
elapsed wall time. For example, a progress line can look like:

```text
[encode-video] Rendering / encoding; 1,240 frames sent; 62.0 frames/s avg; 8 render worker(s); elapsed 23.1s
```

"Frames sent" counts frames delivered to FFmpeg, including repeated frames at
higher FPS and terminal holds. It is not FFmpeg's confirmed encoded-packet
count. No percentage or ETA is guessed: death/completion can shorten the input
timeline. The count remains cumulative if automatic rendering switches workers.
Finalisation can continue after all frames have been sent; `Complete` appears
only after the export returns successfully. Failures/cancellation stop the
reporter and do not print a successful completion message.

```sh
python optimize_replay.py encode-video replay.txt -o replay.mp4
python optimize_replay.py encode-video replay.txt -o replay.mp4 --no-progress
```

`--no-progress` disables these progress lines while retaining the usual final
summary and errors. `--progress` explicitly enables them. TOML supports
`progress = false` in `[encode-video]`; an explicit CLI flag takes precedence.
Progress is independent of `--profile`, which still controls detailed timing
statistics. No progress/report file is created.

Both Python video APIs and the session methods accept `progress=True` to opt
in. Their default is `False`, keeping programmatic exports silent. Only the
calling process reports progress; render workers never print it. Enabled
exports use one short-lived background thread to keep stdout active during
blocking work, without adding per-frame logging or native simulation changes.

## Level name and author (v4.16)

Encodes automatically show `Level name  ( by Author )` at the bottom centre,
in the bundled original N GUI font. This follows the original userlevels caption
format and its `(396, 580)` stage position. The small 8-pixel text scales crisply
with `scale`; output dimensions remain `792*scale` by `600*scale`.

The name and author come from the first two fields of the primary
`$name#author#...` record. Combined demo files retain their own metadata;
packed demos and LTMs use their selected level-database record. Secondary
replays never replace the primary level credit. It stays visible throughout
playback, delayed starts and terminal holds, independently of player labels,
particles and object animations.

The batch API accepts a wrapped level record directly:

```python
result = encode_replay_data_video(
    level_data=f"$My level#Map author##{raw_level_data}#",
    replay_data=replay_string,
    output_path="my_level.mp4",
)
```

An embedded replay in `level_data` is ignored; `replay_data` supplies the inputs.
Raw tile/object strings and pre-parsed `NativeLevel` instances have no name or
author metadata and leave the footer blank. If one field is empty, the available
name or author is shown. Whitespace is flattened to one line; overly wide credits
are ellipsised to fit. As with player labels, characters outside the original
font's Western character set are replaced with `?`.

The caption uses bounded text caching and retained drawing commands, including
parallel workers and reusable sessions. No extra gameplay simulation is needed.

## Install

Python 3.11+ and the existing C compiler/build tools are required when building
from this source release. Cython is not required: regenerated C is included.

```sh
python -m pip install ".[video]"
python build_native.py
```

The optional `video` extra installs Pillow. Install an FFmpeg build that includes
`libx264` separately; `ffmpeg -encoders` should list that encoder. On Ubuntu/WSL,
the distribution's `ffmpeg` package is suitable when it includes libx264.
On Windows use `ffmpeg.exe` on PATH, or pass its path explicitly. A GPU is not
required. The bundled graphics pack removes the need for SWF/Java at runtime.

Installing the ordinary package without `[video]` does not install Pillow.
Normal searches, CLI help and player CSV export do not load Pillow, the renderer,
or graphics. The new scene API is query-only: no scene capture hooks, event
buffers, per-tick checks, state allocations or key changes are added to gameplay.
The existing optional player animation tracker is enabled only for video/dump
calls that request it. Particles use a separate Python tracker created only
when encoding with particles enabled. Object MovieClips and eased eyes have
their own Python tracker, created only when object animations are enabled.
Native gameplay, state layouts, physics, player animation tracking and search
kernels remain unchanged; no cosmetic hooks, counters or branches were added
to optimisation ticks. v4.06 adds an optional read-only door-timer field to the
scene query. Rebuild the extension once to use object animations.

## Command line

```sh
python optimize_replay.py encode-video replay.txt -o replay.mp4
python optimize_replay.py encode-video replay.txt -o replay_2x.mp4 --scale 2
python optimize_replay.py encode-video replay.txt -o clean.mp4 --no-particles
python optimize_replay.py encode-video replay.txt -o effects.mp4 --particle-seed 42
python optimize_replay.py encode-video replay.txt -o simple.mp4 --no-object-animations --no-particles
python optimize_replay.py encode-video "00-0.ltm" --levels-file "N v1.4 + NReality levels.txt" -o "00-0.mp4"
python optimize_replay.py encode-video replay.txt --ffmpeg-path "C:\tools\ffmpeg\bin\ffmpeg.exe"
```

Accepted inputs match `dump-player`: combined level/demo text, packed-only demo
text with an external level database, and `.ltm` movies. Packed demos and LTMs
can specify `--level-id 00-0`; otherwise the loader uses the filename. LTM
menus/preroll are excluded using the existing input loader. Its selected
recorded neutral tail is retained; `--ltm-postroll N` excludes exactly N recorded
trailing frames. No synthetic tick is added to LTM input.

Demo text gets one final neutral input by default, unless simulation has already
ended. `--no-final-neutral` disables it. Stored jump-trigger bits are preserved,
including triggers that differ from the edges of held inputs.

| Option | Default | Meaning |
| --- | --- | --- |
| `--output`, `-o` | Input stem + `.mp4` | Destination |
| `--secondary-replay PATH` | None | Repeat for each additional player; same primary level |
| `--replay-alignment` | start | `start`: simultaneous starts; `exit`: simultaneous completion |
| `--secondary-color "#RRGGBB"` | Blue-first palette | If overriding, repeat once per secondary in replay order |
| `--secondary-gold off/static/animated` | `off` | Leave pending gold in the first uncollected ghost's colour; optionally animate collection |
| `--primary-label TEXT` | None | Optional text identifying the primary player |
| `--secondary-label TEXT` | None | Repeat once per secondary in replay order; `""` hides an individual label |
| `--label-size PIXELS` | 8 | GUI font size in game pixels, 6..32; multiplied by video scale |
| `--label-position` | follow | `follow`: above each player; `top-left`: static colour-matched legend |
| `--scale` | 2 | Integer 1..4; base stage 792x600 |
| `--render-workers` | 8 | 0 selects automatically; 1 is serial; 2..64 request parallel rendering |
| `--render-quality` | fast | Exact geometry, or `fast` for a quantised ninja sprite atlas |
| `--progress` / `--no-progress` | Enabled in CLI | Flushed stdout phase/frame updates about every two seconds |
| `--replay-cache-dir` | None | Optional persistent secondary-pose cache directory |
| `--fps` | 40 | Integer 40..240; higher rates repeat frames |
| `--particles` / `--no-particles` | Enabled | Render particles; no effect on gameplay |
| `--object-animations` / `--no-object-animations` | Enabled | Original object timelines and eye easing; rendering only |
| `--particle-seed` | 0 | Private integer seed for reproducible cosmetic variation |
| `--terminal-hold-seconds` | 1 | Hold terminal gameplay while cosmetic clips continue; 0..3600 |
| `--crf` | 18 | H.264 quality 0..51; lower means higher quality |
| `--preset` | medium | libx264 speed/compression preset |
| `--simulate-enemies` | Enabled | Use native enemy simulation |
| `--assets-path` | Bundled pack | Override directory containing `manifest.json` |
| `--ffmpeg-path` | PATH lookup | Select FFmpeg executable |
| `--config` | None | TOML `[common]` and `[encode-video]` defaults |

When enemy simulation is disabled, enemies are drawn at their initial positions
from level descriptors, without movement or firing. Such an export is a
motion-only visualisation, not a normal gameplay recording.

## Direct-data API

```python
from nv14_video import encode_replay_data_video

result = encode_replay_data_video(
    level_data=level_string,
    replay_data=replay_string,
    output_path="00-0_highscore.mp4",
    simulate_enemies=True,
    fps=40,
    scale=2,
    particles=True,
    object_animations=True,
    particle_seed=0,
    terminal_hold_seconds=1.0,
)
print(result.simulated_ticks, result.video_frames, result.stop_reason)
```

`level_data` accepts a raw level string or a reusable `NativeLevel`. A supplied
native level must match `simulate_enemies`. `replay_data` accepts the packed
`<ticks>:<words>` string, a `ComplexReplay`, or a sequence of `InputFrame` objects.
Every call creates a fresh state. Batch callers can reuse a parsed native level;
no temporary demo or CSV is required.

`encode_replay_video(input_path, output_path=None, ...)` provides the file-based
API. It additionally accepts `levels_file`, `level_id`, and `ltm_postroll`.
Both APIs accept the command-line rendering/encoding options as keyword
arguments, using underscores in option names. There is no `audio` option in
this release: all output is silent.

The repeatable comparison options use the plural API names
`secondary_replays` and `secondary_colors`.

`VideoEncodeResult` provides `output_path`, `source_frames`, `simulated_ticks`,
`video_frames`, `fps`, `width`, `height`, `duration_seconds`, `stop_reason`,
`final_neutral_written`, `dead`, and `complete`. `source_frames` counts selected
replay inputs, not menu/preroll frames or duplicated video frames.
`stop_reason` is `complete`, `dead` or `input_end`; both terminal flags remain
true if completion and death occur on the same tick. Completion takes priority
in the textual stop reason, matching the accepted replay-success convention.

In v4.08 those existing gameplay fields continue to describe the **primary**.
`video_frames` and `duration_seconds` describe the entire comparison video.
New fields are `replay_alignment`, `timeline_ticks` (40 Hz gameplay timeline,
including delayed starts but excluding terminal hold), and `replays`, an ordered
tuple of `VideoReplayResult` records, primary first. Every record contains:

| Field | Meaning |
| --- | --- |
| `index` | 0 for primary; 1, 2, ... for secondaries |
| `source_frames` | Selected inputs, before any synthetic neutral |
| `simulated_ticks` | Actually consumed inputs, including a used final neutral |
| `start_offset_ticks` | Delay before this replay's first tick, in 40 Hz ticks |
| `end_tick` | Offset + simulated ticks; the global end boundary |
| `color` | Secondary `#rrggbb`; `None` means original primary artwork |
| `stop_reason` | `complete`, `dead` or `input_end` |
| `final_neutral_written`, `dead`, `complete` | That replay's own flags |

These records are also populated for ordinary single-replay exports.
`VideoEncodeResult.render_workers` reports the effective render-process count;
`render_quality` reports the selected exact/fast mode. In v4.10, `timings` is
`None` by default or a statistics dictionary with `profile=True`.

Errors and Ctrl+C leave an existing destination untouched. Encoding uses a
temporary file in the destination directory and replaces the target only after
FFmpeg succeeds. Decoded inputs remain in memory; scene/image processing and
frame streaming do not store the entire rendered movie. A reusable renderer
caches static terrain and a bounded set of transformed sprites. The particle
tracker retains only the previous scene and at most 102 live clips, replacing
old depth slots like the original front buffer.

## Performance controls (v4.10)

Rebuild with `python build_native.py` after extracting this release. Included C
sources build the engine and separate optional rendering extension; Cython is
not required. The complete opaque ghost-mask operation now transforms and
flattens paths, computes coverage in one reusable native buffer, and reproduces
Pillow's BOX downsampling. Older render extensions retain the per-path native
fallback, and missing extensions retain the Python fallback. Normal optimiser
imports and ticks do not load rendering dependencies or perform rendering work.

```sh
python optimize_replay.py encode-video primary.txt --secondary-replay other.txt --render-workers 4 --profile -o comparison.mp4
python optimize_replay.py encode-video primary.txt --secondary-replay other.txt --scale 4 --render-memory-mib 256 -o large.mp4
python optimize_replay.py encode-video primary.txt --secondary-replay other.txt --replay-alignment exit --replay-cache-dir .nv14-video-cache -o finish.mp4
```

`render_workers=0` is automatic. A fresh export draws its first twelve gameplay
images serially, then uses the measured drawing/packing and pipe-writing cost to
choose up to four workers, subject to available CPUs and remaining work. Those
initial images are actual output, not an extra replay or discarded probe. Short
exports and scenes dominated by FFmpeg stay serial. A reusable session can use
its previous measurements immediately. Explicit `1` stays serial; `2..64`
requests a process count. Transport memory and shared-memory availability may
reduce that count. The result reports the highest effective count used.

Simulation and cosmetic clocks stay sequential. The encoder owns fresh scene
snapshots and shares them with its trackers without deep-copying them. Cosmetic
records are constructed once per rendered sample. Standalone tracker APIs keep
their defensive copying and existing return values. Workers receive completed
snapshots only; primary-world state, particle RNG and exit alignment are unchanged.

The renderer retains an exact draw list and a private previous canvas. Unchanged
object draw commands are reused, affected regions are restored and replayed in
original depth order, and complex changes fall back to complete redraws. Terrain
and artwork preparation are cached. `SceneRenderer.render()` still returns an
independent image that callers can keep or modify. The internal `render_into`
path packs RGB through bounded chunks into caller-owned buffers. Construct a
renderer with `incremental=False` for a full-redraw reference.

Since v4.15, draw signatures contain only fields that affect rendered pixels.
Collected primary gold leaves the draw list once its collection artwork hides.
A spatial grid selects commands intersecting each dirty region, maintaining
paint order and updating memberships only when bounds change. Small command
lists keep a direct scan; wide-line and large-damage cases still use the exact
full-redraw fallback. When many small dirty regions exceed the region budget,
they are coalesced into a bounded patch if its area remains small. This avoids
premature full redraws while later animation bounds are still being merged.

Workers write into a shared RGB ring and return only completion/statistics
records. Ordered writes keep every output frame in place. The default transport
budget is **128 MiB**, with one slot per queued image plus one retained image.
At scale 4 this fits five RGB slots and permits four workers where shared memory
is available. `render_memory_mib` / `--render-memory-mib` accepts 16..65536 MiB.
A smaller budget or a small POSIX `/dev/shm` mount reduces concurrency; unavailable
shared memory falls back to serial. Serial mode always needs at least one full
RGB frame even if the requested transport budget is smaller.

v4.15 submits the first image immediately and groups subsequent consecutive
images into jobs of up to four frames. Each job uses one worker's retained
canvas and one shared-memory attachment. Blocks shrink to fit the slot budget;
partial blocks flush at the end. Only completion records return through the
process pipe. Pickle shares repeated references within a block; snapshots are
complete so arbitrary worker scheduling remains safe.

The transport budget excludes renderer canvases and artwork caches. Per renderer,
pixel caches are bounded at 16 MiB source assets, 16 MiB world transforms, 8 MiB
primary-player artwork, 8 MiB ghost masks and 8 MiB gold luminance/alpha data;
retained command groups have a 32 MiB budget and entry limit. The optional gold
compositor has separate 8 MiB limits for sprite bytes, command records and
prepared groups, with entry limits; retained Python/Pillow objects add overhead.
Native retained mask workspaces are capped at
16 MiB per process. Terrain and the previous frame add resolution-dependent
storage. No complete rendered movie is retained in memory. Reusable sessions
multiply these costs by their configured cached-level count and worker count.

At **FPS greater than 40**, a private streaming Matroska RGB pipe attaches exact
image durations. FFmpeg expands these durations into the same repeated output
frames as v4.09. This removes repeated RGB payloads without changing gameplay,
frame counts, the partial final interval, or animated terminal holds. The final
file remains H.264 MP4. At 40 FPS the ordinary raw RGB pipe is used. Both paths
preserve `libx264`, default preset `medium`, CRF 18 and explicit preset choices.

`render_quality="exact"` preserves the existing fractional position/rotation,
outline fitting and four-by-four antialiasing. `"fast"` (the default since
v4.16.1) uses ninja-only snapping to eighth-output-pixel positions and whole-degree rotations.
Ghost masks remain independent of colour. Exact cache keys and arithmetic keep
pixels independent of frame order and worker scheduling.

`replay_cache_dir` remains optional. Secondary poses use 64-byte records and
spill beyond 256 KiB per track to temporary storage. Persistent entries retain
checked JSON headers, binary checksums, atomic writes, and keys covering the
actual engine binary, level, inputs and animation options. Corrupt entries are
recomputed. Cache write failures do not prevent export. This release does not
change the native engine or record format; unchanged engine binaries can reuse
v4.09 pose entries. Rebuilding can change the binary hash and invalidate old keys.
Persistent cache files have no automatic eviction.

### Reusable encoding sessions

```python
from nv14_video import VideoEncodeSession


def main():
    with VideoEncodeSession(render_workers=4, max_cached_levels=2) as session:
        first = session.encode_replay_video(
            "primary.txt", "start.mp4", secondary_replays=["other.txt"],
            replay_alignment="start", profile=True)
        second = session.encode_replay_video(
            "primary.txt", "finish.mp4", secondary_replays=["other.txt"],
            replay_alignment="exit", profile=True)
        print(second.timings)


if __name__ == "__main__":
    main()
```

`session.encode_replay_data_video(level_data, replay_data, output_path, ...)`
provides the same reuse for direct data. Session method defaults come from its
`render_workers` and `render_memory_mib` constructor arguments; per-call keyword
overrides are accepted. Ordinary encoding functions also accept `session=...`
while retaining their own keyword defaults. Each export gets fresh gameplay and
cosmetic state and an independent FFmpeg process. Native levels, parent artwork
and worker pools are reused. Cached configurations are bounded by
`max_cached_levels` (default 2; range 1..16). Asset metadata changes invalidate
cached parent configurations. Closing the context releases workers and caches.
One session supports sequential exports; concurrent use is rejected. It can be
reused after an ordinary failed export, and broken worker pools are rebuilt.

Both Python APIs accept `render_memory_mib`, `profile` and `session` in addition
to the existing controls. Protect multiprocessing entry points with
`if __name__ == "__main__":`; the CLI already does so. Use one worker in
interactive environments without an importable guarded entry point.

### Timing and reproducible comparisons

`--profile` / `profile=True` populates `VideoEncodeResult.timings` and prints
statistics in the CLI. Without profiling that field is `None`; a session always
retains its latest measurements in `last_profile`. Reported values include total
wall time, setup time, rendering/packing time, parent wait and pipe-write times,
actual RGB bytes transferred, frame counts, worker decisions, renderer cache and
dirty-region counters, and secondary pose-cache hits. Parallel `render_seconds`
is the **sum of worker elapsed drawing/packing times** and can exceed wall time;
it must not be added to parent wait/write time as if the stages were sequential.

A bundled benchmark compares complete encodes and optionally checks decoded RGB
frames and replay outcomes against another release:

```sh
python -m tools.benchmark_video --ghosts 20 --scales 1 4 --workers 1 4 --fps 40 --compare-root ../v4.09 --json
```

The default fixture is bundled 00-1. Its ghosts are neutral-prefix workload
variants, not a claim of independently successful speedruns. Use `--help` for
input, repetitions, output retention and other options. Decoded frame hashes are
streamed, so verification does not accumulate raw video in memory.

## Comparing multiple replays (v4.08)

The first, positional replay is the primary. Add any number of secondaries:

```sh
python optimize_replay.py encode-video primary.txt --secondary-replay other.txt -o compare_start.mp4
python optimize_replay.py encode-video primary.txt --secondary-replay other.txt --secondary-replay third.txt --replay-alignment exit -o compare_exit.mp4
python optimize_replay.py encode-video primary.txt --secondary-replay other.txt --secondary-replay third.txt --secondary-color "#3568a8" --secondary-color "#689ec9" -o custom_colours.mp4
```

| Mode | Start offsets | Timeline end |
| --- | --- | --- |
| `start` (default) | All zero | Last replay's completion, death or input end |
| `exit` | Longest completion time minus each replay's completion time | All first completion ticks coincide |

For example, completed runs of 300, 360 and 330 ticks receive offsets of
60, 0 and 30 ticks in `exit` mode. At 40 Hz that is 1.5, 0 and 0.75 seconds.
The primary need not be the longest replay. Its world is held at its initial
state until its start, and its player is hidden until its first gameplay tick.
Other delayed players are likewise hidden until they start.

Exit alignment measures native completion, **not** declared replay length,
selected trailing frames or video duration. It includes the demo's final
neutral tick when that is the first tick that reaches the exit. Every replay
must complete with the selected inputs and simulation options; nonfinishers
produce a clear error before the encoder starts. Completion and death on the
same tick are accepted. Start mode also supports unsuccessful and partial runs.

The primary exclusively drives visible object/enemy movement, doors, ordinary gold,
object MovieClips, eye easing and particles, including player dust and death
effects. Secondary replays use independent native states on the same level to
recover their correct positions and animation history. Their objects, enemy
reactions and effects are never rendered or merged into the primary state.
A secondary can therefore pass through a visibly closed door, touch apparently
uncollected gold, or die from a hazard in a different visible position: the
visible world follows the primary, while that player's path follows its own
replay. Players do not interact with one another.

In start mode, finished players retain their last tracked pose while the
remaining replays continue. Dead players follow the existing hidden-sprite
behaviour. The primary's gameplay stops at its own completion/death/input end;
existing primary cosmetic clips can continue to age, without new emissions.
The terminal hold begins only after every replay ends, and is added if any
replay reached completion or death. All-empty inputs with `final_neutral=False`
produce one initial image. Rendered video frames are bounded in memory;
compact secondary pose records spill to temporary files rather than retaining
an entire Python pose trace.

The primary keeps its original colour and is drawn above the secondaries.
The first secondary defaults to darker blue `#3568a8`; further players use
`#689ec9`, `#c38d62`, `#86aa76`, `#ab88bf`, `#cc7e92`, `#68aeaa`, then the
palette repeats. To override, supply exactly one `#RRGGBB` colour per secondary
in replay order. All players retain their own pose, rotation, facing, visibility
and original antialiased limb coverage. Tiles and foreground particles cover
all players. Colours work with both vector artwork and legacy PNG packs.

File comparisons can mix combined demos, packed-only demos and LTMs. Combined
secondaries must contain exactly the same level string as the primary.
Packed-only secondaries and LTMs use the primary's level without another
database lookup; they do not themselves identify or validate their map, so
supply files recorded on that level. The primary uses the usual loader and
requires a level database if it is packed-only or an LTM. `--ltm-postroll N`
trims each LTM, is ignored for demo members of a mixed comparison, and is
rejected if no input is an LTM. Each demo can receive its own final neutral;
an LTM never receives a synthetic tick. All input paths and any primary level
database are protected against output aliases.

Both APIs preserve their primary argument and add comparison keywords:

```python
from nv14_video import encode_replay_data_video, encode_replay_video

result = encode_replay_data_video(
    level_data=level_string,
    replay_data=primary_replay_string,
    secondary_replays=[other_replay_string, third_replay_string],
    replay_alignment="exit",  # or "start"
    secondary_colors=["#3568a8", "#689ec9"],  # optional
    output_path="comparison.mp4",
)
for replay in result.replays:
    print(replay.index, replay.start_offset_ticks, replay.end_tick,
          replay.stop_reason)

result = encode_replay_video(
    "primary.txt", "comparison_start.mp4",
    secondary_replays=["other.txt", "third.ltm"],
    replay_alignment="start",
)
```

Each direct-data secondary accepts a packed string, `ComplexReplay` or sequence
of `InputFrame` records, just like the primary. Wrap one secondary in a list.
`None` or `[]` keeps the ordinary single-replay path. Secondary states share the
parsed immutable level but own their gameplay/animation state. With the v4.09
native extension, secondary poses are captured in batches of 512 and played
back from compact records. Exit alignment captures each secondary only once,
using that capture's completion tick. The primary still has a timing pass,
now using bounded native batches, before its world is simulated for rendering.
Older native extensions retain the original per-tick comparison path.
Comparison costs are confined to encoding; optimisation gains no work.

TOML arrays map to the repeatable options (CLI values append to configured
lists; scalar alignment overrides the configured value):

```toml
[encode-video]
secondary_replays = ["other.txt", "third.txt"]
replay_alignment = "exit"
secondary_colors = ["#3568a8", "#689ec9"]
```

See `examples/config/video-comparison.toml` for a complete example. For a custom
render loop, pass `secondary_players=[other_state.visual_snapshot(), ...]` to
`SceneRenderer.render()`. Each dictionary may add `color=(R, G, B)`; it defaults
to darker blue in the low-level renderer. `show_primary_player=False` hides only
the primary ninja. Rendering does not advance any state or animation.

## Player labels (v4.11)

Every run can have its own optional label, including a primary-only video.
Labels use the original embedded `n_uni05_53` / `uni 05_53` GUI font from the
supplied game assets. The primary label is black; each secondary label uses
that player's actual default or overridden RGB colour. A thin light outline
keeps text legible over terrain. The default font size is 8 game pixels;
`--label-size 12` gives larger text. Text scales crisply with `--scale`.

```sh
python optimize_replay.py encode-video primary.txt --primary-label "Optimised" --secondary-replay other.txt --secondary-label "Baseline" --secondary-replay third.txt --secondary-label "Alternative" -o labelled.mp4
```

By default, labels stay horizontal above the player's position, move on the same gameplay
ticks, and follow visibility and delayed starts. They disappear with a hidden
or dead ninja and remain during a visible completion pose/terminal hold. They
are overlaid above terrain and effects. Nearby captions stack vertically when
space permits, and captions are kept inside the picture. Very crowded scenes
can still overlap; use short names or leave selected captions empty.

Omitting label options preserves unlabelled rendering. If `secondary_labels`
is supplied, it must contain exactly one entry per secondary replay, in replay
order. Use `""` (CLI/TOML/API) or `None` (API) to hide an individual caption.
Text must be one printable line, at most 128 characters. Labels wider than the
picture are shortened with `...`. The original font supports Western Latin
text and punctuation; unsupported characters render as `?`.

Both file/data APIs and `VideoEncodeSession` accept:

```python
result = encode_replay_video(
    "primary.txt", "labelled.mp4",
    secondary_replays=["other.txt", "third.txt"],
    primary_label="Optimised",
    secondary_labels=["Baseline", ""],
    label_size=8,
)
print(result.replays[0].label)  # "Optimised"; unlabelled runs report None
```

```toml
[encode-video]
primary_label = "Optimised"
secondary_replays = ["other.txt", "third.txt"]
secondary_labels = ["Baseline", "Alternative"]
label_size = 8
```

CLI secondary labels append to TOML labels, matching the existing replay and
colour arrays. Primary label and size are scalar overrides. Low-level callers
pass `primary_label="...", label_size=8` to `SceneRenderer.render()` or
`render_into()` and put `"label": "..."` in each `secondary_players` dictionary.

The font is bundled at `nv14_assets/fonts/n_gui.ttf`; no system font install,
game installation or new dependency is needed. The original bundled font is
also used with a custom `assets_path`. It is loaded only when a visible label
is first rendered. Label images use a bounded cache and participate in dirty
region updates and serial/parallel rendering. Names and font size do not alter
simulation, completion timing or persistent secondary pose-cache keys.

### Static top-left labels (v4.12)

Add `--label-position top-left` to show all supplied labels as a fixed legend.
The primary label appears first, followed by non-empty secondary labels in
replay order. Each retains the original GUI font, player colour, light outline
and selected `--label-size`. The legend starts 32 game pixels from the top and
left edges, inside the level border, and scales with the video.

```sh
python optimize_replay.py encode-video primary.txt --primary-label "TAS" --secondary-replay other.txt --secondary-label "Baseline" --label-position top-left -o comparison.mp4
```

Static entries are present from the first frame, including players whose starts
are delayed by exit alignment. They remain after deaths, completion and during
terminal holds; player movement and visibility cannot shift the list. Blank
labels are omitted. A primary-only video supports the same option. The static
legend replaces following captions; it does not add a second set of labels.

Tall lists continue down the next column to the right. Names are shortened with
`...` if necessary to fit their column. If an unusually large list cannot fit
even abbreviated names, encoding reports an error; reduce the font size or
leave more labels empty. A primary plus 20 secondary labels fits in one column
at the default size.

Both APIs and session methods accept `label_position="top-left"`; the default
is `"follow"`. TOML uses the same scalar setting:

```toml
[encode-video]
primary_label = "TAS"
secondary_replays = ["other.txt"]
secondary_labels = ["Baseline"]
label_position = "top-left"
```

For low-level rendering, pass `label_position="top-left"` to `render()` or
`render_into()`. Include labelled secondary records even when they are hidden
(`visible=False`) so the renderer receives the complete legend. The encoder
handles this automatically for delayed starts. The composed legend is cached
and supports dirty-region rendering, multiple workers and reusable sessions.

## Timing and terminal behaviour

Simulation runs at **40 gameplay ticks per second**. The existing visual tracker
advances three nominal SWF timeline frames before each tick and performs one
player draw after it. The exported gameplay frames are post-tick snapshots;
there is no extra initial frame for nonempty simulations. This preserves the
player dump's tick order and final-neutral convention.

At 40 fps, each simulated tick produces exactly one video frame. Higher output
rates repeat the complete 40 Hz images, without interpolation or additional
animation updates. After T ticks the gameplay part contains `ceil(T*fps/40)`
frames. Its duration can therefore exceed T/40 by less than one video frame.
The terminal hold adds `ceil(terminal_hold_seconds*fps)` frames only when
the replay reaches death/completion. An empty replay with `final_neutral=False`
produces one image of the initial state and stops with `input_end`.

The first terminal tick is included. Gameplay is not advanced during the
hold, so it does not alter completion time, score or input data. Existing
particles and object clips advance by three SWF timeline frames per nominal
40 Hz tick, respecting their removal/stop/loop actions; higher output rates duplicate those images. No new
effects are emitted during the hold. Object positions, eyes and laser blast
scale stay frozen; existing clip artwork can continue playing. Disable both
`particles` and `object_animations` for a still hold. The renderer
selects celebration variant 1 if the current terminal tick needs a concrete
pose; this is a deterministic presentation choice, not Flash RNG reproduction.
On death the ordinary player sprite is hidden by the existing tracker. Ragdoll
limbs, continued falling after completion, and full celebration playback are
not implemented in v4.08. Without a terminal hold, effects spawned on the last
gameplay tick appear only in that tick's output image(s).

## Particles

The asset pack contains 28 original particle MovieClips, with all 413 timeline
frames before their `removeMovieClip()` actions. Registration points,
signed X/Y scales, rotation, morphing and fade artwork come from the supplied
SWF and `ParticleManager` code. Particles occupy the source front layer above
the player and below tiles. Gauss hairlines keep their vector endpoints and
frame colours so horizontal/vertical shots survive a zero scale.

| Effect | Trigger used by the renderer |
| --- | --- |
| Ground/wall jump dust | Successful native jump counter change; undo the immediate jump displacement to recover contact position |
| Landing, skidding, wallslide dust | Consecutive native player states, contact normals and velocity |
| Rocket smoke | Active rocket position/rotation with a shared emission counter |
| Mine/rocket explosions | Mine visibility loss or active-rocket disappearance; retained impact position |
| Laser charge motes | Prefire/firing updates |
| Chaingun muzzle flash, trail and impact debris | New native shot index and actual ray endpoint |
| Gauss trail and impact debris | Prefire expiry plus changed target or retained LOS reaching the prior player circle; cancelled LOS alone does not emit a shot |
| Electrical zaps and initial blood spurts | First death transition plus nearby enemy/impact evidence |

`particle_seed` controls a dedicated `random.Random`, not global or optimiser
randomness. The same replay, options and seed reproduce the same cosmetic
sequence. Scene queries do not capture Flash's RNG, MovieClip depth history or
wall-clock draw scheduling, so this is not a bit-exact Flash reconstruction.

The renderer starts the shared emission counter at zero and applies the
source's per-effect rates and modulo reductions to give dust/smoke/charge a
defined cadence. The source's referenced
`debugBloodSpurtMC1` linkage is absent from the SWF, so initial blood spurts use
the available `debugBloodSpurtMC2` clip. Uncalled `SpawnLaserSpark` and
`SpawnRocketDeath` helpers do not cause invented effects.

Spawns are reconstructed from snapshots rather than an in-tick event log.
Rare multiple transitions within one tick, object update ordering and
simultaneous death causes can make effect timing, order or contact placement
approximate. The native engine has no retained killer/contact record; death
spurt position/direction uses nearby evidence or the player centre. Ragdoll
collision dust, repeated electrocution and continuing blood from severed
limbs are not implemented because ragdoll physics is not implemented.

For uncompressed frames or a custom render loop:

```python
from nv14_particles import ParticleSystem
from nv14_render import SceneRenderer

renderer = SceneRenderer(level_string)
effects = ParticleSystem(renderer.manifest, seed=0)
state = native_level.initial_state(track_visuals=True)
effects.reset(state.scene_snapshot())  # prime before the first gameplay tick
for frame in replay_frames:
    event = state.step(frame)
    scene = state.scene_snapshot()
    image = renderer.render(scene, particles=effects.update(scene, frame))
    # save/use image here
    if event["dead"] or event["level_complete"]:
        break
```

`SceneRenderer.render()` is still stateless with respect to particles. Repeated
renders cannot spawn or age them. `ParticleSystem.update()` accepts adjacent
scene frames and treats a repeated frame as a no-op. Use `reset(scene)` after
seeking or when starting another replay; it discards prior effects and resets
the cosmetic seed. `advance(n)` ages existing clips by n SWF frames without
gameplay or new emissions. Omit `particles=` when rendering an isolated scene.
Custom v4.04 asset packs work with `--no-particles --no-object-animations`;
enabling particles requires
the v4.05 particle manifest and frames, otherwise export fails clearly.

## Object animations and eyes

The separate `nv14_object_visuals.ObjectVisualSystem` tracks original frame
labels, stop/play/jump/visibility actions, and sprite positions. It implements:

- Gold collection and its delayed visibility action; opening exit artwork.
- Regular, locked and trap door transitions, switch states and launch activation.
- Gauss prefire/idle body playback and original far/mid/near/prefire/postfire
  crosshair artwork. The source immediately overwrites its firing body label
  with idle; the tracker preserves that ordering.
- Rocket launcher fire/explosion reactions and the rocket's independent loop.
- Zap drone chase pulses, laser prefire/firing/postfire, chaingun prefire/fire/
  postfire, and the laser's animated, expanding endpoint blast.
- Original drone eye easing: normal Draw adds 30% of the literal angular
  difference; chaingun prefire adds 10% toward the aim, and shots explicitly
  assign the shot direction. No shortest-angle wrapping is introduced.
- The original frozen displayed drone/crosshair positions while Draw is
  disabled during weapon cycles, plus the correct prefire/firing laser beam.

All 14 packaged object clips (303 frames) retain their source frame actions,
labels, registration and scale. Static shapes such as bounce blocks and thwumps
continue to use their existing source artwork and native positions/states.

For a custom render loop, prime both trackers before stepping:

```python
from nv14_object_visuals import ObjectVisualSystem
from nv14_particles import ParticleSystem
from nv14_render import SceneRenderer

renderer = SceneRenderer(level_string)
objects = ObjectVisualSystem(renderer.manifest)
effects = ParticleSystem(renderer.manifest, seed=0)
state = native_level.initial_state(track_visuals=True, visual_timeline_frames=3)
scene = state.scene_snapshot(include_object_visuals=True)
objects.reset(scene)
effects.reset(scene)
for frame in replay_frames:
    event = state.step(frame)
    scene = state.scene_snapshot(include_object_visuals=True)
    image = renderer.render(scene, particles=effects.update(scene, frame),
                            object_visuals=objects.update(scene, frame))
    if event["dead"] or event["level_complete"]:
        break
```

Rendering remains stateless: duplicate renders do not advance clips or ease
eyes. `ObjectVisualSystem.update()` requires adjacent snapshots; duplicate
frames are no-ops. Reset after seeking. A reset at an arbitrary mid-replay
snapshot cannot recover prior cosmetic timeline/eye history. `advance(n)` runs
only existing clips for n SWF frames and does not perform gameplay/eye updates.
An isolated `renderer.render(scene)` still uses the simpler snapshot artwork.

## Visual scope and accuracy

This is not a pixel-exact replacement for Flash. It uses the native engine's
actual positions and gameplay state, source timeline actions, and extracted
artwork. Terrain includes curved/half tiles and the outer border; tiles are
composited above objects/player following the source display layers.

Object triggers are reconstructed from consecutive snapshots. The optional
`door_timer` query resolves same-tick regular-door reopening, but rare overlapping
launch/bounce/thwump contacts can hide intermediate launch activation history.
There is no in-tick cosmetic event log. Seeking and disabled enemy simulation
cannot reproduce missing history. Particle randomness and death limitations
remain as described above.

Sound, menus, the original HUD, ragdolls, continued terminal gameplay and full
celebration playback are omitted. Higher fps duplicates complete 40 Hz frames;
it does not reconstruct Flash's independent 120 Hz playback or interpolate
motion. Rasterisation, antialiasing, alpha composition and H.264 compression /
chroma subsampling can still differ from Flash. The v4.07 outline correction was
checked against the supplied game screenshot and original SWF paths, including
the original dark one-pixel platform edge and bounce-block border. This is not
a frame-synchronised Flash/libTAS comparison of an entire replay.

## Assets and development

See `nv14_assets/README.md` and `manifest.json` for provenance, registration
points, extraction settings and the exact SWF hash. `tools/extract_video_assets.py`
documents regeneration of the base artwork; run
`python -m tools.extract_particle_assets` afterwards for particles, then
`python -m tools.extract_object_animation_assets` for object clips, and finally
`python -m tools.extract_vector_assets` for final-scale outlines. Extraction
tools are development dependencies only. No unsuccessful planner module, planner test or planner
configuration from v3.38 is included.

Native scene accessors have their own ABI (`scene_abi=1` in `backend_info()`).
They leave the existing gameplay and player-dump ABIs unchanged. Object-animated
exports require `backend_info()["object_visual_queries"]` from the v4.06
extension; build once with `python build_native.py`. The default scene dictionary
is unchanged. Only `scene_snapshot(include_object_visuals=True)` adds the door
timer. Older scene-capable extensions and base packs can still be used with
object animations disabled (and particles disabled for packs predating v4.05).
After modifying the Cython wrapper, regenerate `native/_nv14_native.c` before
distribution; the generated file is included in this release.


## Ghost gold (v4.13)

`--secondary-gold static` or `--secondary-gold animated` leaves a visual copy
of each piece collected by the primary while at least one secondary still
needs it. The default `off` preserves the existing comparison appearance.

```sh
python optimize_replay.py encode-video primary.txt --secondary-replay first.txt --secondary-replay second.txt --secondary-gold static -o comparison.mp4
python optimize_replay.py encode-video primary.txt --secondary-replay first.txt --secondary-replay second.txt --secondary-gold animated --replay-alignment exit -o finish.mp4
```

Both `encode_replay_video()` and `encode_replay_data_video()`, including their
`VideoEncodeSession` wrappers, accept `secondary_gold="static"` or
`secondary_gold="animated"`. TOML uses `secondary_gold = "animated"` under
`[encode-video]`. Rebuild the native extension with `python build_native.py`.
The generated C is included; Cython is not required to build the release.
No additional game assets are needed.

### Colour ownership and timing

- One idle gold marker is drawn per original gold object, regardless of how
  many ghosts still need it. It shows the colour of the **first pending ghost
  in CLI/API input order**, using the normal/custom secondary player palette.
- When that ghost collects it, the marker immediately switches to the next
  pending ghost's colour. It disappears when none remain. A later ghost which
  has already collected it is skipped, including same-tick pickups.
- A hidden owner's pickup does not change the marker or start an animation.
  If several ghosts collect on the same tick, only the owner visible before
  that tick gets an animation. Colour priority is not based on finish time.
- Ghosts which collected before or on the same video tick as the primary never
  get a duplicate. All comparisons apply replay start offsets, including exit
  alignment. Capture running ahead or loading a cache cannot expose future events.
- A delayed ghost is still a pending owner before its start. Gold never picked
  up by a stopped, dead or completed ghost stays in that ghost's ownership
  through the end of the video. Gold not collected by the primary remains normal.
- Object identities, not coordinates, distinguish colocated gold. Events come
  from the engine's actual collection masks, respecting collision traversal,
  jump timing, explicit triggers and the final neutral/terminal tick.

### Animation and performance

Since v4.14, ghost gold preserves the original artwork's dark border, inset
shading and bright highlight instead of becoming a flat silhouette. The ghost
colour anchors the centre tone; darker source pixels shade towards black and
lighter pixels towards white. Transparency and geometry are preserved. Both
idle pieces and collection animation frames use this treatment, including the
bitmap fallback. This is automatic for `static` and `animated`; no new option
is needed. Recoloured artwork uses bounded sprite caches and small shared colour
lookup tables. v4.15 also shares the original luminance and alpha raster across
colours, including animated frames and exact subpixel phases. The v4.13 physics
extension and replay-event caches remain reusable. Rebuild the native extensions
with `python build_native.py` to enable the new gold compositor; an older or
missing render extension falls back to Pillow.

`static` removes the outgoing owner's copy instantly. `animated` plays the
original `COLLECTED` gold MovieClip in that owner's colour, then hides it;
remaining idle gold is drawn above the effect so its new colour is visible
immediately. Three SWF frames advance per simulation tick; the bundled tween
hides after ten ticks (0.25 seconds). Effects continue after the primary/ghost
stops and during terminal holds, including output rates above 40 FPS.

Duplicate animation is independent of `particles` and `object_animations`:
`--secondary-gold animated --no-particles --no-object-animations` still animates
these copies. This effect uses a gold object clip, not a separate ghost particle
system. Gameplay, score, enemies and the primary world remain authoritative.

Native capture records sparse `(pickup_tick, gold_index)` events during the
existing secondary simulation pass. Gold-mask differences are examined only
on pickup ticks; there is no per-ghost scene snapshot or second simulation.
The event cache is versioned, validated and keyed separately from pose-only
tracks, with both `static` and `animated` sharing the same event data. Old cache
entries are regenerated as needed. Binary events occupy 16 bytes each, at most
one per gold object per secondary; Python playback metadata has additional overhead.

Idle rows are updated only for gold whose visible owner changes; unchanged rows
retain their identity, and a new immutable tuple is formed only when necessary.
Animation actions are compiled once into a bounded frame schedule, including
custom holds, jumps and visibility changes. Unusual timelines use the original
interpreter fallback. Stable draw keys support incremental redraws.
The active marker count depends on gold count, not ghosts times gold count.
Only live collection clips are advanced. Multiple render workers receive
immutable snapshots and produce the same frames as serial rendering.

The optional native compositor batches sufficiently large, dense, consecutive
groups of gold commands into bounded RGB patches. It uses the same integer
alpha rounding as Pillow and preserves each sprite's paint order. Small, sparse
or unsupported groups keep direct Pillow drawing, avoiding unnecessary patch
copies. These optimisations preserve the existing shaded appearance and require
no new CLI or API options.

`off` allocates no gold tracker or event buffers. With no secondaries, or no gold
in the level, the option has no visible effect. For large comparisons, `static`
is the cheaper mode; animated pickups also add changing pixels and short-lived
clips. Use `--profile` to measure the actual scene, scale and worker configuration.
