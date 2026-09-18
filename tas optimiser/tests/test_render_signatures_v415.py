"""Render-only invalidation and colour-independent gold shading."""
from copy import deepcopy
from dataclasses import replace

import pytest

pytest.importorskip("PIL.Image")
from nv14_object_visuals import ObjectVisual, SpriteVisual
from nv14_render import SceneRenderer

LEVEL = "0" * 713 + "|5^100,100"


def scene(objects=()):
    return {"objects": list(objects), "visual": {"x": 100., "y": 100.,
            "frame": 1, "visible": True, "rotation_deg": 0., "facing": 1}}


def test_physics_fields_do_not_invalidate_draw_commands(monkeypatch):
    import nv14_render_commands
    renderer = SceneRenderer(LEVEL)
    state = scene([{"id": 1, "kind": "gold", "x": 150., "y": 100., "visible": True}])
    initial = renderer.render(state).tobytes()
    misses = renderer.stats["command_cache_misses"]
    monkeypatch.setattr(nv14_render_commands, "freeze", lambda value: pytest.fail("recursive scene freezing"))
    state["objects"][0].update(state_index=200, diagnostics={"huge": list(range(1000))})
    state["visual"].update(velocity=[2, 3], diagnostics={"tick": 20})
    assert renderer.render(state).tobytes() == initial
    assert renderer.stats["command_cache_misses"] == misses


def test_mutable_coordinates_and_parameters_invalidate_relevant_artwork():
    renderer, full = SceneRenderer(LEVEL), SceneRenderer(LEVEL, incremental=False)
    obj = {"id": 1, "kind": "oneway", "x": 150., "y": 130., "parameters": [150., 130., 0]}
    turret = {"id": 2, "kind": "turret", "x": 210., "y": 130.,
              "crosshair_visible": True, "aim": [230., 170.]}
    state = scene([obj, turret])
    for direction in range(4):
        obj["parameters"][2] = direction
        turret["aim"][0] += 3
        state["visual"]["x"] += .25
        saved = deepcopy(state)
        assert renderer.render(state).tobytes() == full.render(state).tobytes()
        assert state == saved


def test_collected_primary_gold_is_retained_until_its_artwork_hides():
    renderer, full = SceneRenderer(LEVEL), SceneRenderer(LEVEL, incremental=False)
    state = scene([{"id": 1, "kind": "gold", "x": 150., "y": 100., "visible": False}])
    visual = ObjectVisual(1, SpriteVisual("gold", 5, 150., 100.))
    assert renderer.render(state, object_visuals=[visual]).tobytes() == full.render(state, object_visuals=[visual]).tobytes()
    assert ("primary-gold", 0) in renderer._command_groups
    hidden = replace(visual, body=replace(visual.body, visible=False))
    assert renderer.render(state, object_visuals=[hidden]).tobytes() == full.render(state, object_visuals=[hidden]).tobytes()
    assert ("primary-gold", 0) not in renderer._command_groups
    # Rendering an earlier snapshot again must restore the piece.
    assert renderer.render(state, object_visuals=[visual]).tobytes() == full.render(state, object_visuals=[visual]).tobytes()


@pytest.mark.parametrize("scale", [1, 2, 4])
def test_gold_colours_share_rasterization_but_keep_exact_shading(monkeypatch, scale):
    import nv14_vector
    renderer = SceneRenderer(LEVEL, scale=scale)
    rasterize = nv14_vector.rasterize
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return rasterize(*args, **kwargs)
    monkeypatch.setattr(nv14_vector, "rasterize", counted)
    colors = [(53, 104, 168), (196, 55, 37), (36, 170, 94)]
    for phase in (0., .375):
        calls.clear()
        reference = renderer._Image.new("RGBA", renderer.size)
        renderer._sprite(reference, "gold", 150.+phase, 100., width=6)
        # Use untinted transformed pixels as the independent v4.14 tint input.
        original = next(value for key, value in reversed(list(renderer._transforms.items()))
                        if key[-1] is None)
        sprite, left, top = original
        for color in colors:
            actual = renderer._Image.new("RGBA", renderer.size)
            renderer._sprite(actual, "gold", 150.+phase, 100., width=6,
                             tint=color, shaded_tint=True)
            expected = renderer._Image.new("RGBA", renderer.size)
            tinted = renderer._tint_sprite(sprite, color, shaded=True)
            expected.paste(tinted, (int((150.+phase)*scale)+left, 100*scale+top), tinted)
            assert actual.tobytes() == expected.tobytes()
        assert len(calls) == 1
    assert renderer._gold_sources.bytes_used <= renderer._gold_sources.max_bytes
