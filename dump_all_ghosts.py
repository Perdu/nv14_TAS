#!/usr/bin/env python3
# AI-generated
"""Export TAS ghost trajectories for N levels 00-0 through 99-4.

Run from the repository root (where get_demo.py and 'tas optimiser/' live):

    python3 dump_all_ghosts.py
    python3 dump_all_ghosts.py --start 46-0 --end 46-4 --force

Each demo is obtained from `python get_demo.py LEVEL_ID` and replayed through
nv14_dump into volume/ghosts_TAS/LEVEL_ID.csv. Output is atomic: an unsuccessful
export cannot replace an existing CSV.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OPTIMIZER_DIR = ROOT / "tas optimiser"
DESTINATION = ROOT / "volume" / "ghosts_TAS"
LEVEL_RE = re.compile(r"^(\d{2})-([0-4])$")
PACKED_RE = re.compile(r"\d+:(?:\d+(?:\|\d+)*)?")


def level_index(text: str) -> int:
    match = LEVEL_RE.fullmatch(text)
    if match is None or int(match.group(1)) > 99:
        raise argparse.ArgumentTypeError("level must be between 00-0 and 99-4")
    return int(match.group(1)) * 5 + int(match.group(2))


def packed_demo(output: str) -> str:
    """Pick the packed replay line, allowing get_demo.py to print a status line."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    print(lines)
    for line in reversed(lines):
        if PACKED_RE.fullmatch(line):
            return line
    # Also accept a status prefix, e.g. 'Demo 00-0: 123:1|2|3'.
    matches = [match.group() for line in lines for match in PACKED_RE.finditer(line)]
    if len(matches) == 1:
        return matches[0]
    raise ValueError("get_demo.py did not print one unambiguous packed demo string")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="00-0", help="first level (default: 00-0)")
    parser.add_argument("--end", default="99-4", help="last level (default: 99-4)")
    parser.add_argument("--levels-file", type=Path, help="path to N level database (default: external/N v1.4 + NReality levels.txt)")
    parser.add_argument("--force", action="store_true", help="regenerate existing CSVs")
    parser.add_argument("--timeout", type=float, default=90, help="seconds allowed for each get_demo.py invocation")
    parser.add_argument("--fields", help="comma-separated CSV fields (default: all dump-player fields); e.g. frame,x,y,vx,vy")
    parser.add_argument("--no-simulate-enemies", action="store_true", help="disable enemy simulation (enabled by default)")
    args = parser.parse_args(argv)

    try:
        first, last = level_index(args.start), level_index(args.end)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if first > last:
        parser.error("--start must not be after --end")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    fields = [part.strip() for part in args.fields.split(",")] if args.fields else None
    if fields is not None and any(not field for field in fields):
        parser.error("--fields must be a comma-separated list of nonempty field names")

    fetcher = ROOT / "get_demo.py"
    if not fetcher.is_file():
        parser.error(f"missing {fetcher}: run this script from the repository root")
    if not OPTIMIZER_DIR.is_dir():
        parser.error(f"missing optimiser directory: {OPTIMIZER_DIR}")
    sys.path.insert(0, str(OPTIMIZER_DIR))
    from nv14_dump import dump_player_data_csv
    from nv14_ltm import LEVEL_DATABASE_NAME, find_level_record
    from nv14_native import require_native
    from nv14_replay import parse_combined_level_replay

    levels_file = args.levels_file or ROOT / "external" / LEVEL_DATABASE_NAME
    if not levels_file.is_file():
        parser.error(f"levels database not found: {levels_file} (use --levels-file FILE)")
    try:
        native = require_native()
        if not native.backend_info().get("player_dump_abi"):
            raise RuntimeError("native player dump ABI is unavailable")
    except RuntimeError as exc:
        parser.error(f"{exc}; build the extension in 'tas optimiser/' using python3 build_native.py")

    DESTINATION.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    failures: list[tuple[str, str]] = []
    count = last - first + 1
    for index, current in enumerate(range(first, last + 1), 1):
        level_id = f"{current // 5:02d}-{current % 5}"
        csv_path = DESTINATION / f"{level_id}.csv"
        if csv_path.exists() and not args.force:
            skipped += 1
            print(f"[{index}/{count}] {level_id}: already exists (skip)", flush=True)
            continue
        try:
            completed = subprocess.run(
                [sys.executable, str(fetcher), level_id],
                cwd=ROOT, capture_output=True, text=True,
                timeout=args.timeout, check=False,
            )
            if completed.returncode != 0:
                reason = completed.stderr.strip() or completed.stdout.strip()
                raise RuntimeError(f"get_demo.py returned {completed.returncode}: {reason[-350:]}")
            demo_string = packed_demo(completed.stdout)
            # These records contain the raw level, while get_demo.py returns
            # only the packed input sequence. Combine them in memory.
            record = find_level_record(levels_file, level_id)
            level_data = parse_combined_level_replay(record + "0:#").level_string
            result = dump_player_data_csv(
                level_data, demo_string, csv_path,
                simulate_enemies=not args.no_simulate_enemies,
                fields=fields,
            )
            written += 1
            print(f"[{index}/{count}] {level_id}: {result.rows} rows ({result.stop_reason})", flush=True)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            failures.append((level_id, str(exc)))
            print(f"[{index}/{count}] {level_id}: FAILED: {exc}", file=sys.stderr, flush=True)

    failure_log = DESTINATION / "failed_levels.txt"
    if failures:
        failure_log.write_text(
            "".join(f"{level_id}: {reason}\n" for level_id, reason in failures),
            encoding="utf-8",
        )
        print(f"Failures written to {failure_log}", file=sys.stderr)
    elif failure_log.exists():
        failure_log.unlink()
    print(f"Finished: {written} CSVs written, {skipped} skipped, {len(failures)} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Existing CSVs are preserved; rerun to resume.", file=sys.stderr)
        raise SystemExit(130)
