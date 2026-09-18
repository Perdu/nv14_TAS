"""Colour-independent coverage, bounded player caches, and opt-in atlas quality."""
import json
import math

import pytest

Image = pytest.importorskip("PIL.Image")

from nv14_render import BACKGROUND, SceneRenderer, _ImageCache
import nv14_vector


LEVEL = "0" * 713 + "|5^400,400"
HIDDEN = {"objects": [], "visual": {"visible": False}}


def pose(**changes):
    return {"x": 100.234, "y": 100.567, "frame": 1, "facing": -1,
            "rotation_deg": 31.125, **changes}


@pytest.mark.parametrize("scale", [1, 2, 4])
def test_ghost_mask_matches_previous_rgba_tint_pixels(scale):
    renderer = SceneRenderer(LEVEL, scale=scale)
    player = pose(color=(25, 91, 173))
    actual = renderer.render(HIDDEN, secondary_players=[player])
    art = renderer._vectors[renderer._asset_info("ninja", 1)["vector"]]
    radians = math.radians(player["rotation_deg"])
    c, s = math.cos(radians)*scale, math.sin(radians)*scale
    px, py = math.floor(player["x"]*scale), math.floor(player["y"]*scale)
    phase = (round(player["x"]*scale-px, 8), round(player["y"]*scale-py, 8))
    rgba, left, top = nv14_vector.rasterize(art, (-c, -s, -s, c), phase)
    previous_tint = Image.new("RGBA", rgba.size, player["color"])
    previous_tint.putalpha(rgba.getchannel("A"))
    expected = renderer.render(HIDDEN)
    expected.paste(previous_tint, (px+left, py+top), previous_tint)
    assert actual.tobytes() == expected.tobytes()
    assert len(renderer._player_masks) == 1
    assert len(renderer._player_transforms) == 0


def test_twenty_ghost_colours_share_one_rasterisation(monkeypatch):
    renderer = SceneRenderer(LEVEL)
    original = nv14_vector.rasterize
    calls = []

    def capture(*args, **kwargs):
        calls.append(kwargs.get("alpha_only", False))
        return original(*args, **kwargs)

    monkeypatch.setattr(nv14_vector, "rasterize", capture)
    for n in range(20):
        player = pose(x=100.25+n, y=100.5, color=(n*10, 100, 150))
        renderer.render(HIDDEN, secondary_players=[player])
    assert calls == [True]
    assert len(renderer._player_masks) == 1


def test_primary_coverage_reused_without_rasterisation(monkeypatch):
    renderer = SceneRenderer(LEVEL)
    primary = {"objects": [], "visual": pose()}
    before = renderer.render(primary)

    def fail(*args, **kwargs):
        pytest.fail("Existing primary coverage should be reused for a ghost")

    monkeypatch.setattr(nv14_vector, "rasterize", fail)
    ghost = renderer.render(HIDDEN, secondary_players=[pose(color=(150, 30, 70))])
    assert ghost.tobytes() != before.tobytes()
    assert renderer.render(primary).tobytes() == before.tobytes()
    rgba, x, y = next(iter(renderer._player_transforms.items()))[1]
    mask, mx, my = next(iter(renderer._player_masks.items()))[1]
    assert (x, y) == (mx, my)
    assert rgba.getchannel("A").tobytes() == mask.tobytes()


def test_cache_memory_and_entry_limits_and_lru():
    cache = _ImageCache(20, 3)
    a, b, c = (Image.new("L", (3, 3)) for _ in range(3))
    cache.put("a", (a, 0, 0))
    cache.put("b", (b, 0, 0))
    cache.get("a")
    cache.put("c", (c, 0, 0))
    assert cache.get("b") is None
    assert cache.get("a")[0] is a
    assert cache.bytes_used == 18
    cache.put("oversize", Image.new("RGBA", (3, 3)))
    assert cache.bytes_used == 18 and len(cache) == 2
    cache.put("a", Image.new("L", (1, 1)))
    assert cache.bytes_used == 10
    cache.put("tiny1", Image.new("L", (1, 1)))
    cache.put("tiny2", Image.new("L", (1, 1)))
    assert len(cache) == 3 and cache.get("c") is None


def test_player_cache_churn_does_not_evict_world_art():
    renderer = SceneRenderer(LEVEL)
    renderer._player_masks.max_entries = 2
    renderer._sprite(Image.new("RGB", renderer.size), "bounce_block", 100, 100)
    world_key, world_value = next(iter(renderer._transforms.items()))
    for n in range(6):
        renderer.render(HIDDEN, secondary_players=[pose(x=100+n*.13)])
    assert len(renderer._player_masks) == 2
    assert renderer._transforms.get(world_key) is world_value


