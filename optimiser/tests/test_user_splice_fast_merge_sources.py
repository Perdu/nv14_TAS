"""Patch 54: the *fast* merge must prioritize edits and local sections.

These checks intentionally use --splice-merge-only, not bridge repair.  No
endpoint/Local mutation search may be involved in deciding the tested order.
"""
from __future__ import annotations

from dataclasses import replace

import nv14_user_splice as us
from nv14_engine import InputFrame
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline
from tests.test_user_splice_manual_input_merge import _finished_slow_run


def _no_mutations(*_args, **_kwargs):
    raise AssertionError('--splice-merge-only performed a mutation search')


def test_fast_merge_attempts_positional_input_against_saved_completion_first(monkeypatch):
    level, input_run, _ = _baseline()
    saved_run = _finished_slow_run(level)
    assert input_run != saved_run
    calls = []

    def fake_graft(_level, prefix, suffix, **kwargs):
        calls.append((tuple(prefix), tuple(suffix), kwargs))
        return ()

    monkeypatch.setattr(us, 'verified_suffix_grafts', fake_graft)
    monkeypatch.setattr(us, '_search_stage', _no_mutations)
    monkeypatch.setattr(us, 'repair_suffix_grafts', _no_mutations)
    messages = []
    optimise_user_splices(
        level, input_run,
        [UserSpliceStage('72', EndpointGoal(10, 'min-x'), 0, 10),
         UserSpliceStage('522', EndpointGoal(20, 'min-x'), 10, 20)],
        RandomSpliceConfig(iterations=2),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_final_frames=saved_run,
        saved_stage_candidates={'72': [saved_run], '522': [saved_run]},
        progress=messages.append,
    )
    assert calls
    assert calls[0][0][:len(input_run)] == input_run
    assert calls[0][1] == saved_run
    assert calls[0][2]['completion_required'] is True
    assert any('current-input graft attempt(s)' in msg for msg in messages)
    assert not any('bridge sources' in msg for msg in messages)


def test_fast_merge_preserves_manual_edits_when_joining_saved_suffix(monkeypatch):
    level, saved_run, _ = _baseline()
    edit_frame = 6
    manual = saved_run[:edit_frame] + (InputFrame(left=True),) + saved_run[edit_frame+1:]
    assert manual != saved_run
    calls = []

    def fake_graft(_level, prefix, suffix, **kwargs):
        if tuple(prefix)[:len(manual)] == manual and tuple(suffix) == saved_run:
            calls.append(kwargs['min_prefix_frame'])
        return ()

    monkeypatch.setattr(us, 'verified_suffix_grafts', fake_graft)
    monkeypatch.setattr(us, '_search_stage', _no_mutations)
    optimise_user_splices(
        level, manual,
        [UserSpliceStage('72', EndpointGoal(10, 'min-x'), 0, 10),
         UserSpliceStage('522', EndpointGoal(20, 'min-x'), 10, 20)],
        RandomSpliceConfig(iterations=2),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_final_frames=saved_run,
    )
    assert calls and min(calls) >= edit_frame


def test_early_differences_in_saved_stage_cannot_hide_later_manual_edits(monkeypatch):
    level, completed, _ = _baseline()
    edit_at = 8
    manual = completed[:edit_at] + (InputFrame(left=True),) + completed[edit_at+1:]
    # A saved stage is already different at frame 0, but the positional input
    # was manually changed at frame 8 compared to the saved completed replay.
    alternative = (InputFrame(left=True),) + completed[1:]
    calls = []

    def fake_graft(_level, prefix, suffix, **kwargs):
        if tuple(prefix)[:len(manual)] == manual and tuple(suffix) == alternative:
            calls.append(kwargs['min_prefix_frame'])
        return ()

    monkeypatch.setattr(us, 'verified_suffix_grafts', fake_graft)
    optimise_user_splices(
        level, manual,
        [UserSpliceStage('72', EndpointGoal(10, 'min-x'), 0, 10),
         UserSpliceStage('522', EndpointGoal(20, 'min-x'), 10, 20)],
        RandomSpliceConfig(iterations=2),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_final_frames=completed,
        saved_stage_candidates={'72': [alternative], '522': [alternative]},
    )
    assert calls and min(calls) >= edit_at


def test_fast_merge_can_append_saved_tail_to_truncated_unedited_input(monkeypatch):
    level, saved_run, _ = _baseline()
    incomplete = saved_run[:18]
    calls = []

    def fake_graft(_level, prefix, suffix, **kwargs):
        if tuple(suffix) == saved_run:
            calls.append(kwargs['min_prefix_frame'])
        return ()

    monkeypatch.setattr(us, 'verified_suffix_grafts', fake_graft)
    optimise_user_splices(
        level, incomplete,
        [UserSpliceStage('72', EndpointGoal(10, 'min-x'), 0, 10),
         UserSpliceStage('522', EndpointGoal(20, 'min-x'), 10, 20)],
        RandomSpliceConfig(iterations=2),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_final_frames=saved_run,
    )
    assert calls and set(calls) == {1}


