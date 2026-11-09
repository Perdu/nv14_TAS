"""Reporting saved replay propagation independently of other stage winners."""
from __future__ import annotations

from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def test_summary_traces_same_saved_replay_through_later_splices():
    level, source, _ = _baseline()
    # The saved replay improves min-x at ticks 10 and 20, but not max-x at 25.
    # A different archived winner for stage c must not be used to fabricate
    # a continuous advantage for stage a.
    saved = (InputFrame(left=True),) + source[1:]
    stages = [UserSpliceStage('a', EndpointGoal(10, 'min-x'), 0, 10),
              UserSpliceStage('b', EndpointGoal(20, 'min-x'), 11, 20),
              UserSpliceStage('c', EndpointGoal(25, 'max-x'), 21, 25)]
    log = []
    optimise_user_splices(level, source, stages,
                          RandomSpliceConfig(rounds=1, iterations=2, workers=1),
                          saved_stage_candidates={'a': [saved], 'c': [source]},
                          saved_final_frames=source, summary_only=True,
                          progress=log.append)
    row = next(s for s in log if '[auto:user-splice:summary:pending] \'a\'' in s)
    assert "same-replay downstream gain: as far as 'b'" in row
    assert "next 'c' (no objective gain vs best)" in row
    assert 'through \'c\'' not in row


def test_summary_reports_when_first_downstream_helper_is_not_improved():
    level, source, _ = _baseline()
    saved = (InputFrame(left=True),) + source[1:]
    stages = [UserSpliceStage('a', EndpointGoal(10, 'min-x'), 0, 10),
              UserSpliceStage('b', EndpointGoal(20, 'max-x'), 11, 20)]
    log = []
    optimise_user_splices(level, source, stages,
                          RandomSpliceConfig(rounds=1, iterations=2, workers=1),
                          saved_stage_candidates={'a': [saved]},
                          saved_final_frames=source, summary_only=True,
                          progress=log.append)
    row = next(s for s in log if '[auto:user-splice:summary:pending] \'a\'' in s)
    assert "same-replay downstream gain: none; next 'b' (no objective gain vs best)" in row


def test_same_replay_reach_never_counts_stage_after_physical_death():
    from tests.test_user_splice_partial_propagation import _guarded
    level = _guarded(130)
    fast = (InputFrame(right=True),) * 29
    slow = (InputFrame(),) * 5 + (InputFrame(right=True),) * 50
    # The later goal is reachable with enemies disabled but the source
    # dies at frame 10 in full physics. Do not report a propagated gain.
    stages = [UserSpliceStage('early', EndpointGoal(5, 'max-x'), 0, 5,
                              simulate_enemies=False),
              UserSpliceStage('later', EndpointGoal(20, 'max-x'), 6, 20,
                              simulate_enemies=False)]
    logs = []
    optimise_user_splices(level, slow, stages,
                          RandomSpliceConfig(rounds=1, iterations=2, workers=1),
                          completion_policy='checkpoint',
                          saved_stage_candidates={'early': [fast]},
                          summary_only=True, progress=logs.append)
    row = next(line for line in logs if "'early'" in line and ':summary:pending]' in line)
    assert 'same-replay downstream gain: through' not in row
    assert 'same-replay downstream gain: none' in row
    assert "next 'later'" in row


def test_summary_not_blocked_by_optional_intermediate_helper():
    level, source, _ = _baseline()
    saved = (InputFrame(left=True),) + source[1:]
    stages = [UserSpliceStage('a', EndpointGoal(10, 'min-x'), 0, 10),
              UserSpliceStage('b', EndpointGoal(20, 'max-x'), 11, 20),
              UserSpliceStage('c', EndpointGoal(25, 'min-x'), 21, 25)]
    logs = []
    optimise_user_splices(level, source, stages,
                          RandomSpliceConfig(rounds=1, iterations=2, workers=1),
                          saved_stage_candidates={'a': [saved]},
                          saved_final_frames=source, summary_only=True,
                          progress=logs.append)
    row = next(s for s in logs if "'a'" in s and ':summary:pending]' in s)
    assert "same-replay downstream gain: as far as 'c'" in row
    assert "nonconsecutive (no gain at 'b')" in row
