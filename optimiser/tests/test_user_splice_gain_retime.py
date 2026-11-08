"""Patch 87: deterministic gain retiming uses saved earliest-arrival timing.

The SWF is authoritative; these tests exercise the existing native simulator's
proposal/verification and never claim Flash-verified propagation.
"""
from __future__ import annotations

import pytest

import nv14_user_splice as us
from nv14_auto import evaluate_replay_with_sentinel
from nv14_cli import parse_arguments
from nv14_engine import InputFrame
from nv14_random_splice import RandomSpliceConfig
from nv14_splice_merge import gain_aware_suffix_retimes
from nv14_user_splice import optimise_user_splices
from tests.test_random_splice import _baseline
from tests.test_user_splice_manual_input_merge import _finished_slow_run
from tests.test_user_splice_repair_targeted import _stages


def test_retime_derives_exact_gain_and_keeps_source_prefix_immutable():
    fast = tuple(InputFrame(right=True) for _ in range(29))
    slow = (InputFrame(),) * 5 + fast
    trials = gain_aware_suffix_retimes(fast, slow, prefix_arrival=19,
                                       reference_arrival=24)
    assert {offset for offset, _ in trials} == {-2, -1, 1, 2}
    for offset, candidate in trials:
        assert candidate[:20] == fast[:20]
        assert len(candidate) == len(slow) - 5 - offset
        assert candidate[20:] == slow[25 + offset:]
        assert all(frame.jump_trigger is None for frame in candidate)
    # Exact time shift is naturally identical to the already-known fast run.
    assert 0 not in {offset for offset, _ in trials}


def test_checkpoint_can_end_exactly_at_the_protected_arrival():
    fast = (InputFrame(right=True),) * 20  # final frame is checkpoint arrival 19
    slow = (InputFrame(),) * 5 + (InputFrame(right=True),) * 29
    trials = gain_aware_suffix_retimes(fast, slow, prefix_arrival=19,
                                       reference_arrival=24)
    assert any(offset == 0 and len(replay) == 29 for offset, replay in trials)
    assert all(replay[:20] == fast for _, replay in trials)


def test_retime_achieves_verified_completion_without_stochastic_search(monkeypatch):
    level, fast, _ = _baseline()
    slow = _finished_slow_run(level)
    # A saved stage winner is not necessarily a full completion. This one
    # reaches the stage's goal earlier but then releases right too soon.
    stage_prefix = fast[:20] + (InputFrame(),) * 9
    assert evaluate_replay_with_sentinel(level, stage_prefix).finish_tick is None
    assert evaluate_replay_with_sentinel(level, slow).finish_tick == len(slow)
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *args, **kw: ())
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kw: pytest.fail('entered Auto/Local'))
    saved = []
    messages = []
    result = optimise_user_splices(
        level, slow, _stages(level, fast), RandomSpliceConfig(iterations=2),
        merge_stage_bests=True, merge_only=True, merge_retime_gains=True,
        merge_repair_from='527', merge_repair_to='completed',
        saved_final_frames=slow, saved_stage_candidates={'527': [stage_prefix]},
        best_callback=saved.append, progress=messages.append,
    )
    assert result.improvements == 1 and result.attempts == 0
    assert len(result.frames) == len(fast) == 29
    assert saved and len(saved[-1]) == 29
    assert all(replay[:20] == stage_prefix[:20] for replay in saved)
    assert any('improved verified completed replay' in log for log in messages)


def test_nearby_shifts_preserve_binary_held_inputs_and_jump_edges():
    fast = tuple(InputFrame(jump=(i >= 8)) for i in range(15))
    old = (InputFrame(),) * 4 + tuple(InputFrame(jump=(i >= 8)) for i in range(15))
    trials = gain_aware_suffix_retimes(fast, old, prefix_arrival=10,
                                       reference_arrival=14)
    for _, candidate in trials:
        assert candidate[:11] == fast[:11]
        assert candidate[10].jump
        assert candidate[0] == InputFrame()


@pytest.mark.parametrize('fast_frame,old_frame', [(-1, 12), (12, 12), (15, 19), (4, 21)])
def test_invalid_or_non_positive_gain_never_creates_proposals(fast_frame, old_frame):
    f = (InputFrame(right=True),) * 15
    r = (InputFrame(),) * 20
    assert not gain_aware_suffix_retimes(f, r, prefix_arrival=fast_frame,
                                         reference_arrival=old_frame)


