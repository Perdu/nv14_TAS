"""Route-scale Auto operators: preset/array parsing, boundaries, and budget."""
import random

import pytest

from nv14_auto_endpoint import AutoEndpointConfig, _hybrid_proposal
from nv14_cli import parse_arguments
from nv14_engine import InputFrame, parse_level_string, APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS
from nv14_route_mutations import HIGH, LOW, MEDIUM, operators, parse_operators, propose
from tests.test_random_splice import _baseline


def _sequence():
    neutral = InputFrame()
    left = InputFrame(left=True)
    right = InputFrame(right=True)
    jump_right = InputFrame(right=True, jump=True)
    # Has long direction runs, gaps, reversal, two jump presses, and a donor.
    return ((neutral,) * 10 + (right,) * 22 + (neutral,) * 2 +
            (right,) * 18 + (left,) * 3 + (right,) * 18 +
            (jump_right,) * 3 + (right,) * 25 +
            (jump_right,) * 2 + (right,) * 25 + (neutral,) * 10)


def test_presets_and_explicit_names():
    assert operators('low') == LOW
    assert operators('medium') == MEDIUM
    assert operators('high') == HIGH
    assert len(LOW) < len(MEDIUM) < len(HIGH)
    assert parse_operators(['direction-flip', 'gap-repair']) == ('direction-flip', 'gap-repair')
    assert parse_operators('direction-flip,gap-repair') == ('direction-flip', 'gap-repair')
    assert parse_operators('direction-flip') == ('direction-flip',)
    assert AutoEndpointConfig().route_mutations == 'low'
    with pytest.raises(ValueError, match='unknown'):
        parse_operators(['direction-flip', 'nonsense'])
    with pytest.raises(ValueError, match='repeated'):
        parse_operators(['gap-repair', 'gap-repair'])
    assert parse_operators([]) == ()


@pytest.mark.parametrize('operator', HIGH)
def test_structural_operator_never_changes_immutable_prefix_or_suffix(operator):
    source = _sequence()
    donor = source[:30] + (InputFrame(left=True),) * 60 + source[90:]
    level, _, _ = _baseline()
    for seed in range(6):
        result = propose(operator, source, rng=random.Random(seed),
                         start=10, end=len(source)-11, donor=donor, level=level)
        if result is not None:
            assert len(result) == len(source)
            assert result[:10] == source[:10]
            assert result[-10:] == source[-10:]
            assert result != source


def test_direction_flip_reverses_long_run():
    source = _sequence()
    result = propose('direction-flip', source, rng=random.Random(1), start=10, end=90)
    assert result is not None
    assert any(a.right and b.left for a, b in zip(source, result))
    assert sum(a != b for a, b in zip(source, result)) >= 8


def test_gap_repair_preserves_jump_holds():
    source = _sequence()
    result = propose('gap-repair', source, rng=random.Random(1), start=10, end=90)
    assert result is not None
    assert result[32].right and result[33].right
    assert [f.jump for f in result] == [f.jump for f in source]


def test_explicit_list_is_respected_in_auto_proposals(monkeypatch):
    import nv14_auto_endpoint as auto
    from nv14_endpoint import EndpointEvaluator, EndpointGoal

    level, replay, _ = _baseline()
    goal = EndpointGoal(10, 'min-x')
    evaluation = EndpointEvaluator(level, goal).evaluate(replay)
    candidate = auto.AutoEndpointCandidate(replay, evaluation)
    names = []
    def fake_propose(name, parent, *, rng, start, end, donor, level):
        names.append(name)
        return parent[:start] + (InputFrame(left=True),) + parent[start+1:]
    monkeypatch.setattr(auto, 'route_propose', fake_propose)
    config = AutoEndpointConfig(route_mutations=('direction-flip',), iterations=2)
    for i in range(100):
        _hybrid_proposal(candidate, candidate, rng=random.Random(i), config=config,
                         start=2, end=10, level=level)
    assert names and set(names) == {'direction-flip'}


def test_multi_splicer_toml_preset_array_and_cli_precedence(tmp_path):
    base = tmp_path / 'base.toml'
    base.write_text('[auto]\nmutations="high"\n')
    level = tmp_path / 'multi.toml'
    level.write_text('[multi-splicer]\nfiles=["230", "end"]\n'
                     'mutations=["direction-flip", "gap-repair"]\n')
    parsed = parse_arguments(['auto', 'level.ltm', '--config', str(base),
                              '--splice-config', str(level)])
    assert parsed.auto_mutations == ('direction-flip', 'gap-repair')
    overridden = parse_arguments(['auto', 'level.ltm', '--config', str(base),
                                  '--splice-config', str(level),
                                  '--auto-mutations', 'medium'])
    assert overridden.auto_mutations == 'medium'
    assert parse_arguments(['auto', 'level.ltm']).auto_mutations == 'low'
    level.write_text('[multi-splicer]\nmutations=["invalid"]\n')
    with pytest.raises(SystemExit, match='unknown'):
        parse_arguments(['auto', 'level.ltm', '--splice-config', str(level)])


def test_auto_endpoint_budget_unchanged_with_broad_mutations():
    from nv14_auto_endpoint import optimise_auto_endpoint
    from nv14_endpoint import EndpointGoal
    level, replay, _ = _baseline()
    goal = EndpointGoal(10, 'min-x')
    results = []
    for profile in ('low', 'medium', 'high', ('direction-flip',)):
        _, _, n = optimise_auto_endpoint(
            level, replay, goal,
            AutoEndpointConfig(iterations=32, seed=3, range_start=0,
                               range_end=10, route_mutations=profile))
        results.append(n)
    assert all(0 <= n <= 32 for n in results)


def test_auto_round_resume_with_explicit_operator_array(tmp_path):
    # JSON serializes a Python tuple as a list. Both sides of checkpoint
    # identity matching must normalize that representation.
    from nv14_auto_endpoint import optimise_auto_endpoint_campaign
    from nv14_endpoint import EndpointGoal
    level, replay, _ = _baseline()
    goal = EndpointGoal(10, 'min-x')
    cfg = AutoEndpointConfig(iterations=0, range_end=10,
                             route_mutations=('direction-flip', 'gap-repair'))
    path = tmp_path / 'auto.round.json'
    def interrupt(line):
        if 'round 2/until stagnant: starting' in line:
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        optimise_auto_endpoint_campaign(level, replay, goal, cfg, workers=1,
                                        runs=0, stagnation_rounds=2,
                                        checkpoint_path=path, progress=interrupt)
    lines = []
    optimise_auto_endpoint_campaign(level, replay, goal, cfg, workers=1,
                                    runs=0, stagnation_rounds=2,
                                    checkpoint_path=path, resume=True,
                                    progress=lines.append)
    assert any('loaded completed round 1' in line for line in lines)


def test_config_disable_all_new_mutations(tmp_path):
    p = tmp_path / 'level.toml'
    p.write_text('[multi-splicer]\nfiles=["230","end"]\nmutations=[]\n')
    args = parse_arguments(['auto', 'level.ltm', '--splice-config', str(p)])
    assert args.auto_mutations == ()
