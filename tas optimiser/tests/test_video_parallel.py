"""Ordered frame transport, bounded queues and spawned-renderer equivalence."""
from concurrent.futures import Future
from copy import deepcopy
import hashlib
from io import BytesIO
import pickle
import subprocess
import sys

import pytest

from nv14_video_parallel import OrderedFrameRenderer


LEVEL = "0" * 713 + "|5^100,100"


class DigestStream:
    def __init__(self):
        self.frames = []

    def write(self, pixels):
        self.frames.append(hashlib.sha256(pixels).hexdigest())
        return len(pixels)


def _scene(index):
    return {"objects": [], "visual": {
        "x": 100.25 + index * 3.1, "y": 100.5 + index * .7,
        "frame": index + 1, "visible": True,
        "facing": 1 if index % 2 else -1, "rotation_deg": index * 17.25}}


def test_parallel_module_import_keeps_rendering_optional():
    result = subprocess.run([sys.executable, "-c",
        "import sys; import nv14_video_parallel; "
        "assert 'PIL' not in sys.modules; assert 'nv14_render' not in sys.modules; "
        "assert 'nv14_native' not in sys.modules"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_spawned_frames_match_serial_with_ghosts_and_repeats():
    pytest.importorskip("PIL.Image")
    from nv14_render import SceneRenderer

    # Curved/sloped geometry and non-default colours ensure spawned workers use
    # the actual parent layers instead of rebuilding a default-colour terrain.
    level = "2:A" + "0" * 710 + "|5^100,100"
    renderer = SceneRenderer(level, background=(190, 200, 210), terrain=(100, 120, 130))
    terrain_before = renderer._tiles.tobytes()
    background_before = renderer._background.tobytes()
    scenes = [_scene(i) for i in range(4)]
    options = [{"secondary_players": [
        {**_scene((i + 1) % 4)["visual"], "color": (53, 104, 168)},
        {**_scene((i + 2) % 4)["visual"], "color": (151, 67, 106)}]}
        for i in range(4)]
    saved = deepcopy((scenes, options))
    streams = []
    for workers in (1, 2):
        stream = DigestStream()
        writer = OrderedFrameRenderer(stream, renderer, level, workers=workers)
        with writer:
            writer.submit(scenes[0], options[0], 2)
            writer.extend_last(3)
            for scene, option in zip(scenes[1:], options[1:]):
                writer.submit(scene, option, 1)
            writer.flush()
            writer.extend_last(2)
            assert writer.frames_written == 10
        streams.append(stream.frames)
    assert streams[0] == streams[1]
    assert len(set(streams[0])) == 4
    assert streams[0][:5] == [streams[0][0]] * 5
    assert streams[0][-3:] == [streams[0][-1]] * 3
    assert (scenes, options) == saved
    assert renderer._tiles.tobytes() == terrain_before
    assert renderer._background.tobytes() == background_before


def test_worker_initialisation_reuses_validated_layers_without_rasterising(monkeypatch):
    pytest.importorskip("PIL.Image")
    from nv14_render import SceneRenderer
    import nv14_video_parallel as parallel

    renderer = SceneRenderer(LEVEL)
    expected = renderer.render(_scene(0)).tobytes()
    layers = pickle.loads(pickle.dumps((renderer._background, renderer._tiles)))

    def unexpected_terrain_build(*args, **kwargs):
        raise AssertionError("spawned worker repeated terrain rasterisation")

    monkeypatch.setattr(SceneRenderer, "_terrain_layer", unexpected_terrain_build)
    monkeypatch.setattr(parallel, "_worker_renderer", None)
    parallel._initialise_worker(LEVEL, None, 1, "exact", layers)
    worker = parallel._worker_renderer
    assert worker._background is layers[0] and worker._tiles is layers[1]
    assert worker._background is not renderer._background
    assert worker._tiles is not renderer._tiles
    assert len(worker._player_transforms) == len(worker._player_masks) == 0
    assert worker.render(_scene(0)).tobytes() == expected
    with pytest.raises(ValueError, match="worker terrain layers"):
        SceneRenderer(LEVEL, _terrain_layers=(layers[1], layers[0]))
    with pytest.raises(ValueError, match="worker terrain layers"):
        SceneRenderer(LEVEL, scale=2, _terrain_layers=layers)


def test_worker_error_propagates_and_joins_processes():
    pytest.importorskip("PIL.Image")
    from nv14_render import SceneRenderer

    writer = OrderedFrameRenderer(BytesIO(), SceneRenderer(LEVEL), LEVEL, workers=2)
    writer.submit({}, {}, 1)  # An invalid snapshot fails inside the worker.
    writer.submit(_scene(1), {}, 1)
    processes = tuple(writer._executor._processes.values())
    with pytest.raises(RuntimeError, match="video render worker failed:.*no player visuals"):
        writer.flush()
    assert all(not process.is_alive() for process in processes)
    assert writer._executor is None
    assert not writer._pending
    writer.close()  # Root encoder cleanup can call close again safely.


def test_completed_results_are_written_in_submission_order(monkeypatch):
    import nv14_video_parallel as parallel

    class Executor:
        def __init__(self, **options):
            assert options["mp_context"].get_start_method() == "spawn"
            self.futures = []
            self.closed = False

        def submit(self, function, *args):
            future = Future()
            self.futures.append(future)
            return future

        def shutdown(self, *, wait, cancel_futures):
            assert wait and cancel_futures
            self.closed = True

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", Executor)
    stream = BytesIO()
    writer = OrderedFrameRenderer(stream, object(), LEVEL, workers=2)
    executor = writer._executor
    for index in range(3):
        writer.submit(_scene(index), {}, 1)
    writer.extend_last(2)
    for index in (2, 1, 0):
        executor.futures[index].set_result(bytes([index]))
    writer.flush()
    writer.repeat_last()
    assert stream.getvalue() == b"\x00\x01\x02\x02\x02\x02"
    writer.close()
    assert executor.closed


def test_queue_backpressure_and_worker_count_respect_transport_budget(monkeypatch):
    import nv14_video_parallel as parallel

    class Executor:
        def __init__(self, **options):
            self.workers = options["max_workers"]

        def submit(self, function, scene, *args):
            future = Future()
            future.set_result(bytes([scene]))
            return future

        def shutdown(self, **options):
            pass

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", Executor)
    frame_bytes = 792 * 600 * 3
    stream = BytesIO()
    writer = OrderedFrameRenderer(stream, object(), LEVEL, workers=64,
                                  max_pending_bytes=frame_bytes * 9)
    # v4.10 needs one shared slot per pending frame and one retained last slot;
    # no worker/IPC duplicate payload is included in the transport budget.
    assert writer.workers == writer.max_pending == 8
    for index in range(15):
        writer.submit(index, {}, 1)
        assert len(writer._pending) <= 8
    assert writer.frames_written == 7
    writer.flush()
    assert stream.getvalue() == bytes(range(15))
    writer.close()


def test_serial_frame_validation_and_repeat_lifecycle():
    class Renderer:
        def render(self, scene, **options):
            return scene

    class Image:
        size = (792, 600)
        mode = "RGB"

        def tobytes(self):
            return b"frame"

    stream = BytesIO()
    writer = OrderedFrameRenderer(stream, Renderer(), LEVEL)
    with pytest.raises(RuntimeError, match="before submitting"):
        writer.extend_last()
    image = Image()
    image.mode = "RGBA"
    with pytest.raises(RuntimeError, match="invalid RGB frame"):
        writer.submit(image, {})
    image.mode = "RGB"
    writer.submit(image, {}, 0)
    writer.extend_last(2)
    assert stream.getvalue() == b"frameframe"
    with pytest.raises(ValueError, match="repeat_count"):
        writer.extend_last(-1)
    writer.close()
    writer.close()
    assert not stream.closed
    with pytest.raises(RuntimeError, match="closed"):
        writer.submit(image, {})