def test_fast_merge_uses_later_arriving_faster_archived_section_as_source_and_suffix(
        monkeypatch):
    level, source, _ = _baseline()
    before = (InputFrame(left=True),) + source[1:]
    global_winner = (InputFrame(left=True), InputFrame(left=True)) + source[2:]
    local_fast = (InputFrame(left=True), InputFrame(left=True),
                  InputFrame(left=True)) + source[3:]
    later = (InputFrame(left=True),) * 4 + source[4:]
    stages = [
        UserSpliceStage('72', EndpointGoal(10, 'earliest-arrival',
                                            target_region=(-1000, 1000, -1000, 1000)), 0, 10),
        UserSpliceStage('522', EndpointGoal(20, 'earliest-arrival',
                                             target_region=(-1000, 1000, -1000, 1000)), 10, 20),
        UserSpliceStage('614', EndpointGoal(25, 'min-x'), 20, 25),
    ]
    original_evaluate = EndpointEvaluator.evaluate

    def sample_arrivals(self, frames):
        result = original_evaluate(self, frames)
        if not self.goal.is_earliest:
            return result
        # Global winner reaches 522 at 17, but its section lasts 9 frames.
        # Local section arrives later overall (19) yet lasts only 5 frames.
        times = {global_winner: (8, 17), local_fast: (14, 19)}
        early, late = times.get(tuple(frames), (9, 18))
        frame = early if self.goal.target_frame == 10 else late
        return replace(result, feasible=True, frame=frame, score=-float(frame))

    monkeypatch.setattr(EndpointEvaluator, 'evaluate', sample_arrivals)
    calls = []

    def fake_graft(_level, prefix, suffix, **_kwargs):
        calls.append((tuple(prefix), tuple(suffix)))
        return ()

    monkeypatch.setattr(us, 'verified_suffix_grafts', fake_graft)
    monkeypatch.setattr(us, '_search_stage', _no_mutations)
    monkeypatch.setattr(us, 'repair_suffix_grafts', _no_mutations)
    messages = []
    optimise_user_splices(
        level, source, stages, RandomSpliceConfig(iterations=2, save_frontier=2),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_stage_candidates={'72': [before], '522': [global_winner], '614': [later]},
        saved_stage_frontiers={'522': [global_winner, local_fast]},
        progress=messages.append,
    )
    assert any(prefix == local_fast for prefix, _ in calls)
    assert any(suffix == local_fast for _, suffix in calls)
    assert any('archived-alternative graft attempt(s)' in m for m in messages)
    # No candidate actually joined, so no saved bests were changed.
    assert any('0 completed best(s) improved' in m for m in messages)


def test_unmergeable_stage_does_not_prevent_later_fast_stage_pair(monkeypatch):
    level, source, _ = _baseline()
    earlier = (InputFrame(left=True),) + source[1:]
    incompatible = (InputFrame(left=True),) * 2 + source[2:]
    later = (InputFrame(left=True),) * 3 + source[3:]
    calls = []

    def fake_graft(_level, prefix, suffix, **_kwargs):
        calls.append((tuple(prefix), tuple(suffix)))
        return ()

    monkeypatch.setattr(us, 'verified_suffix_grafts', fake_graft)
    optimise_user_splices(
        level, source,
        [UserSpliceStage('522', EndpointGoal(10, 'min-x'), 0, 10),
         UserSpliceStage('564', EndpointGoal(20, 'min-x'), 10, 20),
         UserSpliceStage('614', EndpointGoal(25, 'min-x'), 20, 25)],
        RandomSpliceConfig(iterations=2),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_stage_candidates={'522': [earlier], '564': [incompatible], '614': [later]},
    )
    assert (earlier, incompatible) in calls
    assert (earlier, later) in calls


def test_fast_merge_equal_section_duration_and_score_do_not_compare_input_frames(monkeypatch):
    """Different archived movies can tie on both ranking fields (user crash)."""
    level, source, _ = _baseline()
    # Three routes are indistinguishable at the two endpoint checkpoints,
    # but have different later inputs; the first is the saved stage best.
    archives = [source[:tick] + (InputFrame(left=True),) + source[tick+1:]
                for tick in (23, 24, 25)]
    assert len(set(archives)) == 3
    # Keep all the candidates so the tie is exercised inside merge_routes,
    # instead of being suppressed by an unrelated diversity limit.
    monkeypatch.setattr(us, '_diverse_saved_archive',
                        lambda pool, *_a, **_k: list(pool))
    calls = []
    monkeypatch.setattr(us, 'verified_suffix_grafts',
                        lambda _level, prefix, suffix, **_kwargs:
                        calls.append((tuple(prefix), tuple(suffix))) or ())
    monkeypatch.setattr(us, '_search_stage', _no_mutations)
    monkeypatch.setattr(us, 'repair_suffix_grafts', _no_mutations)
    messages = []
    stages = [
        UserSpliceStage('72', EndpointGoal(10, 'earliest-arrival',
                         target_region=(-1000, 1000, -1000, 1000)), 0, 10),
        UserSpliceStage('522', EndpointGoal(20, 'earliest-arrival',
                         target_region=(-1000, 1000, -1000, 1000)), 10, 20),
    ]
    optimise_user_splices(
        level, source, stages, RandomSpliceConfig(iterations=2, save_frontier=5),
        completion_policy='checkpoint', merge_stage_bests=True, merge_only=True,
        saved_stage_candidates={'522': [archives[0]]},
        saved_stage_frontiers={'522': archives}, progress=messages.append)
    # Equal durations and objective scores must choose the first remaining
    # archived route deterministically, without comparing InputFrame objects.
    assert any(prefix == archives[1] or suffix == archives[1]
               for prefix, suffix in calls)
    assert any('archived section' in msg for msg in messages)
    assert any('done:' in msg for msg in messages)
