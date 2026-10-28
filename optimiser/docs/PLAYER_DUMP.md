# Player CSV dump (v4.03)

`dump-player` runs a supplied replay through the native C engine and writes
player physics and visual state to a CSV file. It accepts combined level/demo
text, packed-only demo text with a level database, and libTAS `.ltm` movies.
The `dump_player_data_csv()` API added in v4.02 accepts level and replay data
already in memory. Both interfaces share the same native capture and CSV
writer. They do not run an optimisation search.
v4.03 adds ordered CSV field selection to both Python export APIs.

## Build and use

A working v4.01 or v4.02 extension can be reused with the same platform and Python
version; v4.03 changes no native sources or ABIs. For a fresh installation or
an older extension, build from this release:

```sh
python build_native.py
```

Use `python3` in place of `python` if that is your Python 3 executable. The
generated C source is included; Cython and the original SWF are not needed to
build or run the release. A v4.00 binary must be rebuilt for the capture API.

For a combined `$name#author##level#replay#` demo text file:

```sh
python optimize_replay.py dump-player replay.txt -o player.csv
```

For an LTM, supply the matching level database if it is not in a standard
location already searched by the optimiser:

```sh
python optimize_replay.py dump-player "00-0.ltm" --levels-file "N v1.4 + NReality levels.txt" -o "00-0.csv"
```

The level ID is inferred from a filename beginning with an ID such as `00-0`.
Use `--level-id` when the filename does not identify the level:

```sh
python optimize_replay.py dump-player movie.ltm --level-id 00-0 --levels-file levels.txt -o player.csv
```

Packed-only demo text has the form `<ticks>:<word>|<word>|...`. It uses the same
level lookup as LTM input:

```sh
python optimize_replay.py dump-player demo.txt --level-id 00-0 --levels-file levels.txt -o player.csv
```

Database records use the optimiser's existing `$00-0 Name#author##level#` format.
Combined demo files already embed their level; `--levels-file` and `--level-id`
are rejected for those inputs to avoid an ambiguous level selection.

Without `-o`, output is `<input stem>.player.csv` beside the input file.
An explicitly supplied destination must end in `.csv`. Input files and level
databases cannot be overwritten, including through symlinks or hard links.
An existing CSV is replaced only after the complete export succeeds. Errors
and Ctrl+C leave it intact and remove the temporary output.

## Which frames are exported?

- One row represents the state **after** applying one gameplay input tick.
  `frame=0` is the first input; `elapsed_ticks=1` is the resulting engine clock.
  There is no initial, pre-input row. Positions and velocities therefore align
  with the optimiser's existing post-tick trace convention.
- Capture includes the first completion or death tick, then stops. Remaining
  recorded inputs are not exported as repeated frozen states. An unfinished
  replay stops at input end and still produces a valid CSV.
- Demo text gets one neutral tick after its declared inputs by default, matching
  the final-neutral convention used to verify N demos. That row, when reached,
  has `input_kind=final_neutral`. Use `--no-final-neutral` to export only declared
  inputs. No extra tick is added after an earlier completion/death.
- LTM replay frame zero is the input row immediately after the first Space
  press, following the existing importer. Only the active top-level `inputs`
  member is used. Menu/startup rows, alternate input branches and old
  `nv14_optimizer.json` metadata do not supply gameplay or level data.
- LTM trailing neutral inputs are **retained by default**. Capture consumes
  recorded inputs through the first terminal state or the end of the movie.
  `--ltm-postroll N` explicitly excludes the last N recorded rows from the replay
  range. LTM input never receives a synthetic final neutral tick.
- `ltm_frame` is the **zero-based** index of the original active movie input
  row. It is blank for text demos. `input_kind` is `ltm`, `demo` or
  `final_neutral`.

Stored jump-trigger bits in demo text are preserved, even when they differ
from the edges of the held jump button. LTM triggers are derived from its held
keys, with jump initially released at the replay boundary. Both input methods
retain jump and animation history across capture chunks.

The command prints the row count and whether it stopped on completion, death
or input end. Both `dead` and `complete` columns remain available if both flags
are set on the same tick; the summary then reports `stop=complete`.

## CSV schema

The first line is a header. The file uses UTF-8, comma separators and LF line
endings. Boolean values are `0`/`1`. Floating-point values retain Python's
round-trip representation of native doubles; they are not rounded for display.
Unknown/inapplicable animation frame fields are empty rather than zero.

