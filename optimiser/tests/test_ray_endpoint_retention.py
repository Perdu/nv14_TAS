"""ActionScript ray out-parameters survive calls which do not write a hit.

The demo's first CollideRayvsTiles misses through the left border; the beam
therefore uses DroneObject's source constructor target (4, 5). False from
QueryRayObj alone is not a no-write signal: an occluding wall writes a point.
"""
from __future__ import annotations

import math
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import nv14_engine as engine
from nv14_replay import decode_complex_replay, parse_combined_level_replay


FIXTURE = Path(__file__).with_name("laser_stale_endpoint.txt")
ROOT = Path(__file__).resolve().parents[1]
MISS_ORIGIN = (250.71428571428575, 300.0)
MISS_AIM = (145.7842857144547, 384.61668308940745)


def _demo():
    return parse_combined_level_replay(FIXTURE.read_text(encoding="utf-8"))


def _xy(point):
    return point.x, point.y


def _demo_level():
    return engine.parse_level_string(_demo().level_string, simulate_enemies=True)


@pytest.mark.parametrize("backend", ["python", "native"])
def test_source_constructor_vectors(backend):
    module = engine if backend == "python" else pytest.importorskip("_nv14_native")
    level = module.parse_level_string("0" * 713 + (
        "|5^400,100!6^252,300,2,0,1,2!6^252,300,2,0,2,2!10^300,100"),
        simulate_enemies=True)
    state = level.initial_state()
    if backend == "python":
        laser, chain, homing = (state.objects_by_uid[i] for i in (1, 2, 3))
        for drone in (laser, chain):
            assert _xy(drone.view) == (9.0, 4.0)
            assert _xy(drone.targ) == (4.0, 5.0)
            assert _xy(drone.targ2) == (5.0, 7.0)
        assert _xy(chain.targ3) == (3.0, 6.0)
        assert _xy(homing.view) == (4.0, 56.0)
        assert laser.laser_len == 7.0
    else:
        objects = {obj["load_index"]: obj for obj in state.scene_snapshot()["objects"]}
        for uid in (1, 2):
            assert objects[uid]["view"] == (9.0, 4.0)
            assert objects[uid]["target"] == (4.0, 5.0)
            assert objects[uid]["vector"] == (5.0, 7.0)
        assert objects[2]["shot_target"] == (3.0, 6.0)
        assert objects[3]["view"] == (4.0, 56.0)


@pytest.mark.parametrize("origin,aim", [
    ((12.0, 300.0), (0.0, 300.0)),
    ((780.0, 300.0), (800.0, 300.0)),
    ((300.0, 12.0), (300.0, 0.0)),
    ((300.0, 588.0), (300.0, 600.0)),
])
def test_finite_tile_traversal_exits_all_four_borders(origin, aim):
    # Origins are inside full border cells. Their outward edges are off;
    # source traversal reaches a null neighbour without writing an endpoint.
    tiles = engine.TileMap("0" * 713)
    p0, p1 = engine.Vec2(*origin), engine.Vec2(*aim)
    hit, _point, distance = engine.collide_ray_tiles(tiles, p0, p1)
    assert not hit and math.isinf(distance)
    hit, point = engine.query_ray_circle(
        tiles, p0, p1, engine.Vec2(400.0, 100.0), 10.0,
        previous_point=engine.Vec2(77.0, 88.0))
    assert not hit
    assert _xy(point) == (77.0, 88.0)


