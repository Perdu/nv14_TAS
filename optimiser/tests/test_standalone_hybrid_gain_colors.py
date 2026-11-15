"""Standalone Hybrid distinguishes this session's progress from saved stage wins."""
from __future__ import annotations

from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_engine import InputFrame
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from nv14_cli import _print_user_splice_progress
from tests.test_random_splice import _baseline


def _three_replays():
    level, source, _ = _baseline()
    first = (InputFrame(left=True),) + source[1:]
    second = (InputFrame(left=True), InputFrame(left=True)) + source[2:]
    stage = UserSpliceStage('631', EndpointGoal(10, 'min-x'), 0, 10)
    evaluation = EndpointEvaluator(level, stage.goal)
    ordered = sorted((source, first, second), key=lambda candidate:
                     evaluation.evaluate(candidate).objective_key)
    assert len({evaluation.evaluate(candidate).objective_key for candidate in ordered}) == 3
    return level, stage, ordered


def test_hybrid_reports_yellow_session_gain_when_saved_best_is_faster(monkeypatch):
    import nv14_user_splice as us
    level, stage, (best, middle, worst) = _three_replays()
    monkeypatch.setattr(us, '_search_stage',
                        lambda *_args, **_kwargs: (((middle, 10),), 1, 1))
    logs, saved = [], []
    optimise_user_splices(
        level, worst, [stage], RandomSpliceConfig(rounds=1, workers=1, iterations=2),
        single_input_seed=True, completion_policy='checkpoint',
        saved_stage_candidates={'631': [best]}, stage_best_callback=lambda *x: saved.append(x),
        progress=logs.append)
    assert not saved  # Never clobber stronger historical checkpoint.
    gains = [line for line in logs if '[auto:hybrid:gain:' in line]
    assert len(gains) == 1
    assert '[auto:hybrid:gain:input]' in gains[0]
    assert 'improves input only' in gains[0]
    assert 'vs input run:' in gains[0] and 'vs previous absolute best:' in gains[0]


def test_hybrid_reports_green_new_absolute_best(monkeypatch):
    import nv14_user_splice as us
    level, stage, (best, middle, worst) = _three_replays()
    monkeypatch.setattr(us, '_search_stage',
                        lambda *_args, **_kwargs: (((best, 10), (middle, 10)), 2, 1))
    logs, saved = [], []
    optimise_user_splices(
        level, worst, [stage], RandomSpliceConfig(rounds=1, workers=1, iterations=2),
        single_input_seed=True, completion_policy='checkpoint',
        saved_stage_candidates={'631': [middle]},
        stage_best_callback=lambda *x: saved.append(x), progress=logs.append)
    gains = [line for line in logs if '[auto:hybrid:gain:' in line]
    assert len(gains) == 1
    assert '[auto:hybrid:gain:absolute]' in gains[0]
    assert 'new absolute best' in gains[0]
    assert saved == [('631', best)]


def test_hybrid_colors_and_no_color(monkeypatch, capsys):
    monkeypatch.setattr('sys.stdout.isatty', lambda: True)
    _print_user_splice_progress('[auto:hybrid:gain:input] yellow', color=True)
    _print_user_splice_progress('[auto:hybrid:gain:absolute] green', color=True)
    output = capsys.readouterr().out
    assert '\x1b[33m' in output.splitlines()[0]
    assert '\x1b[32m' in output.splitlines()[1]
    _print_user_splice_progress('[auto:hybrid:gain:absolute] plain', color=False)
    assert '\x1b[' not in capsys.readouterr().out


def test_saved_completed_run_also_blocks_false_green(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    one = (InputFrame(left=True),) + source[1:]
    two = (InputFrame(left=True), InputFrame(left=True)) + source[2:]
    stage = UserSpliceStage('631', EndpointGoal(10, 'max-x'), 0, 10)
    evaluator = EndpointEvaluator(level, stage.goal)
    # The untouched replay is a verified completion and has the highest x;
    # edited routes improve the *input* but must not be green.
    assert evaluator.evaluate(source).objective_key < evaluator.evaluate(one).objective_key
    assert evaluator.evaluate(one).objective_key < evaluator.evaluate(two).objective_key
    monkeypatch.setattr(us, '_search_stage',
                        lambda *args, **kw: (((one, 10),), 1, 1))
    messages = []
    optimise_user_splices(level, two, [stage],
                          RandomSpliceConfig(rounds=1, workers=1, iterations=2),
                          single_input_seed=True, completion_policy='checkpoint',
                          saved_final_frames=source, progress=messages.append)
    gains = [line for line in messages if '[auto:hybrid:gain:' in line]
    assert len(gains) == 1
    assert '[auto:hybrid:gain:input]' in gains[0]
    assert 'vs previous absolute best:' in gains[0]
