"""Named multi-splicer: deterministic file ordering, safety and CLI integration."""
from pathlib import Path
import sys

import pytest

from nv14_cli import (parse_arguments, _load_named_splice_stages,
                       _resolve_named_splice_files, main)
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from nv14_replay import encode_complex_replay
from nv14_auto import evaluate_replay_with_sentinel
from tests.test_random_splice import _baseline


def test_config_only_splice_array_selects_user_mode(tmp_path):
    cfg = tmp_path / "cfg.toml"
    cfg.write_text('[auto]\nsplice-files=["203","408","switch","end"]\n')
    args = parse_arguments(['auto', 'some.ltm', '--config', str(cfg)])
    assert args.auto_random_splice and args.auto_splice_mode == "user"
    assert args.auto_splice_files == ('203', '408', 'switch', 'end')
    assert args.auto_splice_directory is None


def test_named_files_exact_order_resolution_and_goal_parser(tmp_path):
    level, frames, _ = _baseline()
    names = ('203', '408', 'switch', 'end')
    for index, name in enumerate(names):
        (tmp_path / (name + ('.toml' if index == 2 else '.txt'))).write_text(
            f'[local]\nobjective="max-x"\ntarget-frame={12+index}\nrange="0:{12+index}"\n')
    args = parse_arguments(['auto', 'some.ltm', '--auto-splice-files', ','.join(names)])
    assert [name for name, _ in _resolve_named_splice_files(tmp_path, names)] == list(names)
    stages = _load_named_splice_stages(level, frames, args, tmp_path, names)
    assert tuple(s.name for s in stages) == names
    assert [s.goal.target_frame for s in stages] == [12, 13, 14, 15]


def test_missing_ambiguous_or_unsafe_files_rejected(tmp_path):
    (tmp_path / '203.txt').write_text('[local]\nobjective="min-y"\ntarget-frame=12\n')
    (tmp_path / '203.toml').write_text('[local]\nobjective="min-y"\ntarget-frame=12\n')
    with pytest.raises(ValueError, match='exactly one'):
        _resolve_named_splice_files(tmp_path, ('203',))
    with pytest.raises(SystemExit):
        parse_arguments(['auto', 'some.ltm', '--auto-splice-files', '203,203'])
    with pytest.raises(SystemExit):
        parse_arguments(['auto', 'some.ltm', '--auto-splice-files', '../secret'])


def test_named_stages_reject_missing_goal_definition(tmp_path):
    level, frames, _ = _baseline()
    (tmp_path / 'switch.txt').write_text('[local]\nobjective="min-y"\n')
    args = parse_arguments(['auto', 'some.ltm', '--auto-splice-files', 'switch'])
    with pytest.raises(ValueError, match='requires objective and target-frame'):
        _load_named_splice_stages(level, frames, args, tmp_path, ('switch',))


def test_completed_source_remains_valid_and_baseline_never_saved():
    level, source, base = _baseline()
    stages = [UserSpliceStage('first', EndpointGoal(10, 'max-x'), 0, 10),
              UserSpliceStage('end', EndpointGoal(14, 'max-x'), 11, 14)]
    saved = []
    result = optimise_user_splices(
        level, source, stages, RandomSpliceConfig(
            iterations=10, splice_rounds=1, rounds=1, workers=1, beam=8, seed=4),
        best_callback=saved.append)
    assert result.evaluations > 0
    checked = evaluate_replay_with_sentinel(level, result.frames)
    assert checked.valid and checked.finish_tick == len(result.frames)
    if saved:
        assert saved[-1] == result.frames
    assert result.improvements == len(saved)