def test_retime_cli_alias_toml_and_override(tmp_path):
    base = parse_arguments(['auto', 'replay.ltm'])
    assert not base.auto_splice_merge_retime_gains
    for flag in ('--retime-gains', '--splice-merge-retime-gains'):
        args = parse_arguments(['auto', 'replay.ltm', flag])
        assert args.auto_splice_merge_retime_gains
    config = tmp_path / 'multi.toml'
    config.write_text('[multi-splicer]\nfiles = ["527", "599"]\n'
                      'merge-retime-gains = true\n', encoding='utf8')
    assert parse_arguments(['auto', 'replay.ltm', '--splice-config', str(config)]).auto_splice_merge_retime_gains
    args = parse_arguments(['auto', 'replay.ltm', '--splice-config', str(config),
                            '--from', '527', '--to', 'completed'])
    assert args.auto_splice_merge_repair_from == '527'
    assert args.auto_splice_merge_repair_to == 'completed'


def test_standalone_retime_sweeps_saved_splices_without_backend_search(monkeypatch):
    level, fast, _ = _baseline()
    slow = _finished_slow_run(level)
    called = []
    # Make direct grafting inert to isolate this pass's behaviour.
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *args, **kw: ())
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kw: pytest.fail('entered Auto/Local'))
    original = us.gain_aware_suffix_retimes

    def record(prefix, reference, **kwargs):
        called.append((tuple(prefix), tuple(reference), kwargs))
        return original(prefix, reference, **kwargs)

    monkeypatch.setattr(us, 'gain_aware_suffix_retimes', record)
    messages = []
    result = optimise_user_splices(
        level, slow, _stages(level, fast), RandomSpliceConfig(iterations=2),
        merge_stage_bests=True, merge_only=True, merge_retime_gains=True,
        saved_final_frames=slow, saved_stage_candidates={'527': [fast], '599': [slow]},
        progress=messages.append,
    )
    assert called
    assert any(v['reference_arrival'] > v['prefix_arrival'] for _, _, v in called)
    assert any('gain-aware suffix retime:' in msg for msg in messages)
    assert result.attempts == 0 and result.evaluations > 0
    assert evaluate_replay_with_sentinel(level, result.frames).valid


def test_retime_from_and_to_filter_pairs(monkeypatch):
    level, fast, _ = _baseline()
    slow = _finished_slow_run(level)
    pairs = []
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *args, **kw: ())
    original = us.gain_aware_suffix_retimes

    def record(prefix, ref, **kw):
        pairs.append((tuple(prefix), tuple(ref)))
        return original(prefix, ref, **kw)

    monkeypatch.setattr(us, 'gain_aware_suffix_retimes', record)
    logs = []
    optimise_user_splices(
        level, slow, _stages(level, fast), RandomSpliceConfig(iterations=2),
        merge_stage_bests=True, merge_only=True, merge_retime_gains=True,
        merge_repair_from='527', merge_repair_to='completed',
        saved_final_frames=slow, saved_stage_candidates={'527': [fast], '599': [slow]},
        progress=logs.append,
    )
    assert pairs and all(ref == slow for _, ref in pairs)
    assert any('gain-aware suffix retime:' in msg for msg in logs)


def test_invalid_flag_requires_merging():
    level, fast, _ = _baseline()
    with pytest.raises(ValueError, match='requires saved-stage merging'):
        optimise_user_splices(level, fast, _stages(level, fast),
                              RandomSpliceConfig(iterations=1), merge_retime_gains=True)


def test_cli_standalone_retime_never_enters_regular_stage_search(
        tmp_path, monkeypatch, capsys):
    import sys
    from nv14_cli import main
    from tests.test_user_splice_list_summary import _setup, _write_combined

    level, source, _, output, _, argv = _setup(tmp_path)
    _write_combined(output, level, source)
    monkeypatch.setattr(us, '_search_stage',
                        lambda *a, **kw: pytest.fail('ran a regular Auto/Local stage'))
    # An explicit merge-bests setting must not turn the retime-only command
    # into a multi-round stochastic search.
    monkeypatch.setattr(sys, 'argv', [*argv, '--retime-gains', '--splice-merge-bests'])
    main()
    assert 'gain-aware suffix retime:' in capsys.readouterr().out
