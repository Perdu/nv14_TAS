"""Registration, layering and observation-only behaviour of optional rendering."""
from __future__ import annotations

from copy import deepcopy
import json
import subprocess
import sys

import pytest

Image = pytest.importorskip("PIL.Image")
from nv14_render import BACKGROUND, TERRAIN, SceneRenderer


@pytest.fixture
def assets(tmp_path):
    # An asymmetric marker tests the registration point independently of the
    # artwork: origin is (2, 2), marker is offset two game pixels right.
    ninja = Image.new("RGBA", (8, 8))
    ninja.putpixel((4, 2), (255, 0, 0, 255))
    ninja.save(tmp_path / "ninja.png")
    gold = Image.new("RGBA", (8, 8), (240, 200, 0, 255))
    gold.save(tmp_path / "gold.png")
    manifest = {
        "schema_version": 1, "pixels_per_unit": 1,
        "ninja": {"frames": {"1": {"file": "ninja.png", "origin": [2, 2]}}},
        "objects": {"gold": {"file": "gold.png", "origin": [4, 4]}}
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    return tmp_path


def scene(**visual):
    return {"objects": [], "visual": {
        "x": 100., "y": 100., "frame": 1, "visible": True,
        "facing": 1, "rotation_deg": 0., **visual}}


def test_module_import_does_not_import_optional_dependencies():
    result = subprocess.run([sys.executable, "-c",
        "import sys; import nv14_render; "
        "assert 'PIL' not in sys.modules; assert 'nv14_engine' not in sys.modules"],
        check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_registration_mirroring_and_clockwise_rotation(assets):
    renderer = SceneRenderer("0" * 713 + "|5^100,100", assets_path=assets)
    normal = renderer.render(scene())
    assert normal.getpixel((102, 100)) == (255, 0, 0)
    flipped = renderer.render(scene(facing=-1))
    assert flipped.getpixel((97, 100)) == (255, 0, 0)
    rotated = renderer.render(scene(rotation_deg=90))
    assert rotated.getpixel((99, 102)) == (255, 0, 0)


def test_gold_visibility_tile_occlusion_and_no_snapshot_mutation(assets):
    tiles = ["0"] * 713
    # Cell at x=4, y=4 occupies [96,120) in the game world.
    tiles[3 * 23 + 3] = "1"
    renderer = SceneRenderer("".join(tiles) + "|5^100,100", assets_path=assets)
    snapshot = scene()
    snapshot["objects"] = [{"kind": "gold", "x": 150, "y": 100, "visible": True}]
    saved = deepcopy(snapshot)
    frame = renderer.render(snapshot)
    assert snapshot == saved
    assert frame.mode == "RGB" and frame.size == (792, 600)
    assert frame.getpixel((102, 100)) == TERRAIN  # Tiles cover the ninja.
    assert frame.getpixel((150, 100)) == (240, 200, 0)
    snapshot["objects"][0]["visible"] = False
    assert renderer.render(snapshot).getpixel((150, 100)) == BACKGROUND
    # Previously returned frames are independent from later renders.
    assert frame.getpixel((150, 100)) == (240, 200, 0)


def test_all_tile_shapes_match_engine_away_from_antialiased_boundaries(assets):
    tiles = ["0"] * 713
    for tile_id in range(1, 34):
        tiles[((tile_id - 1) // 11) * 23 + (tile_id - 1) % 11] = chr(48 + tile_id)
    renderer = SceneRenderer("".join(tiles) + "|5^400,400", assets_path=assets)
    frame = renderer.render(scene(visible=False))
    for column in renderer.level.tiles.grid[1:4]:
        for cell in column[1:12]:
            for dx, dy in ((-10, -10), (-10, 10), (10, -10), (10, 10), (0, 0), (-4, 4)):
                x, y = round(cell.pos.x + dx), round(cell.pos.y + dy)
                solid = renderer.level.tiles.query_point(x + .5, y + .5, cell)
                corners = [renderer.level.tiles.query_point(x+sx, y+sy, cell)
                           for sx in (.01, .99) for sy in (.01, .99)]
                if all(value == solid for value in corners):
                    assert frame.getpixel((x, y)) == (TERRAIN if solid else BACKGROUND)
                else:
                    assert all(t <= value <= b for t, value, b in
                               zip(TERRAIN, frame.getpixel((x, y)), BACKGROUND))


def test_missing_visuals_and_assets_fail_clearly(assets):
    renderer = SceneRenderer("0" * 713 + "|5^100,100", assets_path=assets, scale=2)
    assert renderer.size == (1584, 1200)
    with pytest.raises(ValueError, match="no player visuals"):
        renderer.render({})
    with pytest.raises(ValueError, match="missing from the asset pack"):
        renderer.render(scene(frame=888))


def test_secondary_player_tint_layering_registration_and_cache_isolation(assets):
    renderer = SceneRenderer("0" * 713 + "|5^100,100", assets_path=assets)
    primary = scene()
    grey = scene(x=150)["visual"]
    blue = {**scene(x=200, facing=-1)["visual"], "color": (90, 140, 200)}
    saved = deepcopy((primary, grey, blue))
    baseline = renderer.render(primary)
    image = renderer.render(primary, secondary_players=[grey, blue])
    assert image.getpixel((102, 100)) == (255, 0, 0)
    assert image.getpixel((152, 100)) == (53, 104, 168)
    assert image.getpixel((197, 100)) == (90, 140, 200)
    assert (primary, grey, blue) == saved
    assert renderer.render(primary).tobytes() == baseline.tobytes()
    # At coincident positions the primary remains the top player.
    assert renderer.render(primary, secondary_players=[primary["visual"]]).getpixel((102, 100)) == (255, 0, 0)
    hidden = renderer.render(primary, secondary_players=[grey], show_primary_player=False)
    assert hidden.getpixel((102, 100)) == BACKGROUND
    assert hidden.getpixel((152, 100)) == (53, 104, 168)
    # Native death visibility and terrain occlusion also apply to overlays.
    assert renderer.render(primary, secondary_players=[{**grey, "visible": False}]).getpixel((152, 100)) == BACKGROUND
    tiles = ["0"] * 713
    tiles[3 * 23 + 3] = "1"
    covered = SceneRenderer("".join(tiles) + "|5^100,100", assets_path=assets)
    assert covered.render(scene(visible=False), secondary_players=[primary["visual"]]).getpixel((102, 100)) == TERRAIN
