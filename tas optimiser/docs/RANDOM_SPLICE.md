# Switch-safe random path splicing (Auto)

`auto --auto-random-splice` is an **opt-in micro-optimisation strategy** for an
existing *completed* TAS. It requires `--objective speedrun`, and it will never
write an incomplete or non-improving run.

The optimiser samples a configurable number of waypoints along the current
best simulated path, either by randomised travelled-distance partitions or by
pixel spacing. Each waypoint becomes an earliest-arrival rectangular Local
population goal. After identifying an earlier local arrival, it searches for a
physically compatible join (position **and** velocity/contact state) to the
reference suffix. If direct completion fails, it can run successive Local
population searches toward later waypoints to repair the continuation.

Two improvements prevent premature rejection of otherwise promising routes:
compatible velocity/contact seams are now actually tried (instead of always
being overwritten by the original-anchor fallback); and a bounded **progressive
frontier** can retain surviving but not-yet-feasible near-misses from one
waypoint to the next. This second path mutates the entire interval after the
previous waypoint, retaining several distinct physical states. The final
interval targets the **fresh exit interaction**, with the Local endpoint's
squared distance to the specific exit door ranking incomplete attempts.
Incomplete frontier candidates are never saved as TAS output.

**Switch and object safety are hard constraints:** mandatory waypoints are added
after route-control interactions; every waypoint requires previously activated
switches/locked doors; each proposed seam preserves the reference's exit,
locked-door and trapdoor masks; and a final, repacked replay must complete
with every original exact `(interaction kind, object index)` route-control event
still present. A candidate that skips a necessary switch is discarded, even
if it arrives earlier. Dynamic physics differences are also checked by a full
replay from frame zero. Gold is not hard-required for a speedrun unless its
loss prevents completion.

## TOML example

Add this to your ordinary default Auto TOML (no splice files required):

```toml
[auto]
objective = "speedrun"
random-splice = true
runs = 3                  # 0 repeats until stagnation limit or Ctrl+C
stagnation-runs = 10      # stop after 10 rounds with no shorter completed TAS
beam = 16
seed = "random"         # integer seeds reproduce waypoint selection/search
splice-points = 8        # alternatively: splice-distance = 80.0 (pixels travelled)
splice-radius = 14.0     # +/- in x and y, in pixels
splice-lookback = 40     # seam matching and mutation span, not editable interval size
splice-iterations = 1000 # proposals per anchor, worker, and Local round
rounds = 10               # Local population rounds per waypoint (not Auto campaigns)
splice-frontier = 3       # cross-waypoint partial routes (0 disables; default 3)
splice-exit-lookback = 96 # allow final exit search to overlap recent waypoint intervals
splice-repair-iterations = 500
splice-repair-anchors = 3 # subsequent anchors to attempt repair through
splice-repair-searches = 8 # max expensive continuation searches per waypoint (0 disables)
```

Then run:

```sh
python optimize_replay.py auto completed.txt --config auto-default.toml --output improved.txt
```

Or invoke directly:

```sh
python optimize_replay.py auto completed.txt --output improved.txt \
  --auto-random-splice --auto-runs 2 --auto-splice-points 8 \
  --auto-splice-radius 14 --auto-splice-iterations 1000
```

Use `--auto-splice-distance 80` instead of `--auto-splice-points` to sample
by travel distance. In either case switch/door events add *mandatory* anchors,
which can increase the total above the requested count.

`--workers` controls the Local population search at each waypoint. The
iterations settings are **per worker**, not a global shared limit. For example,
`--workers 15 --auto-splice-iterations 1000` budgets 15,000 proposals for
**each waypoint**. Local creates a new worker pool per waypoint/continuation
search, so frequent startup overhead is possible. Waypoints are processed
sequentially; the CLI now reports each one, Local's periodic population
progress (normally every five seconds), and each continuation-repair search.
`--auto-splice-repair-searches` caps how many such expensive continuation
searches are attempted **per waypoint**, preventing an explosion across
possible seams. A progressive frontier adds extra Local searches (roughly half
of `splice-iterations` per waypoint/branch, full `splice-iterations` at the
exit). If its overhead is unacceptable, set `splice-frontier = 0` to return
to the corrected single-splice-plus-repair strategy. An intermediate waypoint
need not be fully reached for a trajectory to enter the frontier, but the
ninja must survive and preserve all control interactions already triggered in
the reference. Progress diagnostics print near misses, discarded dead routes,
missing switch masks, unverified completions, and the best finite
**exit-door edge gap in pixels** (smaller is better). This distance guides
**incomplete** candidates; verified completed speedrun frame count remains the
only acceptance criterion. `--auto-stagnation-runs 10` also applies to random splicing;
zero disables the stopping condition.
The optimiser outputs a replay only after independently verifying a shorter,
completed run with the same required route-control events. If none is found,
no output file is written and the original source remains untouched.

## Scope and limits

This strategy uses Local's population endpoint evaluator/search, plus state-aware
suffix joining and bounded continuation repairs. It is *not* the full completed
Auto campaign's global multi-parent/splice planner, and it does not currently
support Auto checkpoints/resume or extra
`--auto-parent` replays. Randomising anchors cannot guarantee improvement;
try different fixed seeds and radii, and measure actual finish frames. The
physics and native search kernels are unchanged.

### Exit approach search and early waypoints

The final exit-interaction search must have room to change the approach, not
just the last few frames after the last randomly sampled waypoint.
`splice-exit-lookback = 96` ensures that the ending search can edit at least
96 input frames (or the full run when shorter), **even if the final waypoint
is much closer to the exit**. This overlaps previously sampled waypoint
intervals intentionally: completed results are always checked from the start
with all reference switch/door/trapdoor events preserved. Increase this
value when the closest exit near-miss is still tens of pixels from the door.

The search still uses fixed source-length candidate replays until a completed
run is verified; reaching an early waypoint does not itself imply that the
following suffix was shifted earlier. This remains an architectural limitation.
