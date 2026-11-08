"""Patch 85: short repair/merge CLI options are aliases, not new modes."""
from __future__ import annotations

import pytest

from nv14_cli import build_parser, parse_arguments
from tas import build_command


@pytest.mark.parametrize(("long_option", "short_option", "destination", "value"), [
    ("--splice-merge-only", "--merge", "auto_splice_merge_only", True),
    ("--splice-merge-repair-only", "--repair", "auto_splice_merge_repair_only", True),
    ("--splice-merge-repair-from", "--from", "auto_splice_merge_repair_from", "527"),
    ("--splice-merge-repair-to", "--to", "auto_splice_merge_repair_to", "599"),
])
def test_alias_matches_long_form(long_option, short_option, destination, value):
    args = ["auto", "replay.ltm"]
    value_args = [] if value is True else [value]
    long = parse_arguments([*args, long_option, *value_args])
    short = parse_arguments([*args, short_option, *value_args])
    assert getattr(short, destination) == getattr(long, destination) == value


def test_short_repair_flags_combine_and_preserve_existing_behavior():
    args = parse_arguments(["auto", "replay.ltm", "--repair", "--from", "527", "--to", "completed"])
    assert args.auto_splice_merge_repair_only is True
    assert args.auto_splice_merge_repair_from == "527"
    assert args.auto_splice_merge_repair_to == "completed"
    assert not args.auto_splice_merge_only  # repair implies merge in dispatch, as before
    assert parse_arguments(["auto", "replay.ltm", "--merge"]).auto_splice_merge_only


def test_alias_and_long_form_share_destination_and_last_value_wins():
    args = parse_arguments(["auto", "replay.ltm", "--from", "479",
                            "--splice-merge-repair-from", "527",
                            "--splice-merge-repair-to", "599", "--to", "completed"])
    assert args.auto_splice_merge_repair_from == "527"
    assert args.auto_splice_merge_repair_to == "completed"


def test_flags_are_available_only_in_auto_help():
    parser = build_parser()
    auto = parser._command_parsers["auto"].format_help()
    for option in ("--repair", "--merge", "--from", "--to"):
        assert option in auto
    for mode in ("local", "jump-pattern"):
        text = parser._command_parsers[mode].format_help()
        assert "--splice-merge-repair-only" not in text
        with pytest.raises(SystemExit):
            parser.parse_args([mode, "replay.ltm", "--repair"])


def test_tas_multi_forwards_short_flags_without_rewriting():
    argv = build_command("multi", "81-1", extra=("--repair", "--from", "527", "--to", "599"))
    assert argv[-5:] == ["--repair", "--from", "527", "--to", "599"]
    # The expansion includes a per-level TOML path not bundled with tests.
    # Parse the forwarded options independently of that external file.
    parsed = parse_arguments(["auto", "replay.ltm", *argv[-5:]])
    assert parsed.auto_splice_merge_repair_only is True
    assert parsed.auto_splice_merge_repair_from == "527"
    assert parsed.auto_splice_merge_repair_to == "599"
