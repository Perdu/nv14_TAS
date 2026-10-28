"""Regression tests for prompt Local population Ctrl+C termination."""
from __future__ import annotations

from types import SimpleNamespace
import sys

import pytest

import nv14_cli
import nv14_local
import nv14_population
from nv14_engine import InputFrame
from nv14_replay import encode_complex_replay


def test_interrupt_without_feasible_candidate_retains_existing_output_and_exits_130(
    monkeypatch, tmp_path, capsys,
):
    source = tmp_path / "run.txt"
    level_string = "0" * (31 * 23) + "|5^100,100"
    source.write_text(
        f"$Test#tests##{level_string}#{encode_complex_replay([InputFrame()] * 24)}#\n"
    )
    output = tmp_path / "existing.txt"
    output.write_text("already verified\n")

    def interrupted(*_args, **_kwargs):
        return SimpleNamespace(interrupted=True, candidates=())

    monkeypatch.setattr(nv14_population, "optimise_local_population", interrupted)
    monkeypatch.setattr(sys, "argv", [
        "optimize_replay.py", "local", str(source),
        "--search", "population", "--range", "0:10", "--target-frame", "10",
        "--objective", "max-x", "--output", str(output),
    ])
    with pytest.raises(SystemExit) as exc:
        nv14_cli.main()
    assert exc.value.code == 130
    assert "interrupted; no feasible endpoint" in capsys.readouterr().out
    assert output.read_text() == "already verified\n"


def test_stop_executor_uses_nonblocking_shutdown_and_kills_stubborn_workers():
    class StubbornProcess:
        def __init__(self):
            self.alive = True
            self.terminated = False
            self.killed = False
            self.joins = []

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.terminated = True

        def join(self, timeout=None):
            self.joins.append(timeout)

        def kill(self):
            self.killed = True
            self.alive = False

    processes = [StubbornProcess() for _ in range(15)]

    class FakeExecutor:
        _processes = {i: proc for i, proc in enumerate(processes)}
        calls = []

        def shutdown(self, **kwargs):
            self.calls.append(kwargs)

    executor = FakeExecutor()
    nv14_local._stop_local_executor(executor)
    assert all(proc.terminated and proc.killed for proc in processes)
    assert all(proc.joins[0] <= 2.0 for proc in processes)
    assert executor.calls == [{"wait": False, "cancel_futures": True}]