@pytest.mark.parametrize("backend", ["python", "native"])
def test_supplied_demo_retains_source_target_and_kills_on_tick_59(backend):
    combined = _demo()
    frames = decode_complex_replay(combined.replay_string).frames
    module = engine if backend == "python" else pytest.importorskip("_nv14_native")
    level = module.parse_level_string(combined.level_string, simulate_enemies=True)
    state = level.initial_state()
    clone = None
    checkpoints = {2: 0, 3: 1, 32: 1, 33: 2, 57: 2, 58: 3}
    for tick, inputs in enumerate(frames):
        if backend == "python":
            state.step(inputs, level.tiles)
            drone = state.objects_by_uid[1]
            target = _xy(drone.targ)
            mode = int(drone.mode)
            dead = state.player.dead
        else:
            state.step(inputs)
            drone = next(obj for obj in state.scene_snapshot()["objects"]
                         if obj["load_index"] == 1)
            target = drone["beam_end"]
            mode = drone["mode"]
            dead = state.player_snapshot()["dead"]

        # Explicit source-derived expectations, not Python/native agreement.
        assert target == (4.0, 5.0)
        assert dead is (tick >= 58)
        if tick in checkpoints:
            assert mode == checkpoints[tick]
        if clone is not None:
            if backend == "python":
                clone.step(inputs, level.tiles)
            else:
                clone.step(inputs)
            assert clone.state_key() == state.state_key()
        if tick == 3:
            # Search branches made after acquisition must retain this endpoint.
            clone = state.clone()


def test_query_zero_direction_preserves_previous_point_without_mutating_it():
    tiles = engine.TileMap("0" * 713)
    point = engine.Vec2(100.0, 100.0)
    previous = engine.Vec2(77.0, 88.0)
    hit, endpoint = engine.query_ray_circle(
        tiles, point, point, point, 10.0, previous_point=previous)
    assert not hit
    assert _xy(endpoint) == (77.0, 88.0)
    assert _xy(previous) == (77.0, 88.0)
    hit, _endpoint, distance = engine.collide_ray_tiles(tiles, point, point)
    assert not hit and math.isinf(distance)


def test_query_false_distinguishes_no_write_from_occluding_wall():
    tiles = _demo_level().tiles
    previous = engine.Vec2(77.0, 88.0)
    hit, endpoint = engine.query_ray_circle(
        tiles, engine.Vec2(*MISS_ORIGIN), engine.Vec2(*MISS_AIM),
        engine.Vec2(400.0, 100.0), 10.0, previous_point=previous)
    assert not hit
    assert _xy(endpoint) == (77.0, 88.0)
    # A circle beyond the right border is occluded. False still writes x=768.
    hit, endpoint = engine.query_ray_circle(
        tiles, engine.Vec2(*MISS_ORIGIN), engine.Vec2(1000.0, 300.0),
        engine.Vec2(1000.0, 300.0), 10.0, previous_point=previous)
    assert not hit
    assert _xy(endpoint) == (768.0, 300.0)
    assert _xy(previous) == (77.0, 88.0)


@pytest.mark.parametrize("descriptor", [
    "6^252,300,2,0,1,2", "6^252,300,2,0,2,2",
    "3^252,300", "10^252,300",
])
def test_all_acquisition_outputs_keep_last_wall_point_on_zero_direction(descriptor):
    level = engine.parse_level_string(
        "0" * 713 + "|5^1000,300!" + descriptor, simulate_enemies=True)
    obj = level.objects[0]
    origin = obj.basepos if isinstance(obj, engine.HomingLauncher) else obj.pos
    player = engine.Player.spawn(1000.0, origin.y)
    obj.think(player, level.tiles, {})
    assert _xy(obj.view) == (768.0, origin.y)
    player.pos = origin.copy()
    obj.think(player, level.tiles, {})
    assert _xy(obj.view) == (768.0, origin.y)


def test_later_laser_miss_reuses_nonzero_endpoint_and_damage_segment():
    level = _demo_level()
    drone = next(obj for obj in level.objects if isinstance(obj, engine.LaserDrone))
    drone.pos = engine.Vec2(*MISS_ORIGIN)
    drone._start_firing(level.player, level.tiles, {}, engine.Vec2(300.0, 300.0))
    assert _xy(drone.targ) == (768.0, 300.0)
    # Run the complete first cycle away from the beam, then acquire the miss.
    safe_player = engine.Player.spawn(400.0, 100.0)
    for _ in range(30 + 80 + 40):
        drone.update(safe_player, level.tiles, {})
    assert drone.mode == engine.DroneMode.MOVING
    drone._start_firing(safe_player, level.tiles, {}, engine.Vec2(*MISS_AIM))
    assert _xy(drone.targ) == (768.0, 300.0)
    assert _xy(drone.targ2) == (768.0 - MISS_ORIGIN[0], 0.0)
    for _ in range(30):
        drone.update(safe_player, level.tiles, {})
    on_old_beam = engine.Player.spawn(400.0, 300.0)
    drone.update(on_old_beam, level.tiles, {})
    assert on_old_beam.dead


