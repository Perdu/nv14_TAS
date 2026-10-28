"""Shared-buffer lifetime, reusable spawned sessions and sparse frame writes."""
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
import hashlib
from io import BytesIO
from multiprocessing import shared_memory
import os
from pathlib import Path

import pytest

import nv14_video_parallel as parallel
from nv14_video_parallel import OrderedFrameRenderer, RenderWorkerSession


LEVEL = "0" * 713 + "|5^100,100"
FRAME_BYTES = 792 * 600 * 3


def scene(index):
    return {"objects": [], "visual": {
        "x": 100.25 + index * 3.1, "y": 100.5 + index * .7,
        "frame": index + 1, "visible": True,
        "facing": 1 if index % 2 else -1, "rotation_deg": index * 17.25}}


class DigestStream:
    def __init__(self):
        self.frames = []

    def write(self, pixels):
        self.frames.append(hashlib.sha256(pixels).hexdigest())
        return len(pixels)


class MemoryExecutor:
    """Complete real shared slots in arbitrary order without drawing artwork."""
    def __init__(self, **options):
        self.futures = []
        self.jobs = []
        self.closed = False

    def submit(self, function, *args):
        future = Future()
        self.futures.append(future)
        self.jobs.append(args)
        return future

    def complete(self, index):
        index_value, options, size, name, offset, config = self.jobs[index]
        segment = shared_memory.SharedMemory(name=name)
        view = segment.buf[offset:offset + size[0] * size[1] * 3]
        try:
            view[:] = bytes([index_value]) * len(view)
        finally:
            view.release()
            segment.close()
        self.futures[index].set_result(parallel._RenderedFrame(.01, {"cache_hits": 2}))

    def shutdown(self, **options):
        self.closed = True


def test_shared_slots_are_ordered_retained_and_unlinked(monkeypatch):
    monkeypatch.setattr(parallel, "ProcessPoolExecutor", MemoryExecutor)
    stream = DigestStream()
    writer = OrderedFrameRenderer(stream, object(), LEVEL, workers=2,
                                  max_pending_bytes=5 * FRAME_BYTES)
    name = writer._segment.name
    assert writer.transport == "shared_memory"
    assert writer._segment.size == 5 * FRAME_BYTES
    for index in range(3):
        writer.submit(index, {}, repeat_count=1)
    writer.extend_last(2)
    for index in (2, 0, 1):
        writer._executor.complete(index)
    writer.flush()
    writer.extend_last(1)
    expected = [hashlib.sha256(bytes([i]) * FRAME_BYTES).hexdigest() for i in range(3)]
    assert stream.frames == expected[:2] + [expected[2]] * 4
    assert writer.frames_written == 6
    assert writer.timings["frames_rendered"] == 3
    assert writer.timings["transported_bytes"] == 6 * FRAME_BYTES
    assert writer.renderer_stats == {"cache_hits": 6}
    writer.close()
    with pytest.raises(FileNotFoundError):
        shared_memory.SharedMemory(name=name)


def test_scale_four_budget_can_run_four_workers(monkeypatch):
    monkeypatch.setattr(parallel, "ProcessPoolExecutor", MemoryExecutor)
    with OrderedFrameRenderer(BytesIO(), object(), LEVEL, scale=4, workers=8) as writer:
        assert writer.workers == writer.max_pending == 4
        assert writer._segment.size == 5 * FRAME_BYTES * 16
        assert writer._segment.size <= 128 * 1024**2


def test_shared_memory_failure_falls_back_to_serial(monkeypatch):
    from PIL import Image

    class Renderer:
        def render(self, *args, **kwargs):
            return Image.new("RGB", (792, 600), (1, 2, 3))

    def unavailable(*args, **kwargs):
        raise OSError("shared memory disabled")

    monkeypatch.setattr(parallel.shared_memory, "SharedMemory", unavailable)
    stream = DigestStream()
    with OrderedFrameRenderer(stream, Renderer(), LEVEL, workers=4) as writer:
        assert writer.workers == 1 and writer.transport == "serial"
        writer.submit({}, {}, 1)
    assert len(stream.frames) == 1


def test_native_or_chunked_render_into_avoids_tobytes_path():
    class Renderer:
        size = (792, 600)
        performance_stats = {}

        def render(self, *args, **kwargs):
            raise AssertionError("transport must use render_into")

        def render_into(self, item, buffer, **options):
            buffer[:] = bytes([item]) * len(buffer)

    stream = DigestStream()
    with OrderedFrameRenderer(stream, Renderer(), LEVEL) as writer:
        writer.submit(1, {}, 0)
        writer.extend_last(2)
        retained = writer._last_pixels
        writer.submit(2, {}, 1)
        assert writer._last_pixels is retained
    assert stream.frames[:2] == [hashlib.sha256(b"\x01" * FRAME_BYTES).hexdigest()] * 2
    assert stream.frames[2] == hashlib.sha256(b"\x02" * FRAME_BYTES).hexdigest()


def test_short_writes_preserve_complete_frame():
    class Image:
        size = (792, 600)
        mode = "RGB"

        def tobytes(self):
            return b"abcdefg"

    class Renderer:
        def render(self, *args, **kwargs):
            return Image()

    class ShortStream(BytesIO):
        def write(self, pixels):
            return super().write(pixels[:2])

    stream = ShortStream()
    with OrderedFrameRenderer(stream, Renderer(), LEVEL) as writer:
        writer.submit({}, {}, 2)
        assert writer.frames_written == 2
        assert writer.timings["transported_bytes"] == 14
    assert stream.getvalue() == b"abcdefgabcdefg"


