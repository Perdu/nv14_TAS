"""Named multi-splicer LTMs retain the original inputs after the stage goal."""
from __future__ import annotations

import sys

import pytest

from nv14_engine import InputFrame
from nv14_ltm import LtmMovie, LEVEL_DATABASE_NAME
from nv14_replay import editable_frames
from tests.test_ltm import _basic_config, _level_record, _write_ltm


@pytest.mark.parametrize('mode', ('multi', 'hybrid'))
def test_multi_stage_checkpoint_keeps_tail_after_early_completion(tmp_path, monkeypatch, mode):
    """A completed 29-frame source must not make the 10-frame stage erase its tail."""
    import nv14_user_splice as splice
    from nv14_cli import main

    # The level finishes at tick 29; the user's LTM intentionally has more
    # left/right controls after that point. A normal stage_export trims to 29.
    original = (InputFrame(right=True),) * 29 + (InputFrame(left=True),) * 20
    lines = ['|', '|K20|'] + [
        '|Kff53|' if frame.right else '|Kff51|' for frame in original
    ] + ['|Mpost:0|', '|Mpost:1|']
    src = _write_ltm(
        tmp_path / '00-0.ltm', ('\n'.join(lines) + '\n').encode(),
        config=_basic_config(frame_count=len(lines)))
    database = tmp_path / LEVEL_DATABASE_NAME
    database.write_text(_level_record() + '\n')
    goals = tmp_path / 'goals'
    goals.mkdir()
    (goals / '352.txt').write_text(
        '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    cfg = tmp_path / 'config.toml'
    cfg.write_text('[auto]\nsplice-files=["352"]\nsplice-iterations=1\n'
                   'splice-rounds=1\nruns=1\n')
    # Avoid performing an unnecessary stochastic search; checkpoint creation
    # during initialisation is the operation that reproduced the loss.
    monkeypatch.setattr(splice, '_search_stage', lambda *a, **kw: ((), 0, 0))
    args = (['auto', str(src), '--config', str(cfg),
             '--auto-splice-directory', str(goals)]
            if mode == 'multi' else
            ['hybrid', str(src), '--goal-config', str(goals / '352.txt'),
             '--auto-runs', '1'])
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', *args, '--levels-file', str(database),
        '--output', str(tmp_path / 'out.ltm'), '--workers', '1',
    ])
    main()
    stage_movie = LtmMovie.load(tmp_path / 'out_352.ltm')
    actual = tuple(editable_frames(stage_movie.replay_frames))
    expected = tuple(editable_frames(original))
    assert len(actual) == len(expected)
    assert actual[11:] == expected[11:]
    assert all(frame.left for frame in actual[29:])


def test_stage_checkpoint_preserves_non_n_tail_data_too(tmp_path):
    """The LTM writer also keeps unrelated libTAS events at their same ticks."""
    from nv14_ltm import LtmMovie
    from nv14_engine import InputFrame
    from tests.test_ltm import _basic_config, _write_ltm
    lines = ['|', '|K20|'] + ['|Kff53|' for _ in range(29)] + [
        '|Kff51|Mtracker:0|', '|Kff51|C1:2|']
    source = _write_ltm(tmp_path / '00-0.ltm',
        ('\n'.join(lines) + '\n').encode(), config=_basic_config(frame_count=len(lines)))
    movie = LtmMovie.load(source)
    restored = (InputFrame(right=True),) * 29 + (InputFrame(left=True),) * 2
    out = tmp_path / 'stage.ltm'
    movie.write(out, restored, level_id='00-0', level_record=_level_record())
    reread = LtmMovie.load(out)
    assert tuple(editable_frames(reread.replay_frames)) == tuple(editable_frames(restored))
    assert 'Mtracker:0' in reread.input_lines[31]
    assert 'C1:2' in reread.input_lines[32]


def test_multisplice_live_gain_restores_tail_after_early_arrival(tmp_path, monkeypatch):
    """Backend edits after an earlier qualifying arrival never leak to stage LTMs."""
    import nv14_user_splice as splice
    from nv14_cli import main
    from nv14_endpoint import EndpointEvaluator, EndpointGoal
    from nv14_replay import (
        encode_complex_replay, parse_combined_level_replay, decode_complex_replay)
    from tests.test_random_splice import _baseline

    level, _, _ = _baseline()
    original = (InputFrame(),) * 5 + (InputFrame(right=True),) * 47
    faster = (InputFrame(right=True),) * 52
    goal = EndpointGoal(18, 'earliest-arrival',
                        target_region=(66, 250, 120, 145))
    arrival = EndpointEvaluator(level, goal).evaluate(faster)
    baseline = EndpointEvaluator(level, goal).evaluate(original)
    assert arrival.feasible and baseline.feasible and arrival.frame < baseline.frame
    tampered = (faster[:arrival.frame + 1] +
                (InputFrame(left=True),) * (len(faster) - arrival.frame - 1))
    src = tmp_path / 'source.txt'
    src.write_text(f'$test#author#{level.source_level_string}#'
                   f'{encode_complex_replay(original)}#\n')
    goals = tmp_path / 'goals'
    goals.mkdir()
    (goals / '352.txt').write_text(
        '[local]\nsearch="population"\nobjective="earliest-arrival"\n'
        'target-frame=18\nrange="0:18"\n'
        'target-region="66:250,120:145"\n')
    cfg = tmp_path / 'cfg.toml'
    cfg.write_text('[auto]\nsplice-files=["352"]\nsplice-iterations=1\n'
                   'splice-rounds=1\nruns=1\n')

    def fake_search(_level, _branch, _stage, _config, _rng, **kw):
        kw['candidate_callback'](tampered, arrival.frame)
        return (), 1, 1

    monkeypatch.setattr(splice, '_search_stage', fake_search)
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(src), '--config', str(cfg),
        '--auto-splice-directory', str(goals),
        '--output', str(tmp_path / 'result.txt'), '--workers', '1'])
    main()
    text = (tmp_path / 'result_352.txt').read_text()
    combined = parse_combined_level_replay(text)
    saved = tuple(editable_frames(decode_complex_replay(combined.replay_string).frames))
    assert len(saved) == len(original)
    assert saved[:arrival.frame + 1] == tampered[:arrival.frame + 1]
    assert saved[arrival.frame + 1:] == original[arrival.frame + 1:]