The following table gives all 43 available columns, in their default output
order. The Python APIs accept `fields` to select a subset or change that order.

| Columns | Meaning |
| --- | --- |
| `frame`, `elapsed_ticks` | Zero-based applied input index; engine ticks after that input. |
| `input_left`, `input_right`, `jump_held`, `jump_trigger` | Controls used for this tick; trigger resolved to 0/1. |
| `x`, `y` | Post-tick player physics position, in pixels; positive Y points down. |
| `vx`, `vy` | Post-tick physics velocity, in pixels per gameplay tick, defined as `pos - oldpos`. |
| `old_x`, `old_y` | Native Verlet previous-position values. Collisions and impulses can modify these; velocity is not necessarily the difference between consecutive CSV positions. |
| `player_state`, `player_state_name` | Native state number and name: 0 STANDING, 1 RUNNING, 2 SKIDDING, 3 JUMPING, 4 FALLING, 5 WALLSLIDING, 6 RAGDOLL, 7 CELEBRATING. |
| `in_air`, `near_wall` | Native post-tick contact flags. |
| `floor_nx`, `floor_ny`, `wall_nx`, `wall_ny` | Native floor and wall contact normals. |
| `jump_timer` | Current native jump-timer value. |
| `jumped`, `jump_callable`, `jump_events` | Successful jump this tick; native jump-opportunity flag for this tick; cumulative successful jumps. |
| `dead`, `complete` | Native terminal flags after the tick. |
| `gold_collected`, `gold_bonus_ticks` | Cumulative collected gold and associated bonus ticks (80 per gold). |
| `facing`, `rotation_deg` | Sprite facing (-1 left, +1 right); body rotation in degrees. |
| `animation`, `animation_frame`, `animation_playing` | Selected SWF animation label; absolute one-based MovieClip frame; playback flag. |
| `previous_animation_frame` | Tracker's saved previous frame used by the ActionScript animation rules. This is not simply the preceding CSV row's frame. |
| `run_animation_frame`, `run_animation_remainder` | Persistent running-frame state (blank before initialisation) and fractional running progress. |
| `render_mode` | Active native counterpart of the player's ActionScript renderer. |
| `sprite_x`, `sprite_y` | Last drawn continuous normal-sprite position; may differ from physics position on a terminal tick. |
| `sprite_visible`, `visual_terminal` | Whether the normal sprite is visible; whether automatic visual tracking has reached a terminal state. |
| `ltm_frame`, `input_kind` | Original movie input index where available; source/tick classification. |

On death, use `dead` and the visual fields to identify the terminal state.
The native engine can retain a pre-death `player_state` while the visual
tracker reports `animation=RAGDOLL`. The numeric state is exported as recorded;
it is not rewritten to agree with an inferred animation label.

## Selecting CSV fields (v4.03)

Both Python export APIs accept `fields`, an optional ordered sequence of column
names. The sequence determines the header and the values included in every row:

```python
from nv14_dump import dump_player_data_csv, dump_player_csv

fields = ["frame", "x", "y", "vx", "vy", "facing", "animation_frame"]
result = dump_player_data_csv(
    level_data=level_string,
    replay_data=replay_string,
    output_path="player.csv",
    simulate_enemies=True,
    fields=fields,
)

# The same parameter is available when loading a demo or LTM file.
result = dump_player_csv("replay.txt", "selected.csv", fields=fields)
```

- Omit the parameter or pass `fields=None` to write all 43 columns in their
  original order. Passing all column names explicitly also works.
- A nonempty list or tuple is accepted. Names must exactly match the schema
  above, including case. Unknown names, duplicates and empty selections raise
  `ValueError`; a bare string, unordered collection or non-string name raises
  `TypeError`. Validation happens before native level creation or CSV writing.
- Any available field can be selected, including `ltm_frame` and `input_kind`.
  For example, `fields=["input_kind", "frame", "x"]` writes those three columns
  in that order. A single field produces a valid single-column CSV.
- Field selection affects output only. Row counts, terminal stopping,
  final-neutral handling and `PlayerDumpResult` use the complete captured
  state even if `frame`, `dead`, `complete` or `input_kind` is omitted.
- Native capture, visual calculations and native-to-Python tuple conversion
  still process the full state. Selection reduces CSV formatting and output
  size; it does not switch off unselected simulation/animation calculations.

