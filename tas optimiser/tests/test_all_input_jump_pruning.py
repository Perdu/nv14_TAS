from pathlib import Path

from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    PlayerState,
    parse_level_string,
)
from nv14_replay import decode_complex_replay, parse_combined_level_replay
from optimize_replay import (
    AxisWindow,
    _search_all_input_frames,
    evaluate,
    optimise_local_windows,
    objective_function,
)


def open_air_level():
    return parse_level_string("0" * (31 * 23) + "|5^100,100")


def test_all_input_dfs_prunes_inactive_fresh_jump_subtrees() -> None:
    level = open_air_level()
    frames = [InputFrame(), InputFrame()]
    objective = objective_function("max-x")
    incumbent = evaluate(level, frames, 1, objective)

    best_slice, best_eval, stats = _search_all_input_frames(
        level,
        frames,
        prefix_state=level.initial_state(),
        window_frames=(0, 1),
        target_frame=1,
        objective=objective,
        incumbent_slice=frames,
        incumbent_eval=incumbent,
        x_window=None,
        y_window=None,
    )

    # In free air, every fresh jump press is inactive. A two-frame raw search
    # has 6^2=36 leaves; pruning reduces this to the 3^2 direction choices.
    assert stats.evaluated_leaves == 9
    assert stats.inactive_jump_prunes == 12
    assert all(not frame.jump for frame in best_slice)
    assert best_eval.score > incumbent.score


def test_all_input_dfs_keeps_failed_prehold_before_fixed_held_jump() -> None:
    level = open_air_level()
    frames = [InputFrame(), InputFrame(jump=True)]
    objective = objective_function("max-x")
    incumbent = evaluate(level, frames, 1, objective)

    _best_slice, _best_eval, stats = _search_all_input_frames(
        level,
        frames,
        prefix_state=level.initial_state(),
        window_frames=(0,),
        target_frame=1,
        objective=objective,
        incumbent_slice=(frames[0],),
        incumbent_eval=incumbent,
        x_window=None,
        y_window=None,
    )

    # Frame 0's failed fresh press changes only edge history, but frame 1 is a
    # fixed held-jump input. Keep all three pre-hold branches so they can
    # suppress the next rising edge if that becomes useful on another route.
    assert stats.evaluated_leaves == 6
    assert stats.inactive_jump_prunes == 0


def test_all_input_dfs_keeps_jump_hold_when_it_changes_jump_state() -> None:
    level = open_air_level()
    frames = [InputFrame()]
    objective = objective_function("max-x")
    prefix = level.initial_state()
    prefix.player.state = PlayerState.JUMPING
    prefix.player.g = prefix.player.jump_grav
    prefix.player.previous_jump_held = False
    incumbent = evaluate(level, frames, 0, objective)

    _best_slice, _best_eval, stats = _search_all_input_frames(
        level,
        frames,
        prefix_state=prefix,
        window_frames=(0,),
        target_frame=0,
        objective=objective,
        incumbent_slice=(frames[0],),
        incumbent_eval=incumbent,
        x_window=None,
        y_window=None,
    )

    # jump=True does not call Player.jump() here, but it keeps an existing jump
    # held while jump=False ends it. The state comparison must therefore retain
    # these branches rather than treating them as inactive presses.
    assert stats.evaluated_leaves == 6
    assert stats.inactive_jump_prunes == 0


def test_all_input_dfs_exactly_steps_fresh_jump_with_distant_launchpad() -> None:
    """An unsafe prediction must not turn a valid grounded press into neutral."""
    tiles = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    # Tile centre=(132,156), so a player at y=134 is supported on its top.
    tiles[4 * APP_NUM_GRIDROWS + 5] = "1"
    # This pad is deliberately far from the player. Its existence disables
    # the release-branch predictor, but it must not disable fresh jump input.
    level = parse_level_string("".join(tiles) + "|5^132,134!2^600,500,-1,0")
    frames = [InputFrame()]

    # Prefer a vertical jump while making the no-horizontal-input held frame
    # the unique winner, so it can be compared with independent exact replay.
    def objective(state):
        player = state.player
        return -player.pos.y - abs(player.pos.x - player.oldpos.x)

    incumbent = evaluate(level, frames, 0, objective)
    direct_held = evaluate(level, [InputFrame(jump=True)], 0, objective)
    assert direct_held.state.player.jump_events == 1
    assert direct_held.score > incumbent.score

    best_slice, best_eval, stats = _search_all_input_frames(
        level,
        frames,
        prefix_state=level.initial_state(),
        window_frames=(0,),
        target_frame=0,
        objective=objective,
        incumbent_slice=frames,
        incumbent_eval=incumbent,
        x_window=None,
        y_window=None,
    )

    # Do not rely on serial/parallel agreement: compare the selected branch
    # with direct, exact held-input evaluation.
    assert best_slice == [InputFrame(jump=True)]
    assert best_eval.score == direct_held.score
    assert best_eval.state.state_key() == direct_held.state.state_key()
    assert stats.evaluated_leaves == 6
    assert stats.inactive_jump_prunes == 0


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


def test_all_input_source_skip_respects_explicit_jump_trigger_bits() -> None:
    # The source held input deliberately suppresses its trigger.  The all-input
    # candidate has the same held bits but derives a fresh trigger, so it must
    # remain a changed candidate rather than being mistaken for the incumbent
    # by the unchanged-suffix fast path.
    tiles = list("0" * (31 * 23))
    tiles[4 * APP_NUM_GRIDROWS + 5] = "1"
    level = parse_level_string("".join(tiles) + "|5^132,134")
    frames = [InputFrame(jump=True, jump_trigger=False), InputFrame()]
    objective = objective_function("min-y")
    x_window = AxisWindow(131.99, 132.01)
    baseline = evaluate(
        level,
        frames,
        1,
        objective,
        x_window=x_window,
    )

    best_slice, result, _stats = _search_all_input_frames(
        level,
        frames,
        prefix_state=level.initial_state(),
        window_frames=(0,),
        target_frame=1,
        objective=objective,
        incumbent_slice=frames[:1],
        incumbent_eval=baseline,
        x_window=x_window,
        y_window=None,
    )

    assert best_slice == [InputFrame(jump=True)]
    assert result.score > baseline.score


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
