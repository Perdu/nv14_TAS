"""Optional reusable preparation and scheduling state for video exports.

Importing this module loads only the standard library. Each export still owns
fresh simulation, cosmetic clocks and an independent FFmpeg process.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
import os
import threading


def _asset_identity(assets_path):
    path = (Path(assets_path) if assets_path is not None else
            Path(__file__).resolve().parent / "nv14_assets").resolve()
    # Include PNG/font metadata too: changing artwork must invalidate already-loaded
    # sprite/text caches even if the JSON manifest is unchanged.
    files = []
    for entry in sorted(path.rglob("*")):
        if entry.is_file() and entry.suffix.lower() in (".json", ".png", ".ttf"):
            stat = entry.stat()
            files.append((str(entry.relative_to(path)), stat.st_size,
                          stat.st_mtime_ns, stat.st_ctime_ns))
    return str(path), tuple(files)


def available_cpus():
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def validate_performance_options(render_workers, render_memory_mib, profile):
    if (isinstance(render_workers, bool) or not isinstance(render_workers, int)
            or not 0 <= render_workers <= 64):
        raise ValueError("render_workers must be an integer from 0 to 64")
    if (isinstance(render_memory_mib, bool) or not isinstance(render_memory_mib, int)
            or not 16 <= render_memory_mib <= 65536):
        raise ValueError("render_memory_mib must be an integer from 16 to 65536")
    if not isinstance(profile, bool):
        raise ValueError("profile must be a boolean")


def choose_workers(*, remaining_ticks, scale, players, object_count, fps,
                   render_seconds=None, write_seconds=None, max_workers=None):
    """Use observed frame cost where available, otherwise a scene estimate.

The first few frames of a fresh automatic export are rendered serially. This
decision spends no extra simulation or rendering work on a synthetic probe.
"""
    limit = min(4, max(1, available_cpus() - 1)) if max_workers is None else max_workers
    if remaining_ticks < 32 or limit <= 1:
        return 1
    if render_seconds is not None:
        render_seconds = max(0., render_seconds)
        write_seconds = max(0., write_seconds or 0.)
        # Small scenes cannot repay spawning/transport. Extra drawing capacity
        # also cannot help a pipe that is already waiting primarily for x264.
        if render_seconds * remaining_ticks < .30:
            return 1
        if write_seconds > render_seconds * 2.5:
            return 1
        if render_seconds < .0006 and scale == 1:
            return 1
        return min(limit, 2 if render_seconds < .0015 else 4)
    work = remaining_ticks * (players + object_count / 12) * scale
    return limit if work >= 6500 or scale >= 3 and remaining_ticks >= 160 else 1


class VideoEncodeSession:
    """Reuse renderers and worker processes across sequential video exports.

    Use as a context manager and call ``encode_replay_video`` or
    ``encode_replay_data_video`` on it. Ordinary encoding functions also accept
    ``session=session``. Pools are created lazily; a serial session creates no
    child processes. ``last_profile`` always contains the latest measurements.

    Cached levels are bounded by ``max_cached_levels``. The RGB transport budget
    is separate from per-renderer terrain and sprite caches. A session may be
    reused after a failed export, but concurrent exports through one session are
    rejected to protect its mutable renderer state.
    """

    def __init__(self, *, render_workers=8, render_memory_mib=128,
                 max_cached_levels=2):
        validate_performance_options(render_workers, render_memory_mib, False)
        if (isinstance(max_cached_levels, bool) or not isinstance(max_cached_levels, int)
                or not 1 <= max_cached_levels <= 16):
            raise ValueError("max_cached_levels must be an integer from 1 to 16")
        self.render_workers = render_workers
        self.render_memory_mib = render_memory_mib
        self.max_cached_levels = max_cached_levels
        self.last_profile = None
        self._renderers = OrderedDict()
        self._levels = OrderedDict()
        self._history = OrderedDict()
        self._pool = None
        self._closed = False
        self._active = False
        self._lock = threading.Lock()

    @contextmanager
    def _using(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("video encoding session is closed")
            if self._active:
                raise RuntimeError("video encoding session is already in use")
            self._active = True
        try:
            yield self
        finally:
            with self._lock:
                self._active = False

    def _native_level(self, native, level_string, simulate_enemies):
        key = (level_string, bool(simulate_enemies), native.NativeLevel)
        value = self._levels.pop(key, None)
        if value is None:
            value = native.parse_level_string(level_string, simulate_enemies=simulate_enemies)
        self._levels[key] = value
        while len(self._levels) > self.max_cached_levels:
            self._levels.popitem(last=False)
        return value

    def _renderer(self, level_string, options):
        from nv14_render import SceneRenderer
        key = (level_string, _asset_identity(options.get("assets_path")),
               options["scale"], options.get("render_quality", "exact"))
        renderer = self._renderers.pop(key, None)
        reused = renderer is not None
        if renderer is None:
            renderer = SceneRenderer(level_string, **options)
        else:
            reset = getattr(renderer, "reset_frame_cache", None)
            if reset is not None:
                reset()
        self._renderers[key] = renderer
        while len(self._renderers) > self.max_cached_levels:
            self._renderers.popitem(last=False)
        return renderer, reused

    def _workers(self, count):
        if count <= 1:
            return None
        from nv14_video_parallel import RenderWorkerSession
        if self._pool is not None and self._pool.workers < count:
            self._pool.close()
            self._pool = None
        if self._pool is None:
            self._pool = RenderWorkerSession(count, max_cached_configs=self.max_cached_levels)
        return self._pool

    def _record(self, key, measurements):
        self.last_profile = dict(measurements)
        self._history.pop(key, None)
        self._history[key] = dict(measurements)
        while len(self._history) > 32:
            self._history.popitem(last=False)

    def encode_replay_video(self, input_path, output_path=None, **options):
        from nv14_video import encode_replay_video
        if "session" in options:
            raise TypeError("session is supplied by VideoEncodeSession")
        options.setdefault("render_workers", self.render_workers)
        options.setdefault("render_memory_mib", self.render_memory_mib)
        return encode_replay_video(input_path, output_path, session=self, **options)

    def encode_replay_data_video(self, level_data, replay_data, output_path, **options):
        from nv14_video import encode_replay_data_video
        if "session" in options:
            raise TypeError("session is supplied by VideoEncodeSession")
        options.setdefault("render_workers", self.render_workers)
        options.setdefault("render_memory_mib", self.render_memory_mib)
        return encode_replay_data_video(level_data, replay_data, output_path,
                                        session=self, **options)

    def close(self):
        with self._lock:
            if self._active:
                raise RuntimeError("cannot close an active video encoding session")
            if self._closed:
                return
            self._closed = True
        try:
            if self._pool is not None:
                self._pool.close()
        finally:
            self._pool = None
            self._renderers.clear()
            self._levels.clear()
            self._history.clear()

    def __enter__(self):
        if self._closed:
            raise RuntimeError("video encoding session is closed")
        return self

    def __exit__(self, *exc):
        self.close()
