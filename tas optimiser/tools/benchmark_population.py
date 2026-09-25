"""Compare equal-work local population searches against an extracted baseline.

Run from v4.27::

    python -m tools.benchmark_population --baseline-root ../v4.26 --output results.json

Both source trees need their own built native extension. Each timed workload
uses the same seed, input, proposal budget and worker count. Full result hashes
must match; setup, imports, warmup and process startup are excluded from timing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time


def _worker(root: Path, iterations: int, repetitions: int) -> dict:
    sys.path.insert(0, str(root))
    from dataclasses import asdict, is_dataclass
    from nv14_checkpoint import OPTIMISER_VERSION
    from nv14_endpoint import EndpointEvaluator, EndpointGoal
    from nv14_engine import InputFrame, parse_level_string
    from nv14_native import backend_info
    from nv14_objectives import AxisWindow, resolve_interaction_target, resolve_interaction_requirement
    from nv14_population import PopulationConfig, optimise_local_population
    from nv14_replay import parse_combined_level_replay, decode_complex_replay, editable_frames

    def canonical(value):
        if is_dataclass(value):
            return canonical(asdict(value))
        if isinstance(value, bytes):
            return value.hex()
        if isinstance(value, dict):
            return {str(k): canonical(v) for k, v in value.items()}
        if isinstance(value, (set, frozenset)):
            return sorted((canonical(v) for v in value), key=lambda x: json.dumps(x, sort_keys=True))
        if isinstance(value, (list, tuple)):
            return [canonical(v) for v in value]
        return value

    def digest(result):
        return hashlib.sha256(json.dumps(canonical(result), sort_keys=True).encode()).hexdigest()

    tiles = ["0"] * 713
    for x in range(31):
        tiles[x * 23 + 5] = "1"
    tile_text = "".join(tiles)
    def floor(objects=""):
        return parse_level_string(tile_text + "|5^396,134" + ("!" + objects if objects else ""),
                                  simulate_enemies=True)
    neutral = (InputFrame(),) * 512
    region = (180, 230, 100, 140)
    cases = [("arrival_256", floor(), neutral,
              EndpointGoal(255, "earliest-arrival", target_region=region), ((0, 255),))]
    objects = floor("0^200,134!0^250,134!11^600,134,300,134")
    cases.append(("interaction_256", objects, neutral,
                  EndpointGoal(255, "earliest-interaction",
                               interaction_target=resolve_interaction_target(objects, "gold:any")), ((0, 255),)))
    cases.append(("arrival_constraints_256", objects, neutral,
                  EndpointGoal(255, "earliest-arrival", target_region=region,
                               vx_window=AxisWindow(-4, 0),
                               required_interactions=(resolve_interaction_requirement(objects, "switch:0"),)),
                  ((0, 255),)))
    cases.append(("fixed_long_prefix_suffix", floor(), (InputFrame(),) * 4096,
                  EndpointGoal(2303, "max-x"), ((2048, 2303),)))
    for name, filename in (("arrival_00_1_enemies", "example_00_1_speedrun.txt"),
                           ("arrival_44_0_objects", "example_44_0.txt"),
                           ("arrival_06_4_enemies", "example_06_4_floorguards.txt")):
        combined = parse_combined_level_replay((root / "tests" / filename).read_text())
        level = parse_level_string(combined.level_string, simulate_enemies=True)
        frames = tuple(editable_frames(decode_complex_replay(combined.replay_string).frames))
        deadline = min(299, len(frames) - 1)
        sample_frame = deadline * 2 // 3
        sample = EndpointEvaluator(level, EndpointGoal(sample_frame)).evaluate(frames)
        goal = EndpointGoal(deadline, "earliest-arrival", arrival_start=deadline // 4,
                            target_region=(sample.x - 6, sample.x + 6, sample.y - 6, sample.y + 6),
                            vx_window=AxisWindow(sample.vx - 2, sample.vx + 2))
        cases.append((name, level, frames, goal, ((deadline // 4, deadline),)))

    config = PopulationConfig(iterations=iterations, beam=32, workers=1, repair_steps=16,
                              seed=17, top_results=3)
    results = []
    for name, level, frames, goal, ranges in cases:
        warm = optimise_local_population(level, frames, goal=goal, frame_ranges=ranges, config=config)
        expected = digest(warm)
        seconds = []
        for _ in range(repetitions):
            start = time.perf_counter()
            actual = optimise_local_population(level, frames, goal=goal, frame_ranges=ranges, config=config)
            seconds.append(time.perf_counter() - start)
            if digest(actual) != expected:
                raise RuntimeError(f"non-deterministic population result: {name}")
        results.append({"name": name, "replay_frames": len(frames), "target_frame": goal.target_frame,
                        "editable_ranges": ranges, "evaluations": warm.evaluations,
                        "winner_frame": warm.candidates[0].evaluation.frame if warm.candidates else None,
                        "result_sha256": expected, "seconds": seconds,
                        "median_seconds": statistics.median(seconds)})
    return {"version": OPTIMISER_VERSION, "native": backend_info(), "cases": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--source-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.iterations < 1 or args.repetitions < 1:
        parser.error("iterations and repetitions must be positive")
    if args.source_root:
        print(json.dumps(_worker(args.source_root.resolve(), args.iterations, args.repetitions)))
        return
    if args.baseline_root is None:
        parser.error("--baseline-root is required")
    script = Path(__file__).resolve()
    versions = []
    environment = dict(os.environ, PYTHONHASHSEED="0")
    for root in (args.baseline_root.resolve(), script.parents[1]):
        result = subprocess.run([sys.executable, str(script), "--source-root", str(root),
                                 "--iterations", str(args.iterations), "--repetitions", str(args.repetitions)],
                                env=environment, check=True, text=True, capture_output=True)
        versions.append(json.loads(result.stdout))
    comparisons = []
    for old, new in zip(versions[0]["cases"], versions[1]["cases"]):
        if old["name"] != new["name"] or old["result_sha256"] != new["result_sha256"]:
            raise RuntimeError(f"baseline/current full result mismatch: {old['name']}")
        comparisons.append({"name": old["name"], "baseline_seconds": old["median_seconds"],
                            "current_seconds": new["median_seconds"],
                            "speedup": old["median_seconds"] / new["median_seconds"],
                            "identical_results": True})
    report = {"python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
              "iterations_per_worker": args.iterations, "repetitions": args.repetitions,
              "workers": 1, "beam": 32, "repair_steps": 16, "seed": 17,
              "timing_scope": "whole single-worker search, excluding imports, warmup and process startup",
              "versions": versions, "comparison": comparisons}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(comparisons, indent=2))


if __name__ == "__main__":
    main()
