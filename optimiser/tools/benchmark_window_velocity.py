"""Compare disabled/enabled velocity checks against a separately built v4.28.

python -m tools.benchmark_window_velocity --baseline-root ../v4.28 \
    --repetitions 7 --batch-size 100 --output docs/benchmarks/v4.29_window_velocity.json

Uses the existing local benchmark's four workloads, one warmup and one worker.
Each timed repetition batches 100 searches by default to reduce timing noise.
Wide bounds intentionally retain identical results and native search counters
so enabled-check overhead is measured without changing the search workload.
Run without other CPU-heavy jobs. Timings are host/workload dependent.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
from pathlib import Path
import subprocess
import sys


WORKER = """
import json, sys, time, statistics
import tools.benchmark_local as benchmark
from nv14_objectives import AxisWindow
repetitions, mode, batch_size = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
scenarios = benchmark._scenarios()
rows = []
for scenario in scenarios:
    if mode == "enabled":
        scenario.kwargs.update(vx_window=AxisWindow(-100, 100),
                               vy_window=AxisWindow(-100, 100))
    expected = benchmark._run_once(scenario, workers=1)
    timings = []
    for _ in range(repetitions):
        start = time.perf_counter()
        for _ in range(batch_size):
            actual = benchmark._run_once(scenario, workers=1)
            assert actual == expected, scenario.name
        timings.append((time.perf_counter() - start) / batch_size)
    rows.append(dict(name=scenario.name, description=scenario.description,
                     result_checksum=expected[0], counters=expected[1],
                     visited_nodes=expected[1].get("nodes", 0),
                     evaluated_leaves=expected[1].get("leaves", 0),
                     median_seconds=statistics.median(timings),
                     repetition_seconds=timings))
print(json.dumps(dict(repetitions=repetitions, batch_size=batch_size,
                      workers=1, scenarios=rows)))
"""


def run(root: Path, repetitions: int, batch_size: int, mode: str) -> dict:
    result = subprocess.run([sys.executable, "-c", WORKER, str(repetitions), mode, str(batch_size)],
                            cwd=root, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions < 1 or args.batch_size < 1:
        parser.error("repetitions and batch-size must be positive")
    current = Path(__file__).resolve().parents[1]
    variants = {
        "baseline": (args.baseline_root.resolve(), "disabled"),
        "current_disabled": (current, "disabled"),
        "current_enabled": (current, "enabled"),
    }
    report = dict(python=sys.version, platform=platform.platform(),
                  method="Alternating version order per repetition; batches; one warmup per workload; one worker; equal-result/counter checks")
    labels = list(variants)
    for repetition in range(args.repetitions):
        # Rotate and reverse execution order to reduce host/frequency drift.
        order = labels[repetition % 3:] + labels[:repetition % 3]
        if repetition % 2:
            order.reverse()
        for label in order:
            root, mode = variants[label]
            sample = run(root, 1, args.batch_size, mode)
            if label not in report:
                report[label] = sample
                report[label]["repetitions"] = args.repetitions
            else:
                for stored, row in zip(report[label]["scenarios"], sample["scenarios"], strict=True):
                    for field in ("name", "result_checksum", "counters"):
                        if stored[field] != row[field]:
                            raise RuntimeError(f"non-deterministic {label}: {field}")
                    stored["repetition_seconds"].extend(row["repetition_seconds"])
                    stored["median_seconds"] = statistics.median(stored["repetition_seconds"])
    comparisons = []
    for old, new, enabled in zip(report["baseline"]["scenarios"],
                                  report["current_disabled"]["scenarios"],
                                  report["current_enabled"]["scenarios"], strict=True):
        for field in ("name", "result_checksum", "counters"):
            if not old[field] == new[field] == enabled[field]:
                raise RuntimeError(f"unequal work/results for {old['name']}: {field}")
        comparisons.append(dict(name=old["name"],
                                disabled_change_percent=100 * (new["median_seconds"] / old["median_seconds"] - 1),
                                enabled_vs_disabled_percent=100 * (enabled["median_seconds"] / new["median_seconds"] - 1)))
    report["comparisons"] = comparisons
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(comparisons, indent=2))


if __name__ == "__main__":
    main()
