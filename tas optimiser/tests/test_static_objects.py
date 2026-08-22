from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    PlayerState,
    parse_level_string,
)


def empty_map() -> str:
    return "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)


def make_level(objects: str, *, player_x: float = 100.0, player_y: float = 100.0):
    return parse_level_string(f"{empty_map()}|5^{player_x},{player_y}!{objects}")


def stationary_state(level):
    state = level.initial_state()
    state.player.g = 0.0
    return state


def test_gold_is_default_on_and_uses_exact_strict_overlap() -> None:
    touching = make_level("0^116,100")
    state = stationary_state(touching)
    state.step(InputFrame(), touching.tiles)
    assert state.static_state.collected_gold_mask == 0
    assert state.static_state.gold_bonus_ticks == 0

    overlapping = make_level("0^115.999999,100")
    state = stationary_state(overlapping)
    state.step(InputFrame(), overlapping.tiles)
    assert state.static_state.collected_gold_mask == 1
    assert state.static_state.gold_bonus_ticks == 80


def test_gold_removal_stops_only_the_current_cell_traversal() -> None:
    # Both gold pieces occupy the player's current grid cell. The later-loaded
    # one is at the linked-list head, and removing the current node nulls its
    # next pointer in the source. Therefore only one is collected this frame.
    level = make_level("0^100,100!0^100,100")
    state = stationary_state(level)

    state.step(InputFrame(), level.tiles)
    assert state.static_state.collected_gold_mask == 0b10
    assert state.static_state.gold_bonus_ticks == 80

    state.step(InputFrame(), level.tiles)
    assert state.static_state.collected_gold_mask == 0b11
    assert state.static_state.gold_bonus_ticks == 160


def test_mine_is_default_on_and_uses_exact_strict_overlap() -> None:
    touching = make_level("12^114,100")
    state = stationary_state(touching)
    state.step(InputFrame(), touching.tiles)
    assert not state.player.dead
    assert state.static_state.exploded_mine_mask == 0

    overlapping = make_level("12^113.999999,100")
    state = stationary_state(overlapping)
    state.step(InputFrame(), overlapping.tiles)
    assert state.player.dead
    assert state.static_state.exploded_mine_mask == 1


def test_exit_switch_opens_door_and_door_can_complete_later_same_traversal() -> None:
    # Player starts in cell (4,4). The switch is in the current cell and the
    # overlapping door is in right neighbour (5,4), which CollideVsObjects
    # visits later in the same frame. PlayerHitTrigger inserts the door before
    # that neighbour is visited, so the exit can be hit immediately.
    level = make_level("11^121,100,100,100")
    state = stationary_state(level)

    state.step(InputFrame(), level.tiles)

    assert state.static_state.open_exit_mask == 1
    assert state.level_complete
    assert state.player.state == PlayerState.CELEBRATING


def test_cloned_state_sees_exit_door_added_later_in_same_traversal() -> None:
    # SimulationState.clone() always shares the object-grid containers through
    # copy-on-write, independently of whether physics objects themselves use
    # copy-on-write. Opening the switch must detach the grid without leaving
    # the remainder of this collision pass bound to the abandoned dictionary.
    level = make_level("11^121,100,100,100")

    for copy_on_write_objects in (False, True):
        state = stationary_state(level).clone(
            copy_on_write_objects=copy_on_write_objects
        )

        state.step(InputFrame(), level.tiles)

        assert state.static_state.open_exit_mask == 1
        assert state.level_complete
        assert state.player.state == PlayerState.CELEBRATING


def test_exit_door_in_same_cell_is_not_revisited_after_switch_removal() -> None:
    level = make_level("11^101,100,100,100")
    state = stationary_state(level)

    state.step(InputFrame(), level.tiles)
    assert state.static_state.open_exit_mask == 1
    assert not state.level_complete

    state.step(InputFrame(), level.tiles)
    assert state.level_complete
    assert state.player.state == PlayerState.CELEBRATING


def test_closed_exit_door_cannot_complete_level() -> None:
    # Door overlaps the player, but the switch is elsewhere and remains closed.
    level = make_level("11^100,100,200,200")
    state = stationary_state(level)

    state.step(InputFrame(), level.tiles)

    assert state.static_state.open_exit_mask == 0
    assert not state.level_complete


def test_completed_level_is_terminal_on_subsequent_simulation_steps() -> None:
    level = make_level("11^121,100,100,100")
    state = stationary_state(level)
    state.step(InputFrame(), level.tiles)
    completed_pos = (state.player.pos.x, state.player.pos.y)
    completed_oldpos = (state.player.oldpos.x, state.player.oldpos.y)
    completed_frame = state.frame

    state.step(InputFrame(right=True, jump=True), level.tiles)

    assert state.frame == completed_frame + 1
    assert (state.player.pos.x, state.player.pos.y) == completed_pos
    assert (state.player.oldpos.x, state.player.oldpos.y) == completed_oldpos


def test_static_state_clone_is_independent_but_world_is_shared() -> None:
    level = make_level("0^100,100!12^140,100!11^180,100,160,100")
    original = stationary_state(level)
    clone = original.clone()

    assert clone.static_world is original.static_world
    clone.static_state.collected_gold_mask = 1
    clone.static_state.exploded_mine_mask = 1
    clone.static_state.open_exit_mask = 1
    clone.static_state.gold_bonus_ticks = 80

    assert original.static_state.collected_gold_mask == 0
    assert original.static_state.exploded_mine_mask == 0
    assert original.static_state.open_exit_mask == 0
    assert original.static_state.gold_bonus_ticks == 0
    assert clone.state_key() != original.state_key()


def test_static_objects_do_not_enter_mutable_physics_object_list() -> None:
    level = make_level("0^120,100!12^140,100!11^180,100,160,100")

    assert level.objects == []
    assert level.static_world.gold_count == 1
    assert level.static_world.mine_count == 1
    assert level.static_world.exit_count == 1


def test_static_and_dynamic_colliders_share_reverse_load_order() -> None:
    # Gold loads first; the later launchpad is therefore at the source cell-list
    # head. It launches the player left far enough that the gold no longer
    # overlaps, proving the dynamic object was processed before the static one.
    level = make_level("0^115.9,100!2^100,100,-1,0")
    state = stationary_state(level)

    state.step(InputFrame(), level.tiles)

    assert state.player.pos.x < 100.0
    assert state.static_state.collected_gold_mask == 0

    # Reversing load order makes gold the head. Its self-removal stops traversal
    # of this cell, so the launchpad is not reached on the collection frame.
    level = make_level("2^100,100,-1,0!0^115.9,100")
    state = stationary_state(level)

    state.step(InputFrame(), level.tiles)

    assert state.player.pos.x == 100.0
    assert state.static_state.collected_gold_mask == 1


def test_celebrate_ports_physics_relevant_exit_state_and_drag_changes() -> None:
    level = make_level("11^121,100,100,100")
    state = stationary_state(level)
    state.player.state = PlayerState.JUMPING
    state.player.g = state.player.jump_grav

    state.player.celebrate()
    assert state.player.state == PlayerState.CELEBRATING
    assert state.player.g == state.player.norm_grav

    state.player.in_air = False
    state.player._think_celebrate()
    assert state.player.d == state.player.win_drag
    assert not state.player.celeb_was_in_air

    clone = state.player.clone()
    assert clone.d == state.player.win_drag
