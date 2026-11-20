"""Patch 140: one bounded and verified realignment at the next splice boundary."""
from dataclasses import replace

import nv14_user_splice as us
from nv14_engine import InputFrame
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import (_realign_next_section_seed, UserSpliceStage,
                              optimise_user_splices)
from tests.test_random_splice import _baseline


def test_realign_uses_actual_checkpoint_frames_and_only_next_section():
    level, _, _ = _baseline()
    fast = (InputFrame(right=True),) * 52
    slow = (InputFrame(),) * 5 + (InputFrame(right=True),) * 47
    prior = EndpointEvaluator(level, EndpointGoal(
        18, 'earliest-arrival', target_region=(66, 250, 120, 145)))
    next_goal = EndpointEvaluator(level, EndpointGoal(
        45, 'earliest-arrival', target_region=(95, 250, 120, 145)))
    fast_reached, old_reached = prior.evaluate(fast), prior.evaluate(slow)
    next_reached = next_goal.evaluate(slow)
    assert fast_reached.feasible and old_reached.feasible and next_reached.feasible
    assert old_reached.frame > fast_reached.frame
    assert next_reached.frame < next_goal.goal.target_frame
    result = _realign_next_section_seed(
        fast, slow, improved_arrival=fast_reached.frame,
        reference_arrival=old_reached.frame,
        next_target=next_goal.goal.target_frame, next_start=fast_reached.frame + 1,
        source_endpoint=prior, next_endpoint=next_goal, next_level=level)
    assert result is not None
    offset, proposed = result
    assert offset == 0
    assert proposed[:fast_reached.frame + 1] == fast[:fast_reached.frame + 1]
    copied = slow[old_reached.frame + 1:next_reached.frame + 1]
    assert proposed[fast_reached.frame + 1:fast_reached.frame + 1 + len(copied)] == copied
    assert all(x == InputFrame() for x in proposed[fast_reached.frame + 1 + len(copied):])
    assert len(proposed) == next_goal.goal.target_frame + 1
    assert prior.evaluate(proposed).feasible
    assert prior.evaluate(proposed).frame == fast_reached.frame


def _run_two_stages(monkeypatch, *, gain=True, single=False):
    level, original, _ = _baseline()
    changed = list(original)
    changed[4] = InputFrame(left=True)
    faster = tuple(changed)
    original_evaluate = EndpointEvaluator.evaluate

    def score(self, frames):
        result = original_evaluate(self, frames)
        if self.goal.target_frame == 15:
            is_faster = len(frames) > 4 and frames[4].left
            frame = (10 if is_faster and gain else 11)
        else:
            frame = 22
        return replace(result, feasible=True, score=-float(frame), frame=frame,
                       secondary_score=0.0)

    monkeypatch.setattr(EndpointEvaluator, 'evaluate', score)
    stages = (
        UserSpliceStage('A', EndpointGoal(15, 'earliest-arrival',
                        target_region=(-1000, 1000, -1000, 1000)), 0, 15),
        UserSpliceStage('B', EndpointGoal(25, 'earliest-arrival',
                        target_region=(-1000, 1000, -1000, 1000)), 11, 25),
    )
    searched = []
    messages = []

    def search(_level, frames, stage, *_args, **_kwargs):
        searched.append((stage.name, tuple(frames)))
        return (((faster, 15),) if stage.name == 'A' else ()), 0, 1

    monkeypatch.setattr(us, '_search_stage', search)
    optimise_user_splices(
        level, original, stages, RandomSpliceConfig(rounds=1, iterations=2),
        completion_policy='checkpoint', progress=messages.append,
        single_input_seed=single)
    return original, faster, searched, messages


def test_one_frame_new_stage_best_generates_next_stage_seed(monkeypatch):
    source, improved, searched, messages = _run_two_stages(monkeypatch)
    candidates = [replay for name, replay in searched if name == 'B']
    assert source in candidates
    # 10 is the gained arrival, 11 is the old arrival, and 22 is the old
    # next-goal arrival. The replacement begins AFTER the gained tick.
    expected = improved[:11] + source[12:23] + (InputFrame(),) * 4
    assert expected in candidates
    assert any('[auto:user-splice:realign] realigned A -> B (1f lead, offset +0)' in m
               for m in messages)
    assert any('seed ' in m and '[realigned A -> B (1f lead, offset +0)]' in m
               for m in messages)
    assert all(name != 'C' for name, _ in searched)


def test_no_realign_for_tied_arrival_or_single_input_mode(monkeypatch):
    _, _, searched, messages = _run_two_stages(monkeypatch, gain=False)
    assert not any('realign' in m for m in messages)
    # Ordinary frontier seeds are still present; only the extra realignment
    # seed is absent.
    assert len([name for name, _ in searched if name == 'B']) == 2


def test_no_realign_if_next_section_not_available(monkeypatch):
    level, _, _ = _baseline()
    prior = EndpointEvaluator(level, EndpointGoal(
        18, 'earliest-arrival', target_region=(66, 250, 120, 145)))
    next_goal = EndpointEvaluator(level, EndpointGoal(
        20, 'earliest-arrival', target_region=(95, 250, 120, 145)))
    fast = (InputFrame(right=True),) * 30
    old = (InputFrame(),) * 5 + fast
    assert _realign_next_section_seed(
        fast, old, improved_arrival=9, reference_arrival=14,
        next_target=14, next_start=10, source_endpoint=prior,
        next_endpoint=next_goal, next_level=level) is None


def test_dead_immutable_next_prefix_is_not_offered(monkeypatch):
    import nv14_replay

    level, _, _ = _baseline()
    fast = (InputFrame(right=True),) * 52
    old = (InputFrame(),) * 5 + (InputFrame(right=True),) * 47
    prior = EndpointEvaluator(level, EndpointGoal(
        18, 'earliest-arrival', target_region=(66, 250, 120, 145)))
    next_goal = EndpointEvaluator(level, EndpointGoal(
        45, 'earliest-arrival', target_region=(95, 250, 120, 145)))

    class DeadState:
        class player:
            dead = True
        level_complete = False

    monkeypatch.setattr(nv14_replay, 'simulate_through_frame',
                        lambda *_args, **_kwargs: DeadState())
    assert _realign_next_section_seed(
        fast, old, improved_arrival=9, reference_arrival=14,
        next_target=45, next_start=18, source_endpoint=prior,
        next_endpoint=next_goal, next_level=level) is None
