"""Patch 52: bounded verified bridges, standalone/final switches and fairness."""
from __future__ import annotations

import sys

import pytest

import nv14_user_splice as us
from nv14_auto import evaluate_replay_with_sentinel
from nv14_cli import main, parse_arguments
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_splice_merge import BridgeRepairResult, repair_suffix_grafts
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline
from tests.test_user_splice_manual_input_merge import _finished_slow_run
from tests.test_user_splice_list_summary import _setup


def test_cli_repair_modes_and_toml_settings(tmp_path):
    args = parse_arguments(['auto', 'replay.ltm'])
    assert not args.auto_splice_merge_repair_only
    assert not args.auto_splice_merge_repair_at_end
    assert args.auto_splice_merge_repair_pairs == 48
    assert args.auto_splice_merge_repair_window == 48
    assert args.auto_splice_merge_repair_targets == 2
    for switch, dest in (('--splice-merge-repair-only', 'auto_splice_merge_repair_only'),
                         ('--splice-merge-repair-at-end', 'auto_splice_merge_repair_at_end')):
        assert getattr(parse_arguments(['auto', 'replay.ltm', switch]), dest)
    config = tmp_path / 'config.toml'
    config.write_text('[multi-splicer]\nfiles=["first","end"]\n'
                      'merge-repair-at-end=true\nmerge-repair-pairs=9\n'
                      'merge-repair-window=24\nmerge-repair-targets=3\n'
                      'repair-iterations=17\n')
    args = parse_arguments(['auto', 'replay.ltm', '--splice-config', str(config)])
    assert args.auto_splice_merge_repair_at_end is True
    assert args.auto_splice_merge_repair_pairs == 9
    assert args.auto_splice_merge_repair_window == 24
    assert args.auto_splice_merge_repair_targets == 3
    assert args.auto_splice_repair_iterations == 17


def test_bridge_repairs_inputs_using_local_backend_then_verifies_completed_join():
    level, original, _ = _baseline()
    reference = _finished_slow_run(level)
    modified = list(reference)
    modified[16] = InputFrame(left=True)
    modified = tuple(modified)
    searches = []
    def fake_search(_level, _branch, _goal, *, start, editable_end,
                    config, iterations, rounds, seed, include_partial):
        searches.append((start, editable_end, config.search_backend, iterations))
        assert include_partial and rounds == 1
        assert 16 >= start
        # The backend changes only a bounded window, reconnecting the saved
        # continuation without a free mutation of the earlier prefix.
        return ((reference, editable_end),), 17
    result = repair_suffix_grafts(
        level, modified, reference, seam_frame=20,
        config=RandomSpliceConfig(search_backend='local', repair_iterations=9),
        window=8, targets=2, completion_required=True, seed=123,
        local_search=fake_search)
    assert result.searches >= 1 and result.evaluations >= 17
    assert searches and all(mode == 'local' for _, _, mode, _ in searches)
    assert result.grafts
    assert all(evaluate_replay_with_sentinel(level, item).valid for item in result.grafts)
    assert all(evaluate_replay_with_sentinel(level, item).finish_tick == len(item)
               for item in result.grafts)


def test_bridge_rejects_backend_mutation_outside_immutable_prefix():
    level, _original, _ = _baseline()
    reference = _finished_slow_run(level)
    modified = list(reference)
    modified[16] = InputFrame(left=True)
    def illegal_search(_level, _frames, _goal, **kwargs):
        bad = list(reference)
        bad[0] = InputFrame(left=True)
        return ((tuple(bad), kwargs['editable_end']),), 1
    result = repair_suffix_grafts(
        level, modified, reference, seam_frame=20,
        config=RandomSpliceConfig(search_backend='local', repair_iterations=3),
        window=5, targets=1, completion_required=True, seed=12,
        local_search=illegal_search)
    assert result.searches == 1
    assert not result.grafts


def test_repair_only_independent_stage_failures_cannot_block_other_sources(monkeypatch):
    level, fast, _ = _baseline()
    slow = _finished_slow_run(level)
    stages = [UserSpliceStage(name, EndpointGoal(10 + i * 4, 'min-x'), 0, 10 + i * 4)
              for i, name in enumerate(('522', '564', '614'))]
    good = (InputFrame(left=True),) + slow[1:]
    blocked = (InputFrame(), InputFrame(left=True)) + slow[2:]
    later_section = (InputFrame(), InputFrame(), InputFrame(left=True)) + slow[3:]
    calls = []
    def fake_bridge(_level, prefix, suffix, **kwargs):
        calls.append((prefix, suffix, kwargs['completion_required']))
        if prefix == good and suffix == slow:
            return BridgeRepairResult((fast,), 1, 7, 1)
        if prefix == blocked:
            raise ValueError("unmergeable 564 fixture")
        return BridgeRepairResult((), 1, 7, 1)
    monkeypatch.setattr(us, 'repair_suffix_grafts', fake_bridge)
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_k: ())
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_k: pytest.fail('ran normal search'))
    messages, completed = [], []
    result = optimise_user_splices(
        level, slow, stages,
        RandomSpliceConfig(iterations=4, repair_iterations=3),
        completion_policy='checkpoint', merge_stage_bests=True,
        merge_only=True, merge_repair_only=True, merge_repair_pairs=8, merge_verbose=True,
        saved_final_frames=slow,
        saved_stage_candidates={'522': [good], '564': [blocked], '614': [later_section]},
        progress=messages.append, best_callback=completed.append)
    assert 0 < result.attempts < len(calls)  # failed preflight pairs use no backend searches
    assert completed and completed[-1] == fast
    assert result.improvements >= 1
    assert calls and any(prefix == blocked for prefix, *_ in calls)
    assert any(prefix == good and suffix == later_section for prefix, suffix, _ in calls)
    assert any('no verified graft' in message for message in messages)
    assert any('unmergeable 564 fixture' in message and 'continuing' in message
               for message in messages)
    assert any('bridge repair done' in message for message in messages)
    assert any('independent' in message for message in messages)


