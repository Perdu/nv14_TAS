"""Patch 82: timestamp logs consistently before event tags, even with ANSI."""
import io
import re
import sys

from nv14_cli import _print_user_splice_progress, _print_best_line, _timestamped_line


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_splice_summary_and_route_lines_are_timestamped(monkeypatch):
    sink = TTY()
    monkeypatch.setattr(sys, "stdout", sink)
    monkeypatch.setattr("time.strftime", lambda _fmt: "20:02:07")
    _print_user_splice_progress('[auto:user-splice:summary:propagated] saved', color=True)
    _print_user_splice_progress('[auto:user-splice] improved verified final replay', color=True)
    lines = sink.getvalue().splitlines()
    assert lines[0] == '[20:02:07] [auto:user-splice:summary:propagated] saved'
    assert lines[1] == '\x1b[32m[20:02:07] [auto:user-splice] improved verified final replay\x1b[0m'


def test_log_prefix_does_not_duplicate_timestamp(monkeypatch):
    monkeypatch.setattr("time.strftime", lambda _fmt: "20:02:07")
    assert _timestamped_line('[19:59:56] [auto:phase] existing') == '[19:59:56] [auto:phase] existing'
    assert _timestamped_line('plain') == '[20:02:07] plain'


def test_non_splice_coloured_output_keeps_old_format(monkeypatch):
    sink = TTY()
    monkeypatch.setattr(sys, "stdout", sink)
    monkeypatch.setattr("time.strftime", lambda _fmt: "20:02:07")
    _print_best_line("[local:best] winner", color=True)
    assert sink.getvalue() == "\x1b[32m[local:best] winner\x1b[0m\n"
