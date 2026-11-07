"""Patch 81: informational propagation summaries never look like new gains."""
import io
import sys

from nv14_cli import _print_user_splice_progress


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_propagated_summary_has_no_success_green(monkeypatch):
    buffer = TTY()
    monkeypatch.setattr(sys, 'stdout', buffer)
    _print_user_splice_progress('[auto:user-splice:summary:propagated] "end": in best', color=True)
    assert buffer.getvalue().endswith('[auto:user-splice:summary:propagated] "end": in best\n')


def test_real_completed_improvement_stays_green(monkeypatch):
    buffer = TTY()
    monkeypatch.setattr(sys, 'stdout', buffer)
    _print_user_splice_progress('[auto:user-splice] improved verified final replay', color=True)
    assert '\x1b[32m' in buffer.getvalue()
