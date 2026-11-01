"""Round checkpoints are recoverable, validated, and preserve populations."""
import json
from pathlib import Path

import pytest

from nv14_auto_endpoint import AutoEndpointConfig, optimise_auto_endpoint_campaign
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig, _local_search
from tests.test_random_splice import _baseline


def test_auto_interrupted_after_round_resumes_without_replaying_round_one(tmp_path):
    level, source, _ = _baseline()
    path = tmp_path / 'auto.round.json'
    lines = []
    def interrupt(line):
        lines.append(line)
        if 'round 2/until stagnant: starting' in line:
            raise KeyboardInterrupt
    config = AutoEndpointConfig(iterations=0, seed=13, range_end=10)
    with pytest.raises(KeyboardInterrupt):
        optimise_auto_endpoint_campaign(level, source, EndpointGoal(10,'min-x'),
            config, workers=1, runs=0, stagnation_rounds=2,
            checkpoint_path=path, progress=interrupt)
    assert path.is_file()
    assert json.loads(path.read_text())['payload']['rounds'] == 1
    lines = []
    _, _, used = optimise_auto_endpoint_campaign(
        level, source, EndpointGoal(10,'min-x'), config, workers=1,
        runs=0, stagnation_rounds=2, checkpoint_path=path, resume=True,
        progress=lines.append)
    assert used == 0
    assert any('loaded completed round 1' in line for line in lines)
    assert any('stagnant 2/2' in line for line in lines)
    assert path.with_suffix('.json.prev').exists()
    assert json.loads(path.read_text())['payload']['complete'] is True
    assert not any('round 1/until stagnant: starting' in line for line in lines)


def test_auto_checkpoint_rejects_changed_world_and_corruption(tmp_path):
    level, source, _ = _baseline()
    goal = EndpointGoal(10, 'min-x')
    cfg = AutoEndpointConfig(iterations=0, range_end=10)
    path = tmp_path / 'auto.json'
    optimise_auto_endpoint_campaign(level, source, goal, cfg, workers=1, runs=0,
                                   stagnation_rounds=1, checkpoint_path=path)
    with pytest.raises(ValueError, match='checkpoint.*differs'):
        optimise_auto_endpoint_campaign(level, source, EndpointGoal(10,'max-x'),
            cfg, workers=1, runs=0, stagnation_rounds=1, checkpoint_path=path,
            resume=True)
    document = json.loads(path.read_text())
    document['payload']['rounds'] = 999
    path.write_text(json.dumps(document))
    # The latest snapshot is corrupt, but the older verified snapshot survives.
    seen = []
    optimise_auto_endpoint_campaign(level, source, goal, cfg, workers=1, runs=0,
                                   stagnation_rounds=1, checkpoint_path=path,
                                   resume=True, progress=seen.append)
    assert any('loaded completed round 1' in line for line in seen)
    for candidate in (path, path.with_suffix('.json.prev')):
        candidate.write_text('broken')
    with pytest.raises((ValueError, json.JSONDecodeError), match='Auto round|Expecting|checkpoint'):
        optimise_auto_endpoint_campaign(level, source, goal, cfg, workers=1, runs=0,
                                       stagnation_rounds=1, checkpoint_path=path,
                                       resume=True)


def test_local_round_checkpoint_resume_has_two_snapshots(tmp_path):
    level, source, _ = _baseline()
    path = tmp_path / 'local.round.json'
    config = RandomSpliceConfig(search_backend='local', workers=1, beam=3,
                                iterations=1, frontier=1)
    seen = []
    def interrupt(message):
        seen.append(message)
        if '[local:population] round 2;' in message:
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        _local_search(level, source, EndpointGoal(10,'min-x'), start=0,
                      config=config, iterations=1, rounds=0, stagnation_rounds=3,
                      seed=8, checkpoint_path=path, progress=interrupt)
    assert path.is_file()
    messages = []
    found, evaluations = _local_search(level, source, EndpointGoal(10,'min-x'), start=0,
        config=config, iterations=1, rounds=0, stagnation_rounds=3,
        seed=8, checkpoint_path=path, resume=True, progress=messages.append)
    assert any('round 2;' in m or 'round 3;' in m for m in messages)
    assert path.with_suffix('.json.prev').exists()
