# Native player visual state (v4.00+, updated for v4.01)

The v4.00 release added the optional native visual tracker proposed as step 1 of
the replay-dump feature, based on the supplied v3.21 source. v4.01 adds the
[`dump-player` CSV interface](PLAYER_DUMP.md) and native chunk capture.
No later route planner has been introduced. The visual rules and API below
are unchanged.

## Use

Rebuild with `python3 build_native.py`, or `python build_native.py` on Windows.
The release includes regenerated `native/_nv14_native.c`; building does not
require Cython or the original SWF.

```python
from pathlib import Path
from nv14_native import require_native
from nv14_replay import parse_combined_level_replay, decode_complex_replay

record = parse_combined_level_replay(Path("replay.txt").read_text(encoding="utf-8"))
replay = decode_complex_replay(record.replay_string)
native = require_native()
level = native.parse_level_string(record.level_string, simulate_enemies=True)
state = level.initial_state(track_visuals=True)

print(state.visual_snapshot())  # Initial STAND, frame 1, facing right.
for frame in replay.frames:
    event = state.step(frame)
    physics = state.player_snapshot()
    visual = state.visual_snapshot()
    # For a CSV export, use dump-player or state.capture_player_frames().
    if event["dead"] or event["level_complete"]:
        break
```

This example runs only the supplied input list; it does not append the replay
evaluator's final neutral sentinel. Input-boundary policy remains with the
caller, as it does for existing native stepping. A dump command can add and
label that neutral input when it is implemented.

For batches, `state.step_many(frames)` performs all physics and visual updates
in C while the GIL is released. Its final `state` dictionary includes `visual`
only when tracking is enabled. `level.simulate()` and
`nv14_native.simulate_batch()` also accept `track_visuals=True`.

## Opt-in API

```python
state = level.initial_state(
    track_visuals=True,
    visual_timeline_frames=3,
    visual_auto_draw=True,
    celebration_variant=0,
)

# Equivalent opt-in before the first step:
state = level.initial_state()
state.enable_visuals(timeline_frames=3, auto_draw=True, celebration_variant=0)

assert state.visuals_enabled
copy = state.clone()       # Preserves independent animation history and options.
visual = state.visual_snapshot()
state.disable_visuals()   # Frees the tracker; physics is untouched.
assert state.visual_snapshot() is None
```

Enabling requires a fresh, unstepped player. Repeated enable and enable after
stepping raise an error: reconstructing animation history from a late physics
snapshot would be unreliable. Re-simulate from the beginning instead.
Disabling is idempotent. Python snapshot shapes are unchanged while disabled.

The C API is in `native/nv14_visual.h` and has its own visual ABI version (1).
Existing public gameplay snapshot layouts, core ABI and route-trace ABI remain
unchanged. The opaque native state owns an optional heap-allocated tracker.
Cloning and `nv14_state_copy_into()` preserve it; copies into existing tracked
states reuse the allocation. Copying an untracked state into a tracked state
removes the destination tracker. Direct player-snapshot replacement is rejected
while a tracker is attached, to prevent stale animation history.

Ordinary optimisation never enables tracking. The disabled path has null-pointer
checks but performs no animation arithmetic, sprite-frame progression, animation
allocations, or animation copying. Visual state is excluded from gameplay keys,
search ranking and replay trace tuples. Equal gameplay keys need not have equal
visual histories. The search-only alternate-input shortcut declines tracked
states because its result contains only a gameplay player snapshot.

## Snapshot fields

| Field | Meaning |
| --- | --- |
| `x`, `y` | Last drawn sprite position, kept in continuous game coordinates. |
| `facing` | `1` right, `-1` left. Zero horizontal velocity retains the direction. |
| `rotation_deg` | Signed body rotation in degrees, including slope alignment and airborne relaxation. |
| `animation` | SWF label containing the selected frame, or an explicit terminal/unresolved label. |
| `frame` | One-based SWF frame number; `None` for ragdoll/unresolved celebration. |
| `previous_frame` | `Draw_Normal`'s `prevframe`, captured before `Render` selects a pose. |
| `playing` | MovieClip timeline playback flag. A stopped clip can still change pose through Render. |
| `run_frame` | Persistent `runanimcurframe`; initially `None`, retained across run re-entry. |
| `run_remainder` | Fractional `runanimleftovers`, reset on entry to running. |
| `render_mode` | `static_ground`, `run`, `in_air`, `wallslide`, or `ragdoll`. |
| `visible` | Whether the normal ninja sprite is visible. |
| `terminal` | Native simulation has reached death or completion. |

Movement state is still `state.player_snapshot()["state"]`. It is deliberately
separate from animation. A falling player uses the JUMP frame range, and entering
CELEBRATING does not itself select an animation or change the Render method.

## Timing

The supplied SWF declares **120 MovieClip frames/second**. Its ActionScript uses
`APP_GAMETIME_TICKLEN = 25` ms, or **40 gameplay ticks/second** at normal speed.
The app can execute multiple gameplay ticks before one draw. Idle and celebration
playback also advances independently of gameplay; a replay's input sequence does
not encode the actual wall-clock/render schedule.

The default tracker provides a deterministic **nominal schedule**:

1. Advance a playing MovieClip by three frames before each gameplay tick.
2. Execute the existing object updates, player physics, collisions and Think.
3. Apply one player draw after the tick, then expose the visual snapshot.

