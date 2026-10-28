"""Optional, bounded-memory native replay rendering and MP4 encoding.

Only standard-library modules are imported here. Pillow, the renderer, assets
and the native backend are loaded when export is explicitly requested.
"""
from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import subprocess
import tempfile
from time import perf_counter
from statistics import median
from collections.abc import Sequence
from dataclasses import dataclass, replace
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

from nv14_video_session import (VideoEncodeSession, choose_workers,
                                validate_performance_options)

if TYPE_CHECKING:
    from _nv14_native import NativeLevel
    from nv14_engine import InputFrame
    from nv14_replay import ComplexReplay


DEFAULT_SECONDARY_COLORS = (
    "#3568a8", "#689ec9", "#c38d62", "#86aa76", "#ab88bf", "#cc7e92", "#68aeaa",
)


@dataclass(frozen=True, slots=True)
class VideoReplayResult:
    """One replay's own clock and outcome; index 0 is always the primary."""

    index: int
    source_frames: int
    simulated_ticks: int
    start_offset_ticks: int
    color: str | None
    stop_reason: str
    final_neutral_written: bool
    dead: bool
    complete: bool
    label: str | None = None

    @property
    def end_tick(self) -> int:
        return self.start_offset_ticks + self.simulated_ticks


@dataclass(frozen=True, slots=True)
class VideoEncodeResult:
    output_path: Path
    source_frames: int
    simulated_ticks: int
    video_frames: int
    fps: int
    width: int
    height: int
    stop_reason: str
    final_neutral_written: bool
    dead: bool
    complete: bool
    replay_alignment: str = "start"
    timeline_ticks: int = 0
    replays: tuple[VideoReplayResult, ...] = ()
    render_workers: int = 1
    render_quality: str = "exact"
    timings: dict | None = None

    @property
    def duration_seconds(self) -> float:
        return self.video_frames / self.fps


def _secondary_sequence(value, name):
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, os.PathLike)):
        raise TypeError(f"{name} must be a sequence; wrap a single item in a list")
    return tuple(value)


def _comparison_options(replay_alignment, secondary_colors, count):
    if replay_alignment not in ("start", "exit"):
        raise ValueError("replay_alignment must be 'start' or 'exit'")
    if secondary_colors is None:
        return tuple(DEFAULT_SECONDARY_COLORS[i % len(DEFAULT_SECONDARY_COLORS)]
                     for i in range(count))
    colors = _secondary_sequence(secondary_colors, "secondary_colors")
    if len(colors) != count:
        raise ValueError("secondary_colors must contain one color per secondary replay")
    if any(not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)
           for color in colors):
        raise ValueError("secondary_colors must use '#RRGGBB' hex strings")
    return tuple(color.lower() for color in colors)


def _label_options(primary_label, secondary_labels, label_size, count, label_position="follow"):
    from nv14_render import validate_player_label, validate_label_size, validate_label_position

    validate_label_size(label_size)
    validate_label_position(label_position)
    validate_player_label(primary_label)
    labels = ((None,) * count if secondary_labels is None else
              _secondary_sequence(secondary_labels, "secondary_labels"))
    if len(labels) != count:
        raise ValueError("secondary_labels must contain one label per secondary replay; "
                         "use an empty string or None to hide an individual label")
    for label in labels:
        validate_player_label(label)
    return primary_label or None, tuple(label or None for label in labels)


def _completion_ticks(level, frames, final_neutral, index):
    """Measure the real exit tick in bounded native batches, without visuals."""
    from nv14_engine import InputFrame

    state = level.initial_state()
    total = len(frames) + int(bool(final_neutral))
    if hasattr(state, "step_many"):
        for start in range(0, total, 4096):
            end = min(total, start + 4096)
            batch = list(frames[start:min(end, len(frames))])
            if end > len(frames):
                batch.append(InputFrame())
            result = state.step_many(batch, stop_on_dead=True, stop_on_complete=True)
            event = result["last_step"]
            if event and event["level_complete"]:
                return start + result["consumed"]
            if event and event["dead"]:
                break
    else:
        for tick in range(total):
            frame = frames[tick] if tick < len(frames) else InputFrame()
            event = state.step(frame)
            # Completion takes priority over same-tick death.
            if event["level_complete"]:
                return tick + 1
            if event["dead"]:
                break
    name = "primary replay" if index == 0 else f"secondary replay {index}"
    raise ValueError(f"exit alignment requires every replay to complete; {name} "
                     "does not reach the exit with the selected inputs and simulation options")


class _VideoReplay:
    """A streamed private simulation. Only the primary contributes a scene."""

    def __init__(self, state, frames, final_neutral, offset, color):
        self.state, self.frames = state, frames
        self.final_neutral, self.offset, self.color = final_neutral, offset, color
        self.ticks = 0
        self.dead = self.complete = self.sentinel_written = False
        self.visual = state.visual_snapshot()

    @property
    def done(self):
        return (self.dead or self.complete
                or self.ticks >= len(self.frames) + int(bool(self.final_neutral)))

    def step(self):
        from nv14_engine import InputFrame

        self.sentinel_written = self.ticks == len(self.frames)
        frame = InputFrame() if self.sentinel_written else self.frames[self.ticks]
        event = self.state.step(frame)
        self.ticks += 1
        self.dead, self.complete = bool(event["dead"]), bool(event["level_complete"])
        self.visual = self.state.visual_snapshot()
        return frame

    def result(self, index):
        return VideoReplayResult(index, len(self.frames), self.ticks, self.offset,
            self.color, "complete" if self.complete else "dead" if self.dead else "input_end",
            self.sentinel_written, self.dead, self.complete)


