"""Frame-proportional, complexity-boundary and physics-informed splicing."""
from dataclasses import replace
import random

import pytest

from nv14_auto import RouteControlEvent
from nv14_cli import parse_arguments
from nv14_engine import InputFrame
from nv14_random_splice import (
    RandomSpliceConfig, Waypoint, _complexity_regions, _physics_event_tick, _goal,
    choose_waypoints, optimise_random_splices,
)
from tests.test_random_splice import _baseline


def _long_reference(length=250):
    _, _, reference = _baseline()
    point = reference.point(0)
    trace = tuple(replace(point, tick=i, x=float(i), y=110.)
                  for i in range(length + 2))
    return replace(reference, trace=trace, finish_tick=length), trace


def test_frames_per_point_scales_with_source_length_and_is_reproducible():
    reference, _ = _long_reference(250)
    cfg = RandomSpliceConfig(points=19, frames_per_point=100)
    first = choose_waypoints(reference, cfg, random.Random(12))
    again = choose_waypoints(reference, cfg, random.Random(12))
    assert first == again
    assert len(first) == 3  # 250/100 rounded half up
    assert len({p.frame for p in first}) == 3
    assert len(choose_waypoints(reference, replace(cfg, frames_per_point=50),
                                random.Random(12))) == 5


def test_complexity_splice_surrounds_an_action_burst():
    reference, trace = _long_reference(170)
    frames = [InputFrame(right=True) for _ in range(170)]
    frames[80] = InputFrame(right=True, jump=True)
    frames[82] = InputFrame(right=True)
    frames[84] = InputFrame(left=True)
    frames[85] = InputFrame(left=True, jump=True)
    frames[86] = InputFrame(left=True, jump=True)
    frames[87] = InputFrame(left=True)
    frames[88] = InputFrame(right=True)
    regions = _complexity_regions(frames, reference, 168)
    assert any(a <= 80 and b >= 88 for a, b, _ in regions)
    chosen = choose_waypoints(
        reference, RandomSpliceConfig(mode="complexity", points=2),
        random.Random(2), frames=frames)
    assert len(chosen) == 2
    assert chosen[0].frame < 80
    assert chosen[1].frame > 88


def test_complexity_still_has_exact_count_without_action_changes():
    reference, _ = _long_reference(180)
    frames = [InputFrame(right=True)] * 180
    chosen = choose_waypoints(reference, RandomSpliceConfig(
        mode="complexity", frames_per_point=30), random.Random(7), frames=frames)
    assert len(chosen) == 6


def test_physics_interaction_selection_switch_never_randomly_skipped():
    reference, trace = _long_reference(120)
    updated = list(trace)
    updated[29] = replace(updated[29], near_wall=True, in_air=True)
    updated[30] = replace(updated[30], near_wall=True, in_air=True)
    updated[79] = replace(updated[79], in_air=True)
    updated[80] = replace(updated[80], in_air=False)
    reference = replace(reference, trace=tuple(updated), successful_jumps=(30,),
                        route_control_events=(RouteControlEvent("exit", 0, 50),))
    cfg = RandomSpliceConfig(mode="physics", points=3, physics_skip_probability=0)
    all_events = choose_waypoints(reference, cfg, random.Random(1))
    assert {w.kind for w in all_events} == {"switch", "walljump", "landing"}
    switch = next(w for w in all_events if w.kind == "switch")
    assert switch.frame == 50 and switch.mandatory and switch.target_index == 0
    assert switch.direction == 1  # next landing to the right
    skipped = choose_waypoints(reference, replace(cfg, physics_skip_probability=1),
                               random.Random(1))
    assert any(w.kind == "switch" and w.mandatory for w in skipped)
    assert not any(w.kind in ("walljump", "landing") for w in skipped)
    assert len(skipped) == 3  # budget filled with path anchors


def test_physics_target_must_really_land_or_walljump():
    reference, trace = _long_reference(100)
    updated = list(trace)
    updated[29] = replace(updated[29], near_wall=True, in_air=True)
    updated[30] = replace(updated[30], near_wall=True, in_air=True)
    updated[79] = replace(updated[79], in_air=True)
    updated[80] = replace(updated[80], in_air=False)
    reference = replace(reference, trace=tuple(updated), successful_jumps=(30,))
    wall = Waypoint(30, 30.0, 110.0, kind="walljump")
    land = Waypoint(80, 80.0, 110.0, kind="landing")
    assert _physics_event_tick(reference, wall, 0, 45, 12) == 30
    assert _physics_event_tick(reference, land, 0, 90, 12) == 80
    lost = replace(reference, successful_jumps=(), trace=tuple(
        replace(item, in_air=False, near_wall=False) for item in updated))
    assert _physics_event_tick(lost, wall, 0, 45, 12) is None
    assert _physics_event_tick(lost, land, 0, 90, 12) is None