def test_no_stage_skipping_when_an_earlier_requirement_is_broken(monkeypatch):
    level, source, baseline = _baseline()
    first_tick = 10
    initial_point = baseline.point(first_tick)
    # Achievable only by replay inputs of the starting source at this tick.
    stage0 = UserSpliceStage('first', EndpointGoal(
        first_tick, 'earliest-arrival',
        target_region=(initial_point.x-1, initial_point.x+1,
                       initial_point.y-1, initial_point.y+1)), 0, first_tick)
    stage1 = UserSpliceStage('end', EndpointGoal(14, 'max-x'), 0, 14)
    altered = tuple(InputFrame(left=True) for _ in source)
    import nv14_user_splice as us
    monkeypatch.setattr(us, '_local_search', lambda *a, **kw: (((altered, 14),), 1))
    result = us.optimise_user_splices(level, source, [stage0, stage1],
                    RandomSpliceConfig(rounds=1, workers=1, iterations=1))
    assert result.frames == tuple(source)
    assert result.improvements == 0


def test_cli_loads_ordered_goals_from_explicit_directory(tmp_path, monkeypatch):
    level, frames, _ = _baseline()
    input_path = tmp_path / 'source.txt'
    input_path.write_text(f'$test#author#{level.source_level_string}#'
                          f'{encode_complex_replay(frames)}#\n')
    goals = tmp_path / 'goals'; goals.mkdir()
    for name, tick in [('203', 12), ('end', 15)]:
        (goals / (name+'.txt')).write_text(
            f'[local]\nobjective="max-x"\ntarget-frame={tick}\nrange="0:{tick}"\n')
    config = tmp_path / 'config.toml'
    config.write_text('[auto]\nsplice-files=["203","end"]\n'
                      'runs=1\nsplice-iterations=8\nsplice-rounds=1\nbeam=8\nseed=0\n')
    out = tmp_path / 'optim.txt'
    monkeypatch.setattr(sys, 'argv', ['optimize_replay.py', 'auto', str(input_path),
        '--config', str(config), '--auto-splice-directory', str(goals),
        '--output', str(out), '--workers', '1'])
    main()
    # No no-op checkpoints, but a completed and validated improvement may be saved.
    if out.exists():
        from nv14_replay import parse_combined_level_replay, decode_complex_replay
        replay = parse_combined_level_replay(out.read_text())
        checked = evaluate_replay_with_sentinel(level, decode_complex_replay(replay.replay_string).frames)
        assert checked.valid and checked.finish_tick == len(decode_complex_replay(replay.replay_string).frames)


def test_named_goal_after_completed_replay_end_uses_neutral_tail(tmp_path):
    """Regression: end.txt may target frames later than the recorded finish."""
    level, source, check = _baseline()
    assert check.finish_tick == len(source)
    (tmp_path / '218.txt').write_text(
        '[local]\nobjective="max-x"\ntarget-frame=15\nrange="0:15"\n')
    (tmp_path / 'end.txt').write_text(
        '[local]\nobjective="max-x"\ntarget-frame=36\nrange="20:36"\n')
    args = parse_arguments(['auto', 'some.ltm', '--auto-splice-files', '218,end'])
    stages = _load_named_splice_stages(level, source, args, tmp_path, ('218', 'end'))
    assert [(s.name, s.goal.target_frame, s.start, s.end) for s in stages] == [
        ('218', 15, 0, 15), ('end', 36, 20, 36)]

    # The optimiser can search the padded interval, but must preserve the
    # canonical, completed source when no strict improvement was found.
    messages, saves = [], []
    result = optimise_user_splices(
        level, source, stages, RandomSpliceConfig(
            iterations=6, splice_rounds=1, rounds=1, workers=1, beam=8, seed=4),
        best_callback=saves.append, progress=messages.append,
        completion_policy='complete')
    assert result.evaluations > 0
    assert any('appended 8 neutral search frame(s)' in line for line in messages)
    assert any(f'completion at frame {len(source)}' in line for line in messages)
    if saves:
        assert result.frames == saves[-1]
    else:
        assert result.frames == tuple(source)
    checked = evaluate_replay_with_sentinel(level, result.frames)
    assert checked.valid and checked.finish_tick == len(result.frames)