def test_fast_merge_only_never_runs_bridge_repair(monkeypatch):
    level, source, _ = _baseline()
    stages = [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
              for name in ('first', 'end')]
    monkeypatch.setattr(us, 'repair_suffix_grafts', lambda *_a, **_k: pytest.fail('started expensive repair'))
    result = optimise_user_splices(
        level, source, stages, RandomSpliceConfig(iterations=2),
        merge_stage_bests=True, merge_only=True)
    assert (result.attempts, result.evaluations) == (0, 0)


def test_end_of_run_repair_runs_after_regular_stages(monkeypatch):
    level, source, _ = _baseline()
    stages = [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
              for name in ('first', 'end')]
    messages, order = [], []
    def fake_search(*_a, **_kw):
        order.append('normal')
        return (), 1, 1
    def fake_bridge(*_a, **_kw):
        order.append('repair')
        return BridgeRepairResult((), 1, 3, 1)
    monkeypatch.setattr(us, '_search_stage', fake_search)
    monkeypatch.setattr(us, 'repair_suffix_grafts', fake_bridge)
    optimise_user_splices(level, source, stages,
        RandomSpliceConfig(rounds=1, iterations=2),
        merge_stage_bests=True, merge_repair_at_end=True,
        saved_stage_candidates={'first': [(InputFrame(left=True),) + source[1:]]},
        merge_repair_pairs=2, progress=messages.append)
    assert 'normal' in order and 'repair' in order
    assert order.index('normal') < order.index('repair')
    assert any('bridge repair done' in message for message in messages)


def test_cli_standalone_repair_has_no_resume_sidecars(tmp_path, monkeypatch, capsys):
    _level, _source, _saved, output, _packed, argv = _setup(tmp_path)
    monkeypatch.setattr(us, '_search_stage', lambda *_a, **_k: pytest.fail('ran Auto/Local campaign'))
    monkeypatch.setattr(us, 'repair_suffix_grafts',
                        lambda *_a, **_kw: BridgeRepairResult((), 1, 3, 1))
    monkeypatch.setattr(sys, 'argv', [*argv, '--splice-merge-repair-only',
                                     '--splice-merge-repair-at-end',
                                     '--splice-merge-repair-pairs', '1'])
    main()
    assert '[auto:user-splice:repair-only]' in capsys.readouterr().out
    assert not output.with_suffix('.splice-search.json').exists()
    assert not output.with_suffix('.splice-progress.json').exists()


def test_real_local_and_endpoint_backends_produce_verified_grafts():
    """Small real-engine smoke, not only mocked search-result tests."""
    level, _, _ = _baseline()
    reference = _finished_slow_run(level)
    edited = list(reference)
    edited[16] = InputFrame(left=True)
    for backend in ('local', 'endpoint-auto'):
        result = repair_suffix_grafts(
            level, edited, reference, seam_frame=20, window=8, targets=1,
            config=RandomSpliceConfig(
                search_backend=backend, repair_iterations=10, beam=4, workers=1),
            completion_required=True, seed=123)
        assert result.searches == 1 and result.evaluations > 0
        assert result.grafts
        for graft in result.grafts:
            checked = evaluate_replay_with_sentinel(level, graft)
            assert checked.valid and checked.finish_tick == len(graft)
            assert graft[:12] == tuple(edited[:12])


def test_section_archive_keeps_fastest_segment_even_if_global_rank_is_worse():
    from types import SimpleNamespace
    from nv14_user_splice import _diverse_saved_archive
    ranked = [((InputFrame(right=True),) * i + (InputFrame(left=True),) * (5-i))
              for i in (1, 2, 3, 4)]
    scores = {frames: (score,) for score, frames in enumerate(ranked)}
    class Evaluator:
        def evaluate(self, frames):
            return SimpleNamespace(x=scores[frames][0], y=0, vx=0, vy=0)
    selected = _diverse_saved_archive(scores, Evaluator(), limit=2,
                                      preserve=(ranked[-1],))
    assert selected == [ranked[0], ranked[-1]]


def test_section_duration_is_reported_only_for_time_measured_objectives():
    level, source, _ = _baseline()
    checked = evaluate_replay_with_sentinel(level, source)
    def region(tick):
        point = checked.point(tick)
        return (point.x - 0.05, point.x + 0.05, point.y - 0.05, point.y + 0.05)
    stages = [
        UserSpliceStage('first', EndpointGoal(16, 'earliest-arrival',
                                           target_region=region(10)), 0, 16),
        UserSpliceStage('second', EndpointGoal(23, 'earliest-arrival',
                                            target_region=region(19)), 16, 23),
    ]
    output = []
    optimise_user_splices(
        level, source, stages, RandomSpliceConfig(rounds=1, iterations=3),
        saved_stage_candidates={'first': [source], 'second': [source]},
        summary_only=True, progress=output.append)
    assert any('from first: ' in line and 'section frames' in line
               for line in output if "'second'" in line)
    assert not any('section frames' in line for line in output if "'first'" in line)
