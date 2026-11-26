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


def test_level_identifier_precedes_tags_for_each_named_splice_message(monkeypatch):
    sink = TTY()
    monkeypatch.setattr(sys, "stdout", sink)
    monkeypatch.setattr("time.strftime", lambda _fmt: "21:24:08")
    _print_user_splice_progress(
        "[auto:user-splice:stage] round 1 'end': complete", color=True,
        level_identifier="32-1")
    _print_user_splice_progress(
        "[auto:user-splice:seed] round 1 seed 1/4", color=True,
        level_identifier="32-1")
    _print_user_splice_progress(
        "[auto:hybrid:gain:input] 'end': improves input only; frame 120 -> 119",
        color=True, level_identifier="32-1")
    lines = sink.getvalue().splitlines()
    assert lines[0] == "[21:24:08] 32-1 [auto:user-splice:stage] round 1 'end': complete"
    assert lines[1] == "[21:24:08] 32-1 [auto:user-splice:seed] round 1 seed 1/4"
    assert lines[2].startswith("\x1b[33m[21:24:08] 32-1 [auto:hybrid:gain:input]")
    assert "[auto:hybrid:gain:input] 32-1:" not in lines[2]


def test_level_prefix_is_idempotent_on_timestamped_messages(monkeypatch):
    monkeypatch.setattr("time.strftime", lambda _fmt: "21:24:08")
    original = "[21:24:07] [auto:user-splice:stage] complete"
    once = _timestamped_line(original, level_identifier="32-1")
    assert once == "[21:24:07] 32-1 [auto:user-splice:stage] complete"
    assert _timestamped_line(once, level_identifier="32-1") == once
    assert _timestamped_line("[auto:user-splice:stage] complete", level_identifier="32-1") == (
        "[21:24:08] 32-1 [auto:user-splice:stage] complete")


def test_formatted_summary_has_single_level_prefix_before_tag(monkeypatch):
    sink = TTY()
    monkeypatch.setattr(sys, "stdout", sink)
    monkeypatch.setattr("time.strftime", lambda _fmt: "21:24:08")
    _print_user_splice_progress(
        "[auto:user-splice:summary:pending] 'end': pending (saved); "
        "downstream gain: none; splice: frame 120; vs best run: +0 frames saved",
        color=True, level_identifier="32-1")
    result = sink.getvalue()
    assert result.startswith("\x1b[33m[21:24:08] 32-1 [auto:user-splice:summary:pending] \x1b[1m'end'\x1b[22m:")
    assert "[auto:user-splice:summary:pending] 32-1:" not in result
    assert "\n  downstream gain: none;" in result


def test_range_adapted_keeps_yellow_when_level_prefix_is_added(monkeypatch):
    sink = TTY()
    monkeypatch.setattr(sys, "stdout", sink)
    monkeypatch.setattr("time.strftime", lambda _fmt: "21:24:08")
    _print_user_splice_progress(
        "[auto:user-splice:range-adapted] '456': configured range adjusted",
        color=True, level_identifier="32-1",
    )
    assert sink.getvalue() == (
        "\x1b[33m[21:24:08] 32-1 "
        "[auto:user-splice:range-adapted] '456': configured range adjusted\x1b[0m\n"
    )
