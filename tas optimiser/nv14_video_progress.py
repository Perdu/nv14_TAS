"""Optional parent-process stdout progress for one video export."""
from __future__ import annotations

import sys
from threading import Event, Lock, Thread
from time import perf_counter


class VideoProgress:
    """Report phases and keep printing while encoding waits on external work.

    Frame counters describe images handed to FFmpeg, not confirmed encoded
    packets. No percentage/ETA is guessed from inputs that can end early.
    Disabled API calls create no thread and perform no per-frame work.
    """

    INTERVAL_SECONDS = 2.0

    def __init__(self, enabled=False, *, stage="Loading replays"):
        if not isinstance(enabled, bool):
            raise TypeError("progress must be a boolean")
        self.enabled = enabled
        self._stage = stage
        self._detail = ""
        self._counter = None
        self._workers = None
        self._render_started = None
        self._thread = None

    def __enter__(self):
        if self.enabled:
            self._started = perf_counter()
            self._stream = sys.stdout
            self._stop = Event()
            self._lock = Lock()
            with self._lock:
                self._emit()
            if self.enabled:
                self._thread = Thread(target=self._heartbeat,
                                      name="nv14-video-progress", daemon=True)
                self._thread.start()
        return self

    def stage(self, message, detail=""):
        if self.enabled:
            with self._lock:
                self._stage, self._detail = message, detail
                self._emit()

    def detail(self, message):
        if self.enabled:
            with self._lock:
                self._detail = message

    def rendering(self, writer, *, previous_frames=0):
        if self.enabled:
            with self._lock:
                if self._render_started is None:
                    self._render_started = perf_counter()
                # Capture this writer/offset together, including after an
                # automatic worker switch. Only read its integer counter.
                self._counter = lambda: previous_frames + writer.frames_written
                self._workers = writer.workers
                self._stage, self._detail = "Rendering / encoding", ""
                self._emit()

    def _emit(self):
        now = perf_counter()
        parts = [f"[encode-video] {self._stage}"]
        if self._detail:
            parts.append(self._detail)
        if self._counter is not None:
            count = self._counter()
            parts.append(f"{count:,} frames sent")
            elapsed = now - self._render_started
            if elapsed >= 1.0:
                parts.append(f"{count / elapsed:.1f} frames/s avg")
            parts.append(f"{self._workers} render worker(s)")
        parts.append(f"elapsed {now - self._started:.1f}s")
        try:
            print("; ".join(parts), file=self._stream, flush=True)
        except (OSError, ValueError):
            # A detached/closed progress sink must not damage the video.
            self.enabled = False
            self._stop.set()

    def _heartbeat(self):
        while not self._stop.wait(self.INTERVAL_SECONDS):
            with self._lock:
                if self.enabled:
                    self._emit()

    def __exit__(self, exc_type, exc, traceback):
        if self._thread is not None:
            self._stop.set()
            self._thread.join()
        if self.enabled:
            self.stage("Complete" if exc_type is None else
                       "Cancelled" if isinstance(exc, KeyboardInterrupt) else "Failed")
        return False
