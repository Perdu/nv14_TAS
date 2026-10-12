"""Exact native/Python parity for original artwork and difficult coverage cases."""
import json
import math
from pathlib import Path
import random
import subprocess
import sys

import pytest

Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")
import nv14_vector as vector

ASSETS = Path(__file__).resolve().parents[1] / "nv14_assets"


@pytest.fixture
def native():
    return pytest.importorskip("_nv14_render_native")


def test_vector_import_does_not_load_pillow_or_native_renderer():
    subprocess.run([sys.executable, "-c", "import sys, nv14_vector; "
                    "assert '_nv14_render_native' not in sys.modules; "
                    "assert 'PIL' not in sys.modules"], check=True)


def test_native_masks_match_fallback_including_holes_round_caps_and_grid_fit(native):
    rng = random.Random(409)
    sets = [
        [], [[]], [[(0., 0.)]],
        [[(4., 4.), (4., 4.)]],
        [[(1., 4.), (28., 4.), (28., 28.), (1., 28.), (1., 4.)]],
        [[(0., 0.), (32., 0.), (32., 32.), (0., 32.)],
         [(8., 8.), (24., 8.), (24., 24.), (8., 24.)]],
        [[(-10000., 4.), (10000., 4.)]],
        [[(4.4999999, 4.), (4.5000001, 28.)]],
    ]
    sets += [[[(rng.uniform(-10, 40), rng.uniform(-10, 40))
               for _ in range(rng.randint(2, 12))]] for _ in range(25)]
    size = (32, 32)
    for contours in sets:
        assert native.fill_mask(*size, contours) == vector._fill_mask_python(
            size, contours, Image, ImageDraw).tobytes()
        for width in (0., .1, 1., 4., 5.5, 12.):
            for fit in (False, True):
                assert native.stroke_mask(*size, contours, width, fit) == (
                    vector._stroke_mask_python(size, contours, width, Image,
                                               grid_fit=fit).tobytes())


def test_strict_capsule_boundary_matches_python_power_rounding(native):
    # At this pixel the radius squared equals multiplication of the residual,
    # but Python's libm pow-based **2 rounds down one ULP: the sample is inside.
    residual = -1.820467805551365
    contours = [[(.5-residual, .5), (.5-residual, .5)]]
    width = -2*residual
    expected = vector._stroke_mask_python((8, 8), contours, width, Image,
                                          grid_fit=False).tobytes()
    assert native.stroke_mask(8, 8, contours, width, False) == expected


def compare_art(monkeypatch, native, art, transform, phase=(0., 0.), clip=None):
    monkeypatch.setattr(vector, "_native_checked", True)
    monkeypatch.setattr(vector, "_native", None)
    expected, x, y = vector.rasterize(art, transform, phase, clip)
    monkeypatch.setattr(vector, "_native", native)
    actual, ax, ay = vector.rasterize(art, transform, phase, clip)
    assert (ax, ay, actual.size, actual.tobytes()) == (x, y, expected.size, expected.tobytes())
    alpha, ax, ay = vector.rasterize(art, transform, phase, clip, alpha_only=True)
    assert alpha.mode == "L"
    assert (ax, ay, alpha.size, alpha.tobytes()) == (
        x, y, expected.size, expected.getchannel("A").tobytes())


def test_every_bundled_sprite_has_exact_native_rgba_and_alpha_coverage(monkeypatch, native):
    manifest = json.loads((ASSETS / "manifest.json").read_text())
    pack = json.loads((ASSETS / manifest["vectors"]["file"]).read_text())
    for name, art in pack["sprites"].items():
        try:
            compare_art(monkeypatch, native, art, (1., 0., 0., 1.), (.23, .77))
        except AssertionError as error:
            raise AssertionError(f"Native parity failed for {name}") from error


@pytest.mark.parametrize("scale,angle,facing", [(1, 0, 1), (2, 31, -1), (3, 90, 1),
                                                (4, -127, -1), (.25, 17, 1)])
def test_ninja_subpixel_rotated_mirrored_and_clipped_parity(monkeypatch, native, scale, angle, facing):
    manifest = json.loads((ASSETS / "manifest.json").read_text())
    pack = json.loads((ASSETS / manifest["vectors"]["file"]).read_text())
    theta = math.radians(angle)
    co, si = math.cos(theta) * scale, math.sin(theta) * scale
    transform = (co * facing, -si, si * facing, co)
    frames = list(manifest["ninja"]["frames"].values())
    for info in frames[::max(1, len(frames) // 10)]:
        compare_art(monkeypatch, native, pack["sprites"][info["vector"]],
                    transform, (.125, .875), (-30, -30, 30, 30))


def test_translucent_alpha_and_singular_transforms_remain_exact(monkeypatch, native):
    art = {"bounds": [-4., -4., 12., 12.], "paths": [
        {"commands": [["M", -4, -4], ["L", 12, -4], ["L", 12, 12], ["L", -4, 12], ["Z"]],
         "fill": [100, 50, 210, 37], "stroke": [5, 10, 100, 127], "stroke_width": .25},
        {"commands": [["M", -4, 4], ["Q", 5, 15, 12, 4], ["L", -4, 4]],
         "fill": [255, 0, 0, 128], "stroke": [255, 255, 255, 183], "stroke_width": 1.5},
    ]}
    for transform in ((1., 0., 0., 1.), (1., 0., 0., 0.), (0., 0., 0., 0.)):
        compare_art(monkeypatch, native, art, transform, (.5, .5))
        compare_art(monkeypatch, native, art, transform, (.5, .5), (100, 100, 101, 101))


def test_missing_extension_uses_python_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "_nv14_render_native", None)
    monkeypatch.setattr(vector, "_native_checked", False)
    monkeypatch.setattr(vector, "_native", None)
    assert not vector.native_backend_available()
    contours = [[(1., 4.), (28., 4.)]]
    assert vector._stroke_mask((32, 32), contours, 4., Image).tobytes() == (
        vector._stroke_mask_python((32, 32), contours, 4., Image).tobytes())


def test_native_rejects_invalid_mask_sizes_and_nonfinite_geometry(native):
    with pytest.raises(ValueError):
        native.fill_mask(-1, 10, [])
    with pytest.raises(ValueError):
        native.stroke_mask(10, 10, [[(math.nan, 0), (1, 1)]], 4.)
    with pytest.raises(ValueError):
        native.stroke_mask(10, 10, [], math.inf)
