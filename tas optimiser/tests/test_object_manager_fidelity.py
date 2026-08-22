from nv14_engine import (
    BounceBlock,
    GRIDREF_OBJECT,
    InputFrame,
    ObjectGridState,
    StaticColliderKind,
    _grid_cell_bit,
    object_grid_ref,
    parse_level_string,
)


EMPTY_MAP = "0" * (31 * 23)


def level_string(*objects: str) -> str:
    return EMPTY_MAP + "|" + "!".join(objects)


def _expected_occupancy_mask(grid: ObjectGridState) -> int:
    mask = 0
    for cell, refs in grid.cells.items():
        if refs:
            mask |= _grid_cell_bit(cell)
    return mask


def _expected_grid_state_key(grid: ObjectGridState) -> tuple:
    return tuple(
        (cell, tuple(refs))
        for cell, refs in sorted(grid.cells.items())
        if refs
    )


def test_object_grid_occupancy_mask_tracks_public_construction_and_mutation():
    static_ref = (1, int(StaticColliderKind.GOLD), 0)
    grid = ObjectGridState(
        cells={(2, 3): [static_ref]},
        membership={static_ref: (2, 3)},
    )
    assert grid.occupancy_mask == _expected_occupancy_mask(grid)

    object_ref = object_grid_ref(0)
    grid.add(object_ref, (2, 3))
    assert grid.occupancy_mask == _expected_occupancy_mask(grid)

    # Removing one of two same-cell entries must retain the occupied bit.
    grid.remove(static_ref)
    assert grid.occupancy_mask == _expected_occupancy_mask(grid)
    assert grid.occupancy_mask != 0

    # The object-specialized move updates both the linked grid and its mask.
    grid.moved_object_xy(0, object_ref, 4, 5)
    assert grid.occupancy_mask == _expected_occupancy_mask(grid)

    # Out-of-range cells remain available through the public dictionary while
    # intentionally contributing no bit to cached in-grid neighbourhoods.
    grid.moved_object_xy(0, object_ref, 40, 40)
    assert grid.occupancy_mask == _expected_occupancy_mask(grid) == 0

    clone = grid.clone()
    assert clone.occupancy_mask == _expected_occupancy_mask(clone)
    assert clone == grid


def test_object_grid_state_key_cache_tracks_all_mutations():
    first = object_grid_ref(0)
    second = object_grid_ref(1)
    grid = ObjectGridState()

    assert grid.state_key() == _expected_grid_state_key(grid)

    grid.add(first, (2, 3))
    assert grid.state_key() == _expected_grid_state_key(grid)

    # Re-adding an existing ref changes linked-list order and must invalidate
    # the cached key even when the destination cell is unchanged.
    grid.add(second, (2, 3))
    grid.add(first, (2, 3))
    assert grid.state_key() == _expected_grid_state_key(grid)

    grid.remove(second)
    assert grid.state_key() == _expected_grid_state_key(grid)

    grid.moved_object_xy(0, first, 4, 5)
    assert grid.state_key() == _expected_grid_state_key(grid)


def test_object_grid_clone_detaches_only_when_a_branch_mutates():
    first = object_grid_ref(0)
    second = object_grid_ref(1)
    grid = ObjectGridState()
    grid.add(first, (2, 3))
    grid.add(second, (4, 5))
    clone = grid.clone()

    clone.remove(first)
    assert first in grid.membership
    assert first not in clone.membership
    assert grid.state_key() != clone.state_key()

    grid.add(first, (6, 7))
    assert grid.membership[first] == (6, 7)
    assert first not in clone.membership


def test_thinker_self_removal_advances_twice_like_source_tick():
    level = parse_level_string(
        level_string(
            "5^300,300",
            "1^48,48",
            "1^72,48",
            "1^96,48",
        )
    )
    state = level.initial_state()
    blocks = {obj.load_index: obj for obj in state.objects if isinstance(obj, BounceBlock)}

    # A -> B -> C with A current. A's Think() sleeps/removes itself.
    state.thinker_uids = [1, 2, 3]
    state.update_uids = [1, 2, 3]
    blocks[1].asleep = False
    blocks[1].sleep_timer = blocks[1].sleep_threshold + 1
    state.think_timer = state.think_rate + 1

    state._tick_thinker(level.tiles)

    # EndThink(A) first makes B current, then ObjectManager.Tick's unconditional
    # curThinker = curThinker.next advances once more to C.
    assert state.thinker_uids == [3, 2]
    assert 1 not in state.update_uids


def test_trap_door_removal_severs_same_cell_collision_traversal():
    level = parse_level_string(
        level_string(
            "5^60,60",
            "12^60,60",                 # mine inserted first
            "9^60,60,0,1,2,2,0,0,0",   # trap inserted later -> cell head
        )
    )
    state = level.initial_state()
    trap_ref = object_grid_ref(2)
    mine_ref = (1, int(StaticColliderKind.MINE), 0)
    cell = state.grid_state.membership[trap_ref]
    assert state.grid_state.entries(cell)[:2] == (trap_ref, mine_ref)

    state.step(InputFrame(), level.tiles)

    # Trap TestVsPlayer -> RemoveFromGrid(current) -> current.next = null, so the
    # mine behind it is not visited during this cell traversal.
    assert not state.player.dead
    assert trap_ref not in state.grid_state.membership
    assert mine_ref in state.grid_state.membership


def test_bounceblock_position_change_does_not_change_grid_membership_without_moved():
    level = parse_level_string(
        level_string(
            "5^300,300",
            "1^60,60",
        )
    )
    state = level.initial_state()
    block = next(obj for obj in state.objects if isinstance(obj, BounceBlock))
    ref = object_grid_ref(block.load_index)
    original_cell = state.grid_state.membership[ref]

    # BounceBlock.Update/TestVsPlayer never call objects.Moved in the source.
    block.pos.x += 48.0
    block.oldpos.x += 48.0
    block.asleep = False
    state.start_update(block.load_index)
    state.step(InputFrame(), level.tiles)

    assert state.grid_state.membership[ref] == original_cell
    assert int(block.pos.x // level.tiles.tw) != original_cell[0]


def test_general_update_list_includes_non_turrets_and_new_entries_go_to_front():
    level = parse_level_string(
        level_string(
            "5^300,300",
            "8^60,60,1",          # thwomp StartUpdate uid 1
            "6^84,60,2,0,0,0",    # zap drone StartUpdate uid 2
            "3^108,60",            # turret thinker only uid 3
        ),
        simulate_enemies=True,
    )
    state = level.initial_state()

    assert state.update_uids == [2, 1]
    assert state.turret_update_uids == []

    state.start_update(3)
    assert state.update_uids == [3, 2, 1]
    assert state.turret_update_uids == [3]