class _ReplayComparison:
    def __init__(self, level, primary_state, sources, offsets, colors, secondary_tracks=None,
                 secondary_labels=(), capture_gold=False):
        self.colors = [tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) for color in colors]
        self.labels = secondary_labels or (None,) * len(colors)
        self.timeline_ticks = 0
        self.capture_gold = capture_gold
        self.gold_pickups = ()
        self.tracks = []
        for index, ((frames, final_neutral), offset) in enumerate(zip(sources, offsets)):
            if index and secondary_tracks is not None:
                track = secondary_tracks[index - 1]
                track.offset = offset
                self.tracks.append(track)
                continue
            state = primary_state if index == 0 else level.initial_state(
                track_visuals=True, visual_timeline_frames=3, celebration_variant=1)
            self.tracks.append(_VideoReplay(state, frames, final_neutral, offset,
                                           None if index == 0 else colors[index - 1]))

    @property
    def done(self):
        return all(track.done for track in self.tracks)

    def step(self):
        self.timeline_ticks += 1
        primary_input = None
        if self.capture_gold:
            self.gold_pickups = []
        for index, track in enumerate(self.tracks):
            if self.timeline_ticks > track.offset and not track.done:
                frame = track.step()
                if index == 0:
                    primary_input = frame
                elif self.capture_gold and track.gold_pickups:
                    self.gold_pickups.append((index - 1, track.gold_pickups))
        return primary_input

    def render_options(self, label_position="follow"):
        players = []
        for track, color, label in zip(self.tracks[1:], self.colors, self.labels):
            started = self.timeline_ticks > track.offset or track.offset == 0
            if started or label_position == "top-left":
                player = {**track.visual, "color": color}
                if not started:
                    player["visible"] = False
                if label:
                    player["label"] = label
                players.append(player)
        return {"secondary_players": players,
                "show_primary_player": self.timeline_ticks > self.tracks[0].offset
                                       or self.tracks[0].offset == 0}


def _validate_options(output_path, fps, scale, crf, preset, terminal_hold_seconds):
    path = Path(output_path)
    if path.suffix.lower() != ".mp4":
        raise ValueError("video output must have an .mp4 extension")
    for name, value, low, high in (("fps", fps, 40, 240), ("scale", scale, 1, 4), ("crf", crf, 0, 51)):
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{name} must be an integer from {low} to {high}")
    if preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"}:
        raise ValueError("unsupported H.264 preset")
    if isinstance(terminal_hold_seconds, bool) or not isinstance(terminal_hold_seconds, (int, float)) or not math.isfinite(terminal_hold_seconds) or not 0 <= terminal_hold_seconds <= 3600:
        raise ValueError("terminal_hold_seconds must be finite and between 0 and 3600")
    return path