def test_named_goal_on_short_incomplete_source_uses_neutral_tail(tmp_path):
    """An incomplete prefix can also be extended through the configured goal."""
    level, source, _ = _baseline()
    short = source[:12]
    (tmp_path / 'end.txt').write_text(
        '[local]\nobjective="max-x"\ntarget-frame=36\nrange="5:36"\n')
    args = parse_arguments(['auto', 'some.ltm', '--auto-splice-files', 'end'])
    stages = _load_named_splice_stages(level, short, args, tmp_path, ('end',))
    messages = []
    result = optimise_user_splices(
        level, short, stages, RandomSpliceConfig(
            iterations=6, splice_rounds=1, rounds=1, workers=1, beam=8, seed=5),
        progress=messages.append, completion_policy='checkpoint')
    assert result.evaluations > 0
    assert any('appended 25 neutral search frame(s)' in line for line in messages)
    assert any('incomplete source' in line for line in messages)


def test_user_splice_unextended_completed_replay_remains_unchanged():
    level, source, _ = _baseline()
    stage = UserSpliceStage('end', EndpointGoal(15, 'max-x'), 0, 15)
    result = optimise_user_splices(level, source, (stage,), RandomSpliceConfig(
        iterations=4, splice_rounds=1, rounds=1, workers=1, beam=8, seed=2),
        completion_policy='complete')
    assert evaluate_replay_with_sentinel(level, result.frames).finish_tick == len(result.frames)


def test_user_splice_end_interaction_can_precede_later_target(tmp_path):
    """An early exit is valid even when end.txt ends several ticks afterward."""
    from nv14_endpoint import EndpointEvaluator
    from nv14_user_splice import _materialise_splice_tail
    level, source, _ = _baseline()
    (tmp_path / 'end.txt').write_text(
        '[local]\nobjective="earliest-interaction"\n'
        'target-object="exit:0.door"\ntarget-frame=36\n'
        'arrival-start=0\nrange="20:36"\n')
    args = parse_arguments(['auto', 'some.ltm', '--auto-splice-files', 'end'])
    (stage,) = _load_named_splice_stages(level, source, args, tmp_path, ('end',))
    goal_eval = EndpointEvaluator(level, stage.goal).evaluate(
        _materialise_splice_tail(source, stage.goal.target_frame))
    assert goal_eval.feasible and goal_eval.frame == len(source)

    # The search starts from a canonical 29-tick completion, not an invalid
    # 37-tick reference. Both backends may optimise the 37-tick workspace.
    reports = []
    result = optimise_user_splices(
        level, source, [stage], RandomSpliceConfig(
            search_backend='both', iterations=8, splice_rounds=1,
            rounds=1, workers=1, beam=8, frontier=2, seed=7),
        completion_policy='complete', progress=reports.append)
    assert result.attempts == 2
    assert result.evaluations > 0
    assert any('completion at frame 29' in line for line in reports)
    verified = evaluate_replay_with_sentinel(level, result.frames)
    assert verified.valid and verified.finish_tick == len(result.frames)


