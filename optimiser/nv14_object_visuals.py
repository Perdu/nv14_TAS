"""Optional, observation-only object MovieClips for replay rendering.

The tracker consumes consecutive scene queries and owns all of its state.  It
never imports an engine, installs callbacks, or changes a gameplay snapshot.
Three nominal SWF frames elapse *before* each 40 Hz game tick.  MovieClip frame
actions come from the extracted asset manifest, rather than guessed lifetimes.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class SpriteVisual:
    clip: str
    frame: int
    x: float
    y: float
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    visible: bool = True


@dataclass(frozen=True, slots=True)
class BeamVisual:
    start: tuple[float, float]
    end: tuple[float, float]
    color: str
    width: float
    visible: bool = True


@dataclass(frozen=True, slots=True)
class ObjectVisual:
    id: int
    body: SpriteVisual
    eye_rotation: float | None = None
    crosshair: SpriteVisual | None = None
    blast: SpriteVisual | None = None
    rocket: SpriteVisual | None = None
    trigger: SpriteVisual | None = None
    beam: BeamVisual | None = None


class _Clip:
    """The small subset of AVM1 timeline operations used by object artwork."""

    def __init__(self, name, info, frame=1, *, playing=False, visible=True):
        self.name, self.info = name, info
        self.frame, self.playing, self.visible = frame, playing, visible

    def _number(self, target):
        return int(self.info.get("labels", {}).get(str(target), target))

    def goto(self, target, play=False):
        self.frame = self._number(target)
        self.playing = play
        self._actions()

    def _actions(self):
        # A goto can execute the destination's actions synchronously. Bound
        # recursive jumps to reject malformed external asset packs cleanly.
        for _ in range(64):
            jumped = False
            for action in self.info.get("actions", {}).get(str(self.frame), ()):
                op = action["op"]
                if op == "stop":
                    self.playing = False
                elif op == "play":
                    self.playing = True
                elif op in ("goto_and_stop", "goto_and_play"):
                    target = self._number(action["target"])
                    self.playing = op == "goto_and_play"
                    if target != self.frame:
                        self.frame = target
                        jumped = True
                        break
                elif op == "set_visible":
                    self.visible = bool(action["visible"])
                elif op == "remove":
                    self.visible = self.playing = False
            if not jumped:
                return
        raise ValueError("Cyclic object MovieClip frame actions")

    def advance(self, frames):
        for _ in range(frames):
            if not self.playing:
                break
            self.frame = self.frame % self.info["frame_count"] + 1
            self._actions()

    def sprite(self, x, y, **kwargs):
        return SpriteVisual(self.name, self.frame, x, y, visible=self.visible, **kwargs)


def _direction_rotation(obj):
    # AS SetDir uses these literal values; interpolation does not wrap its
    # delta to the shortest arc (in particular 180 -> -90).
    if "direction_index" in obj:
        return (0., 90., 180., -90.)[int(obj["direction_index"]) % 4]
    return math.degrees(math.atan2(*reversed(obj.get("direction", (1., 0.)))))


class ObjectVisualSystem:
    """A private replay's object artwork, independent from native simulation.

    Prime with ``reset(initial_scene)`` and call ``update(scene)`` after each
    adjacent tick, including unsampled video ticks. Duplicate frames are
    idempotent. Seeking requires a reset, which cannot recover prior cosmetic
    history. ``advance(n)`` only runs MovieClips and is suitable for frozen
    terminal holds: it does not move objects, rotate eyes or infer new events.
    """

    REQUIRED = frozenset(("gold", "exit", "door", "launchpad", "turret",
                          "turret_crosshair", "homing_launcher", "drone",
                          "laser_blast", "rocket"))

    def __init__(self, manifest, *, _borrow_scenes=False):
        pack = manifest.get("object_animations", {})
        self.clips = deepcopy(pack.get("clips", {}))
        if pack.get("schema_version") != 1 or not self.REQUIRED <= self.clips.keys():
            raise ValueError("Object animations require the v4.06 asset pack; use "
                             "object_animations=False / --no-object-animations with older packs")
        # Borrowing is reserved for immutable-by-ownership encoder queries.
        # The public path owns one deep copy of each scene and shares its
        # object descriptors with the private animation states.
        self._borrow_scenes = _borrow_scenes
        self.reset()

    def _clip(self, name, label=1, *, play=False, visible=True):
        result = _Clip(name, self.clips[name], visible=visible)
        result.goto(label, play)
        return result

    def reset(self, scene=None, *, _snapshot=True):
        self._previous = scene if self._borrow_scenes else deepcopy(scene)
        self._states = {}
        self._ordered_ids = None
        if self._previous is not None:
            for obj in self._previous["objects"]:
                self._add(obj)
        return self.snapshot() if _snapshot else None

    def _add(self, obj):
        kind = obj["kind"]
        name = {"exit_door": "exit", "testdoor": "door", "launch": "launchpad",
                "homing": "homing_launcher"}.get(kind, kind)
        if kind.startswith("drone_"):
            name = "drone"
        if name not in self.clips:
            return
        label, play = 1, False
        if kind == "gold":
            label = "NOT_COLLECTED"
        elif kind == "exit_door":
            label = 31 if obj.get("is_open") else "exit_closed"
        elif kind == "testdoor":
            label = ("open_Lock" if obj.get("is_open") else "closed_Lock") if obj.get("is_locked") else (
                ("open_Trap" if obj.get("is_open") else "closed_Trap") if obj.get("is_trap") else
                ("open_Trek" if obj.get("is_open") else "closed_Trek"))
        elif kind == "launch":
            label = "launch_idle"
        elif kind == "turret":
            label = "turret_prefire" if obj.get("mode") == 2 else "turret_idle"
            play = obj.get("mode") == 2
        elif kind == "homing":
            label = "rocket_active" if obj.get("rocket_visible") else "rocket_waiting"
        elif kind == "drone_zap":
            p = obj.get("parameters", ())
            label = "zapdrone_chaseidle" if len(p) > 3 and p[3] else "zapdrone_move"
        elif kind in ("drone_laser", "drone_chaingun"):
            prefix = "laserdrone" if kind == "drone_laser" else "chaingundrone"
            suffix = ("move", "prefire", "firing" if kind == "drone_laser" else "fire", "postfire")[max(0, obj.get("mode", 0))]
            label = prefix + "_" + suffix
            play = obj.get("mode") in (1, 3) or (kind == "drone_chaingun" and obj.get("mode") == 2)
        elif kind == "floorguard":
            label = "floorguard_active" if obj.get("chasing") else "floorguard_idle"
        elif kind in ("exit_switch", "door_switch"):
            label = "exit_open" if obj.get("is_open") else "exit_closed"
        elif kind == "mine":
            label = "mine_unexploded" if obj.get("visible", True) else "mine_exploded"
        state = {"obj": obj, "body": self._clip(name, label, play=play,
                  visible=obj.get("visible", True)), "eye": None,
                  "display_pos": (obj["x"], obj["y"])}
        if kind.startswith("drone_"):
            state["eye"] = .3 * _direction_rotation(obj)
        if kind == "turret":
            state["crosshair"] = self._clip("turret_crosshair", "aim_far",
                                            visible=obj.get("crosshair_visible", False))
            state["crosshair_pos"] = tuple(obj.get("aim", (obj["x"], obj["y"])))
        if kind == "homing":
            # The rocket's own timeline starts at construction, runs while
            # hidden, and is not restarted by FireMissile.
            state["rocket"] = self._clip("rocket", play=True, visible=obj.get("rocket_visible", False))
        if kind == "drone_laser":
            state["blast"] = self._clip("laser_blast", play=True, visible=False)
            state["blast_scale"] = 0.
        if kind == "testdoor" and (obj.get("is_locked") or obj.get("is_trap")) and "door_switch" in self.clips:
            state["trigger"] = self._clip("door_switch", "exit_open" if obj.get("is_open") and obj.get("is_locked") else "exit_closed")
        # Clip membership is fixed at construction; avoid inspecting all
        # state fields with isinstance on every animation tick.
        state["clips"] = tuple(value for value in state.values() if isinstance(value, _Clip))
        self._states[obj["id"]] = state
        self._ordered_ids = None

    def snapshot(self):
        result = []
        if self._ordered_ids is None:
            self._ordered_ids = tuple(sorted(self._states))
        for key in self._ordered_ids:
            s = self._states[key]
            obj = s["obj"]
            kind, x, y = obj["kind"], obj["x"], obj["y"]
            rotation = 0.
            if kind.startswith("drone_"):
                x, y = s["display_pos"]
            elif kind == "launch":
                p = obj.get("parameters", ())
                dx, dy = p[2:4] if len(p) >= 4 else obj.get("direction", (0., -1.))
                rotation = math.degrees(math.atan2(dy, dx)) + 90
            elif kind == "testdoor":
                p = obj.get("parameters", ())
                delta_i, delta_j = p[7:9] if len(p) >= 9 else (0, 0)
                x, y = obj.get("door_x", x), obj.get("door_y", y)
                if obj.get("horizontal"):
                    y += 12 if delta_j else -13
                    rotation = 270. if delta_j else 90.
                else:
                    x += 12 if delta_i else -13
                    rotation = 180. if delta_i else 0.
            body = s["body"].sprite(x, y, rotation=rotation)
            crosshair = s["crosshair"].sprite(*s["crosshair_pos"]) if "crosshair" in s else None
            blast = s["blast"].sprite(*obj.get("beam_end", (x, y)),
                scale_x=s["blast_scale"], scale_y=s["blast_scale"]) if "blast" in s else None
            rocket = s["rocket"].sprite(obj["rocket_x"], obj["rocket_y"],
                rotation=obj.get("rocket_rotation_deg", 0.)) if "rocket" in s else None
            trigger = s["trigger"].sprite(obj["x"], obj["y"],
                scale_x=2/3 if obj.get("is_trap") else 1.,
                scale_y=2/3 if obj.get("is_trap") else 1.) if "trigger" in s else None
            beam = None
            if kind == "drone_laser":
                firing = obj.get("mode") == 2
                beam = BeamVisual((obj["x"], obj["y"]), tuple(obj.get("beam_end", (x, y))),
                                  "#882222" if firing else "#cb7579", 3. if firing else 0.,
                                  obj.get("mode") in (1, 2))
            result.append(ObjectVisual(key, body, s["eye"], crosshair, blast, rocket, trigger, beam))
        return tuple(result)

    def advance(self, timeline_frames=3, *, _snapshot=True):
        if isinstance(timeline_frames, bool) or not isinstance(timeline_frames, int) or timeline_frames < 0:
            raise ValueError("timeline_frames must be a non-negative integer")
        for state in self._states.values():
            for clip in state["clips"]:
                clip.advance(timeline_frames)
        return self.snapshot() if _snapshot else None

    def _turret(self, state, old, obj, before):
        body, crosshair = state["body"], state["crosshair"]
        oldmode, mode = old.get("mode"), obj.get("mode")
        if oldmode == 1:
            # Update_Targetting chooses a band using the OLD error and only
            # then advances its aim; the inner band deliberately retains the
            # previous crosshair rather than assigning aim_near.
            p = before["player"]
            px, py = p["pos"]
            ox, oy = p.get("oldpos", (px, py))
            ax, ay = old["aim"]
            distance2 = (ax - (2 * px - ox))**2 + (ay - (2 * py - oy))**2
            if distance2 > 96**2:
                crosshair.goto("aim_far")
            elif distance2 >= 24**2:
                crosshair.goto("aim_near" if distance2 < 42**2 else "aim_mid")
        if mode == 2 and oldmode != 2:
            body.goto("turret_prefire", True)
            crosshair.goto("prefire")
        elif (oldmode == 2 and old.get("fire_delay_timer", 0) >= 9
              and obj.get("fire_delay_timer") == 0 and mode in (0, 3)):
            # Fire's gotoAndPlay(turret_firing) is synchronously superseded
            # by StopFiring's gotoAndPlay(turret_idle), including lethal shots.
            # LOS cancellation takes exactly the same final body/crosshair.
            body.goto("turret_idle", True)
            crosshair.goto("postfire")
        elif oldmode == 0 and mode == 1:
            crosshair.goto("aim_far")
        crosshair.visible = obj.get("crosshair_visible", mode != 0)
        # StartFiring removes Draw before the newly updated aim can be drawn.
        if mode == 1:
            state["crosshair_pos"] = tuple(obj["aim"])

    def _drone(self, state, old, obj, before):
        kind, body = obj["kind"], state["body"]
        oldmode, mode = old.get("mode", 0), obj.get("mode", 0)
        if kind == "drone_zap":
            # Chase can be renewed at a goal while ischasing remains true.
            reached = math.hypot(old.get("goal", (old["x"], old["y"]))[0] - old["x"],
                                 old.get("goal", (old["x"], old["y"]))[1] - old["y"]) < old.get("speed", 0.)
            if obj.get("chasing") and (not old.get("chasing") or reached):
                body.goto("zapdrone_chaseactive", True)
        elif oldmode != mode:
            prefix = "laserdrone" if kind == "drone_laser" else "chaingundrone"
            if mode == 1:
                body.goto(prefix + "_prefire", True)
            elif mode == 2:
                body.goto(prefix + ("_firing" if kind == "drone_laser" else "_fire"), kind != "drone_laser")
            elif mode == 3:
                body.goto(prefix + "_postfire", True)
                if (kind == "drone_chaingun" and oldmode == 1
                        and old.get("fire_delay_timer", 0) >= 34):
                    # At zero target distance Fire_Chaingun calls StopFiring,
                    # but Update_PreFire then executes its trailing fire goto.
                    body.goto("chaingundrone_fire", True)
            # StartMoving does not jump its body timeline; its preceding
            # postfire timeline reaches the move label on its own.
        if kind == "drone_chaingun":
            if oldmode == 1:
                px, py = before["player"]["pos"]
                target = math.degrees(math.atan2(py - obj["y"], px - obj["x"]))
                state["eye"] += .1 * (target - state["eye"])
            if obj.get("shot_index", 0) != old.get("shot_index", 0) and obj.get("shot_visible"):
                ex, ey = obj["beam_end"]
                state["eye"] = math.degrees(math.atan2(ey - obj["y"], ex - obj["x"]))
        if kind == "drone_zap" or mode == 0:
            state["display_pos"] = (obj["x"], obj["y"])
            state["eye"] += .3 * (_direction_rotation(obj) - state["eye"])
        if kind == "drone_laser":
            blast = state["blast"]
            if mode == 2 and oldmode != 2:
                blast.visible = True
                blast.goto(1, True)
                state["blast_scale"] = 0.
            elif mode == 2:
                state["blast_scale"] = .3 + 2 * old.get("weapon_timer", 0) / 80
            elif oldmode != mode and mode == 3:
                blast.visible = False
                blast.goto(1)

    @staticmethod
    def _launched(obj, before, after):
        """Recognise Launch's retained oldpos/contact and impulse.

        Launch has no native event counter. Its overwritten oldpos retains the
        contact for the last launch in a tick. Require a matching displacement
        too: collecting colocated gold can terminate that cell's collision
        traversal before a geometrically overlapping pad is actually tested.
        Multiple pads and other object displacements within a single collision
        traversal cannot always be uniquely recovered from endpoint snapshots.
        """
        old, new = before["player"], after["player"]
        p = obj.get("parameters", ())
        nx, ny = p[2:4] if len(p) >= 4 else obj.get("direction", (0., -1.))
        radius = new.get("r", 10.)
        def contact(x, y):
            dx, dy = obj["x"] - x, obj["y"] - y
            return math.hypot(dx, dy) < obj.get("radius", 6.) + radius and (dx + nx * radius) * nx + (dy + ny * radius) * ny >= 0
        ox, oy = old["pos"]
        px, py = old.get("oldpos", (ox, oy))
        ix = ox + old.get("d", .99) * (ox - px)
        iy = oy + old.get("d", .99) * (oy - py) + old.get("g", .15)
        cx, cy = new.get("oldpos", (ox, oy))
        # A genuine launch rewrites oldpos to its integrated contact; normal
        # integration alone leaves oldpos at the previous position.
        retained = (cx, cy) != (ox, oy) and contact(cx, cy)
        fx, fy = new["pos"]
        displaced = (fx - ix) * nx + (fy - iy) * ny > 1e-7
        return displaced and (retained or contact(ix, iy))

    def update(self, scene, input_frame=None, *, _snapshot=True):
        before = self._previous
        if before is None:
            return self.reset(scene, _snapshot=_snapshot)
        delta = scene["frame"] - before["frame"]
        if delta == 0:
            return self.snapshot() if _snapshot else None
        if delta != 1:
            raise ValueError("Object animations require consecutive scene frames; reset(scene) after seeking")
        scene = scene if self._borrow_scenes else deepcopy(scene)
        self.advance(3, _snapshot=False)
        old_objects = {obj["id"]: obj for obj in before["objects"]}
        live = not before.get("static_state", {}).get("level_complete") and not before["player"].get("dead")
        for obj in scene["objects"]:
            key = obj["id"]
            if key not in self._states:
                self._add(obj)
                continue
            state, old = self._states[key], old_objects.get(key)
            if old is None:
                continue
            body, kind = state["body"], obj["kind"]
            if live:
                if kind == "gold" and old.get("visible", True) and not obj.get("visible", True):
                    body.goto("COLLECTED", True)
                elif kind == "exit_door" and not old.get("is_open") and obj.get("is_open"):
                    body.goto("exit_opening", True)
                elif kind == "exit_switch" and old.get("is_open") != obj.get("is_open"):
                    body.goto("exit_open" if obj.get("is_open") else "exit_closed")
                elif kind == "mine":
                    if old.get("visible", True) and not obj.get("visible", True):
                        body.goto("mine_exploded")
                        body.visible = False
                elif kind == "testdoor":
                    reopened = (old.get("is_open") and obj.get("is_open")
                                and old.get("updating", True) and old.get("door_timer", -1) >= 5
                                and obj.get("door_timer") == 0
                                and not obj.get("is_locked") and not obj.get("is_trap"))
                    if old.get("is_open") != obj.get("is_open") or reopened:
                        suffix = "Lock" if obj.get("is_locked") else "Trap" if obj.get("is_trap") else "Trek"
                        label = ("opening_" if obj.get("is_open") else "closing_") + suffix
                        body.goto(label, True)
                        if "trigger" in state:
                            state["trigger"].goto("exit_open" if obj.get("is_open") else "exit_closed")
                elif kind == "launch" and self._launched(obj, before, scene):
                    body.goto("launch_triggered", True)
                elif kind == "turret":
                    self._turret(state, old, obj, before)
                elif kind == "homing":
                    if old.get("rocket_visible") and not obj.get("rocket_visible"):
                        body.goto("rocket_explode", True)
                    elif not old.get("rocket_visible") and obj.get("rocket_visible"):
                        body.goto("rocket_fire", True)
                    elif (old.get("mode") == 1 and old.get("fire_delay_timer", 0) >= 9
                          and (obj.get("mode") != 1 or obj.get("fire_delay_timer", 0) < old["fire_delay_timer"])):
                        # Launch and contact explosion can both happen before
                        # the first visible rocket snapshot.
                        body.goto("rocket_explode", True)
                    state["rocket"].visible = obj.get("rocket_visible", False)
                elif kind.startswith("drone_"):
                    self._drone(state, old, obj, before)
                elif kind == "floorguard" and obj.get("chasing") != old.get("chasing"):
                    body.goto("floorguard_active" if obj.get("chasing") else "floorguard_idle")
            state["obj"] = obj
        self._previous = scene
        return self.snapshot() if _snapshot else None
