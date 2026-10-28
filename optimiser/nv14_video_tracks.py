"""Compact, optional replay pose tracks and gold events for video comparison.

Records preserve binary64 poses and all visual metadata. Capture runs in native
batches and spills to a temporary file, so long replays do not accumulate Python
snapshots. The optional persistent cache stores checked JSON and fixed-width
binary records; it never deserialises executable objects.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import warnings


_RECORD = struct.Struct("<4d6i5B3x")
_GOLD_EVENT = struct.Struct("<QQ")  # local replay tick, gold state index
_MAGIC = b"NV14VT2\n"
_CACHE_VERSION = 2
_COPY_BLOCK = 1024 * 1024
_ANIMATIONS = (
    "STAND", "SKID", "RUN", "JUMP", "WALLSLIDE", "CELEBRATE_OLD",
    *(f"CELEBRATE_NEW{i}" for i in range(1, 10)), "RAGDOLL", "CELEBRATE_UNRESOLVED",
)
_RENDER_MODES = ("static_ground", "run", "in_air", "wallslide", "ragdoll")
_ENGINE_IDENTITIES = {}


def _engine_identity():
    """Include the actual simulation/animation binary, not just its ABI number."""
    import _nv14_native

    path = Path(_nv14_native.__file__)
    stat = path.stat()
    identity = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    if identity not in _ENGINE_IDENTITIES:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while block := source.read(_COPY_BLOCK):
                digest.update(block)
        _ENGINE_IDENTITIES[identity] = digest.hexdigest()
    return _ENGINE_IDENTITIES[identity]


def _cache_key(level, frames, final_neutral, capture_gold=False):
    digest = hashlib.sha256()
    metadata = {
        "format": _CACHE_VERSION, "engine": _engine_identity(),
        "level": level.level_string, "simulate_enemies": bool(level.simulate_enemies),
        "final_neutral": bool(final_neutral), "timeline_frames": 3,
        "celebration_variant": 1, "source_frames": len(frames),
        "capture_gold": capture_gold,
    }
    digest.update(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    # Distinguish stored trigger=False/True from automatic edge detection (None).
    for start in range(0, len(frames), 4096):
        digest.update(bytes(
            int(bool(frame.left)) | int(bool(frame.right)) << 1 |
            int(bool(frame.jump)) << 2 |
            (0 if frame.jump_trigger is None else 1 + int(bool(frame.jump_trigger))) << 3
            for frame in frames[start:start + 4096]
        ))
    return digest.hexdigest()


def _decode_record(raw):
    (x, y, rotation, remainder, facing, animation, frame, previous, run, mode,
     playing, visible, terminal, dead, complete) = _RECORD.unpack(raw)
    visual = {
        "x": x, "y": y, "rotation_deg": rotation, "run_remainder": remainder,
        "facing": facing, "animation": _ANIMATIONS[animation], "frame": frame or None,
        "previous_frame": previous or None, "run_frame": run or None,
        "render_mode": _RENDER_MODES[mode], "playing": bool(playing),
        "visible": bool(visible), "terminal": bool(terminal),
    }
    return visual, bool(dead), bool(complete)


class VisualTrack:
    """Replay-compatible player clock backed by compact native visual capture.

    ``step()`` advances the playback clock by one tick. Capturing is chunked and
    may run ahead internally; terminal flags always describe the displayed tick.
    ``precompute()`` captures the remaining inputs without moving that clock, and
    provides ``completion_tick`` for exit alignment. Call ``close()`` when done.
    """

    def __init__(self, level, frames, final_neutral, *, offset=0, color=None,
                 chunk_size=512, cache_dir=None, capture_gold=False):
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
            raise ValueError("chunk_size must be a positive integer")
        if not isinstance(capture_gold, bool):
            raise ValueError("capture_gold must be a boolean")
        self.capture_gold = capture_gold
        self._gold_count = level.gold_count if capture_gold else 0
        self._gold_events = []
        self._gold_cursor = 0
        self.gold_pickups = ()
        self.frames = frames
        self.final_neutral = bool(final_neutral)
        self.offset, self.color = offset, color
        self.ticks = 0
        self.dead = self.complete = self.sentinel_written = False
        self.chunk_size = chunk_size
        self.total_ticks = self.completion_tick = None
        self.cache_hit = False
        self._count = 0
        self._data_offset = 0
        self._final_dead = self._final_complete = False
        self._cache_path = self._key = None
        self._cache_written = False
        self._closed = False
        self.state = None
        self._stream = None
        if cache_dir is not None:
            self._key = _cache_key(level, frames, final_neutral, capture_gold)
            self._cache_path = Path(cache_dir) / f"{self._key}.nv14-track"
            if self._load_cache():
                self.cache_hit = True
                return
        self.state = level.initial_state(
            track_visuals=True, visual_timeline_frames=3, celebration_variant=1)
        self.initial_visual = self.state.visual_snapshot()
        self.visual = self.initial_visual.copy()
        # At most 256 KiB per track remains in RAM; longer tracks spill to disk.
        self._stream = tempfile.SpooledTemporaryFile(max_size=256 * 1024, mode="w+b")
        if not self._input_count:
            self._finish_capture()

    @property
    def _input_count(self):
        return len(self.frames) + int(self.final_neutral)

    @property
    def done(self):
        return (self.dead or self.complete or self.ticks >= self._input_count
                or self.total_ticks is not None and self.ticks >= self.total_ticks)

    def _capture_chunk(self):
        from nv14_engine import InputFrame

        if self.total_ticks is not None:
            return
        end = min(self._count + self.chunk_size, self._input_count)
        inputs = list(self.frames[self._count:min(end, len(self.frames))])
        if end > len(self.frames):
            inputs.append(InputFrame())
        if self.capture_gold:
            raw, events = self.state.capture_gold_visual_frames(inputs)
            self._gold_events.extend((self._count + tick, index) for tick, index in events)
        else:
            raw = self.state.capture_visual_frames(inputs)
        count, remainder = divmod(len(raw), _RECORD.size)
        if remainder or count > len(inputs):
            raise RuntimeError("native visual capture returned an invalid record buffer")
        self._stream.seek(self._count * _RECORD.size)
        self._stream.write(raw)
        self._count += count
        if count:
            _, self._final_dead, self._final_complete = _decode_record(raw[-_RECORD.size:])
        if self._final_dead or self._final_complete or self._count >= self._input_count:
            self._finish_capture()
        elif count != len(inputs):
            raise RuntimeError("native visual capture stopped without a terminal frame")

    def _finish_capture(self):
        self.total_ticks = self._count
        self.completion_tick = self._count if self._final_complete else None
        self.state = None
        if self._cache_path is not None and not self._cache_written:
            self._save_cache()

    def precompute(self):
        while self.total_ticks is None:
            self._capture_chunk()
        return self

    def step(self):
        if self.done:
            raise RuntimeError("cannot advance a finished visual track")
        if self.ticks == self._count:
            self._capture_chunk()
        self._stream.seek(self._data_offset + self.ticks * _RECORD.size)
        self.visual, self.dead, self.complete = _decode_record(self._stream.read(_RECORD.size))
        self.sentinel_written = self.ticks == len(self.frames)
        self.ticks += 1
        if self.capture_gold:
            start = self._gold_cursor
            while (self._gold_cursor < len(self._gold_events)
                   and self._gold_events[self._gold_cursor][0] <= self.ticks):
                self._gold_cursor += 1
            self.gold_pickups = tuple(index for _, index in self._gold_events[start:self._gold_cursor])
        # The comparison driver only consumes the primary's returned input.
        return None

    def result(self, index):
        from nv14_video import VideoReplayResult

        return VideoReplayResult(
            index, len(self.frames), self.ticks, self.offset, self.color,
            "complete" if self.complete else "dead" if self.dead else "input_end",
            self.sentinel_written, self.dead, self.complete)

    def _load_cache(self):
        stream = None
        try:
            stream = self._cache_path.open("rb")
            if stream.read(len(_MAGIC)) != _MAGIC:
                return False
            raw_size = stream.read(4)
            if len(raw_size) != 4:
                return False
            header_size, = struct.unpack("<I", raw_size)
            if not 0 < header_size <= 16384:
                return False
            header = json.loads(stream.read(header_size))
            count = header["records"]
            event_count = header["gold_events"]
            if (header["version"] != _CACHE_VERSION or header["key"] != self._key
                    or type(count) is not int or not 0 <= count <= self._input_count
                    or type(event_count) is not int or not 0 <= event_count <= self._gold_count
                    or not isinstance(header["initial_visual"], dict)):
                return False
            initial = header["initial_visual"]
            required = {"x", "y", "rotation_deg", "run_remainder", "facing", "animation",
                        "frame", "previous_frame", "run_frame", "render_mode", "playing",
                        "visible", "terminal"}
            if set(initial) != required:
                return False
            data_offset = stream.tell()
            if os.fstat(stream.fileno()).st_size != data_offset + count * _RECORD.size + event_count * _GOLD_EVENT.size:
                return False
            digest = hashlib.sha256()
            while block := stream.read(_COPY_BLOCK):
                digest.update(block)
            if digest.hexdigest() != header["sha256"]:
                return False
            stream.seek(data_offset + count * _RECORD.size)
            events = list(_GOLD_EVENT.iter_unpack(stream.read(event_count * _GOLD_EVENT.size)))
            if (any(not 1 <= tick <= count or index >= self._gold_count for tick, index in events)
                    or events != sorted(events) or len({index for _, index in events}) != event_count):
                return False
            dead = complete = False
            if count:
                stream.seek(data_offset + (count - 1) * _RECORD.size)
                _, dead, complete = _decode_record(stream.read(_RECORD.size))
            if count < self._input_count and not (dead or complete):
                return False
            self.initial_visual = initial
            self.visual = initial.copy()
            self._count = self.total_ticks = count
            self._final_dead, self._final_complete = dead, complete
            self.completion_tick = count if complete else None
            self._data_offset = data_offset
            self._gold_events = events
            self._stream, stream = stream, None
            self._cache_written = True
            return True
        except (OSError, ValueError, TypeError, KeyError, IndexError, struct.error):
            return False
        finally:
            if stream is not None:
                stream.close()

    def _save_cache(self):
        self._cache_written = True
        temporary = None
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            self._stream.seek(0)
            while block := self._stream.read(_COPY_BLOCK):
                digest.update(block)
            gold_data = b"".join(_GOLD_EVENT.pack(*event) for event in self._gold_events)
            digest.update(gold_data)
            header = json.dumps({
                "version": _CACHE_VERSION, "key": self._key, "records": self._count,
                "gold_events": len(self._gold_events),
                "initial_visual": self.initial_visual, "sha256": digest.hexdigest(),
            }, sort_keys=True, separators=(",", ":")).encode("utf-8")
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".nv14-track-",
                    suffix=".tmp", dir=self._cache_path.parent, delete=False) as output:
                temporary = Path(output.name)
                output.write(_MAGIC)
                output.write(struct.pack("<I", len(header)))
                output.write(header)
                self._stream.seek(0)
                while block := self._stream.read(_COPY_BLOCK):
                    output.write(block)
                output.write(gold_data)
                output.flush()
            os.replace(temporary, self._cache_path)
            temporary = None
        except OSError as exc:
            warnings.warn(f"Could not save replay visual cache: {exc}", RuntimeWarning,
                          stacklevel=2)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def close(self):
        if not self._closed:
            self._closed = True
            self.state = None
            if self._stream is not None:
                self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
