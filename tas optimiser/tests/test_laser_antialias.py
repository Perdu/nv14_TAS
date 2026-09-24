"""Laser coverage, subpixel motion and retained-frame regression tests."""
from dataclasses import replace
from unittest.mock import patch

import pytest

Image = pytest.importorskip("PIL.Image")
from nv14_object_visuals import BeamVisual, ObjectVisual, SpriteVisual
from nv14_render import SceneRenderer, BACKGROUND
from nv14_vector import rasterize_beam
import nv14_vector

LEVEL = "0" * 713 + "|5^400,400"
SCENE = {"objects": [{"kind": "drone_laser", "id": 1, "x": 100., "y": 100.}],
         "visual": {"visible": False}}
BEAM = BeamVisual((80.125, 70.375), (210.625, 225.125), "#902b1e", 2.)
VISUAL = ObjectVisual(1, SpriteVisual("laserdrone_firing", 1, 100., 100., visible=False),
                      beam=BEAM)


@pytest.mark.parametrize("scale", [1, 2, 4])
@pytest.mark.parametrize("quality", ["fast", "exact"])
def test_beam_edges_have_partial_coverage_and_keep_solid_interior(scale, quality):
    renderer = SceneRenderer(LEVEL, scale=scale, render_quality=quality)
    image = renderer.render(SCENE, object_visuals=[VISUAL])
    colors = {color for _, color in image.crop((75*scale, 65*scale, 215*scale, 230*scale)).getcolors(4096)}
    ink = (144, 43, 30)
    assert ink in colors and BACKGROUND in colors
    partial = colors - {ink, BACKGROUND}
    assert len(partial) >= 8
    assert all(all(a <= p <= b for a, p, b in zip(ink, color, BACKGROUND))
               for color in partial)


def test_subpixel_endpoints_and_width_are_not_rounded():
    renderer = SceneRenderer(LEVEL, scale=2)
    first = renderer.render(SCENE, object_visuals=[VISUAL])
    moved = replace(BEAM, start=(80.225, 70.475), end=(210.725, 225.225))
    assert first.tobytes() != renderer.render(SCENE, object_visuals=[replace(VISUAL, beam=moved)]).tobytes()
    wider = replace(BEAM, width=2.2)
    assert first.tobytes() != renderer.render(SCENE, object_visuals=[replace(VISUAL, beam=wider)]).tobytes()


@pytest.mark.parametrize("scale", [1, 2])
def test_snapshot_fallback_also_antialiases(scale):
    renderer = SceneRenderer(LEVEL, scale=scale)
    state = {**SCENE, "objects": [{**SCENE["objects"][0], "beam_visible": True,
                                 "beam_start": BEAM.start, "beam_end": BEAM.end}]}
    image = renderer.render(state)
    colors = {color for _, color in image.crop((140*scale, 140*scale, 175*scale, 175*scale)).getcolors(4096)}
    assert len(colors - {BACKGROUND, (230, 70, 70)}) >= 8


def test_retained_render_matches_full_when_beam_moves_disappears_and_player_crosses():
    incremental = SceneRenderer(LEVEL, scale=2)
    full = SceneRenderer(LEVEL, scale=2, incremental=False)
    for n in range(12):
        beam = BEAM if n < 5 else replace(BEAM, end=(250.125, 240.375), visible=n < 9)
        state = {**SCENE, "visual": {"x": 125+n, "y": 123., "frame": 1,
                                      "facing": 1, "rotation_deg": 0.}}
        options = {"object_visuals": [replace(VISUAL, beam=beam)]}
        assert incremental.render(state, **options).tobytes() == full.render(state, **options).tobytes()
    assert incremental.stats["dirty_frames"] > 0


def test_mask_cache_reuses_geometry_when_other_object_visuals_change():
    renderer = SceneRenderer(LEVEL)
    with patch.object(nv14_vector, "rasterize_beam", wraps=rasterize_beam) as raster:
        for frame in (1, 2, 3):
            visual = replace(VISUAL, body=replace(VISUAL.body, frame=frame))
            renderer.render(SCENE, object_visuals=[visual])
        assert raster.call_count == 1
    assert renderer._beam_masks.bytes_used <= renderer._beam_masks.max_bytes


@pytest.mark.parametrize("start,end", [((-100., -80.), (120., 150.)),
    ((-100., 20.), (200., 20.)), ((20., -100.), (20., 200.)),
    ((30.25, 30.75), (30.25, 30.75)), ((-200., -200.), (-100., -100.))])
def test_clipping_round_caps_and_native_fallback_agree(start, end):
    native = nv14_vector.native_backend_available()
    with patch.object(nv14_vector, "_native", None):
        python = rasterize_beam(start, end, 4., (100, 100))
    assert python[0].width <= 100 and python[0].height <= 100
    if native:
        actual = rasterize_beam(start, end, 4., (100, 100))
        assert actual[1:] == python[1:]
        assert actual[0].tobytes() == python[0].tobytes()


def test_axis_aligned_width_and_round_caps():
    mask, left, top = rasterize_beam((10., 20.), (30., 20.), 4., (50, 50))
    assert sum(mask.getpixel((20-left, y)) for y in range(mask.height)) == 4 * 255
    assert mask.getpixel((9-left, 20-top)) == 255
    assert mask.getpixel((8-left, 18-top)) < 255
    assert mask.getpixel((7-left, 20-top)) == 0


def test_nonfinite_endpoints_are_ignored():
    renderer = SceneRenderer(LEVEL)
    hidden = renderer.render({"objects": [], "visual": {"visible": False}})
    for value in (float("nan"), float("inf"), -float("inf")):
        visual = replace(VISUAL, beam=replace(BEAM, end=(value, 20.)))
        assert renderer.render(SCENE, object_visuals=[visual]).tobytes() == hidden.tobytes()


@pytest.mark.parametrize("scale", [1, 2, 4])
def test_diagonal_prefire_hairline_has_coverage(scale):
    renderer = SceneRenderer(LEVEL, scale=scale)
    visual = replace(VISUAL, beam=replace(BEAM, width=0., color="#cb7579"))
    image = renderer.render(SCENE, object_visuals=[visual])
    colors = {color for _, color in image.crop((75*scale, 65*scale, 215*scale, 230*scale)).getcolors(4096)}
    assert len(colors - {BACKGROUND, (203, 117, 121)}) >= 8
