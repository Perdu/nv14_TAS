# v4.1 layered configs and Local splice goal import (2026-10-12)

The original v4 native/Cython and physics code is unchanged. This update modifies
Python CLI/TOML configuration parsing only, adds seven configuration regression
tests, and documents `--config` layering plus Auto's `--goal-config` switch.

**Native rebuild:** `python build_native.py` — succeeded.

**Complete unfiltered regression suite:** `python -m pytest -q`

```text
2149 passed, 2 skipped, 38 warnings, 245 subtests passed in 262.60s (0:04:22)
exit status: 0
```

The 38 warnings are Python 3.13 multiprocessing `fork()` deprecation warnings.
No test failures. The focused TOML + Auto endpoint group passed 36/36.

**End-to-end CLI smoke test:** with the v4 Auto default TOML containing
`objective = "speedrun"`, `runs = 0` and an unchanged `[local]` splice TOML
containing `objective = "max-x"`, the command below ran with a finite round
override and independently verified the endpoint output:

```shell
python optimize_replay.py auto examples/91-1.txt \
  --config default.toml --goal-config splice.toml \
  --auto-runs 1 --output result.txt
```

It evaluated 40 distinct candidates; the verified endpoint X at frame 25
improved from 68.9971678603 to 74.0513611109. These are synthetic smoke-test
results, not a representative benchmark. The exact original `[local]` splice
shape with `earliest-arrival`, target rectangle, secondary max-y and multiple
required interactions was also checked through the configuration parser.

**Compatibility:** a regular `--config` does not automatically copy its `[local]`
goal into Auto. `--goal-config` is an explicit goal-only import, ignoring Local
population/window search budgets and settings. Explicit CLI options override
both sources. Endpoints still require finite positive `--auto-runs`.

---

# v4 Auto endpoint objectives — final verification (2026-10-12)

The v4 code adds Local-compatible endpoint goals to the Auto CLI, using a
shared `[goal]` TOML section and the existing native endpoint evaluator.
No physics, search kernel, Cython interface, or checked-in generated C source
was modified relative to the cleaned v3 release.

**Release build:** `python build_native.py` — successful.

**Complete regression gate:** `python -m pytest -q`

```
2142 passed, 2 skipped, 38 warnings, 245 subtests passed in 250.86s (0:04:10)
```

Warnings: Python 3.13 `multiprocessing` deprecation warnings about `fork()`
from multi-threaded processes. There were no test failures.

**Selected focused regressions:** 218 passing tests, including new Auto
endpoint/search/TOML tests and existing Auto/Local objective/CLI tests.

**End-to-end smoke checks:**

- A `[goal] earliest-arrival` configuration ran in both Auto and Local.
  Both found frame-29 arrivals from a frame-31 sample reference under their
  respective exploration budgets.
- Endpoint Auto with 2 workers over 2 rounds verified an improved replay.
- `min-distance` Auto improved a sample score from approximately -993.12 to
  -97.37 (negative squared-distance-style objective) at target frame 30.
- Partial routes with no level exit were eligible under `checkpoint` and
  rejected under `complete`. A canonical full completion was accepted.
- Replays were packed and independently verified with `verify_endpoint`
  before acceptance and output.

**Compatibility:** complete-run `speedrun`/`highscore` Auto continues to reject
endpoint-only flags by default; the existing full-run optimiser remains
unchanged. Existing Local window/population behavior is preserved.

---

# Hybrid repair follow-up: test report

## Reproduction

From this source directory:

```shell
python build_native.py
python -m pytest -q --tb=short
python benchmarks/hybrid_repair_smoke.py
```

The baseline source ZIP was rebuilt and the **entire** pytest suite executed.
It finished in 498.77 s with 2,111 passes, 7 failures, 2 skips, and 245
passing subtests. All seven failures were independent of the native search:

- Five tests mistakenly required `PIL` to be absent from *all* Python startup
  modules. The hosted Python environment pre-imports Pillow through
  `/opt/python-hooks/sitecustomize.py` before application code executes.
  The corrected tests check for modules newly imported by the subject module.
- Two tests used 792-pixel-wide unscaled offsets to crop output from a video
  API whose default scale is 2 (1584 x 1200). Scaled coordinates find the
  expected black userlevel credit glyphs. Both corrected tests pass.

