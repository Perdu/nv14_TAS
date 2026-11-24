"""Auto/Local cannot publish redundant Shift presses from late splice inputs."""
from __future__ import annotations

import sys

import pytest

from nv14_auto import evaluate_replay_with_sentinel
from nv14_engine import InputFrame
from nv14_replay import (clean_ineffective_air_jumps, decode_complex_replay,
                         editable_frames, encode_complex_replay, parse_combined_level_replay)
from tests.test_random_splice import _baseline


def _held_jump_tail():
    level, _, _ = _baseline()
    # The real jump is triggered at 2; N's max jump hold is 30 ticks. After
    # that the player has started falling and Shift cannot affect the trace,
    # even though the same continuous press began on the floor.
    # The explicit release at 60 makes it safe to reuse this checkpoint:
    # both input streams have the same jump-edge state at the final body tick.
    frames = tuple(InputFrame(jump=(2 <= i < 60)) for i in range(61))
    return level, frames


def test_remove_useless_tail_of_real_jump_without_changing_any_trace():
    level, frames = _held_jump_tail()
    cleaned = clean_ineffective_air_jumps(level, frames)
    assert [i for i, f in enumerate(cleaned) if f.jump] == list(range(2, 33))
    original = evaluate_replay_with_sentinel(level, frames)
    verified = evaluate_replay_with_sentinel(level, cleaned)
    assert original.successful_jumps == verified.successful_jumps == (2,)
    assert original.route_control_events == verified.route_control_events
    assert original.final_gold_mask == verified.final_gold_mask
    # All world, collision, velocity and event fields other than the cached
    # previous-held-input marker stay exactly equal for each simulated tick.
    from dataclasses import replace
    assert all(replace(a, previous_jump_held=False) ==
               replace(b, previous_jump_held=False)
               for a, b in zip(original.trace, verified.trace))
    assert len(original.trace) == len(verified.trace)
    assert clean_ineffective_air_jumps(level, cleaned) == cleaned


def test_local_mutable_boundary_cannot_truncate_a_crossing_jump_pulse():
    level, frames = _held_jump_tail()
    assert clean_ineffective_air_jumps(
        level, frames, editable_ranges=((33, 59),)) == frames
    assert clean_ineffective_air_jumps(
        level, frames, editable_ranges=((2, 59),))[32].jump
    assert not clean_ineffective_air_jumps(
        level, frames, editable_ranges=((2, 59),))[33].jump


def test_saved_stage_checkpoint_does_not_restore_shift_tail(tmp_path, monkeypatch):
    """Stage suffix restore used to reintroduce the useless held jump."""
    import nv14_user_splice as splice
    from nv14_cli import main

    level, frames = _held_jump_tail()
    source = tmp_path / 'input.txt'
    source.write_text(f'$test#author#{level.source_level_string}#'
                      f'{encode_complex_replay(frames)}#\n')
    goals = tmp_path / 'goals'
    goals.mkdir()
    (goals / 'end.txt').write_text(
        '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    config = tmp_path / 'cfg.toml'
    config.write_text('[auto]\nsplice-files=["end"]\nsplice-iterations=1\n'
                      'splice-rounds=1\nruns=1\n')
    # Seed initialisation emits a named checkpoint before search starts.
    monkeypatch.setattr(splice, '_search_stage', lambda *args, **kwargs: ((), 0, 0))
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(source), '--config', str(config),
        '--auto-splice-directory', str(goals),
        '--output', str(tmp_path / 'out.txt'), '--workers', '1',
    ])
    main()
    published = parse_combined_level_replay(
        (tmp_path / 'out_end.txt').read_text())
    saved = tuple(editable_frames(decode_complex_replay(
        published.replay_string).frames))
    assert len(saved) == len(frames)
    assert [i for i, frame in enumerate(saved) if frame.jump] == list(range(2, 33))
    assert evaluate_replay_with_sentinel(level, saved).successful_jumps == (2,)


@pytest.mark.parametrize("release_after_hold", [False, True])
def test_ltm_checkpoint_uses_serialized_jump_boundary(
    tmp_path, monkeypatch, release_after_hold,
):
    import nv14_user_splice as splice
    from nv14_cli import main
    from nv14_ltm import LEVEL_DATABASE_NAME, LtmMovie
    from tests.test_ltm import _basic_config, _level_record, _write_ltm

    # An LTM ending with a held Shift has no serialized release, even if it
    # includes neutral post-roll. Only the variant with a later right press
    # serializes an explicit release before the movie boundary.
    body = (tuple(InputFrame(jump=(2 <= i < 60), right=(i == 61))
                  for i in range(62)) if release_after_hold else
            tuple(InputFrame(jump=(2 <= i < 60)) for i in range(60)))
    rows = ['|', '|K20|'] + [
        '|Kffe1|' if frame.jump else '|Kff53|' if frame.right else '|'
        for frame in body
    ] + ['|Mpost:0|', '|Mpost:1|']
    source = _write_ltm(tmp_path / '00-0.ltm', ('\n'.join(rows) + '\n').encode(),
                        config=_basic_config(frame_count=len(rows)))
    (tmp_path / LEVEL_DATABASE_NAME).write_text(_level_record() + '\n')
    goals = tmp_path / 'goals'
    goals.mkdir()
    (goals / 'end.txt').write_text(
        '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    config = tmp_path / 'config.toml'
    config.write_text('[auto]\nsplice-files=["end"]\nsplice-iterations=1\n'
                      'splice-rounds=1\nruns=1\n')
    monkeypatch.setattr(splice, '_search_stage', lambda *args, **kwargs: ((), 0, 0))
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(source), '--config', str(config),
        '--auto-splice-directory', str(goals),
        '--levels-file', str(tmp_path / LEVEL_DATABASE_NAME),
        '--output', str(tmp_path / 'out.ltm'), '--workers', '1',
    ])
    main()
    movie = LtmMovie.load(tmp_path / 'out_end.ltm')
    # Preserve post-roll and the last *serialized* jump-button state. A
    # released tail may be shortened; a hold through the boundary may not.
    assert len(movie.input_lines) >= movie.replay_start + len(body)
    from nv14_ltm import KEY_JUMP, keyboard_keys
    held_end = 33 if release_after_hold else 60
    assert all(KEY_JUMP in keyboard_keys(movie.input_lines[movie.replay_start + i])
               for i in range(2, held_end))
    assert all(KEY_JUMP not in keyboard_keys(movie.input_lines[movie.replay_start + i])
               for i in range(held_end, len(body)))
    saved = decode_complex_replay((tmp_path / 'out_end.txt').read_text()).frames
    assert tuple(i for i, frame in enumerate(saved) if frame.jump) == tuple(range(2, held_end))


