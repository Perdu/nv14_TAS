"""Optional event-driven ghost gold. No engine imports or gameplay mutations.

One idle marker per gold object shows the first pending ghost in input order.
Hidden owners collect silently; only active collection clips advance each tick.
Immutable snapshots can be drawn out of order by independent render workers.
"""
from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache
import json
from operator import index as integer_index


def _bits(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


@dataclass(frozen=True, slots=True)
class GoldVisual:
    key: tuple[int, int]
    x: float
    y: float
    frame: int | None
    color: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class _GoldTimeline:
    # An exact finite prefix followed by a cycle. Stopped clips have a
    # one-state cycle; custom goto/visibility actions retain their semantics.
    states: tuple[tuple[int, bool], ...]
    repeat: int

    def sample(self, age):
        if age >= len(self.states):
            age = self.repeat + (age - self.repeat) % (len(self.states) - self.repeat)
        return self.states[age]


@lru_cache(maxsize=32)
def _compile_timeline(serialized):
    from nv14_object_visuals import _Clip

    clip = _Clip("gold", json.loads(serialized))
    states, seen = [], {}
    try:
        clip.goto("COLLECTED", True)
        # Bound work and cache memory for unusually large external packs.
        # The ordinary gold clip needs only thirty states. A fallback clip
        # also leaves errors in malformed packs at their original tick.
        for _ in range(4096):
            state = (clip.frame, clip.playing, clip.visible)
            if state in seen:
                return _GoldTimeline(tuple(states), seen[state])
            seen[state] = len(states)
            states.append((clip.frame, clip.visible))
            clip.advance(1)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    return None


@dataclass(slots=True)
class _GoldEffect:
    age: int
    visual: GoldVisual
    clip: object = None


class GhostGoldSystem:
    def __init__(self, scene, colors, manifest, *, animated=False):
        self.colors = tuple(colors)
        self._all = (1 << len(colors)) - 1
        self._positions = {obj["state_index"]: (obj["x"], obj["y"])
                           for obj in scene["objects"] if obj["kind"] == "gold"}
        self._clip_info = manifest.get("object_animations", {}).get("clips", {}).get("gold")
        if animated and self._clip_info is None:
            raise ValueError("animated secondary gold requires the gold object animation asset")
        self.animated = animated
        self._primary = 0
        self._collected = {}
        self._pending = {}
        self._idle_indices = []
        self._idle_rows = []
        self._idle = ()
        self._idle_changed = set()
        self._effects = {}
        self._generation = 0
        self._timeline = None
        self._timeline_ready = False
        self._snapshot = ()
        self._snapshot_dirty = False

    def _color(self, owners):
        return self.colors[(owners & -owners).bit_length() - 1]

    def update(self, primary_mask, pickups):
        """Observe one video tick; pickups is (ghost index, gold indices) pairs.

        Consume every ghost first, so a same-tick primary/ghost pickup never
        creates a marker or effect, regardless of replay ordering or offsets.
        """
        self.advance(3)
        removed = {}
        pending_before = {}
        for ghost, indices in pickups:
            bit = 1 << ghost
            for index in indices:
                previous = self._collected.get(index, 0)
                if previous & bit:
                    continue
                self._collected[index] = previous | bit
                pending = self._pending.get(index, 0)
                if pending & bit:
                    if self.animated:
                        pending_before.setdefault(index, pending)
                        removed[index] = removed.get(index, 0) | bit
                    if pending & -pending == bit:
                        self._idle_changed.add(index)
                    pending &= ~bit
                    if pending:
                        self._pending[index] = pending
                    else:
                        del self._pending[index]
        for index in _bits(primary_mask & ~self._primary):
            pending = self._all & ~self._collected.get(index, 0)
            if pending:
                self._pending[index] = pending
                self._idle_changed.add(index)
        self._primary = primary_mask
        if self.animated and removed:
            self._generation += 1
            for index, owners in removed.items():
                visible = pending_before[index] & -pending_before[index]
                if not owners & visible:
                    continue
                if not self._timeline_ready:
                    # Raster metadata does not affect MovieClip transitions.
                    info = {key: self._clip_info.get(key, {})
                            for key in ("frame_count", "labels", "actions")}
                    self._timeline = _compile_timeline(json.dumps(info, sort_keys=True))
                    self._timeline_ready = True
                clip = None
                if self._timeline is None:
                    from nv14_object_visuals import _Clip
                    clip = _Clip("gold", self._clip_info)
                    clip.goto("COLLECTED", True)
                    frame = clip.frame
                else:
                    frame = self._timeline.states[0][0]
                key = index, self._generation
                visual = GoldVisual(key, *self._positions[index], frame, self._color(visible))
                self._effects[key] = _GoldEffect(0, visual, clip)
                self._snapshot_dirty = True

    def advance(self, timeline_frames=3):
        """Age existing effects, including after a ghost stops and during hold."""
        if not self._effects:
            return
        frames = max(0, integer_index(timeline_frames))
        expired = []
        for key, effect in self._effects.items():
            if effect.clip is None:
                effect.age += frames
                frame, visible = self._timeline.sample(effect.age)
            else:
                effect.clip.advance(frames)
                frame, visible = effect.clip.frame, effect.clip.visible
            if not visible:
                expired.append(key)
            elif frame != effect.visual.frame:
                old = effect.visual
                effect.visual = GoldVisual(key, old.x, old.y, frame, old.color)
                self._snapshot_dirty = True
        if expired:
            for key in expired:
                del self._effects[key]
            self._snapshot_dirty = True

    @property
    def animating(self):
        return bool(self._effects)

    def snapshot(self):
        if self._idle_changed:
            changed = False
            for index in self._idle_changed:
                owners = self._pending.get(index, 0)
                position = bisect_left(self._idle_indices, index)
                present = (position < len(self._idle_indices)
                           and self._idle_indices[position] == index)
                if owners:
                    color = self._color(owners)
                    if present and self._idle_rows[position].color == color:
                        continue
                    row = GoldVisual((index, 0), *self._positions[index],
                                     1 if self._clip_info else None, color)
                    if present:
                        self._idle_rows[position] = row
                    else:
                        self._idle_indices.insert(position, index)
                        self._idle_rows.insert(position, row)
                elif present:
                    del self._idle_indices[position]
                    del self._idle_rows[position]
                else:
                    continue
                changed = True
            self._idle_changed.clear()
            if changed:
                self._idle = tuple(self._idle_rows)
                self._snapshot_dirty = True
        if not self._effects:
            return self._idle
        # Effects sit underneath remaining markers, so the new owner's colour
        # is visible immediately even on the first collection-animation frame.
        if self._snapshot_dirty:
            self._snapshot = tuple(effect.visual for effect in self._effects.values()) + self._idle
            self._snapshot_dirty = False
        return self._snapshot
