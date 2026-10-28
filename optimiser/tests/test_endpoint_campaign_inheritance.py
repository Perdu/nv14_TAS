"""Endpoint Auto survivors, balanced mutation mix and progress reporting."""
from dataclasses import replace
import random

import pytest

import nv14_auto_endpoint as endpoint
from nv14_auto_endpoint import (
    AutoEndpointCandidate, AutoEndpointConfig, _hybrid_proposal,
    _key, optimise_auto_endpoint, optimise_auto_endpoint_campaign,
)
from nv14_cli import parse_arguments
from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame, parse_level_string


def simple_level():
    return parse_level_string("0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + "|5^60,60")


def test_cli_mutation_share_default_and_toml(tmp_path):
    file = tmp_path / "auto.toml"
    file.write_text('[auto]\nendpoint-auto-mutation-share = 0.75\n')
    normal = parse_arguments(['auto', 'run.ltm'])
    assert normal.auto_endpoint_auto_mutation_share == 0.5
    settings = parse_arguments(['auto', 'run.ltm', '--config', str(file)])
    assert settings.auto_endpoint_auto_mutation_share == 0.75
    for invalid in (-0.1, 1.01, float('nan'), float('inf')):
        with pytest.raises(ValueError, match='auto-mutation-share'):
            AutoEndpointConfig(auto_mutation_share=invalid)


def test_mutation_ratio_routes_to_both_actual_operators(monkeypatch):
    level = simple_level()
    source = (InputFrame(),) * 24
    goal = EndpointGoal(target_frame=16, objective='max-x')
    cand = AutoEndpointCandidate(source, EndpointEvaluator(level, goal).evaluate(source))
    calls = {'auto': 0, 'local': 0}

    def auto(frames, **kwargs):
        calls['auto'] += 1
        return frames

    def local(first, second, windows, indices, rng, span):
        calls['local'] += 1
        return first.frames, 'no-op', 8

    monkeypatch.setattr(endpoint, '_proposal', auto)
    monkeypatch.setattr(endpoint, '_population_mutate', local)
    for value, expect in ((0, 'local'), (1, 'auto')):
        calls.update(auto=0, local=0)
        for _ in range(10):
            _hybrid_proposal(cand, cand, rng=random.Random(17),
                             config=AutoEndpointConfig(auto_mutation_share=value),
                             start=4, end=16)
        assert calls[expect] == 10
        assert calls['local' if expect == 'auto' else 'auto'] == 0
    calls.update(auto=0, local=0)
    rng = random.Random(91)
    for _ in range(300):
        _hybrid_proposal(cand, cand, rng=rng,
                         config=AutoEndpointConfig(), start=4, end=16)
    assert calls['auto'] > 100 and calls['local'] > 100


def test_inherited_population_rechecked_and_proposal_budget_is_not_spent():
    level = simple_level()
    source = (InputFrame(),) * 36
    goal = EndpointGoal(target_frame=22, objective='max-x')
    modified = source[:10] + (InputFrame(right=True),) + source[11:]
    previous = AutoEndpointCandidate(modified, EndpointEvaluator(level, goal).evaluate(modified))
    baseline, best, count = optimise_auto_endpoint(
        level, source, goal, AutoEndpointConfig(iterations=0, beam_width=8,
                                               range_start=4, range_end=22),
        initial_population=[previous],
    )
    assert count == 1
    assert best is not None
    assert verify_endpoint(level, best.frames, goal, expected=best.evaluation).feasible
    assert best.evaluation.objective_key <= baseline.evaluation.objective_key


@pytest.mark.parametrize('workers', [1, 2])
def test_campaign_inherits_more_than_global_winner(workers):
    level = simple_level()
    frames = (InputFrame(),) * 40
    # Unreachable target forces the campaign to inherit *infeasible* niches,
    # which previously vanished entirely between rounds.
    goal = EndpointGoal(target_frame=20, objective='earliest-arrival',
                        target_region=(900, 910, 900, 910))
    messages = []
    baseline, best, count = optimise_auto_endpoint_campaign(
        level, frames, goal,
        AutoEndpointConfig(iterations=85, beam_width=12, repair_steps=0,
                           range_end=20, seed=41),
        workers=workers, runs=2, progress=messages.append,
    )
    assert count > 0
    assert not baseline.evaluation.feasible
    assert best is None
    second = [message for message in messages if 'round 2/2: starting' in message]
    assert len(second) == 1
    number = int(second[0].split(' inherited candidates')[0].split('; ')[-1])
    assert number >= 2, second[0]


def test_secondary_reported_for_feasible_baseline_and_progress():
    level = simple_level()
    frames = (InputFrame(),) * 40
    goal = EndpointGoal(target_frame=20, objective='earliest-arrival',
                        target_region=(0, 1000, 0, 1000),
                        secondary_objective='min-x')
    reports = []
    optimise_auto_endpoint_campaign(level, frames, goal,
        AutoEndpointConfig(iterations=20, beam_width=8, repair_steps=0),
        workers=1, runs=1, progress=reports.append)
    assert any('secondary min-x=' in msg for msg in reports if msg.startswith('baseline:'))
    assert any('secondary min-x=' in msg for msg in reports if 'proposals' in msg)
