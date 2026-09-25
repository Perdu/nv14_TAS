# Local population search (v4.27)

`local --search population` evolves a bounded part of an existing replay for
manual TAS work. It can optimise position or distance at a fixed frame, or
find the earliest qualifying arrival inside a rectangle or interaction with a
selected object. It does not require
the level to finish, or the unchanged later replay to remain successful.

This is a heuristic search, not a proof of the global optimum. It uses the
existing native physics, including object boosts and enemy simulation. It does
not use reinforcement learning or the optional boost-sensitive physics pruning
used by direction-only Local window searches.

## Fixed-frame example

```bash
python3 optimize_replay.py local run.txt \
  --search population \
  --range 200:400 \
  --target-frame 400 \
  --objective min-x \
  --y-window 100:160 \
  --vx-window=-6:-1 \
  --require-interaction switch:0 \
  --iterations 10000 --beam 32 --workers 8 \
  --rounds 0 --stagnation-rounds 20 \
  --top-results 5 \
  --checkpoint manual_campaign.json \
  --output run_optimised.txt
```

The player must be alive after input 400, inside the y window, moving left at
between 1 and 6 pixels per tick, and have activated `switch:0`. Among feasible
results, the smallest endpoint x wins. The velocity constraint does not become
an extra weighted objective.

Negative window bounds are easiest to pass using `--vx-window=-6:-1` so argparse
does not mistake the value for another option. Velocities are the engine's
implicit `pos - oldpos` in pixels per tick; positive x points right and positive
y points down.

## Earliest arrival

```bash
python3 optimize_replay.py local run.txt \
  --search population \
  --range 200:500 \
  --target-frame 500 \
  --objective earliest-arrival \
  --secondary-objective max-vx \
  --target-region 700:740,90:130 \
  --arrival-start 200 \
  --vx-window 1: \
  --require-interaction gold:7 \
  --iterations 10000 --workers 8 \
  --rounds 0 --stagnation-rounds 20 \
  --output arrival.txt
```

The rectangle contains the player's **centre** and has inclusive bounds.
Frame 500 is a deadline. The evaluator checks each frame from `arrival-start`
through the deadline and accepts the first frame at which the region,
position/velocity windows and all interactions are satisfied together, with
the player alive. A prior region entry without the required gold does not
qualify. Leaving the region and entering again can qualify later.

There is no monotonic-arrival or binary-search assumption. Death or an unwanted
interaction after an accepted arrival does not invalidate that result. A
candidate which never qualifies is not a successful output, even if it comes
very close. Distance to the region and constraint progress guide the internal
search while it has no qualifying arrival. Earlier feasible arrival always
outranks later feasible arrival.

`target-region` is required only for `earliest-arrival`. It is independent of
`--target-point`/`--target-object` positional anchors used by `min-distance`.
`earliest-interaction` also uses `--target-object` for an exact event target.

## Earliest interaction (v4.21)

```bash
python3 optimize_replay.py local run.txt \
  --search population --objective earliest-interaction \
  --target-object switch:0 --range 200:500 --target-frame 500 \
  --secondary-objective max-vx --vx-window 1: \
  --iterations 10000 --workers 8 --rounds 0 --stagnation-rounds 20 \
  --output interaction.txt
```

The target is the actual engine interaction, checked after each input tick.
Frame 500 is an inclusive deadline. `--arrival-start` is the first eligible
interaction frame and defaults to the first editable frame. A target object is
required; `--target-region` and `--target-point` are not accepted for this goal.

| Selector | Qualifying event |
|---|---|
| `gold:7` or `gold:7.center` | Collect that gold piece. |
| `switch:0` or `exit:0.switch` | Activate that exit switch. |
| `testdoor:2` (locked door) | Open it using its switch. |
| `testdoor:2` (trapdoor), or `trapdoor:2` | Activate its permanent trapdoor trigger. |
| `exit:0`, `exit:0.center` or `exit:0.door` | Complete through that specific exit. |

`--list-objects` lists the stable per-type indices. `switch`/`exit-switch` are
aliases for exit-switch targets; trapdoor indices are the existing TestDoor
indices, including ordinary and locked doors. Bare types require one supported
matching interaction. `:any` permits a fresh event from any supported match;
`testdoor:any` includes locked switches and trapdoors and excludes transient
proximity doors. The existing `--require-interaction testdoor:any` still means
locked switches only. Unsupported objects such as launchpads, mines and
ordinary proximity doors cannot be used as interaction targets.

