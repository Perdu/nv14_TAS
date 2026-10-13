# Experimental native beam repair (opt-in)

Native C search ABI: **5** (was 4). Regenerate the native extension after updating:

    python build_native.py

The checked-in `native/_nv14_native.c` retains the original Cython 3.3.0
generated output, with a small, clearly labeled hand-maintained C ABI bridge
for the three beam parameters and the one beam statistic. Cython 3.3.0 was
not available in the build environment; the mismatched Cython 3.2.4
regeneration in the earlier release has been discarded. The `.pyx` remains
the source of truth. See `docs/CYTHON_GENERATED_SOURCE.md` for precise
regeneration instructions. The source archive intentionally contains no
platform-specific precompiled `.so` files.

Auto CLI, using your usual TAS arguments:

    python optimize_replay.py auto run.txt --auto-repair-beam-width 32 --auto-repair-local-steps 2000

For a controlled comparison, rerun with exactly the same seed, input, and
simulation budgets, but `--auto-repair-beam-width 0` (original DFS).

The beam applies to native Cartesian direction/all-input repair searches only.
It scores intermediate states with the current endpoint objective and progress
rewards, uses optional soft state-dependent input priorities, and deduplicates
complete exact emulator state including required-jump history. No approximate
state merges; no guarantee of global optimality. Existing final replay
verification, splice handling, and evolutionary search remain unchanged.

Controls via `SearchSpec`: `beam_width` (0..4096, default 0),
`beam_edit_penalty` (>=0), and `beam_adaptive_inputs` (bool).
`SearchStats.beam_width_prunes` counts frontier candidates lost to the width cap;
`deduplicated_prunes` counts exact duplicates.

Tests run with a newly built CPython 3.13 native extension:

    python -m pytest -q tests/test_native_beam_search.py tests/test_native_local_search.py tests/test_auto.py tests/test_splice_repair.py tests/test_auto_v245.py

65 passed. Another selected group had 67 passed / 2 skipped. Full suite
was started but not completed (simulation-heavy tests exceeded the run limit).
Neither exhaustive speedup testing nor game-runtime parity verification has
been performed on your actual TAS routes.

## Follow-on implementation: bounded reuse, adaptive horizons, input ordering

- `--auto-repair-cache-entries N` (0..64, default 0) enables **exact result
  memoisation**, keyed by immutable `SearchSpec` and the full replay input
  prefix through `target_frame`, within a single level-owned native session.
  Cached successes and completed failures are safe to reuse; interrupted or
  tick-budget-exhausted queries are never cached. Search statistics on a cache
  hit charge zero simulated ticks (and expose `cache_hits=1`). This is not a
  persistent per-state transposition table across different repair targets.
- `--auto-adaptive-repair-windows` (off by default) selects 2, 4, and full
  windows in ascending order, each consuming part of the same repair budget.
  Both direction-only and all-input native repairs support the option. Search
  correctness is still decided by the original endpoint and full-TAS verifier.
- When `beam_adaptive_inputs` is true, the C kernel stably **reorders** up to
  32 legal options based on target displacement, braking and jump context,
  without pruning any choice. It is a search-budget prioritisation policy.

Native state-frontier dedup remains bounded within each beam. A truly global
cross-window state transposition table needs proofs about different remaining
replay suffixes, objectives and interaction constraints; do not conflate that
with the safe exact-query cache. Likewise, native intra-repair threading is
not enabled: run a CPU saturation benchmark first, because the existing
multi-process workers already consume parallelism.

Run `python -m pytest -q tests/test_adaptive_repair_cache.py` after building.

### Deterministic smoke benchmark

`python benchmarks/hybrid_repair_smoke.py` compares DFS with beam widths 16 and
32 in a tiny synthetic level, capped at 500 simulated ticks per search. It
cross-checks every improved native endpoint against the independent Python
replay evaluator. It does *not* establish speedups on real maps, particularly
with enemy and moving-object state; real TAS route-window A/B benchmarking is
still required. Results will depend on the platform and input objective.

## Local-mode sliding-window integration (v3)

The `nv14_local.py` window search now passes `SearchSpec.beam_width`,
`beam_adaptive_inputs`, and `max_simulated_ticks` to the same native kernel
used by Auto. The per-trajectory native session optionally enables
`NativeSearchSession.configure_result_cache`. Short 2/4/full trailing
horizons share a **per-original-window** simulation allowance with a reserved
allocation for each remaining horizon. Cached searches count as zero ticks.
Only the exact native candidate selected at the endpoint can be accepted,
subject to existing hard constraints and optional independent Python replay
resimulation. Full replay output verification is unchanged.

CLI switches (windows only): `--local-beam-width`,
`--local-search-cache-entries`, `--local-adaptive-windows`, and
`--local-search-ticks`. The legacy local search is the default. Population
mode does not use the native Cartesian-window kernel and explicitly rejects
these switches, to prevent a misleading no-op.

Regression tests: `tests/test_local_hybrid_windows.py`.
