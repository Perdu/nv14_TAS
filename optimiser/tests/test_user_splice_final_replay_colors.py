"""Saving a better completion must not make a worse stage score green."""
from __future__ import annotations

import io
import sys

import pytest

import nv14_user_splice as us
from nv14_cli import _print_user_splice_progress
from nv14_engine import InputFrame
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


class TTY(io.StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize('historical_stage_is_better, color_code', [
    (True, 33), (False, 32),
])
@pytest.mark.parametrize('level_identifier', [None, '03-4'])
def test_final_replay_save_color_tracks_absolute_stage_best(
        monkeypatch, historical_stage_is_better, color_code, level_identifier):
    level, direct, _ = _baseline()
    neutral, right = InputFrame(), InputFrame(right=True)
    old = (neutral,) * 6 + direct          # Completes at frame 35.
    candidate = (neutral,) * 3 + direct    # Completes at frame 32.
    # Better at the stage checkpoint (frame 10), but a much later finish.
    # This is intentionally distinct from the saved completed-run baseline.
    stronger_stage = (right,) * 11 + (neutral,) * 22 + direct
    historical_stage = stronger_stage if historical_stage_is_better else old
    goal = EndpointGoal(10, 'max-x')
    evaluator = EndpointEvaluator(level, goal)
    assert evaluator.evaluate(candidate).objective_key < evaluator.evaluate(old).objective_key
    assert (evaluator.evaluate(historical_stage).objective_key <
            evaluator.evaluate(candidate).objective_key) == historical_stage_is_better

    monkeypatch.setattr(us, '_search_stage',
                        lambda *_args, **_kwargs: (((candidate, 10),), 1, 1))
    messages, completed_saves = [], []
    result = optimise_user_splices(
        level, old, [UserSpliceStage('end', goal, 0, 10)],
        RandomSpliceConfig(rounds=1, workers=1, iterations=2),
        single_input_seed=True, completion_policy='complete',
        saved_stage_candidates={'end': [historical_stage]},
        saved_final_frames=old,
        best_callback=completed_saves.append, progress=messages.append)
    assert result.improvements == 1
    assert len(completed_saves) == 1 and len(completed_saves[0]) == 32
    final_lines = [m for m in messages if 'improved verified final replay' in m]
    assert len(final_lines) == 1
    assert ('absolute stage best unchanged' in final_lines[0]) == historical_stage_is_better
    assert ('new absolute stage best' in final_lines[0]) != historical_stage_is_better
    assert '; saved' in final_lines[0]
    gains = [m for m in messages if m.startswith('[auto:hybrid:gain:')]
    assert len(gains) == 1
    assert gains[0].startswith('[auto:hybrid:gain:input]' if historical_stage_is_better
                               else '[auto:hybrid:gain:absolute]')

    sink = TTY()
    monkeypatch.setattr(sys, 'stdout', sink)
    _print_user_splice_progress(final_lines[0], color=True,
                                level_identifier=level_identifier)
    rendered = sink.getvalue()
    assert rendered.startswith(f'\x1b[{color_code}m')
    assert 'improved verified final replay' in rendered
    assert 'saved' in rendered
    if level_identifier is not None:
        expected_status = ('absolute stage best unchanged' if historical_stage_is_better
                           else 'new absolute stage best')
        assert f'\n  {expected_status}; saved' in rendered
    sink.seek(0)
    sink.truncate(0)
    _print_user_splice_progress(final_lines[0], color=False,
                                level_identifier=level_identifier)
    assert '\x1b[' not in sink.getvalue()
