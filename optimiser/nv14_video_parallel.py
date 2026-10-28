"""Optional ordered, bounded frame rendering for the video encoder.

Simulation and cosmetic timelines stay in the submitting process. Spawned
workers draw immutable snapshots into a bounded shared RGB ring, returning only
small timing records. Importing this module does not import Pillow or an engine.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import multiprocessing
from multiprocessing import shared_memory
import os
from pathlib import Path
import pickle
import shutil
import tempfile
from time import perf_counter
import uuid


_worker_renderer = None
_worker_renderers = OrderedDict()
_worker_cache_limit = 2


def _initialise_worker(level_string, assets_path, scale, render_quality, terrain_layers=None):
    global _worker_renderer
    from nv14_render import SceneRenderer

    _worker_renderer = SceneRenderer(level_string, assets_path=assets_path,
        scale=scale, render_quality=render_quality, _terrain_layers=terrain_layers)


def _initialise_session_worker(max_cached_configs):
    global _worker_renderer, _worker_renderers, _worker_cache_limit
    _worker_renderer = None
    _worker_renderers = OrderedDict()
    _worker_cache_limit = max_cached_configs


def _session_renderer(config):
    """Load immutable layers once per worker/config, never once per frame."""
    key, filename = config
    renderer = _worker_renderers.get(key)
    if renderer is None:
        from nv14_render import SceneRenderer
        # This is a private seed written by this process's parent, not a user
        # cache or replay file. Its directory is owned by RenderWorkerSession.
        with open(filename, "rb") as stream:
            settings = pickle.load(stream)
        renderer = SceneRenderer(**settings)
        _worker_renderers[key] = renderer
        while len(_worker_renderers) > _worker_cache_limit:
            _worker_renderers.popitem(last=False)
    _worker_renderers.move_to_end(key)
    return renderer


def _render_rgb(renderer, scene, options, expected_size):
    image = renderer.render(scene, **options)
    if image.mode != "RGB" or image.size != expected_size:
        raise RuntimeError("renderer returned an invalid RGB frame")
    return image.tobytes()


def _render_rgb_into(renderer, scene, options, expected_size, buffer):
    if len(buffer) != expected_size[0] * expected_size[1] * 3:
        raise RuntimeError("invalid RGB frame buffer size")
    render_into = getattr(renderer, "render_into", None)
    if callable(render_into):
        if getattr(renderer, "size", expected_size) != expected_size:
            raise RuntimeError("renderer returned an invalid RGB frame")
        render_into(scene, buffer, **options)
    else:
        buffer[:] = _render_rgb(renderer, scene, options, expected_size)


def _renderer_stats(renderer):
    stats = getattr(renderer, "stats", getattr(renderer, "performance_stats", {}))
    if callable(stats):
        stats = stats()
    if not isinstance(stats, dict):
        return {}
    return {key: value for key, value in stats.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)}


@dataclass(slots=True)
class _RenderedFrame:
    render_seconds: float
    renderer_stats: dict


def _render_worker(scene, options, expected_size, shared_name=None, offset=0, config=None):
    renderer = _session_renderer(config) if config is not None else _worker_renderer
    if renderer is None:
        raise RuntimeError("video render worker was not initialised")
    if shared_name is None:
        return _render_rgb(renderer, scene, options, expected_size)
    segment = shared_memory.SharedMemory(name=shared_name)
    view = None
    before = _renderer_stats(renderer)
    started = perf_counter()
    try:
        length = expected_size[0] * expected_size[1] * 3
        view = segment.buf[offset:offset + length]
        _render_rgb_into(renderer, scene, options, expected_size, view)
        elapsed = perf_counter() - started
        after = _renderer_stats(renderer)
        return _RenderedFrame(elapsed, {key: value - before.get(key, 0)
                                       for key, value in after.items()})
    finally:
        if view is not None:
            view.release()
        segment.close()


def _render_block_worker(frames, expected_size, shared_name, config=None):
    """Keep neighbouring frames on one renderer and attach the RGB ring once.

    A block is bounded by the parent's existing frame-slot budget. Only small
    completion records travel back through the process pipe; pixel buffers stay
    in their individual slots so output ordering and repeats remain unchanged.
    Pickle also memoizes artwork/visual references shared within this packet.
    """
    renderer = _session_renderer(config) if config is not None else _worker_renderer
    if renderer is None:
        raise RuntimeError("video render worker was not initialised")
    segment = shared_memory.SharedMemory(name=shared_name)
    length = expected_size[0] * expected_size[1] * 3
    completions = []
    try:
        for scene, options, offset in frames:
            before = _renderer_stats(renderer)
            started = perf_counter()
            view = segment.buf[offset:offset + length]
            try:
                _render_rgb_into(renderer, scene, options, expected_size, view)
            finally:
                view.release()
            elapsed = perf_counter() - started
            after = _renderer_stats(renderer)
            completions.append(_RenderedFrame(elapsed, {
                key: value - before.get(key, 0) for key, value in after.items()}))
        return tuple(completions)
    finally:
        segment.close()


def _positive_integer(name, value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _terrain_layers(renderer):
    if hasattr(renderer, "_background") and hasattr(renderer, "_tiles"):
        return renderer._background, renderer._tiles
    return None


class RenderWorkerSession:
    """Reuse one spawned drawing pool and bounded per-worker renderer caches.

    Sequential OrderedFrameRenderer instances can borrow this session. Workers
    retain parsed artwork, immutable terrain and sprite caches for up to
    ``max_cached_configs`` parent renderers. Parent renderer identity is part of
    the key, so custom terrain or background layers are never accidentally
    replaced by another export's artwork. Reuse the parent renderer too for best
    results. ``workers`` is the pool's maximum size; each writer can admit fewer
    jobs when its RGB budget requires it.

    Private temporary seed files transmit large immutable layers just once per
    worker/config without putting them in every frame's process message. Closing
    a writer returns the pool; closing the session joins workers and deletes all
    seed files. A session supports one active export at a time.
    """

    def __init__(self, workers=4, *, max_cached_configs=2):
        _positive_integer("workers", workers)
        _positive_integer("max_cached_configs", max_cached_configs)
        self.workers = workers
        self.max_cached_configs = max_cached_configs
        self._executor = None
        self._directory = None
        self._configs = OrderedDict()
        self._active = None
        self._closed = False

    def _acquire(self, owner, renderer, level_string, assets_path, scale, render_quality):
        if self._closed:
            raise RuntimeError("render worker session is closed")
        if self._active is not None:
            raise RuntimeError("render worker session already has an active export")
        assets = str(Path(assets_path).resolve()) if assets_path is not None else None
        asset_root = Path(assets) if assets is not None else Path(__file__).parent / "nv14_assets"
        try:
            stat = (asset_root / "manifest.json").stat()
            fingerprint = stat.st_mtime_ns, stat.st_size
        except OSError:
            fingerprint = None  # SceneRenderer reports missing assets normally.
        key = (id(renderer), level_string, assets, fingerprint, scale, render_quality)
        entry = self._configs.get(key)
        if entry is None:
            if self._directory is None:
                self._directory = tempfile.TemporaryDirectory(prefix="nv14-render-session-")
            token = uuid.uuid4().hex
            filename = str(Path(self._directory.name) / (token + ".pickle"))
            settings = dict(level_data=level_string, assets_path=assets, scale=scale,
                            render_quality=render_quality, _terrain_layers=_terrain_layers(renderer))
            try:
                with open(filename, "wb") as stream:
                    pickle.dump(settings, stream, protocol=pickle.HIGHEST_PROTOCOL)
            except BaseException:
                Path(filename).unlink(missing_ok=True)
                raise
            # Retain the parent object as well, preventing Python id reuse from
            # ever producing a false cache hit after another level is evicted.
            entry = (renderer, (token, filename))
            self._configs[key] = entry
            while len(self._configs) > self.max_cached_configs:
                _, (_, (_, old_filename)) = self._configs.popitem(last=False)
                Path(old_filename).unlink(missing_ok=True)
        self._configs.move_to_end(key)
        if self._executor is None:
            self._executor = ProcessPoolExecutor(
                max_workers=self.workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_initialise_session_worker,
                initargs=(self.max_cached_configs,),
            )
        self._active = owner
        return self._executor, entry[1]

    def _release(self, owner):
        if self._active is owner:
            self._active = None

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._active is not None:
                self._active.close()
        finally:
            executor, self._executor = self._executor, None
            try:
                if executor is not None:
                    executor.shutdown(wait=True, cancel_futures=True)
            finally:
                self._configs.clear()
                if self._directory is not None:
                    self._directory.cleanup()
                    self._directory = None

    def __enter__(self):
        if self._closed:
            raise RuntimeError("render worker session is closed")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


@dataclass(slots=True)
class _PendingFrame:
    future: object
    repeats: int
    slot: int
    result_index: int | None = None


class OrderedFrameRenderer:
    """Draw and write RGB frames in order with a bounded shared-memory ring.

    ``submit`` borrows snapshots until they drain. ``extend_last`` duplicates the
    last submitted image, even after ``flush``. The caller owns ``stream``.

    Parallel workers return small completion records, never full RGB payloads.
    Consecutive frames are grouped into jobs of up to four, letting each worker
    retain drawing state between neighbouring frames. The first frame starts
    immediately, and flush/drain submit any partial block. Blocks shrink when
    necessary to keep the requested workers occupied within the RGB budget.
    The budget counts one slot per queued image plus a retained last-frame slot;
    it excludes renderer artwork/caches and each worker's drawing canvas. For
    example, 128 MiB holds five scale-4 RGB slots and permits four workers. Small
    budgets reduce concurrency. Serial mode retains one frame, even when the
    requested budget is smaller. If shared memory is unavailable, rendering
    falls back to serial instead of creating an unbounded process pipe queue.

    ``worker_session`` optionally lends a persistent spawned pool. ``close``
    cancels pending work and releases slots, without flushing or closing the
    caller's stream. Successful callers must flush first. Timing and renderer
    cache counters are available in ``timings`` and ``renderer_stats``.
    """

    def __init__(self, stream, renderer, level_string, *, assets_path=None,
                 scale=1, render_quality="exact", workers=1,
                 max_pending_bytes=128 * 1024 ** 2, worker_session=None):
        for name, value in (("workers", workers), ("scale", scale),
                            ("max_pending_bytes", max_pending_bytes)):
            _positive_integer(name, value)
        if worker_session is not None and not isinstance(worker_session, RenderWorkerSession):
            raise TypeError("worker_session must be a RenderWorkerSession")
        if worker_session is not None and worker_session._closed:
            raise RuntimeError("render worker session is closed")
        self.stream = stream
        self.renderer = renderer
        self.size = (792 * scale, 600 * scale)
        self.frame_bytes = self.size[0] * self.size[1] * 3
        self.requested_workers = workers
        available_bytes = max_pending_bytes
        # POSIX shm creation may succeed despite a too-small /dev/shm mount and
        # then SIGBUS on first write. Inspect available space before allocation.
        if os.name == "posix" and Path("/dev/shm").is_dir():
            try:
                available_bytes = min(available_bytes, max(0, shutil.disk_usage("/dev/shm").free - 1024**2))
            except OSError:
                pass
        budget_slots = max(1, available_bytes // self.frame_bytes - 1)
        capacity = worker_session.workers if worker_session is not None else workers
        self.workers = min(workers, capacity, budget_slots)
        # Batch only buffer-capable renderers. Keep the original one-frame
        # protocol for integrations with lightweight byte-producing workers.
        block_cap = 4 if callable(getattr(renderer, "render_into", None)) else 1
        self.max_pending = min(max(2, block_cap) * self.workers, budget_slots)
        self.block_size = min(block_cap, max(1, self.max_pending // self.workers))
        self.frames_written = 0
        self.timings = dict(render_seconds=0.0, wait_seconds=0.0, write_seconds=0.0,
                            frames_rendered=0, transported_bytes=0)
        self.renderer_stats = {}
        self._pending = deque()
        self._staged = []
        self._submitted_blocks = 0
        self._last_pixels = None
        self._last_slot = None
        self._last_emitted = False
        self._closed = False
        self._executor = None
        self._session = worker_session
        self._config = None
        self._segment = None
        self._free_slots = deque()
        self.transport = "serial"
        if self.workers > 1:
            try:
                self._segment = shared_memory.SharedMemory(
                    create=True, size=(self.max_pending + 1) * self.frame_bytes)
            except OSError:
                self.workers = self.max_pending = 1
                self.block_size = 1
            else:
                self._free_slots.extend(range(self.max_pending + 1))
                self.transport = "shared_memory"
                try:
                    if worker_session is not None:
                        self._executor, self._config = worker_session._acquire(
                            self, renderer, level_string, assets_path, scale, render_quality)
                    else:
                        assets = str(Path(assets_path).resolve()) if assets_path is not None else None
                        self._executor = ProcessPoolExecutor(
                            max_workers=self.workers,
                            mp_context=multiprocessing.get_context("spawn"),
                            initializer=_initialise_worker,
                            initargs=(level_string, assets, scale, render_quality,
                                      _terrain_layers(renderer)),
                        )
                except BaseException:
                    self._segment.close()
                    self._segment.unlink()
                    self._segment = None
                    raise

    def _check_open(self):
        if self._closed:
            raise RuntimeError("frame renderer is closed")

    @staticmethod
    def _validate_repeats(repeat_count):
        if (isinstance(repeat_count, bool) or not isinstance(repeat_count, int)
                or repeat_count < 0):
            raise ValueError("repeat_count must be a non-negative integer")

    def _write(self, pixels, repeat_count):
        started = perf_counter()
        try:
            write_frame = getattr(self.stream, "write_frame", None)
            if callable(write_frame):
                write_frame(pixels, repeat_count)
                if repeat_count:
                    self.timings["transported_bytes"] += len(pixels)
                    self.frames_written += repeat_count
                    self._last_emitted = True
                return
            for _ in range(repeat_count):
                # Buffered FFmpeg pipes usually consume the complete buffer.
                # Honour short writes for raw streams and custom integrations.
                consumed = 0
                view = memoryview(pixels)
                try:
                    while consumed < len(view):
                        tail = view[consumed:]
                        try:
                            written = self.stream.write(tail)
                        finally:
                            tail.release()
                        if written is None:
                            written = len(view) - consumed
                        if written <= 0 or written > len(view) - consumed:
                            raise OSError("video output stream did not accept RGB frame data")
                        consumed += written
                finally:
                    view.release()
                self.timings["transported_bytes"] += consumed
                self.frames_written += 1
                self._last_emitted = True
        finally:
            self.timings["write_seconds"] += perf_counter() - started

    def _write_slot(self, slot, repeat_count):
        start = slot * self.frame_bytes
        pixels = self._segment.buf[start:start + self.frame_bytes]
        try:
            self._write(pixels, repeat_count)
        finally:
            pixels.release()

    def _collect_stats(self, elapsed, stats):
        self.timings["render_seconds"] += elapsed
        self.timings["frames_rendered"] += 1
        for key, value in stats.items():
            self.renderer_stats[key] = self.renderer_stats.get(key, 0) + value

    def _submit_staged(self):
        if not self._staged:
            return
        staged = self._staged
        try:
            if len(staged) == 1:
                entry, scene, options = staged[0]
                future = self._executor.submit(
                    _render_worker, scene, options, self.size, self._segment.name,
                    entry.slot * self.frame_bytes, self._config)
            else:
                frames = tuple((scene, options, entry.slot * self.frame_bytes)
                               for entry, scene, options in staged)
                future = self._executor.submit(
                    _render_block_worker, frames, self.size, self._segment.name,
                    self._config)
            for index, (entry, _, _) in enumerate(staged):
                entry.future = future
                if len(staged) > 1:
                    entry.result_index = index
            self._staged = []
            self._submitted_blocks += 1
        except BaseException:
            self.close()
            raise

    def submit(self, scene, options, repeat_count=1):
        """Render once and write ``repeat_count`` copies, draining if needed."""
        self._check_open()
        self._validate_repeats(repeat_count)
        if self._executor is None:
            before = _renderer_stats(self.renderer)
            started = perf_counter()
            if callable(getattr(self.renderer, "render_into", None)):
                if self._last_pixels is None:
                    self._last_pixels = bytearray(self.frame_bytes)
                _render_rgb_into(self.renderer, scene, options, self.size, self._last_pixels)
            else:
                self._last_pixels = _render_rgb(self.renderer, scene, options, self.size)
            elapsed = perf_counter() - started
            after = _renderer_stats(self.renderer)
            self._collect_stats(elapsed, {key: value - before.get(key, 0)
                                          for key, value in after.items()})
            self._last_emitted = False
            self._write(self._last_pixels, repeat_count)
            return
        if len(self._pending) >= self.max_pending:
            self.drain_one()
        slot = self._free_slots.popleft()
        entry = _PendingFrame(None, repeat_count, slot)
        self._pending.append(entry)
        self._staged.append((entry, scene, options))
        # Starting immediately avoids adding block-fill latency to short
        # exports. Also propagate a crashed session's submission error promptly.
        if (not self._submitted_blocks or len(self._staged) >= self.block_size
                or getattr(self._executor, "_broken", False)):
            self._submit_staged()

    def extend_last(self, repeat_count=1):
        """Append duplicates of the last submitted frame without rendering."""
        self._check_open()
        self._validate_repeats(repeat_count)
        if not repeat_count:
            return
        if self._pending:
            self._pending[-1].repeats += repeat_count
        elif self._last_emitted and callable(getattr(self.stream, "repeat_last", None)):
            started = perf_counter()
            try:
                self.stream.repeat_last(repeat_count)
                self.frames_written += repeat_count
            finally:
                self.timings["write_seconds"] += perf_counter() - started
        elif self._last_slot is not None:
            self._write_slot(self._last_slot, repeat_count)
        elif self._last_pixels is not None:
            self._write(self._last_pixels, repeat_count)
        else:
            raise RuntimeError("cannot repeat a frame before submitting one")

    repeat_last = extend_last

    def drain_one(self):
        """Wait for and write the oldest completed slot, preserving order."""
        self._check_open()
        if not self._pending:
            return
        # Keep the in-flight entry registered until result() returns, so an
        # interrupted wait cannot unlink a buffer while its worker still runs.
        entry = self._pending[0]
        if entry.future is None:
            self._submit_staged()
        started = perf_counter()
        try:
            result = entry.future.result()
            if entry.result_index is not None:
                if not isinstance(result, tuple) or len(result) <= entry.result_index:
                    raise RuntimeError("invalid render block completion record")
                result = result[entry.result_index]
        except Exception as exc:
            self.close()
            raise RuntimeError(f"video render worker failed: {exc}") from exc
        finally:
            self.timings["wait_seconds"] += perf_counter() - started
        self._pending.popleft()
        if self._last_slot is not None:
            self._free_slots.append(self._last_slot)
            self._last_slot = None
        self._last_emitted = False
        # Keep support for lightweight executor test doubles and integrations
        # that replace _render_worker with a byte-producing function.
        if isinstance(result, (bytes, bytearray)):
            self._free_slots.append(entry.slot)
            self._last_pixels = result
            self._collect_stats(0.0, {})
            self._write(result, entry.repeats)
        else:
            if not isinstance(result, _RenderedFrame):
                self.close()
                raise RuntimeError("video render worker returned an invalid completion record")
            self._last_pixels = None
            self._last_slot = entry.slot
            self._collect_stats(result.render_seconds, result.renderer_stats)
            self._write_slot(entry.slot, entry.repeats)

    def flush(self):
        """Write all submitted frames; keep the last available for repeats."""
        self._check_open()
        self._submit_staged()
        while self._pending:
            self.drain_one()

    def close(self):
        """Cancel pending work and release buffers; safe to call repeatedly."""
        if self._closed:
            return
        self._closed = True
        pending = list(self._pending)
        self._pending.clear()
        self._staged.clear()
        futures = {entry.future for entry in pending if entry.future is not None}
        for future in futures:
            future.cancel()
        executor, self._executor = self._executor, None
        try:
            if executor is not None:
                if self._session is None:
                    executor.shutdown(wait=True, cancel_futures=True)
                else:
                    # Running workers must finish before their shared buffer is
                    # unlinked, but remain alive for the next session export.
                    for future in futures:
                        try:
                            future.result()
                        except Exception:
                            pass
                    # A normal bad scene only fails its own Future. A crashed
                    # process breaks the entire executor; replace that pool on
                    # the next export while retaining reusable config seeds.
                    if getattr(executor, "_broken", False):
                        executor.shutdown(wait=True, cancel_futures=True)
                        if self._session._executor is executor:
                            self._session._executor = None
        finally:
            if self._session is not None:
                self._session._release(self)
            self._last_pixels = None
            self._last_slot = None
            if self._segment is not None:
                segment, self._segment = self._segment, None
                try:
                    segment.close()
                finally:
                    segment.unlink()
            self._free_slots.clear()

    def __enter__(self):
        self._check_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is None:
                self.flush()
        finally:
            self.close()