The initial snapshot is immediately after player initialisation: STAND frame 1,
playing, facing right, rotation zero. On an undisturbed flat floor the default
idle frames are consequently 4, 7, 10, 11, 11, ... . The stop action on frame 11
halts playback. Running and airborne poses are explicitly selected by the player
logic rather than automatically advanced on the MovieClip timeline.

This convention is not a claim that every live Flash playback has the same
render schedule. For comparison with a recorded Flash/libTAS schedule, disable
the automatic clock and draw, then issue them at the recorded points:

```python
state = level.initial_state(
    track_visuals=True, visual_timeline_frames=0, visual_auto_draw=False,
)
state.advance_visual_timeline(3)  # Only the MovieClip clock.
state.step(input_frame)          # Think and state transitions, without a draw.
state.draw_visual()              # Only Draw_Normal/Render; no physics or clock.
```

Multiple Think calls without a draw intentionally use the same displayed
MovieClip frame in `AdvanceRunAnim`, matching the source. Draw captures
`previous_frame` before changing the displayed pose. Run entry resets its
remainder but preserves a previously assigned `runanimcurframe`; the first-ever
run has no previous run frame and retains the frame selected by `Run()`.

## Source data and animation rules

The data was read from DefineSprite **898**, exported as **testNinjaMCm**, in
the supplied `n_v14.swf` (797 frames, SWF version 6).

SWF SHA-256:
`9db8e7b1e2d15dfa3e378690dd35c17b3818a0cc85dc46e2ae0e9ef4d93b18c1`

| Label | First frame | Stop action |
| --- | ---: | ---: |
| STAND | 1 | 11 |
| SKID | 12 | Selected with gotoAndStop |
| RUN | 13 | Selected with gotoAndStop |
| JUMP | 85 | Selected with gotoAndStop |
| WALLSLIDE | 104 | Selected with gotoAndStop |
| CELEBRATE_OLD | 105 | Not selected by ThinkCelebrate |
| CELEBRATE_NEW1 | 106 | 166 |
| CELEBRATE_NEW2 | 167 | 233 |
| CELEBRATE_NEW3 | 234 | 312 |
| CELEBRATE_NEW4 | 313 | 354 |
| CELEBRATE_NEW5 | 355 | 448 |
| CELEBRATE_NEW6 | 449 | 506 |
| CELEBRATE_NEW7 | 507 | 658 |
| CELEBRATE_NEW8 | 659 | 743 |
| CELEBRATE_NEW9 | 744 | 797 |

`PlayerObject.Think`, state-entry methods, `AdvanceRunAnim`, `Draw_Normal`,
`RenderRun`, `RenderInAir`, `RenderStatic_Ground` and `RenderWallSlide` supply the
update rules. In the supplied `n14.zip` export these are in root frame 1's
`DoAction_85.as`, `DoAction_86.as` and `DoAction_87.as`. The scripts agree with the
earlier code dump; the SWF adds the previously missing label tags.

- Running uses frames 13..84. Progress is speed along the floor divided by 0.9,
  plus retained fractional progress. The native callback receives Think's actual
  local velocity variables, avoiding extra subtraction/rounding from a snapshot.
- Airborne rendering selects frames 85..103 from vertical velocity, with the
  original linear rising / square-root falling calculation and floor rounding.
- Ground rendering follows the full floor normal. Airborne Think relaxes rotation
  by 10%; jumps and wallslide entry reset it to zero.
- Most renderers face the direction of velocity. Wallslide entry faces the wall,
  and its renderer preserves that choice rather than recomputing it each draw.
- Launch-pad entry switches to the airborne renderer at the collision event.

## Limits

This is animation-state tracking, not a renderer. It does not rasterise artwork,
simulate limb positions, reproduce Flash matrix/twip quantisation, particles or
sound, or add post-completion gameplay. No additional source assets are needed
for the implemented tracker.

The v3.21 engine stops normal player simulation at completion/death. v4.00 keeps
that behaviour. The tracker captures the terminal tick, then automatic visual
updates and timeline advancement freeze. In manual-draw mode a caller may still
draw the terminal state to finish its pending draw.

On death the ordinary sprite is marked invisible and the animation becomes
RAGDOLL with `frame=None`. The original game's separate ragdoll physics is not
implemented here. The last drawn normal-sprite position and rotation are retained;
they must not be treated as a simulated ragdoll position.

When ThinkCelebrate actually chooses a random animation, the default reports
CELEBRATE_UNRESOLVED with `frame=None` and `playing=True`. Supplying
`celebration_variant=1..9` uses the corresponding exact SWF label instead. This is
an explicit supplied choice, not a reproduction of Flash's RNG; no random numbers
are consumed or introduced into gameplay. Airborne completion can legitimately
retain the previous animation, because Celebrate() alone does not select one.

## Validation

`tests/test_native_visual.py` covers opt-in behaviour, initialisation, idle stop
frames, independent clocks, running progression and re-entry, facing, airborne
poses, slope angles and relaxation, wallslides, launch pads, all nine celebration
labels, terminal states, cloning/copying, batch equivalence and invalid options.

Every gameplay state byte and step event matched the unmodified v3.21 engine
across **3,381 ticks in ten bundled replay fixtures**, with tracking disabled and
enabled. Visuals are checked against the source rules and extracted SWF metadata;
this release has not been validated against a newly recorded live Flash visual
trace. Such a comparison should supply the actual timeline/draw schedule.