def _find_ffmpeg(ffmpeg_path) -> str:
    requested = os.fspath(ffmpeg_path) if ffmpeg_path is not None else "ffmpeg"
    executable = shutil.which(requested)
    if executable is None:
        raise RuntimeError("FFmpeg was not found; install FFmpeg with libx264 and add it to PATH, or supply ffmpeg_path")
    try:
        check = subprocess.run([executable, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"cannot run FFmpeg: {exc}") from exc
    if check.returncode or not re.search(r"\blibx264\b", check.stdout):
        raise RuntimeError("the selected FFmpeg build does not provide the libx264 encoder")
    return executable


def _replay_frames(replay_data):
    from nv14_engine import InputFrame
    from nv14_replay import ComplexReplay, decode_complex_replay

    if isinstance(replay_data, str):
        text = replay_data.strip().removeprefix("\ufeff").strip()
        if not re.match(r"^\d+:", text):
            raise ValueError("replay_data must use '<ticks>:<packed words>' format")
        return decode_complex_replay(text).frames
    frames = replay_data.frames if isinstance(replay_data, ComplexReplay) else replay_data
    if not isinstance(frames, Sequence) or isinstance(frames, (str, bytes, bytearray, memoryview)):
        raise TypeError("replay_data must be a packed replay string, ComplexReplay, or sequence of InputFrame records")
    if any(not isinstance(frame, InputFrame) for frame in frames):
        raise TypeError("decoded replay_data must contain only InputFrame records")
    return frames


def _level_credit(name, author):
    """Keep userlevel metadata on one line, in the original GUI's format."""
    name, author = " ".join(name.split()), " ".join(author.split())
    if not author:
        return name or None
    return f"{name}  ( by {author} )" if name else f"( by {author} )"


def encode_replay_data_video(
    level_data: str | NativeLevel,
    replay_data: str | ComplexReplay | Sequence[InputFrame],
    output_path: str | os.PathLike[str], *,
    secondary_replays: Sequence[str | ComplexReplay | Sequence[InputFrame]] | None = None,
    replay_alignment: str = "start",
    secondary_colors: Sequence[str] | None = None,
    secondary_gold: str = "off",
    primary_label: str | None = None,
    secondary_labels: Sequence[str | None] | None = None,
    label_size: int = 8,
    label_position: str = "follow",
    assets_path: str | os.PathLike[str] | None = None,
    simulate_enemies: bool = True,
    final_neutral: bool = True,
    fps: int = 40,
    scale: int = 2,
    particles: bool = True,
    particle_seed: int = 0,
    object_animations: bool = True,
    terminal_hold_seconds: float = 1.0,
    crf: int = 18,
    preset: str = "medium",
    ffmpeg_path: str | os.PathLike[str] | None = None,
    render_workers: int = 8,
    render_quality: str = "fast",
    replay_cache_dir: str | os.PathLike[str] | None = None,
    render_memory_mib: int = 128,
    profile: bool = False,
    progress: bool = False,
    session: VideoEncodeSession | None = None,
) -> VideoEncodeResult:
    """Render level/replay data directly to a silent H.264 MP4.

    Accepts a raw level string, a $name#author#... userlevel record, or a reusable
    NativeLevel, and packed demo, ComplexReplay or InputFrame sequence. Each call
    starts a fresh tracked state. Stored jump triggers are preserved. One neutral
    sentinel is appended by default, unless completion/death has already occurred.
    Userlevel records also supply the bottom-centred "name  ( by author )"
    credit. Raw strings and NativeLevel instances have no name metadata and
    leave the footer blank. An embedded replay is ignored in favour of replay_data.

    Gameplay and animation use the existing nominal 40 Hz schedule (three SWF
    timeline frames per tick). fps=40..240 repeats whole rendered frames; it never
    changes gameplay speed or interpolates positions. The last gameplay interval
    is rounded up to a whole video frame. No extra physics runs during the optional
    terminal hold (existing particles and object clips continue to age).
    An empty input with final_neutral=False produces one
    image of the initial state. Rendering dependencies are entirely opt-in.

    particles=False retains the particle-free rendering path. particle_seed
    controls a private cosmetic RNG and cannot affect gameplay or search RNG.
    object_animations=False selects representative static object art; enabled
    exports track the source MovieClip sequences and gradual drone eye rotation.

    secondary_replays supplies additional player-only overlays on the same level.
    Each is privately simulated to recover its own poses; only replay_data drives
    the visible objects, enemies and particles. replay_alignment='start' starts
    everyone together and runs to the last replay's end. 'exit' delays shorter
    replays so their actual first completion ticks coincide; all must complete.
    The primary world freezes before its start and after its last gameplay tick.
    Secondary colors default to darker blue, then a repeating distinct palette;
    secondary_colors may provide one '#RRGGBB' string per secondary replay.
    secondary_gold='static' or 'animated' leaves ghost-coloured gold where
    the primary collected first. Each piece shows the first pending ghost in
    input order, then switches colour when that ghost collects it. Animated mode
    reuses gold collection clips, independently of particles/object_animations.
    The default 'off' retains the original path; no secondaries means no effect.
    primary_label and secondary_labels optionally attach original GUI-font text
    to each player. Supply one secondary label per replay; None/empty hides it.
    label_size is the font size in game pixels (6..32, default 8), before scale.
    label_position='follow' keeps text above each visible player (default);
    'top-left' shows a fixed colour-matched legend throughout the video.

    Defaults are scale=2 (1584x1200), render_workers=8 and render_quality='fast'.
    Explicit render_workers=0 measures an initial serial prefix and selects up to four
    render processes when useful; 1 stays serial. render_quality='exact' preserves exact geometry;
    'fast' snaps only ninja artwork to an eighth output pixel and whole degrees.
    replay_cache_dir optionally stores versioned compact secondary pose tracks.
    render_memory_mib bounds RGB transport (not artwork); profile=True returns
    timing/cache statistics in result.timings. progress=True prints phase/frame
    updates to stdout about every two seconds, including during waits.
    A VideoEncodeSession can reuse
    renderers, native levels and spawned workers across independent exports.
    Multiprocess API callers must use a __main__ guard (as on Windows).

    Returns counts and terminal flags. The destination is atomically replaced
    only after successful encoding; exceptions/interrupts remove temporary output.
    """
    from nv14_video_progress import VideoProgress

    with VideoProgress(progress, stage="Loading replay data") as reporter:
        path = _validate_options(output_path, fps, scale, crf, preset, terminal_hold_seconds)
        frames = _replay_frames(replay_data)
        secondary = _secondary_sequence(secondary_replays, "secondary_replays")
        colors = _comparison_options(replay_alignment, secondary_colors, len(secondary))
        primary_label, labels = _label_options(primary_label, secondary_labels, label_size, len(secondary), label_position)
        secondary_frames = tuple((_replay_frames(replay), bool(final_neutral)) for replay in secondary)
        return _encode_frames(level_data, frames, path, assets_path=assets_path,
            simulate_enemies=simulate_enemies, final_neutral=final_neutral, fps=fps,
            scale=scale, terminal_hold_seconds=terminal_hold_seconds, crf=crf,
            preset=preset, ffmpeg_path=ffmpeg_path, particles=particles,
            particle_seed=particle_seed, object_animations=object_animations,
            secondary_frames=secondary_frames, replay_alignment=replay_alignment,
            secondary_colors=colors, secondary_gold=secondary_gold, primary_label=primary_label, secondary_labels=labels,
            label_size=label_size, label_position=label_position, render_workers=render_workers,
            render_quality=render_quality, replay_cache_dir=replay_cache_dir,
            render_memory_mib=render_memory_mib, profile=profile, session=session, progress=reporter)


def encode_replay_video(
    input_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str] | None = None, *,
    secondary_replays: Sequence[str | os.PathLike[str]] | None = None,
    replay_alignment: str = "start",
    secondary_colors: Sequence[str] | None = None,
    secondary_gold: str = "off",
    primary_label: str | None = None,
    secondary_labels: Sequence[str | None] | None = None,
    label_size: int = 8,
    label_position: str = "follow",
    levels_file: str | os.PathLike[str] | None = None,
    level_id: str | None = None,
    ltm_postroll: int | None = None,
    assets_path: str | os.PathLike[str] | None = None,
    simulate_enemies: bool = True,
    final_neutral: bool = True,
    fps: int = 40,
    scale: int = 2,
    particles: bool = True,
    particle_seed: int = 0,
    object_animations: bool = True,
    terminal_hold_seconds: float = 1.0,
    crf: int = 18,
    preset: str = "medium",
    ffmpeg_path: str | os.PathLike[str] | None = None,
    render_workers: int = 8,
    render_quality: str = "fast",
    replay_cache_dir: str | os.PathLike[str] | None = None,
    render_memory_mib: int = 128,
    profile: bool = False,
    progress: bool = False,
    session: VideoEncodeSession | None = None,
) -> VideoEncodeResult:
    """Encode a combined/packed demo or LTM, reusing the player-dump loader.

    LTM input needs a level database, preserves its selected recorded tail, and
    never receives a synthetic final-neutral tick. Menus/preroll are not rendered.
    secondary_replays lists same-level files in overlay order. Packed-only
    secondaries and LTMs inherit the primary level; combined demos must contain
    the identical level. ltm_postroll applies to each LTM in a comparison, and
    final_neutral applies only to demo text. Mixed formats are supported.
    Label and progress options have the same meaning as in encode_replay_data_video.
    """
    from nv14_video_progress import VideoProgress

    with VideoProgress(progress, stage="Loading replay files") as reporter:
        from nv14_cli import _paths_alias
        from nv14_dump import load_player_dump_source

        source_path = Path(input_path)
        path = _validate_options(output_path if output_path is not None else source_path.with_suffix(".mp4"), fps, scale, crf, preset, terminal_hold_seconds)
        secondary_paths = tuple(Path(item) for item in _secondary_sequence(secondary_replays, "secondary_replays"))
        colors = _comparison_options(replay_alignment, secondary_colors, len(secondary_paths))
        primary_label, labels = _label_options(primary_label, secondary_labels, label_size, len(secondary_paths), label_position)
        if any(_paths_alias(item, path) for item in (source_path, *secondary_paths)):
            raise ValueError("input and video output must be different files")
        source = load_player_dump_source(source_path,
            levels_file=Path(levels_file) if levels_file is not None else None,
            level_id=level_id, ltm_postroll=(None if secondary_paths and source_path.suffix.lower() != ".ltm"
                                          else ltm_postroll))
        if source.levels_file is not None and _paths_alias(source.levels_file, path):
            raise ValueError("levels file and video output must be different files")
        if secondary_paths and ltm_postroll is not None and not any(
                item.suffix.lower() == ".ltm" for item in (source_path, *secondary_paths)):
            raise ValueError("--ltm-postroll is only valid with an .ltm input")
        secondary_frames = []
        for replay_index, item in enumerate(secondary_paths, 1):
            reporter.detail(f"secondary replay {replay_index}/{len(secondary_paths)}")
            if item.suffix.lower() == ".ltm":
                from nv14_ltm import LtmMovie
                movie = LtmMovie.load(item, postroll_frames=0 if ltm_postroll is None else ltm_postroll)
                secondary_frames.append((movie.replay_frames, False))
            else:
                text = item.read_text(encoding="utf-8-sig").strip()
                if re.match(r"^\d+:", text):
                    replay_frames = _replay_frames(text)
                else:
                    other = load_player_dump_source(item)
                    if other.level_string != source.level_string:
                        raise ValueError(f"secondary replay {item} contains a different level from the primary")
                    replay_frames = other.frames
                secondary_frames.append((replay_frames, bool(final_neutral)))
        return _encode_frames(source.level_string, source.frames, path,
            level_credit=_level_credit(source.level_name, source.level_author),
            assets_path=assets_path, simulate_enemies=simulate_enemies,
            final_neutral=bool(final_neutral and source.input_kind == "demo"), fps=fps,
            scale=scale, terminal_hold_seconds=terminal_hold_seconds, crf=crf,
            preset=preset, ffmpeg_path=ffmpeg_path, particles=particles,
            particle_seed=particle_seed, object_animations=object_animations,
            secondary_frames=secondary_frames, replay_alignment=replay_alignment,
            secondary_colors=colors, secondary_gold=secondary_gold, primary_label=primary_label, secondary_labels=labels,
            label_size=label_size, label_position=label_position, render_workers=render_workers,
            render_quality=render_quality, replay_cache_dir=replay_cache_dir,
            render_memory_mib=render_memory_mib, profile=profile, session=session, progress=reporter)


