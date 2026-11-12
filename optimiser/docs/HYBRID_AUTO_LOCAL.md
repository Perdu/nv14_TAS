# Experimental one-Auto / N-Local hybrid (patch 75, population handoff 76, config compatibility 77)

This is a **bounded, opt-in scheduling experiment** for named splice goals,
not a new physics engine or an assurance of better TAS quality. Starting in
**patch 76, `hybrid` retains a shared, bounded population of replay candidates**
across Auto/Local switches, rather than passing only its current best. The
existing `both` mode remains unchanged for a separate comparison.

## Why

An improvement after switching algorithms does not establish causality. A
restart alone might reach a different local optimum. With patch 76, `hybrid`
retains a diverse population of surviving candidates between phases, while two
restart-only controls permit a more informative comparison.

For each named stage seed, `hybrid` runs up to `K` cycles:

1. One **endpoint Auto** campaign round, `I` proposals per worker.
2. **N consecutive Local** population rounds *inside one Local invocation*,
   `I` proposals per worker per round. Local retains its population across
   these N rounds.
3. Merge each backend's actual *retained beam* with the previous cross-backend
   population, keeping a bounded set of feasible elites and distinct endpoint
   niches, including live non-feasible states. By default the shared pool is
   limited to `beam` candidates, and retains an infeasible reserve.
4. Hand the selected replay population to the next backend, including members
   that were not exported as named-stage winners or partial frontiers. In the
   receiving backend every replay is independently evaluated with the current
   endpoint goal and checked against fixed prefix/suffix frames. Raw native
   states, visited sets, private caches, and round counters are **not** reused.
5. The best eligible incumbent still cannot regress. Other returned candidates
   are preserved for normal named-splice frontier selection and verification.

Local's N rounds remain one uninterrupted native-population invocation. Across
backend calls, phase-specific internal search state is recreated, but the
*surviving replay population* is persistent. This is a shared replay beam,
not a single unified native search session. An optional stagnant-cycle limit
stops after K cycles without a feasible objective gain (default 0: run all).

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

In Hybrid, Hybrid-Restart and Hybrid-Local-Control, older `splice-rounds`,
`auto-stagnation-rounds`, `local-stagnation-rounds`, legacy
`stagnation-rounds` and `round-speeds` settings are **accepted but ignored**.
`speed` (`--splice-speed`) **does** control hybrid stagnant-cycle patience:
`fast`=3, `normal`=5, `slow`=10. This preset overrides the numerical
`hybrid-stagnation-cycles` setting; omit `speed` to set that limit manually or
leave it at 0 (no stagnation early stop). The same legacy compatibility applies
to `rounds` and `stagnation-rounds` in each named `[local]` goal file. Existing
TOML configurations can therefore switch to Hybrid without deleting settings
used by `both` or standalone Local. `hybrid-local-rounds` and `hybrid-cycles`
continue to control round counts and maximum cycles; `runs` remains the separate
outer multi-splicer limit. Unused settings must still have valid values.

**The speed preset does not raise `hybrid-cycles`.** For example, with default
`hybrid-cycles=5`, `speed="slow"` sets patience to 10 but a stage still runs at
most 5 cycles. To allow 10 stagnant cycles, also set `hybrid-cycles` to 10 or
higher. The same mapping applies to `hybrid-restart` and
`hybrid-local-control`. Outer `round-speeds` schedules remain ignored in all
three hybrid variants.
Other Local goals/constraints and per-stage mutation/beam settings remain available.

## Matched restart experiment

**Use the same input replay, named goal, workers, iterations, cycle count,
Local round count and seeds**, with separate output/checkpoint paths:

- **Population-preserving Hybrid:** `--auto-splice-search hybrid` uses Auto(1),
  Local(N), exchanging a bounded population after every backend call.
- **Auto/Local restart control:** `--auto-splice-search hybrid-restart`
  uses Auto(1), Local(N) but passes only the incumbent. This preserves patch 75's
  original alternating behaviour and isolates the value of population handoff.
- **Local-only restart control:** `--auto-splice-search hybrid-local-control`
  uses Local(1), Local(N) and passes only the incumbent. It tests whether Auto
  adds value compared with Local-only restarts, independently of the population
  handoff experiment.