def test_physics_switch_later_in_replay_is_targeted_and_preserved():
    from nv14_auto import evaluate_replay_with_sentinel
    from nv14_engine import parse_level_string
    from tests.test_auto import _running_exit_level
    base_level = _running_exit_level()
    level = parse_level_string(base_level.source_level_string.replace(
        "!11^140,134,60,134", "!11^140,134,85,134"))
    frames = tuple(InputFrame(right=True) for _ in range(29))
    reference = evaluate_replay_with_sentinel(level, frames)
    assert reference.finish_tick == 29
    assert reference.route_control_events[0].tick == 11
    cfg = RandomSpliceConfig(mode="physics", points=1,
                             physics_skip_probability=1, iterations=8,
                             repair_iterations=8, frontier=0, rounds=1, seed=17)
    points = choose_waypoints(reference, cfg, random.Random(cfg.seed),
                              frames=frames, level=level)
    assert len(points) == 1 and points[0].kind == "switch"
    assert points[0].frame == 11
    result = optimise_random_splices(level, frames, cfg)
    checked = evaluate_replay_with_sentinel(level, result.frames)
    assert checked.valid and checked.finish_tick == len(result.frames)
    assert {(e.kind, e.index) for e in reference.route_control_events} <= {
        (e.kind, e.index) for e in checked.route_control_events}


def test_mandatory_switches_can_raise_physics_point_budget():
    reference, _ = _long_reference(120)
    reference = replace(reference, route_control_events=tuple(
        RouteControlEvent("exit", n, tick) for n, tick in enumerate((20, 40, 60))))
    cfg = RandomSpliceConfig(mode="physics", points=1, physics_skip_probability=1)
    chosen = choose_waypoints(reference, cfg, random.Random(9))
    assert [w.frame for w in chosen] == [20, 40, 60]
    assert all(w.mandatory for w in chosen)


def test_switch_uses_real_earliest_interaction_and_post_touch_direction():
    level, frames, _ = _baseline()
    switch = Waypoint(10, 60, 134, mandatory=True,
                      kind="switch", target_index=0, direction=-1)
    goal = _goal(level, frames, switch, RandomSpliceConfig(mode="physics"),
                 deadline=10, start=0)
    assert goal.objective == "earliest-interaction"
    assert goal.interaction_target.alternatives[0].kind == "exit-switch"
    assert goal.secondary_objective == "min-vx"
    walljump = replace(switch, mandatory=False, kind="walljump", target_index=None)
    jump_goal = _goal(level, frames, walljump, RandomSpliceConfig(mode="physics"),
                      deadline=10, start=2)
    assert jump_goal.objective == "earliest-arrival"
    assert jump_goal.require_jump_region is not None
    assert jump_goal.require_jump_frames == (2, 10)


def test_modes_run_through_same_verified_completion_pipeline():
    level, frames, original = _baseline()
    for mode in ("complexity", "physics"):
        result = optimise_random_splices(level, frames, RandomSpliceConfig(
            mode=mode, points=2, rounds=1, iterations=8,
            repair_iterations=8, frontier=0, seed=19))
        assert result.attempts >= 1
        assert len(result.frames) <= len(frames)
        from nv14_auto import evaluate_replay_with_sentinel
        finished = evaluate_replay_with_sentinel(level, result.frames)
        assert finished.valid
        assert finished.finish_tick == len(result.frames)
        assert {(e.kind, e.index) for e in original.route_control_events} <= {
            (e.kind, e.index) for e in finished.route_control_events}


def test_cli_toml_array_config_and_overrides(tmp_path):
    path = tmp_path / "physics.toml"
    path.write_text('''[auto]
objective = "speedrun"
random-splice = true
splice-mode = "physics"
splice-frames-per-point = 100
splice-interactions = ["switch", "walljump", "landing", "bounceblock"]
splice-skip-probability = 0.5
''')
    args = parse_arguments(["auto", "source.txt", "--config", str(path),
                            "--output", str(tmp_path / "out.txt")])
    assert args.auto_splice_mode == "physics"
    assert args.auto_splice_frames_per_point == 100
    assert args.auto_splice_interactions == ("switch", "walljump", "landing", "bounceblock")
    assert args.auto_splice_skip_probability == 0.5
    args2 = parse_arguments(["auto", "source.txt", "--auto-random-splice",
                             "--auto-splice-mode", "complexity",
                             "--auto-splice-interactions", "switch,landing"])
    assert args2.auto_splice_interactions == ("switch", "landing")


@pytest.mark.parametrize("kwargs", [
    {"frames_per_point": 0}, {"frames_per_point": 1.5},
    {"mode": "neural"}, {"physics_interactions": ("switch", "bogus")},
    {"physics_interactions": ("switch", "switch")},
    {"physics_skip_probability": -0.01}, {"physics_skip_probability": 1.01},
])
def test_invalid_new_options(kwargs):
    with pytest.raises(ValueError):
        RandomSpliceConfig(**kwargs)
