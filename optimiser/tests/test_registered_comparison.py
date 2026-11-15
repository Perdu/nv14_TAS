"""Registered snapshots are stable comparison baselines, never search seeds."""
import sys
from pathlib import Path

import pytest

from nv14_cli import main, parse_arguments, _format_user_splice_report
from nv14_engine import InputFrame
from nv14_ltm import LtmMovie, LEVEL_DATABASE_NAME
from nv14_random_splice import RandomSpliceConfig
from nv14_registered_baseline import registered_path, load_registered_run, write_registered_run
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from nv14_endpoint import EndpointGoal
from tests.test_ltm import _write_ltm, _basic_config, _level_record
from tests.test_random_splice import _baseline


def test_registered_snapshot_roundtrip_and_rejects_wrong_level(tmp_path):
    path = tmp_path / 'test.registered.json'
    frames = (InputFrame(right=True), InputFrame(jump=True))
    write_registered_run(path, level_id='01-0', level_string='test-level',
                         branch=9, frames=frames)
    assert load_registered_run(path, level_id='01-0', level_string='test-level') == frames
    assert 'inputs9' in path.read_text()
    with pytest.raises(ValueError, match='different level'):
        load_registered_run(path, level_id='01-0', level_string='other-level')
    assert not load_registered_run(tmp_path / 'missing.json', level_id='01-0', level_string='test-level')


def test_register_inputs9_from_actual_ltm_does_not_touch_movies(tmp_path, monkeypatch, capsys):
    primary = b'|K20|\n|Kff51|\n|Kff51|\n|Kff51|\n|\n'
    alternate = b'|K20|\n|Kff53|\n|Kff53|\n|Kff53|\n|\n'
    input_path = _write_ltm(tmp_path / '00-0.ltm', primary, config=_basic_config(frame_count=5),
                            extra_members=(('inputs9', alternate),))
    (tmp_path / LEVEL_DATABASE_NAME).write_text(_level_record()+'\n')
    output_path = tmp_path / 'best.ltm'
    before = input_path.read_bytes()
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(input_path), '--register', '9',
        '--levels-file', str(tmp_path / LEVEL_DATABASE_NAME),
        '--output', str(output_path)])
    main()
    assert input_path.read_bytes() == before
    assert not output_path.exists()
    registered = registered_path(output_path)
    assert registered.exists()
    from nv14_cli import _load_source
    source = _load_source(input_path, levels_file_path=tmp_path / LEVEL_DATABASE_NAME,
                          explicit_level_id=None, ltm_postroll=None)
    loaded = load_registered_run(registered, level_id=source.level_id,
                                 level_string=source.combined.level_string)
    assert [(f.left, f.right, f.jump) for f in loaded] == [
        (f.left, f.right, f.jump) for f in LtmMovie.load(input_path, branch=9).replay_frames]
    assert 'inputs9' in capsys.readouterr().out
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(input_path), '--register', 'inputs',
        '--levels-file', str(tmp_path / LEVEL_DATABASE_NAME),
        '--output', str(output_path)])
    main()
    assert [(f.left, f.right, f.jump) for f in load_registered_run(
        registered, level_id=source.level_id,
        level_string=source.combined.level_string)] == [
        (f.left, f.right, f.jump) for f in LtmMovie.load(input_path).replay_frames]
    assert not output_path.exists()
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(input_path), '--register', '12',
        '--levels-file', str(tmp_path / LEVEL_DATABASE_NAME),
        '--output', str(output_path)])
    with pytest.raises(SystemExit, match='inputs12'):
        main()
    assert registered.exists()  # missing branch does not corrupt prior registration


def test_registered_comparison_is_reported_without_altering_summary_search(monkeypatch):
    level, source, _ = _baseline()
    other = (InputFrame(left=True),) + source[1:]
    goal = EndpointGoal(10, 'min-x')
    stage = UserSpliceStage('230', goal, 0, 10)
    import nv14_user_splice as us
    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw: pytest.fail('ran search'))
    lines = []
    optimise_user_splices(level, source, [stage],
                          RandomSpliceConfig(rounds=1, iterations=4, workers=1),
                          summary_only=True, completion_policy='checkpoint',
                          registered_comparison_frames=source,
                          saved_stage_candidates={'230': [other]}, progress=lines.append)
    msg = '\n'.join(lines)
    assert 'vs registered run:' in msg
    formatted = _format_user_splice_report(next(line for line in lines if ':summary:pending]' in line),
                                          level_identifier='01-0')
    assert '\n  vs registered run:' in formatted
    assert 'vs best run:' in formatted


def test_register_cli_only_parses_as_auto():
    assert parse_arguments(['auto','input.ltm','--register','9']).register == '9'
    assert parse_arguments(['auto','input.ltm','--register','inputs']).register == 'inputs'