- **Uninterrupted Local:** `--auto-splice-search local`
  `--auto-splice-rounds K*(1+N)` uses an uninterrupted Local population with
  comparable nominal proposal slots. It does not match the restart schedule.
- **Previous combined strategy:** `--auto-splice-search both`, using the
  current independent phase-stagnation settings. Its work is *not* directly
  budget-matched until the actual number of evaluations is measured.

To run either restart control, use `auto` with `--auto-splice-files` and
`--auto-splice-search hybrid-restart` or `hybrid-local-control`, or a named
`[multi-splicer]` TOML configuration. `tas.py hybrid` selects the shared-pool
version. Distinct seed streams at the worker level can result even with equal
coordinator draws once a backend receives a different population.

The hybrid progress log records the backend, round count, per-turn random
seed, evaluation count and best eligible objective key after every turn; use
those records to determine **which phase** produces a gain and how frequently
restarts without Auto or without population handoff find comparable gains.
The log also reports the number of retained cross-backend replay candidates.

Compare **many identical seed sets**, not just one lucky restart. Measure:

- first and best eligible objective after equivalent cumulative proposals;
- full replay input strings and verified game/SWF outcomes;
- diverse candidates, failed/near-miss goals and objective progress;
- elapsed wall time, distinct evaluations and evaluated candidates per second.

These controls match *nominal round slots* and coordinator RNG draws, not the
exact number of simulations, the populations, or their numerical trajectories.
Re-evaluating transferred candidates adds overhead not counted as proposal
slots, although those evaluations are included in reported evaluation totals. Do **not** conclude Auto is
beneficial solely because Hybrid beats the baseline once. A difference that
persists across matched seeds, budgets and verified replays is more credible.

## Safety and limitations

The existing named-splice coordinator continues to perform stage-goal and
completed-replay verification. The original SWF, rather than native C,
remains the authoritative gameplay implementation. This patch changes no
physics or floating-point precision. It does not add a GPU dependency.

Hybrid's cross-backend population is in-memory only and is scoped to one named
stage seed; it is not a persistent pool shared between different stage goals.
Hybrid cycles do not yet have per-cycle restart checkpoints. Existing outer
multi-splicer checkpoints remain supported, but an interruption *inside* one
hybrid stage seed may repeat the unfinished seed on resume. Experiment with
separate checkpoint/output directories and do not overwrite the input movie.

This initial implementation is restricted to **named** splices. Sampled
random/physics waypoint search is left unchanged because the separate repair
paths still assume a single backend; extending the scheduler to those paths
requires additional review.

## Optional input-run seed (patch 79)

Set `[multi-splicer] use-current-run = false` or use
`--no-use-current-run` to prevent the supplied input run from being
searched as a seed at every named stage. It still contributes the input
baseline and reporting metrics. Saved stage frontiers, saved checkpoints and
a distinct saved completed replay can supply seeds instead; if none are
available for a stage, an explicit error explains why the search cannot
proceed. This does not disable `--splice-from-best` or resume recovery.

## Per-splice history lookback (patch 80)

In each goal file, e.g. `522.txt`, set `[local] lookback = 3` (or
`stage-lookback = 3`) to use up to three preceding splice frontiers **as
seeds for this stage**. An explicit `--splice-stage-lookback N` overrides
per-stage values. The coordinator retains enough preceding populations for
the largest per-stage value, even if earlier stages use a smaller one. This
is not the mutation/repair frame lookback (`repair-lookback` in a Local goal
file), nor the global seam-matching horizon (`--auto-splice-lookback`).

## Timestamps (patch 82)

Multi-splicer CLI status lines, including named-splice summaries, routes, and
colourized improvement messages, are prefixed with local `[HH:MM:SS]`. This
is only a presentation change; search state and checkpoints are unchanged.

## Alternate-route summaries (patch 83)

`-l` / `--ls-splice` is strictly read-only and overrides any `--merge`,
`--repair`, `--retime-gains`, or related search mode configured in TOML or
specified on the command line. It ignores splice start/stop/from-best filters
and reports all configured saved checkpoints without modifying any replay.

`--ls-splice` / `-l` now prints a separate `summary:route` heading for the
configured alternate route, then shows every configured stage in that order
(shared prefix, alternate-only stages, reconvergence, and suffix), labelled
`[alternate route]`. Summary mode remains read-only. Normal search still
executes only its planned divergent stages before reconvergence.