@pytest.mark.parametrize("zero_direction", [False, True])
def test_turret_fire_retains_previous_target_on_no_write(zero_direction):
    level = _demo_level()
    turret = engine.Turret.from_spec(
        engine.ObjectSpec(engine.OBJTYPE_TURRET, MISS_ORIGIN, 1), level.tiles)
    turret.aim = engine.Vec2(1000.0, 300.0)
    player = engine.Player.spawn(400.0, 100.0)
    assert not turret._fire(player, level.tiles, {})
    assert _xy(turret.targ) == (768.0, 300.0)
    turret.aim = turret.pos.copy() if zero_direction else engine.Vec2(*MISS_AIM)
    assert not turret._fire(player, level.tiles, {})
    assert _xy(turret.targ) == (768.0, 300.0)
    assert not player.dead


@pytest.mark.parametrize("zero_direction", [False, True])
def test_chaingun_shot_retains_previous_view_on_no_write(zero_direction):
    tiles = _demo_level().tiles
    drone = engine.ChaingunDrone.from_spec(engine.ObjectSpec(
        engine.OBJTYPE_DRONE, (252.0, 300.0, 2.0, 0.0, 2.0, 2.0), 1), tiles)
    drone.pos = engine.Vec2(*MISS_ORIGIN)
    drone.view = engine.Vec2(77.0, 88.0)
    drone.mode = engine.DroneMode.FIRING
    drone.chaingun_timer = 5
    drone.chaingun_max_num = 4
    drone.chaingun_cur_num = 2  # Middle shot has no spread offset.
    drone.targ = (engine.Vec2() if zero_direction else engine.Vec2(
        MISS_AIM[0] - MISS_ORIGIN[0], MISS_AIM[1] - MISS_ORIGIN[1]))
    player = engine.Player.spawn(400.0, 100.0)
    drone.update(player, tiles, {}, 100)
    assert _xy(drone.view) == (77.0, 88.0)
    assert drone.chaingun_cur_num == 3
    assert not player.dead


@pytest.mark.parametrize("mode", [engine.DroneMode.MOVING, engine.DroneMode.POSTFIRE])
@pytest.mark.parametrize("precision", [None, 6])
def test_laser_retained_target_distinguishes_search_keys_and_clones(mode, precision):
    state = _demo_level().initial_state()
    state.objects_by_uid[1].mode = mode
    clone = state.clone()
    assert clone.state_key(precision=precision) == state.state_key(precision=precision)
    clone.objects_by_uid[1].targ = engine.Vec2(768.0, 300.0)
    assert _xy(state.objects_by_uid[1].targ) == (4.0, 5.0)
    assert clone.state_key(precision=precision) != state.state_key(precision=precision)


def test_native_c_ray_output_and_lifecycle_regressions(tmp_path):
    compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if compiler is None or sys.platform == "win32":
        pytest.skip("standalone native regression harness requires a C compiler")
    sources = ["nv14_core", "nv14_visual", "nv14_dump", "nv14_scene", "nv14_rays",
               "nv14_objects_basic", "nv14_objects_guard", "nv14_objects_ranged",
               "nv14_objects_drones", "nv14_drone_weapons"]
    executable = tmp_path / "ray-endpoint-tests"
    subprocess.run([
        compiler, "-std=c11", "-O1", "-fno-fast-math", "-ffp-contract=off",
        "-I", str(ROOT / "native"), str(FIXTURE.with_name("ray_endpoint_harness.c")),
        *(str(ROOT / "native" / (name + ".c")) for name in sources),
        "-lm", "-o", str(executable),
    ], check=True, capture_output=True, text=True)
    tile_data = _demo().level_string.split("|", 1)[0]
    level = tile_data + (
        "|5^400,100!6^252,300,2,0,1,2!6^252,300,2,0,2,2"
        "!3^250.71428571428575,300!10^250.71428571428575,300")
    result = subprocess.run([str(executable), level], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
