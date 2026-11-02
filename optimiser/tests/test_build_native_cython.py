"""Generated C should be reproducible, but not rebuilt needlessly."""
from __future__ import annotations

from pathlib import Path
import subprocess

import build_native


def test_missing_c_triggers_regeneration(tmp_path, monkeypatch):
    native = tmp_path / "native"
    native.mkdir()
    (native / "_nv14_native.pyx").write_text("cdef int number = 2\n")
    monkeypatch.setattr(build_native, "ROOT", tmp_path)
    commands = []

    def run(command, **kwargs):
        commands.append((command, kwargs))
        (native / "_nv14_native.c").write_text("/* generated */\n")

    monkeypatch.setattr(build_native.subprocess, "run", run)
    build_native._regenerate_cython_source()
    assert len(commands) == 1
    assert commands[0][0][1:4] == ["-m", "cython", "-3"]
    assert commands[0][1]["cwd"] == tmp_path


def test_up_to_date_c_is_not_regenerated(tmp_path, monkeypatch):
    native = tmp_path / "native"
    native.mkdir()
    (native / "_nv14_native.pyx").write_text("cdef int number = 2\n")
    (native / "_nv14_native.c").write_text("/* generated */\n")
    monkeypatch.setattr(build_native, "ROOT", tmp_path)

    def unexpected_run(*args, **kwargs):
        raise AssertionError("Cython ran despite up-to-date generated C")

    monkeypatch.setattr(build_native.subprocess, "run", unexpected_run)
    build_native._regenerate_cython_source()


def test_force_cython_always_regenerates(tmp_path, monkeypatch):
    native = tmp_path / "native"
    native.mkdir()
    (native / "_nv14_native.pyx").write_text("cdef int number = 2\n")
    (native / "_nv14_native.c").write_text("/* generated */\n")
    monkeypatch.setattr(build_native, "ROOT", tmp_path)
    commands = []
    monkeypatch.setattr(build_native.subprocess, "run", lambda command, **kwargs: commands.append(command))
    build_native._regenerate_cython_source(force=True)
    assert len(commands) == 1


def test_stale_c_regenerated(tmp_path, monkeypatch):
    native = tmp_path / "native"
    native.mkdir()
    generated = native / "_nv14_native.c"
    generated.write_text("/* old generated */\n")
    source = native / "_nv14_native.pyx"
    source.write_text("cdef int number = 2\n")
    generated.touch()
    import os
    os.utime(generated, ns=(1, 1))
    monkeypatch.setattr(build_native, "ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(build_native.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    build_native._regenerate_cython_source()
    assert len(calls) == 1


def test_failed_cython_reports_dependency_hint(tmp_path, monkeypatch):
    native = tmp_path / "native"
    native.mkdir()
    (native / "_nv14_native.pyx").write_text("invalid")
    monkeypatch.setattr(build_native, "ROOT", tmp_path)

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(build_native.subprocess, "run", fail)
    try:
        build_native._regenerate_cython_source()
    except SystemExit as exc:
        assert "Cython regeneration failed" in str(exc)
    else:
        raise AssertionError("Expected Cython failure to abort native compilation")


def test_native_build_is_incremental_by_default(tmp_path, monkeypatch):
    """The ordinary command must not add setuptools' --force flag."""
    import os
    import sys
    import pytest

    fake_modules = tuple(
        tmp_path / f"{name}.so"
        for name in ("_nv14_native", "_nv14_render_native")
    )
    for module in fake_modules:
        module.write_bytes(b"built")

    monkeypatch.setattr(build_native, "ROOT", tmp_path)
    monkeypatch.setattr(
        build_native,
        "_extension_candidates",
        lambda name: (tmp_path / f"{name}.so",),
    )
    cython_calls = []
    monkeypatch.setattr(
        build_native,
        "_regenerate_cython_source",
        lambda *, force=False: cython_calls.append(force),
    )
    monkeypatch.setattr(build_native, "_backend_probe", lambda: {"available": True})
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if "--force" in command:
            for module in fake_modules:
                timestamp = module.stat().st_mtime_ns + 10_000_000
                os.utime(module, ns=(timestamp, timestamp))

    monkeypatch.setattr(build_native.subprocess, "run", fake_run)

    for flags, expected_compiler_force, expected_cython_force in (
        ([], False, False),
        (["--no-force"], False, False),
        (["--force"], True, False),
        (["--force-cython"], False, True),
    ):
        commands.clear()
        cython_calls.clear()
        monkeypatch.setattr(sys, "argv", ["build_native.py", *flags])
        build_native.main()
        assert len(commands) == 1
        assert ("--force" in commands[0]) is expected_compiler_force
        assert cython_calls == [expected_cython_force]

    monkeypatch.setattr(sys, "argv", ["build_native.py", "--check"])
    commands.clear()
    cython_calls.clear()
    build_native.main()
    assert not commands and not cython_calls

    monkeypatch.setattr(sys, "argv", ["build_native.py", "--force", "--no-force"])
    with pytest.raises(SystemExit):
        build_native.main()
