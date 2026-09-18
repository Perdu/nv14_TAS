"""Exact, low-copy delivery of repeated RGB frames to FFmpeg.

An internal streaming Matroska track carries uncompressed RGB images together
with the number of output frames for which each image remains visible. FFmpeg's
fps filter expands those durations. No temporary media files, image compression,
external Python package, or extra FFmpeg process is required.

Only the private encoder-to-FFmpeg pipe uses this format; the output remains an
ordinary H.264 MP4 with the requested preset and quality.
"""
from __future__ import annotations


# Matroska uses microsecond timestamps here. Quantisation is at most 0.5 us,
# compared with a minimum supported output-frame interval of 4166.7 us. Both
# starts and ends are computed from integral output-frame numbers, so errors
# cannot accumulate over a long replay.
_TIMESTAMP_UNITS = 1_000_000


def _size(value):
    for width in range(1, 9):
        if value < (1 << (7 * width)) - 1:
            return (value | (1 << (7 * width))).to_bytes(width, "big")
    raise ValueError("Matroska element exceeds the supported size")


def _element(identifier, payload):
    return bytes.fromhex(identifier) + _size(len(payload)) + payload


def _integer(identifier, value, *, width=None):
    width = width or max(1, (value.bit_length() + 7) // 8)
    return _element(identifier, value.to_bytes(width, "big"))


def _header(width, height, fps):
    ebml = _element("1a45dfa3", (
        _integer("4286", 1) + _integer("42f7", 1)
        + _integer("42f2", 4) + _integer("42f3", 8)
        + _element("4282", b"matroska")
        + _integer("4287", 4) + _integer("4285", 2)))
    info = _element("1549a966", (
        _integer("2ad7b1", 1000)
        + _element("4d80", b"nv14") + _element("5741", b"nv14")))
    entry = (
        _integer("d7", 1) + _integer("73c5", 1) + _integer("83", 1)
        + _integer("9c", 0)
        + _integer("23e383", (1_000_000_000 + fps // 2) // fps)
        + _element("86", b"V_UNCOMPRESSED")
        + _element("e0", _integer("b0", width) + _integer("ba", height)
                   + _element("2eb524", b"RGB\x18")))
    tracks = _element("1654ae6b", _element("ae", entry))
    # An unknown-size outer Segment is the standard non-seekable stream form.
    return ebml + bytes.fromhex("1853806701ffffffffffffff") + info + tracks


class TimedFramePipe:
    """Deliver one RGB payload per rendered image, including exact repeats.

    ``write_frame(pixels, repeat_count)`` consumes a contiguous bytes-like image
    immediately; the caller may therefore release/reuse a shared-memory slot as
    soon as it returns. ``repeat_last`` extends its duration without transferring
    its pixels again or retaining their buffer. ``finish`` completes the final
    duration and flushes, but never closes the caller-owned pipe.

    Each BlockGroup has a known length and a fixed-width BlockDuration *after*
    its image payload. Delaying that final metadata until the next image allows
    an arbitrary number of ``repeat_last`` calls with no retained RGB copy. At
    most one block's duration is pending. ``flush`` alone does not seal it.
    """

    def __init__(self, stream, width, height, fps):
        for name, value in (("width", width), ("height", height), ("fps", fps)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not 40 <= fps <= 240:
            raise ValueError("fps must be between 40 and 240")
        self.stream = stream
        self.width = width
        self.height = height
        self.fps = fps
        self.frame_bytes = width * height * 3
        self.frames_written = 0
        self.images_written = 0
        self.pixel_bytes_written = 0
        self._pending_start = None
        self._finished = False
        self._write_all(_header(width, height, fps))

    @staticmethod
    def input_arguments():
        return ["-f", "matroska", "-i", "pipe:0"]

    @staticmethod
    def filter_arguments(fps):
        # Timestamps already express output-frame indices, including the ceil
        # rounding used by the game's 40 Hz timeline. Round to the nearest index
        # only to undo the sub-microsecond timestamp representation error.
        return ["-vf", f"fps={fps}:round=near:eof_action=round"]

    @staticmethod
    def _validate_repeats(repeat_count):
        if (isinstance(repeat_count, bool) or not isinstance(repeat_count, int)
                or repeat_count < 0):
            raise ValueError("repeat_count must be a non-negative integer")

    def _check_open(self):
        if self._finished:
            raise RuntimeError("timed frame pipe is finished")

    def _timestamp(self, frame_number):
        return (frame_number * _TIMESTAMP_UNITS + self.fps // 2) // self.fps

    def _write_all(self, value):
        # Binary streams are allowed to perform a partial write. Do not retain
        # even a view of worker-owned shared memory beyond this call.
        view = memoryview(value)
        try:
            while view:
                written = self.stream.write(view)
                if written is None or written <= 0:
                    raise BrokenPipeError("FFmpeg input accepted no frame data")
                remainder = view[written:]
                view.release()
                view = remainder
        finally:
            view.release()

    def _finish_block(self):
        if self._pending_start is not None:
            duration = self._timestamp(self.frames_written) - self._pending_start
            self._write_all(_integer("9b", duration, width=8))
            self._pending_start = None

    def write_frame(self, pixels, repeat_count=1):
        self._check_open()
        self._validate_repeats(repeat_count)
        if not repeat_count:
            return
        view = memoryview(pixels)
        try:
            if not view.c_contiguous or view.nbytes != self.frame_bytes:
                raise ValueError("invalid RGB frame buffer")
            if view.format != "B" or view.ndim != 1:
                flat = view.cast("B")
                view.release()
                view = flat
            self._finish_block()
            start = self._timestamp(self.frames_written)
            timestamp = _integer("e7", start)
            block_size = 4 + self.frame_bytes
            block_prefix = b"\xa1" + _size(block_size) + b"\x81\x00\x00\x00"
            # BlockDuration is a one-byte ID, one-byte size and eight-byte value.
            group_size = len(block_prefix) + self.frame_bytes + 10
            group_prefix = b"\xa0" + _size(group_size)
            cluster_size = len(timestamp) + len(group_prefix) + group_size
            self._write_all(bytes.fromhex("1f43b675") + _size(cluster_size)
                            + timestamp + group_prefix + block_prefix)
            self._write_all(view)
            self._pending_start = start
            self.frames_written += repeat_count
            self.images_written += 1
            self.pixel_bytes_written += self.frame_bytes
        finally:
            view.release()

    def repeat_last(self, repeat_count=1):
        self._check_open()
        self._validate_repeats(repeat_count)
        if not repeat_count:
            return
        if self._pending_start is None:
            raise RuntimeError("cannot repeat a frame before submitting one")
        self.frames_written += repeat_count

    def flush(self):
        self._check_open()
        self.stream.flush()

    def finish(self):
        if self._finished:
            return
        self._finish_block()
        self.stream.flush()
        self._finished = True
