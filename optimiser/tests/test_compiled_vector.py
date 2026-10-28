"""Whole-artwork compilation must preserve the established exact rasteriser."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import math
from pathlib import Path
import random
from types import SimpleNamespace

import pytest

Image = pytest.importorskip("PIL.Image")
import nv14_vector as vector


@pytest.fixture
def native(monkeypatch):
    backend = pytest.importorskip("_nv14_render_native")
    monkeypatch.setattr(vector, "_native_checked", True)
    monkeypatch.setattr(vector, "_native", backend)
    vector._compiled_art_cache.clear()
    return backend


def stamp(art, transform=(1., 0., 0., 1.), phase=(0., 0.), clip=None):
    image, x, y = vector.rasterize(art, transform, phase, clip, alpha_only=True)
    return image.size, x, y, image.tobytes()


def legacy(monkeypatch, native, art, transform=(1., 0., 0., 1.), phase=(0., 0.), clip=None):
    with monkeypatch.context() as context:
        context.setattr(vector, "_native", SimpleNamespace(
            fill_mask=native.fill_mask, stroke_mask=native.stroke_mask))
        return stamp(art, transform, phase, clip)


def polygon_art():
    return {"bounds": [-2., -3., 10., 8.], "paths": [
        {"commands": [["M", -2., 0.], ["L", 7., 0.], ["L", 9., 8.], ["Z"]],
         "fill": [100, 100, 100, 255], "stroke": [0, 0, 0, 255], "stroke_width": 0.},
        {"commands": [["M", 1., 2.], ["Q", 8., -3., 10., 5.]],
         "fill": None, "stroke": [0, 0, 0, 255], "stroke_width": 1.25},
    ]}


def test_compiled_operation_does_not_use_legacy_python_path_operations(monkeypatch, native):
    art = polygon_art()
    expected = legacy(monkeypatch, native, art)

    def fail(*args, **kwargs):
        pytest.fail("Full-artwork mask must perform path preparation and unions in C")

    monkeypatch.setattr(vector, "_contours", fail)
    monkeypatch.setattr(vector, "_fill_mask", fail)
    monkeypatch.setattr(vector, "_stroke_mask", fail)
    assert stamp(art) == expected


def test_compile_cache_notices_in_place_public_artwork_edits(monkeypatch, native):
    art = polygon_art()
    before = stamp(art)
    first = vector._compiled_art_cache[id(art)][2]
    assert stamp(art) == before
    assert vector._compiled_art_cache[id(art)][2] is first
    art["paths"][0]["commands"][1][1] = 3.5
    after = stamp(art)
    assert after != before
    assert after == legacy(monkeypatch, native, art)
    assert vector._compiled_art_cache[id(art)][2] is not first
    art["paths"][0]["stroke_width"] = 3.75
    assert stamp(art) == legacy(monkeypatch, native, art)


def test_compile_cache_is_bounded_and_holds_original_identity(monkeypatch, native):
    monkeypatch.setattr(vector, "_COMPILED_ART_CACHE_LIMIT", 3)
    arts = [polygon_art() for _ in range(4)]
    for art in arts:
        stamp(art)
    assert len(vector._compiled_art_cache) == 3
    assert id(arts[0]) not in vector._compiled_art_cache
    for art in arts[1:]:
        assert vector._compiled_art_cache[id(art)][0] is art


def test_translucent_paths_keep_source_over_alpha(monkeypatch, native):
    art = polygon_art()
    art["paths"][0]["fill"][3] = 127
    expected = legacy(monkeypatch, native, art)

    def fail(*args, **kwargs):
        pytest.fail("Translucent artwork must use the source-over fallback")

    monkeypatch.setattr(vector, "_compiled_art", fail)
    assert stamp(art) == expected


def test_all_ninja_frames_varied_scales_phases_rotations_and_clips(monkeypatch, native):
    assets = Path(__file__).resolve().parents[1] / "nv14_assets"
    manifest = json.loads((assets / "manifest.json").read_text())
    pack = json.loads((assets / manifest["vectors"]["file"]).read_text())
    rng = random.Random(410)
    for frame in manifest["ninja"]["frames"].values():
        art = pack["sprites"][frame["vector"]]
        for scale in (.125, 1., 2., 4.):
            theta = rng.uniform(-math.pi, math.pi)
            c, s = math.cos(theta)*scale, math.sin(theta)*scale
            facing = rng.choice((-1, 1))
            transform = (c*facing, -s, s*facing, c)
            phase = rng.random(), rng.random()
            clip = None if rng.random() < .5 else (-11, -7, 13, 19)
            assert stamp(art, transform, phase, clip) == legacy(
                monkeypatch, native, art, transform, phase, clip)


def test_adaptive_quadratics_holes_singular_and_skewed_transforms(monkeypatch, native):
    art = polygon_art()
    art["paths"].append({
        "commands": [["M", -1, -1], ["L", 9, -1], ["L", 9, 7], ["L", -1, 7], ["Z"],
                     ["M", 2, 2], ["L", 6, 2], ["L", 6, 5], ["L", 2, 5], ["Z"]],
        "fill": [1, 2, 3, 255.0], "stroke": None})
    for transform in ((1., 0., 0., 1.), (1., 0., 0., 0.), (0., 0., 0., 0.),
                      (-2., .5, 1.7, 3.), (12., -2., 5., 10.)):
        assert stamp(art, transform, (.3, .8), (-100, -100, 100, 100)) == legacy(
            monkeypatch, native, art, transform, (.3, .8), (-100, -100, 100, 100))
    # Put the adaptive subdivision threshold and its adjacent binary64 values
    # into the error expression, so Python's hypot tie behaviour is exercised.
    for y in (.25, math.nextafter(.25, 0.), math.nextafter(.25, 1.)):
        art["paths"][1]["commands"] = [["M", 0., 0.], ["Q", .25, y, .5, 0.]]
        assert stamp(art) == legacy(monkeypatch, native, art)


def test_shared_compiled_workspace_is_thread_safe(monkeypatch, native):
    art = polygon_art()
    cases = [((4., .2, -.3, 3.), (i/37., i/43.)) for i in range(24)]
    expected = [legacy(monkeypatch, native, art, m, phase) for m, phase in cases]
    stamp(art)  # All concurrent calls reuse the same compiled capsule.
    with ThreadPoolExecutor(max_workers=8) as pool:
        actual = list(pool.map(lambda case: stamp(art, *case), cases))
    assert actual == expected


def test_native_compilation_rejects_invalid_commands_and_alpha(native):
    art = polygon_art()
    art["paths"][0]["commands"][0][0] = ""
    with pytest.raises(ValueError, match="Unsupported"):
        native.compile_art(art["paths"])
    art = polygon_art()
    art["paths"][0]["stroke"][3] = 127
    with pytest.raises(ValueError, match="opaque"):
        native.compile_art(art["paths"])
    capsule = native.compile_art([])
    with pytest.raises(ValueError):
        native.alpha_mask(capsule, -1, 4, (1., 0., 0., 1.), (0., 0.), (0., 0.), 1.)
