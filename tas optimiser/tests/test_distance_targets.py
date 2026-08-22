import pytest

from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    parse_level_string,
)
from optimize_replay import (
    format_level_objects,
    objective_function,
    optimise_local_windows,
    resolve_target_object,
    target_from_point,
)


def make_level(objects: str):
    map_string = "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    return parse_level_string(f"{map_string}|5^100,100!{objects}")


def test_unique_exit_defaults_to_door_anchor() -> None:
    level = make_level("11^200,120,180,96")
    target = resolve_target_object(level, "exit")
    assert len(target.targets) == 1
    assert target.targets[0].label == "exit:0.door"
    assert (target.targets[0].x, target.targets[0].y) == (200.0, 120.0)


def test_exit_switch_and_switch_pseudotype_match() -> None:
    level = make_level("11^200,120,180,96!11^300,240,288,216")
    exit_switch = resolve_target_object(level, "exit:1.switch").targets[0]
    switch = resolve_target_object(level, "switch:1").targets[0]
    assert (exit_switch.x, exit_switch.y) == (288.0, 216.0)
    assert (switch.x, switch.y) == (exit_switch.x, exit_switch.y)


def test_bare_multiple_type_is_rejected_but_any_is_explicit() -> None:
    level = make_level("0^120,100!0^140,100")
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_target_object(level, "gold")
    target = resolve_target_object(level, "gold:any")
    assert [item.label for item in target.targets] == ["gold:0.center", "gold:1.center"]


def test_min_distance_scores_nearest_target_by_negative_squared_distance() -> None:
    level = make_level("0^120,100!0^150,100")
    state = level.initial_state()
    target = resolve_target_object(level, "gold:any")
    score = objective_function("min-distance", target)(state)
    assert score == -(20.0**2)


def test_target_point_uses_same_metric() -> None:
    level = make_level("0^120,100")
    state = level.initial_state()
    target = target_from_point((103.0, 104.0))
    assert objective_function("min-distance", target)(state) == -25.0


def test_parallel_local_window_reconstructs_distance_objective() -> None:
    level = make_level("0^160,100")
    frames = [InputFrame() for _ in range(6)]
    target = target_from_point((150.0, 100.0))
    kwargs = dict(
        target_frame=5,
        range_start=0,
        range_end=3,
        objective_name="min-distance",
        objective_target=target,
        window_size=2,
        passes=1,
        local_inputs="direction",
        progress=None,
    )

    serial, serial_result = optimise_local_windows(
        level, frames, workers=1, **kwargs
    )
    parallel, parallel_result = optimise_local_windows(
        level, frames, workers=3, **kwargs
    )

    assert parallel == serial
    assert parallel_result.score == serial_result.score
    assert parallel_result.state.state_key() == serial_result.state.state_key()


def test_list_objects_exposes_stable_indices_and_exit_switch_alias() -> None:
    level = make_level("0^120,100!0^140,100!11^200,120,180,96")
    listing = format_level_objects(level)
    assert "gold:0  center=(120, 100)" in listing
    assert "gold:1  center=(140, 100)" in listing
    assert "exit:0  door=(200, 120)  switch=(180, 96)" in listing
    assert "switch:0" in listing