Column selection is available through the Python APIs. The `dump-player`
command uses the default full schema.

## Options and visual timing

| Option | Default | Effect |
| --- | --- | --- |
| `-o`, `--output` | `<input stem>.player.csv` | CSV destination. |
| `--levels-file` | Existing database discovery | Level database for LTM or packed-only text. |
| `--level-id` | Filename inference | Select a database level. |
| `--ltm-postroll N` | 0 | Explicit number of recorded trailing LTM rows to exclude. |
| `--final-neutral` / `--no-final-neutral` | Enabled | Append a labelled neutral tick to demo text only. |
| `--simulate-enemies` / `--no-simulate-enemies` | Enabled | Run supported native enemies. Disabling this changes the simulated replay. |
| `--visual-timeline-frames N` | 3 | MovieClip advances before each gameplay tick. |
| `--celebration-variant N` | 0 | 0 leaves the random choice unresolved; 1..9 supplies a specific celebration. |
| `--config FILE` | None | TOML defaults; explicit command-line options take precedence. |

The tracker uses v4.00's nominal clock: three MovieClip advances, then one
gameplay tick, then a draw. This models the supplied SWF's 120 fps timeline
against N's 40 Hz gameplay clock. `--visual-timeline-frames 0` disables automatic
timeline advancement while retaining gameplay-triggered animation changes and
draws. The constant is not inferred from the LTM's movie framerate: one imported
input row remains one gameplay tick under the optimiser's established mapping.

Replay controls do not record the exact Flash draw/timeline schedule, and the
tracker does not reproduce Flash's random-number state. Consequently, these
visual fields describe the native tracker under the selected clock convention.
They are not a claim of frame-exact matching to a separately captured Flash
display. A default random celebration is `CELEBRATE_UNRESOLVED` with a blank
frame; a supplied variant selects its known SWF frame when the game chooses
a celebration. Airborne completion can retain its earlier animation.

Ragdoll limbs and post-completion animation are not simulated. On death, the
normal sprite is hidden and its frame becomes blank; its retained sprite
coordinates are not ragdoll positions. See [the visual-state API and source
tables](NATIVE_VISUAL_STATE.md) for the full tracking contract. No additional
SWF data is needed for the implemented exporter.

TOML example (`[dump_player]` is also accepted):

```toml
[dump-player]
final_neutral = false
simulate_enemies = true
visual_timeline_frames = 3
celebration_variant = 0
```

```sh
python optimize_replay.py dump-player replay.txt --config dump.toml -o player.csv
```

## Direct level and replay data (v4.02)

Use this entry point when your batch script already has the level and replay
fields, for example after reading a YAML or JSONL corpus:

```python
from nv14_dump import dump_player_data_csv

result = dump_player_data_csv(
    level_data=level_string,
    replay_data=replay_string,
    output_path="00-0_highscore.csv",
    simulate_enemies=True,
)
print(result.output_path, result.rows, result.stop_reason)
```

| Argument | Accepted data |
| --- | --- |
| `level_data` | Raw engine level string: the 713-character tile map followed by `\|` and object data. Also accepts an already parsed `NativeLevel`. This argument contains data, not a filename, database record or combined level/demo record. |
| `replay_data` | A packed `<ticks>:<word>\|<word>...` replay string, a `ComplexReplay` from `nv14_replay`, or a list/tuple/other sequence of `InputFrame` objects. Packed trigger bits are preserved; `InputFrame.jump_trigger=None` derives edges in the engine. Byte strings and unsized iterators are not accepted. |
| `output_path` | Required CSV destination, as a string, `Path` or other string-valued path-like object. Parent directories are created if needed. |

The optional keyword arguments are `simulate_enemies=True`,
`final_neutral=True`, `visual_timeline_frames=3`, `celebration_variant=0`,
`chunk_size=4096` (1..65536) and `fields=None`. They have the same meanings as
for the file exporter. The default output uses the full 43-column schema;
`fields` selects and orders columns. The source values are `input_kind=demo`
and an empty `ltm_frame`. The appended neutral row, if reached, is labelled
`final_neutral`. Set `final_neutral=False` when supplying an input sequence
that already contains the required final neutral tick. Use the file interface
for automatic LTM provenance and post-roll handling.

The return value is the existing immutable `PlayerDumpResult`:

