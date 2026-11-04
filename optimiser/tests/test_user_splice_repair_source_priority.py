"""Repair provenance and locally fast sections, without broadening normal lookback."""
from __future__ import annotations

from dataclasses import replace

import nv14_user_splice as us
from nv14_engine import InputFrame
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_splice_merge import BridgeRepairResult
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline
from tests.test_user_splice_manual_input_merge import _finished_slow_run


def test_repair_uses_positional_input_even_when_it_is_in_memory_completed_best(monkeypatch):
    level, manual, _ = _baseline()  # Faster than the saved completion.
    old_saved = _finished_slow_run(level)
    assert manual != old_saved
    attempted = []

    def fake_bridge(_level, prefix, reference, **kwargs):
        attempted.append((tuple(prefix), tuple(reference), kwargs['completion_required']))
        return BridgeRepairResult((), 1, 5, 1)

    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_args, **_kwargs: ())
    monkeypatch.setattr(us, 'repair_suffix_grafts', fake_bridge)
    messages = []
    result = optimise_user_splices(
        level, manual,
        [UserSpliceStage('first', EndpointGoal(10, 'min-x'), 0, 10),
         UserSpliceStage('later', EndpointGoal(20, 'min-x'), 10, 20)],
        RandomSpliceConfig(iterations=2, repair_iterations=2),
        completion_policy='checkpoint', merge_stage_bests=True,
        merge_only=True, merge_repair_only=True, merge_repair_pairs=1, merge_verbose=True,
        saved_final_frames=old_saved, progress=messages.append)
    # The *old* saved final is still the suffix even though best_output is the
    # manually edited input. Repair must never silently replace that prefix.
    assert attempted == [(manual, old_saved, True)]
    assert result.frames == manual
    assert any('positional current input' in message and
               'saved completed' in message for message in messages)
    assert any('bridge current input -> saved completed' in message
               for message in messages)


def test_later_arriving_faster_section_gets_repair_attempt_with_default_sized_budget(
        monkeypatch):
    level, source, _ = _baseline()
    before = (InputFrame(left=True),) + source[1:]
    global_best = (InputFrame(left=True), InputFrame(left=True)) + source[2:]
    # This route reaches the current helper later in absolute time, but
    # traverses the previous-to-current interval in fewer frames.
    local_fast = (InputFrame(left=True), InputFrame(left=True),
                  InputFrame(left=True)) + source[3:]
    later = (InputFrame(left=True),) * 4 + source[4:]
    goal0 = EndpointGoal(10, 'earliest-arrival', target_region=(-1000, 1000, -1000, 1000))
    goal1 = EndpointGoal(20, 'earliest-arrival', target_region=(-1000, 1000, -1000, 1000))
    stages = [UserSpliceStage('72', goal0, 0, 10),
              UserSpliceStage('522', goal1, 10, 20),
              UserSpliceStage('614', EndpointGoal(25, 'min-x'), 20, 25)]
    original_evaluate = EndpointEvaluator.evaluate

    def section_evaluation(self, frames):
        score = original_evaluate(self, frames)
        if not self.goal.is_earliest:
            return score
        # Synthetic arrivals isolate the archive/scheduler behavior from
        # random mutation and replay physics. The helper objective ranks the
        # global best higher (17 vs 19), but section duration is 9 vs 5.
        at = tuple(frames)
        arrival = {
            global_best: (8, 17),
            local_fast: (14, 19),
        }.get(at, (9, 18))
        frame = arrival[0] if self.goal.target_frame == 10 else arrival[1]
        return replace(score, feasible=True, frame=frame, score=-float(frame))

    monkeypatch.setattr(EndpointEvaluator, 'evaluate', section_evaluation)
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_kw: ())
    attempted = []

    def fake_bridge(_level, prefix, suffix, **kwargs):
        attempted.append(tuple(prefix))
        return BridgeRepairResult((), 1, 5, 1)

    monkeypatch.setattr(us, 'repair_suffix_grafts', fake_bridge)
    config = RandomSpliceConfig(iterations=2, repair_iterations=2, save_frontier=2)
    # Five attempts for four primary sources plus one archived section. The
    # pre-patch52 scheduler spent all five attempts on primary routes first.
    optimise_user_splices(
        level, source, stages, config,
        completion_policy='checkpoint', merge_stage_bests=True,
        merge_only=True, merge_repair_only=True, merge_repair_pairs=5,
        saved_final_frames=source,
        saved_stage_candidates={'72': [before], '522': [global_best], '614': [later]},
        saved_stage_frontiers={'522': [global_best, local_fast]},
    )
    assert attempted[0] == source  # Positional input has strict priority.
    assert global_best in attempted
    assert local_fast in attempted  # The later-arriving, locally faster route survives.
    assert attempted.index(local_fast) < 5
