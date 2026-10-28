"""Regression coverage for QueryRayObj's player-first tile-DDA cutoff."""

from __future__ import annotations

import math
import random

import nv14_engine as engine


def _unbounded_query_ray_circle(
    tiles: engine.TileMap,
    p0: engine.Vec2,
    p1: engine.Vec2,
    obj_pos: engine.Vec2,
    radius: float,
    edge_overrides: engine.EdgeOverrides | None = None,
) -> tuple[bool, engine.Vec2]:
    """The pre-v2.27 query order, retained here as an exact oracle."""
    vx = p1.x - p0.x
    vy = p1.y - p0.y
    length = math.sqrt(vx * vx + vy * vy)
    if length == 0.0:
        return False, engine.Vec2()
    dx = vx / length
    dy = vy / length
    tile_hit, tile_point, tile_distance = engine.collide_ray_tiles(
        tiles, p0, p1, edge_overrides, _ray=(length, dx, dy)
    )
    circle_hit, circle_point, circle_distance = engine._ray_circle_first_hit(
        p0.x, p0.y, dx, dy, obj_pos, radius
    )
    if circle_hit and (not tile_hit or circle_distance <= tile_distance):
        return True, circle_point
    return False, tile_point if tile_hit else engine.Vec2()


def _assert_same_query(
    actual: tuple[bool, engine.Vec2], expected: tuple[bool, engine.Vec2]
) -> None:
    assert actual[0] == expected[0]
    assert actual[1].x == expected[1].x
    assert actual[1].y == expected[1].y


def test_query_ray_circle_stops_before_a_far_shaped_tile(monkeypatch) -> None:
    """A player hit must avoid geometry work that lies farther down the ray."""
    data = ["0"] * (31 * 23)
    # TileMap strings are column-major; this 45-degree tile lies far to the
    # right of both ray origin and player.
    data[(18 - 1) * 23 + (10 - 1)] = chr(48 + engine.TID_45DEGPN)
    tiles = engine.TileMap("".join(data))
    observed_tiles: list[tuple[int, int]] = []
    original = engine._test_ray_tile

    def recording_test(px, py, dx, dy, tile):
        observed_tiles.append((tile.i, tile.j))
        return original(px, py, dx, dy, tile)

    monkeypatch.setattr(engine, "_test_ray_tile", recording_test)
    result = engine.query_ray_circle(
        tiles,
        engine.Vec2(60.0, 252.0),
        engine.Vec2(180.0, 252.0),
        engine.Vec2(180.0, 252.0),
        10.0,
    )

    assert result[0] is True
    assert result[1].x == 170.0
    assert result[1].y == 252.0
    assert observed_tiles == []


def test_query_ray_circle_prefers_the_circle_on_a_tile_entry_tie() -> None:
    """The cutoff preserves QueryRayObj's circle-priority equality rule."""
    data = ["0"] * (31 * 23)
    # The ray enters this full tile at x=72. The player's circle first touches
    # that same point, so the old full DDA and the cutoff must both return it.
    data[(3 - 1) * 23 + (10 - 1)] = chr(48 + engine.TID_FULL)
    tiles = engine.TileMap("".join(data))
    p0 = engine.Vec2(60.0, 252.0)
    p1 = engine.Vec2(82.0, 252.0)
    player = engine.Vec2(82.0, 252.0)
    expected = _unbounded_query_ray_circle(tiles, p0, p1, player, 10.0)
    actual = engine.query_ray_circle(tiles, p0, p1, player, 10.0)

    _assert_same_query(actual, expected)
    assert actual[0] is True
    assert actual[1].x == 72.0
    assert actual[1].y == 252.0


def test_query_ray_circle_keeps_a_near_entry_shaped_tile() -> None:
    """Curved/angled helper arithmetic can put a hit just before entry."""
    data = ["0"] * (31 * 23)
    data[(10 - 1) * 23 + (10 - 1)] = chr(48 + engine.TID_22DEGPNS)
    tiles = engine.TileMap("".join(data))
    p0 = engine.Vec2(232.3028194787856, 247.9812035565363)
    p1 = engine.Vec2(
        p0.x + 100.0 * 0.4611169874734967,
        p0.y + 100.0 * 0.8873393510170543,
    )
    player = engine.Vec2(244.61116987473497, 271.6664807185709)
    vx = p1.x - p0.x
    vy = p1.y - p0.y
    length = math.sqrt(vx * vx + vy * vy)
    dx = vx / length
    dy = vy / length
    circle_hit, _circle_point, circle_distance = engine._ray_circle_first_hit(
        p0.x, p0.y, dx, dy, player, 10.0
    )
    assert circle_hit
    # A direct entry cutoff would drop the shaped cell because independent
    # floating-point paths put the circle root just before its entry.
    direct_hit, _direct_point, _direct_distance = engine.collide_ray_tiles(
        tiles,
        p0,
        p1,
        _ray=(length, dx, dy),
        _max_entry_distance=circle_distance,
    )
    assert direct_hit is False
    expected = _unbounded_query_ray_circle(tiles, p0, p1, player, 10.0)
    actual = engine.query_ray_circle(tiles, p0, p1, player, 10.0)

    _assert_same_query(actual, expected)
    assert actual[0] is False
    assert actual[1].x == 240.0
    assert actual[1].y == 262.7930872084003


def test_query_ray_circle_cutoff_matches_unbounded_rays_exactly() -> None:
    """Mixed shapes and edge overrides retain the old QueryRayObj result."""
    rng = random.Random(22427)
    for _map_index in range(5):
        data = ["0"] * (31 * 23)
        for i in range(31):
            for j in range(23):
                if rng.random() < 0.38:
                    data[i * 23 + j] = chr(48 + rng.randrange(1, 34))
        tiles = engine.TileMap("".join(data))

        for ray_index in range(400):
            p0 = engine.Vec2(rng.uniform(25.0, 719.0), rng.uniform(25.0, 527.0))
            p1 = engine.Vec2(rng.uniform(25.0, 719.0), rng.uniform(25.0, 527.0))
            if p0.x == p1.x and p0.y == p1.y:
                p1.x += 1.0
            obj_pos = engine.Vec2(
                rng.uniform(25.0, 719.0), rng.uniform(25.0, 527.0)
            )
            edge_overrides: engine.EdgeOverrides | None = None
            if ray_index % 7 == 0:
                edge_overrides = {}
                for _ in range(rng.randrange(5)):
                    i = rng.randrange(1, 32)
                    j = rng.randrange(1, 24)
                    side = rng.randrange(4)
                    key = (i, j, side)
                    # TestDoor only restores an edge captured from TileMap or
                    # closes it as solid; it never invents a new interesting
                    # shaped-edge route.
                    edge_overrides[key] = (
                        engine.EID_SOLID
                        if rng.randrange(2)
                        else tiles.grid[i][j].edges[side]
                    )
            radius = rng.uniform(0.01, 30.0)

            expected = _unbounded_query_ray_circle(
                tiles,
                p0,
                p1,
                obj_pos,
                radius,
                edge_overrides,
            )
            actual = engine.query_ray_circle(
                tiles,
                p0,
                p1,
                obj_pos,
                radius,
                edge_overrides,
            )
            _assert_same_query(actual, expected)