## Bounded Hybrid bridge repairs and targeted propagation (patch 84)

Bridge repair accepts `search = "hybrid"`, `"hybrid-restart"`, and
`"hybrid-local-control"`. To keep the repair work bounded, it runs a single
Auto/Local handoff (or Local/Local for the control), dividing
`repair-iterations` across those two calls; only the regular named-stage
Hybrid campaign uses the configured `hybrid-cycles` and
`hybrid-local-rounds`. The persistent variant carries candidate replays from
Auto into Local. Existing canonical completion and persistent-control
verification remain mandatory.

For example, restrict bridge mutation searches to the saved 527 checkpoint
and a later saved 599 route:

```sh
--splice-merge-repair-only \
--splice-merge-repair-from 527 --splice-merge-repair-to 599 \
--splice-merge-verbose
```

The same command with short CLI flags is:

```sh
--repair --from 527 --to 599 --splice-merge-verbose
```

`--merge` is the short form of `--splice-merge-only` (without mutation-based
bridge repairs). The long flag names remain supported; these options are
accepted by `optimize_replay.py auto` and forwarded by `tas.py multi`.

To target the bridge around a specific source replay frame, add
`--merge-repair-at-frame 800` or the shorter `--at 800` (TOML:
`[multi-splicer] merge-repair-at-frame = 800`). This centres a bounded
neighbourhood of target ticks around frame 800; it does not force a single
reference tick and does not move the immutable checkpoint prefix. If the
source replay cannot reach frame 800 alive, the repair reports the unavailable
frame rather than silently picking a different seam. For example:
`--repair --from 527 --to completed --at 800 --splice-merge-verbose`.

Or use `[multi-splicer] merge-repair-from = "527"` and
`merge-repair-to = "599"`. The target `completed` selects a verified
completed suffix, while source `current` selects the positional input.

### Deterministic gain-aware suffix retiming

Before spending on stochastic bridge mutations, try the saved measured frame
lead itself: `--retime-gains` (alias `--splice-merge-retime-gains`). For each
saved earliest-arrival stage that is ahead of an available saved continuation
at that same helper, preserve all of the faster replay through its **actual**
arrival frame, then splice in the reference's later input sequence at the
reference's actual arrival. It also tests nearby offsets of +/-1 and +/-2.
The shifted replay is fully re-evaluated; no equality of physical states is
assumed at the seam. Only existing independent stage/completion verification
can save a result. The original SWF is still authoritative.

```sh
# Sweep all saved gains, no expensive Auto/Local bridge mutation search:
python3 tas.py multi 69-2 --retime-gains
# Focus on one source -> saved completed continuation:
python3 tas.py multi 69-2 --retime-gains --from 777 --to completed
# Do the deterministic pass, then bounded stochastic repair:
python3 tas.py multi 69-2 --repair --retime-gains --from 777 --to completed
```

With no `--from` restriction the sweep considers each saved earliest-arrival
checkpoint, and when no `--to` is given it uses verified completed continuations
and the next available later saved stage. `[multi-splicer]
merge-retime-gains = true` enables the same path. Unlike the mutation search,
retiming is not limited by `merge-repair-pairs` or `repair-iterations`; it
reports how many candidates were actually tested. A standalone `--retime-gains`
implies the merge-only pass. `--at` only affects the subsequent bridge search;
retiming always aligns the measured source/destination checkpoint arrivals.
If the source checkpoint has no measured gain, the sweep skips it.

Repair no longer mutates or grafts before an already feasible
`earliest-arrival` checkpoint's actual arrival frame. A gain remains pending
if no later valid continuation can preserve it; an accepted repair candidate
is not the same thing as an improved completed replay. Normal multi-splicer
stage search, direct grafting, and the SWF verification hierarchy are unchanged.

## Partial checkpoint propagation from saved replays (patch 90)

`--merge` and `--repair` now independently check whether every saved stage
winner (and one archived sectional alternative) already reaches **later** named
goals. A subsequent death does not erase an earlier valid stage result. Each
proposed checkpoint is evaluated by its own named goal **and** checked against
the enemy-enabled physical replay: a goal reached only in an enemy-disabled
stage world after real-physics death is not promoted. A verified intermediate
stage best is saved to that stage's checkpoint/frontier, **not** published as a
completed replay. This pass does not invoke stochastic search and does not
require `--retime-gains`.

