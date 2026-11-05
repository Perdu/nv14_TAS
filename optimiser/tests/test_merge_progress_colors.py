"""Color meaningful outcomes, but keep redirected logs clean."""
from io import StringIO

import nv14_cli as cli

class Terminal(StringIO):
    def isatty(self):
        return True


def test_merge_colors_provisional_yellow_and_completed_green(monkeypatch):
    stream = Terminal()
    monkeypatch.setattr(cli.sys, 'stdout', stream)
    cli._print_user_splice_progress(
        '[auto:user-splice:merge-only] 522 -> 614: new saved stage best', color=True)
    cli._print_user_splice_progress(
        '[auto:user-splice:merge] 522 -> end: improved verified completed replay at 788 frames', color=True)
    cli._print_user_splice_progress(
        '[auto:user-splice:repair-only] 522 -> end: verified completed join accepted', color=True)
    cli._print_user_splice_progress(
        '[auto:user-splice:merge-only] done: 100 pairs considered', color=True)
    assert stream.getvalue().count('\x1b[33m') == 1
    assert stream.getvalue().count('\x1b[32m') == 2
    assert 'done: 100 pairs considered' in stream.getvalue()


def test_merge_redirected_logs_stay_plain(monkeypatch):
    stream = StringIO()
    monkeypatch.setattr(cli.sys, 'stdout', stream)
    cli._print_user_splice_progress(
        '[auto:user-splice:merge-only] saved stage best', color=True)
    assert '\x1b' not in stream.getvalue()
