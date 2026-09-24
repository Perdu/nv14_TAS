"""Source registration and layer composition of immutable object visuals."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")
from nv14_object_visuals import BeamVisual, ObjectVisual, ObjectVisualSystem, SpriteVisual
from nv14_render import BACKGROUND, SceneRenderer


COLORS = {
    "gold": (240, 200, 0), "drone": (30, 40, 50),
    "door": (50, 100, 150), "door_switch": (150, 100, 50),
    "exit": (20, 120, 220), "exit_switch": (220, 120, 20),
    "rocket": (200, 10, 20), "turret_crosshair": (10, 200, 20),
    "laser_blast": (200, 20, 200), "homing_launcher": (50, 60, 70),
    "turret": (70, 60, 50),
}


@pytest.fixture
def renderer(tmp_path):
    source = Path(__file__).resolve().parents[1] / "nv14_assets" / "manifest.json"
    manifest = json.loads(source.read_text())
    clips = manifest["object_animations"]["clips"]
    for name, color in COLORS.items():
        Image.new("RGBA", (8, 8), (*color, 255)).save(tmp_path / f"{name}.png")
        info = {"file": f"{name}.png", "origin": [4, 4], "pixels_per_unit": 2}
        clips[name]["frames"] = {key: dict(info) for key in clips[name]["frames"]}
    eye = Image.new("RGBA", (8, 8))
    eye.putpixel((6, 4), (255, 0, 0, 255))
    eye.save(tmp_path / "eye.png")
    for name in ("drone_eye", "drone_chaingun_eye"):
        manifest["objects"][name] = {"file": "eye.png", "origin": [4, 4], "pixels_per_unit": 1}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return SceneRenderer("0" * 713 + "|5^400,400", assets_path=tmp_path)


def scene(objects):
    return {"frame": 0, "objects": objects, "visual": {"visible": False},
            "player": {"pos": (400., 400.), "oldpos": (400., 400.)}}


def obj(identifier, kind, x=100., y=100., **extras):
    return {"id": identifier, "load_index": identifier, "kind": kind,
            "x": x, "y": y, **extras}


def test_collected_gold_uses_clip_visibility_and_render_cannot_age_it(renderer):
    state = scene([obj(1, "gold", visible=True)])
    tracker = ObjectVisualSystem(renderer.manifest)
    tracker.reset(state)
    collected = deepcopy(state)
    collected["frame"] = 1
    collected["objects"][0]["visible"] = False
    visuals = tracker.update(collected)
    saved = deepcopy(collected)
    assert visuals[0].body.frame == 2 and visuals[0].body.visible
    for _ in range(3):
        assert renderer.render(collected, object_visuals=visuals).getpixel((100, 100)) == COLORS["gold"]
        assert tracker.snapshot() == visuals
        assert collected == saved
    hidden = tracker.advance(28)
    assert hidden[0].body.frame == 30 and not hidden[0].body.visible
    assert renderer.render(collected, object_visuals=hidden).getpixel((100, 100)) == BACKGROUND


@pytest.mark.parametrize("kind", ["drone_zap", "drone_chaingun"])
def test_drone_eye_uses_display_pose_and_source_clockwise_rotation(renderer, kind):
    state = scene([obj(1, kind, x=300., y=300.)])
    visual = ObjectVisual(1, SpriteVisual("drone", 2, 100., 120.), eye_rotation=90.)
    image = renderer.render(state, object_visuals=[visual])
    assert image.getpixel((99, 122)) == (255, 0, 0)
    assert image.getpixel((299, 302)) == BACKGROUND
    # Hiding the parent also hides its attached eye clip.
    hidden = replace(visual, body=replace(visual.body, visible=False))
    assert renderer.render(state, object_visuals=[hidden]).getpixel((99, 122)) == BACKGROUND


@pytest.mark.parametrize("scale", [1, 2])
def test_laser_prefire_hairline_remains_one_device_pixel(renderer, scale):
    renderer = SceneRenderer(renderer.level, assets_path=renderer.assets_path, scale=scale)
    state = scene([obj(1, "drone_laser")])
    body = SpriteVisual("drone", 29, 30., 30., visible=False)
    visual = ObjectVisual(1, body, beam=BeamVisual((100., 100.), (120., 100.), "#cb7579", 0.))
    image = renderer.render(state, object_visuals=[visual])
    column = [image.getpixel((110 * scale, y)) for y in range(96 * scale, 105 * scale)]
    assert column.count((203, 117, 121)) == 1
    firing = replace(visual, beam=replace(visual.beam, color="#882222", width=3.))
    image = renderer.render(state, object_visuals=[firing])
    column = [image.getpixel((110 * scale, y)) for y in range(96 * scale, 105 * scale)]
    # Odd device widths centred on integer coordinates straddle two edge
    # rows. Integrated coverage, including those half-covered rows, is 3*s.
    assert sum((202 - rgb[0]) / (202 - 136) for rgb in column) == pytest.approx(3 * scale)


def test_blast_applies_dynamic_scale_once_and_uses_endpoint_registration(renderer):
    state = scene([obj(1, "drone_laser", x=300., y=300.)])
    body = SpriteVisual("drone", 29, 30., 30., visible=False)
    blast = SpriteVisual("laser_blast", 1, 100., 120., scale_x=0., scale_y=0.)
    visual = ObjectVisual(1, body, blast=blast)
    assert renderer.render(state, object_visuals=[visual]).getpixel((100, 120)) == BACKGROUND
    visual = replace(visual, blast=replace(blast, scale_x=2., scale_y=2.))
    image = renderer.render(state, object_visuals=[visual])
    assert image.getpixel((96, 120)) == COLORS["laser_blast"]
    assert image.getpixel((103, 120)) == COLORS["laser_blast"]
    assert image.getpixel((95, 120)) == BACKGROUND
    assert image.getpixel((104, 120)) == BACKGROUND


@pytest.mark.parametrize("kind,field,clip", [
    ("homing", "rocket", "rocket"), ("turret", "crosshair", "turret_crosshair"),
])
@pytest.mark.parametrize("weapon_first", [True, False])
def test_weapon_clips_keep_source_object_layer_registration_order(renderer, kind, field, clip, weapon_first):
    weapon_id, gold_id = (1, 2) if weapon_first else (2, 1)
    weapon = obj(weapon_id, kind, x=300., y=300.)
    gold = obj(gold_id, "gold", visible=True)
    state = scene([weapon, gold] if weapon_first else [gold, weapon])
    body_clip, body_frame = ("homing_launcher", 1) if kind == "homing" else ("turret", 29)
    weapon_visual = ObjectVisual(weapon_id, SpriteVisual(body_clip, body_frame, 300., 300.),
                                 **{field: SpriteVisual(clip, 1, 100., 100.)})
    gold_visual = ObjectVisual(gold_id, SpriteVisual("gold", 1, 100., 100.))
    image = renderer.render(state, object_visuals=[weapon_visual, gold_visual])
    # Both are LAYER_OBJECTS; AS CreateSprite allocates increasing depths.
    assert image.getpixel((100, 100)) == COLORS["gold" if weapon_first else clip]
    # The weapon is drawn at its own retained pose rather than at its base.
    assert image.getpixel((300, 300)) == COLORS[body_clip]


def test_exit_trigger_follows_its_door_at_the_same_wall_registration(renderer):
    # Native ids split the exit switch before the door. AS constructs the
    # body's wall clip first and its trigger second, so the switch is above.
    switch = obj(1, "exit_switch", load_index=1)
    door = obj(2, "exit_door", load_index=1)
    state = scene([switch, door])
    visuals = [ObjectVisual(1, SpriteVisual("exit_switch", 1, 100., 100.)),
               ObjectVisual(2, SpriteVisual("exit", 1, 100., 100.))]
    image = renderer.render(state, object_visuals=visuals)
    assert image.getpixel((100, 100)) == COLORS["exit_switch"]


@pytest.mark.parametrize("locked,trap,frame", [(False, False, 34), (True, False, 55), (False, True, 54)])
@pytest.mark.parametrize("horizontal,delta,x,y,rotation", [
    (False, 0, 227., 240., 0.), (False, -1, 252., 240., 180.),
    (True, 0, 240., 227., 90.), (True, -1, 240., 252., 270.),
])
def test_door_source_registration_and_switch_scale(renderer, locked, trap, frame,
                                                  horizontal, delta, x, y, rotation):
    params = [100, 100, int(horizontal), int(trap), 9, 9, int(locked),
              0 if horizontal else delta, delta if horizontal else 0]
    state = scene([obj(1, "testdoor", parameters=params, door_x=240., door_y=240.,
                       horizontal=horizontal, is_open=False, is_locked=locked, is_trap=trap)])
    visual, = ObjectVisualSystem(renderer.manifest).reset(state)
    assert (visual.body.x, visual.body.y, visual.body.rotation, visual.body.frame) == (x, y, rotation, frame)
    image = renderer.render(state, object_visuals=[visual])
    assert image.getpixel((round(x), round(y))) == COLORS["door"]
    if locked or trap:
        assert (visual.trigger.x, visual.trigger.y) == (100., 100.)
        assert visual.trigger.scale_x == visual.trigger.scale_y == (2 / 3 if trap else 1.)
        assert image.getpixel((100, 100)) == COLORS["door_switch"]
    else:
        assert visual.trigger is None
        assert image.getpixel((100, 100)) == BACKGROUND
