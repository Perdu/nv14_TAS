"""In-memory range correction follows actual checkpoint times without editing files."""
from dataclasses import replace
import io

import pytest

from nv14_endpoint import EndpointEvaluation, EndpointGoal
from nv14_user_splice import UserSpliceStage, _adapt_named_stage_range
from nv14_cli import _load_config_defaults, _print_user_splice_progress, build_parser
from nv14_random_splice import RandomSpliceConfig


def scored(frame):
    return EndpointEvaluation(feasible=True, score=-frame, frame=frame,
                              x=0, y=0, vx=0, vy=0,
                              missing_interactions=frozenset(),
                              violated_interactions=frozenset(), dead=False,
                              progress_key=(0, frame), state_key=b'', niche_key=())


def test_previous_or_two_back_extends_search_start_without_shrinking():
    original = UserSpliceStage('399', EndpointGoal(399, 'max-x'), 350, 399)
    adjusted, warnings = _adapt_named_stage_range(original, [scored(320), scored(280)],
                                                    scored(345), lookback=50, warn_frames=300)
    assert (adjusted.start, adjusted.end) == (270, 399)
    assert original.start == 350  # persisted goal remains unchanged
    assert 'edit the splice file' in warnings[0]
    fallback, _ = _adapt_named_stage_range(original, [None, scored(280)], None,
                                           lookback=50, warn_frames=300)
    assert fallback.start == 230
    early, _ = _adapt_named_stage_range(original, [], scored(310),
                                        lookback=50, warn_frames=300)
    assert early.start == 310


def test_warnings_for_long_section_and_no_false_positive():
    stage = UserSpliceStage('end', EndpointGoal(800, 'max-x'), 20, 650)
    _, warnings = _adapt_named_stage_range(stage, [scored(50)], scored(600),
                                            lookback=50, warn_frames=300,
                                            measured_section=550)
    assert any('editable section' in item for item in warnings)
    assert any('measured section' in item for item in warnings)
    short = UserSpliceStage('next', EndpointGoal(150, 'max-x'), 50, 150)
    _, warnings = _adapt_named_stage_range(short, [scored(100)], scored(140),
                                            lookback=50, warn_frames=300)
    assert warnings == ()


def test_cli_and_multi_splicer_config(tmp_path):
    config = tmp_path / 'multi.toml'
    config.write_text('[multi-splicer]\nadaptive-range-lookback=65\n'
                      'section-warning-frames=260\n')
    parser = build_parser()
    _, multi = _load_config_defaults(config, parser._command_parsers['auto'], 'auto')
    assert multi['auto_splice_adaptive_range_lookback'] == 65
    assert multi['auto_splice_section_warning_frames'] == 260
    assert RandomSpliceConfig(adaptive_range_lookback=65, section_warning_frames=260)
    with pytest.raises(ValueError):
        RandomSpliceConfig(adaptive_range_lookback=0)


def test_range_warning_is_red_only_on_terminals(monkeypatch):
    import sys

    class TTY(io.StringIO):
        def isatty(self):
            return True

    line = "[auto:user-splice:range-warning] '399': edit the splice file"
    tty = TTY()
    monkeypatch.setattr(sys, 'stdout', tty)
    _print_user_splice_progress(line, color=True)
    assert '\x1b[31m' in tty.getvalue()
    assert 'edit the splice file' in tty.getvalue()
    plain = TTY()
    monkeypatch.setattr(sys, 'stdout', plain)
    _print_user_splice_progress(line, color=False)
    assert '\x1b[' not in plain.getvalue()


def test_independent_checkpoint_times_are_not_mislabeled_as_measured_section():
    stage = UserSpliceStage('next', EndpointGoal(800, 'max-x'), 500, 600)
    _, warnings = _adapt_named_stage_range(stage, [scored(1)], scored(750),
                                            lookback=50, warn_frames=300)
    assert not any('measured section' in item for item in warnings)