Direct suffix grafting also checks seam windows around a source's **actual**
earliest-arrival tick, including earlier windows, rather than searching only
near its nominal `target_frame`. In stage-only grafts, a reference route that
dies *after* a useful section can provide its still-live portion; completed
suffix grafts retain the original strict completion and control requirements.

**Stage-only outputs retain their complete recorded input sequence (patch 98).**
An intermediate replay may reach a useful checkpoint and die at a later tick.
That later death disqualifies it as a completed run, **not** as a saved stage
checkpoint. The merge, bridge-repair and direct-checkpoint-promotion paths now
verify the live segment through the target goal without cutting off the later
recorded inputs or replacing them with neutral padding. This matters for a
later stage seeded from that checkpoint: its existing continuation remains
available to mutate or retime. An already truncated checkpoint cannot have its
previously discarded inputs inferred; recover those from an intact LTM/TXT or
frontier member when available.

For example, if a 442-stage replay reaches 630 at frame 554 but dies near the
exit, a normal merge can save a verified 630 checkpoint without claiming an
improved completion. `--retime-gains` remains a separate deterministic
**input-shift** search: it may still be necessary when the saved 442 movie does
not itself reach 630, and it can be combined with `--repair`. Neither feature
makes a dead movie into a valid final replay; the next task is to reconnect or
repair its continuation past the enemy.

When `merge-retime-gains = true` is set in `[multi-splicer]`, it augments
normal search/merge operations and does not switch to standalone merge-only.
To request only a deterministic retiming sweep, pass `--retime-gains` on the
command line. `merge-only = true` and `merge-repair-only = true` in TOML
retain their explicit standalone semantics.

## Interpreting named multi-splicer checkpoint propagation

Full named multi-splicer summaries (`-l` or periodic progress) report a
**same-replay downstream gain** alongside each saved stage. This field evaluates
that stage's *own saved replay* at each subsequent named goal in route order,
using the goal's configured enemy simulation. A gain is reported only while
that replay remains alive under the full level physics and beats the verified
completed baseline (or positional input if no completed baseline exists).
The report gives the furthest later stage with a measurable advantage,
flags intermediate helper goals that had no gain (nonconsecutive propagation),
and identifies the first following stage without a gain when one exists.
For earliest-arrival stages it includes the frame saving at the downstream
checkpoint; for fixed-frame spatial stages it says "better stage objective"
and does not mislabel spatial improvement as saved frames.

A later stage's independently saved candidate can have a better result even if
this particular replay cannot get there. The summary does **not** combine
unrelated stage winners into one claimed route. Reaching a stage does not imply
full-level completion, and a death after a valid checkpoint does not erase
that checkpoint's earlier gain.

## Unified named checkpoints for Auto, Local population and Hybrid (patch 96)

When a level has `../splices/LEVEL/multi-splicer.toml`, the `tas.py` shortcuts
`auto`, `local`, `goal`, `both` and `hybrid` use the **same named-stage
coordinator** as `tas.py multi`. They write the same per-stage verified best
LTMs and companion TXT/frontier files, for example `wip/91-2_442.ltm`,
`wip/91-2_442.txt` and `wip/91-2_442.frontier.json`. Checkpoints remain
separate from `wip/91-2.ltm` (the completed-run output); an incomplete stage
result cannot replace a verified completed replay.

The backend selected by the shortcut overrides `[multi-splicer] search`:

| Shortcut | Managed search backend | Stages actually searched |
|---|---|---|
| `tas.py auto LEVEL` | endpoint-auto | Whole named route |
| `tas.py auto LEVEL NAME` | endpoint-auto | NAME only |
| `tas.py local LEVEL NAME` | local population | NAME only |
| `tas.py goal LEVEL NAME` | endpoint-auto | NAME only |
| `tas.py both LEVEL NAME` | both | NAME only |
| `tas.py hybrid LEVEL NAME` | hybrid | **NAME only**, never subsequent stages |

For single-splice searches the full configured route is **loaded for
checkpoint/merge sources**, but normal search is strictly restricted to NAME.
An alternate-only NAME selects its alternate route; a shared NAME defaults to
the primary route. The existing full multi-splicer path remains `tas.py multi`.

