"""Compare ghost-gold pixels and warmed encoding time between release trees.

Examples (run from the newer project root)::

    python -m tools.benchmark_video_v415 --compare-root ../nv14_v414 --verify-only
    python -m tools.benchmark_video_v415 --compare-root ../nv14_v414 \
        --case dense-20-animated-s1-w1 --case dense-20-animated-s1-w2 \
        --repeats 3 --output comparison.json

Each case imports each release in a separate subprocess. Pixel verification
hashes every complete RGB frame at the encoder boundary, without running a
lossy codec. Its temporary encoder stub is used only for verification; timed
encodes use the ordinary FFmpeg API and its unmodified codec/quality defaults.
Verification time, the discarded warm-up export, and subprocess startup are
excluded from the reported warmed timings. Repeats reuse one VideoEncodeSession
and its replay cache. The dense cases use delayed synthetic copies of primary
inputs, not independently verified successful replays.

This is a workload-specific comparison, not a promise of speedup on other maps,
machines, resolutions, or FFmpeg builds. Avoid concurrent CPU-heavy work when
measuring. For parallel rendering, render_seconds is summed worker work, not
elapsed wall time; compare total_seconds for end-to-end speedup.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTCOME_FIELDS = (
    "source_frames", "simulated_ticks", "video_frames", "fps", "width", "height",
    "stop_reason", "final_neutral_written", "dead", "complete", "replay_alignment",
    "timeline_ticks", "replays", "render_quality",
)


def _cases():
    cases = {}
    for ghosts in (2, 20):
        for mode in ("off", "static", "animated"):
            name = f"dense-{ghosts}-{mode}-s1-w1"
            cases[name] = dict(workload="dense", ghosts=ghosts, mode=mode,
                               scale=1, workers=1, fps=40, quality="exact",
                               alignment="start")
    for scale, workers in ((1, 2), (2, 1), (2, 2)):
        name = f"dense-20-animated-s{scale}-w{workers}"
        cases[name] = dict(workload="dense", ghosts=20, mode="animated",
                           scale=scale, workers=workers, fps=40, quality="exact",
                           alignment="start")
    for scale, workers, quality, alignment in (
        (1, 1, "exact", "start"), (1, 2, "exact", "start"),
        (2, 1, "fast", "exit"), (2, 2, "fast", "exit"),
        (4, 1, "exact", "exit"),
    ):
        name = f"visual-2-animated-s{scale}-w{workers}-{quality}-{alignment}"
        cases[name] = dict(workload="visual", ghosts=2, mode="animated",
                           scale=scale, workers=workers, fps=60, quality=quality,
                           alignment=alignment)
    return cases


def _json_value(value):
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


class _HashFrames:
    """Record one digest per displayed frame without retaining RGB buffers."""
    def __init__(self):
        self.hashes = []
        self.frame_bytes = None
        self.last = None
        self.closed = False

    def write_frame(self, pixels, repeats):
        if len(pixels) != self.frame_bytes:
            raise AssertionError(f"Incomplete RGB frame: {len(pixels)} != {self.frame_bytes}")
        self.last = hashlib.sha256(pixels).hexdigest()
        self.hashes.extend([self.last] * repeats)

    def repeat_last(self, repeats):
        if self.last is None:
            raise AssertionError("Repeat before first RGB frame")
        self.hashes.extend([self.last] * repeats)

    def write(self, pixels):
        self.write_frame(pixels, 1)
        return len(pixels)

    def close(self):
        self.closed = True


@contextmanager
def _raw_frame_verification(video):
    """Keep production simulation/rendering but replace the external encoder."""
    original = video.subprocess, video._find_ffmpeg, video._make_frame_stream
    streams = []

    class Process:
        def __init__(self, command, **options):
            self.stdin = _HashFrames()
            self.output = Path(command[-1])
            self.returncode = None
            streams.append(self.stdin)

        def wait(self, timeout=None):
            self.returncode = 0
            # Production code checks and atomically replaces the output file.
            # This is a temporary marker, not a video or user deliverable.
            self.output.write_bytes(b"raw-frame-verification")
            return self.returncode

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    def stream(pipe, width, height, fps):
        pipe.frame_bytes = width * height * 3
        return pipe

    # Replace only this module's subprocess reference. Multiprocessing still
    # uses the real subprocess module when spawning rendering workers.
    proxy = dict(vars(video.subprocess))
    proxy["Popen"] = Process
    video.subprocess = SimpleNamespace(**proxy)
    video._find_ffmpeg = lambda requested: "raw-frame-verification"
    video._make_frame_stream = stream
    try:
        yield streams
    finally:
        video.subprocess, video._find_ffmpeg, video._make_frame_stream = original


def _workload(case, InputFrame):
    tiles = ["0"] * 713
    for column in range(31):
        tiles[column * 23 + 5] = "1"
    neutral, right = InputFrame(), InputFrame(right=True)
    if case["workload"] == "dense":
        objects = "".join(f"!0^{x},134" for x in range(120, 701, 6))
        frames = [right] * 160
        delays = [3 * (index + 1) for index in range(case["ghosts"])]
    else:
        # Gold bursts, switch/door object clips and terminal hold, with ghosts
        # collecting at different times. Start and exit alignment are covered.
        objects = "!0^140,134!0^160,134!0^180,134!11^230,134,100,134"
        frames = [right] * 80
        delays = [9, 4]
    world = "".join(tiles) + "|5^100,134" + objects
    ghosts = [[neutral] * delay + frames for delay in delays]
    options = dict(secondary_replays=ghosts, secondary_gold=case["mode"],
                   scale=case["scale"], fps=case["fps"],
                   render_quality=case["quality"], replay_alignment=case["alignment"],
                   particles=case["workload"] == "visual", particle_seed=781,
                   object_animations=case["workload"] == "visual",
                   terminal_hold_seconds=.15, profile=True)
    if case["workload"] == "visual":
        options.update(primary_label="Primary", secondary_labels=("Blue", "Red"),
                       secondary_colors=("#3568a8", "#97436a"))
    return world, frames, options


def _outcome(result):
    return {key: _json_value(getattr(result, key)) for key in OUTCOME_FIELDS}


def _run_child(config_path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    root = Path(config["root"]).resolve()
    sys.path.insert(0, str(root))
    from nv14_engine import InputFrame
    import nv14_video as video
    import PIL

    if Path(video.__file__).resolve().parent != root:
        raise RuntimeError(f"Incorrect release imported: {video.__file__}")
    case = config["case"]
    world, frames, options = _workload(case, InputFrame)
    folder = config_path.parent
    options["replay_cache_dir"] = folder / "tracks"
    report = dict(root=str(root), case=case, environment=dict(
        python=sys.version, platform=platform.platform(), pillow=PIL.__version__,
        logical_cpus=os.cpu_count(),
        available_cpus=len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count(),
    ))
    if config["verify"]:
        with _raw_frame_verification(video) as streams:
            with video.VideoEncodeSession(render_workers=case["workers"]) as session:
                result = session.encode_replay_data_video(world, frames,
                    folder / "verify.mp4", **options)
            hashes = streams[-1].hashes
        if len(hashes) != result.video_frames:
            raise AssertionError(f"Frame count differs: {len(hashes)} != {result.video_frames}")
        report["verification"] = dict(outcome=_outcome(result), hashes=hashes,
            raw_rgb_sha256=hashlib.sha256("\n".join(hashes).encode("ascii")).hexdigest(),
            effective_workers=result.render_workers)
    if config["benchmark"]:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("FFmpeg is required for timing runs")
        report["environment"]["ffmpeg"] = subprocess.run(
            [ffmpeg, "-version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
        samples = []
        with video.VideoEncodeSession(render_workers=case["workers"]) as session:
            for index in range(config["repeats"] + 1):
                result = session.encode_replay_data_video(world, frames,
                    folder / "timed.mp4", **options)
                if index:
                    samples.append(_json_value(result.timings))
        report["benchmark"] = dict(samples=samples,
            median={key: statistics.median(sample[key] for sample in samples)
                    for key in ("total_seconds", "render_seconds", "write_seconds",
                                "wait_seconds", "preparation_seconds")},
            outcome=_outcome(result), effective_workers=result.render_workers)
    (folder / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _comparison(baseline, current):
    answer = {}
    if "verification" in baseline:
        old, new = baseline["verification"], current["verification"]
        sentinel = object()
        first_difference = next((index for index, (a, b) in enumerate(itertools.zip_longest(
            old["hashes"], new["hashes"], fillvalue=sentinel)) if a != b), None)
        changed = [key for key in sorted(old["outcome"].keys() | new["outcome"].keys())
                   if old["outcome"].get(key) != new["outcome"].get(key)]
        answer.update(raw_rgb_equal=first_difference is None,
                      first_different_frame_zero_based=first_difference,
                      changed_outcome_fields=changed,
                      identical=first_difference is None and not changed)
    if "benchmark" in baseline:
        old, new = baseline["benchmark"]["median"], current["benchmark"]["median"]
        answer["end_to_end_speedup"] = old["total_seconds"] / new["total_seconds"]
        answer["render_work_speedup"] = old["render_seconds"] / new["render_seconds"]
    return answer


def main(argv=None):
    cases = _cases()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--compare-root", required=True, type=Path)
    parser.add_argument("--current-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--case", action="append", choices=tuple(cases), dest="case_names")
    parser.add_argument("--repeats", type=int, default=3)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--verify-only", action="store_true")
    group.add_argument("--benchmark-only", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("video_v415_comparison.json"))
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    report = dict(note="Synthetic delayed ghosts; warm session medians exclude one warm-up. "
                       "Raw RGB verification precedes FFmpeg; benchmark uses ordinary FFmpeg defaults.",
                  repeats=args.repeats, cases={})
    names = args.case_names or list(cases)
    script = Path(__file__).resolve()
    for case_index, name in enumerate(names):
        reports = {}
        # Alternate release order to reduce a persistent first/second bias.
        roots = [("baseline", args.compare_root), ("current", args.current_root)]
        if case_index % 2:
            roots.reverse()
        for label, root in roots:
            with tempfile.TemporaryDirectory(prefix="nv14-v415-comparison-") as temporary:
                folder = Path(temporary)
                config = dict(root=str(root.resolve()), case=cases[name], repeats=args.repeats,
                              verify=not args.benchmark_only, benchmark=not args.verify_only)
                config_path = folder / "config.json"
                config_path.write_text(json.dumps(config), encoding="utf-8")
                subprocess.run([sys.executable, str(script), "--child", str(config_path)], check=True)
                reports[label] = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        reports["comparison"] = _comparison(reports["baseline"], reports["current"])
        report["cases"][name] = reports
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"case": name, **reports["comparison"]}), flush=True)
    return int(any(not item["comparison"].get("identical", True) for item in report["cases"].values()))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        _run_child(Path(sys.argv[2]))
    else:
        raise SystemExit(main())
