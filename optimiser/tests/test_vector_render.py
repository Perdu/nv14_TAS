"""Source outlines, device-space widths and ordered vector composition."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")
from nv14_render import BACKGROUND, TERRAIN, SceneRenderer
from nv14_vector import rasterize
from tools.extract_vector_assets import extract_svg

ASSETS = Path(__file__).resolve().parents[1] / "nv14_assets"


@pytest.mark.parametrize("scale", [1, 2, 4])
def test_tinted_ninja_vectors_preserve_coverage_and_original_cached_artwork(scale):
    renderer = SceneRenderer("0" * 713 + "|5^100,100", scale=scale)
    pose = {"x": 100.25, "y": 100.5, "frame": 1, "facing": -1, "rotation_deg": 31.}
    original = renderer.render({"objects": [], "visual": pose})
    hidden = {"objects": [], "visual": {"visible": False}}
    tinted = renderer.render(hidden, secondary_players=[pose])
    assert original.tobytes() != tinted.tobytes()
    assert renderer.render({"objects": [], "visual": pose}).tobytes() == original.tobytes()
    # Tint changes only RGB, retaining subpixel coverage and the hairline alpha.
    assert len(renderer._player_transforms) == len(renderer._player_masks) == 1
    a, ax, ay = next(iter(renderer._player_transforms.items()))[1]
    b, bx, by = next(iter(renderer._player_masks.items()))[1]
    assert (ax, ay, a.size) == (bx, by, b.size)
    assert b.mode == "L"
    assert a.getchannel("A").tobytes() == b.tobytes()
    # Ghost colours are applied while compositing; cached coverage is untinted.
    assert len(renderer._transforms) == 0


def scene(*objects):
    return {"objects": list(objects), "visual": {"visible": False}}


@pytest.mark.parametrize("scale", [1, 2, 3, 4])
def test_original_bounce_border_is_one_dark_device_pixel_at_every_scale(scale):
    renderer = SceneRenderer("0"*713 + "|5^400,400", scale=scale)
    state = scene({"kind": "bounce", "x": 100., "y": 100.})
    saved = deepcopy(state)
    image = renderer.render(state)
    # Source sprite 879: 19.2 game units, #ccc fill and #666 hairline.
    row = [image.getpixel((x, 100*scale))
           for x in range(85*scale, 115*scale)]
    assert row.count((102, 102, 102)) == 2
    assert image.getpixel((100*scale, 100*scale)) == (204, 204, 204)
    assert state == saved
    assert renderer.render(state).tobytes() == image.tobytes()


@pytest.mark.parametrize("direction", [0, 1, 2, 3])
def test_oneway_source_top_hairline_survives_rotation(direction):
    renderer = SceneRenderer("0"*713 + "|5^400,400", scale=2)
    state = scene({"kind": "oneway", "x": 100., "y": 100.,
                   "parameters": (100, 100, direction)})
    image = renderer.render(state)
    dx, dy = ((1, 0), (0, 1), (-1, 0), (0, -1))[direction]
    # The collision-facing edge is 12 game pixels from registration.
    assert image.getpixel(((100+dx*12)*2, (100+dy*12)*2)) == (56, 56, 56)


def test_static_and_animated_exit_share_original_detail_and_registration():
    renderer = SceneRenderer("0"*713 + "|5^400,400", scale=2)
    for name, clip, frame in (("exit", "exit", 1), ("exit_open", "exit", 31),
                              ("exit_switch", "exit_switch", 1),
                              ("launchpad", "launchpad", 20)):
        static = Image.new("RGB", renderer.size, BACKGROUND)
        animated = static.copy()
        renderer._sprite(static, name, 100., 100.)
        renderer._sprite(animated, "object:"+clip, 100., 100., frame=frame)
        assert static.tobytes() == animated.tobytes()
    # The two light inner rectangles of the closed door used to disappear.
    renderer._sprite(static, "exit", 150., 150.)
    colors = static.crop((278, 278, 322, 322)).getcolors(4096)
    assert any(rgb == (204, 204, 204) and count > 20 for count, rgb in colors)


def test_dynamic_scale_keeps_hairline_width_and_fractional_positions_are_preserved():
    renderer = SceneRenderer("0"*713 + "|5^400,400", scale=2)
    for scale in (.5, 1., 2.):
        canvas = Image.new("RGB", renderer.size, BACKGROUND)
        renderer._sprite(canvas, "bounce_block", 100., 100., scale_x=scale, scale_y=scale)
        assert sum(canvas.getpixel((x, 200)) == (102, 102, 102)
                   for x in range(150, 250)) == 2
    a = Image.new("RGB", renderer.size, BACKGROUND)
    b = a.copy()
    renderer._sprite(a, "bounce_block", 100., 100., rotation=30.)
    renderer._sprite(b, "bounce_block", 100.25, 100.25, rotation=30.)
    assert a.tobytes() != b.tobytes()


def test_fill_holes_alpha_and_painter_order():
    black, red = [0, 0, 0, 255], [255, 0, 0, 128]
    ring = {"commands": [["M", 0, 0], ["L", 10, 0], ["L", 10, 10], ["L", 0, 10], ["Z"],
                         ["M", 3, 3], ["L", 7, 3], ["L", 7, 7], ["L", 3, 7], ["Z"]],
            "fill": black, "stroke": None}
    cover = {"commands": [["M", 0, 0], ["L", 5, 0], ["L", 5, 10], ["L", 0, 10], ["Z"]],
             "fill": red, "stroke": None}
    image, left, top = rasterize({"bounds": [0, 0, 10, 10], "paths": [ring, cover]}, (1, 0, 0, 1))
    assert image.getpixel((8-left, 5-top)) == (0, 0, 0, 255)
    assert image.getpixel((6-left, 5-top))[3] == 0
    assert image.getpixel((4-left, 5-top)) == (255, 0, 0, 128)
    assert image.getpixel((1-left, 5-top)) == (128, 0, 0, 255)


def test_source_singular_limb_transform_retains_finite_visible_hairline(tmp_path):
    source = tmp_path / "limb.svg"
    source.write_text('''<svg xmlns="http://www.w3.org/2000/svg"
      xmlns:ffdec="https://www.free-decompiler.com/flash">
      <g transform="matrix(1,0,0,1,50,30)"><g transform="matrix(.2,0,0,0,0,0)">
      <path d="M-50 0 L50 0" fill="none" stroke="#000000" stroke-width="Infinity"
        stroke-linecap="round" stroke-linejoin="round" ffdec:original-stroke-width="0.05"/>
      </g></g></svg>''')
    art = extract_svg(source, 1.)
    assert art["bounds"] == [-10., 0., 10., 0.]
    image, left, top = rasterize(art, (2, 0, 0, 2))
    column = [image.getpixel((-left, y))[3] for y in range(image.height)]
    assert column.count(255) == 1
    assert sum(column) == 255


def test_vector_pack_covers_every_original_object_and_pose_with_valid_provenance():
    manifest = json.loads((ASSETS / "manifest.json").read_text())
    payload = (ASSETS / manifest["vectors"]["file"]).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == manifest["vectors"]["sha256"]
    pack = json.loads(payload)
    assert pack["source_swf_sha256"] == manifest["source_swf_sha256"]
    entries = [*manifest["objects"].values(), *manifest["ninja"]["frames"].values()]
    for clip in manifest["object_animations"]["clips"].values():
        entries.extend(clip["frames"].values())
    assert len(entries) == manifest["vectors"]["sprites"] == 445
    assert {info["vector"] for info in entries} == pack["sprites"].keys()
    bounce = pack["sprites"]["objects/bounce_block"]
    assert bounce["bounds"] == pytest.approx([-9.6, -9.6, 9.6, 9.6], abs=.001)
    assert bounce["paths"][-1]["stroke"] == [102, 102, 102, 255]


def test_terrain_slope_has_coverage_pixels_without_dark_fringe_or_tile_seams():
    tiles = ["0"]*713
    tiles[0] = "2"  # Diagonal half-solid cell.
    tiles[23] = tiles[46] = "1"  # Adjacent full cells.
    renderer = SceneRenderer("".join(tiles) + "|5^400,400")
    image = renderer.render(scene())
    colors = {image.getpixel((x, y)) for x in range(24, 48) for y in range(24, 48)}
    assert TERRAIN in colors and BACKGROUND in colors
    partial = colors - {TERRAIN, BACKGROUND}
    assert partial
    assert all(all(t < value < b for t, value, b in zip(TERRAIN, rgb, BACKGROUND))
               for rgb in partial)
    assert all(image.getpixel((x, 30)) == TERRAIN for x in range(48, 96))
