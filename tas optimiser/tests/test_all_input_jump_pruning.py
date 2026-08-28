from pathlib import Path

from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    parse_level_string,
)
from nv14_replay import decode_complex_replay, parse_combined_level_replay
from optimize_replay import (
    evaluate,
    optimise_local_windows,
    objective_function,
    target_from_point,
)


def open_air_level():
    return parse_level_string("0" * (31 * 23) + "|5^100,100")


def _search_counter(logs: list[str], name: str) -> int:
    search_line = next(
        line for line in logs if line.startswith("frames ") and " search: " in line
    )
    return int(search_line.split(f"{name}=", 1)[1].split(",", 1)[0])


def _grounded_level(*, extra_objects: str = ""):
    tiles = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for tile_x in range(APP_NUM_GRIDCOLS):
        tiles[tile_x * APP_NUM_GRIDROWS + 5] = "1"
    objects = "|5^132,134"
    if extra_objects:
        objects += "!" + extra_objects
    return parse_level_string("".join(tiles) + objects)


def test_all_input_native_search_prunes_inactive_fresh_jump_subtrees() -> None:
    level = open_air_level()
    frames = [InputFrame(), InputFrame()]
    logs: list[str] = []

    optimised, result = optimise_local_windows(
        level,
        frames,
        target_frame=1,
        range_start=0,
        range_end=1,
        objective_name="max-x",
        window_size=2,
        passes=1,
        local_inputs="all",
        workers=1,
        progress=logs.append,
    )

    # In free air, every fresh jump press is inactive. A two-frame raw search
    # has 6^2=36 leaves; pruning reduces this to the 3^2 direction choices.
    assert _search_counter(logs, "leaves") == 9
    assert _search_counter(logs, "inactive-jump") == 12
    assert all(not frame.jump for frame in optimised)
    assert result.score > 100.0


def test_all_input_native_search_keeps_failed_prehold_before_fixed_held_jump() -> None:
    level = open_air_level()
    frames = [InputFrame(), InputFrame(jump=True)]
    logs: list[str] = []

    optimise_local_windows(
        level,
        frames,
        target_frame=1,
        range_start=0,
        range_end=0,
        objective_name="max-x",
        window_size=1,
        passes=1,
        local_inputs="all",
        workers=1,
        progress=logs.append,
    )

    # Frame 0's failed fresh press changes only edge history, but frame 1 is a
    # fixed held-jump input. Keep all three pre-hold branches so they can
    # suppress the next rising edge if that becomes useful on another route.
    assert _search_counter(logs, "leaves") == 6
    assert _search_counter(logs, "inactive-jump") == 0


def test_all_input_native_search_keeps_jump_hold_when_it_changes_jump_state() -> None:
    level = _grounded_level()
    frames = [InputFrame(jump=True), InputFrame(), InputFrame()]
    logs: list[str] = []

    optimised, result = optimise_local_windows(
        level,
        frames,
        target_frame=2,
        range_start=1,
        range_end=1,
        objective_name="min-distance",
        objective_target=target_from_point((132.0, 110.0)),
        window_size=1,
        passes=1,
        local_inputs="all",
        workers=1,
        progress=logs.append,
    )

    # jump=True does not call Player.jump() here, but it keeps an existing jump
    # held while jump=False ends it. The state comparison must therefore retain
    # these branches rather than treating them as inactive presses.
    assert optimised[1].jump
    assert result.state.player.jump_events == 1
    assert _search_counter(logs, "leaves") == 6
    assert _search_counter(logs, "inactive-jump") == 0


def test_all_input_native_search_exactly_steps_fresh_jump_with_distant_launchpad() -> None:
    """An unsafe prediction must not turn a valid grounded press into neutral."""
    # This pad is deliberately far from the player. Its existence disables
    # the release-branch predictor, but it must not disable fresh jump input.
    level = _grounded_level(extra_objects="2^600,500,-1,0")
    frames = [InputFrame(), InputFrame()]
    target = target_from_point((132.0, 120.0))
    direct_held = evaluate(
        level,
        [InputFrame(jump=True), InputFrame()],
        1,
        objective_function("min-distance", target),
    )
    logs: list[str] = []

    optimised, result = optimise_local_windows(
        level,
        frames,
        target_frame=1,
        range_start=0,
        range_end=0,
        objective_name="min-distance",
        objective_target=target,
        window_size=1,
        passes=1,
        local_inputs="all",
        workers=1,
        python_resimulate=True,
        progress=logs.append,
    )

    # Do not rely on serial/parallel agreement: compare the selected branch
    # with direct, exact held-input evaluation.
    assert optimised[0] == InputFrame(jump=True)
    assert result.score == direct_held.score
    assert result.state.state_key() == direct_held.state.state_key()
    assert _search_counter(logs, "leaves") == 6
    assert _search_counter(logs, "inactive-jump") == 0


def test_all_input_terminal_suffix_does_not_consume_held_sibling() -> None:
    """A returned local result must be the exact state of its returned inputs."""
    source = Path(__file__).with_name("example_motherlode.txt")
    combined = parse_combined_level_replay(source.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string)
    objective = objective_function("max-x")

    kwargs = dict(
        target_frame=71,
        range_start=0,
        range_end=71,
        objective_name="max-x",
        window_size=3,
        passes=1,
        local_inputs="all",
        python_resimulate=True,
        progress=None,
    )
    serial, serial_reported = optimise_local_windows(
        level,
        replay.frames,
        workers=1,
        **kwargs,
    )
    optimised, reported = optimise_local_windows(
        level,
        replay.frames,
        workers=2,
        **kwargs,
    )
    direct = evaluate(level, optimised, 71, objective)

    assert reported.score == serial_reported.score
    assert reported.state.state_key() == serial_reported.state.state_key()
    assert optimised == serial
    assert reported.score == direct.score
    assert reported.state.state_key() == direct.state.state_key()


def test_parallel_all_input_keeps_launchpad_exact_step_fallback() -> None:
    level = parse_level_string(
        "0" * (31 * 23) + "|5^100,100!2^100,100,-1,0"
    )
    frames = [InputFrame() for _ in range(6)]
    kwargs = dict(
        target_frame=5,
        range_start=0,
        range_end=3,
        objective_name="max-x",
        window_size=2,
        passes=1,
        local_inputs="all",
        window_order="forward",
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