def test_cli_user_splicer_accepts_target_after_finish(tmp_path, monkeypatch):
    level, frames, _ = _baseline()
    input_path = tmp_path / 'source.txt'
    input_path.write_text(f'$test#author#{level.source_level_string}#'
                          f'{encode_complex_replay(frames)}#\n')
    goals = tmp_path / 'goals'; goals.mkdir()
    (goals / '218.txt').write_text(
        '[local]\nobjective="max-x"\ntarget-frame=15\nrange="0:15"\n')
    (goals / 'end.txt').write_text(
        '[local]\nobjective="earliest-interaction"\n'
        'target-object="exit:0.door"\ntarget-frame=36\n'
        'arrival-start=0\nrange="20:36"\n')
    config = tmp_path / 'multi-splicer.toml'
    config.write_text('[auto]\nsplice-files=["218", "end"]\n'
                      'splice-search="both"\nruns=1\nsplice-iterations=8\n'
                      'splice-rounds=1\nbeam=8\nseed=0\n')
    out = tmp_path / 'optim.txt'
    monkeypatch.setattr(sys, 'argv', [
        'optimize_replay.py', 'auto', str(input_path),
        '--config', str(config), '--auto-splice-directory', str(goals),
        '--output', str(out), '--workers', '1'])
    main()
    if out.exists():
        from nv14_replay import parse_combined_level_replay, decode_complex_replay
        rendered = parse_combined_level_replay(out.read_text())
        candidate = decode_complex_replay(rendered.replay_string).frames
        verified = evaluate_replay_with_sentinel(level, candidate)
        assert verified.valid and verified.finish_tick == len(candidate)


def test_unmet_intermediate_checkpoint_does_not_skip_end(monkeypatch):
    """A failed stage must not silently discard the final end search."""
    import nv14_user_splice as us
    level, source, _ = _baseline()
    stages = (
        UserSpliceStage('556', EndpointGoal(10, 'max-x'), 0, 10),
        UserSpliceStage('739', EndpointGoal(12, 'earliest-arrival',
            target_region=(100000, 100010, 100000, 100010)), 0, 12),
        UserSpliceStage('end', EndpointGoal(15, 'max-x'), 0, 15),
    )
    visited = []
    def fake_search(level, branch, stage, config, rng):
        visited.append((stage.name, branch))
        return (((branch, stage.goal.target_frame),), 1, 1)
    monkeypatch.setattr(us, '_search_stage', fake_search)
    messages, saved = [], []
    result = us.optimise_user_splices(
        level, source, stages, RandomSpliceConfig(
            iterations=6, rounds=1, workers=1, frontier=2, seed=3),
        progress=messages.append, best_callback=saved.append,
        completion_policy='complete')
    assert [name for name, _ in visited] == ['556', '739', 'end']
    assert visited[-1][1] == tuple(source)
    assert any("'739': no candidate met all goals" in line for line in messages)
    assert any("'end' seed 1/1" in line for line in messages)
    assert any('unmet checkpoints: 739, end' in line for line in messages)
    assert result.attempts == 3 and result.evaluations == 3
    assert result.frames == tuple(source) and result.improvements == 0
    assert not saved


def test_failed_stage_keeps_two_back_fallback_branches(monkeypatch):
    """An infeasible checkpoint must not erase distinct older seed replays."""
    import nv14_user_splice as us
    level, source, _ = _baseline()
    alt = list(source)
    alt[4] = InputFrame(right=not source[4].right)
    alt = tuple(alt)
    stages = (
        UserSpliceStage('first', EndpointGoal(10, 'max-x'), 0, 10),
        UserSpliceStage('second', EndpointGoal(11, 'max-x'), 0, 11),
        UserSpliceStage('unreachable', EndpointGoal(12, 'earliest-arrival',
            target_region=(100000, 100010, 100000, 100010)), 0, 12),
        UserSpliceStage('end', EndpointGoal(15, 'max-x'), 0, 15),
    )
    visited = []
    def fake_search(level, branch, stage, config, rng):
        visited.append((stage.name, branch))
        if stage.name == 'first':
            return (((branch, 10), (alt, 10)), 1, 1)
        return (((branch, stage.goal.target_frame),), 1, 1)
    monkeypatch.setattr(us, '_search_stage', fake_search)
    logs = []
    result = us.optimise_user_splices(
        level, source, stages, RandomSpliceConfig(
            iterations=6, rounds=1, workers=1, frontier=2, seed=3),
        progress=logs.append)
    assert any(stage == 'end' for stage, branch in visited)
    assert any("'unreachable': no candidate met all goals" in line for line in logs)
    assert result.frames == tuple(source) and result.improvements == 0