Every position/velocity window, required interaction and forbidden interaction
is checked on the event tick, with the player alive at the end of that tick.
Death or other interactions later in the retained replay do not invalidate it.
Exit targets also use this Local survival rule. Full replay completion and a
neutral completion sentinel are not required for other target types.

A bit which was already set does not represent a fresh interaction. If gold is
collected at frame 250 and the velocity window is first satisfied at frame 260,
that pickup does not qualify. For `gold:any`, a later pickup of a different
piece can still qualify. Simultaneous matching events are all reported in
stable selector order. Required route interactions still count from the
immutable prefix, while the selected target must produce a new event in the
eligible interval. When the immutable prefix has consumed every target or
completed the level, the search reports that the editable range must start
earlier. An explicitly eligible event before the editable range can be returned
as a fixed result, just as an earlier region arrival can.

Reference requirements retain their existing deadline semantics: everything
required from the source through `target_frame` must already be satisfied on
the candidate's qualifying interaction tick. The input length and all held
inputs outside the editable range union are preserved, including the suffix.
An interaction may occur in a fixed gap or after the last editable input.

The score is the negative interaction frame. Earlier qualifying interactions
outrank later ones, followed by the optional secondary objective, changed-input
count and deterministic encoded-input ordering. Infeasible candidates use
distance to unconsumed targets and constraint errors to guide repair. A failed
interaction's actual tick or an earlier viable approach is retained; later
states cannot retroactively satisfy that event's constraints. Every output is
packed and re-evaluated from frame zero, including its event identity. With
`--python-resimulate`, the Python engine also verifies the target's transition
on the selected tick.

See `examples/config/local-interaction.toml` for the TOML equivalent.

## Secondary objective for tied arrivals or interactions

Use `--secondary-objective NAME`, or `secondary_objective = "NAME"` in
`[local]`, to choose the preferred state when feasible runs arrive at the same
frame. This option requires population search with `earliest-arrival` or
`earliest-interaction`.

| Choice | Value preferred at the qualifying arrival frame |
|---|---|
| `max-x` | Player centre x: further right. |
| `min-x` | Player centre x: further left. |
| `max-y` | Player centre y: further down. |
| `min-y` | Player centre y: further up. |
| `max-vx` | Larger signed horizontal velocity (`x - oldx`), in pixels per tick. |
| `min-vx` | Smaller signed horizontal velocity: favours leftward velocity. |
| `max-vy` | Larger signed vertical velocity (`y - oldy`), in pixels per tick. |
| `min-vy` | Smaller signed vertical velocity: favours upward velocity. |

The order is **earlier arrival frame, better secondary value, fewer changed
input frames, lexicographically smaller encoded input sequence**. Better means
larger for `max-*` and smaller for `min-*`. Velocities are signed, so `max-vx`
prefers `-1` over `-5`, while `min-vx` prefers `-5` over `-1`. Positive y points
down; `min-vy` favours upward motion. These objectives use signed values rather
than speed magnitude. This is a strict tie-break, with no weighting or trade-off
against arrival time. The primary score remains the negative arrival frame.

The value is measured at the first frame satisfying the region, velocity and
interaction requirements, not at the deadline or a later visit. Failed arrivals
keep the existing constraint-progress ranking. With the option omitted, no
secondary value is preferred and the previous edit-count/input ordering remains.
Edits are counted over the whole normalised replay, including edits after arrival.

The configured objective applies to worker selection, feasible elites,
refinement/repair comparisons, best-run saves and the ordering of selected output
replays. Secondary improvements at the current best arrival frame reset the
stagnation counter; fewer edits alone do not. Progress, best-save and final
result messages report the actual signed secondary value. Internally, minimum
objectives negate that value so a larger normalised score always means better.

## Frame and interaction semantics

- Frame numbers are zero-based and inclusive. Target frame N is the state after
  inputs 0 through N, i.e. N+1 input steps.
- Replay length is fixed. Every frame outside the mutable range union retains
  its original held inputs, including gaps between disjoint ranges.
- Stored jump-trigger bits are derived from the held-jump stream, as in existing
  Local and Auto searches. Editing a jump hold can change a neighbouring derived
  trigger; the strict range protects held inputs, not stale encoded trigger bits.
- The evaluation frame may follow the final mutable frame: intervening inputs
  remain fixed, allowing the search to measure a delayed landing or boost.
