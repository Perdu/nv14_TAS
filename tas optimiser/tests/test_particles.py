"""Render-only particle events, original artwork, lifetime and isolation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random

import pytest

from nv14_engine import InputFrame, Turret, parse_level_string
from nv14_particles import Particle, ParticleSystem
from nv14_replay import decode_complex_replay, parse_combined_level_replay

ROOT = Path(__file__).resolve().parents[1]
native = pytest.importorskip("_nv14_native")


@pytest.fixture(scope="module")
def manifest():
    return json.loads((ROOT / "nv14_assets/manifest.json").read_text())


def flat(objects="", x=100, y=134):
    tiles = ["0"] * 713
    for column in range(31):
        tiles[column * 23 + 5] = "1"
    return "".join(tiles) + f"|5^{x},{y}" + objects


def tracked(text, manifest, seed=0):
    state = native.parse_level_string(text, simulate_enemies=True).initial_state(track_visuals=True)
    effects = ParticleSystem(manifest, seed=seed)
    effects.reset(state.scene_snapshot())
    return state, effects


def tick(state, effects, frame=InputFrame()):
    state.step(frame)
    return effects.update(state.scene_snapshot(), frame)


def test_bundled_clip_frames_have_valid_provenance_and_registration(manifest):
    clips = manifest["particles"]["clips"]
    assert len(clips) == 28
    assert sum(len(c["frames"]) for c in clips.values()) == 413
    for clip in clips.values():
        assert set(clip["frames"]) == {str(i) for i in range(1, clip["remove_frame"])}
        for info in clip["frames"].values():
            path = ROOT / "nv14_assets" / info["file"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == info["sha256"]
            assert len(info["origin"]) == 2 and info["pixels_per_unit"] > 0


def test_actual_jump_emits_at_contact_and_false_trigger_emits_nothing(manifest):
    state, effects = tracked(flat(), manifest)
    tick(state, effects)
    assert not effects.snapshot()
    records = tick(state, effects, InputFrame(jump=True, jump_trigger=False))
    assert not records
    records = tick(state, effects, InputFrame(jump=True, jump_trigger=True))
    assert len(records) == 4 and all(p.symbol.startswith("debugDust") for p in records)
    assert all(p.x == pytest.approx(100) and p.y == pytest.approx(144) for p in records)
    # A held/ineffective trigger in the air cannot emit another jump burst.
    records = tick(state, effects, InputFrame(jump=True, jump_trigger=True))
    assert len(records) == 4 and all(p.frame == 4 for p in records)


def test_landing_skidding_and_wallsliding_have_dust(manifest):
    state, effects = tracked(flat(), manifest)
    tick(state, effects)
    for i in range(100):
        frame = InputFrame(right=i < 25, jump=10 <= i < 20)
        previous = state.player_snapshot()
        records = tick(state, effects, frame)
        current = state.player_snapshot()
        if previous["state"] > 2 and current["state"] in (1, 2):
            assert len([p for p in records if p.frame == 1 and "Dust" in p.symbol]) == 4
            break
    else:
        pytest.fail("Synthetic jump did not land")
    saw_skid = False
    for _ in range(30):
        records = tick(state, effects)
        saw_skid |= any(p.frame == 1 and "Dust" in p.symbol for p in records)
    assert saw_skid
    # A falling ninja pressing into a vertical wall exercises wall dust.
    tiles = ["0"] * 713
    for row in range(23):
        tiles[4 * 23 + row] = "1"
    state, effects = tracked("".join(tiles) + "|5^110,90", manifest)
    for _ in range(40):
        records = tick(state, effects, InputFrame(right=True))
        if state.player_snapshot()["state"] == 5 and any(p.frame == 1 for p in records):
            assert any("Dust" in p.symbol for p in records)
            break
    else:
        pytest.fail("No wallslide dust")


def test_mine_and_electrical_death_only_emit_once_then_expire(manifest):
    for descriptor, required in [("!12^100,134", "FireBurst"), ("!6^100,134,2,0,0,0", "Zap")]:
        state, effects = tracked(flat(descriptor), manifest)
        records = tick(state, effects)
        assert state.player_snapshot()["dead"]
        assert any(required in p.symbol for p in records)
        assert 6 <= sum("Blood" in p.symbol for p in records) <= 13
        assert effects.update(state.scene_snapshot()) == records
        assert tick(state, effects) == tuple(p for p in effects.snapshot())
        assert all(p.frame > 1 for p in effects.snapshot())
        before = state.snapshot()
        effects.advance(120)
        assert effects.snapshot() == ()
        assert state.snapshot() == before


def test_rocket_smoke_and_explosion_use_retained_rocket_position(manifest):
    state, effects = tracked(flat("!10^300,100"), manifest)
    smoked = False
    for _ in range(250):
        before = state.scene_snapshot()
        records = tick(state, effects)
        smoked |= any("RocketSmoke" in p.symbol for p in records)
        after = state.scene_snapshot()
        rocket = after["objects"][0]
        if before["objects"][0]["rocket_visible"] and not rocket["rocket_visible"]:
            burst = next(p for p in records if "FireBurst" in p.symbol and p.frame == 1)
            assert (burst.x, burst.y) == (rocket["rocket_x"], rocket["rocket_y"])
            assert smoked
            break
    else:
        pytest.fail("No rocket explosion")


def test_laser_charge_and_chaingun_flash(manifest):
    for weapon, required in [(1, "LaserCharge"), (2, "ChainFlash")]:
        state, effects = tracked(flat(f"!6^300,108,2,0,{weapon},2"), manifest)
        for _ in range(180):
            records = tick(state, effects)
            if any(required in p.symbol for p in records):
                break
            assert not state.player_snapshot()["dead"]
        else:
            pytest.fail(f"No {required}")


def test_gauss_cancellation_and_repeated_identical_endpoint(manifest):
    state, effects = tracked(flat("!3^300,100"), manifest)
    before = state.scene_snapshot()
    old = before["objects"][0]
    old.update(mode=2, fire_delay_timer=9, target=(100., 124.))
    after = deepcopy(before)
    after["frame"] += 1
    obj = after["objects"][0]
    obj.update(mode=3, fire_delay_timer=0, view=(200., 117.))  # LOS stopped by wall
    effects.reset(before)
    assert not effects.update(after)
    obj["view"] = (100., 124.)  # valid LOS; target unchanged since a prior shot
    effects.reset(before)
    records = effects.update(after)
    assert sum("TurretBullet" in p.symbol for p in records) == 1
    assert sum("TurretDebris" in p.symbol for p in records) == 2


def test_real_gauss_events_match_reference_firing_calls(manifest, monkeypatch):
    replay = parse_combined_level_replay((ROOT / "tests/example_28_3_turrets.txt").read_text())
    frames = decode_complex_replay(replay.replay_string).frames
    state, effects = tracked(replay.level_string, manifest)
    level = parse_level_string(replay.level_string, simulate_enemies=True)
    reference = level.initial_state()
    calls = []
    original = Turret._fire
    def fire(self, *args):
        calls.append(self.load_index)
        return original(self, *args)
    monkeypatch.setattr(Turret, "_fire", fire)
    total = 0
    for frame in [*frames, InputFrame()]:
        calls.clear()
        reference.step(frame, level.tiles)
        records = tick(state, effects, frame)
        count = sum("TurretBullet" in p.symbol and p.frame == 1 for p in records)
        assert count == len(calls), f"gauss event mismatch at tick {state.frame}"
        total += count
        if state.player_snapshot()["dead"] or state.level_complete:
            break
    assert total > 0


@pytest.mark.parametrize("filename", ["example_00_1_speedrun.txt", "example_07_3_homing.txt"])
def test_particles_do_not_change_native_results_keys_or_random(filename, manifest):
    replay = parse_combined_level_replay((ROOT / "tests" / filename).read_text())
    frames = decode_complex_replay(replay.replay_string).frames
    level = native.parse_level_string(replay.level_string, simulate_enemies=True)
    plain = level.initial_state()
    state = level.initial_state(track_visuals=True)
    a, b = ParticleSystem(manifest, seed=731), ParticleSystem(manifest, seed=731)
    for fx in (a, b):
        fx.reset(state.scene_snapshot())
    global_random = random.getstate()
    saw = False
    for frame in [*frames, InputFrame()]:
        assert state.step(frame) == plain.step(frame)
        snapshot = state.scene_snapshot()
        saved = deepcopy(snapshot)
        assert a.update(snapshot, frame) == b.update(snapshot, frame)
        saw |= bool(a.snapshot())
        assert snapshot == saved
        assert state.state_key() == plain.state_key()
        assert state.player_snapshot() == plain.player_snapshot()
        assert random.getstate() == global_random
        if state.player_snapshot()["dead"] or state.level_complete:
            break
    assert saw and state.level_complete


def test_bound_depth_order_seed_reset_and_seek_rejection(manifest):
    state, effects = tracked(flat("!12^100,134"), manifest, seed=99)
    initial = state.scene_snapshot()
    first = tick(state, effects)
    effects.reset(initial)
    assert effects.update(state.scene_snapshot()) == first
    different = ParticleSystem(manifest, seed=100)
    different.reset(initial)
    assert different.update(state.scene_snapshot()) != first
    # Burst pressure must replace ring slots, not grow with replay length.
    for _ in range(300):
        effects._explosion(100, 100)
    assert len(effects.snapshot()) == 102
    assert [p.depth for p in effects.snapshot()] == list(range(102))
    jumped = state.scene_snapshot()
    jumped["frame"] += 5
    before = effects.snapshot()
    with pytest.raises(ValueError, match="consecutive"):
        effects.update(jumped)
    assert effects.snapshot() == before
    effects.advance(120)
    assert not effects.snapshot()
    with pytest.raises(ValueError, match="v4.05 asset pack"):
        ParticleSystem({})


def test_particle_render_layering_hairlines_and_idempotence(manifest):
    pytest.importorskip("PIL")
    from nv14_render import BACKGROUND, TERRAIN, SceneRenderer
    renderer = SceneRenderer(flat())
    state = native.parse_level_string(flat()).initial_state(track_visuals=True)
    scene = state.scene_snapshot()
    scene["visual"]["visible"] = False
    # An axis-aligned gauss hairline has a zero scale and must still render.
    records = (Particle("debugTurretBulletMC1", 80, 100, 1., 0.),
               Particle("debugTurretBulletMC1", 100, 140, 0., .5))
    before = deepcopy(scene)
    image = renderer.render(scene, particles=records)
    assert image.getpixel((130, 100)) == (0, 0, 0)
    assert image.getpixel((100, 142)) == (0, 0, 0)
    assert image.getpixel((100, 150)) == TERRAIN  # tiles cover front particles
    assert renderer.render(scene, particles=records).tobytes() == image.tobytes()
    assert scene == before
    assert renderer.render(scene).getpixel((130, 100)) == BACKGROUND
    # Rendering extreme dust is clipped before bitmap allocation.
    huge = Particle("debugDustMC1", 100, 100, 1e8, 1e8, frame=7)
    assert renderer.render(scene, particles=(huge,)).size == (792, 600)
