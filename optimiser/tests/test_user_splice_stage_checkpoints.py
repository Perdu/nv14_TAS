"""Named multi-splicer checkpoints are playable, separate and stage-scored."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import nv14_user_splice as us
from nv14_cli import (_user_splice_output_paths, main)
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_random_splice import RandomSpliceConfig
from nv14_replay import decode_complex_replay, encode_complex_replay, parse_combined_level_replay
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def test_path_names_and_collision_protection(tmp_path):
    out = tmp_path / 'wip' / 'optim.ltm'
    packed = tmp_path / 'wip' / '97-2.txt'
    destinations = _user_splice_output_paths(['230', 'switch.txt', 'end.toml'], out, packed)
    assert destinations['230'] == (tmp_path/'wip'/'optim_230.ltm',
                                   tmp_path/'wip'/'97-2_230.txt')
    assert destinations['switch.txt'][0].name == 'optim_switch.ltm'
    assert destinations['end.toml'][1].name == '97-2_end.txt'
    fallback = _user_splice_output_paths(['230'], out, None)
    assert fallback['230'] == (tmp_path/'wip'/'optim_230.ltm', tmp_path/'wip'/'optim_230.txt')
    with pytest.raises(ValueError, match='different files'):
        _user_splice_output_paths(['230', '230.txt'], out, packed)
    with pytest.raises(ValueError, match='different files'):
        _user_splice_output_paths(['230'], out, packed,
                                  protected_paths=[('input', out.with_name('optim_230.ltm'))])


def test_stage_best_checkpoint_only_strict_updates(monkeypatch):
    level, source, _ = _baseline()
    alternative = (InputFrame(left=True),) + source[1:]
    stage = UserSpliceStage('230', EndpointGoal(10, 'min-x'), 0, 10)
    old = EndpointEvaluator(level, stage.goal).evaluate(source).objective_key
    new = EndpointEvaluator(level, stage.goal).evaluate(alternative).objective_key
    assert new < old

    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw:
                        (((alternative, 10), (source, 10)), 2, 1))
    stage_saves = []
    finals = []
    optimise_user_splices(level, source, [stage],
                          RandomSpliceConfig(rounds=2, workers=1, iterations=2),
                          completion_policy='complete',
                          best_callback=finals.append,
                          stage_best_callback=lambda name, frames:
                          stage_saves.append((name, frames)))
    assert stage_saves == [('230', alternative)], 'save only strict stage improvements'
    assert not finals, 'a stage-only gain may not overwrite the final completed replay'


def test_cli_writes_named_stage_replays_beside_main_outputs(tmp_path, monkeypatch):
    level, source, _ = _baseline()
    source_file = tmp_path / 'source.txt'
    source_file.write_text(f'$test#author#{level.source_level_string}#'
                           f'{encode_complex_replay(source)}#\n')
    goals = tmp_path / 'goals'; goals.mkdir()
    for name, frame in (('230', 10), ('end', 15)):
        (goals / f'{name}.txt').write_text(
            f'[local]\nobjective="min-x"\ntarget-frame={frame}\nrange="0:{frame}"\n')
    config = tmp_path / 'config.toml'
    config.write_text('[auto]\nsplice-files=["230", "end"]\n'
                      'splice-search="both"\nsplice-iterations=8\n'
                      'splice-rounds=1\nruns=1\nbeam=8\nseed=0\n')
    output = tmp_path/'optim.txt'
    replay = tmp_path/'97-2.txt'
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(source_file),
        '--config', str(config), '--auto-splice-directory', str(goals),
        '--output', str(output), '--replay-output', str(replay), '--workers', '1'])
    import nv14_user_splice as us
    candidate = (InputFrame(left=True),) + source[1:]
    monkeypatch.setattr(us, '_search_stage', lambda lvl, branch, stage, config, rng:
                        (((candidate, stage.goal.target_frame),), 1, 1))
    main()
    for name in ('230', 'end'):
        stage_main = tmp_path / f'optim_{name}.txt'
        stage_replay = tmp_path / f'97-2_{name}.txt'
        assert stage_main.exists() and stage_replay.exists()
        decoded = decode_complex_replay(stage_replay.read_text().strip()).frames
        saved = parse_combined_level_replay(stage_main.read_text()).replay_string
        assert list(decoded) == decode_complex_replay(saved).frames
    # There may be no full-run improvement, so the main file isn't required.


@pytest.mark.parametrize('explicit_replay', [True, False])
def test_cli_stage_outputs_are_loadable_ltm_movies(tmp_path, monkeypatch, explicit_replay):
    from nv14_ltm import LtmMovie, LEVEL_DATABASE_NAME
    from tests.test_ltm import _write_ltm, _basic_config, _level_record

    body = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    input_lines = ['|Mboot:0|', '|K20|Mboot:1|']
    input_lines.extend('|Kff53|' if frame.right else '|' for frame in body)
    input_lines.extend(('|K61|Mpost:0|', '|Mpost:1|', '|Mpost:2|'))
    source_ltm = _write_ltm(tmp_path/'00-0.ltm',
                            ('\n'.join(input_lines) + '\n').encode(),
                            config=_basic_config(frame_count=len(input_lines)))
    database = tmp_path/LEVEL_DATABASE_NAME
    database.write_text(_level_record() + '\n')
    goals = tmp_path/'goals'; goals.mkdir()
    (goals/'230.txt').write_text('[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    (goals/'end.txt').write_text('[local]\nobjective="min-x"\ntarget-frame=36\nrange="0:36"\n')
    cfg = tmp_path/'multi.toml'
    cfg.write_text('[auto]\nsplice-files=["230","end"]\n'
                   'splice-iterations=4\nsplice-rounds=1\nruns=1\nbeam=4\nseed=0\n')
    destination = tmp_path/'optim.ltm'
    packed = tmp_path/'00-0.txt'
    cli_args = [
        'optimize_replay.py', 'auto', str(source_ltm), '--config', str(cfg),
        '--levels-file', str(database), '--auto-splice-directory', str(goals),
        '--output', str(destination), '--workers', '1']
    if explicit_replay:
        cli_args.extend(('--replay-output', str(packed)))
    monkeypatch.setattr(sys, 'argv', cli_args)
    main()
    stage_ltm = tmp_path/'optim_230.ltm'
    stage_txt = tmp_path/('00-0_230.txt' if explicit_replay else 'optim_230.txt')
    alias_ltm = tmp_path/'00-0_230.ltm' if explicit_replay else None
    assert stage_ltm.exists() and stage_txt.exists()
    if alias_ltm is not None:
        assert alias_ltm.exists()
        assert alias_ltm.read_bytes() == stage_ltm.read_bytes()
    loaded = LtmMovie.load(stage_ltm)
    packed_frames = decode_complex_replay(stage_txt.read_text().strip()).frames
    assert tuple(loaded.replay_frames) == tuple(packed_frames)
