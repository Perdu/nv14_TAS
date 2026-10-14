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
splice-lookback = 40     # editable frames before an anchor
splice-iterations = 1000 # proposals per anchor and worker
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
possible seams. `--auto-stagnation-runs 10` also applies to random splicing;
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
