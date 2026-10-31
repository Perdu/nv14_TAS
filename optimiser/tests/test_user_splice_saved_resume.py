"""Historical named-splice checkpoints are validated and never regressed."""
from __future__ import annotations

import pytest

from nv14_cli import _load_user_splice_checkpoints, _user_splice_alias_ltm_path
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_replay import encode_complex_replay
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def test_previous_text_replays_are_read_and_deduplicated(tmp_path):
    src = (InputFrame(left=True), InputFrame(right=True))
    main = tmp_path / 'optim_556.ltm'
    packed = tmp_path / '97-1_556.txt'
    packed.write_text(encode_complex_replay(src) + '\n')
    loaded = _load_user_splice_checkpoints({'556': (main, packed)},
                                            tmp_path / 'optim.ltm', tmp_path / '97-1.txt')
    assert len(loaded['556']) == 1
    assert loaded['556'][0] == tuple(src)
    assert _user_splice_alias_ltm_path(tmp_path/'optim.ltm', tmp_path/'97-1.txt', '556') == tmp_path/'97-1_556.ltm'


def test_unreadable_checkpoint_refuses_overwrite(tmp_path):
    path = tmp_path / 'optim_556.ltm'
    path.write_bytes(b'not an LTM')
    with pytest.raises(ValueError, match='refusing to overwrite'):
        _load_user_splice_checkpoints({'556': (path, None)},
                                      tmp_path/'optim.ltm', None)


def test_saved_better_stage_score_blocks_worse_replacement(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    one = (InputFrame(left=True),) + source[1:]
    two = (InputFrame(left=True), InputFrame(left=True)) + source[2:]
    stage = UserSpliceStage('556', EndpointGoal(10, 'min-x'), 0, 10)
    from nv14_endpoint import EndpointEvaluator
    e = EndpointEvaluator(level, stage.goal)
    ranked = sorted([source, one, two], key=lambda x: e.evaluate(x).objective_key)
    assert len({e.evaluate(x).objective_key for x in ranked}) == 3
    best, middle, worst = ranked
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs: (((middle, 10),), 1, 1))
    saves = []
    messages = []
    optimise_user_splices(level, worst, [stage],
                          RandomSpliceConfig(rounds=1, workers=1, iterations=2),
                          completion_policy='checkpoint',
                          saved_stage_candidates={'556': [best]},
                          stage_best_callback=lambda *args: saves.append(args),
                          progress=messages.append)
    assert not saves
    assert any('restored a strictly better historical checkpoint' in m for m in messages)


def test_better_than_saved_is_saved_once(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    one = (InputFrame(left=True),) + source[1:]
    two = (InputFrame(left=True), InputFrame(left=True)) + source[2:]
    stage = UserSpliceStage('556', EndpointGoal(10, 'min-x'), 0, 10)
    from nv14_endpoint import EndpointEvaluator
    e = EndpointEvaluator(level, stage.goal)
    best, middle, worst = sorted([source, one, two], key=lambda x: e.evaluate(x).objective_key)
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs: (((best, 10), (middle, 10)), 2, 1))
    saves = []
    optimise_user_splices(level, worst, [stage],
                          RandomSpliceConfig(rounds=1, workers=1, iterations=2),
                          completion_policy='checkpoint',
                          saved_stage_candidates={'556': [middle]},
                          stage_best_callback=lambda *args: saves.append(args))
    assert saves == [('556', best)]