| Field | Meaning |
| --- | --- |
| `output_path` | Destination as a `Path`. |
| `rows` | Number of CSV data rows written, excluding the header. |
| `source_frames` | Number of supplied/declared input frames before adding a neutral tick; includes inputs after any earlier terminal frame. |
| `stop_reason` | `complete`, `dead` or `end_of_input`. Completion takes priority in this label if both terminal flags are set. |
| `final_neutral_written` | Whether the synthetic neutral tick was actually captured and written. |
| `dead`, `complete` | Separate terminal flags after the final captured tick. |

An unfinished replay is a successful export with `stop_reason=end_of_input`.
Empty replay data writes one neutral row by default, or just the header with
`final_neutral=False`. Bad input raises `TypeError`/`ValueError`, unavailable or
unsupported native execution raises `RuntimeError`/`NotImplementedError`, and
I/O errors raise `OSError`. Existing CSVs are replaced only on successful export;
failed or interrupted output is discarded. The API returns without printing.

For batch processing, call it repeatedly with distinct output paths:

```python
from pathlib import Path
from nv14_dump import dump_player_data_csv

# jobs yields (job_id, level_string, replay_string) from your existing loader.
for job_id, level_string, replay_string in jobs:
    result = dump_player_data_csv(
        level_string, replay_string, Path("dumps") / f"{job_id}.csv",
        simulate_enemies=True,
    )
    print(job_id, result.rows, result.stop_reason)
```

For several replays of the same level, parse the native level once and reuse it:

```python
from pathlib import Path
from nv14_dump import dump_player_data_csv
from nv14_native import require_native

level = require_native().parse_level_string(level_string, simulate_enemies=True)
for job_id, replay_string in replays_for_this_level:
    result = dump_player_data_csv(
        level, replay_string, Path("dumps") / f"{job_id}.csv",
        simulate_enemies=True,
    )
```

Every call creates a fresh state: player, enemies, collected gold, jump history
and animation history start from the level's initial conditions. The supplied
native level and decoded input records are not modified. A native level's
`simulate_enemies` setting must match the argument; a mismatch raises
`ValueError`. Callers control level reuse without a growing global cache.

Simulation, animation and capture still run in C, with the GIL released for
each chunk. Python handles decoding, argument validation and CSV formatting.
Packed inputs are decoded in memory; decoded sequences are reused without
copying the entire sequence. Capture buffers remain bounded by `chunk_size`.

## File-based and lower-level interfaces

For repeated exports in one Python process:

```python
from pathlib import Path
from nv14_dump import dump_player_csv

for source in sorted(Path("replays").glob("*.txt")):
    result = dump_player_csv(source, Path("csv") / (source.stem + ".csv"))
    print(source.name, result.rows, result.stop_reason)
```

`dump_player_csv` exposes the CLI settings as keyword arguments plus
`chunk_size` (default 4096; 1..65536) and `fields` (default `None`, all columns).
It returns a `PlayerDumpResult` with the
destination, row count, declared/selected source-frame count, stop reason,
final-neutral-written flag and terminal flags. `load_player_dump_source`
exposes the input loader without running a simulation.

For an already parsed native level:

```python
from nv14_native import require_native

native = require_native()
state = native.parse_level_string(level_string, simulate_enemies=True).initial_state(
    track_visuals=True
)
columns = native.PLAYER_DUMP_COLUMNS
rows = state.capture_player_frames(input_chunk)
# Each row is a tuple in columns order. Repeat on the same state for the next chunk.
```

The C API in `native/nv14_dump.h` exposes `nv14_player_dump_capture` and a
caller-owned `nv14_player_dump_row` buffer. The loop runs physics, animation
and snapshot capture entirely in C; the wrapper releases the GIL for the whole
chunk. No Python callback or dictionary is created inside that loop. The
wrapper then converts captured rows to tuples and the Python CSV writer writes
them. Source parsing still uses memory proportional to the input size, while
capture/CSV buffers are bounded by the chunk size.

Tracking must be enabled on a fresh state. Capture does not turn it on itself,
add neutral inputs, or advance past a terminal tick. A terminal state returns
zero rows on subsequent calls. Invalid C buffer arguments are rejected before
stepping; a native runtime error reports the successfully captured count via
`written_out` and can leave the state advanced. The Python CSV interface
discards partial output on any error.

`backend_info()["player_dump_abi"]` is 1. Existing core, visual and trace ABIs
are unchanged. Ordinary optimisation never invokes this capture API and still
keeps the optional visual tracker disabled.
