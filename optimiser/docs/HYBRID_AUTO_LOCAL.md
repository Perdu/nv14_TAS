# Experimental one-Auto / N-Local hybrid (patch 75)

This is a **bounded, opt-in scheduling experiment** for named splice goals,
not a new physics engine, an assurance of better TAS quality, or a merged
Auto/Local population. The existing `both` mode remains unchanged so the
previous continuous Auto-until-stagnant → Local-until-stagnant strategy can be
compared independently.

## Why

An improvement after changing algorithms does not establish causality. The
second algorithm starts a *new population*, with a new random seed and another
opportunity to reach a different local optimum. Merely restarting Local from
an incumbent could yield the same advantage. This mode tests that hypothesis.

For each named stage seed, `hybrid` runs up to `K` cycles:

1. One **endpoint Auto** campaign round, `I` proposals per worker.
2. **N consecutive Local** population rounds *inside one Local invocation*,
   `I` proposals per worker per round. Local retains its population across
   these N rounds.
3. Feed the best feasible stage incumbent to the next turn. With no feasible
   candidate, follow the best endpoint progress ranking. Preserve all returned
   candidates for the normal named-splice frontier and independent validation.

Each backend starts its *own* search population on invocation; the population
itself does not survive a backend switch. The shared state is the incumbent,
not the full search history. An optional hybrid-specific stagnant-cycle limit
can stop before the fixed `K` cycles. A cycle is stagnant only when neither
backend improves the stage's feasible objective. Default 0 runs all cycles.

## Invocation

Single goal shortcut:

```sh
python3 tas.py hybrid 88-4 522 \
  --splice-hybrid-local-rounds 5 --splice-hybrid-cycles 8 \
  --auto-splice-iterations 400 --workers 8 --seed 42
```

Named multi-splicer TOML:

```toml
[multi-splicer]
files = ["522", "end"]
search = "hybrid"
iterations = 400
hybrid-local-rounds = 5
hybrid-cycles = 8
hybrid-stagnation-cycles = 0
```

The existing `--auto-runs` controls **outer named-splicer rounds**, not Auto
rounds inside a hybrid cycle. `--auto-splice-iterations` is **per worker, per
backend round** in this mode. Thus one stage seed uses at most
`workers * iterations * cycles * (1 + local_rounds)` nominal proposal slots,
excluding any stage-specific repair overhead. Actual *distinct evaluations*
are reported separately, as duplicate/early-stopped searches may use fewer.

`hybrid` rejects the incompatible older phase-stagnation, speed-preset and
`splice-rounds > 1` settings rather than silently reinterpreting them. Named
Local goal files containing their own `rounds` or `stagnation_rounds` must
have those stopping parameters moved to the hybrid settings above. Other Local
goals/constraints and per-stage mutation/beam settings remain available.

## Matched restart experiment

**Use the same input replay, named goal, workers, iterations, cycle count,
Local round count and seeds**, with separate output/checkpoint paths:

- **Hybrid:** `--auto-splice-search hybrid` uses Auto(1), Local(N).
- **Restart-only control:** `--auto-splice-search hybrid-local-control`
  uses Local(1), Local(N). This repeats exactly the same invocation boundaries,
  number of round slots, and coordinator random-seed draws. Only the first
  algorithm changes.
- **Uninterrupted Local:** `--auto-splice-search local`
  `--auto-splice-rounds K*(1+N)` uses an uninterrupted Local population with
  comparable nominal proposal slots. It does not match the restart schedule.
- **Previous combined strategy:** `--auto-splice-search both`, using the
  current independent phase-stagnation settings. Its work is *not* directly
  budget-matched until the actual number of evaluations is measured.

To run the control, use `auto` with `--auto-splice-files` and
`--auto-splice-search hybrid-local-control` (or a named `[multi-splicer]` TOML
configuration). The `tas.py hybrid` shortcut intentionally selects the
experimental hybrid rather than the control.

The hybrid progress log records the backend, round count, per-turn random
seed, evaluation count and best eligible objective key after every turn; use
those records to determine **which phase** produces a gain and how frequently
restarts without Auto find comparable gains.

Compare **many identical seed sets**, not just one lucky restart. Measure:

- first and best eligible objective after equivalent cumulative proposals;
- full replay input strings and verified game/SWF outcomes;
- diverse candidates, failed/near-miss goals and objective progress;
- elapsed wall time, distinct evaluations and evaluated candidates per second.

These controls match *nominal round slots*, not the algorithms' exact counts
of simulations or their numerical trajectories. Do **not** conclude Auto is
beneficial solely because Hybrid beats the baseline once. A difference that
persists across matched seeds, budgets and verified replays is more credible.

## Safety and limitations

The existing named-splice coordinator continues to perform stage-goal and
completed-replay verification. The original SWF, rather than native C,
remains the authoritative gameplay implementation. This patch changes no
physics or floating-point precision. It does not add a GPU dependency.

Hybrid cycles do not yet have per-cycle restart checkpoints. Existing outer
multi-splicer checkpoints remain supported, but an interruption *inside* one
hybrid stage seed may repeat the unfinished seed on resume. Experiment with
separate checkpoint/output directories and do not overwrite the input movie.

This initial implementation is restricted to **named** splices. Sampled
random/physics waypoint search is left unchanged because the separate repair
paths still assume a single backend; extending the scheduler to those paths
requires additional review.
