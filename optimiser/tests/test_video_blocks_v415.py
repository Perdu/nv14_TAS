"""Neighbouring frame jobs retain ordering without exceeding the RGB budget."""
from concurrent.futures import Future
from multiprocessing import shared_memory

import pytest

import nv14_video_parallel as parallel


LEVEL = "0" * 713 + "|5^100,100"
FRAME_BYTES = 792 * 600 * 3


class BufferRenderer:
    def render_into(self, *args, **kwargs):
        raise AssertionError("the submitting renderer must not draw worker frames")


class FrameStream:
    def __init__(self):
        self.frames = []

    def write_frame(self, pixels, repeats):
        assert len(pixels) == FRAME_BYTES
        self.frames.extend([pixels[0]] * repeats)


class BlockExecutor:
    def __init__(self, **options):
        self.jobs = []
        self.closed = False

    def submit(self, function, *args):
        if function is parallel._render_worker:
            scene, options, size, name, offset, config = args
            frames = ((scene, options, offset),)
        else:
            assert function is parallel._render_block_worker
            frames, size, name, config = args
        self.jobs.append(tuple(scene for scene, _, _ in frames))
        segment = shared_memory.SharedMemory(name=name)
        try:
            for scene, _, offset in frames:
                segment.buf[offset:offset + FRAME_BYTES] = bytes([scene]) * FRAME_BYTES
        finally:
            segment.close()
        completions = tuple(parallel._RenderedFrame(.01, {"frames": 1}) for _ in frames)
        future = Future()
        future.set_result(completions if len(frames) > 1 else completions[0])
        return future

    def shutdown(self, **options):
        self.closed = True


def test_worker_block_attaches_once_and_keeps_frames_on_one_renderer(monkeypatch):
    class Renderer:
        size = (2, 1)

        def __init__(self):
            self.seen = []
            self.stats = {"frames": 0}

        def render_into(self, scene, buffer, **options):
            self.seen.append((scene, options))
            buffer[:] = bytes([scene]) * len(buffer)
            self.stats["frames"] += 1

    renderer = Renderer()
    monkeypatch.setattr(parallel, "_worker_renderer", renderer)
    segment = shared_memory.SharedMemory(create=True, size=18)
    attach = parallel.shared_memory.SharedMemory
    attachments = []

    def tracked_attach(**kwargs):
        attachments.append(kwargs)
        return attach(**kwargs)

    monkeypatch.setattr(parallel.shared_memory, "SharedMemory", tracked_attach)
    try:
        result = parallel._render_block_worker(
            ((3, {"a": 1}, 0), (4, {"a": 2}, 6), (5, {}, 12)),
            renderer.size, segment.name)
        assert bytes(segment.buf) == b"\x03" * 6 + b"\x04" * 6 + b"\x05" * 6
        assert renderer.seen == [(3, {"a": 1}), (4, {"a": 2}), (5, {})]
        assert attachments == [{"name": segment.name}]
        assert [entry.renderer_stats for entry in result] == [{"frames": 1}] * 3
    finally:
        segment.close()
        segment.unlink()


def test_consecutive_jobs_partial_flush_repeats_and_bounded_slots(monkeypatch):
    monkeypatch.setattr(parallel, "ProcessPoolExecutor", BlockExecutor)
    stream = FrameStream()
    with parallel.OrderedFrameRenderer(stream, BufferRenderer(), LEVEL, workers=2,
                                      max_pending_bytes=9 * FRAME_BYTES) as writer:
        assert writer.block_size == 4
        assert writer.max_pending == 8
        assert writer._segment.size == 9 * FRAME_BYTES
        executor = writer._executor
        for index in range(11):
            writer.submit(index, {}, 0 if index == 10 else 1)
            assert len(writer._pending) <= writer.max_pending
        writer.extend_last(2)
        writer.flush()
        writer.extend_last(1)
        assert executor.jobs == [(0,), (1, 2, 3, 4), (5, 6, 7, 8), (9, 10)]
        assert stream.frames == list(range(10)) + [10] * 3
        assert writer.timings["frames_rendered"] == 11
        assert writer.renderer_stats == {"frames": 11}
        assert writer.frames_written == 13
    assert executor.closed


@pytest.mark.parametrize("slots,workers,block_size", [(5, 4, 1), (9, 4, 2), (17, 4, 4)])
def test_blocks_shrink_to_leave_capacity_for_each_worker(monkeypatch, slots, workers, block_size):
    monkeypatch.setattr(parallel, "ProcessPoolExecutor", BlockExecutor)
    with parallel.OrderedFrameRenderer(FrameStream(), BufferRenderer(), LEVEL,
            workers=workers, max_pending_bytes=slots * FRAME_BYTES) as writer:
        assert writer.workers == workers
        assert writer.block_size == block_size
        assert writer.max_pending >= workers * block_size
        assert writer._segment.size <= slots * FRAME_BYTES


def test_drain_submits_a_partial_block_and_close_discards_unsubmitted_tail(monkeypatch):
    monkeypatch.setattr(parallel, "ProcessPoolExecutor", BlockExecutor)
    stream = FrameStream()
    writer = parallel.OrderedFrameRenderer(stream, BufferRenderer(), LEVEL, workers=2)
    executor = writer._executor
    name = writer._segment.name
    writer.submit(0, {})
    writer.submit(1, {})
    writer.drain_one()
    writer.drain_one()
    assert stream.frames == [0, 1]
    writer.submit(2, {})
    writer.close()
    assert executor.jobs == [(0,), (1,)]
    assert stream.frames == [0, 1]
    assert not writer._pending and not writer._staged
    with pytest.raises(FileNotFoundError):
        shared_memory.SharedMemory(name=name)


def test_blocks_completing_out_of_order_still_write_every_frame_in_order(monkeypatch):
    class DeferredExecutor(BlockExecutor):
        def __init__(self, **options):
            super().__init__(**options)
            self.completions = []

        def submit(self, function, *args):
            ready = super().submit(function, *args)
            pending = Future()
            self.completions.append((pending, ready.result()))
            return pending

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", DeferredExecutor)
    stream = FrameStream()
    with parallel.OrderedFrameRenderer(stream, BufferRenderer(), LEVEL, workers=2) as writer:
        for index in range(7):
            writer.submit(index, {}, 2 if index == 4 else 1)
        writer._submit_staged()
        for pending, result in reversed(writer._executor.completions):
            pending.set_result(result)
        writer.flush()
        assert stream.frames == [0, 1, 2, 3, 4, 4, 5, 6]
