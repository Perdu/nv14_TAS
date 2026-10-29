# Auto endpoint objectives (shared with Local)

The `[goal]` TOML table is read by **both** `auto` and `local`. Its keys are
parsed with the exact same types and resolved into the same `EndpointGoal`.
`[auto]` or `[local]` overrides a shared key only for that mode; explicit CLI
arguments override both. See `examples/config/shared-endpoint.toml`.

```
python optimize_replay.py auto run.txt --config examples/config/shared-endpoint.toml --output checkpoint.txt
python optimize_replay.py local run.txt --config examples/config/shared-endpoint.toml --output comparison.txt
```

Or without TOML:

```
python optimize_replay.py auto run.txt --output best.txt \
  --auto-objective earliest-arrival --auto-target-frame 250 \
  --auto-target-region 700:740,90:130 --auto-arrival-start 100 \
  --range 100:250 --auto-completion-policy checkpoint
```

## Legacy Local splice TOMLs with unchanged contents

Auto can import the endpoint constraints from an existing `[local]` TOML
without copying it into a `[goal]` table:

```bash
python optimize_replay.py auto run.txt \
  --config auto-default.toml \
  --goal-config splice-167.toml \
  --auto-runs 1 \
  --output best.txt
```

The import includes frame range, target frame/region, interaction constraints,
secondary objective and enemy simulation. It does **not** import Local's
population/window search settings. All regular `--config` paths are layered
left-to-right, then any `--goal-config` imports apply, then explicit CLI
switches. An Auto default containing `runs=0` needs `--auto-runs 1` (or another
finite positive number) for endpoint mode. See [TOML configuration](CONFIGURATION.md).

## Supported goals

Both modes share `max-x`, `min-x`, `max-y`, `min-y`, `min-distance`,
`earliest-arrival`, `earliest-interaction`, `target-frame`, `target-point`,
`target-object`, `target-region`, `arrival-start`, `secondary-objective`,
`x-window`, `y-window`, `vx-window`, `vy-window`, `require-interaction`,
`avoid-interaction`, `require-reference-interactions`, `require-jump-region`
and `require-jump-frames`, plus repeatable `require-jumps` requirements. Fixed-frame objectives are evaluated at the given
input frame. Earliest goals score the *first feasible* event up to that frame.
If omitted, Auto's `target-frame` defaults to the last serialized input.

The default Auto `speedrun` and `highscore` objectives still use its original
complete-route optimiser; a `[goal]` endpoint objective selects the dedicated
native-evaluated reference-guided mutation beam instead.

## Partial route or complete level?

- `completion-policy = "checkpoint"` (default for Auto endpoint objectives):
  keep and verify a feasible endpoint, even if the replay later dies or fails
  to exit. **Such an output is not automatically a completed TAS.**
- `completion-policy = "complete"`: accept only a feasible endpoint whose
  packed replay also completes exactly on its implicit neutral sentinel.
  This is more restrictive, and may reject otherwise useful trajectories.

Local population's endpoint checks are independent of level completion.
The traditional Auto `speedrun`/`highscore` search still always demands a
completed replay and uses its existing native repair/splice coordinator.

## Search engine boundaries

Endpoint Auto reuses Local's native evaluator, including exact dynamic state
verification, interaction identity, arrival frame, signed secondary objective,
and event/jump predicates. Its proposal beam uses Auto-style suffix and
single-transition retiming, jump-pulse shifts, directional bursts, jump edits
and between-candidate section mixing. Search rounds may run in parallel
processes and feed back the best verified endpoint replay.

**The original full-run Auto's reference-alignment repairs and exact suffix
splicing do not run for partial endpoints.** They assume completed replay
sentinels and must be adapted separately before being safe for checkpoint
trajectories. No changes are made to the physics engine or Cython bindings.

Endpoint Auto currently requires finite `runs`; it does not support the
completion-only Auto checkpoint/resume protocol, `--auto-parent`, or the
highscore-only `--auto-max-extra-ticks`/gold requirements. Other full-route
repair configuration options do not tune the endpoint beam. Every accepted
best candidate is round-tripped through the packed replay representation and
independently checked with Local's `verify_endpoint` before it is written.
`workers=0` selects one endpoint worker; positive values run parallel workers.

## Measuring results

Use the same `[goal]`, input, range and simulation settings for both modes.
`iterations` is a *proposal attempt* ceiling, not a guarantee of equal numbers
of physical simulation ticks. Auto may skip duplicate proposed replays;
compare its printed distinct evaluation count to Local's evaluation count.
For a full-run TAS, continue verifying completion separately before adopting a
checkpoint-only output as a replacement.

## Requiring multiple real jumps in one splice

`require-jumps` is a list of independent, **AND**-combined predicates. Each
needs at least one *executed* jump originating inside its rectangle and during
its inclusive input-frame interval. Inputs merely holding Jump do not count.
A single actual jump may satisfy overlapping requirements; to require distinct
jumps use disjoint frame intervals. The old `require-jump-region` and
`require-jump-frames` options still work unchanged. Do not mix the old single
requirement with the list in the same goal.

Existing Local-style splice files can now contain:

```toml
[local]
search = "population"
target-frame = 167
range = ":167"
objective = "earliest-arrival"
target-region = "382:422,377:397"

[[local.require-jumps]]
region = "375:410,340:385"
frames = "30:95"

[[local.require-jumps]]
region = "382:422,377:397"
frames = "96:167"
```

Both `region = [xmin, xmax, ymin, ymax]` and `frames = [start, end]`
arrays are accepted. Use the splice TOML unchanged with `local --config`
or `auto --goal-config`. A shared `[goal]` file can similarly use
`[[goal.require-jumps]]`. On the CLI, repeat
`--require-jumps '375:410,340:385@30:95'` as needed.

For multiple requirements, evaluation performs an exact per-frame native-state
scan with Python orchestration to track all successful jumps and enforce
correct earliest-goal ordering. This **does not change game physics or the
Cython/native ABI**, but is slower than the single-jump compiled endpoint scan.

## Native endpoint fast path and optional diagnostics

After applying the native endpoint performance update, rebuild once:

```sh
cd optimiser
python3 build_native.py
```

The compiled endpoint scan now returns the exact player coordinates **before**
its selected interaction tick. `min-exit-distance` uses this point instead of
simulating the whole replay a second time. The reference-scoring fallback is
unchanged, and the previous seven-element `NativeEndpointPlan.scan()` return
value is preserved unless `with_pre_position=True` is requested.

Auto reuses compact packed keys when trying a single-frame polish or chain edit.
It still materializes a complete replay for each distinct candidate, because
checkpoint persistence and verification require it. These changes do **not**
change proposal order or consume additional evaluation slots.

For detailed worker timing and duplication counters:

```toml
[auto]
performance-stats = true
```

The reported evaluate duration includes native scanning and Python-side
scoring, but does not separate their time internally. Pack/mutate/population
categories account for timed portions of each worker, so they need not sum to
100% of its wall-clock time. Timing is disabled by default to avoid overhead.

Optional same-round exchange of newly verified best replays:

```toml
[auto]
shared-refinement-proposals = 128
```

This is a **supplemental** search after a worker completes its original budget,
using the latest confirmed candidate received from another worker during the
round. It never replaces proposals from that original seeded search. The value
is an *additional* per-worker proposal allowance, not a fraction of the existing
budget. `0` (the default) disables it. Extra simulations and worker time may be
spent, and the additional search may not run when no better shared candidate
is available. Asynchronous arrival affects the optional supplemental results,
not the original worker streams.

The equivalent CLI options are `--auto-performance-stats` and
`--auto-shared-refinement-proposals 128`.
