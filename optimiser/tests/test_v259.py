from __future__ import annotations

import os
from pathlib import Path

import nv14_cli
import nv14_local


def _windows_replace_error(winerror: int) -> PermissionError:
    error = PermissionError(13, "simulated Windows replace denial")
    error.winerror = winerror
    return error


def test_atomic_write_retries_transient_windows_replace_denial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    destination = tmp_path / "optimised.txt"
    destination.write_text("old\n", encoding="utf-8")
    real_replace = os.replace
    replace_calls = 0
    sleep_calls: list[float] = []

    def intermittently_locked(source: Path, target: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls < 3:
            raise _windows_replace_error(5)
        real_replace(source, target)

    monkeypatch.setattr(nv14_cli.os, "replace", intermittently_locked)
    monkeypatch.setattr(nv14_cli.time, "sleep", sleep_calls.append)

    nv14_cli._atomic_write_text(destination, "new\n")

    assert destination.read_text(encoding="utf-8") == "new\n"
    assert replace_calls == 3
    assert sleep_calls == [0.01, 0.02]
    assert not list(tmp_path.glob(".optimised.txt.*.tmp"))


def test_atomic_write_exhausts_bounded_windows_replace_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    destination = tmp_path / "optimised.txt"
    destination.write_text("old\n", encoding="utf-8")
    replace_calls = 0

    def permanently_locked(_source: Path, _target: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        raise _windows_replace_error(32)

    monkeypatch.setattr(nv14_cli.os, "replace", permanently_locked)
    monkeypatch.setattr(nv14_cli.time, "sleep", lambda _delay: None)

    try:
        nv14_cli._atomic_write_text(destination, "new\n")
    except PermissionError as exc:
        assert exc.winerror == 32
    else:
        raise AssertionError("permanent replace denial was not reported")

    assert replace_calls == 9
    assert destination.read_text(encoding="utf-8") == "old\n"
    assert not list(tmp_path.glob(".optimised.txt.*.tmp"))


def test_simple_progress_queue_drains_without_feeder_thread() -> None:
    progress_queue = nv14_local.multiprocessing.get_context().SimpleQueue()
    try:
        progress_queue.put("first")
        progress_queue.put("second")
        delivered: list[str] = []
        assert nv14_local._drain_local_worker_progress(
            progress_queue, delivered.append
        ) == 2
        assert delivered == ["first", "second"]
    finally:
        progress_queue.close()


def test_interrupt_message_uses_active_mode() -> None:
    assert nv14_cli._interrupt_message(["local", "input.txt"]).startswith(
        "\n[local:interrupt]"
    )
    assert nv14_cli._interrupt_message(["auto", "input.txt"]).startswith(
        "\n[auto:interrupt]"
    )
    assert nv14_cli._interrupt_message(["--help"]).startswith("\n[interrupt]")
