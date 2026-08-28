"""Deterministic replay-evaluation microbenchmark for the nv14 engine.

Parsing and replay decoding happen before the timer.  The timed section covers
the operation repeated by optimiser searches: create a fresh state, execute
every stored input through ``SimulationState.step``, and execute the implicit
neutral completion tick.  Seven bundled replays exercise static objects,
bounce blocks, floor guards, homing launchers, turrets, zap drones, doors,
thwomps, mines, launch pads, and one-way platforms.

Run from the project root with, for example::

    python -m tools.benchmark_engine
    python -m tools.benchmark_engine --evaluations 500 --repetitions 5 --json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from nv14_engine import InputFrame, Level, UnsupportedTileCollision, parse_level_string
from nv14_replay import decode_complex_replay, parse_combined_level_replay


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NEUTRAL_INPUT = InputFrame(False, False, False, None)
SCENARIO_PATHS = (
    "examples/replays/example_motherlode.txt",
    "tests/example_44_0.txt",
    "tests/example_06_4_floorguards.txt",
    "tests/example_07_3_homing.txt",
    "tests/example_28_3_turrets.txt",
    "tests/example_74_1_zap.txt",
    "examples/replays/example_21_2_greedo.txt",
)


class BenchmarkError(RuntimeError):
    """A bundled benchmark replay did not satisfy its expected contract."""


@dataclass(frozen=True, slots=True)
class Scenario:
    path: str
    name: str
    level: Level
    frames: tuple[InputFrame, ...]

    @property
    def declared_ticks(self) -> int:
        return len(self.frames) - 1

    @property
    def simulated_ticks(self) -> int:
        return len(self.frames)


@dataclass(frozen=True, slots=True)
class ScenarioReport:
    path: str
    name: str
    declared_ticks: int
    simulated_ticks_per_evaluation: int


@dataclass(frozen=True, slots=True)
class EngineBenchmarkReport:
    enemy_simulation: bool
    raw_jump_triggers: bool
    scenarios: tuple[ScenarioReport, ...]
    evaluations_per_scenario: int
    repetitions: int
    evaluations_per_repetition: int
    simulated_ticks_per_repetition: int
    repetition_seconds: tuple[float, ...]
    median_seconds: float
    evaluations_per_second: float
    ticks_per_second: float
    checksum: int


def _positive_integer(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _prepare_scenarios(project_root: Path = PROJECT_ROOT) -> tuple[Scenario, ...]:
    scenarios: list[Scenario] = []
    for relative_path in SCENARIO_PATHS:
        path = project_root / relative_path
        try:
            combined = parse_combined_level_replay(path.read_text(encoding="utf-8"))
            replay = decode_complex_replay(combined.replay_string)
            level = parse_level_string(
                combined.level_string,
                strict_shapes=True,
                simulate_enemies=True,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise BenchmarkError(f"could not load {relative_path}: {exc}") from exc
        scenarios.append(
            Scenario(
                path=relative_path,
                name=combined.name or path.stem,
                level=level,
                # Preserve the packed jump_trigger values.  The only added
                # frame is the game's implicit neutral completion sentinel.
                frames=tuple(replay.frames) + (NEUTRAL_INPUT,),
            )
        )
    return tuple(scenarios)


def _run_once(scenario: Scenario) -> tuple[int, int]:
    state = scenario.level.initial_state()
    sentinel_index = len(scenario.frames) - 1
    try:
        for tick, frame in enumerate(scenario.frames):
            state.step(frame, scenario.level.tiles)
            if state.level_complete:
                if tick != sentinel_index:
                    raise BenchmarkError(
                        f"{scenario.path}: completed at tick {tick}, expected "
                        f"sentinel tick {sentinel_index}"
                    )
                break
            if state.player.dead:
                raise BenchmarkError(
                    f"{scenario.path}: player died at tick {tick} before completion"
                )
    except UnsupportedTileCollision as exc:
        raise BenchmarkError(
            f"{scenario.path}: unsupported tile collision at engine frame "
            f"{state.frame}: {exc}"
        ) from exc
    if not state.level_complete:
        raise BenchmarkError(
            f"{scenario.path}: did not complete on sentinel tick {sentinel_index}"
        )
    if state.player.dead:
        raise BenchmarkError(f"{scenario.path}: player died on completion")
    if state.frame != len(scenario.frames):
        raise BenchmarkError(
            f"{scenario.path}: engine frame is {state.frame}, expected "
            f"{len(scenario.frames)}"
        )
    exit_index = state.static_state.completed_exit_index
    if exit_index is None:
        raise BenchmarkError(f"{scenario.path}: completion has no exit index")
    return state.frame, exit_index


def run_benchmark(
    *,
    evaluations_per_scenario: int = 200,
    repetitions: int = 3,
    project_root: Path = PROJECT_ROOT,
) -> EngineBenchmarkReport:
    if evaluations_per_scenario < 1:
        raise ValueError("evaluations_per_scenario must be positive")
    if repetitions < 1:
        raise ValueError("repetitions must be positive")

    scenarios = _prepare_scenarios(project_root)
    # Validate every scenario and populate Level's immutable initial-state
    # caches before timing.  This removes one-time parsing/setup variance from
    # a benchmark intended to model repeated evaluations of an existing level.
    for scenario in scenarios:
        _run_once(scenario)

    evaluations_per_repetition = evaluations_per_scenario * len(scenarios)
    ticks_per_scenario_pass = sum(
        scenario.simulated_ticks for scenario in scenarios
    )
    simulated_ticks_per_repetition = (
        evaluations_per_scenario * ticks_per_scenario_pass
    )
    timings: list[float] = []
    checksum: int | None = None
    for _repetition in range(repetitions):
        current_checksum = 0
        started = time.perf_counter()
        # Keep each level hot for consecutive evaluations, matching an
        # optimiser working repeatedly on one replay while still weighting all
        # seven scenarios equally.
        for scenario in scenarios:
            for _evaluation in range(evaluations_per_scenario):
                frame, exit_index = _run_once(scenario)
                current_checksum += frame + exit_index
        elapsed = time.perf_counter() - started
        timings.append(elapsed)
        if checksum is None:
            checksum = current_checksum
        elif current_checksum != checksum:
            raise BenchmarkError(
                "benchmark checksum changed between deterministic repetitions"
            )

    median_seconds = statistics.median(timings)
    assert checksum is not None
    return EngineBenchmarkReport(
        enemy_simulation=True,
        raw_jump_triggers=True,
        scenarios=tuple(
            ScenarioReport(
                path=scenario.path,
                name=scenario.name,
                declared_ticks=scenario.declared_ticks,
                simulated_ticks_per_evaluation=scenario.simulated_ticks,
            )
            for scenario in scenarios
        ),
        evaluations_per_scenario=evaluations_per_scenario,
        repetitions=repetitions,
        evaluations_per_repetition=evaluations_per_repetition,
        simulated_ticks_per_repetition=simulated_ticks_per_repetition,
        repetition_seconds=tuple(timings),
        median_seconds=median_seconds,
        evaluations_per_second=evaluations_per_repetition / median_seconds,
        ticks_per_second=simulated_ticks_per_repetition / median_seconds,
        checksum=checksum,
    )


def _print_human(report: EngineBenchmarkReport) -> None:
    print(
        f"Prepared {len(report.scenarios)} deterministic enemy-enabled "
        "engine scenarios:"
    )
    for scenario in report.scenarios:
        print(
            f"  {scenario.path}: {scenario.declared_ticks:,} declared + "
            "1 neutral tick"
        )
    for index, elapsed in enumerate(report.repetition_seconds, start=1):
        print(
            f"Repetition {index}: {report.evaluations_per_repetition:,} "
            f"evaluations and {report.simulated_ticks_per_repetition:,} ticks "
            f"in {elapsed:.3f} s"
        )
    print(
        f"Median: {report.median_seconds:.3f} s, "
        f"{report.evaluations_per_second:,.2f} evaluations/s, "
        f"{report.ticks_per_second:,.0f} ticks/s; "
        f"checksum {report.checksum}."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark repeated nv14 engine evaluations across seven bundled replays"
        )
    )
    parser.add_argument(
        "--evaluations",
        type=_positive_integer,
        default=200,
        help="evaluations of each scenario per repetition (default: 200)",
    )
    parser.add_argument(
        "--repetitions",
        type=_positive_integer,
        default=3,
        help="timed repetitions; the median is reported (default: 3)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a machine-readable JSON report",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_benchmark(
            evaluations_per_scenario=args.evaluations,
            repetitions=args.repetitions,
        )
    except BenchmarkError as exc:
        print(f"engine benchmark failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
