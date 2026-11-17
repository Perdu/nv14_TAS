"""Patch 132: fastest archived sections are real, correctly aligned search seeds."""
from __future__ import annotations

from dataclasses import replace

import nv14_user_splice as us
from nv14_engine import InputFrame
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, _replace_section_inputs, optimise_user_splices
from tests.test_random_splice import _baseline


def test_section_transplant_uses_reached_frames_and_shifts_remaining_inputs():
    base = tuple(InputFrame(right=True) for _ in range(30))
    archive = tuple(InputFrame(left=True) if i in range(12, 17)
                    else InputFrame(jump=True) for i in range(30))
    # The named goal deadlines are 10 and 25, but on these two replay
    # histories the zero-based arrival ticks are 5/20 and 6/13 respectively.
    joined = _replace_section_inputs(base, archive, 5, 20, 6, 13)
    assert joined[:6] == base[:6]  # Tick 5 reached the previous goal
    assert joined[6:13] == archive[7:14]  # AFTER previous goal, THROUGH next
    assert joined[13:] == base[21:]
    assert len(joined) == len(base) - (20 - 5) + (13 - 6)
    assert joined[11] == archive[12]  # Archived input's correct relative tick
    assert joined[13] == base[21]  # Base suffix resumes immediately afterward


def _setup(monkeypatch, *, graft_feasible=True, archive_end=13):
    level, source, _ = _baseline()
    archive = source[:12] + (InputFrame(left=True),) + source[13:]
    stitched = _replace_section_inputs(source, archive, 5, 20, 6, 13)
    original = EndpointEvaluator.evaluate

    def observed(self, frames):
        frames = tuple(frames)
        result = original(self, frames)
        if self.goal.target_frame == 10:
            t = 6 if frames[:len(archive)] == archive else 5
        else:
            if frames[:len(archive)] == archive:
                t = archive_end
            elif frames[:len(stitched)] == stitched:
                t = 12
            else:
                t = 20
        feasible = not (not graft_feasible and
                        self.goal.target_frame == 25 and
                        frames[:len(stitched)] == stitched)
        return replace(result, feasible=feasible, frame=t, score=-float(t),
                       secondary_score=0.0)

    monkeypatch.setattr(EndpointEvaluator, 'evaluate', observed)
    stages = (
        UserSpliceStage('388', EndpointGoal(10, 'earliest-arrival',
                                         target_region=(-1000, 1000, -1000, 1000)), 0, 10),
        UserSpliceStage('462', EndpointGoal(25, 'earliest-arrival',
                                         target_region=(-1000, 1000, -1000, 1000)), 10, 25),
    )
    return level, source, archive, stitched, stages


def test_multi_adds_transplanted_fastest_section_seed(monkeypatch):
    level, source, archive, stitched, stages = _setup(monkeypatch)
    searched = []
    messages = []

    def fake_search(_level, frames, stage, *_args, **_kwargs):
        searched.append((stage.name, tuple(frames)))
        return (), 0, 1

    monkeypatch.setattr(us, '_search_stage', fake_search)
    optimise_user_splices(
        level, source, stages, RandomSpliceConfig(rounds=1, iterations=2),
        completion_policy='checkpoint',
        saved_stage_frontiers={'462': [archive]}, progress=messages.append)
    searched_462 = [frames for name, frames in searched if name == '462']
    assert source in searched_462
    # The stage backend sees a fully materialised input run, with the real
    # source prefix, archived physical section and shifted suffix.
    assert any(frames[:len(stitched)] == stitched for frames in searched_462)
    assert any('transplanted inputs 7:14 -> 6:13' in m for m in messages)
    assert any('fastest archived section' in m and 'seed 2/2' in m
               for m in messages)


def test_unverified_transplant_falls_back_to_intact_archived_replay(monkeypatch):
    level, source, archive, stitched, stages = _setup(monkeypatch, graft_feasible=False)
    calls = []
    messages = []
    monkeypatch.setattr(us, '_search_stage', lambda _level, frames, stage, *_a, **_kw:
                        (calls.append((stage.name, tuple(frames))) or (), 0, 1))
    optimise_user_splices(
        level, source, stages, RandomSpliceConfig(rounds=1, iterations=2),
        completion_policy='checkpoint',
        saved_stage_frontiers={'462': [archive]}, progress=messages.append)
    searched = [frames for name, frames in calls if name == '462']
    assert archive in searched
    assert not any(frames[:len(stitched)] == stitched for frames in searched)
    assert any('intact archived replay (no verified transplant)' in m
               for m in messages)


def test_standalone_single_input_hybrid_does_not_add_archive_seed(monkeypatch):
    level, source, archive, _stitched, stages = _setup(monkeypatch)
    calls = []
    monkeypatch.setattr(us, '_search_stage', lambda _level, frames, stage, *_a, **_kw:
                        (calls.append(tuple(frames)) or (), 0, 1))
    optimise_user_splices(
        level, source, [stages[1]], RandomSpliceConfig(rounds=1, iterations=2),
        completion_policy='checkpoint', single_input_seed=True,
        saved_stage_frontiers={'462': [archive]})
    assert calls == [source]


def test_native_replay_transplant_keeps_earlier_arrival_and_fast_section():
    """Real physics agrees with zero-based endpoint arrival tick slicing."""
    level, _completed, _ = _baseline()
    fast = (InputFrame(right=True),) * 52
    slow = ((InputFrame(right=True),) * 11 + (InputFrame(),) * 6 +
            (InputFrame(right=True),) * 35)
    previous = EndpointEvaluator(level, EndpointGoal(
        10, 'earliest-arrival', target_region=(66, 250, 120, 145)))
    current = EndpointEvaluator(level, EndpointGoal(
        35, 'earliest-arrival', target_region=(95, 250, 120, 145)))
    bp, bc = previous.evaluate(slow), current.evaluate(slow)
    ap, ac = previous.evaluate(fast), current.evaluate(fast)
    assert bp.feasible and bc.feasible and ap.feasible and ac.feasible
    assert bp.frame == ap.frame == 9
    assert bc.frame == 28 and ac.frame == 22
    joined = _replace_section_inputs(slow, fast, bp.frame, bc.frame,
                                     ap.frame, ac.frame)
    jp, jc = previous.evaluate(joined), current.evaluate(joined)
    assert jp.feasible and jp.frame == bp.frame
    assert jc.feasible and jc.frame == ac.frame  # Actual 6-frame gain
    assert joined[:10] == slow[:10]
    assert joined[10:23] == fast[10:23]
    assert joined[23:] == slow[29:]


def test_zero_duration_archive_is_a_seed_without_an_empty_transplant(monkeypatch):
    level, source, archive, _stitched, stages = _setup(monkeypatch, archive_end=6)
    searched = []
    messages = []
    monkeypatch.setattr(us, '_search_stage', lambda _level, frames, stage, *_a, **_kw:
                        (searched.append((stage.name, tuple(frames))) or (), 0, 1))
    optimise_user_splices(
        level, source, stages, RandomSpliceConfig(rounds=1, iterations=2),
        completion_policy='checkpoint',
        saved_stage_frontiers={'462': [archive]}, progress=messages.append)
    assert ('462', archive) in searched
    assert any('zero-length section' in m for m in messages)
