"""Check mode uses result colors without changing feasibility or output files."""
from __future__ import annotations

import io
import sys

import pytest

from tests.test_user_splice_input_check import _run, _setup


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def _infeasible_goal(goals):
    (goals / 'second.txt').write_text(
        '[local]\nsearch="population"\nobjective="earliest-arrival"\n'
        'target-frame=10\nrange="0:10"\ntarget-region="9000:9100,9000:9100"\n')


def test_check_tty_green_feasible_red_infeasible_and_summary(
        tmp_path, monkeypatch):
    original, route, goals, _ = _setup(tmp_path)
    _infeasible_goal(goals)
    output = _Terminal()
    with monkeypatch.context() as patch:
        patch.setattr(sys, 'stdout', output)
        with pytest.raises(SystemExit) as exc:
            _run(patch, ['auto', str(original), '--splice-config', str(route),
                         '--check-splices'])
    assert exc.value.code == 1
    lines = output.getvalue().splitlines()
    assert any(line.startswith("\x1b[32m[check:feasible] 'first':")
               and line.endswith('\x1b[0m') for line in lines)
    assert any(line.startswith("\x1b[31m[check:infeasible] 'second':")
               and line.endswith('\x1b[0m') for line in lines)
    assert any(line.startswith('\x1b[31m[check:summary] input run: 2/3')
               for line in lines)


def test_check_tty_all_feasible_summary_green(tmp_path, monkeypatch):
    original, route, _, _ = _setup(tmp_path)
    output = _Terminal()
    with monkeypatch.context() as patch:
        patch.setattr(sys, 'stdout', output)
        _run(patch, ['auto', str(original), '--splice-config', str(route),
                     '--check-splices'])
    assert '\x1b[32m[check:summary] input run: 3/3' in output.getvalue()
    assert '\x1b[31m' not in output.getvalue()


def test_check_no_color_disables_ansi_even_on_tty(tmp_path, monkeypatch):
    original, route, goals, _ = _setup(tmp_path)
    _infeasible_goal(goals)
    output = _Terminal()
    with monkeypatch.context() as patch:
        patch.setattr(sys, 'stdout', output)
        with pytest.raises(SystemExit) as exc:
            _run(patch, ['auto', str(original), '--splice-config', str(route),
                         '--check-splices', '--no-color'])
    assert exc.value.code == 1
    assert '[check:feasible]' in output.getvalue()
    assert '[check:infeasible]' in output.getvalue()
    assert '\x1b[' not in output.getvalue()


def test_check_error_tty_is_red_and_exits_one(tmp_path, monkeypatch):
    original, route, goals, _ = _setup(tmp_path)
    (goals / 'second.txt').unlink()
    error = _Terminal()
    with monkeypatch.context() as patch:
        patch.setattr(sys, 'stderr', error)
        with pytest.raises(SystemExit) as exc:
            _run(patch, ['auto', str(original), '--splice-config', str(route),
                         '--check-splices'])
    assert exc.value.code == 1
    assert error.getvalue().startswith('\x1b[31m[check:error]')
    assert error.getvalue().rstrip().endswith('\x1b[0m')


def test_check_error_redirected_and_no_color_are_plain(
        tmp_path, monkeypatch, capsys):
    original, route, goals, _ = _setup(tmp_path)
    (goals / 'second.txt').unlink()
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, ['auto', str(original), '--splice-config', str(route),
                           '--check-splices'])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert '[check:error]' in captured.err
    assert '\x1b[' not in captured.err

    error = _Terminal()
    with monkeypatch.context() as patch:
        patch.setattr(sys, 'stderr', error)
        with pytest.raises(SystemExit) as exc:
            _run(patch, ['auto', str(original), '--splice-config', str(route),
                         '--check-splices', '--no-color'])
    assert exc.value.code == 1
    assert '[check:error]' in error.getvalue()
    assert '\x1b[' not in error.getvalue()
