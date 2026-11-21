#!/usr/bin/env python3
"""Find libTAS movies that beat a level's published N demo.

Requires PyYAML and the optimiser (including its built native extension).
Run from either the project root or the optimiser directory, for example:

    python3 optimiser/compare_ltm_demos.py volume/n_levels wip
    python3 compare_ltm_demos.py '../volume/n_levels/*.ltm' --mode auto
    python3 compare_ltm_demos.py wip/00-0_*.ltm --level 00-0 --mode sr --all
    python3 compare_ltm_demos.py volume/n_levels --mode both --csv comparisons.csv

In auto mode, filenames containing an '_hs' suffix are compared with the
Highscore demo; all other movies are compared with the Speedrun demo.
For a single LTM, --mode sr/hs overrides this inference. --mode both checks both.

Speedrun: fewer completion frames is better. Highscore: more timer ticks is
better (90 seconds initially, plus gold bonuses, minus completion frames).
In either mode, smaller pre-finish *edge-to-edge* door gap is better. A door
improvement with a worse primary score is labelled DISTANCE ONLY, not BEST.

Comparison is to the metadata stored in tas/level_data.yml, not to the input
movie, optimiser checkpoint, or globally best replay. Every LTM is simulated;
file length or trailing neutral padding is never treated as a completion score.
No files are modified except an explicitly requested --csv export.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import glob
import math
from pathlib import Path
import re
import sys
from typing import Sequence

# Also work when copied next to the existing root-level ltm_to_demo.py and
# sol_to_demo.py rather than kept inside the optimiser directory.
_SCRIPT_DIR = Path(__file__).resolve().parent
if not (_SCRIPT_DIR / "nv14_auto.py").is_file():
    _OPTIMISER_DIR = _SCRIPT_DIR / "optimiser"
    if (_OPTIMISER_DIR / "nv14_auto.py").is_file():
        sys.path.insert(0, str(_OPTIMISER_DIR))

TICKS_PER_SECOND = 40
INITIAL_TIME_TICKS = 90 * TICKS_PER_SECOND
LEVEL_NAME = re.compile(r"^(\d{2}-[0-4])(?:$|[_. -])")
SPEEDRUN_TIME = re.compile(r"^\s*(\d+)\s*f(?:\s*\([^)]*\))?\s*$", re.I)
HIGHSCORE_SUFFIX = re.compile(r"(?:^|_)hs(?:_|$)", re.I)


class ComparisonError(ValueError):
    """Input, demo metadata, or emulator validation error."""


@dataclass(frozen=True)
class Baseline:
    frames_or_ticks: int
    door_gap: float
    level_string: str


@dataclass(frozen=True)
class Result:
    path: str
    level: str
    mode: str
    status: str
    score: int | None = None
    demo_score: int | None = None
    score_gain: int | None = None
    door_gap: float | None = None
    demo_door_gap: float | None = None
    door_gain: float | None = None
    detail: str = ""

    def csv_row(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _project_root() -> Path:
    script = Path(__file__).resolve().parent
    for root in (Path.cwd(), script.parent, script):
        if (root / "tas" / "level_data.yml").is_file():
            return root
    # Installation next to the existing sol_to_demo.py/ltm_to_demo.py is also
    # supported; an explicit --level-data can override this default.
    return script.parent if script.name == "optimiser" else script


def _metadata_score(row: dict, mode: str) -> int:
    raw = row.get("time")
    if mode == "sr":
        match = SPEEDRUN_TIME.fullmatch(str(raw))
        if not match:
            raise ComparisonError(f"Speedrun.time must be a frame count such as '335 f', got {raw!r}")
        return int(match.group(1))
    try:
        seconds = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ComparisonError(f"Highscore.time must be seconds, got {raw!r}") from exc
    ticks = seconds * TICKS_PER_SECOND
    if not ticks.is_finite() or ticks != ticks.to_integral_value():
        raise ComparisonError(f"Highscore.time does not represent whole 1/40-second ticks: {raw!r}")
    return int(ticks)


def _metadata_door_gap(row: dict) -> float:
    try:
        result = float(row["distance_to_door"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ComparisonError("demo is missing a numeric distance_to_door") from exc
    if not math.isfinite(result):
        raise ComparisonError("demo distance_to_door must be finite")
    return result


def read_baseline(db: dict, level: str, mode: str) -> Baseline:
    try:
        row = db[level]["Highscore" if mode == "hs" else "Speedrun"]
    except (KeyError, TypeError) as exc:
        raise ComparisonError(f"no {mode.upper()} demo in level_data.yml for {level}") from exc
    if not isinstance(row, dict):
        raise ComparisonError(f"invalid {mode.upper()} demo entry for {level}")
    demo = row.get("demo")
    if not isinstance(demo, str) or not demo.strip():
        raise ComparisonError(f"missing demo replay for {level} {mode.upper()}")
    from nv14_replay import parse_combined_level_replay
    try:
        combined = parse_combined_level_replay(demo)
    except ValueError as exc:
        raise ComparisonError(f"invalid demo level record for {level} {mode.upper()}: {exc}") from exc
    return Baseline(
        frames_or_ticks=_metadata_score(row, mode),
        door_gap=_metadata_door_gap(row),
        level_string=combined.level_string,
    )


def compare_metrics(
    path: str, level: str, mode: str, candidate_score: int, door_gap: float,
    baseline: Baseline,
) -> Result:
    # Positive is better for both deltas: saved frames / extra highscore ticks,
    # and reduced door-edge distance respectively.
    score_gain = (
        baseline.frames_or_ticks - candidate_score if mode == "sr"
        else candidate_score - baseline.frames_or_ticks
    )
    gap_gain = baseline.door_gap - door_gap
    # Door data recorded in YAML is decimal text from a float. Tolerate the
    # few ULPs introduced by YAML serialization and native arithmetic.
    gap_better = gap_gain > 1e-9
    if score_gain > 0:
        status = "BEST"
    elif score_gain == 0 and gap_better:
        status = "TIEBREAK"
    elif gap_better:
        status = "DISTANCE ONLY"
    else:
        status = "NO GAIN"
    return Result(
        path, level, mode, status, candidate_score, baseline.frames_or_ticks,
        score_gain, door_gap, baseline.door_gap, gap_gain,
    )


def evaluate_movie(path: Path, baseline: Baseline, *, branch: int) -> tuple[int, int, float] | None:
    """Return finish frame, absolute highscore ticks and door edge gap.

    None means no verified completion. `auto_completion_probe_frames()` keeps
    recorded neutral post-roll that can contain the completion tick.
    """
    from nv14_auto import evaluate_replay_with_sentinel, pre_finish_exit_edge_distance
    from nv14_engine import parse_level_string
    from nv14_ltm import LtmMovie

    movie = LtmMovie.load(path, branch=branch)
    level = parse_level_string(baseline.level_string, simulate_enemies=True)
    evaluation = evaluate_replay_with_sentinel(
        level, movie.auto_completion_probe_frames(), trace_stride=1,
    )
    if not evaluation.valid or evaluation.finish_tick is None:
        return None
    gap = pre_finish_exit_edge_distance(level, evaluation)
    if gap is None or not math.isfinite(gap):
        raise ComparisonError("completed replay has no measurable pre-finish exit-door gap")
    return (
        evaluation.finish_tick,
        INITIAL_TIME_TICKS + evaluation.gold_bonus_ticks - evaluation.finish_tick,
        gap,
    )


def _modes_for(path: Path, mode: str) -> tuple[str, ...]:
    if mode == "both":
        return ("sr", "hs")
    if mode != "auto":
        return (mode,)
    level_match = LEVEL_NAME.match(path.stem)
    suffix = path.stem[level_match.end():] if level_match else path.stem
    return ("hs",) if HIGHSCORE_SUFFIX.search(suffix) else ("sr",)


def find_movies(paths: Sequence[str]) -> list[Path]:
    found: dict[str, Path] = {}
    for item in paths:
        # Support shell-expanded globs and quoted globs on all platforms.
        expanded = [Path(p) for p in glob.glob(item, recursive=True)] if glob.has_magic(item) else [Path(item)]
        if not expanded:
            raise ComparisonError(f"no files match {item!r}")
        for entry in expanded:
            if entry.is_dir():
                candidates = entry.rglob("*.ltm")
            elif entry.is_file():
                candidates = [entry]
            else:
                raise ComparisonError(f"LTM path does not exist: {entry}")
            for candidate in candidates:
                if candidate.is_file() and candidate.suffix.lower() == ".ltm":
                    found[str(candidate.resolve())] = candidate
    return sorted(found.values(), key=lambda path: str(path))


def _read_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise ComparisonError("PyYAML is required: python3 -m pip install pyyaml") from exc
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            data = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise ComparisonError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ComparisonError(f"{path} must contain a mapping of level IDs")
    return data


def scan(paths: Sequence[Path], db: dict, *, mode: str, branch: int, level: str | None) -> list[Result]:
    baselines: dict[tuple[str, str], Baseline] = {}
    results: list[Result] = []
    for path in paths:
        level_id = level or (LEVEL_NAME.match(path.stem).group(1) if LEVEL_NAME.match(path.stem) else None)
        for kind in _modes_for(path, mode):
            if level_id is None:
                results.append(Result(str(path), "?", kind, "ERROR", detail="could not infer level ID; use --level"))
                continue
            try:
                key = (level_id, kind)
                if key not in baselines:
                    baselines[key] = read_baseline(db, level_id, kind)
                baseline = baselines[key]
                evaluated = evaluate_movie(path, baseline, branch=branch)
                if evaluated is None:
                    results.append(Result(str(path), level_id, kind, "INCOMPLETE", detail="no verified finish"))
                    continue
                finish_frame, hs_ticks, gap = evaluated
                metric = finish_frame if kind == "sr" else hs_ticks
                results.append(compare_metrics(str(path), level_id, kind, metric, gap, baseline))
            except (ComparisonError, ValueError, OSError, RuntimeError) as exc:
                results.append(Result(str(path), level_id, kind, "ERROR", detail=str(exc)))
    return results


def render(result: Result) -> str:
    prefix = f"[{result.status}] {result.level} {result.mode.upper()} {result.path}:"
    if result.score is None:
        return f"{prefix} {result.detail}"
    if result.mode == "sr":
        score_text = (
            f"{result.score} f (demo {result.demo_score} f, "
            f"gain {result.score_gain:+d} f)"
        )
    else:
        score_text = (
            f"{result.score / TICKS_PER_SECOND:.3f} s "
            f"(demo {result.demo_score / TICKS_PER_SECOND:.3f} s, "
            f"gain {result.score_gain:+d} ticks)"
        )
    return (
        f"{prefix} {score_text}; "
        f"door {result.door_gap:.6g} px (demo {result.demo_door_gap:.6g}, "
        f"gain {result.door_gain:+.6g} px)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", metavar="LTM_OR_DIRECTORY", nargs="*", help="LTM paths, directory trees, or quoted glob patterns")
    parser.add_argument("--level-data", type=Path, help="path to tas/level_data.yml (default: auto-detected)")
    parser.add_argument("--level", help="override level ID when filenames don't identify it")
    parser.add_argument("--mode", choices=("auto", "sr", "hs", "both"), default="auto", help="auto: *_hs.ltm -> Highscore, other movies -> Speedrun")
    parser.add_argument("--branch", type=int, default=0, help="read inputsN instead of inputs (default: 0)")
    parser.add_argument("--all", action="store_true", help="show movies without gains and incomplete replays too")
    parser.add_argument("--csv", type=Path, help="export every comparison (including no-gain/incomplete) to CSV")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.branch < 0:
        print("error: --branch must be non-negative", file=sys.stderr)
        return 2
    if args.level is not None and not re.fullmatch(r"\d{2}-[0-4]", args.level):
        print("error: --level must look like 00-0", file=sys.stderr)
        return 2
    root = _project_root()
    db_path = args.level_data or (root / "tas" / "level_data.yml")
    try:
        db = _read_yaml(db_path)
        paths = find_movies(args.paths or [str(root / "volume" / "n_levels")])
        if not paths:
            raise ComparisonError("no .ltm files found")
        rows = scan(paths, db, mode=args.mode, branch=args.branch, level=args.level)
        if args.csv is not None:
            with args.csv.open("w", newline="", encoding="utf-8") as out:
                writer = csv.DictWriter(out, fieldnames=list(Result.__dataclass_fields__))
                writer.writeheader()
                writer.writerows(row.csv_row() for row in rows)
    except ComparisonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    positives = {"BEST", "TIEBREAK", "DISTANCE ONLY"}
    for row in rows:
        if args.all or row.status in positives or row.status == "ERROR":
            print(render(row))
    counts = {status: sum(row.status == status for row in rows) for status in (*sorted(positives), "NO GAIN", "INCOMPLETE", "ERROR")}
    print(f"Checked {len(rows)} comparison(s): " + ", ".join(f"{count} {status.lower()}" for status, count in counts.items()) + ".")
    if not args.all and counts["INCOMPLETE"]:
        print("(Incomplete movies are omitted; use --all to see them.)")
    return 1 if counts["ERROR"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
