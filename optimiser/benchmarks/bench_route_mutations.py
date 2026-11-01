"""Microbenchmark native route operators against the exact Python fallback.

Run from optimiser/: python benchmarks/bench_route_mutations.py
The times are isolated mutation-generation costs, not total optimiser speed.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nv14_route_mutations as route
from nv14_engine import InputFrame
from nv14_native import require_native
from tests.test_random_splice import _baseline


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repetitions', type=int, default=100)
    args = ap.parse_args()
    if args.repetitions < 1:
        ap.error('--repetitions must be positive')
    require_native()
    neutral, right, left = InputFrame(), InputFrame(right=True), InputFrame(left=True)
    jump = InputFrame(right=True, jump=True)
    body = (right,) * 60 + (neutral,) * 2 + (right,) * 70 + (left,) * 5 + (right,) * 50
    body += (jump,) * 3 + (right,) * 50 + (jump,) * 4 + (right,) * 45 + (neutral,) * 8
    frames = (body * 3)[:800]
    level, _, _ = _baseline()
    donor = list(frames)
    donor[90:95] = (left,) * 5
    donor = tuple(donor)

    original = route._native_route_module
    try:
        for name in route.HIGH:
            measurements = []
            for fast in (False, True):
                route._native_route_module = original if fast else lambda: None
                started = perf_counter()
                for seed in range(args.repetitions):
                    route.propose(name, frames, rng=random.Random(seed),
                                  start=8, end=len(frames)-9, donor=donor,
                                  level=level)
                measurements.append((perf_counter()-started)/args.repetitions * 1e6)
            print(f'{name:20} Python {measurements[0]:9.1f} us  '
                  f'native {measurements[1]:9.1f} us   '
                  f'speedup {measurements[0]/measurements[1]:5.2f}x')
    finally:
        route._native_route_module = original


if __name__ == '__main__':
    main()
