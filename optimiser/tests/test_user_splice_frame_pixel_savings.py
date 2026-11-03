"""Patch 45: physical frame/pixel deltas, including read-only summaries."""
from dataclasses import replace
import sys

import nv14_user_splice as us
from nv14_cli import main
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from nv14_engine import InputFrame
from tests.test_random_splice import _baseline
from tests.test_user_splice_list_summary import _setup, _write_combined
from nv14_replay import encode_complex_replay


def test_goal_directed_pixel_savings_are_signed_correctly():
    level, source, _ = _baseline()
    original = EndpointEvaluator(level, EndpointGoal(10, 'min-x')).evaluate(source)
    earlier = replace(original, frame=8, x=original.x-4.25)
    assert us._stage_savings_text(EndpointGoal(10, 'min-x'), earlier, original, 'input run') == (
        'vs input run: +2 frames saved, +4.25 px saved (min-x)')
    later = replace(original, frame=13, x=original.x+3.5)
    assert us._stage_savings_text(EndpointGoal(10, 'min-x'), later, original, 'best run') == (
        'vs best run: -3 frames saved, -3.5 px saved (min-x)')
    assert '+3.5 px saved (max-x)' in us._stage_savings_text(
        EndpointGoal(10, 'max-x'), later, original, 'input run')


def test_distance_and_earliest_objectives_do_not_mislabel_pixels():
    level, source, _ = _baseline()
    original = EndpointEvaluator(level, EndpointGoal(10, 'min-x')).evaluate(source)
    # Only the objective's score matters to physical distance comparison.
    from types import SimpleNamespace
    distance_goal = SimpleNamespace(objective='min-distance', secondary_objective=None)
    assert '+4 px saved (min-distance)' in us._stage_savings_text(
        distance_goal, replace(original, score=-36),
        replace(original, score=-100), 'input run')
    earliest_goal = SimpleNamespace(objective='earliest-arrival', secondary_objective=None)
    result = us._stage_savings_text(
        earliest_goal, replace(original, frame=8, x=original.x-10),
        original, 'input run')
    assert '+2 frames saved' in result
    assert 'position dx -10 px' in result
    assert 'px saved' not in result
    secondary_goal = SimpleNamespace(objective='earliest-arrival', secondary_objective='min-x')
    result = us._stage_savings_text(
        secondary_goal, replace(original, frame=8, secondary_value=5),
        replace(original, secondary_value=15), 'best run')
    assert '+10 px saved (min-x)' in result
    assert us._stage_savings_text(secondary_goal, original, None, 'best run').endswith(
        'unavailable (no feasible checkpoint)')


def test_saved_stage_best_reports_deltas_against_input_and_best(monkeypatch):
    level, source, _ = _baseline()
    improved = (InputFrame(left=True),) + source[1:]
    stage = UserSpliceStage('230', EndpointGoal(10, 'min-x'), 0, 10)
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs: ((), 0, 1))
    lines = []
    optimise_user_splices(level, source, [stage],
                          RandomSpliceConfig(rounds=1, workers=1, iterations=2),
                          saved_stage_candidates={'230': [improved]},
                          completion_policy='checkpoint',
                          progress=lines.append)
    saved_line = next(s for s in lines if '[auto:user-splice:summary:pending]' in s)
    assert 'vs input run:' in saved_line
    assert 'vs best run:' in saved_line
    assert 'px saved (min-x)' in saved_line
    assert 'frames saved' in saved_line


def test_cli_ls_splice_uses_original_input_comparison(tmp_path, monkeypatch, capsys):
    level, source, saved, output, _packed, argv = _setup(tmp_path)
    _write_combined(output, level, saved)
    (tmp_path / '97-1_230.txt').write_text(encode_complex_replay(saved) + '\n')
    monkeypatch.setattr(us, '_search_stage', lambda *a, **kw:
                        (_ for _ in ()).throw(AssertionError('summary started a search')))
    monkeypatch.setattr(sys, 'argv', [*argv, '--ls-splice'])
    main()
    stdout = capsys.readouterr().out
    line = next(s for s in stdout.splitlines() if '[auto:user-splice:summary:propagated]' in s)
    original = EndpointEvaluator(level, EndpointGoal(10, 'min-x')).evaluate(source)
    revised = EndpointEvaluator(level, EndpointGoal(10, 'min-x')).evaluate(saved)
    gain = original.x-revised.x
    assert gain > 0
    assert f'{gain:+.6g} px saved (min-x)' in line
    assert 'vs best run: +0 frames saved, +0 px saved (min-x)' in line
