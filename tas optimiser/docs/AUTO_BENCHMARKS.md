# Autonomous optimiser design and supplied-pair benchmarks

## v2.77 native Auto performance gates

The v2.77 release gate compares freshly built v2.76 and v2.77 source trees on
one pinned CPU with `PYTHONHASHSEED=0`. The native extensions in those
historical releases were compiled by their bundled `build_native.py` scripts
with GCC `-O3` and strict floating-point semantics. Times are the median of
three independent processes and remain
workload- and machine-specific; the output and terminal result are the stable
correctness gates.

| Workload | v2.76 median | v2.77 median | Speed-up | Fidelity gate |
|---|---:|---:|---:|---|
| older 91-0, seed 100, beam 32, 300 macro evaluations | 3.102497 s | 1.265443 s | 2.45x | finish 298; identical mutations, encoded replay and SHA-256 |
| real 44-0 deep direction repair, 10,000 simulated-tick budget | 169.168 ms | 28.357 ms | 5.97x | identical selected edit, encoded replay, failure/target frames and charged budget |

The 91-0 output is 390 bytes with SHA-256
`e236613fa59b5e583f8fce212635864f82f67753f2deafc6f12696d4a3643a10`.
Its winning mutations are `horizontal pulse 257+1=+0` and `boundary 269 -1`.
The repair result has SHA-256
`dd57fbe94012280689049465dc86241d776fd089e47281830ef0616df208f1088`;
both versions consume exactly 10,000 candidate ticks. Native mechanics counters
are not required to match because v2.77 explicitly accounts for batched native
branches and checkpoint reuse, while the policy-level result must match.

Reproduce the public 91-0 comparison with:

```bash
python -m tools.benchmark_autonomous examples/benchmark/Improved_TASes.txt \
  --tick 299 --iterations 300 --beam 32 --seed 100 --max-retime 3
```

## v2.9 merge gates

The v2.9 merge is required to retain both complementary real-search results:

| Gate | Fidelity/configuration | Required result | Observed v2.9 |
|---|---|---:|---:|
| older 00-2 (343) | enemies on, seed 0, beam 32, 200 macro evaluations | <=342 | 342 in 13.0 s |
| older 91-0 (299) | enemy flag immaterial (thwomps are always simulated), seed 100, beam 32, 300 macro evaluations | <=298 | 298 in 41.3 s |

The corresponding v2.8 baselines in the same runtime were 49.3 seconds for the
faster `(1)` build's 00-2 result and 51.8 seconds for the integrated build's
91-0 result.  The v2.9 00-2 repair performed 529,878 local simulation steps,
down from 2,704,581, because sensitivity trials branch from cached exact prefix
states. Times are illustrative; terminal ticks and freshly verified lineages
are the stable gates.

A 1,000-evaluation 00-2 run with deep repair and the deterministic pulse sweep
disabled used about 28 MiB peak RSS in v2.9, versus about 101 MiB in the faster
v2.8. The important change is structural: compact seen keys and bounded
finalists replace the old unbounded archive of dense traces/full replay tuples.

The 00-2 lineage is:

```text
jump pulse 0 shift +1 hold -1
direction repair near 28
suffix 186 -1
direction repair near 187 (shifted missed jump 187)
```

The 91-0 lineage is the one-frame horizontal neutral pulse at frame 257. The
same source also has two equivalent direct 298 edits: frame 255 -> left and
frame 256 -> left.

Run the reproducible verifier/benchmark against the supplied pair file with:

```bash
python -m tools.benchmark_autonomous examples/benchmark/Improved_TASes.txt --verify-only
python -m tools.benchmark_autonomous examples/benchmark/Improved_TASes.txt \
  --tick 343 --iterations 200 --beam 32 --seed 0
```

## What the paired TASes show

`examples/benchmark/Improved_TASes.txt` contains six improved/older pairs; the improved replay is
first in each pair. Their declared completion lengths are:

| Level | Older | Improved | Gain | Held-input transitions old -> improved |
|---|---:|---:|---:|---:|
| 00-0 the motherlode | 337 | 335 | 2 | 32 -> 56 |
| 00-1 cloud city | 302 | 301 | 1 | 25 -> 27 |
| 00-2 all about thwumps | 343 | 342 | 1 | 20 -> 24 |
| 00-4 lockness | 162 | 161 | 1 | 11 -> 15 |
| 25-2 leap of faith | 311 | 310 | 1 | 20 -> 35 |
| 91-0 quicky | 299 | 296 | 3 | 13 -> 29 |
| **Total** | **1754** | **1745** | **9** | **121 -> 186** |

Only 00-2 has a long, informative, exactly shifted suffix: improved inputs
174-341 equal older inputs 175-342. Its player state is bit-exactly one frame
ahead for 155 consecutive simulated states late in the run, although one thwomp
remains out of phase. The other apparent terminal suffix matches are constant
final holds and are not evidence for a globally shifted trajectory.

Across all pairs there are 80 same-index changed regions. Fifty-three are one
frame long and 65 are at most two frames long. One-frame neutral runs rise from
4 in the older replays to 21 in the improved replays. That evidence is why v2.8
combines suffix retiming with local boundary edits and heavily weighted short
pulse mutations.

## Reproducible real-pair smoke benchmark

The older 91-0 replay (299) provides a useful autonomous smoke benchmark because
its known three-frame improvement is built mainly from sparse horizontal pulses,
not a shifted suffix. With the annotated `299:` line extracted to an ordinary
combined level/replay file, this command was run in the v2.8 build:

```bash
python optimize_replay.py auto 91-0-old.txt \
  --iterations 300 \
  --beam 32 \
  --max-retime 3 \
  --seed 100 \
  --output 91-0-auto.txt
```

Two independent runs produced the same freshly verified 298-frame completion
at iteration 60, with byte-identical output and normalized diagnostics. The
winning lineage composed two exact local repairs:
`local-direction 192+4 gain=2.393`, then
`local-direction 250+4 gain=13.17`. After packing and decoding, the 298-input
output again completes at tick 298. Its SHA-256 is
`5567b077575cc1ece4f7211840f1c28d9fa0586b57f10a7f20908779e8e6bc31`.
Seed 1 found a different verified 298-frame output at iteration 44 with the
single winning mutation `pulse 257+1=..`; seeds 7, 42 and 12345 also improved
within the same 300-iteration budget. The known supplied 296-frame TAS was not
reached in these short runs. This demonstrates autonomous search on a real
supplied replay, not that 300 iterations reproduce the full known improvement.

The older 00-2 replay was also run for 500 iterations with seed 12345, beam 24
and one immediate repair attempt. It remained at 343. This is expected to be a
harder repair problem: directly retiming the late suffix kills the player and
the known improved prefix includes a substantially earlier jump release. Longer
runs, a wider repair span, or future sparse free-state repair may recover it.

## Verification convention

All twelve supplied replays reach the exit on the immediately following neutral
simulation tick. Thus a declared 299-frame replay reports autonomous completion
frame 299, and a 298 result is encoded with 298 held-input frames. Every record
promotion and final output is re-simulated from the level's initial state; an
alignment score or frontier candidate by itself is never accepted as a result.
