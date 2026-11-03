"""Patch 56: repair completed replays shorter than later splice deadlines."""
from __future__ import annotations

import nv14_user_splice as us
from nv14_auto import evaluate_replay_with_sentinel
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_splice_merge import BridgeRepairResult, repair_suffix_grafts
from nv14_user_splice import UserSpliceStage, optimise_user_splices, _materialise_splice_tail
from tests.test_random_splice import _baseline
from tests.test_user_splice_manual_input_merge import _finished_slow_run


def test_repair_only_accepts_completed_best_shorter_than_later_helper(monkeypatch):
    level, edited_input, _ = _baseline()  # Completes in 29 frames.
    saved_final = _finished_slow_run(level)  # Different, slower completed replay.
    assert len(edited_input) < len(saved_final) < 41
    goals = [UserSpliceStage('first', EndpointGoal(10, 'min-x'), 0, 10),
             UserSpliceStage('end', EndpointGoal(40, 'min-x'), 10, 40)]
    # The real bridge backend isn't needed to reproduce the crash: the old
    # repair source-filter itself evaluates the 29-frame best at frame 40.
    attempts = []

    def bridge(_level, prefix, suffix, **_kwargs):
        attempts.append((tuple(prefix), tuple(suffix)))
        return BridgeRepairResult((), searches=1, evaluations=1, targets=1)

    monkeypatch.setattr(us, 'repair_suffix_grafts', bridge)
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_k: ())
    messages = []
    result = optimise_user_splices(
        level, edited_input, goals,
        RandomSpliceConfig(iterations=2, repair_iterations=2, workers=1),
        merge_stage_bests=True, merge_only=True, merge_repair_only=True,
        merge_repair_pairs=4, saved_final_frames=saved_final,
        saved_stage_candidates={'first': [edited_input], 'end': [saved_final]},
        progress=messages.append,
    )
    assert result.frames == edited_input
    assert attempts  # A short completed best cannot stop later pairs.
    assert any('bridge repair done' in line for line in messages)


def test_bridge_does_not_target_neutral_tail_after_completed_replay():
    level, completed, _ = _baseline()  # 29-frame canonical finish.
    saved_final = _finished_slow_run(level)
    padded = _materialise_splice_tail(completed, 50)
    assert len(padded) == 51
    assert evaluate_replay_with_sentinel(level, padded).finish_tick == len(completed)
    searched = []

    def search(_level, frames, goal, **kwargs):
        searched.append((goal.target_frame, kwargs['editable_end'], len(frames)))
        return (), 1

    result = repair_suffix_grafts(
        level, padded, saved_final,
        seam_frame=45, window=32, targets=2,
        config=RandomSpliceConfig(search_backend='local', repair_iterations=3),
        completion_required=True, seed=17, local_search=search,
    )
    assert searched
    assert result.searches == len(searched)
    assert all(target <= len(completed) - 2 and end == target and length == len(padded)
               for target, end, length in searched)
