# Multiple required jumps — verification report

This release is based on `bruteforcer_v4_2_local_neutral_tail.zip`.

## Scope

- `[[local.require-jumps]]`, `[[goal.require-jumps]]`, and repeated CLI `--require-jumps`
- `auto --goal-config` imports unchanged Local splice files
- Conjunctive exact-jump constraints, earliest/fixed-frame scoring, independent Python replay verification
- Local checkpoint/restart persistence and state diversity
- No changes to C/Cython, native physics, or game rendering
- Old singular jump-region syntax preserved

## Completed checks

- Native build succeeded (Python 3.13).
- 84 focused new/existing jump, Auto, and configuration tests passed.
- Local and Auto end-to-end runs with a two-jump TOML passed and their packed output was independently verified.
- Two complete runs, each: **2,163 passed, 2 skipped, 1 failed** (245 subtests passed), at 266.60 s and 270.90 s respectively. The sole failure in each run was the pre-existing SIGINT/shutdown test `tests/test_native_jump_search.py::test_threaded_native_jump_search_exits_promptly_after_sigint`, which times out at 5 s in the full-suite environment. The test does not exercise the endpoint objective implementation and all native/Cython search files are unchanged from v4.2.
- The failing native jump-pattern SIGINT test **passed when rerun in isolation** (1/1 in 1.35 seconds). No changes to that unrelated test or the native engine are included in this release.
- 38 existing Python 3.13 multiprocessing fork deprecation warnings appeared.

## Performance

Multiple requirements use the existing native state's per-tick stepping from Python rather than changing the compiled native endpoint plan. In a small synthetic 170-frame repeated evaluation, the compiled single-jump scan averaged about 0.023 ms/evaluation and the multi-jump scan averaged about 0.104 ms/evaluation on this machine; expect slower evaluation for multi-jump goals until a compiled multi-jump plan is justified.