def test_timed_output_repeats_only_metadata_but_retains_zero_count_frame():
    class Image:
        size = (792, 600)
        mode = "RGB"

        def __init__(self, pixels):
            self.pixels = pixels

        def tobytes(self):
            return self.pixels

    class Renderer:
        def render(self, item, **options):
            return Image(item)

    class TimedStream:
        def __init__(self):
            self.events = []

        def write(self, pixels):
            raise AssertionError("duplicate RGB pipe writes are unnecessary")

        def write_frame(self, pixels, repeats):
            if repeats:
                self.events.append((bytes(pixels), repeats))

        def repeat_last(self, repeats):
            self.events.append((None, repeats))

    stream = TimedStream()
    with OrderedFrameRenderer(stream, Renderer(), LEVEL) as writer:
        writer.submit(b"first", {}, 3)
        writer.extend_last(2)
        writer.submit(b"second", {}, 0)
        writer.extend_last(1)
        writer.extend_last(4)
        assert writer.frames_written == 10
        assert writer.timings["transported_bytes"] == 11
    assert stream.events == [(b"first", 3), (None, 2), (b"second", 1), (None, 4)]


def test_session_reuses_spawned_pool_and_correct_custom_layers():
    from nv14_render import SceneRenderer

    renderers = [SceneRenderer(LEVEL), SceneRenderer(LEVEL, background=(190, 200, 210))]
    session = RenderWorkerSession(workers=2, max_cached_configs=2)
    pids = None
    config_tokens = []
    try:
        for index in (0, 1, 0):
            renderer = renderers[index]
            stream = DigestStream()
            expected = DigestStream()
            with OrderedFrameRenderer(expected, renderer, LEVEL) as serial:
                serial.submit(scene(0), {}, 1)
                serial.submit(scene(1), {}, 2)
            with OrderedFrameRenderer(stream, renderer, LEVEL, workers=2,
                                      worker_session=session) as writer:
                writer.submit(scene(0), {}, 1)
                writer.submit(scene(1), {}, 2)
                writer.flush()
                assert writer._executor is session._executor
                config_tokens.append(writer._config[0])
                if pids is None:
                    pids = set(session._executor._processes)
                assert set(session._executor._processes) == pids
                name = writer._segment.name
            assert stream.frames == expected.frames
            assert session._active is None
            with pytest.raises(FileNotFoundError):
                shared_memory.SharedMemory(name=name)
        assert config_tokens[0] == config_tokens[2] != config_tokens[1]
        directory = Path(session._directory.name)
        processes = tuple(session._executor._processes.values())
    finally:
        session.close()
    assert not directory.exists()
    assert all(not process.is_alive() for process in processes)
    session.close()


def test_session_worker_failure_allows_subsequent_export():
    from nv14_render import SceneRenderer

    renderer = SceneRenderer(LEVEL)
    with RenderWorkerSession(workers=2) as session:
        writer = OrderedFrameRenderer(BytesIO(), renderer, LEVEL, workers=2,
                                      worker_session=session)
        writer.submit({}, {}, 1)
        writer.submit(scene(0), {}, 1)
        with pytest.raises(RuntimeError, match="no player visuals"):
            writer.flush()
        assert session._active is None
        stream = DigestStream()
        with OrderedFrameRenderer(stream, renderer, LEVEL, workers=2,
                                  worker_session=session) as another:
            another.submit(scene(1), {}, 1)
        assert len(stream.frames) == 1


def test_session_restarts_pool_after_process_crash():
    from nv14_render import SceneRenderer

    renderer = SceneRenderer(LEVEL)
    with RenderWorkerSession(workers=2) as session:
        writer = OrderedFrameRenderer(BytesIO(), renderer, LEVEL, workers=2,
                                      worker_session=session)
        crashed = session._executor.submit(os._exit, 17)
        with pytest.raises(BrokenProcessPool):
            crashed.result(timeout=15)
        with pytest.raises(BrokenProcessPool):
            writer.submit(scene(0), {}, 1)
        assert writer._closed and session._executor is None
        stream = DigestStream()
        with OrderedFrameRenderer(stream, renderer, LEVEL, workers=2,
                                  worker_session=session) as another:
            another.submit(scene(1), {}, 1)
        assert len(stream.frames) == 1


def test_session_rejects_simultaneous_exports_and_cleans_live_writer():
    from nv14_render import SceneRenderer

    renderer = SceneRenderer(LEVEL)
    session = RenderWorkerSession(workers=2)
    writer = OrderedFrameRenderer(BytesIO(), renderer, LEVEL, workers=2,
                                  worker_session=session)
    name = writer._segment.name
    with pytest.raises(RuntimeError, match="active export"):
        OrderedFrameRenderer(BytesIO(), renderer, LEVEL, workers=2,
                             worker_session=session)
    writer.submit(scene(0), {}, 1)
    session.close()
    assert writer._closed
    with pytest.raises(FileNotFoundError):
        shared_memory.SharedMemory(name=name)
    with pytest.raises(RuntimeError, match="session is closed"):
        OrderedFrameRenderer(BytesIO(), renderer, LEVEL, workers=2,
                             worker_session=session)
