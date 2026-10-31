"""Multi-splice reporting: shared budget, temporary vs verified results."""
from __future__ import annotations

import random
from dataclasses import replace

from nv14_cli import _print_temporary_line, parse_arguments
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal, EndpointEvaluator
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, _search_stage, _stage_improvement_text, optimise_user_splices
from tests.test_random_splice import _baseline


def test_no_stage_specific_budget_option(tmp_path):
    config = tmp_path / 'multi.toml'
    config.write_text('[auto]\nsplice-files=["203","end"]\n'
                      'splice-search="both"\nsplice-iterations=400\n'
                      'splice-rounds=3\nruns=5\n')
    args = parse_arguments(['auto', 'source.ltm', '--config', str(config)])
    assert args.auto_splice_iterations == 400
    assert args.auto_splice_rounds == 3
    assert args.auto_runs == 5


def test_both_passes_internal_rounds_and_shared_iterations(monkeypatch):
    import nv14_user_splice as module
    level, source, _ = _baseline()
    stage = UserSpliceStage('203', EndpointGoal(10, 'max-x'), 0, 10)
    observed = []

    def fake_search(*args, **kwargs):
        observed.append((kwargs['config'].search_backend,
                         kwargs['iterations'], kwargs['rounds']))
        return (), 0

    monkeypatch.setattr(module, '_local_search', fake_search)
    _search_stage(level, source, stage,
                  RandomSpliceConfig(search_backend='both', iterations=401,
                                     splice_rounds=3), random.Random(1))
    assert observed == [('endpoint-auto', 200, 3), ('local', 201, 3)]


def test_temporary_best_is_not_saved_and_budget_is_shared(monkeypatch):
    import nv14_user_splice as module
    level, source, _ = _baseline()
    better = (InputFrame(left=True),) + source[1:]
    stages = [
        UserSpliceStage('203', EndpointGoal(10, 'min-x'), 0, 10),
        UserSpliceStage('end', EndpointGoal(18, 'max-x'), 0, 18),
    ]
    calls = []

    def fake_stage_search(level, branch, stage, config, rng):
        calls.append((stage.name, config.iterations))
        if stage.name == '203':
            return ((better, 10),), 9, 2
        return (), 3, 2

    monkeypatch.setattr(module, '_search_stage', fake_stage_search)
    messages, saves = [], []
    outcome = optimise_user_splices(
        level, source, stages,
        RandomSpliceConfig(iterations=400, splice_rounds=2,
                           rounds=1, workers=2, frontier=1,
                           search_backend='both'),
        progress=messages.append, best_callback=saves.append)
    assert calls and all(amount == 400 for _, amount in calls)
    assert any('endpoint Auto 200 -> Local 200 (seeded from Auto best)' in line
               and '2 internal round(s) per seed' in line for line in messages)
    assert any('[auto:user-splice:temporary]' in line and "'203'" in line
               and 'new stage best' in line for line in messages)
    assert any('[auto:user-splice:stage]' in line and 'distinct evaluations' in line
               for line in messages)
    assert outcome.improvements == len(saves)
    assert not saves and outcome.frames == source


def test_yellow_only_on_tty(capsys, monkeypatch):
    monkeypatch.setattr('sys.stdout.isatty', lambda: True)
    _print_temporary_line('temporary', color=True)
    assert capsys.readouterr().out == '\x1b[33mtemporary\x1b[0m\n'
    _print_temporary_line('plain', color=False)
    assert capsys.readouterr().out == 'plain\n'
    monkeypatch.setattr('sys.stdout.isatty', lambda: False)
    _print_temporary_line('redirect', color=True)
    assert capsys.readouterr().out == 'redirect\n'


def test_temporary_line_uses_physical_values_not_negative_internal_rank():
    level, source, _ = _baseline()
    goal = EndpointGoal(18, 'earliest-arrival',
                        target_region=(0., 2000., 0., 2000.),
                        secondary_objective='min-y')
    evaluator = EndpointEvaluator(level, goal)
    real = evaluator.evaluate(source)
    old = replace(real, frame=832, score=-832, y=91.5,
                  secondary_value=91.5, secondary_score=-91.5)
    new = replace(real, frame=832, score=-832, y=90.06704168647623,
                  secondary_value=90.06704168647623,
                  secondary_score=-90.06704168647623)
    text = _stage_improvement_text(goal, old, new)
    assert text.count('frame 832') == 1
    assert 'position (' in text
    assert 'min-y 91.5 -> 90.0670417' in text
    assert 'rank' not in text and '-90.0670417' not in text
    assert 'score -832' not in text


def test_changed_frame_and_non_earliest_metric_are_readable():
    level, source, _ = _baseline()
    goal = EndpointGoal(10, 'min-x')
    evaluation = EndpointEvaluator(level, goal).evaluate(source)
    old = replace(evaluation, frame=833, x=420.0, score=-420.0)
    new = replace(evaluation, frame=832, x=419.5, score=-419.5)
    text = _stage_improvement_text(goal, old, new)
    assert 'frame 833 -> 832' in text
    assert 'min-x 420 -> 419.5' in text
    assert 'rank' not in text
