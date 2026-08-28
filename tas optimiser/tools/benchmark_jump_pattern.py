"""Benchmark representative jump-pattern searches in the native kernel.

The timed operation is the public :func:`optimise_jump_patterns` call, including
Python policy/spec construction and top-result verification but excluding level
and replay parsing.  Each scenario is warmed once and guarded by exact result
checksums and native search counters so timings always compare equal work.

Examples::

    python -m tools.benchmark_jump_pattern
    python -m tools.benchmark_jump_pattern --repetitions 7 --json
    python -m tools.benchmark_jump_pattern --scenario ditched-two-jump
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
from nv14_jump import optimise_jump_patterns
from nv14_replay import decode_complex_replay, parse_combined_level_replay


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_COUNTER_PATTERN = re.compile(
    r"attempted (?P<attempted>\d+) starts, "
    r"(?P<successful>\d+) produced Player\.jump\(\), "
    r"evaluated (?P<evaluated>\d+) terminal states, "
    r"deduplicated (?P<deduplicated>\d+) branches"
)


@dataclass(frozen=True, slots=True)
class JumpPatternScenario:
    name: str
    description: str
    level: Level
    frames: tuple[InputFrame, ...]
    kwargs: dict[str, Any]


@dataclass(frozen=True, slots=True)
class JumpPatternScenarioTiming:
    name: str
    description: str
    repetition_seconds: tuple[float, ...]
    median_seconds: float
    searches_per_second: float
    attempted_starts: int
    successful_starts: int
    evaluated_candidates: int
    deduplicated_branches: int
    candidates_per_second: float
    result_checksum: str


@dataclass(frozen=True, slots=True)
class JumpPatternBenchmarkReport:
    repetitions: int
    workers: int
    scenarios: tuple[JumpPatternScenarioTiming, ...]


def _positive_integer(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _combined_fixture(
    relative_path: str,
    *,
    simulate_enemies: bool,
) -> tuple[Level, tuple[InputFrame, ...]]:
    path = PROJECT_ROOT / relative_path
    combined = parse_combined_level_replay(path.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(
        combined.level_string,
        strict_shapes=True,
        simulate_enemies=simulate_enemies,
    )
    return level, tuple(replay.frames)


def _scenarios() -> tuple[JumpPatternScenario, ...]:
    ditched_level, ditched_frames = _combined_fixture(
        "tests/example_ditched_supplied.txt",
        simulate_enemies=False,
    )
    motherlode_level, motherlode_frames = _combined_fixture(
        "tests/example_motherlode.txt",
        simulate_enemies=False,
    )
    bounce_level, bounce_frames = _combined_fixture(
        "tests/example_44_0.txt",
        simulate_enemies=True,
    )
    return (
        JumpPatternScenario(
            "ditched-two-jump",
            "short exact two-jump search with bounded hold lengths",
            ditched_level,
            ditched_frames,
            {
                "target_frame": 123,
                "range_start": 106,
                "range_end": 123,
                "objective_name": "min-x",
                "jump_count_min": 2,
                "jump_count_max": 2,
                "jump_length_min": 1,
                "jump_length_max": 4,
                "top_results": 3,
            },
        ),
        JumpPatternScenario(
            "motherlode-three-jump",
            "72-frame two/three-jump search with a delayed target",
            motherlode_level,
            motherlode_frames,
            {
                "target_frame": 71,
                "range_start": 0,
                "range_end": 71,
                "objective_name": "max-x",
                "jump_count_min": 2,
                "jump_count_max": 3,
                "jump_length_min": 1,
                "jump_length_max": 10,
                "top_results": 10,
            },
        ),
        JumpPatternScenario(
            "enemy-bounceblocks",
            "enemy-enabled 44-0 prefix with native object-state copies",
            bounce_level,
            bounce_frames,
            {
                "target_frame": 100,
                "range_start": 0,
                "range_end": 30,
                "objective_name": "max-x",
                "jump_count_min": 1,
                "jump_count_max": 2,
                "jump_length_min": 1,
                "jump_length_max": 4,
                "top_results": 5,
            },
        ),
    )


def _search_counters(logs: list[str]) -> dict[str, int]:
    for line in logs:
        match = _COUNTER_PATTERN.search(line)
        if match is not None:
            return {name: int(value) for name, value in match.groupdict().items()}
    raise RuntimeError("jump-pattern progress did not contain native counters")


def _result_checksum(results: Sequence[object]) -> str:
    digest = hashlib.sha256()
    for result in results:
        score = float(result.score)
        digest.update(score.hex().encode("ascii"))
        for pulse in result.pulses:
            digest.update(int(pulse.start_frame).to_bytes(8, "little"))
            digest.update(int(pulse.hold_length).to_bytes(8, "little"))
        digest.update(repr(result.evaluation.state.state_key()).encode("utf-8"))
    return digest.hexdigest()


def _run_once(
    scenario: JumpPatternScenario,
    *,
    workers: int,
) -> tuple[str, dict[str, int]]:
    logs: list[str] = []
    results = optimise_jump_patterns(
        scenario.level,
        scenario.frames,
        workers=workers,
        progress=logs.append,
        **scenario.kwargs,
    )
    if not results:
        raise RuntimeError(f"{scenario.name}: search returned no feasible result")
    return _result_checksum(results), _search_counters(logs)


def run_benchmark(
    *,
    repetitions: int = 5,
    workers: int = 1,
    selected: tuple[str, ...] = (),
) -> JumpPatternBenchmarkReport:
    if repetitions < 1 or workers < 1:
        raise ValueError("repetitions and workers must be positive")
    all_scenarios = _scenarios()
    if selected:
        known = {item.name for item in all_scenarios}
        unknown = set(selected) - known
        if unknown:
            raise ValueError("unknown scenario(s): " + ", ".join(sorted(unknown)))
        scenarios = tuple(item for item in all_scenarios if item.name in selected)
    else:
        scenarios = all_scenarios

    reports: list[JumpPatternScenarioTiming] = []
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
        evaluated = expected_counters["evaluated"]
        reports.append(
            JumpPatternScenarioTiming(
                name=scenario.name,
                description=scenario.description,
                repetition_seconds=tuple(timings),
                median_seconds=median,
                searches_per_second=1.0 / median,
                attempted_starts=expected_counters["attempted"],
                successful_starts=expected_counters["successful"],
                evaluated_candidates=evaluated,
                deduplicated_branches=expected_counters["deduplicated"],
                candidates_per_second=evaluated / median,
                result_checksum=expected_checksum,
            )
        )
    return JumpPatternBenchmarkReport(repetitions, workers, tuple(reports))


def _print_human(report: JumpPatternBenchmarkReport) -> None:
    print(
        f"Native jump-pattern benchmark: {report.repetitions} timed repetitions, "
        f"workers={report.workers}"
    )
    for scenario in report.scenarios:
        print(f"\n{scenario.name}: {scenario.description}")
        print(
            f"  median {scenario.median_seconds:.6f} s; "
            f"{scenario.candidates_per_second:,.0f} evaluated candidates/s"
        )
        print(
            f"  equal work: {scenario.attempted_starts:,} starts, "
            f"{scenario.successful_starts:,} successful, "
            f"{scenario.evaluated_candidates:,} terminal simulations, "
            f"{scenario.deduplicated_branches:,} deduplicated; "
            f"checksum {scenario.result_checksum[:16]}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repetitions",
        type=_positive_integer,
        default=5,
        help="timed repetitions after one warm-up (default: 5)",
    )
    parser.add_argument(
        "--workers",
        type=_positive_integer,
        default=1,
        help="native worker shards used by each search (default: 1)",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="scenario name to run; repeat to select several",
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
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
