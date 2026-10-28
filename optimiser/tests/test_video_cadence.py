"""Compare actual FFmpeg output with v4.09's per-output-frame repetition."""
from __future__ import annotations

import io
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nv14_video_cadence import TimedFramePipe


def _pixels(index):
    return bytes(((index * 37) % 256, (index * 73) % 256, (index * 113) % 256)) * 4


def _legacy_sequence(fps, timeline_ticks, hold_frames, *, animated=True):
    """Independent literal reference for the old gameplay/tail loop."""
    sequence = []
    for tick in range(1, timeline_ticks + 1):
        target = (tick * fps + 39) // 40
        sequence.extend([tick] * (target - len(sequence)))
    if not sequence:
        sequence.append(0)
    advanced_ticks = 0
    latest = sequence[-1]
    for _ in range(hold_frames):
        tail_tick = len(sequence) * 40 // fps + 1 - timeline_ticks
        if animated and tail_tick > advanced_ticks:
            advanced_ticks = tail_tick
            latest = timeline_ticks + tail_tick
        sequence.append(latest)
    return sequence


def _mux(sequence, fps):
    stream = io.BytesIO()
    pipe = TimedFramePipe(stream, 2, 2, fps)
    previous = None
    for index in sequence:
        if previous == index:
            pipe.repeat_last(1)
        else:
            pipe.write_frame(_pixels(index), 1)
        previous = index
    pipe.finish()
    return stream.getvalue(), pipe


class TimedPipeTests(unittest.TestCase):
    def test_no_buffer_retention_and_no_duplicate_pixels(self):
        target = io.BytesIO()
        pipe = TimedFramePipe(target, 2, 2, 120)
        buffer = bytearray(_pixels(1))
        pipe.write_frame(memoryview(buffer), 3)
        first_size = len(target.getvalue())
        buffer[:] = _pixels(2)
        pipe.repeat_last(18)
        self.assertEqual(len(target.getvalue()), first_size)
        pipe.finish()
        self.assertEqual(pipe.frames_written, 21)
        self.assertEqual(pipe.images_written, 1)
        self.assertEqual(pipe.pixel_bytes_written, 12)
        self.assertFalse(target.closed)
        self.assertIn(_pixels(1), target.getvalue())
        self.assertNotIn(_pixels(2), target.getvalue())
        pipe.finish()  # idempotent

    def test_partial_write_stream(self):
        class ShortWriter(io.BytesIO):
            def write(self, value):
                return super().write(value[:7])

        output = ShortWriter()
        pipe = TimedFramePipe(output, 2, 2, 59)
        pipe.write_frame(_pixels(1), 4)
        pipe.finish()
        expected, _ = _mux([1] * 4, 59)
        self.assertEqual(output.getvalue(), expected)

    def test_validation_and_zero_repeats(self):
        for fps in (39, 241, True, 59.5):
            with self.subTest(fps=fps), self.assertRaises(ValueError):
                TimedFramePipe(io.BytesIO(), 2, 2, fps)
        pipe = TimedFramePipe(io.BytesIO(), 2, 2, 40)
        pipe.write_frame(b"", 0)
        pipe.repeat_last(0)
        with self.assertRaises(RuntimeError):
            pipe.repeat_last()
        for repeats in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                pipe.write_frame(_pixels(1), repeats)
        with self.assertRaises(ValueError):
            pipe.write_frame(b"incorrect")
        pipe.finish()
        with self.assertRaises(RuntimeError):
            pipe.write_frame(_pixels(1))


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is not installed")
class FFmpegCadenceTests(unittest.TestCase):
    def _assert_decode(self, sequence, fps):
        encoded, pipe = _mux(sequence, fps)
        result = subprocess.run(
            [shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error",
             *pipe.input_arguments(), *pipe.filter_arguments(fps),
             "-threads", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
            input=encoded, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        expected = b"".join(_pixels(index) for index in sequence)
        self.assertEqual(result.stdout, expected,
                         f"cadence mismatch at {fps} FPS: wanted {len(sequence)} frames, "
                         f"got {len(result.stdout) // 12}")
        return pipe

    def test_every_supported_integer_fps_and_partial_animated_hold(self):
        for fps in range(40, 241):
            with self.subTest(fps=fps):
                sequence = _legacy_sequence(fps, 13, 17, animated=True)
                pipe = self._assert_decode(sequence, fps)
                self.assertEqual(pipe.frames_written, len(sequence))

    def test_terminal_static_holds_and_short_streams(self):
        for fps in (40, 41, 59, 60, 79, 80, 119, 120, 239, 240):
            for ticks, hold in ((0, 0), (1, 0), (1, 1), (3, 23)):
                with self.subTest(fps=fps, ticks=ticks, hold=hold):
                    self._assert_decode(_legacy_sequence(fps, ticks, hold,
                                                         animated=False), fps)

    def test_arbitrary_duration_and_mutable_shared_buffer(self):
        self._assert_decode([1] * 2 + [2] * 1 + [3] * 7 + [4] * 3, 59)
        pipe = self._assert_decode([1] * 360, 120)
        self.assertEqual(pipe.pixel_bytes_written, 12)


if __name__ == "__main__":
    unittest.main()
