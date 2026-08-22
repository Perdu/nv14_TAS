from __future__ import annotations

import ast
import inspect
import multiprocessing
import subprocess
import sys
import textwrap
from pathlib import Path

import nv14_auto
import nv14_cli
import nv14_jump
import nv14_local
import nv14_objectives
import optimize_replay
import pytest
from nv14_engine import InputFrame, parse_level_string
from nv14_replay import decode_complex_replay, parse_combined_level_replay

ROOT = Path(__file__).parents[1]


def test_autonomous_entrypoint_is_a_thin_compatibility_facade() -> None:
    source = textwrap.dedent(inspect.getsource(nv14_auto.optimise_autonomous))
    tree = ast.parse(source)
    entrypoint = tree.body[0]

    assert isinstance(entrypoint, ast.FunctionDef)
    assert len(source.splitlines()) <= 30
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(entrypoint)
        if node is not entrypoint
    )
    assert nv14_auto.optimize_autonomous is nv14_auto.optimise_autonomous


def test_compatibility_facade_reexports_single_owned_definitions() -> None:
    assert optimize_replay.AxisWindow is nv14_objectives.AxisWindow
    assert optimize_replay.Evaluation is nv14_objectives.Evaluation
    assert optimize_replay.JumpPulse is nv14_jump.JumpPulse
    assert optimize_replay.ImmutableJumpSpec is nv14_jump.ImmutableJumpSpec
    assert optimize_replay.LocalSearchRunResult is nv14_local.LocalSearchRunResult
    assert optimize_replay.LocalConfig is nv14_cli.LocalConfig
    assert optimize_replay.JumpPatternConfig is nv14_cli.JumpPatternConfig
    assert (
        optimize_replay._search_all_input_frames
        is nv14_local._search_all_input_frames
    )
    assert (
        optimize_replay._validate_output_paths
        is nv14_cli._validate_output_paths
    )


def test_runtime_modules_import_in_dependency_reverse_order() -> None:
    command = (
        "import nv14_cli, nv14_local, nv14_jump, nv14_objectives, "
        "nv14_auto_parallel, nv14_auto, nv14_replay, nv14_engine, "
        "optimize_replay"
    )
    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_thin_entrypoint_runs_as_a_real_subprocess() -> None:
    completed = subprocess.run(
        [sys.executable, "optimize_replay.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "{auto,local,jump-pattern}" in completed.stdout


def test_jump_workers_use_a_forced_spawn_context(monkeypatch) -> None:
    spawn_context = multiprocessing.get_context("spawn")
    monkeypatch.setattr(
        nv14_jump.multiprocessing,
        "get_context",
        lambda: spawn_context,
    )
    combined = parse_combined_level_replay(
        (ROOT / "tests" / "example_motherlode.txt").read_text(encoding="utf-8")
    )
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string)

    results = nv14_jump.optimise_jump_patterns(
        level,
        replay.frames,
        target_frame=71,
        range_start=0,
        range_end=71,
        objective_name="max-x",
        jump_count_min=2,
        jump_count_max=2,
        jump_length_min=1,
        jump_length_max=3,
        top_results=2,
        workers=2,
        progress=None,
    )
    assert results


def test_local_workers_use_a_forced_spawn_context(monkeypatch) -> None:
    spawn_context = multiprocessing.get_context("spawn")
    monkeypatch.setattr(
        nv14_local.multiprocessing,
        "get_context",
        lambda: spawn_context,
    )
    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(10)]

    logs: list[str] = []
    optimised, evaluation = nv14_local.optimise_local_windows(
        level,
        frames,
        target_frame=9,
        range_start=0,
        range_end=9,
        objective_name="max-x",
        window_size=2,
        passes=1,
        local_inputs="direction",
        window_order="random",
        restarts=2,
        seed=1234,
        workers=2,
        progress=logs.append,
    )
    assert len(optimised) == len(frames)
    assert evaluation.feasible
    assert any(line.endswith("[NEW BEST SO FAR]") for line in logs)


def test_parallel_local_interrupt_terminates_executor(monkeypatch) -> None:
    class FakeProgressQueue:
        def __init__(self) -> None:
            self.closed = False

        def empty(self) -> bool:
            return True

        def close(self) -> None:
            self.closed = True

    class FakeContext:
        def __init__(self) -> None:
            self.progress_queue: FakeProgressQueue | None = None

        def SimpleQueue(self) -> FakeProgressQueue:
            self.progress_queue = FakeProgressQueue()
            return self.progress_queue

    class FakeFuture:
        def cancel(self) -> bool:
            return True

    class FakeExecutor:
        instances: list["FakeExecutor"] = []

        def __init__(self, **_kwargs) -> None:
            self.terminated = False
            self.shutdown_calls: list[dict[str, object]] = []
            self.instances.append(self)

        def submit(self, _function, _spec) -> FakeFuture:
            return FakeFuture()

        def terminate_workers(self) -> None:
            self.terminated = True

        def shutdown(self, **kwargs) -> None:
            self.shutdown_calls.append(kwargs)

    def interrupting_wait(*_args, **_kwargs):
        raise KeyboardInterrupt

    context = FakeContext()
    monkeypatch.setattr(nv14_local, "ProcessPoolExecutor", FakeExecutor)
    monkeypatch.setattr(nv14_local.multiprocessing, "get_context", lambda: context)
    monkeypatch.setattr(nv14_local, "wait", interrupting_wait)
    level = parse_level_string("0" * (31 * 23) + "|5^100,100")
    frames = [InputFrame() for _ in range(10)]

    with pytest.raises(KeyboardInterrupt):
        nv14_local.optimise_local_windows(
            level,
            frames,
            target_frame=9,
            range_start=0,
            range_end=9,
            objective_name="max-x",
            window_size=2,
            passes=1,
            local_inputs="direction",
            window_order="mixed",
            restarts=1,
            seed=1234,
            workers=2,
            progress=lambda _message: None,
        )

    executor = FakeExecutor.instances[-1]
    assert executor.terminated
    assert executor.shutdown_calls == []
    assert context.progress_queue is not None
    assert context.progress_queue.closed
