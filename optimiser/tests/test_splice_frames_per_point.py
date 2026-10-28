"""Frame-proportional random waypoint count and CLI/TOML wiring."""
from dataclasses import replace
import random

import pytest

from nv14_cli import parse_arguments
from nv14_random_splice import RandomSpliceConfig, choose_waypoints
from tests.test_random_splice import _baseline


def _reference_of_length(n):
    _level, _frames, reference = _baseline()
    point = reference.point(0)
    trace = tuple(replace(point, tick=i, x=float(i), y=110.)
                  for i in range(n + 2))
    return replace(reference, trace=trace, finish_tick=n)


@pytest.mark.parametrize('length,expected', [
    (29, 1), (100, 1), (149, 1), (150, 2), (250, 3),
    (314, 3), (350, 4), (466, 5),
])
def test_frame_proportional_waypoints(length, expected):
    reference = _reference_of_length(length)
    config = RandomSpliceConfig(points=19, frames_per_point=100)
    first = choose_waypoints(reference, config, random.Random(42))
    second = choose_waypoints(reference, config, random.Random(42))
    assert first == second
    assert len(first) == expected
    assert len({point.frame for point in first}) == expected
    assert all(2 <= point.frame <= length - 2 for point in first)


def test_setting_new_ratio_changes_counts_without_changing_legacy_count():
    reference = _reference_of_length(314)
    assert len(choose_waypoints(reference, RandomSpliceConfig(points=6), random.Random(1))) == 6
    assert len(choose_waypoints(reference, RandomSpliceConfig(
        points=6, frames_per_point=50), random.Random(1))) == 6
    assert len(choose_waypoints(_reference_of_length(100), RandomSpliceConfig(
        points=6, frames_per_point=100), random.Random(1))) == 1


def test_ratio_counts_only_editable_endpoint_interval():
    reference = _reference_of_length(466)
    waypoints = choose_waypoints(reference, RandomSpliceConfig(frames_per_point=100),
                                 random.Random(1), min_frame=150, max_frame=249)
    assert len(waypoints) == 1
    assert all(150 <= waypoint.frame <= 249 for waypoint in waypoints)


def test_cli_and_toml_and_default(tmp_path):
    base = parse_arguments(['auto', 'source.txt', '--auto-random-splice'])
    assert base.auto_splice_frames_per_point is None
    parsed = parse_arguments(['auto', 'source.txt', '--auto-random-splice',
                              '--auto-splice-frames-per-point', '100'])
    assert parsed.auto_splice_frames_per_point == 100
    path = tmp_path / 'settings.toml'
    path.write_text('[auto]\nrandom-splice = true\nsplice-frames-per-point = 125\n')
    parsed = parse_arguments(['auto', 'source.txt', '--config', str(path)])
    assert parsed.auto_splice_frames_per_point == 125
    parsed = parse_arguments(['auto', 'source.txt', '--config', str(path),
                              '--auto-splice-frames-per-point', '80'])
    assert parsed.auto_splice_frames_per_point == 80


def test_rejected_without_random_splice_and_bad_values():
    with pytest.raises(SystemExit, match='require --auto-random-splice'):
        parse_arguments(['auto', 'source.txt', '--auto-splice-frames-per-point', '100'])
    with pytest.raises(SystemExit):
        parse_arguments(['auto', 'source.txt', '--auto-random-splice',
                         '--auto-splice-frames-per-point', '0'])
    for value in (0, -1, 1.5, True):
        with pytest.raises(ValueError, match='frames_per_point'):
            RandomSpliceConfig(frames_per_point=value)
    with pytest.raises(ValueError, match='alternative spacing modes'):
        RandomSpliceConfig(frames_per_point=100, distance=20)
