from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    EID_SOLID,
    EID_OFF,
    EDGE_L,
    EDGE_R,
    InputFrame,
    OBJTYPE_PLAYER,
    OBJTYPE_TESTDOOR,
    TestDoor as DoorObject,
    parse_level_string,
)


def empty_map() -> str:
    return "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)


def level_with_locked_door(*, trigger_x: float, trigger_y: float):
    # The door is the boundary between tile cells (3,3) and (4,3), x=96.
    door = (
        f"{OBJTYPE_TESTDOOR}^{trigger_x},{trigger_y},0,0,3,3,1,0,0"
    )
    player = f"{OBJTYPE_PLAYER}^90,84"
    return parse_level_string(f"{empty_map()}|{door}!{player}")


def get_door(level) -> DoorObject:
    return next(obj for obj in level.objects if isinstance(obj, DoorObject))


def test_locked_door_blocks_its_tile_edge_while_closed() -> None:
    level = level_with_locked_door(trigger_x=60.0, trigger_y=84.0)
    state = level.initial_state()
    door = get_door(level)

    overrides = {}
    get_door_from_state = next(obj for obj in state.objects if isinstance(obj, DoorObject))
    get_door_from_state.write_edge_overrides(overrides)
    assert overrides[(3, 3, EDGE_R)] == EID_SOLID
    assert overrides[(4, 3, EDGE_L)] == EID_SOLID

    state.step(InputFrame(), level.tiles)
    assert state.player.pos.x == 86.0
    assert not get_door_from_state.is_open
    assert not door.is_open


def test_locked_switch_opens_before_tile_collision_on_same_frame() -> None:
    level = level_with_locked_door(trigger_x=90.0, trigger_y=84.0)
    state = level.initial_state()
    door = next(obj for obj in state.objects if isinstance(obj, DoorObject))

    state.step(InputFrame(), level.tiles)

    assert door.is_open
    assert state.player.pos.x == 90.0


def test_door_state_is_independent_between_search_branches() -> None:
    level = level_with_locked_door(trigger_x=90.0, trigger_y=84.0)
    closed_branch = level.initial_state()
    opened_branch = closed_branch.clone()

    opened_branch.step(InputFrame(), level.tiles)
    opened_door = next(obj for obj in opened_branch.objects if isinstance(obj, DoorObject))
    closed_door = next(obj for obj in closed_branch.objects if isinstance(obj, DoorObject))

    assert opened_door.is_open
    assert not closed_door.is_open

    # Move the closed branch's switch out of range and verify that the shared
    # TileMap was not permanently opened by the other branch.
    closed_door.pos.x = 60.0
    closed_branch.step(InputFrame(), level.tiles)
    assert closed_branch.player.pos.x == 86.0


def test_shared_door_edge_uses_source_mutation_order() -> None:
    # This mirrors the unusual arrangement in built-in level 188: a locked
    # door is spawned first and a trap door later on the same tile boundary.
    locked = f"{OBJTYPE_TESTDOOR}^60,84,0,0,3,3,1,0,0"
    trap = f"{OBJTYPE_TESTDOOR}^120,84,0,1,3,3,0,0,0"
    player = f"{OBJTYPE_PLAYER}^40,40"
    level = parse_level_string(f"{empty_map()}|{locked}!{trap}!{player}")
    state = level.initial_state()
    doors = sorted(
        (obj for obj in state.objects if isinstance(obj, DoorObject)),
        key=lambda obj: obj.load_index,
    )
    locked_door, trap_door = doors
    key = (3, 3, EDGE_R)

    # The later trap captures the already-closed edge as its own open state.
    assert trap_door.open_state_front == EID_SOLID
    assert state.edge_overrides[key] == EID_SOLID

    # Opening the locked door writes the original empty edge, then closing the
    # trap later writes solid again. This cannot be represented by merely
    # deriving the edge from the two Boolean is_open values each frame.
    locked_door.open(state.edge_overrides)
    assert state.edge_overrides[key] == EID_OFF
    trap_door.close(state.edge_overrides)
    assert state.edge_overrides[key] == EID_SOLID
