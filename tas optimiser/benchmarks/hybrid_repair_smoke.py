"""Deterministic *synthetic* A/B smoke test for native DFS and repair beam.

Run from the project root: python benchmarks/hybrid_repair_smoke.py
This checks endpoint parity, but is NOT a representative performance claim for
real TAS levels; use real replay windows and identical seeds/budgets for those.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nv14_engine import InputFrame, parse_level_string
from nv14_objectives import evaluate, objective_function
from nv14_search import NativeSearchSession, SearchSpec, OBJECTIVE_MAX_X


def main() -> None:
    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = (InputFrame(),) * 9
    session = NativeSearchSession(level)
    base = SearchSpec(
        mutable_frames=(0, 1, 2, 3, 4),
        choices=((InputFrame(), InputFrame(left=True),
                  InputFrame(right=True)),) * 5,
        target_frame=6,
        objective=OBJECTIVE_MAX_X,
        max_simulated_ticks=500,
        incumbent_score=float("-inf"),
    )
    print("method    ticks  leaves  dedup  width_pruned  score   seconds  verified")
    for name, spec in (
        ("DFS", base),
        ("beam16", replace(base, beam_width=16, beam_adaptive_inputs=True)),
        ("beam32", replace(base, beam_width=32, beam_adaptive_inputs=True)),
    ):
        start = perf_counter()
        result = session.search(frames, spec)
        seconds = perf_counter() - start
        verified = False
        if result.improved:
            patched = list(frames)
            for index, value in zip(spec.mutable_frames, result.best_inputs, strict=True):
                patched[index] = value
            reference = evaluate(level, patched, spec.target_frame,
                                 objective_function("max-x"))
            verified = reference.feasible and abs(result.score - reference.score) < 1e-9
        print(f"{name:8} {result.stats.simulated_ticks:5} "
              f"{result.stats.evaluated_leaves:6} "
              f"{result.stats.deduplicated_prunes:6} "
              f"{result.stats.beam_width_prunes:13} "
              f"{result.score:7.3f} {seconds:8.4f} {verified}")
        if result.improved and not verified:
            raise RuntimeError(f"{name} result failed independent replay verification")


if __name__ == "__main__":
    main()