def _worker_count(requested, sources):
    """Avoid process startup for short exports; leave CPU capacity for x264."""
    if requested:
        return requested
    ticks = max(len(frames) + bool(neutral) for frames, neutral in sources)
    if ticks < 160 or ticks * len(sources) < 8000:
        return 1
    try:
        cpus = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpus = os.cpu_count() or 1
    return min(4, max(1, cpus - 1))


def _make_frame_stream(stream, width, height, fps):
    if fps > 40:
        from nv14_video_cadence import TimedFramePipe
        return TimedFramePipe(stream, width, height, fps)
    return stream


def _encode_frames(level_data, frames, output_path, *, assets_path, simulate_enemies,
                   final_neutral, fps, scale, terminal_hold_seconds, crf, preset, ffmpeg_path, progress,
                   particles=True, particle_seed=0, object_animations=True,
                   secondary_frames=(), replay_alignment="start", secondary_colors=(), secondary_gold="off",
                   primary_label=None, secondary_labels=(), label_size=8, label_position="follow",
                   render_workers=8, render_quality="fast", replay_cache_dir=None,
                   render_memory_mib=128, profile=False, session=None, level_credit=None):
    progress.stage("Preparing native replay simulation")
    from nv14_native import require_native

    if secondary_gold not in ("off", "static", "animated"):
        raise ValueError("secondary_gold must be 'off', 'static', or 'animated'")
    if not isinstance(particles, bool):
        raise ValueError("particles must be a boolean")
    if not isinstance(object_animations, bool):
        raise ValueError("object_animations must be a boolean")
    if isinstance(particle_seed, bool) or not isinstance(particle_seed, int):
        raise ValueError("particle_seed must be an integer")
    validate_performance_options(render_workers, render_memory_mib, profile)
    if session is not None and not isinstance(session, VideoEncodeSession):
        raise TypeError("session must be a VideoEncodeSession")
    if render_quality not in ("exact", "fast"):
        raise ValueError("render_quality must be 'exact' or 'fast'")
    if replay_cache_dir is not None:
        replay_cache_dir = Path(replay_cache_dir)
    native = require_native()
    if not hasattr(native.NativeState, "scene_snapshot"):
        raise RuntimeError("video export requires the v4.04 native extension; run python build_native.py")
    if object_animations and not native.backend_info().get("object_visual_queries", False):
        raise RuntimeError("object animation export requires the v4.06 native extension; run python build_native.py")
    started = perf_counter()
    with ExitStack() as resources:
        if session is not None:
            resources.enter_context(session._using())
        if isinstance(level_data, str):
            if level_data.lstrip("\ufeff \t\r\n").startswith("$"):
                from nv14_replay import parse_combined_level_replay
                # Append an empty demo so level-only records use the same
                # parser as combined files. Only geometry goes to the engine.
                record = parse_combined_level_replay(
                    level_data.lstrip("\ufeff \t\r\n").rstrip().rstrip("#") + "#0:#")
                level_credit = _level_credit(record.name, record.author)
                level_data = record.level_string
            level = (session._native_level(native, level_data, simulate_enemies)
                     if session is not None else
                     native.parse_level_string(level_data, simulate_enemies=simulate_enemies))
        elif isinstance(level_data, native.NativeLevel):
            level = level_data
            if level.simulate_enemies != bool(simulate_enemies):
                raise ValueError("simulate_enemies must match the supplied NativeLevel")
        else:
            raise TypeError("level_data must be a raw level string or a NativeLevel")
        if secondary_gold != "off" and secondary_frames:
            if not level.gold_count:
                secondary_gold = "off"
            elif not hasattr(native.NativeState, "capture_gold_visual_frames"):
                raise RuntimeError("secondary gold requires the v4.13 native extension; run python build_native.py")
        sources = ((frames, final_neutral), *secondary_frames)
        offsets = [0] * len(sources)
        tracks = None
        # Retain compatibility with v4.06+ extensions; rebuilding enables compact
        # C capture. Only rendering callers construct/capture these tracks.
        if secondary_frames and hasattr(native.NativeState, "capture_visual_frames"):
            from nv14_video_tracks import VisualTrack
            tracks = []
            progress.stage("Preparing secondary replay tracks/cache")
            for replay_index, ((replay, neutral), color) in enumerate(zip(secondary_frames, secondary_colors), 1):
                progress.detail(f"secondary replay {replay_index}/{len(secondary_frames)}")
                track = VisualTrack(level, replay, neutral, color=color,
                                    cache_dir=replay_cache_dir,
                                    capture_gold=secondary_gold != "off")
                resources.callback(track.close)
                tracks.append(track)
        elif replay_cache_dir is not None and secondary_frames:
            raise RuntimeError("replay caching requires the v4.09 native extension; run python build_native.py")
        if replay_alignment == "exit":
            progress.stage("Measuring exit alignment", "primary replay")
            completions = [_completion_ticks(level, frames, final_neutral, 0)]
            if tracks is None:
                for i, (replay, neutral) in enumerate(secondary_frames, 1):
                    progress.detail(f"secondary replay {i}/{len(secondary_frames)}")
                    completions.append(_completion_ticks(level, replay, neutral, i))
            else:
                for i, track in enumerate(tracks, 1):
                    progress.detail(f"secondary replay {i}/{len(tracks)}")
                    track.precompute()
                    if track.completion_tick is None:
                        raise ValueError(f"exit alignment requires every replay to complete; secondary replay {i} "
                            "does not reach the exit with the selected inputs and simulation options")
                    completions.append(track.completion_tick)
            finish = max(completions)
            offsets = [finish - ticks for ticks in completions]
        return _encode_timeline(level, frames, output_path, sources=sources,
            level_credit=level_credit,
            offsets=offsets, tracks=tracks, secondary_colors=secondary_colors, secondary_gold=secondary_gold,
            primary_label=primary_label, secondary_labels=secondary_labels, label_size=label_size,
            label_position=label_position,
            replay_alignment=replay_alignment, assets_path=assets_path, fps=fps,
            scale=scale, particles=particles, particle_seed=particle_seed,
            object_animations=object_animations, terminal_hold_seconds=terminal_hold_seconds,
            crf=crf, preset=preset, ffmpeg_path=ffmpeg_path,
            render_workers=render_workers, render_quality=render_quality,
            render_memory_mib=render_memory_mib, profile=profile, session=session,
            preparation_seconds=perf_counter()-started, progress=progress)


