"""Binary64 boundary regressions derived from the supplied ActionScript dump.

These fixtures deliberately differ from mathematically equivalent shortcuts.
The quadratic expectations follow the dump; original AVM1 bytecode has not
been provided to independently resolve its decompiler-parentheses caveat.
"""
from pathlib import Path
import math
import shutil
import subprocess
import sys

import pytest

import nv14_engine as engine


ROOT = Path(__file__).resolve().parents[1]


def test_circle_root_preserves_dump_multiplication_order():
    d = 1.0 / math.sqrt(2.0)
    hit, point, distance = engine._ray_circle_first_hit(
        0.0, 0.0, d, d, engine.Vec2(13.0, 13.0), 10.0)
    assert hit
    assert distance == 8.38477631085023
    assert distance != 8.384776310850233  # Conventional / (2*a).
    assert point.x == point.y == distance * d


@pytest.mark.parametrize("tile_id,origin,direction,expected", [
    (engine.TID_CONCAVEPP, 60.0, -1.0, 31.02943725152287),
    (engine.TID_CONVEXPP, 47.0, 1.0, 7.029437251522872),
])
def test_arc_roots_preserve_dump_multiplication_order(tile_id, origin, direction, expected):
    tiles = engine.TileMap("0" * 713)
    cell = tiles.grid[1][1]
    cell.tile_id = tile_id
    tiles._update_type(cell)
    d = direction / math.sqrt(2.0)
    hit, point = engine._test_ray_tile(origin, origin, d, d, cell)
    assert hit
    assert point.x == point.y == expected


def test_nan_discriminant_does_not_write_circle_hit():
    hit, _point, distance = engine._ray_circle_first_hit(
        0.0, 0.0, math.nan, math.nan, engine.Vec2(13.0, 13.0), 10.0)
    assert not hit
    assert math.isinf(distance)


def test_nan_ray_follows_neighbour_links_and_undefined_origin_retains_output():
    tiles = engine.TileMap("0" * 713)
    previous = engine.Vec2(77.0, 88.0)
    target = engine.Vec2(math.nan, math.nan)
    hit, point = engine.query_ray_circle(
        tiles, engine.Vec2(100.0, 100.0), target,
        engine.Vec2(300.0, 300.0), 10.0, previous_point=previous)
    # NaN comparisons select the source's down-neighbour links. The finite
    # map ends this traversal at a solid edge, writing a NaN wall endpoint.
    assert not hit
    assert math.isnan(point.x) and math.isnan(point.y)
    hit, point = engine.query_ray_circle(
        tiles, target, engine.Vec2(100.0, 100.0),
        engine.Vec2(300.0, 300.0), 10.0, previous_point=previous)
    assert not hit
    assert (point.x, point.y) == (77.0, 88.0)


def test_zap_sqrt_rounded_tangency_survives_with_inside_control():
    tiles = engine.TileMap("0" * 713)
    drone = engine.ZapDrone.from_spec(engine.ObjectSpec(
        engine.OBJTYPE_DRONE, (36.0, 36.0, 2.0, 0.0, 0.0, 0.0), 1), tiles)
    player = engine.Player.spawn(36.05, 54.99993421041241)
    dx, dy = drone.pos.x - player.pos.x, drone.pos.y - player.pos.y
    assert dx * dx + dy * dy == 360.99999999999994
    drone.test_player(player)
    assert not player.dead
    player.pos.y = math.nextafter(player.pos.y, -math.inf)
    drone.test_player(player)
    assert player.dead


def test_zero_predicted_rocket_target_poisoning_continues_next_tick():
    tiles = engine.TileMap("0" * 713)
    rocket = engine.HomingLauncher.from_spec(engine.ObjectSpec(
        engine.OBJTYPE_HOMINGLAUNCHER, (300.0, 300.0), 1), tiles)
    rocket.mode = engine.HomingMode.HOMING
    rocket.speed = rocket.maxspeed
    rocket.mdir = engine.Vec2(1.0, 0.0)
    player = engine.Player.spawn((300.0 + rocket.speed) + rocket.speed, 300.0)
    assert not rocket.update(player, tiles, {})
    assert math.isnan(rocket.mdir.x) and math.isnan(rocket.mdir.y)
    assert math.isfinite(rocket.pos.x) and math.isfinite(rocket.pos.y)
    assert not rocket.update(player, tiles, {})
    assert math.isnan(rocket.pos.x) and math.isnan(rocket.pos.y)
    assert rocket.mode == engine.HomingMode.HOMING
    rocket.test_player(player)
    assert not player.dead


def test_native_source_arithmetic_boundaries(tmp_path):
    compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if compiler is None or sys.platform == "win32":
        pytest.skip("standalone native regression harness requires a C compiler")
    sources = ["nv14_core", "nv14_visual", "nv14_dump", "nv14_scene", "nv14_rays",
               "nv14_objects_basic", "nv14_objects_guard", "nv14_objects_ranged",
               "nv14_objects_drones", "nv14_drone_weapons"]
    executable = tmp_path / "as-arithmetic-tests"
    subprocess.run([
        compiler, "-std=c11", "-O2", "-fno-fast-math", "-ffp-contract=off",
        "-I", str(ROOT / "native"), str(Path(__file__).with_name("as_arithmetic_424_harness.c")),
        *(str(ROOT / "native" / (name + ".c")) for name in sources),
        "-lm", "-o", str(executable),
    ], check=True, capture_output=True, text=True)
    level = "0" * 713 + "|5^100,100!6^36,36,2,0,0,0!10^300,300"
    result = subprocess.run([str(executable), level], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
