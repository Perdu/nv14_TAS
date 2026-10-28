#!/usr/bin/env python3
"""Benchmark Python and native C n v1.4 replay simulation throughput.

Run from the optimiser project root against a combined level/replay text file::

    python -m tools.benchmark_nv14_replay example.txt 1000
    python -m tools.benchmark_nv14_replay example.txt 1000 --simulate-enemies

The input file must use the same combined format accepted by optimize_replay.py::

    $name#author##<level data>#<complex replay>#

The benchmark preserves the options and timing scope of the original standalone
``benchmark_nv14_replay.py``. Reading/parsing the input is excluded. Each timed
simulation includes creation of a fresh initial state and execution of the
replay. The C engine uses the native fixed-input batch API; it never silently
falls back to the Python emulator.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
import time
from collections.abc import Callable, Sequence

# Support both ``python -m tools.benchmark_nv14_replay`` and direct execution as
# ``python tools/benchmark_nv14_replay.py`` from the extracted project tree.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from nv14_engine import InputFrame, Level, UnsupportedTileCollision, parse_level_string
    from nv14_native import require_native
    from nv14_replay import decode_complex_replay, editable_frames, parse_combined_level_replay
except ImportError as exc:
    raise SystemExit(
        "Could not import the n v1.4 optimiser modules. Run this tool from the "
        "extracted optimiser project tree.\n"
        f"Import error: {exc}"
    ) from exc


@dataclass(frozen=True, slots=True)
class SimulationResult:
    frames_stepped: int
    dead: bool
    level_complete: bool


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    replay_length: int
    frames_per_second: float
    simulations_per_second: float
    mean_ms: float


def simulate_python_once(
    level: Level,
    frames: Sequence[InputFrame],
    *,
    stop_on_complete: bool,
) -> SimulationResult:
    """Run one replay through the Python reference engine."""
    state = level.initial_state()
    stepped = 0

    for frame in frames:
        state.step(frame, level.tiles)
        stepped += 1
        if state.player.dead:
            break
        if stop_on_complete and state.level_complete:
            break

    return SimulationResult(stepped, state.player.dead, state.level_complete)


def simulate_native_once(
    level: object,
    frames: Sequence[InputFrame],
    *,
    stop_on_complete: bool,
) -> SimulationResult:
    """Run one replay through the compiled C engine with no Python fallback."""
    state = level.initial_state()
    result = state.step_many(
        frames,
        stop_on_dead=True,
        stop_on_complete=stop_on_complete,
    )
    snapshot = result["state"]
    player = snapshot["player"]
    return SimulationResult(
        int(result["consumed"]),
        bool(player["dead"]),
        bool(snapshot["static_state"]["level_complete"]),
    )


def positive_int(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return value


def nonnegative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the Python and native C n v1.4 engines on the same replay "
            "and report replay throughput for each."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help="combined custom-level/replay text file",
    )
    parser.add_argument(
        "runs",
        type=positive_int,
        help="number of timed replay simulations per engine",
    )
    parser.add_argument(
        "--warmup",
        type=nonnegative_int,
        default=3,
        metavar="N",
        help="untimed warm-up simulations per engine before benchmarking (default: 3)",
    )
    parser.add_argument(
        "--simulate-enemies",
        action="store_true",
        help=(
            "enable optional enemy simulation for both engines, matching "
            "optimize_replay.py --simulate-enemies"
        ),
    )
    parser.add_argument(
        "--non-strict-shapes",
        action="store_true",
        help=(
            "allow unsupported tile shapes instead of rejecting them, matching "
            "the optimiser option of the same name"
        ),
    )
    parser.add_argument(
        "--stop-on-complete",
        action="store_true",
        help=(
            "stop each run as soon as the exit completes the level instead of "
            "consuming the remaining replay ticks"
        ),
    )
    return parser


def benchmark_engine(
    *,
    replay_length: int,
    runs: int,
    warmup: int,
    run_once: Callable[[], SimulationResult],
) -> tuple[BenchmarkResult, SimulationResult]:
    warm_result: SimulationResult | None = None
    for _ in range(warmup):
        warm_result = run_once()

    # Even with --warmup 0, perform one untimed validation run so the benchmark
    # can verify that both engines are doing equivalent work without polluting
    # the timed region.
    if warm_result is None:
        warm_result = run_once()

    total_frames = 0
    started_ns = time.perf_counter_ns()
    for _ in range(runs):
        total_frames += run_once().frames_stepped
    elapsed_ns = time.perf_counter_ns() - started_ns

    elapsed = elapsed_ns / 1_000_000_000.0
    if elapsed <= 0.0:
        raise SystemExit("Timer resolution was insufficient for this benchmark; use more runs.")

    return (
        BenchmarkResult(
            replay_length=replay_length,
            frames_per_second=total_frames / elapsed,
            simulations_per_second=runs / elapsed,
            mean_ms=elapsed * 1000.0 / runs,
        ),
        warm_result,
    )


def print_result(engine_name: str, result: BenchmarkResult) -> None:
    print(engine_name)
    print(f"Replay length:             {result.replay_length:,} frames")
    print(f"Simulation speed:          {result.frames_per_second:,.2f} frames/second")
    print(f"Level simulations/second:  {result.simulations_per_second:,.2f}")
    print(f"Mean time/simulation:      {result.mean_ms:,.4f} ms")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        text = args.input.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"Could not read {args.input}: {exc}") from exc

    try:
        combined = parse_combined_level_replay(text)
        replay = decode_complex_replay(combined.replay_string)
        # Match optimiser input handling: stored trigger bits are discarded and
        # jump-trigger edges are derived by each engine from held jump state.
        frames = tuple(editable_frames(replay.frames))
        python_level = parse_level_string(
            combined.level_string,
            strict_shapes=not args.non_strict_shapes,
            simulate_enemies=args.simulate_enemies,
        )
    except (ValueError, UnsupportedTileCollision) as exc:
        raise SystemExit(f"Could not parse/simulate input: {exc}") from exc

    if not frames:
        raise SystemExit("Replay contains zero frames; there is nothing to benchmark.")

    try:
        native = require_native()
    except RuntimeError as exc:
        raise SystemExit(f"Could not load the C engine: {exc}") from exc

    try:
        # Call the extension parser directly so unsupported native work is an
        # error rather than nv14_native.parse_level_string's Python fallback.
        native_level = native.parse_level_string(
            combined.level_string,
            strict_shapes=not args.non_strict_shapes,
            simulate_enemies=args.simulate_enemies,
        )
    except (ValueError, NotImplementedError) as exc:
        raise SystemExit(f"Could not prepare the C engine for this level: {exc}") from exc

    python_run = lambda: simulate_python_once(
        python_level,
        frames,
        stop_on_complete=args.stop_on_complete,
    )
    native_run = lambda: simulate_native_once(
        native_level,
        frames,
        stop_on_complete=args.stop_on_complete,
    )

    try:
        python_result, python_validation = benchmark_engine(
            replay_length=len(frames),
            runs=args.runs,
            warmup=args.warmup,
            run_once=python_run,
        )
        native_result, native_validation = benchmark_engine(
            replay_length=len(frames),
            runs=args.runs,
            warmup=args.warmup,
            run_once=native_run,
        )
    except UnsupportedTileCollision as exc:
        raise SystemExit(f"Unsupported tile collision during benchmark: {exc}") from exc
    except NotImplementedError as exc:
        raise SystemExit(f"C engine encountered unsupported replay work: {exc}") from exc

    if python_validation != native_validation:
        raise SystemExit(
            "Python and C engines did not execute equivalent warm-up work: "
            f"Python={python_validation}, C={native_validation}"
        )

    print_result("Python engine", python_result)
    print()
    print_result("C engine", native_result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