- The deadline/target must already exist in the input replay. This version does
  not invent additional frames beyond a partial recording.
- Required/forbidden interactions include the immutable prefix. A pickup before
  the editable range already counts; a forbidden persistent trigger there is
  impossible to undo within the range.
- Existing selectors apply unchanged: required gold, exit switches and locked
  door switches; avoidance also supports trapdoors. `:any` means at least one
  required match, but forbids every matching object for avoidance.
- Reference requirements are resolved once from the post-retime source through
  the target/deadline. With earliest arrival, all those requirements must be met
  by the qualifying arrival, even if the source collected them later.
- Object targets for `min-distance` use the existing map anchors, including the
  map positions of moving objects. They do not dynamically follow an object.
- Ordinary common `--retime` is preprocessing: the strict edit bounds refer to
  the post-retime seed. Population mutations do not change its length.

Enemy simulation defaults to enabled for population searches; it remains
disabled by default for Local window searches. Explicit `--simulate-enemies`
or `--no-simulate-enemies` overrides either default.

## Options

All these controls live in `[local]` when using TOML. CLI scalar values override
the file in the usual way. The input filename remains positional.

| CLI | TOML key | Default | Meaning |
|---|---|---|---|
| `--search windows\|population` | `search` | `"windows"` | Choose Local's search strategy. |
| `--range START:END[,START:END...]` | `range` | `0:target` | Strict mutable input intervals; TOML also accepts a string array. |
| `--target-frame N` | `target_frame` | required | Fixed scoring frame, or inclusive earliest-arrival/interaction deadline. |
| `--objective NAME` | `objective` | `"max-x"` | Existing five positional objectives, plus `earliest-arrival` and `earliest-interaction`. |
| `--secondary-objective NAME` | `secondary_objective` | none | Earliest-arrival/interaction ties: `max-x`, `min-x`, `max-y`, `min-y`, `max-vx`, `min-vx`, `max-vy` or `min-vy`, measured on the endpoint tick before edit-count ties. |
| `--target-point X,Y` | `target_point` | none | Existing explicit min-distance target. |
| `--target-object SELECTOR` | `target_object` | none | Min-distance anchor, or required earliest-interaction object selector. |
| `--x-window MIN:MAX` | `x_window` | none | Inclusive endpoint x constraint. |
| `--y-window MIN:MAX` | `y_window` | none | Inclusive endpoint y constraint. |
| `--vx-window MIN:MAX` | `vx_window` | none | Inclusive endpoint horizontal velocity constraint. |
| `--vy-window MIN:MAX` | `vy_window` | none | Inclusive endpoint vertical velocity constraint. |
| `--target-region XMIN:XMAX,YMIN:YMAX` | `target_region` | none | Finite inclusive arrival rectangle. |
| `--arrival-start N` | `arrival_start` | first mutable frame | First frame eligible for arrival or a fresh interaction. |
| `--iterations N` | `iterations` | `10000` | Proposal budget per worker per round, including repair proposals. |
| `--beam N` | `beam` | `32` | Bound on retained candidates per search beam; must be at least top-results. |
| `--rounds N` | `rounds` | `1` | Total round limit; zero removes the round limit. |
| `--stagnation-rounds N` | `stagnation_rounds` | `20` | Stop after N rounds without a better feasible primary objective or a secondary gain at tied arrival time. Edit-only gains do not reset it. Zero disables this limit. Both stop limits zero runs until Ctrl+C. |
| `--repair-steps N` | `repair_steps` | `64` | Maximum proposals in a bounded refinement/repair attempt; zero disables it. |
| `--repair-lookback N` | `repair_lookback` | `32` | Maximum backward repair reach, clipped to mutable frames. |
| `--mutation-span N` | `mutation_span` | `32` | Bound on temporal span of ordinary interval mutations. |
| `--top-results N` | `top_results` | `1` | Maximum distinct diverse feasible outputs. |
| `--workers N\|auto` | `workers` | `auto` | Independent worker processes, sharing retained candidates between rounds. |
| `--seed N\|random` | `seed` | `0` | Reproducible population seed; `random` generates and prints one. |
| `--checkpoint PATH` | `checkpoint` | none | Atomic JSON campaign checkpoint at round boundaries. |
| `--resume` | `resume` | `false` | Restore the matching population campaign. |

