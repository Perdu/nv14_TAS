"""Standalone Hybrid saves its live session leader without regressing saved bests."""
from __future__ import annotations

import sys

import pytest

from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_engine import InputFrame
from nv14_replay import decode_complex_replay, encode_complex_replay, editable_frames, parse_combined_level_replay
from tests.test_random_splice import _baseline


def _replays():
    level, source, _ = _baseline()
    a = (InputFrame(left=True),) + source[1:]
    b = (InputFrame(left=True), InputFrame(left=True)) + source[2:]
    evaluator = EndpointEvaluator(level, EndpointGoal(10, 'min-x'))
    sorted_replays = sorted((source, a, b), key=lambda r: evaluator.evaluate(r).objective_key)
    assert len({evaluator.evaluate(r).objective_key for r in sorted_replays}) == 3
    return level, sorted_replays


def test_saved_checkpoint_is_preserved_and_session_best_is_live(tmp_path, monkeypatch):
    """Even a yellow gain must be on disk before the backend returns."""
    from nv14_cli import main
    import nv14_user_splice as us

    level, (best, middle, worst) = _replays()
    source = tmp_path / 'input.txt'
    source.write_text(f'$test#author#{level.source_level_string}#'
                      f'{encode_complex_replay(worst)}#\n')
    goal = tmp_path / '631.txt'
    goal.write_text('[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    dest = tmp_path / 'output.txt'
    stage = tmp_path / 'output_631.txt'
    stage.write_text(f'$test#author#{level.source_level_string}#'
                     f'{encode_complex_replay(best)}#\n')
    original_stage = stage.read_bytes()
    session = tmp_path / 'output_631.session.txt'
    session.write_text('stale prior session')
    recorded = []

    def search(_lvl, _branch, _stage, config, _rng, **kwargs):
        assert config.live_save_best  # no 30-second live candidate throttle
        assert not session.exists()  # prior session must not masquerade as new
        kwargs['candidate_callback'](middle, 10)
        assert session.is_file(), 'the best candidate is written during search'
        assert editable_frames(decode_complex_replay(
            parse_combined_level_replay(session.read_text()).replay_string
        ).frames) == list(middle)
        assert stage.read_bytes() == original_stage
        assert not dest.exists()  # stage-only result is not a completed best
        recorded.append(True)
        return (), 1, 1

    monkeypatch.setattr(us, '_search_stage', search)
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'hybrid', str(source), '--goal-config', str(goal),
        '--output', str(dest), '--workers', '15', '--auto-runs', '1',
        '--no-propagation'])
    main()
    assert recorded
    assert stage.read_bytes() == original_stage


def test_standalone_hybrid_live_ltm_survives_interrupt(tmp_path, monkeypatch):
    from nv14_cli import main
    from nv14_ltm import LtmMovie, LEVEL_DATABASE_NAME
    from tests.test_ltm import _write_ltm, _basic_config, _level_record
    import nv14_user_splice as us

    body = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    lines = ['|Mboot:0|', '|K20|Mboot:1|']
    lines.extend('|Kff53|' if frame.right else '|' for frame in body)
    lines.extend(('|K61|Mpost:0|', '|Mpost:1|', '|Mpost:2|'))
    ltm = _write_ltm(tmp_path / '00-0.ltm',
                     ('\n'.join(lines) + '\n').encode(),
                     config=_basic_config(frame_count=len(lines)))
    database = tmp_path / LEVEL_DATABASE_NAME
    database.write_text(_level_record() + '\n')
    goal = tmp_path / '631.txt'
    goal.write_text('[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    session_movie = tmp_path / 'out_631.session.ltm'
    session_txt = tmp_path / 'out_631.session.txt'
    output = tmp_path / 'out.ltm'
    inspected = []

    def search(_lvl, branch, stage, config, _rng, **kwargs):
        assert config.live_save_best
        candidate = (InputFrame(left=True),) + tuple(branch[1:])
        assert EndpointEvaluator(_lvl, stage.goal).evaluate(candidate).objective_key < (
            EndpointEvaluator(_lvl, stage.goal).evaluate(branch).objective_key)
        kwargs['candidate_callback'](candidate, 10)
        assert session_movie.is_file() and session_txt.is_file()
        assert (tmp_path / 'out_631.ltm').is_file()  # new absolute stage best
        assert LtmMovie.load(session_movie).replay_frames
        assert editable_frames(decode_complex_replay(session_txt.read_text().strip()).frames) == (
            editable_frames(LtmMovie.load(session_movie).replay_frames))
        assert not output.is_file()
        inspected.append(True)
        raise KeyboardInterrupt

    monkeypatch.setattr(us, '_search_stage', search)
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'hybrid', str(ltm), '--goal-config', str(goal),
        '--levels-file', str(database), '--output', str(output),
        '--replay-output', str(tmp_path / 'out.txt'),
        '--workers', '15', '--auto-runs', '1', '--no-propagation'])
    with pytest.raises((KeyboardInterrupt, SystemExit)) as exc:
        main()
    assert inspected, f"early exception: {exc.value!r}"
    assert inspected and session_movie.is_file() and session_txt.is_file()


def test_cli_ordinary_multi_splicer_does_not_enable_immediate_writes(tmp_path, monkeypatch):
    """Hybrid session files and no-throttle mode are standalone-only."""
    from nv14_cli import main
    import nv14_user_splice as us

    level, (_, _, source) = _replays()
    input_file = tmp_path / 'input.txt'
    input_file.write_text(f'$test#author#{level.source_level_string}#'
                          f'{encode_complex_replay(source)}#\n')
    goal = tmp_path / '631.txt'
    goal.write_text('[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    captured = []
    def search(_level, _branch, _stage, config, _rng, **kw):
        captured.append(config.live_save_best)
        return (), 1, 1
    monkeypatch.setattr(us, '_search_stage', search)
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(input_file), '--auto-splice-files', '631',
        '--auto-splice-search', 'hybrid', '--auto-splice-directory', str(tmp_path),
        '--auto-runs', '1', '--output', str(tmp_path / 'out.txt'),
        '--no-propagation', '--workers', '1'])
    main()
    assert captured == [False]
    assert not (tmp_path / 'out_631.session.txt').exists()
