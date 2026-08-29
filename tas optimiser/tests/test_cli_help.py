from __future__ import annotations

import re

import pytest

import optimize_replay as opt


def _lists_option(help_text: str, option: str) -> bool:
    pattern = rf"^\s+{re.escape(option)}(?:\s|,|$)"
    return re.search(pattern, help_text, flags=re.MULTILINE) is not None


def test_subcommand_help_lists_only_relevant_mode_options() -> None:
    parser = opt.build_parser()
    help_text = {
        mode: command.format_help()
        for mode, command in parser._command_parsers.items()
    }

    assert _lists_option(help_text["auto"], "--iterations")
    assert _lists_option(help_text["auto"], "--auto-objective")
    assert _lists_option(
        help_text["auto"], "--auto-beam-repair-revisit-limit"
    )
    assert _lists_option(
        help_text["auto"], "--auto-splice-repair-revisit-limit"
    )
    assert _lists_option(help_text["auto"], "--workers")
    assert not _lists_option(help_text["auto"], "--target-frame")
    assert not _lists_option(help_text["auto"], "--window")
    assert not _lists_option(help_text["auto"], "--jumps")

    assert _lists_option(help_text["local"], "--target-frame")
    assert _lists_option(help_text["local"], "--window")
    assert _lists_option(help_text["local"], "--seed")
    assert _lists_option(help_text["local"], "--python-resimulate")
    assert not _lists_option(help_text["local"], "--iterations")
    assert not _lists_option(help_text["local"], "--jumps")
    assert not _lists_option(help_text["local"], "--auto-objective")

    assert _lists_option(help_text["jump-pattern"], "--target-frame")
    assert _lists_option(help_text["jump-pattern"], "--jumps")
    assert _lists_option(help_text["jump-pattern"], "--fixed-jump-frames")
    assert _lists_option(help_text["jump-pattern"], "--python-resimulate")
    assert not _lists_option(help_text["jump-pattern"], "--iterations")
    assert not _lists_option(help_text["jump-pattern"], "--window")
    assert not _lists_option(help_text["jump-pattern"], "--seed")
    assert not _lists_option(help_text["auto"], "--python-resimulate")

    for mode_help in help_text.values():
        assert not _lists_option(mode_help, "--non-strict-shapes")


@pytest.mark.parametrize(
    ("mode", "wrong_options"),
    (
        ("local", ("--iterations", "-1")),
        ("jump-pattern", ("--seed", "random")),
        ("local", ("--auto-no-deterministic",)),
    ),
)
def test_wrong_mode_cli_options_are_rejected(
    mode: str, wrong_options: tuple[str, ...]
) -> None:
    parser = opt.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([mode, "input.txt", *wrong_options])


@pytest.mark.parametrize("mode", ("auto", "local", "jump-pattern"))
def test_removed_non_strict_shapes_option_is_rejected(mode: str) -> None:
    parser = opt.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([mode, "input.txt", "--non-strict-shapes"])