@pytest.mark.parametrize("scale", [1, 3])
def test_fast_atlas_reuses_eighth_pixel_and_degree_bins(scale):
    renderer = SceneRenderer(LEVEL, scale=scale, render_quality="fast")
    first = pose(x=100+.98/scale, y=100+.51/scale, rotation_deg=31.12)
    second = pose(x=101 if scale == 1 else 100+1/scale,
                  y=100+.50/scale, rotation_deg=31.24)
    a = renderer.render(HIDDEN, secondary_players=[first])
    b = renderer.render(HIDDEN, secondary_players=[second])
    assert a.tobytes() == b.tobytes()
    assert len(renderer._player_masks) == 1
    key = next(iter(renderer._player_masks.items()))[0]
    assert key[2] == 31 and key[-2] == (0., .5)
    # The quantisation error is bounded in device pixels, independent of scale.
    exact = SceneRenderer(LEVEL, scale=scale)
    aligned = pose(x=(math.floor(first["x"]*scale)+1)/scale,
                   y=(math.floor(first["y"]*scale)+.5)/scale,
                   rotation_deg=31)
    assert a.tobytes() == exact.render(HIDDEN, secondary_players=[aligned]).tobytes()


def test_fast_negative_coordinate_carry_and_world_art_accuracy():
    renderer = SceneRenderer(LEVEL, render_quality="fast")
    renderer.render(HIDDEN, secondary_players=[pose(x=-.02, y=-.02)])
    key = next(iter(renderer._player_masks.items()))[0]
    assert key[-2] == (0., 0.)
    fast = Image.new("RGB", renderer.size, BACKGROUND)
    exact_renderer = SceneRenderer(LEVEL)
    exact = fast.copy()
    for r, canvas in ((renderer, fast), (exact_renderer, exact)):
        r._sprite(canvas, "bounce_block", 100.234, 100.789, rotation=31.125)
    assert fast.tobytes() == exact.tobytes()


def test_exact_quality_keeps_distinct_subpixel_transforms():
    renderer = SceneRenderer(LEVEL)
    for x in (100.22, 100.24):
        renderer.render(HIDDEN, secondary_players=[pose(x=x)])
    assert len(renderer._player_masks) == 2
    with pytest.raises(ValueError, match="render_quality"):
        SceneRenderer(LEVEL, render_quality="approximate")


def test_exact_nearby_rotations_do_not_depend_on_prior_cache_entries():
    renderer = SceneRenderer(LEVEL)
    axis_aligned = Image.new("RGB", renderer.size, BACKGROUND)
    rotated = axis_aligned.copy()
    # A minute rotation changes whether the hairline is axis-grid-fitted.
    # Rounding only the cache key used to reuse whichever pose was drawn first,
    # allowing different worker histories to change the output pixels.
    renderer._sprite(axis_aligned, "bounce_block", 100.25, 100.25, rotation=0.)
    renderer._sprite(rotated, "bounce_block", 100.25, 100.25, rotation=.000002)
    assert axis_aligned.tobytes() != rotated.tobytes()
    isolated = SceneRenderer(LEVEL)
    expected = Image.new("RGB", renderer.size, BACKGROUND)
    isolated._sprite(expected, "bounce_block", 100.25, 100.25, rotation=.000002)
    assert rotated.tobytes() == expected.tobytes()


def test_legacy_png_ghosts_share_transformed_alpha(tmp_path):
    source = Image.new("RGBA", (8, 8), (10, 40, 90, 0))
    source.putpixel((3, 3), (20, 80, 190, 128))
    source.putpixel((4, 4), (60, 30, 120, 255))
    source.save(tmp_path / "ninja.png")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "ninja": {"frames": {"1": {
            "file": "ninja.png", "origin": [4, 4]}}}}))
    renderer = SceneRenderer(LEVEL, assets_path=tmp_path)
    p = pose(rotation_deg=0, x=100, y=100, facing=1)
    primary = renderer.render({"objects": [], "visual": p})
    for color in ((30, 150, 100), (150, 50, 100)):
        image = renderer.render(HIDDEN, secondary_players=[{**p, "color": color}])
        assert image.getpixel((100, 100)) == color
        assert image.getpixel((99, 99)) == tuple((a*128+b*127+127)//255
                                               for a, b in zip(color, BACKGROUND))
    assert len(renderer._player_masks) == len(renderer._player_transforms) == 1
    assert renderer.render({"objects": [], "visual": p}).tobytes() == primary.tobytes()
