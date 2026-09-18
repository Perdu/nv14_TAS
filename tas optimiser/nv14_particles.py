"""Optional replay-only cosmetics, reconstructed from consecutive scene queries.

No engine/search module imports this file. It owns no native state, installs no
hooks and uses a private RNG. It ports ParticleManager's placement/scales and
plays extracted MovieClip frames; it does not simulate new gameplay. See
docs/VIDEO_ENCODING.md for the limits of reconstructing transient events.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import math
import random


@dataclass(frozen=True, slots=True)
class Particle:
    symbol: str
    x: float
    y: float
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    frame: int = 1
    layer: str = "front"
    depth: int = 0


def _angle(x, y):
    return math.degrees(math.atan2(y, x))


def _unit(x, y):
    length = math.hypot(x, y)
    return (x / length, y / length) if length else (1.0, 0.0)


class ParticleSystem:
    """Track one replay, seeded independently of gameplay and global random.

    Pass the renderer's full asset manifest. Prime with the initial scene, then
    call ``update(scene, input_frame)`` once per consecutive gameplay tick.
    Repeating a frame is idempotent; seeking/skipping requires ``reset(scene)``.
    ``snapshot()`` returns immutable draw records. ``advance(n)`` only ages
    existing cosmetics by n SWF timeline frames (3 per 40 Hz gameplay tick).
    """

    # AS wraps when (100 < curDepth++), giving slots 0..101, not 0..99.
    CAPACITY = 102
    VARIANTS = {
        "dust": ("debugDustMC1", "debugDustMC2"),
        "blood": ("debugBloodSpurtMC2",),
        "smoke": ("debugRocketSmokeMC1", "debugRocketSmokeMC2", "debugRocketSmokeMC3"),
        "fireball": ("debugFireBallMC1", "debugFireBallMC2", "debugFireBallMC3"),
        "fireburst": ("debugFireBurstMC1", "debugFireBurstMC2"),
        "gauss": ("debugTurretBulletMC1",),
        "gauss_debris": ("debugTurretDebrisMC1",),
        "chain": ("debugChainBulletMC1",),
        "flash": ("debugChainFlashMC1", "debugChainFlashMC2"),
        "chain_debris": ("debugChainDebrisMC1", "debugChainDebrisMC2", "debugChainDebrisMC3"),
        "charge": ("debugLaserChargeMC1", "debugLaserChargeMC2", "debugLaserChargeMC3"),
        "zap": ("debugZapMC1", "debugZapMC2", "debugZapMC3"),
        "zap_v": ("debugZapVMC1", "debugZapVMC2", "debugZapVMC3"),
    }

    def __init__(self, manifest, *, seed=0, _borrow_scenes=False):
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("particle_seed must be an integer")
        pack = manifest.get("particles", {})
        self.clips = pack.get("clips", {})
        if pack.get("schema_version") != 1 or any(
                symbol not in self.clips for names in self.VARIANTS.values() for symbol in names):
            raise ValueError("Particles require the v4.05 asset pack; use particles=False / --no-particles with older packs")
        self.seed = seed
        # Private encoder fast path: each native query is a new snapshot and
        # its owner promises never to mutate it. Public callers retain the
        # historical defensive-copy behaviour, including nested scene data.
        self._borrow_scenes = _borrow_scenes
        self.reset()

    def reset(self, scene=None):
        """Start a fresh cosmetic sequence, optionally primed at a known scene."""
        self._rng = random.Random(self.seed)
        self._slots = {}
        self._depth = 0
        self._counter = 0
        self._rates = {"skid": 7, "smoke": 3, "charge": 2}
        self._previous = scene if self._borrow_scenes else deepcopy(scene)

    def snapshot(self):
        return tuple(self._slots[key] for key in sorted(self._slots))

    def advance(self, timeline_frames=3, *, _snapshot=True):
        if isinstance(timeline_frames, bool) or not isinstance(timeline_frames, int) or timeline_frames < 0:
            raise ValueError("timeline_frames must be a non-negative integer")
        self._slots = {depth: replace(p, frame=p.frame + timeline_frames)
                       for depth, p in self._slots.items()
                       if p.frame + timeline_frames < self.clips[p.symbol]["remove_frame"]}
        return self.snapshot() if _snapshot else None

    def _emit(self, kind, x, y, sx=100., sy=100., rotation=0.):
        if not all(math.isfinite(v) for v in (x, y, sx, sy, rotation)):
            return
        names = self.VARIANTS[kind]
        symbol = names[self._depth % len(names)]
        self._slots[self._depth] = Particle(symbol, x, y, sx / 100., sy / 100.,
                                            rotation, depth=self._depth)
        self._depth = (self._depth + 1) % self.CAPACITY

    def _rate(self, kind, rate, modulus):
        # The source manager's counter is implicit. Start this render-only
        # shared counter at zero for a defined, reproducible modulo cadence.
        self._rates[kind] -= self._counter % modulus
        self._counter += 1
        if self._rates[kind] < 0:
            self._rates[kind] = rate
            return True
        return False

    def _dust(self, x, y, rotation, strength=None):
        r = self._rng.random
        direction = 1
        for _ in range(4):
            turn = 20 if strength is None else 40
            rot = rotation - direction * turn + r() * 20 - 10
            sx = direction * (10 + r() * 8 if strength is None else 5 + r() * 5 + strength)
            sy = 10 + r() * 5 if strength is None else 15 + strength * 2
            self._emit("dust", x, y, sx, sy, rot)
            direction *= -1

    def _player_effects(self, before, after, input_frame):
        old, p = before["player"], after["player"]
        if old["dead"] or p["dead"] or after["static_state"]["level_complete"]:
            return
        x, y = p["pos"]
        nx, ny = p["floor_n"]
        radius = p["r"]
        old_state, state = old["state"], p["state"]
        visual = before.get("visual") or {}
        rotation = visual.get("rotation_deg", 0.)
        horizontal = (int(input_frame.right) - int(input_frame.left)) if input_frame is not None else 0
        if p["jump_events"] > old["jump_events"]:
            # Undo Jump's immediate displacement, not its velocity: oldpos
            # need not equal the contact position when momentum is retained.
            if p["in_air"]:
                nx, ny = p["wall_n"]
                slide = old_state == 5 and horizontal * nx < 0
                jx, jy = nx * (1.0 if slide else 1.5), ny - (.5 if slide else .7)
                rotation = nx * 90
            else:
                jx, jy = (0., -.7) if horizontal * nx < 0 else (nx, ny)
            x -= jx * p["jump_amt"]
            y -= jy * (p["jump_amt"] + p["jump_y_bias"])
            self._dust(x - nx * radius, y - ny * radius, rotation)
        elif not p["in_air"] and old_state > 2 and state in (1, 2):
            vx, vy = x - p["oldpos"][0], y - p["oldpos"][1]
            self._dust(x - nx * radius, y - ny * radius, _angle(nx, ny) + 90,
                       max(0., abs(vx) + vy))
        elif p["in_air"] and old_state == state == 5:
            if self._rate("skid", 7, 3):
                nx, ny = p["wall_n"]
                vy = y - p["oldpos"][1]
                strength = abs(vy / (1 - p["wall_friction"])) if vy >= 0 else abs(vy / (1 + p["wall_friction"]))
                r = self._rng.random
                self._emit("dust", x - nx * radius, y - ny * radius - (r() * radius * 2 - radius),
                           10 + strength * 20, 10, 90 - nx * 8 + r() * 10 - 5)
        elif not p["in_air"] and old_state == 2 and state in (0, 2):
            if self._rate("skid", 7, 3):
                vx, vy = x - p["oldpos"][0], y - p["oldpos"][1]
                if state == 2:
                    vx /= p["skid_friction"]
                strength = abs(vx * -ny + vy * nx)
                direction = visual.get("facing", 1)
                self._emit("dust", x - nx * radius, y - ny * radius,
                           direction * (10 + strength * 10), 10,
                           rotation - direction * 8 + self._rng.random() * 10 - 5)

    def _explosion(self, x, y):
        # Preserve the four correlated ball scales/angles in SpawnExplosion.
        r = self._rng.random
        a, b, c, d, e = (r() for _ in range(5))
        self._emit("fireburst", x, y, 15 + a * 15, 15 + b * 15)
        self._emit("fireball", x, y, 20 + c * 20, 20 + e * 20, 360 * a)
        self._emit("fireball", x, y, 20 + c * 20, 20 + a * 10, 360 * b)
        self._emit("fireball", x, y, 20 + d * 30, 20 + a * 10, 360 * e)
        self._emit("fireball", x, y, 20 + d * 30, 20 + e * 20, 360 * c)

    def _shot(self, obj, *, gauss=False, hit=False, radius=10):
        x, y = obj["x"], obj["y"]
        ex, ey = obj["target"] if gauss else obj["beam_end"]
        dx, dy = ex - x, ey - y
        ux, uy = _unit(dx, dy)
        # AS extends a lethal gauss trail into the player by one radius;
        # native target retains QueryRayObj's first intersection instead.
        if gauss and hit:
            ex, ey = ex + ux * radius, ey + uy * radius
            dx, dy = ex - x, ey - y
        rot = _angle(dx, dy)
        r = self._rng.random
        if gauss:
            self._emit("gauss", x, y, dx, dy)
            rot += 0 if hit else 180
            a, b = 40 + r() * 20, 20 + r() * 40
            self._emit("gauss_debris", ex, ey, a, b, rot + 5 + r() * 15)
            self._emit("gauss_debris", ex, ey, b, a, rot - 5 - r() * 15)
        else:
            a, b, c = (r() * 2 - 1 for _ in range(3))
            self._emit("flash", x, y, 30 + a * 10, 20 + b * 20, rot)
            self._emit("chain", x, y, math.hypot(dx, dy), 100, rot)
            self._emit("chain_debris", ex, ey, 30 + b * 15, 100, rot - 180 + 15 * a)
            self._emit("chain_debris", ex, ey, 30 + c * 15, 100, rot - 180 + 15 * b)

    def _weapons(self, before, after):
        old_objects = {o["id"]: o for o in before["objects"]}
        old_player = before["player"]
        impacts = []
        for obj in after["objects"]:
            old = old_objects.get(obj["id"])
            if old is None:
                continue
            kind, x, y = obj["kind"], obj["x"], obj["y"]
            r = self._rng.random
            if kind == "mine" and old["visible"] and not obj["visible"]:
                self._explosion(x, y)
                impacts.append((x, y, "explosive"))
            elif kind == "homing":
                rx, ry = obj["rocket_x"], obj["rocket_y"]
                if old["rocket_visible"] and not obj["rocket_visible"]:
                    self._explosion(rx, ry)
                    impacts.append((rx, ry, "explosive"))
                elif obj["rocket_visible"] and self._rate("smoke", 3, 2):
                    rot = obj["rocket_rotation_deg"] + 10 * (r() * 2 - 1)
                    self._emit("smoke", rx, ry, 20 + r() * 20, 20 + r() * 20, rot)
            elif kind == "drone_laser" and old["mode"] in (1, 2):
                if self._rate("charge", 2, 3):
                    self._emit("charge", x, y, 20 + r() * 20, 10 + r() * 20, r() * 360)
            elif kind == "drone_chaingun" and obj["shot_visible"] and obj["shot_index"] != old["shot_index"]:
                self._shot(obj)
                impacts.append((*obj["beam_end"], "bullet"))
            elif (kind == "turret" and old["mode"] == 2 and old["fire_delay_timer"] >= 9
                  and obj["mode"] in (0, 3) and obj["fire_delay_timer"] == 0):
                # POSTFIRE alone also means LOS cancellation. The retained
                # LOS endpoint must reach the pre-integration player circle,
                # or the shot target must have changed. This also recognises
                # real repeated shots with identical endpoints.
                px, py = old_player["pos"]
                vx, vy = obj["view"]
                radius = old_player["r"]
                has_los = (vx - px)**2 + (vy - py)**2 <= radius**2 + 1e-6
                if obj["target"] != old["target"] or has_los:
                    ex, ey = obj["target"]
                    hit = (ex - px)**2 + (ey - py)**2 <= radius**2 + 1e-6
                    self._shot(obj, gauss=True, hit=hit, radius=radius)
                    impacts.append((ex, ey, "bullet"))
        return impacts

    def _death(self, before, after, impacts):
        old, p = before["player"], after["player"]
        if old["dead"] or not p["dead"]:
            return
        px, py = p["pos"]
        if not all(math.isfinite(v) for v in (px, py)):
            return
        r = self._rng.random
        x, y, vx, vy = px, py, 0., 0.
        # The native state has no killer/contact record. Only use nearby
        # evidence; otherwise render a neutral spurt at the player centre.
        close = [i for i in impacts if math.hypot(i[0] - px, i[1] - py) <= p["r"] + 8]
        if close:
            x, y, kind = min(close, key=lambda i: math.hypot(i[0] - px, i[1] - py))
            if kind == "explosive":
                vx, vy = px - x, py - y
            else:
                vx, vy = _unit(px - x, py - y)
                vx, vy = vx * 6, vy * 6
        else:
            for obj in after["objects"]:
                kind, ox, oy = obj["kind"], obj["x"], obj["y"]
                dx, dy = px - ox, py - oy
                if kind in ("drone_zap", "floorguard") and math.hypot(dx, dy) < p["r"] + obj["radius"] + 1e-6:
                    ux, uy = _unit(dx, dy)
                    for _ in range(6):
                        sx, sy, rot = 30 + r() * 30, 30 + r() * 20, _angle(ux, uy) + 20 * (r() * 2 - 1)
                        self._emit("zap", ox + ux * obj["radius"], oy + uy * obj["radius"], sx, sy, rot)
                    x, y, vx, vy = px - ux * p["r"], py - uy * p["r"], ux * 10, uy * 10
                    break
                if kind == "thwomp":
                    nx, ny = obj["direction"]
                    # Source thwomp half-width is 9; only its lethal face zaps.
                    hitx, hity = 9 + p["xw"] - abs(dx), 9 + p["yw"] - abs(dy)
                    if hitx <= 0 or hity <= 0:
                        continue
                    vertical = hity < hitx
                    if (vertical and dy * ny <= 0) or (not vertical and dx * nx <= 0):
                        continue
                    for _ in range(6):
                        if vertical:
                            self._emit("zap_v", ox - 9 + 9 * r(), oy + 9 * ny,
                                       60 + 60 * r(), 36 * ny + 20 * (r() * 2 - 1))
                        else:
                            self._emit("zap", ox + 9 * nx, oy - 9 + 9 * r(),
                                       36 * nx + 20 * (r() * 2 - 1), 60 + 60 * r())
                    vx, vy = (0., -8. if ny < 0 else 6.) if vertical else (nx * 8, -4.)
                    x, y = px + nx * p["r"] * .5, py + ny * p["r"] * .5
                    break
        count = 6 + int(r() * 8)
        for _ in range(count):
            self._emit("blood", x - (r() * 8 - 4), y - (r() * 8 - 4),
                       vx * (6 + r() * 3) - (r() * 60 - 30),
                       vy * (6 + r() * 3) - (r() * 60 - 30))

    def update(self, scene, input_frame=None, *, _snapshot=True):
        """Observe one adjacent post-tick snapshot without modifying it."""
        before = self._previous
        if before is None:
            self._previous = scene if self._borrow_scenes else deepcopy(scene)
            return self.snapshot() if _snapshot else None
        delta = scene["frame"] - before["frame"]
        if delta == 0:
            return self.snapshot() if _snapshot else None
        if delta != 1:
            raise ValueError("Particles require consecutive scene frames; reset(scene) after seeking")
        self.advance(3, _snapshot=False)
        if not before["static_state"]["level_complete"] and not before["player"]["dead"]:
            impacts = self._weapons(before, scene)
            self._player_effects(before, scene, input_frame)
            self._death(before, scene, impacts)
        self._previous = scene if self._borrow_scenes else deepcopy(scene)
        return self.snapshot() if _snapshot else None