def _encode_timeline(level, frames, output_path, *, sources, offsets, tracks,
                     secondary_colors, replay_alignment, assets_path, fps, scale,
                     particles, particle_seed, object_animations, terminal_hold_seconds,
                     crf, preset, ffmpeg_path, render_workers, render_quality, progress,
                     primary_label=None, secondary_labels=(), label_size=8, label_position="follow",
                     secondary_gold="off",
                     render_memory_mib=128, profile=False, session=None,
                     preparation_seconds=0., level_credit=None):
    from nv14_engine import InputFrame
    from nv14_ltm import _replace_with_windows_retries
    from nv14_render import SceneRenderer
    from nv14_video_parallel import OrderedFrameRenderer

    timeline_started = perf_counter()
    final_neutral = sources[0][1]
    progress.stage("Checking FFmpeg")
    executable = _find_ffmpeg(ffmpeg_path)
    progress.stage("Preparing renderer and graphics assets")
    renderer_options = {"assets_path": assets_path, "scale": scale}
    if render_quality != "exact":
        renderer_options["render_quality"] = render_quality
    started = perf_counter()
    if session is None:
        renderer = SceneRenderer(level.level_string, **renderer_options)
        renderer_reused = False
    else:
        renderer, renderer_reused = session._renderer(level.level_string, renderer_options)
    renderer_setup_seconds = perf_counter() - started
    state = level.initial_state(track_visuals=True, visual_timeline_frames=3,
                                celebration_variant=1)
    comparison = (_ReplayComparison(level, state, sources, offsets, secondary_colors,
                                   secondary_tracks=tracks, secondary_labels=secondary_labels,
                                   capture_gold=secondary_gold != "off")
                  if len(sources) > 1 else None)

    def snapshot_scene():
        return (state.scene_snapshot(include_object_visuals=True) if object_animations
                else state.scene_snapshot())

    effects = objects = gold = None
    initial_scene = snapshot_scene() if particles or object_animations or comparison is not None else None
    if comparison is not None and secondary_gold != "off":
        from nv14_video_gold import GhostGoldSystem
        gold = GhostGoldSystem(initial_scene, comparison.colors, renderer.manifest,
                               animated=secondary_gold == "animated")
    if particles:
        from nv14_particles import ParticleSystem
        effects = ParticleSystem(renderer.manifest, seed=particle_seed, _borrow_scenes=True)
        effects.reset(initial_scene)
    if object_animations:
        from nv14_object_visuals import ObjectVisualSystem
        objects = ObjectVisualSystem(renderer.manifest, _borrow_scenes=True)
        objects.reset(initial_scene, _snapshot=False)

    def render_options():
        options = comparison.render_options(label_position) if comparison is not None else {}
        if level_credit:
            options["level_credit"] = level_credit
        if label_position != "follow" and (primary_label or any(secondary_labels)):
            options["label_position"] = label_position
        if primary_label:
            options["primary_label"] = primary_label
        if (primary_label or any(secondary_labels)) and label_size != 8:
            options["label_size"] = label_size
        if gold is not None:
            options["secondary_gold"] = gold.snapshot()
        if effects is not None:
            options["particles"] = effects.snapshot()
        if objects is not None:
            options["object_visuals"] = objects.snapshot()
        return options

    def playback_inputs():
        if comparison is not None:
            while not comparison.done:
                yield comparison.step()
        else:
            for index in range(len(frames) + int(bool(final_neutral))):
                yield frames[index] if index < len(frames) else InputFrame()

    width, height = 792 * scale, 600 * scale
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output_path.stem}.", suffix=".mp4", dir=output_path.parent)
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    process = writer = None
    frame_stream = None
    ticks = written = timeline_ticks = 0
    previous_writer_frames = 0
    dead = complete = sentinel_written = False
    last_scene = initial_scene
    automatic_workers = render_workers == 0
    requested_workers = render_workers
    estimated_ticks = max(offset + len(source) + int(neutral)
                          for offset, (source, neutral) in zip(offsets, sources))
    object_count = len((initial_scene or {}).get("objects", ()))
    history_key = (level.level_string, scale, render_quality, len(sources),
                   fps, particles, object_animations, secondary_gold)
    previous_profile = session._history.get(history_key) if session is not None else None
    if automatic_workers:
        if previous_profile is not None:
            count = max(1, previous_profile.get("frames_rendered", 1))
            render_workers = choose_workers(remaining_ticks=estimated_ticks, scale=scale,
                players=len(sources), object_count=object_count, fps=fps,
                render_seconds=previous_profile.get("render_seconds", 0.) / count,
                write_seconds=previous_profile.get("write_seconds", 0.) / count)
        else:
            render_workers = 1
    warmup = automatic_workers and previous_profile is None
    render_samples, write_samples = [], []
    prior_timings, prior_renderer_stats = {}, {}
    used_workers = render_workers
    worker_decision = "explicit" if not automatic_workers else "warmup" if warmup else "session_history"

    def accumulate(target, values):
        for key, value in values.items():
            target[key] = target.get(key, 0) + value

    def make_writer(count):
        pool = session._workers(count) if session is not None else None
        return OrderedFrameRenderer(frame_stream, renderer, level.level_string,
            assets_path=assets_path, scale=scale, render_quality=render_quality,
            workers=count, max_pending_bytes=render_memory_mib * 1024**2,
            worker_session=pool)

    try:
        with tempfile.TemporaryFile(mode="w+b") as errors:
            # Preset, codec and quality defaults are unchanged from v4.08.1.
            if fps > 40:
                from nv14_video_cadence import TimedFramePipe
                input_arguments = TimedFramePipe.input_arguments()
                filter_arguments = TimedFramePipe.filter_arguments(fps)
            else:
                input_arguments = ["-f", "rawvideo", "-pixel_format", "rgb24",
                    "-video_size", f"{width}x{height}", "-framerate", str(fps), "-i", "pipe:0"]
                filter_arguments = []
            command = [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                *input_arguments, "-an", *filter_arguments, "-c:v", "libx264",
                "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-f", "mp4", str(temporary_path)]
            progress.stage("Starting FFmpeg and render workers")
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
            frame_stream = _make_frame_stream(process.stdin, width, height, fps)
            writer = make_writer(render_workers)
            render_workers = writer.workers
            used_workers = render_workers
            progress.rendering(writer)
            try:
                for input_frame in playback_inputs():
                    if comparison is None:
                        sentinel_written = ticks == len(frames)
                        event = state.step(input_frame)
                        ticks += 1
                        dead, complete = bool(event["dead"]), bool(event["level_complete"])
                    else:
                        primary = comparison.tracks[0]
                        ticks = primary.ticks
                        sentinel_written = primary.sentinel_written
                        dead, complete = primary.dead, primary.complete
                    timeline_ticks += 1
                    if input_frame is not None:
                        last_scene = snapshot_scene()
                        if effects is not None:
                            effects.update(last_scene, input_frame, _snapshot=False)
                        if objects is not None:
                            objects.update(last_scene, input_frame, _snapshot=False)
                    elif ticks:
                        if effects is not None:
                            effects.advance(3, _snapshot=False)
                        if objects is not None:
                            objects.advance(3, _snapshot=False)
                    if gold is not None:
                        gold.update(last_scene["static_state"]["collected_gold_mask"],
                                    comparison.gold_pickups)
                    target_count = (timeline_ticks * fps + 39) // 40
                    if warmup and timeline_ticks == 13:
                        # The serial prefix is actual output, not a discarded
                        # probe. Switching occurs before a new image submission,
                        # so terminal repeats never lose the previous image.
                        remaining = estimated_ticks - timeline_ticks
                        terminal_now = comparison.done if comparison is not None else dead or complete
                        selected = 1 if terminal_now else choose_workers(
                            remaining_ticks=remaining, scale=scale, players=len(sources),
                            object_count=object_count, fps=fps,
                            render_seconds=median(render_samples[-8:]),
                            write_seconds=median(write_samples[-8:]))
                        worker_decision = "measured"
                        if selected > 1:
                            writer.flush()
                            accumulate(prior_timings, writer.timings)
                            accumulate(prior_renderer_stats, writer.renderer_stats)
                            previous_writer_frames += writer.frames_written
                            writer.close()
                            writer = make_writer(selected)
                            progress.rendering(writer, previous_frames=previous_writer_frames)
                            used_workers = max(used_workers, writer.workers)
                        warmup = False
                    previous_render = writer.timings["render_seconds"]
                    previous_write = writer.timings["write_seconds"]
                    writer.submit(last_scene, render_options(), target_count - written)
                    if warmup:
                        render_samples.append(writer.timings["render_seconds"] - previous_render)
                        write_samples.append(writer.timings["write_seconds"] - previous_write)
                    written = target_count
                    if comparison is None and (dead or complete):
                        break
                if not written:
                    last_scene = snapshot_scene()
                    writer.submit(last_scene, render_options(), 1)
                    written = 1
                terminal = (any(track.dead or track.complete for track in comparison.tracks)
                            if comparison is not None else dead or complete)
                if terminal:
                    if terminal_hold_seconds > 0:
                        progress.stage("Rendering terminal hold")
                    advanced_ticks = 0
                    for _ in range(int(math.ceil(terminal_hold_seconds * fps))):
                        tail_tick = written * 40 // fps + 1 - timeline_ticks
                        if (effects is not None or objects is not None
                                or gold is not None and gold.animating) and tail_tick > advanced_ticks:
                            count = 3 * (tail_tick - advanced_ticks)
                            if effects is not None:
                                effects.advance(count, _snapshot=False)
                            if objects is not None:
                                objects.advance(count, _snapshot=False)
                            if gold is not None:
                                gold.advance(count)
                            advanced_ticks = tail_tick
                            writer.submit(last_scene, render_options(), 1)
                        else:
                            writer.repeat_last(1)
                        written += 1
                progress.stage("Finishing queued frames")
                writer.flush()
                if frame_stream is not process.stdin:
                    frame_stream.finish()
                writer.close()
                progress.stage("Finalising FFmpeg")
                process.stdin.close()
            except BrokenPipeError as exc:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    raise RuntimeError("FFmpeg closed its input but did not exit") from exc
                errors.seek(0, os.SEEK_END)
                errors.seek(max(0, errors.tell() - 8192))
                detail = errors.read().decode("utf-8", "replace").strip()
                raise RuntimeError(f"FFmpeg stopped while encoding: {detail or 'broken input pipe'}") from exc
            returncode = process.wait()
            if returncode:
                errors.seek(0, os.SEEK_END)
                errors.seek(max(0, errors.tell() - 8192))
                detail = errors.read().decode("utf-8", "replace").strip()
                raise RuntimeError(f"FFmpeg failed with exit code {returncode}: {detail}")
        if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
            raise RuntimeError("FFmpeg did not produce a video")
        progress.stage("Saving video")
        _replace_with_windows_retries(temporary_path, output_path)
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if process.stdin is not None and not process.stdin.closed:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
        if writer is not None:
            writer.close()
        temporary_path.unlink(missing_ok=True)
    stop_reason = "complete" if complete else "dead" if dead else "input_end"
    replays = (tuple(track.result(i) for i, track in enumerate(comparison.tracks))
               if comparison is not None else (VideoReplayResult(0, len(frames), ticks, 0,
                   None, stop_reason, sentinel_written, dead, complete),))
    if primary_label or any(secondary_labels):
        labels = (primary_label, *(secondary_labels or (None,) * (len(replays) - 1)))
        replays = tuple(replace(replay, label=label) for replay, label in zip(replays, labels))
    measurements = dict(prior_timings)
    accumulate(measurements, writer.timings)
    renderer_stats = dict(prior_renderer_stats)
    accumulate(renderer_stats, writer.renderer_stats)
    measurements.update(total_seconds=preparation_seconds + perf_counter()-timeline_started,
        preparation_seconds=preparation_seconds, renderer_setup_seconds=renderer_setup_seconds,
        renderer_reused=renderer_reused, render_workers=used_workers,
        requested_workers=requested_workers, worker_decision=worker_decision,
        transport=writer.transport, frame_delivery="timed" if fps > 40 else "raw",
        video_frames=written, renderer_stats=renderer_stats)
    if tracks is not None:
        measurements["replay_cache_hits"] = sum(track.cache_hit for track in tracks)
    if session is not None:
        session._record(history_key, measurements)
    return VideoEncodeResult(output_path, len(frames), ticks, written, fps, width, height,
        stop_reason, sentinel_written, dead, complete, replay_alignment, timeline_ticks, replays,
        used_workers, render_quality, measurements if profile else None)


