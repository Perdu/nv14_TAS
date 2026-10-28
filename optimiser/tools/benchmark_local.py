"""Benchmark representative local searches backed by the native kernel.

The timed operation is the public local-mode call, including SearchSpec
construction and result adaptation but excluding level/replay parsing.  Each
scenario is warmed once, then repeated with one worker so multiprocessing and
process-startup policy do not obscure native-kernel throughput.  Deterministic
replay/result checksums and search counters guard against timing unequal work.

Examples::

    python -m tools.benchmark_local
    python -m tools.benchmark_local --repetitions 7 --json
    python -m tools.benchmark_local --scenario open-air-direction
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from nv14_engine import InputFrame, Level, parse_level_string
from nv14_local import optimise_local_windows
from nv14_replay import decode_complex_replay, parse_combined_level_replay


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_COUNTER_PATTERN = re.compile(r"\b([a-z-]+)=(\d+)\b")


@dataclass(frozen=True, slots=True)
class LocalScenario:
    name: str
    description: str
    level: Level
    frames: tuple[InputFrame, ...]
    kwargs: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LocalScenarioTiming:
    name: str
    description: str
    local_inputs: str
    mutable_frames_per_window: int
    repetition_seconds: tuple[float, ...]
    median_seconds: float
    searches_per_second: float
    visited_nodes: int
    evaluated_leaves: int
    nodes_per_second: float
    leaves_per_second: float
    result_checksum: str


@dataclass(frozen=True, slots=True)
class LocalBenchmarkReport:
    repetitions: int
    workers: int
    scenarios: tuple[LocalScenarioTiming, ...]


def _positive_integer(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _combined_fixture(relative_path: str, *, simulate_enemies: bool) -> tuple[Level, tuple[InputFrame, ...]]:
    path = PROJECT_ROOT / relative_path
    combined = parse_combined_level_replay(path.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(
        combined.level_string,
        strict_shapes=True,
        simulate_enemies=simulate_enemies,
    )
    return level, tuple(replay.frames)


def _scenarios() -> tuple[LocalScenario, ...]:
    open_air = parse_level_string("0" * (31 * 23) + "|5^100,100")
    neutral = tuple(InputFrame() for _ in range(12))
    common_open_air = {
        "target_frame": 11,
        "range_start": 0,
        "range_end": 7,
        "objective_name": "max-x",
        "window_size": 8,
        "passes": 1,
        "window_order": "forward",
    }

    lockness_level, lockness_frames = _combined_fixture(
        "tests/example_lockness_missed_jumps.txt",
        simulate_enemies=False,
    )
    bounce_level, bounce_frames = _combined_fixture(
        "tests/example_44_0.txt",
        simulate_enemies=True,
    )
    return (
        LocalScenario(
            "open-air-direction",
            "one 8-frame ternary direction window with a four-frame suffix",
            open_air,
            neutral,
            {**common_open_air, "local_inputs": "direction"},
        ),
        LocalScenario(
            "open-air-all",
            "one 8-frame all-input window exercising inactive-jump pruning",
            open_air,
            neutral,
            {**common_open_air, "local_inputs": "all"},
        ),
        LocalScenario(
            "lockness-jump-repair",
            "a real replay window which repairs a previously missed jump press",
            lockness_level,
            lockness_frames,
            {
                "target_frame": 90,
                "range_start": 70,
                "range_end": 73,
                "objective_name": "min-x",
                "window_size": 4,
                "passes": 1,
                "local_inputs": "direction",
                "window_order": "forward",
            },
        ),
        LocalScenario(
            "bounceblock-heavy",
            "enemy-enabled 44-0 prefix with 120 mutable bounce blocks",
            bounce_level,
            bounce_frames,
            {
                "target_frame": 160,
                "range_start": 140,
                "range_end": 143,
                "objective_name": "max-x",
                "window_size": 4,
                "passes": 1,
                "local_inputs": "direction",
                "window_order": "forward",
            },
        ),
    )


def _search_counters(logs: list[str]) -> dict[str, int]:
    counters: dict[str, int] = {}
    for line in logs:
        if " search: " not in line or "nodes=" not in line:
            continue
        for name, value_text in _COUNTER_PATTERN.findall(line):
            counters[name] = counters.get(name, 0) + int(value_text)
    return counters


def _result_checksum(frames: list[InputFrame], score: float, state_key: object) -> str:
    digest = hashlib.sha256()
    for frame in frames:
        digest.update(
            bytes(
                (
                    int(frame.left),
                    int(frame.right),
                    int(frame.jump),
                    2 if frame.jump_trigger is None else int(frame.jump_trigger),
                )
            )
        )
    digest.update(score.hex().encode("ascii"))
    digest.update(repr(state_key).encode("utf-8"))
    return digest.hexdigest()


def _run_once(scenario: LocalScenario, *, workers: int) -> tuple[str, dict[str, int]]:
    logs: list[str] = []
    frames, evaluation = optimise_local_windows(
        scenario.level,
        scenario.frames,
        workers=workers,
        progress=logs.append,
        **scenario.kwargs,
    )
    return (
        _result_checksum(frames, evaluation.score, evaluation.state.state_key()),
        _search_counters(logs),
    )


def run_benchmark(
    *,
    repetitions: int = 5,
    workers: int = 1,
    selected: tuple[str, ...] = (),
) -> LocalBenchmarkReport:
    if repetitions < 1 or workers < 1:
        raise ValueError("repetitions and workers must be positive")
    scenarios = _scenarios()
    if selected:
        selected_set = set(selected)
        scenarios = tuple(item for item in scenarios if item.name in selected_set)
        unknown = selected_set - {item.name for item in scenarios}
        if unknown:
            raise ValueError("unknown scenario(s): " + ", ".join(sorted(unknown)))

    reports: list[LocalScenarioTiming] = []
    for scenario in scenarios:
        expected_checksum, expected_counters = _run_once(
            scenario,
            workers=workers,
        )
        timings: list[float] = []
        for _ in range(repetitions):
            started = time.perf_counter()
            checksum, counters = _run_once(scenario, workers=workers)
            elapsed = time.perf_counter() - started
            if checksum != expected_checksum:
                raise RuntimeError(
                    f"{scenario.name}: deterministic result checksum changed"
                )
            if counters != expected_counters:
                raise RuntimeError(
                    f"{scenario.name}: search counters changed between repetitions"
                )
            timings.append(elapsed)
        median = statistics.median(timings)
        nodes = expected_counters.get("nodes", 0)
        leaves = expected_counters.get("leaves", 0)
        reports.append(
            LocalScenarioTiming(
                name=scenario.name,
                description=scenario.description,
                local_inputs=str(scenario.kwargs["local_inputs"]),
                mutable_frames_per_window=int(scenario.kwargs["window_size"]),
                repetition_seconds=tuple(timings),
                median_seconds=median,
                searches_per_second=1.0 / median,
                visited_nodes=nodes,
                evaluated_leaves=leaves,
                nodes_per_second=nodes / median,
                leaves_per_second=leaves / median,
                result_checksum=expected_checksum,
            )
        )
    return LocalBenchmarkReport(repetitions, workers, tuple(reports))


def _print_human(report: LocalBenchmarkReport) -> None:
    print(
        f"Native local benchmark: {report.repetitions} timed repetitions, "
        f"workers={report.workers}"
    )
    for scenario in report.scenarios:
        print(f"\n{scenario.name}: {scenario.description}")
        print(
            f"  median {scenario.median_seconds:.6f} s; "
            f"{scenario.nodes_per_second:,.0f} nodes/s; "
            f"{scenario.leaves_per_second:,.0f} leaves/s"
        )
        print(
            f"  equal work: {scenario.visited_nodes:,} nodes, "
            f"{scenario.evaluated_leaves:,} leaves; "
            f"checksum {scenario.result_checksum[:16]}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repetitions",
        type=_positive_integer,
        default=5,
        help="timed repetitions per scenario (default: 5)",
    )
    parser.add_argument(
        "--workers",
        type=_positive_integer,
        default=1,
        help="local worker count; use 1 for kernel comparisons (default: 1)",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=tuple(item.name for item in _scenarios()),
        default=[],
        help="run one named scenario; repeat to select several",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_benchmark(
            repetitions=args.repetitions,
            workers=args.workers,
            selected=tuple(args.scenario),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"native local benchmark failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
