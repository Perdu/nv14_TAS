"""Resume propagation from a validated saved splice-best replay."""
from __future__ import annotations

import sys

import pytest

import nv14_user_splice as us
from nv14_cli import main, parse_arguments
from nv14_endpoint import EndpointGoal
from nv14_engine import InputFrame
from nv14_random_splice import RandomSpliceConfig
from nv14_replay import encode_complex_replay
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


def _stages():
    return [UserSpliceStage(name, EndpointGoal(10, 'min-x'), 0, 10)
            for name in ('230', '408', 'end')]


def test_saved_best_seeds_next_stage_and_every_outer_round(monkeypatch):
    level, source, _ = _baseline()
    saved = (InputFrame(left=True),) + source[1:]
    calls = []

    def search(_level, frames, stage, *_args, **_kwargs):
        calls.append((stage.name, tuple(frames)))
        return ((), 1, 1)

    monkeypatch.setattr(us, '_search_stage', search)
    messages = []
    result = optimise_user_splices(
        level, source, _stages(), RandomSpliceConfig(rounds=2, workers=1, iterations=2),
        completion_policy='checkpoint', from_best='230',
        saved_stage_candidates={'230': [saved]}, progress=messages.append)
    assert [stage for stage, _ in calls] == ['408', 'end', '408', 'end']
    assert calls[0][1] == saved and calls[2][1] == saved
    assert result.frames == source  # The saved partial replay is not a verified full-run best.
    assert any("starting at stage '408' from saved" in m for m in messages)


def test_explicit_start_can_retry_source_stage(monkeypatch):
    level, source, _ = _baseline()
    saved = (InputFrame(left=True),) + source[1:]
    calls = []
    monkeypatch.setattr(us, '_search_stage', lambda level, branch, stage, *a, **kw:
                        (calls.append((stage.name, branch)) or (), 0, 1))
    optimise_user_splices(level, source, _stages(),
                          RandomSpliceConfig(rounds=1, workers=1, iterations=2),
                          completion_policy='checkpoint', from_best='230',
                          start_at='230', stop_at='408',
                          saved_stage_candidates={'230': [saved]})
    assert [name for name, _ in calls] == ['230', '408']
    assert calls[0][1] == saved


def test_missing_or_ineligible_saved_best_fails(monkeypatch):
    level, source, _ = _baseline()
    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw: ((), 0, 1))
    with pytest.raises(ValueError, match='no valid saved checkpoint'):
        optimise_user_splices(level, source, _stages(),
                              RandomSpliceConfig(rounds=1, workers=1, iterations=2),
                              completion_policy='checkpoint', from_best='230')
    with pytest.raises(ValueError, match='no later stage to propagate'):
        optimise_user_splices(level, source, _stages(),
                              RandomSpliceConfig(rounds=1, workers=1, iterations=2),
                              completion_policy='checkpoint', from_best='end')
    with pytest.raises(ValueError, match='not a unique name'):
        optimise_user_splices(level, source, _stages(),
                              RandomSpliceConfig(rounds=1, workers=1, iterations=2),
                              completion_policy='checkpoint', from_best='absent')


def test_cli_parses_new_named_splice_flag():
    args = parse_arguments(['auto', 'level.ltm', '--auto-random-splice',
                            '--auto-splice-mode', 'user',
                            '--auto-splice-files', '230,408,end',
                            '--splice-from-best', '230'])
    assert args.auto_splice_from_best == '230'


def test_cli_reads_saved_text_checkpoint_and_passes_selected_seed(tmp_path, monkeypatch):
    level, source, _ = _baseline()
    saved = (InputFrame(left=True),) + source[1:]
    source_file = tmp_path / 'source.txt'
    source_file.write_text(f'$test#author#{level.source_level_string}#'
                           f'{encode_complex_replay(source)}#\n')
    goal_dir = tmp_path / 'goals'
    goal_dir.mkdir()
    for name in ('230', '408', 'end'):
        (goal_dir / f'{name}.txt').write_text(
            '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    cfg = tmp_path / 'config.toml'
    cfg.write_text('[auto]\nsplice-files=["230","408","end"]\n'
                   'splice-search="local"\nsplice-iterations=4\n'
                   'splice-rounds=1\nruns=1\nbeam=4\nseed=0\n')
    # Checkpoint naming follows --replay-output. It is intentionally a partial
    # source candidate, not a replacement for the verified final output.
    (tmp_path / '97-1_230.txt').write_text(encode_complex_replay(saved) + '\n')
    calls = []
    monkeypatch.setattr(us, '_search_stage', lambda _level, frames, stage, *a, **kw:
                        (calls.append((stage.name, tuple(frames))) or (), 0, 1))
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(source_file),
        '--config', str(cfg), '--auto-splice-directory', str(goal_dir),
        '--output', str(tmp_path/'optim.txt'),
        '--replay-output', str(tmp_path/'97-1.txt'),
        '--splice-from-best', '230', '--workers', '1'])
    main()
    assert [name for name, _ in calls] == ['408', 'end']
    assert calls[0][1] == saved