The ordinary `require_interaction`, `avoid_interaction`,
`require_reference_interactions`, output and enemy-simulation options are also
supported. Population searches vary all directional/jump inputs. Window-only
controls, including direction-only search, immutable-jump controls, sparse
window settings, passes and window restarts, are not population controls;
unsupported explicit combinations are rejected.

## TOML example

```toml
[local]
search = "population"
range = "200:400"
target_frame = 400
objective = "min-distance"
target_point = [732.0, 108.0]
vx_window = "1:"
vy_window = "-3:3"
require_interaction = ["switch:0"]
top_results = 5
iterations = 10000
beam = 32
workers = 8
rounds = 0
stagnation_rounds = 20
seed = 12345
checkpoint = "manual_campaign.json"
```

```bash
python3 optimize_replay.py local run.txt --config manual.toml --output result.txt
```

For earliest arrival, replace the objective/target-point lines with:

```toml
objective = "earliest-arrival"
secondary_objective = "max-vx"  # optional; break arrival-frame ties by velocity
target_region = "700:740,90:130"
arrival_start = 200
```

See the ready-to-edit files in `examples/config/local-population.toml` and
`examples/config/local-arrival.toml`.

## Results, diversity and resuming

The best feasible primary/secondary objective pair is always retained. Other requested results
favour distinct endpoint velocity, position/contact and interaction niches;
they can have worse primary scores and are intended as alternative continuation
states for manual TASing. Exact replay duplicates are excluded. If fewer than
the requested number of distinct feasible results are found, only those found
are written; the optimiser does not fabricate alternatives.

The best result uses the requested output path. Further results use
`result.rank02.txt`, `result.rank03.txt`, etc. LTM outputs keep the movie format,
and optional packed replay sidecars receive matching rank suffixes. Each saved
result is packed, decoded and verified independently from frame zero through
its endpoint, including velocity and interaction requirements. There is no
extra completion sentinel requirement. A newly improved verified best is saved
during the search; the population checkpoint additionally records round state
for resume.

Resume with the original input, matching goal/ranges/search settings and the
same checkpoint path. The round and stagnation stop limits may be extended on
resume; the saved seed controls the continuation. The input, level, constraints and search configuration
are fingerprinted so unrelated campaigns cannot be combined accidentally.
The population checkpoint format is distinct from Auto campaign checkpoints.
The secondary objective is part of the goal fingerprint, and its value is
re-evaluated and checked for every restored candidate. Changing it requires a
new campaign. The resolved interaction target is also fingerprinted, and event
identity and completed-exit state are re-verified when restoring candidates.
Local population checkpoints from earlier builds cannot resume in v4.27;
use a replay from that campaign as the input to a new search.

## Implementation

`nv14_endpoint.py` compiles goals and creates public endpoint evaluations.
`native/nv14_endpoint.c` scans every eligible tick chronologically in C with the
GIL released. It checks region/velocity windows, exact requirements/avoidances,
fresh object events and infeasible progress ranking, and retains the selected
full native state. Python snapshots, niche keys and exact state keys are built
only for that selected endpoint. A compiled plan is reused for each worker's
candidates; it contains goal data and object coordinates, not mutable simulation
state. Fixed-frame goals use the same packed-input native replay path.

The original per-tick scorer remains available as `evaluate_reference()`.
`verify_endpoint()` uses it for independent endpoint selection; optional Python
physics verification remains available. Native numeric comparisons conservatively
detect very close progress rankings, where libc and Python distance rounding
could change the chosen frame, and use the reference scorer for those candidates.
Nonfinite player states retain their original infeasible treatment. Accepted
arrivals still stop immediately, without requiring survival after that tick.

Input encoding, immutable-range checking and changed-input counting run in one
compiled pass. The resulting lossless replay key is reused for caching and
native evaluation. Every candidate is checked, including cache hits; explicit
jump-trigger bits and disjoint immutable gaps retain their previous semantics.

`nv14_population.py` owns mutations, evolving beams, crossover, repair, diversity,
workers and checkpoints. `nv14_cli.py` owns strategy-specific CLI/TOML validation
and TXT/LTM output. The native wrapper exposes persistent door-control masks
without changing existing snapshot shapes or the physics engine.

Rebuild the native extension for v4.27 with `python3 build_native.py`. An older
extension cannot run the new population API. The source archive includes
generated C, so installing Cython is not required for that build. No new search
flags or runtime dependencies are introduced. See the
[v4.27 changelog](changelog/CHANGELOG_v4.27.md) for benchmark conditions; the
speedup depends on the goal, replay length and object workload.
