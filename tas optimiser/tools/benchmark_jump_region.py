"""Measure native jump tracking on identical replays, with reference parity.

Run after building: python3 -m tools.benchmark_jump_region --output results.json
Simulation/scoring only; no mutation, cache hits, imports or build time included.
"""
from dataclasses import replace
import argparse
import json
from pathlib import Path
import platform
import statistics
import sys
import time

from nv14_engine import InputFrame, parse_level_string
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_native import backend_info
from nv14_objectives import resolve_interaction_target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluations', type=int, default=200)
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if min(args.evaluations, args.repetitions) < 1:
        parser.error('evaluations and repetitions must be positive')
    tiles = ['0'] * 713
    for x in range(31):
        tiles[x * 23 + 5] = '1'
    level = parse_level_string(''.join(tiles) + '|5^396,134!0^700,134', simulate_enemies=True)
    frames = tuple(InputFrame(jump=i in (5, 60, 120)) for i in range(256))
    cases = [EndpointGoal(255),
             EndpointGoal(255, 'earliest-arrival', target_region=(700, 720, 120, 140)),
             EndpointGoal(255, 'earliest-interaction',
                          interaction_target=resolve_interaction_target(level, 'gold:0'))]
    rows = []
    for goal in cases:
        for label, region in (('disabled', None), ('satisfied', (390, 402, 130, 138)),
                              ('unsatisfied', (100, 120, 130, 138))):
            configured = replace(goal, require_jump_region=region)
            evaluator = EndpointEvaluator(level, configured, frames)
            key = evaluator._source_key
            expected = evaluator.evaluate_reference(frames)
            assert evaluator._evaluate_packed(key, frames) == expected
            falls_back = evaluator._native_plan.scan(evaluator._prefix, key)[-1]
            times = {}
            for mode in ('native', 'reference'):
                call = ((lambda: evaluator._evaluate_packed(key, frames)) if mode == 'native'
                        else (lambda: evaluator.evaluate_reference(frames)))
                call()
                seconds = []
                for _ in range(args.repetitions):
                    start = time.perf_counter()
                    for _ in range(args.evaluations):
                        result = call()
                    seconds.append(time.perf_counter() - start)
                    assert result == expected
                times[mode] = {'seconds': seconds, 'median_seconds': statistics.median(seconds)}
            rows.append({'objective': goal.objective, 'requirement': label,
                         'ticks': len(frames), 'jump_event': expected.jump_event,
                         'reference_fallback': falls_back, 'identical_reference_result': True, **times})
    report = {'python': sys.version, 'platform': platform.platform(), 'native': backend_info(),
              'evaluations': args.evaluations, 'repetitions': args.repetitions,
              'timing_scope': 'packed endpoint evaluation on identical 256-tick replays; no result-cache hits',
              'cases': rows}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
