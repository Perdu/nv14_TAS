r"""Benchmark optional video encoding and compare releases without loading RGB videos.

Run from the project root (or invoke this script by absolute path)::

    python -m tools.benchmark_video --ghosts 0 20 --scales 1 4 --workers 1 4
    python -m tools.benchmark_video --ghosts 20 --workers 1 4 --repeats 3 \
        --compare-root ../nv14_v409 --json

Ghosts are synthetic copies of the primary inputs prefixed with neutral ticks.
They are a reproducible rendering workload, NOT independent successful replays.
Input must contain both a level and a complex replay (the bundled 00-1 fixture
is the default). Each case runs in a fresh process importing the requested tree;
repeats share that process but call the ordinary encode API independently.
FFmpeg preset/CRF and cosmetic options retain their API defaults, except the
terminal hold is explicitly configurable. Timings exclude decoding/verification.

Temporary MP4s and streamed framemd5 files are deleted by default. --keep-videos
retains them in a newly created subdirectory; existing inputs are never replaced.
Comparisons return a nonzero exit status if replay outcomes, decoded frame counts,
or even one decoded RGB frame differs. Lossy H.264 equality requires matching
FFmpeg builds/settings; use the same interpreter and machine for both releases.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import asdict, is_dataclass
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_GHOST_NOTE = (
    "Synthetic ghosts are neutral-prefix variants of the primary inputs, "
    "not independently verified successful runs."
)
OUTCOME_FIELDS = (
    "source_frames", "simulated_ticks", "video_frames", "fps", "width", "height",
    "stop_reason", "final_neutral_written", "dead", "complete", "replay_alignment",
    "timeline_ticks", "replays", "render_quality",
)


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _nonnegative(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return number


def _json_value(value):
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _frame_hashes(path: Path):
    """Yield one decoded RGB digest per frame, ignoring FFmpeg metadata lines."""
    with path.open(encoding="ascii") as stream:
        for line in stream:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = [field.strip() for field in line.split(",")]
            if len(fields) != 6:
                raise ValueError(f"Unexpected framemd5 record in {path}: {line!r}")
            yield fields[-1]


def _hash_video(executable: str, path: Path) -> dict:
    hashes_path = path.with_suffix(".framemd5")
    command = [executable, "-v", "error", "-n", "-i", str(path), "-map", "0:v:0",
               "-an", "-vsync", "0", "-pix_fmt", "rgb24", "-f", "framemd5",
               str(hashes_path)]
    completed = subprocess.run(command, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, text=True)
    if completed.returncode:
        raise RuntimeError(f"FFmpeg verification failed: {completed.stderr.strip()}")
    digest = hashlib.sha256()
    count = 0
    for frame_hash in _frame_hashes(hashes_path):
        digest.update(frame_hash.encode("ascii") + b"\n")
        count += 1
    return {"decoded_frames": count, "decoded_rgb_sha256": digest.hexdigest(),
            "hashes_path": str(hashes_path)}


def _run_case(config_path: Path) -> None:
    """Private subprocess entry: import only the selected release tree."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    root = Path(config["root"]).resolve()
    # The script itself may belong to a newer checkout. Do not let it shadow the
    # requested release, including when multiprocessing imports this main module.
    sys.path.insert(0, str(root))
    from nv14_engine import InputFrame
    from nv14_replay import decode_complex_replay, parse_combined_level_replay
    import nv14_video

    if Path(nv14_video.__file__).resolve().parent != root:
        raise RuntimeError(f"Imported nv14_video from an unexpected tree: {nv14_video.__file__}")
    source = Path(config["input"])
    combined = parse_combined_level_replay(source.read_text(encoding="utf-8-sig"))
    frames = decode_complex_replay(combined.replay_string).frames
    case = config["case"]
    neutral = InputFrame(False, False, False, False)
    ghosts = [[neutral] * ((index + 1) * config["ghost_delay"]) + frames
              for index in range(case["ghosts"])]
    folder = config_path.parent
    runs = []
    for repeat in range(config["repeats"]):
        output_path = folder / f"repeat_{repeat + 1}.mp4"
        if output_path.exists() or output_path.resolve() == source.resolve():
            raise FileExistsError(f"Refusing to replace benchmark output: {output_path}")
        started = time.perf_counter()
        result = nv14_video.encode_replay_data_video(
            combined.level_string, frames, output_path,
            secondary_replays=ghosts, replay_alignment="start", fps=case["fps"],
            scale=case["scale"], render_workers=case["workers"],
            render_quality=case["quality"],
            terminal_hold_seconds=config["terminal_hold"], ffmpeg_path=config["ffmpeg"],
        )
        elapsed = time.perf_counter() - started
        hashes = _hash_video(config["ffmpeg"], output_path)
        if hashes["decoded_frames"] != result.video_frames:
            raise RuntimeError(f"Decoded frame count {hashes['decoded_frames']} differs "
                               f"from reported count {result.video_frames}")
        runs.append({
            "repeat": repeat + 1, "elapsed_seconds": elapsed,
            "encoded_frames_per_second": result.video_frames / elapsed,
            "effective_workers": getattr(result, "render_workers", 1),
            "timings": _json_value(getattr(result, "timings", None)),
            "performance": _json_value(getattr(result, "performance", None)),
            "outcome": {key: _json_value(getattr(result, key))
                        for key in OUTCOME_FIELDS if hasattr(result, key)},
            "output_path": str(output_path), **hashes,
        })
    median_seconds = statistics.median(run["elapsed_seconds"] for run in runs)
    report = {
        "root": str(root), "case": case, "runs": runs,
        "median_elapsed_seconds": median_seconds,
        "median_encoded_frames_per_second": statistics.median(
            run["encoded_frames_per_second"] for run in runs),
        "repeat_outputs_identical": all(
            run["outcome"] == runs[0]["outcome"]
            and run["decoded_rgb_sha256"] == runs[0]["decoded_rgb_sha256"]
            for run in runs[1:]),
    }
    (folder / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _compare_runs(baseline: dict, current: dict) -> dict:
    differences = []
    all_equal = True
    for old, new in zip(baseline["runs"], current["runs"], strict=True):
        outcome_equal = old["outcome"] == new["outcome"]
        first_different_frame = None
        sentinel = object()
        for index, (left, right) in enumerate(itertools.zip_longest(
                _frame_hashes(Path(old["hashes_path"])),
                _frame_hashes(Path(new["hashes_path"])), fillvalue=sentinel)):
            if left != right:
                first_different_frame = index
                break
        same_frames = (first_different_frame is None
                       and old["decoded_frames"] == new["decoded_frames"])
        all_equal = all_equal and outcome_equal and same_frames
        differences.append({
            "repeat": old["repeat"], "outcomes_equal": outcome_equal,
            "decoded_rgb_frames_equal": same_frames,
            "first_different_frame_zero_based": first_different_frame,
            "changed_outcome_fields": [key for key in sorted(old["outcome"].keys()
                                       | new["outcome"].keys())
                                       if old["outcome"].get(key) != new["outcome"].get(key)],
        })
    return {
        "identical": all_equal,
        "speedup": baseline["median_elapsed_seconds"] / current["median_elapsed_seconds"],
        "runs": differences,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path,
                        default=PROJECT_ROOT / "tests/example_00_1_speedrun.txt",
                        help="combined level/complex replay text file")
    parser.add_argument("--ghosts", type=_nonnegative, nargs="+", default=[0, 20],
                        help="synthetic secondary-player counts (default: 0 20)")
    parser.add_argument("--ghost-delay", type=_positive, default=1,
                        help="neutral prefix increases by this many ticks per ghost")
    parser.add_argument("--scale", "--scales", dest="scales", type=_positive,
                        nargs="+", default=[1])
    parser.add_argument("--workers", type=_nonnegative, nargs="+", default=[1],
                        help="requested render-worker counts; 0 uses automatic selection")
    parser.add_argument("--fps", type=_positive, nargs="+", default=[40])
    parser.add_argument("--quality", choices=("exact", "fast"), default="exact")
    parser.add_argument("--repeats", type=_positive, default=1)
    parser.add_argument("--terminal-hold", type=float, default=1.0, metavar="SECONDS")
    parser.add_argument("--compare-root", type=Path,
                        help="baseline tree with built native extensions, e.g. v4.09")
    parser.add_argument("--keep-videos", type=Path, metavar="DIRECTORY",
                        help="retain outputs in a new unique subdirectory here")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable")
    parser.add_argument("--json", action="store_true", help="print full report as JSON")
    parser.add_argument("--_case-config", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv=None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args._case_config is not None:
        _run_case(args._case_config)
        return 0
    source = args.input.resolve()
    if not source.is_file():
        parser.error(f"Input file does not exist: {source}")
    if not 0 <= args.terminal_hold < float("inf"):
        parser.error("--terminal-hold must be a finite nonnegative number")
    if any(not 40 <= fps <= 240 for fps in args.fps):
        parser.error("--fps values must be between 40 and 240")
    executable = shutil.which(args.ffmpeg)
    if executable is None:
        parser.error(f"FFmpeg executable not found: {args.ffmpeg}")
    roots = [("current", PROJECT_ROOT)]
    if args.compare_root:
        baseline_root = args.compare_root.resolve()
        if not (baseline_root / "nv14_video.py").is_file():
            parser.error(f"Baseline tree has no nv14_video.py: {baseline_root}")
        roots.insert(0, ("baseline", baseline_root))
    if args.keep_videos:
        args.keep_videos.mkdir(parents=True, exist_ok=True)
        context = nullcontext(tempfile.mkdtemp(prefix="video_benchmark_", dir=args.keep_videos))
    else:
        context = tempfile.TemporaryDirectory(prefix="nv14_video_benchmark_")
    report = {
        "input": str(source), "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "python": sys.executable, "ffmpeg": executable, "ghost_note": SYNTHETIC_GHOST_NOTE,
        "ghost_delay_ticks": args.ghost_delay, "terminal_hold_seconds": args.terminal_hold,
        "ffmpeg_encoding": "Unchanged API defaults: preset=medium, CRF=18.",
        "timing_scope": "encode API call; verification and input parsing excluded",
        "cases": [],
    }
    print(SYNTHETIC_GHOST_NOTE, file=sys.stderr)
    success = True
    with context as temporary:
        report["retained_outputs"] = str(Path(temporary).resolve()) if args.keep_videos else None
        combinations = itertools.product(args.ghosts, args.scales, args.workers, args.fps)
        for index, (ghosts, scale, workers, fps) in enumerate(combinations):
            case = {"ghosts": ghosts, "scale": scale, "workers": workers,
                    "fps": fps, "quality": args.quality}
            case_report = {"case": case}
            for label, root in roots:
                print(f"{label}: {ghosts} ghosts, scale {scale}, workers {workers}, "
                      f"{fps} FPS, {args.repeats} repeat(s)", file=sys.stderr, flush=True)
                folder = Path(temporary).resolve() / f"case_{index:03d}" / label
                folder.mkdir(parents=True)
                config_path = folder / "config.json"
                config = {"root": str(root), "input": str(source), "case": case,
                          "ghost_delay": args.ghost_delay, "repeats": args.repeats,
                          "terminal_hold": args.terminal_hold, "ffmpeg": executable}
                config_path.write_text(json.dumps(config), encoding="utf-8")
                completed = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                            "--_case-config", str(config_path)],
                                           cwd=root, stdout=sys.stderr)
                if completed.returncode:
                    raise RuntimeError(f"{label} benchmark subprocess failed ({completed.returncode})")
                case_report[label] = json.loads((folder / "result.json").read_text(encoding="utf-8"))
                success = success and case_report[label]["repeat_outputs_identical"]
            if args.compare_root:
                case_report["comparison"] = _compare_runs(case_report["baseline"], case_report["current"])
                success = success and case_report["comparison"]["identical"]
            report["cases"].append(case_report)
        report["all_outputs_match"] = success
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("ghosts scale requested effective FPS elapsed_s encode_FPS baseline_s speedup identical")
            for item in report["cases"]:
                case = item["case"]
                current = item["current"]
                effective = ",".join(str(run["effective_workers"]) for run in current["runs"])
                baseline = item.get("baseline")
                comparison = item.get("comparison")
                previous = f"{baseline['median_elapsed_seconds']:.3f}" if baseline else "-"
                speedup = f"{comparison['speedup']:.3f}x" if comparison else "-"
                identical = str(comparison["identical"]) if comparison else "-"
                print(f"{case['ghosts']} {case['scale']} {case['workers']} {effective} "
                      f"{case['fps']} {current['median_elapsed_seconds']:.3f} "
                      f"{current['median_encoded_frames_per_second']:.1f} "
                      f"{previous} {speedup} {identical}")
            if args.keep_videos:
                print(f"Retained outputs: {report['retained_outputs']}")
            if not success:
                print("Output verification FAILED; rerun with --json for difference details.", file=sys.stderr)
    return 0 if success else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Video benchmark failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