def test_incomplete_checkpoint_must_preserve_live_jump_edge_at_body_end():
    """The implicit neutral sentinel is not the state when a stage is extended."""
    from nv14_replay import identical_replay_physics

    level, released = _held_jump_tail()
    # Leave Shift held through the last *serialized* frame, without a release.
    source = released[:-1]
    assert not evaluate_replay_with_sentinel(level, source).completed
    # The formerly accepted truncation has identical physics up to the
    # sentinel, but would turn the next held Shift input into a fresh edge.
    bad = tuple(InputFrame(frame.left, frame.right,
                           frame.jump if index < 33 else False)
                for index, frame in enumerate(source))
    original_eval = evaluate_replay_with_sentinel(level, source)
    bad_eval = evaluate_replay_with_sentinel(level, bad)
    assert original_eval.point(len(source) - 1).previous_jump_held
    assert not bad_eval.point(len(source) - 1).previous_jump_held
    assert not original_eval.trace[-1].previous_jump_held
    assert not bad_eval.trace[-1].previous_jump_held
    assert original_eval.successful_jumps == bad_eval.successful_jumps
    assert not identical_replay_physics(level, source, bad)

    continuation = (InputFrame(jump=True),)
    original_extended = evaluate_replay_with_sentinel(level, source + continuation)
    bad_extended = evaluate_replay_with_sentinel(level, bad + continuation)
    assert len(source) not in original_extended.jump_edges
    assert len(source) in bad_extended.jump_edges
    assert clean_ineffective_air_jumps(level, source) == source


def test_release_after_ineffective_hold_allows_safe_checkpoint_cleanup():
    level, source = _held_jump_tail()
    cleaned = clean_ineffective_air_jumps(level, source)
    assert tuple(i for i, frame in enumerate(cleaned) if frame.jump) == tuple(range(2, 33))
    # The body boundary, not just the forced neutral sentinel, must agree.
    a = evaluate_replay_with_sentinel(level, source)
    b = evaluate_replay_with_sentinel(level, cleaned)
    assert a.point(len(source) - 1).previous_jump_held == b.point(len(source) - 1).previous_jump_held
    # Arbitrary continuations after the release start from identical native
    # input history. No new rising Shift edge should appear.
    for future in ((InputFrame(jump=True),),
                   (InputFrame(), InputFrame(jump=True))):
        a2 = evaluate_replay_with_sentinel(level, source + future)
        b2 = evaluate_replay_with_sentinel(level, cleaned + future)
        assert a2.jump_edges == b2.jump_edges
        assert a2.successful_jumps == b2.successful_jumps


def test_saved_incomplete_txt_checkpoint_keeps_unreleased_shift(tmp_path, monkeypatch):
    """The saver must not erase the jump edge required by a later splice."""
    import nv14_user_splice as splice
    from nv14_cli import main

    level, released = _held_jump_tail()
    frames = released[:-1]
    source = tmp_path / 'input.txt'
    source.write_text(f'$test#author#{level.source_level_string}#'
                      f'{encode_complex_replay(frames)}#\n')
    goals = tmp_path / 'goals'
    goals.mkdir()
    (goals / 'end.txt').write_text(
        '[local]\nobjective="min-x"\ntarget-frame=10\nrange="0:10"\n')
    config = tmp_path / 'cfg.toml'
    config.write_text('[auto]\nsplice-files=["end"]\nsplice-iterations=1\n'
                      'splice-rounds=1\nruns=1\n')
    monkeypatch.setattr(splice, '_search_stage', lambda *args, **kwargs: ((), 0, 0))
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(source), '--config', str(config),
        '--auto-splice-directory', str(goals),
        '--output', str(tmp_path / 'out.txt'), '--workers', '1',
    ])
    main()
    published = parse_combined_level_replay((tmp_path / 'out_end.txt').read_text())
    saved = tuple(editable_frames(decode_complex_replay(published.replay_string).frames))
    assert saved == frames
    # Extension with Shift still held should not acquire a new rising edge.
    before = evaluate_replay_with_sentinel(level, frames + (InputFrame(jump=True),))
    after = evaluate_replay_with_sentinel(level, saved + (InputFrame(jump=True),))
    assert before.jump_edges == after.jump_edges
