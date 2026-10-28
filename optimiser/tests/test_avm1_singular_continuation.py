"""Source-derived continuation for missing AVM1 members and 0/0 arithmetic.

These force the unusual callbacks directly; they do not claim a reachable
ordinary replay at a convex centre. In AVM1, GetMember on undefined returns
undefined and CallMethod on it is a no-op (unlike JavaScript TypeError).
"""
import math
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import nv14_engine as e

ROOT = Path(__file__).resolve().parents[1]


def boxed_level():
    chars = ['0'] * 713
    for i, j in [(3, 2), (3, 4), (2, 3), (4, 3)]:
        chars[(i - 1) * 23 + j - 1] = '1'
    return ''.join(chars) + '|5^300,300!6^84,84,2,0,0,0'


@pytest.mark.parametrize('offsets', [(1, 0), (0, 1), (1, 1), (0, 0)])
def test_convex_forced_zero_normalisation_keeps_ticking(offsets):
    tiles = e.TileMap('0' * 713)
    tile = e.TileCell(4, 4, e.Vec2(108.0, 108.0), tile_id=e.TID_CONVEXPP,
                      ctype=e.CTYPE_CONVEX, signx=1, signy=1)
    player = e.Player.spawn(96.0, 96.0)
    assert tiles._project_circle_convex(40.0, 40.0, *offsets, player, tile) == e.COL_OTHER
    assert math.isnan(player.pos.x) and math.isnan(player.pos.y)
    assert not player.dead
    for _ in range(3):
        player.step(e.InputFrame(), tiles)
        assert not player.dead
        assert math.isnan(player.pos.x) and math.isnan(player.pos.y)
        assert not player.near_wall


@pytest.mark.parametrize('x,y', [(-50., 100.), (850., 100.), (100., -50.),
                                 (100., 650.), (math.nan, math.nan)])
def test_missing_tile_is_no_collision_and_no_artificial_death(x, y):
    tiles = e.TileMap('0' * 713)
    player = e.Player.spawn(100., 100.)
    player.pos.x, player.pos.y = x, y
    player.oldpos = player.pos.copy()
    assert not tiles.query_point(x, y)
    player.step(e.InputFrame(), tiles)
    assert not player.dead
    assert player.cell_i == player.cell_j == e._UNDEFINED_CELL_INDEX


def test_offmap_grid_member_unlinks_and_reenters_without_sparse_cells():
    grid = e.ObjectGridState()
    ref = e.object_grid_ref(0)
    grid.add(ref, (32, 4))
    assert grid.moved_object_xy(0, ref, 33, 4)
    assert grid.cells == {} and grid.occupancy_mask == 0
    assert grid.object_cells[0] == e._UNDEFINED_CELL
    clone = grid.clone()
    assert clone.moved_object_xy(0, ref, 32, 4)
    assert clone.entries((32, 4)) == (ref,)
    assert not grid.cells


def test_boxed_drone_loses_direction_and_does_not_recover_when_unboxed():
    level = e.parse_level_string(boxed_level(), simulate_enemies=True)
    state = level.initial_state()
    drone = state.objects_by_uid[1]
    state.step(e.InputFrame(), level.tiles)
    assert drone.cur_dir is None
    assert (drone.pos.x, drone.pos.y) == (84., 84.)
    # Opening edges cannot recover undefined: RotateAIDir(undefined, rot)
    # produces NaN, so TestEdge matches no cardinal direction.
    edges = {(3, 3, side): e.EID_OFF for side in range(4)}
    drone._update_move(level.tiles, edges)
    assert drone.cur_dir is None
    assert (drone.goal.x, drone.goal.y) == (84., 84.)
    # If another callback changes the goal, Update_Move reads undefined
    # curDirV.x/y and arithmetic produces NaNs, with no thrown exception.
    drone.goal.x = 108.
    drone._update_move(level.tiles, edges)
    assert math.isnan(drone.pos.x) and math.isnan(drone.pos.y)
    assert drone.cell_i == drone.cell_j == e._UNDEFINED_CELL_INDEX


def test_boxed_chaser_can_select_goal_but_setdir_remains_undefined():
    level = e.parse_level_string(boxed_level(), simulate_enemies=True)
    drone = level.initial_state().objects_by_uid[1]
    drone._update_move(level.tiles, {})
    assert drone.cur_dir is None
    drone.is_chaser = True
    player = e.Player.spawn(132., 84.)
    drone._update_move(level.tiles, {(3, 3, e.EDGE_R): e.EID_OFF}, player)
    assert drone.is_chasing
    assert drone.goal.x > drone.pos.x
    assert drone.cur_dir is None
    assert math.isnan(drone.cur_dir_v.x) and math.isnan(drone.cur_dir_v.y)
    drone._update_move(level.tiles, {}, player)
    assert math.isnan(drone.pos.x) and math.isnan(drone.pos.y)


def test_native_singular_and_undefined_member_continuation(tmp_path):
    compiler = shutil.which('cc') or shutil.which('gcc')
    if compiler is None or sys.platform == 'win32':
        pytest.skip('standalone harness requires a C compiler')
    # Harness includes core.c to force the otherwise private convex branch.
    sources = ['nv14_visual', 'nv14_dump', 'nv14_scene', 'nv14_rays',
               'nv14_objects_basic', 'nv14_objects_guard', 'nv14_objects_ranged',
               'nv14_objects_drones', 'nv14_drone_weapons']
    exe = tmp_path / 'avm1-continuation'
    compiled = subprocess.run([
        compiler, '-std=c11', '-O1', '-fno-fast-math', '-ffp-contract=off',
        '-I', str(ROOT / 'native'), str(Path(__file__).with_suffix('.c')),
        *(str(ROOT / 'native' / (name + '.c')) for name in sources),
        '-lm', '-o', str(exe)], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    result = subprocess.run([str(exe), boxed_level()], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
