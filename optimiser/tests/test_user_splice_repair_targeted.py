"""Patch 84: targeted, gain-aware, precision-preserving bridge repairs."""
from __future__ import annotations

from dataclasses import replace

import pytest

import nv14_user_splice as us
from nv14_auto import evaluate_replay_with_sentinel
from nv14_cli import parse_arguments
from nv14_endpoint import EndpointGoal
from nv14_engine import InputFrame
from nv14_random_splice import RandomSpliceConfig
from nv14_splice_merge import BridgeRepairResult, repair_suffix_grafts, repair_backend_schedule
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline
from tests.test_user_splice_manual_input_merge import _finished_slow_run


def test_target_cli_and_toml(tmp_path):
    args = parse_arguments(['auto', 'replay.ltm', '--splice-merge-repair-from', '527',
                            '--splice-merge-repair-to', '599'])
    assert (args.auto_splice_merge_repair_from, args.auto_splice_merge_repair_to) == ('527', '599')
    assert parse_arguments(['auto', 'replay.ltm']).auto_splice_merge_repair_from is None
    config = tmp_path / 'splices.toml'
    config.write_text('[multi-splicer]\nfiles=["527", "599"]\n'
                      'merge-repair-from="527"\nmerge-repair-to="completed"\n')
    args = parse_arguments(['auto', 'replay.ltm', '--splice-config', str(config)])
    assert (args.auto_splice_merge_repair_from, args.auto_splice_merge_repair_to) == ('527', 'completed')


def _stages(level, fast):
    point = evaluate_replay_with_sentinel(level, fast).point(19)
    assert point is not None
    return [
        UserSpliceStage('479', EndpointGoal(12, 'min-x'), 0, 12),
        UserSpliceStage('527', EndpointGoal(29, 'earliest-arrival',
                                         target_region=(point.x - 0.2, point.x + 0.2,
                                                        point.y - 0.2, point.y + 0.2),
                                         arrival_start=12), 12, 29),
        UserSpliceStage('599', EndpointGoal(35, 'min-x'), 29, 35),
    ]


def test_target_527_to_599_only_attempts_requested_bridge(monkeypatch):
    level, fast, _ = _baseline()
    slow = _finished_slow_run(level)
    targets = []

    def fake_repair(_level, prefix, suffix, **kw):
        targets.append((tuple(prefix), tuple(suffix), kw))
        return BridgeRepairResult((), searches=1, evaluations=7, targets=2)

    monkeypatch.setattr(us, 'repair_suffix_grafts', fake_repair)
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_args, **_kw: ())
    messages = []
    optimise_user_splices(
        level, slow, _stages(level, fast), RandomSpliceConfig(iterations=3),
        merge_stage_bests=True, merge_only=True, merge_repair_only=True,
        merge_repair_from='527', merge_repair_to='599', merge_repair_pairs=10,
        saved_final_frames=slow,
        saved_stage_candidates={'527': [fast], '599': [slow]},
        progress=messages.append,
    )
    assert targets, 'targeted repair should attempt an actual source/suffix pairing'
    assert all(source[:len(fast)] == fast and suffix[:len(slow)] == slow
               for source, suffix, _ in targets)
    assert any('from=527, to=599' in msg for msg in messages)
    assert all(kw['protected_through'] is not None for _, _, kw in targets)
    assert all(kw['seam_frame'] >= kw['protected_through'] for _, _, kw in targets)


def test_frame_gain_527_is_prioritized_before_unrelated_stages(monkeypatch):
    level, fast, _ = _baseline()
    slow = _finished_slow_run(level)
    attempted = []

    def fake_repair(_level, prefix, suffix, **kw):
        attempted.append(tuple(prefix))
        return BridgeRepairResult((), searches=1, evaluations=2, targets=1)

    monkeypatch.setattr(us, 'repair_suffix_grafts', fake_repair)
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_args, **_kw: ())
    optimise_user_splices(
        level, slow, _stages(level, fast), RandomSpliceConfig(iterations=2),
        merge_stage_bests=True, merge_only=True, merge_repair_only=True,
        merge_repair_pairs=3, saved_final_frames=slow,
        saved_stage_candidates={'527': [fast], '599': [slow]},
    )
    assert attempted and any(source[:len(fast)] == fast for source in attempted[:3])


@pytest.mark.parametrize(('backend', 'expected', 'share'), [
    ('hybrid', ('endpoint-auto', 'local'), True),
    ('hybrid-restart', ('endpoint-auto', 'local'), False),
    ('hybrid-local-control', ('local', 'local'), False),
    ('both', ('endpoint-auto', 'local'), False),
])
def test_hybrid_repair_maps_to_bounded_backends_with_optional_handoff(backend, expected, share):
    level, _, _ = _baseline()
    reference = _finished_slow_run(level)
    modified = list(reference)
    modified[16] = InputFrame(left=True)
    called = []

    def backend_search(_level, _branch, _goal, **kwargs):
        name = kwargs['config'].search_backend
        population = kwargs.get('initial_population', ())
        called.append((name, population, kwargs['iterations']))
        return ((reference, kwargs['editable_end']),), 3

    result = repair_suffix_grafts(
        level, modified, reference, seam_frame=20, window=8, targets=1,
        completion_required=True, seed=3,
        config=RandomSpliceConfig(search_backend=backend, repair_iterations=16),
        local_search=backend_search,
    )
    assert repair_backend_schedule(backend) == expected
    assert tuple(item[0] for item in called) == expected
    assert bool(called[1][1]) is share
    assert all(item[2] == 8 for item in called)
    assert result.searches == 2 and result.evaluations == 6
    assert result.grafts


def test_protected_checkpoint_inputs_are_never_changed_by_bridge_search():
    level, _, _ = _baseline()
    reference = _finished_slow_run(level)
    modified = list(reference)
    modified[16] = InputFrame(left=True)
    seen = []

    def invalid_search(_level, _branch, _goal, **kwargs):
        seen.append((kwargs['start'], kwargs['editable_end']))
        return ((reference, kwargs['editable_end']),), 1

    result = repair_suffix_grafts(
        level, modified, reference, seam_frame=20, window=8, targets=2,
        completion_required=True, seed=3, protected_through=16,
        config=RandomSpliceConfig(search_backend='local', repair_iterations=4),
        local_search=invalid_search,
    )
    assert seen and all(start >= 17 for start, end in seen)
    assert result.rejected_prefix >= 1
    assert not result.grafts


def test_invalid_selected_name_reports_no_pair_instead_of_falling_back(monkeypatch):
    level, fast, _ = _baseline()
    slow = _finished_slow_run(level)
    monkeypatch.setattr(us, 'repair_suffix_grafts', lambda *_a, **_kw: pytest.fail('ran unrelated repair'))
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_kw: ())
    messages = []
    optimise_user_splices(
        level, slow, _stages(level, fast), RandomSpliceConfig(iterations=2),
        merge_stage_bests=True, merge_only=True, merge_repair_only=True,
        merge_repair_from='missing', merge_repair_to='599',
        saved_final_frames=slow, saved_stage_candidates={'527': [fast], '599': [slow]},
        progress=messages.append,
    )
    assert any('is not in this route' in msg for msg in messages)
    assert any('0 source(s)' in msg for msg in messages)
