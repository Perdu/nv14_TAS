"""Exact dirty-region composition and reusable rendering preparation."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

Image = pytest.importorskip("PIL.Image")
from nv14_object_visuals import BeamVisual, ObjectVisual, ObjectVisualSystem, SpriteVisual
from nv14_particles import Particle
from nv14_render import BACKGROUND, SceneRenderer

LEVEL = "0" * 713 + "|5^100,100"


def scene(x=100., y=100., objects=()):
    return {"frame": 0, "objects": list(objects), "visual": {
        "x": x, "y": y, "frame": 1, "visible": True,
        "facing": 1, "rotation_deg": 0.},
        "player": {"pos": (x, y), "oldpos": (x, y)}}


@pytest.mark.parametrize("scale", [1, 2])
def test_dirty_objects_ghosts_layers_and_alpha_terrain_match_full_redraw(scale):
    tiles = list("0" * 713)
    tiles[3*23+3], tiles[4*23+3], tiles[3*23+4] = "2", ":", "A"
    level = "".join(tiles) + "|5^100,100"
    incremental = SceneRenderer(level, scale=scale)
    full = SceneRenderer(level, scale=scale, incremental=False)
    old_frames = []
    for tick in range(12):
        objects = [
            {"id": 1, "load_index": 1, "kind": "gold", "x": 110., "y": 106., "visible": tick < 6},
            {"id": 2, "load_index": 2, "kind": "homing", "x": 160., "y": 112.,
             "rocket_visible": tick < 8, "rocket_x": 110.+tick, "rocket_y": 116.,
             "rocket_rotation_deg": tick * 7.5},
            {"id": 3, "load_index": 3, "kind": "turret", "x": 132., "y": 106.,
             "crosshair_visible": tick > 2, "aim": (130.+tick, 117.-tick), "mode": tick % 3},
            {"id": 4, "load_index": 4, "kind": "testdoor", "x": 136., "y": 100.,
             "door_x": 205., "door_y": 208., "horizontal": False, "is_open": tick > 8},
        ]
        state = scene(105.1+tick*.31, 108.+tick*.7, objects)
        state["visual"].update(frame=tick+1, rotation_deg=tick*13.75, facing=-1 if tick%2 else 1)
        # Both front/back sprites disappear and overlap players/antialiasing.
        particles = [Particle("debugDustMC1", 110.+tick, 110., frame=1,
                              scale_x=.3, scale_y=.5, rotation=35., layer="back"),
                     Particle("debugFireBallMC1", 111., 110.+tick, frame=1,
                              scale_x=.5, scale_y=.5, layer="front")][:tick % 3]
        ghosts = [{**state["visual"], "x": 111.-tick*.25,
                   "color": (60, 99, 143), "rotation_deg": -tick*15.5},
                  {**state["visual"], "x": 110., "color": (150, 40, 80)}][:1+tick%2]
        options = dict(particles=particles, secondary_players=ghosts,
                       show_primary_player=tick % 4 != 0)
        saved = deepcopy((state, options))
        expected = full.render(state, **options).tobytes()
        actual = incremental.render(state, **options)
        assert actual.tobytes() == expected, f"mismatched frame {tick}, scale {scale}"
        assert (state, options) == saved
        old_frames.append((actual, expected))
    for image, expected in old_frames:
        assert image.tobytes() == expected
    assert incremental.stats["dirty_frames"] >= 1
    assert incremental.stats["command_cache_hits"] > 0
    assert incremental.stats["drawn_pixels"] < 12 * incremental.size[0] * incremental.size[1]


def test_collection_and_terminal_clip_tail_remain_exact():
    renderer = SceneRenderer(LEVEL)
    full = SceneRenderer(LEVEL, incremental=False)
    state = scene(objects=[{"id": 1, "load_index": 1, "kind": "gold",
                            "x": 130., "y": 110., "visible": True}])
    tracker = ObjectVisualSystem(renderer.manifest)
    visuals = tracker.reset(state)
    assert renderer.render(state, object_visuals=visuals).tobytes() == full.render(state, object_visuals=visuals).tobytes()
    state["objects"][0]["visible"] = False
    state["frame"] = 1
    visuals = tracker.update(state)
    for tick in range(35):
        assert renderer.render(state, object_visuals=visuals).tobytes() == full.render(state, object_visuals=visuals).tobytes()
        visuals = tracker.advance(1)
    assert not visuals[0].body.visible
    assert renderer.stats["dirty_frames"] > 0
    assert renderer.stats["unchanged_frames"] > 0


def test_long_clipped_lines_and_fallback_circles_match_full_redraw(tmp_path):
    # Deliberately minimal external pack exercises line/circle fallback paths.
    manifest = {"schema_version": 1, "objects": {}, "particles": {"clips": {
        "trail": {"frames": {"1": {"line": {"color": "#a14b7c", "opacity": .35,
                                                  "points": [[-500, 0], [500, 0]]}}}}}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    incremental = SceneRenderer(LEVEL, assets_path=tmp_path)
    full = SceneRenderer(LEVEL, assets_path=tmp_path, incremental=False)
    state = scene(objects=[{"id": 1, "kind": "turret", "x": 100., "y": 100.,
                            "crosshair_visible": True, "aim": (111., 120.)}])
    state["visual"]["visible"] = False
    for index, rotation in enumerate((0., 23.3, 45., 90., 155., 210.)):
        state["objects"][0]["aim"] = (111.+index*3.7, 120.+index*.5)
        particle = Particle("trail", 200.+index*11., 300., rotation=rotation)
        assert incremental.render(state, particles=[particle]).tobytes() == full.render(state, particles=[particle]).tobytes()
    # A giant laser requests full-frame fallback instead of thousands of patches.
    assert incremental.stats["full_frames"] > 1


def test_translucent_hairline_uses_same_pixels_as_original_full_overlay(tmp_path):
    manifest = {"schema_version": 1, "objects": {}, "particles": {"clips": {
        "trail": {"frames": {"1": {"line": {"color": "#a14b7c", "opacity": .35,
                                                  "points": [[-500, 0], [500, 0]]}}}}}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    renderer = SceneRenderer(LEVEL, assets_path=tmp_path, scale=2)
    import math
    for angle in (0., 23.3, 45., 90., 155., 210.):
        p = Particle("trail", 200., 300., rotation=angle)
        result = renderer.render({"objects": [], "visual": {"visible": False}}, particles=[p])
        expected = renderer._background.copy()
        overlay = Image.new("RGBA", renderer.size)
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        renderer._line(overlay, [(p.x+c*x, p.y+s*x) for x in (-500, 500)],
                       (161, 75, 124, round(255*.35)))
        expected.paste(overlay, (0, 0), overlay)
        expected.paste(renderer._tiles, (0, 0), renderer._tiles)
        assert result.tobytes() == expected.tobytes()


def test_render_into_is_exact_bounded_and_keeps_returned_images_independent(monkeypatch):
    renderer = SceneRenderer(LEVEL)
    state = scene()
    original = renderer.render(state)
    expected = original.tobytes()
    target = bytearray(len(expected))
    original.putpixel((100, 100), (255, 0, 255))
    # Direct output must not fall back to a complete temporary image byte string.
    monkeypatch.setattr(Image.Image, "tobytes", lambda *args, **kwargs: pytest.fail("full-frame bytes allocation"))
    renderer.render_into(state, target)
    assert target == expected
    old_stats = dict(renderer.stats)
    renderer.reset_frame_cache()
    renderer.render_into(state, target)
    assert renderer.stats["full_frames"] == old_stats["full_frames"] + 1
    assert target == expected
    with pytest.raises(ValueError, match="size"):
        renderer.render_into(state, bytearray(10))
    with pytest.raises(ValueError, match="writable"):
        renderer.render_into(state, bytes(target))
    with pytest.raises(ValueError, match="contiguous"):
        renderer.render_into(state, memoryview(target)[::2])


def test_preparation_cache_reuses_geometry_but_detects_custom_asset_changes(tmp_path, monkeypatch):
    first = SceneRenderer(LEVEL, terrain=(117, 123, 138))
    def forbidden(*args):
        pytest.fail("terrain rasterised again")
    monkeypatch.setattr(SceneRenderer, "_terrain_layer", forbidden)
    second = SceneRenderer(LEVEL, terrain=(117, 123, 138))
    assert second._tiles is first._tiles
    assert second.stats["terrain_cache_hits"] == 1
    manifest = {"schema_version": 1, "objects": {}, "extra": {"value": 1}}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    a = SceneRenderer(LEVEL, terrain=(117, 123, 138), assets_path=tmp_path)
    a.manifest["extra"]["value"] = 33
    b = SceneRenderer(LEVEL, terrain=(117, 123, 138), assets_path=tmp_path)
    assert b.manifest["extra"]["value"] == 1
    manifest["extra"]["value"] = 2
    path.write_text(json.dumps(manifest))
    c = SceneRenderer(LEVEL, terrain=(117, 123, 138), assets_path=tmp_path)
    assert c.manifest["extra"]["value"] == 2


@pytest.mark.parametrize("scale", [1, 2, 3])
def test_wide_laser_dirty_patch_regression_matches_full_viewport(scale):
    incremental = SceneRenderer(LEVEL, scale=scale)
    full = SceneRenderer(LEVEL, scale=scale, incremental=False)
    beam = {"id": 1, "load_index": 1, "kind": "drone_laser",
            "x": 200., "y": 200., "beam_visible": True,
            "beam_start": (152., -60.), "beam_end": (14., 124.)}
    for x, y in ((86., 30.), (90., 34.)):
        state = scene(x, y, [beam])
        assert incremental.render(state).tobytes() == full.render(state).tobytes()
    # Coverage masks are translation invariant when pasted into dirty patches;
    # lasers no longer need the old Pillow wide-line full-viewport fallback.
    assert incremental.stats["full_frames"] == 1
    assert incremental.stats["dirty_frames"] == 1


def test_randomized_primitive_redraws_match_original_viewport():
    from PIL import ImageDraw
    from nv14_render_commands import Command, dirty_regions, intersects
    import random
    rng = random.Random(4192)
    size = (100, 100)
    for width in (1, 2, 3, 4, 8, 12, 21):
        for trial in range(100):
            points = tuple((rng.randrange(-150, 250), rng.randrange(-150, 250))
                           for _ in range(2 + trial % 2))
            bounds = (min(x for x, y in points)-width, min(y for x, y in points)-width,
                      max(x for x, y in points)+width+1, max(y for x, y in points)+width+1)
            line = Command("line", (points, (99, 44, 155), width), bounds)
            line.key = ("line", 0)
            x, y = rng.randrange(70), rng.randrange(70)
            old_marker = Command("paste", ((220, 80, 30), (x, y, x+14, y+14), None),
                                 (x, y, x+14, y+14))
            old_marker.key = ("player", 0)
            rect = (x+2, y+2, x+16, y+16)
            new_marker = Command("paste", ((220, 80, 30), rect, None), rect)
            new_marker.key = old_marker.key
            before, after = [line, old_marker], [line, new_marker]
            expected = Image.new("RGB", size, BACKGROUND)
            # Independent direct Pillow reference in original device coordinates.
            ImageDraw.Draw(expected).line(points, fill=(99, 44, 155), width=width)
            expected.paste((220, 80, 30), rect)
            regions = dirty_regions(before, after, size)
            if regions is None:
                actual = Image.new("RGB", size, BACKGROUND)
                for command in after:
                    command.draw(actual)
            else:
                actual = Image.new("RGB", size, BACKGROUND)
                for command in before:
                    command.draw(actual)
                for region in regions:
                    patch = Image.new("RGB", (region[2]-region[0], region[3]-region[1]), BACKGROUND)
                    for command in after:
                        if intersects(command.bounds, region):
                            command.draw(patch, region[:2])
                    actual.paste(patch, region[:2])
            assert actual.tobytes() == expected.tobytes(), (width, trial, points)


def test_randomized_translucent_lines_match_v409_full_overlay(tmp_path):
    from PIL import ImageDraw
    import random
    rng = random.Random(4910)
    manifest = {"schema_version": 1, "objects": {}, "particles": {"clips": {
        "trail": {"frames": {"1": {"line": {"color": "#a14b7c", "opacity": .35,
                                                  "points": [[0, 0], [10, 10]]}}}}}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    renderer = SceneRenderer(LEVEL, assets_path=tmp_path)
    # Exercise exact old/new rasterisation on a compact viewport, independent
    # of terrain and player setup. _particles only needs size, scale and assets.
    renderer.size = (100, 100)
    info = renderer.manifest["particles"]["clips"]["trail"]["frames"]["1"]["line"]
    for width in (1, 2, 3, 4, 8):
        renderer.scale = width
        cases = [[(19, 145), (103, -135)], [(15, 40), (167, 152)]]
        cases += [[(rng.randrange(-150, 250), rng.randrange(-150, 250))
                   for _ in range(2 + index % 2)] for index in range(100)]
        for device in cases:
            info["points"] = [[x/width, y/width] for x, y in device]
            actual = Image.new("RGB", renderer.size, BACKGROUND)
            renderer._particles(actual, [Particle("trail", 0., 0.)], "front")
            expected = Image.new("RGB", renderer.size, BACKGROUND)
            overlay = Image.new("RGBA", renderer.size)
            ImageDraw.Draw(overlay).line(device, fill=(161, 75, 124, round(255*.35)), width=width)
            expected.paste(overlay, (0, 0), overlay)
            assert actual.tobytes() == expected.tobytes(), (width, device)
