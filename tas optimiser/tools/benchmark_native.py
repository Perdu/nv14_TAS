"""Measure the optional C core against the Python reference on equal work.

This benchmark never counts a Python fallback as native work.  Its mandatory
workload is a deterministic, native-supported 512-tick player/tile simulation;
the Python side uses ordinary per-tick stepping and the native side uses the
fixed-input batch API when available.  Both produce the same validated final
snapshot and deterministic checksum.

An optional schema-v1 corpus path adds native capability coverage counts.  It
does not time unsupported levels or mix them into the native throughput::

    python -m tools.benchmark_native
    python -m tools.benchmark_native --corpus corpus.yml --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType

from tools.compare_engines import (
    NativeAdapter,
    NativeBackendUnavailable,
    NativeLevelUnsupported,
    RawInput,
    _reference_extra_snapshot,
    load_native_module,
    load_reference_engine,
    native_backend_info,
)
from tools.verify_corpus import CorpusError, _load_yaml, _validate_document


@dataclass(frozen=True, slots=True)
class BackendTiming:
    backend: str
    execution_mode: str
    repetition_seconds: tuple[float, ...]
    median_seconds: float
    evaluations_per_second: float
    ticks_per_second: float
    runtime_checksum: int


@dataclass(frozen=True, slots=True)
class NativeCoverageReport:
    corpus: str
    total_levels: int
    supported_levels: int
    unsupported_levels: int
    total_cases: int
    supported_cases: int
    unsupported_cases: int
    total_declared_input_ticks: int
    supported_declared_input_ticks: int
    unsupported_declared_input_ticks: int


@dataclass(frozen=True, slots=True)
class NativeBenchmarkReport:
    native_available: bool
    native_backend_info: object
    workload: str
    frames_per_evaluation: int
    evaluations_per_repetition: int
    repetitions: int
    deterministic_state_checksum: str
    python: BackendTiming
    native: BackendTiming
    speedup: float
    corpus_coverage: NativeCoverageReport | None


@dataclass(frozen=True, slots=True)
class SkippedNativeBenchmark:
    native_available: bool
    skipped: bool
    reason: str


def _positive_integer(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _synthetic_workload() -> tuple[str, tuple[RawInput, ...]]:
    # A full-tile floor forces collision work every grounded frame.  The
    # balanced direction pattern keeps the ninja near the middle of the level,
    # while seven jump pulses exercise both collision and input state changes.
    chars = ["0"] * (31 * 23)
    for tile_x in range(31):
        chars[tile_x * 23 + 5] = "1"
    level_string = "".join(chars) + "|5^396,134"

    frames: list[RawInput] = []
    previous_jump = False
    for tick in range(512):
        phase = tick % 128
        left = 32 <= phase < 96
        right = not left
        jump = tick % 80 < 18
        frames.append(
            RawInput(
                left=left,
                right=right,
                jump=jump,
                jump_trigger=jump and not previous_jump,
            )
        )
        previous_jump = jump
    return level_string, tuple(frames)


def _python_run_once(
    reference: ModuleType,
    level: object,
    frames: tuple[object, ...],
) -> tuple[object, int]:
    state = level.initial_state()
    for frame in frames:
        state.step(frame, level.tiles)
    return state, state.frame + state.player.jump_events


def _native_run_once(
    adapter: NativeAdapter,
    level: object,
    frames: tuple[RawInput, ...],
) -> tuple[object, int, str]:
    state = adapter.initial_state(level)
    step_many = getattr(state, "step_many", None)
    if callable(step_many):
        result = step_many(
            frames,
            stop_on_dead=False,
            stop_on_complete=False,
        )
        consumed = int(result.get("consumed", -1))
        mode = "native-batch"
    else:
        for frame in frames:
            adapter.step(state, frame)
        consumed = len(frames)
        mode = "native-per-tick"
    if consumed != len(frames):
        raise RuntimeError(
            f"native workload consumed {consumed} frames, expected {len(frames)}"
        )
    snapshot = state.snapshot() if callable(getattr(state, "snapshot", None)) else {}
    player = snapshot.get("player", {}) if isinstance(snapshot, dict) else {}
    jump_events = int(player.get("jump_events", 0))
    return state, consumed + jump_events, mode


def _time_backend(
    *,
    name: str,
    mode: str,
    run_once,
    evaluations: int,
    repetitions: int,
    frames_per_evaluation: int,
) -> BackendTiming:
    timings: list[float] = []
    checksum: int | None = None
    for _repetition in range(repetitions):
        current_checksum = 0
        started = time.perf_counter()
        for _evaluation in range(evaluations):
            current_checksum += run_once()
        elapsed = time.perf_counter() - started
        timings.append(elapsed)
        if checksum is None:
            checksum = current_checksum
        elif current_checksum != checksum:
            raise RuntimeError(f"{name} checksum changed between repetitions")
    assert checksum is not None
    median = statistics.median(timings)
    return BackendTiming(
        backend=name,
        execution_mode=mode,
        repetition_seconds=tuple(timings),
        median_seconds=median,
        evaluations_per_second=evaluations / median,
        ticks_per_second=evaluations * frames_per_evaluation / median,
        runtime_checksum=checksum,
    )


def measure_corpus_coverage(
    path: Path | str,
    *,
    native_module: ModuleType | None = None,
) -> NativeCoverageReport:
    document, _load_seconds = _load_yaml(Path(path))
    corpus = _validate_document(document)
    adapter = NativeAdapter(native_module or load_native_module())
    supported_refs: set[str] = set()
    unsupported_refs: set[str] = set()
    for level_ref, level_string in corpus.levels.items():
        try:
            adapter.parse_level(level_string, simulate_enemies=True)
        except NativeLevelUnsupported:
            unsupported_refs.add(level_ref)
        else:
            supported_refs.add(level_ref)

    supported_cases = 0
    supported_ticks = 0
    unsupported_cases = 0
    unsupported_ticks = 0
    for case in corpus.cases:
        if case.level_ref in supported_refs:
            supported_cases += 1
            supported_ticks += case.ticks
        else:
            unsupported_cases += 1
            unsupported_ticks += case.ticks
    return NativeCoverageReport(
        corpus=str(path),
        total_levels=len(corpus.levels),
        supported_levels=len(supported_refs),
        unsupported_levels=len(unsupported_refs),
        total_cases=len(corpus.cases),
        supported_cases=supported_cases,
        unsupported_cases=unsupported_cases,
        total_declared_input_ticks=corpus.declared_input_ticks,
        supported_declared_input_ticks=supported_ticks,
        unsupported_declared_input_ticks=unsupported_ticks,
    )


def run_native_benchmark(
    *,
    evaluations: int = 1_000,
    repetitions: int = 3,
    corpus: Path | None = None,
    reference_module: ModuleType | None = None,
    native_module: ModuleType | None = None,
) -> NativeBenchmarkReport:
    if evaluations < 1 or repetitions < 1:
        raise ValueError("evaluations and repetitions must be positive")
    reference = reference_module or load_reference_engine()
    native = native_module or load_native_module()
    adapter = NativeAdapter(native)
    level_string, raw_frames = _synthetic_workload()
    reference_frames = tuple(
        reference.InputFrame(
            frame.left,
            frame.right,
            frame.jump,
            frame.jump_trigger,
        )
        for frame in raw_frames
    )
    reference_level = reference.parse_level_string(
        level_string,
        strict_shapes=True,
        simulate_enemies=True,
    )
    native_level = adapter.parse_level(level_string, simulate_enemies=True)

    # Warm caches, verify an identical complete mutable snapshot, and derive a
    # checksum before timing either backend.
    reference_state, reference_runtime_value = _python_run_once(
        reference,
        reference_level,
        reference_frames,
    )
    native_state, native_runtime_value, native_mode = _native_run_once(
        adapter,
        native_level,
        raw_frames,
    )
    adapter.compare_state(
        reference_state,
        native_state,
        case_id="synthetic-supported-benchmark",
        tick=len(raw_frames) - 1,
    )
    if reference_runtime_value != native_runtime_value:
        raise RuntimeError(
            "Python/native warm-run checksums differ: "
            f"{reference_runtime_value} != {native_runtime_value}"
        )
    state_checksum = hashlib.sha256(
        repr(_reference_extra_snapshot(reference_state)).encode("utf-8")
    ).hexdigest()

    python_timing = _time_backend(
        name="python-reference",
        mode="per-tick",
        run_once=lambda: _python_run_once(
            reference,
            reference_level,
            reference_frames,
        )[1],
        evaluations=evaluations,
        repetitions=repetitions,
        frames_per_evaluation=len(raw_frames),
    )
    native_timing = _time_backend(
        name="native-core",
        mode=native_mode,
        run_once=lambda: _native_run_once(adapter, native_level, raw_frames)[1],
        evaluations=evaluations,
        repetitions=repetitions,
        frames_per_evaluation=len(raw_frames),
    )
    if python_timing.runtime_checksum != native_timing.runtime_checksum:
        raise RuntimeError(
            "Python/native timed checksums differ: "
            f"{python_timing.runtime_checksum} != "
            f"{native_timing.runtime_checksum}"
        )
    coverage = (
        measure_corpus_coverage(corpus, native_module=native)
        if corpus is not None
        else None
    )
    return NativeBenchmarkReport(
        native_available=True,
        native_backend_info=native_backend_info(native),
        workload="synthetic-supported-player-tile-512",
        frames_per_evaluation=len(raw_frames),
        evaluations_per_repetition=evaluations,
        repetitions=repetitions,
        deterministic_state_checksum=state_checksum,
        python=python_timing,
        native=native_timing,
        speedup=python_timing.median_seconds / native_timing.median_seconds,
        corpus_coverage=coverage,
    )


def _print_human(report: NativeBenchmarkReport) -> None:
    print(
        f"Workload {report.workload}: {report.frames_per_evaluation:,} ticks x "
        f"{report.evaluations_per_repetition:,} evaluations, "
        f"{report.repetitions} repetitions."
    )
    for timing in (report.python, report.native):
        print(
            f"{timing.backend} ({timing.execution_mode}): median "
            f"{timing.median_seconds:.3f} s, "
            f"{timing.ticks_per_second:,.0f} ticks/s, checksum "
            f"{timing.runtime_checksum}."
        )
    print(
        f"Native speedup: {report.speedup:.2f}x; deterministic state checksum "
        f"{report.deterministic_state_checksum}."
    )
    coverage = report.corpus_coverage
    if coverage is not None:
        print(
            f"Native corpus coverage: {coverage.supported_levels:,}/"
            f"{coverage.total_levels:,} levels, {coverage.supported_cases:,}/"
            f"{coverage.total_cases:,} cases, and "
            f"{coverage.supported_declared_input_ticks:,}/"
            f"{coverage.total_declared_input_ticks:,} declared ticks."
        )
        print(
            f"Excluded from native throughput: {coverage.unsupported_levels:,} "
            f"levels, {coverage.unsupported_cases:,} cases, "
            f"{coverage.unsupported_declared_input_ticks:,} declared ticks."
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evaluations",
        type=_positive_integer,
        default=1_000,
        help="evaluations per timed repetition (default: 1000)",
    )
    parser.add_argument(
        "--repetitions",
        type=_positive_integer,
        default=3,
        help="timed repetitions; the median is reported (default: 3)",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        help="optional schema-v1 corpus for native coverage counts",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_native_benchmark(
            evaluations=args.evaluations,
            repetitions=args.repetitions,
            corpus=args.corpus,
        )
    except NativeBackendUnavailable as exc:
        skipped = SkippedNativeBenchmark(
            native_available=False,
            skipped=True,
            reason=f"native backend unavailable: {exc}",
        )
        if args.json:
            print(json.dumps(asdict(skipped), indent=2, sort_keys=True))
        else:
            print(f"Skipped native benchmark: {skipped.reason}")
        return 0
    except (CorpusError, NativeLevelUnsupported, RuntimeError, ValueError) as exc:
        print(f"native benchmark failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
