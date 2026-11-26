"""Patch 124: readable summaries and colour only for a faster archive span."""
import io
import re
import sys

from nv14_cli import _format_user_splice_report, _print_user_splice_progress


SAMPLE = (
    "[auto:user-splice:summary:pending] '462': pending (saved); "
    "same-replay downstream gain: none; next '495' (goal not reached); "
    "splice: frame 455; max-y 364.879962; from 388: 67 section frames; "
    "fastest archived section 67 frames; full run: frame 461; max-y 369.674498; "
    "individual splice gain: +7 section frames (74 -> 67; 388 to 462); "
    "cumulative gain through this splice: +6 frames at this checkpoint vs input; "
    "vs input run: +6 frames saved, -4.79454 px saved (max-y); "
    "vs best run: +6 frames saved, -4.79454 px saved (max-y)"
)


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_pending_summary_is_exact_requested_layout():
    assert _format_user_splice_report(SAMPLE, level_identifier='01-0') == (
        "[auto:user-splice:summary:pending] '462':\n"
        "  same-replay downstream gain: none;\n"
        "  next '495' (goal not reached);\n"
        "  splice: frame 455; max-y 364.879962; from 388: 67 section frames; "
        "fastest archived section 67 frames;\n"
        "  full run: frame 461; max-y 369.674498; "
        "individual splice gain: +7 section frames (74 -> 67; 388 to 462);\n"
        "  cumulative gain through this splice: +6 frames at this checkpoint vs input;\n"
        "  vs input run: +6 frames, -4.79454 px (max-y);\n"
        "  vs best run: +6 frames, -4.79454 px (max-y)"
    )


def test_tty_bolds_splice_name_and_frame_gains_and_respects_archive_comparison(monkeypatch):
    output = TTY()
    monkeypatch.setattr(sys, 'stdout', output)
    monkeypatch.setattr('time.strftime', lambda _fmt: '16:02:58')
    _print_user_splice_progress(SAMPLE, color=True, level_identifier='01-0')
    text = output.getvalue()
    assert "[16:02:58] 01-0 [auto:user-splice:summary:pending] \x1b[1m'462'\x1b[22m:" in text
    assert 'vs input run: \x1b[1m+6\x1b[22m frames' in text
    assert 'vs best run: \x1b[1m+6\x1b[22m frames' in text
    assert '\x1b[31m' not in text  # Equal archived and current sections

    output.seek(0)
    output.truncate(0)
    _print_user_splice_progress(SAMPLE.replace('fastest archived section 67',
                                               'fastest archived section 65'),
                                color=True, level_identifier='01-0')
    assert '\x1b[31mfastest archived section 65 frames\x1b[33m' in output.getvalue()
    output.seek(0)
    output.truncate(0)
    _print_user_splice_progress(SAMPLE.replace('fastest archived section 67',
                                               'fastest archived section 70'),
                                color=True, level_identifier='01-0')
    assert '\x1b[31m' not in output.getvalue()


def test_redirected_and_no_color_output_keep_multiline_without_ansi(monkeypatch):
    plain = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', plain)
    _print_user_splice_progress(SAMPLE.replace('fastest archived section 67',
                                               'fastest archived section 66'),
                                color=True, level_identifier='01-0')
    assert '\x1b[' not in plain.getvalue()
    assert "\n  vs best run: +6 frames, -4.79454 px (max-y)" in plain.getvalue()

    terminal = TTY()
    monkeypatch.setattr(sys, 'stdout', terminal)
    _print_user_splice_progress(SAMPLE, color=False, level_identifier='01-0')
    assert '\x1b[' not in terminal.getvalue()


def test_new_stage_best_is_indented_with_level_and_gains(monkeypatch):
    progress = (
        "[auto:user-splice:temporary] round 1 stage 6/6 '462': new stage best; "
        "frame 460 -> 455; position (400, 360) -> (405, 364); "
        "individual splice gain: +7 section frames (74 -> 67; 388 to 462); "
        "cumulative gain through this splice: +6 frames at this checkpoint vs input; "
        "vs input run: +6 frames saved, -4 px saved (max-y); "
        "vs best run: +6 frames saved, -4 px saved (max-y)"
    )
    output = TTY()
    monkeypatch.setattr(sys, 'stdout', output)
    _print_user_splice_progress(progress, color=True, level_identifier='01-0')
    printed = output.getvalue()
    assert "01-0 [auto:user-splice:temporary] round 1 stage 6/6 \x1b[1m'462'\x1b[22m: new stage best" in printed
    assert '\n  individual splice gain:' in printed
    assert '\n  vs input run: \x1b[1m+6\x1b[22m' in printed


def test_propagated_summary_preserves_status_and_final_splice(monkeypatch):
    message = (
        "[auto:user-splice:summary:propagated] 'end': covered by best (different route) "
        "(saved); downstream gain: final named splice; splice: frame 90; min-x 100; "
        "full run: frame 89; min-x 99; individual splice gain: +1 frames from start; "
        "cumulative gain through this splice: +1 frames at this checkpoint vs input; "
        "vs input run: +1 frames saved, +1 px saved (min-x); "
        "vs best run: -1 frames saved, -1 px saved (min-x)"
    )
    text = _format_user_splice_report(message, level_identifier='01-0')
    assert "[auto:user-splice:summary:propagated] 'end':" in text
    assert '\n  status: covered by best (different route) (saved);' in text
    assert '\n  downstream gain: final named splice;' in text
    assert '\n  vs best run: -1 frames, -1 px (min-x)' in text