The new functionality is disabled by default, except the input ordering when
native beam mode explicitly enables it. Source changes add a bounded exact
query memo, progressive repair horizons with one shared tick budget, and
state-aware ordering without rejecting any legal input.

Focused tests of the new implementation and native beam passed, as did an
86-test Auto/CLI/splicing/population regression group. The synthetic benchmark
independently replay-verifies each generated native endpoint.

## Release-gate full-suite result

**PASS.** Fresh rebuild and complete unfiltered pytest suite on the final source:

```text
python -m pytest -q --tb=short
2124 passed, 2 skipped, 38 warnings, 245 subtests passed in 457.49s (0:07:37)
exit status: 0
```

Zero failures. The 38 warnings were `DeprecationWarning` messages emitted by
Python 3.13's multiprocessing `fork()` path in a multithreaded process, in
`tests/test_local_velocity_windows.py`, `tests/test_replay.py`,
`tests/test_sparse_windows.py`, and `tests/test_v267.py`. No tests were excluded
from this release-gate run.

The synthetic benchmark is a correctness/sensitivity check, **not** a speedup
claim for real game levels. Native nested multithreading and cross-query
global frontier deduplication are deliberately not implemented: the latter
requires stronger equivalence guarantees for changing search constraints;
the former should first be justified by a CPU-throughput benchmark of the
existing multiprocessing architecture.

## Local sliding-window hybrid (v3) release gate

Built the native extension with `python build_native.py` and ran the complete
unfiltered test suite after integrating the local search options:

```text
python -m pytest -q --disable-warnings
2130 passed, 2 skipped, 38 warnings, 245 subtests passed in 244.41s (0:04:04)
exit status: 0
```

The new `tests/test_local_hybrid_windows.py` covers configuration bounds and
rejection in population mode, progressive horizon geometry, shared native
tick accounting, cache initialization, legacy DFS defaults, and Python
replay-verified beam improvements in both direction-only and all-input
local window search.

CLI smoke-test command (synthetic open-air source, target tick 10):

```shell
python optimize_replay.py local /mnt/data/local_hybrid_cli_input.txt \
  --target-frame 10 --range 2:7 --window 6 --passes 1 \
  --local-beam-width 16 --local-search-cache-entries 4 \
  --local-adaptive-windows --local-search-ticks 600 \
  --workers 1 --python-resimulate --output /mnt/data/local_hybrid_cli_output.txt
```

The final verified score improved from 100.0 to 103.186065008804206,
changed precisely frames 2..7, and used a total of 600 native simulated
ticks across three horizons. This is a functional smoke test and not an
assertion of performance on actual TAS replays.

## Native Cython-generated source cleanup verification (v3 reviewable)

This release replaces the Cython-3.2.4-generated `native/_nv14_native.c` from
v3 with the **original Cython 3.3.0-generated file**, plus two small,
explicitly hand-maintained ABI compatibility edits. This is **not** a fresh
Cython 3.3.0 regeneration: that compiler was unavailable here. The authoritative
`native/_nv14_native.pyx` matches v3 and describes the new fields. See
`docs/CYTHON_GENERATED_SOURCE.md` for regeneration instructions.

Original generated C to cleaned generated C: **42 inserted source lines** in
two locations, instead of thousands of lines from a compiler-version change.
`nv14_engine.py` and `native/nv14_core.c` remain byte-for-byte unchanged from
the original ZIP; v3's native search `.c`/`.h` and `.pyx` are unchanged.

Freshly rebuilt native extension from this cleaned source:

```text
python build_native.py
exit status: 0
```

Focused feature tests:

```text
python -m pytest -q tests/test_native_beam_search.py tests/test_adaptive_repair_cache.py tests/test_local_hybrid_windows.py tests/test_auto_v245.py
22 passed in 0.46s
```

Complete regression suite on the rebuilt cleaned native extension:

```text
python -m pytest -q
2130 passed, 2 skipped, 38 warnings, 245 subtests passed in 237.56s (0:03:57)
exit status: 0
```

Synthetic comparison (`python benchmarks/hybrid_repair_smoke.py`) completed with
independent replay verification for DFS, beam-16, and beam-32. Those smoke
results are not evidence of actual-map speedups.

The three review patches were independently applied in sequence against the
original project source and their resulting contents compared against the
cleaned v3 source. Compiled binaries remain excluded from the source archive.