These managed modes honor `[multi-splicer] merge-bests`,
`merge-repair-at-end`, and `merge-retime-gains` settings, running the enabled
passes around the search as in the named multi-splicer. A cheap direct merge
may update later saved stages without any later **search**. To disable all
three propagation passes for one run, use `--no-propagation`
(`--no-splice-propagation`); verified stage checkpoints are still saved.
The standalone `--merge`, `--repair` and `--retime-gains` commands retain their
existing explicit meanings and cannot be combined with `--no-propagation`.

### A named goal without `multi-splicer.toml` (patch 99)

A route file is **no longer required to persist a named splice result**.
When `tas.py auto/local/goal/both/hybrid LEVEL NAME` finds the corresponding
`../splices/LEVEL/NAME.txt` (or `NAME.toml`), it runs a **one-stage named
campaign**, saving a verified best to `wip/LEVEL_NAME.ltm`, its replay TXT,
and its stage frontier exactly as in the multi-splicer. The stage is the
**only** stage searched, including in Hybrid mode. No downstream goals or
merge/bridge repair/retime phases are implied: in the absence of a named
route they are disabled. `tas.py auto LEVEL` without NAME continues to run
ordinary standalone Auto. Without an existing named goal, the older Local,
Hybrid, Both, and Goal shortcuts keep their standalone operation.

The goal file must use `[local] search = "population"` (the named-stage
coordinator's supported backend). A Local `search = "windows"` goal is still
handled by the legacy Local command, rather than changing its search engine;
that legacy window-search path does not yet publish named checkpoints.
Direct `optimize_replay.py local` likewise remains the original standalone
command. To use the same checkpoint writer directly without a route TOML:

```sh
python3 optimize_replay.py auto ../n_levels/91-2.ltm \
  --config examples/config.toml \
  --auto-splice-files 442 --auto-splice-mode user --auto-random-splice \
  --auto-splice-directory ../splices/91-2 \
  --auto-splice-search hybrid --single-splice 442 --no-propagation \
  --output wip/91-2.ltm --replay-output wip/91-2.txt
```

The checkpoint is independently goal-verified, and a worse checkpoint does
not overwrite a better one. **Single-splice Auto/Local/Hybrid output is not
replaced by the multi-splicer summary.** The underlying endpoint-Auto and Local
population backends also print their usual per-round progress, including best
frame and objective/position information; Hybrid shows both backend phases.
The named-stage summary and checkpoint-save messages remain visible alongside
those mode-specific logs, so search progress is distinguishable from a saved
checkpoint and from an independently verified full-level completion. A full
`tas.py multi LEVEL` route retains its compact stage-level output.
If a multi-splicer route file is created later,
it can load and re-evaluate the already saved LTM/TXT stage best. Saved
frontier metadata is checked against the current stage identity; incompatible
frontiers may be skipped, but the verified per-stage replay remains eligible.
With an actual multi-splicer route, the normal merging and propagation
behavior remains unchanged.

Managed `tas.py local` uses the **named Local population backend**, not the
legacy standalone Local window-search engine. For managed Local with an
existing route use `tas.py local` or the equivalent:

```sh
python3 optimize_replay.py auto ../n_levels/91-2.ltm \
  --config examples/config.toml \
  --splice-config ../splices/91-2/multi-splicer.toml \
  --auto-splice-search local --single-splice 442 \
  --output wip/91-2.ltm --replay-output wip/91-2.txt
```

Single-splice runs still load and independently verify existing checkpoint
files before replacing them, and still use strict full-level physics for
completed output. No physics or native precision changes are involved.

## Reporting-only dead ends

A named splice goal can declare `dead-end = true` under `[local]`. This
marks a saved checkpoint as a **dead end for reporting only**, so pending
summary lines and temporary best messages for that goal use neutral rather than
yellow terminal colouring:

```toml
[local]
search = "population"
objective = "earliest-arrival"
target-frame = 442
dead-end = true
```

This flag **does not** disable checkpoint storage, Auto/Local/Hybrid search,
future seeding, merge, repair, retiming, or canonical completion verification.
To restore yellow pending-state reporting, omit the flag or set it to `false`.