def add_video_arguments(parser: argparse.ArgumentParser) -> None:
    from nv14_cli import parse_ltm_level_id, parse_nonnegative_int

    parser.add_argument("input", type=Path, help="combined demo, packed demo text, or libTAS .ltm")
    parser.add_argument("--secondary-replay", dest="secondary_replays", type=Path,
                        action="append", default=[], metavar="PATH",
                        help="player-only comparison replay on the primary level; repeat for more players")
    parser.add_argument("--replay-alignment", choices=("start", "exit"), default="start",
                        help="start together (default), or delay starts to complete together at the exit")
    parser.add_argument("--secondary-color", dest="secondary_colors", action="append",
                        metavar="#RRGGBB", help="repeat once per secondary to override the blue-first palette")
    parser.add_argument("--secondary-gold", choices=("off", "static", "animated"), default="off",
                        help="leave ghost-coloured gold after primary pickups; static disappears, animated plays collection clips")
    parser.add_argument("--primary-label", metavar="TEXT",
                        help="optional GUI-font label for the primary player")
    parser.add_argument("--secondary-label", dest="secondary_labels", action="append", metavar="TEXT",
                        help="one label per secondary in replay order; use an empty string to hide one")
    parser.add_argument("--label-position", choices=("follow", "top-left"), default="follow",
                        help="labels follow players (default), or form a static top-left legend")
    parser.add_argument("--label-size", type=int, default=8, metavar="PIXELS",
                        help="label font size in game pixels before scaling, 6..32 (default: 8)")
    parser.add_argument("--output", "-o", type=Path, help="MP4 destination (default: <input stem>.mp4)")
    parser.add_argument("--levels-file", type=Path, help="level database for LTM or packed-only demos")
    parser.add_argument("--level-id", type=parse_ltm_level_id)
    parser.add_argument("--ltm-postroll", type=parse_nonnegative_int, help="exclude exactly N recorded trailing LTM frames")
    parser.add_argument("--final-neutral", action=argparse.BooleanOptionalAction, default=True,
                        help="append one neutral tick to demos; LTM uses recorded frames only")
    parser.add_argument("--simulate-enemies", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--assets-path", type=Path, help="custom asset pack; default: bundled SWF artwork")
    parser.add_argument("--fps", type=int, default=40, help="40..240; rates above 40 repeat frames without interpolation")
    parser.add_argument("--scale", type=int, choices=range(1, 5), default=2, help="integer scale of the 792x600 stage (default: 2)")
    parser.add_argument("--particles", action=argparse.BooleanOptionalAction, default=True,
                        help="render original SWF particle effects (default: enabled; encoding only)")
    parser.add_argument("--particle-seed", type=int, default=0, help="independent cosmetic random seed (default: 0)")
    parser.add_argument("--object-animations", action=argparse.BooleanOptionalAction, default=True,
                        help="play original object clips and smooth drone eye turns (default: enabled; encoding only)")
    parser.add_argument("--terminal-hold-seconds", type=float, default=1.0, help="hold terminal gameplay; cosmetic clips continue (default: 1)")
    parser.add_argument("--crf", type=int, default=18, help="H.264 quality 0..51, lower is higher quality (default: 18)")
    parser.add_argument("--preset", default="medium", help="FFmpeg libx264 speed preset (default: medium)")
    parser.add_argument("--ffmpeg-path", type=Path, help="path to FFmpeg if it is not on PATH")
    parser.add_argument("--render-workers", type=parse_nonnegative_int, default=8,
                        help="render processes (default: 8): 0 selects automatically (up to 4), 1 is serial, maximum 64")
    parser.add_argument("--render-quality", choices=("exact", "fast"), default="fast",
                        help="fast cached ninja poses (default), or exact outlines; fast uses 1/8-pixel and 1-degree snapping")
    parser.add_argument("--replay-cache-dir", type=Path,
                        help="optional directory for reusable validated secondary pose tracks")
    parser.add_argument("--render-memory-mib", type=int, default=128,
                        help="RGB transport memory budget in MiB (default: 128; excludes artwork caches)")
    parser.add_argument("--progress", action=argparse.BooleanOptionalAction, default=True,
                        help="print periodic encoding progress to stdout (default: enabled)")
    parser.add_argument("--profile", action="store_true",
                        help="report rendering, transport, cache and total timing statistics")
    parser.add_argument("--config", type=Path, help="TOML defaults from [common] and [encode-video]")


def run_video_encode(args: argparse.Namespace) -> None:
    try:
        result = encode_replay_video(args.input, args.output,
            secondary_replays=args.secondary_replays, replay_alignment=args.replay_alignment,
            secondary_colors=args.secondary_colors, secondary_gold=args.secondary_gold,
            primary_label=args.primary_label, secondary_labels=args.secondary_labels,
            label_size=args.label_size, label_position=args.label_position,
            levels_file=args.levels_file, level_id=args.level_id, ltm_postroll=args.ltm_postroll,
            assets_path=args.assets_path, simulate_enemies=args.simulate_enemies,
            final_neutral=args.final_neutral, fps=args.fps, scale=args.scale,
            particles=args.particles, particle_seed=args.particle_seed,
            object_animations=args.object_animations,
            terminal_hold_seconds=args.terminal_hold_seconds, crf=args.crf,
            preset=args.preset, ffmpeg_path=args.ffmpeg_path,
            render_workers=args.render_workers, render_quality=args.render_quality,
            replay_cache_dir=args.replay_cache_dir,
            render_memory_mib=args.render_memory_mib, profile=args.profile, progress=args.progress)
    except (OSError, ValueError, TypeError, RuntimeError, ImportError) as exc:
        raise SystemExit(f"video export failed: {exc}; video output was not replaced") from exc
    print(f"wrote {result.output_path}: {result.video_frames} video frames at {result.fps} fps; "
          f"{result.simulated_ticks} gameplay ticks; {result.duration_seconds:.3f}s; "
          f"stop={result.stop_reason}; complete={int(result.complete)}; dead={int(result.dead)}; "
          f"final_neutral={int(result.final_neutral_written)}; "
          f"render_workers={result.render_workers}; render_quality={result.render_quality}")
    if result.timings is not None:
        import json
        print("performance: " + json.dumps(result.timings, sort_keys=True))
    if len(result.replays) > 1:
        print(f"comparison: {len(result.replays)} players; alignment={result.replay_alignment}; "
              f"{result.timeline_ticks} timeline ticks")
        for replay in result.replays:
            name = "primary" if replay.index == 0 else f"secondary {replay.index} ({replay.color})"
            print(f"  {name}: start +{replay.start_offset_ticks} ticks; "
                  f"{replay.simulated_ticks} gameplay ticks; stop={replay.stop_reason}; "
                  f"complete={int(replay.complete)}; dead={int(replay.dead)}; "
                  f"final_neutral={int(replay.final_neutral_written)}")
