#!/usr/bin/env python3
# AI-generated
"""Dump TAS ghosts for every N level, from 00-0 to 99-4.

Place this file beside get_demo.py at your repository root:

    python3 dump_all_ghosts.py
    python3 dump_all_ghosts.py --start 46-0 --end 46-4 --force

The script fetches each packed demo using get_demo.py and reconstructs the
player's trajectory with the existing native dump_player_data_csv API.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OPTIMIZER_DIR = ROOT / "optimiser"
DESTINATION = ROOT / "volume" / "ghosts_TAS"
LEVEL_RE = re.compile(r"(\d{2})-([0-4])\Z")

# The old expression did not allow signed packed words (which the native demo
# decoder accepts), whitespace, quoted values or multiple diagnostics in stdout.
# Extract candidates, then validate them with the *same* decoder as the dumper.
PACKED_CANDIDATE_RE = re.compile(
    r"(?<![\w\d])(?P<ticks>\d+)\s*:\s*"
    r"(?P<words>[+-]?\d+(?:\s*\|\s*[+-]?\d+)*)?"
)
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def level_index(text: str) -> int:
    match = LEVEL_RE.fullmatch(text)
    if match is None or int(match.group(1)) > 99:
        raise argparse.ArgumentTypeError("level must be between 00-0 and 99-4")
    return int(match.group(1)) * 5 + int(match.group(2))


def packed_demo(output: str) -> str:
    """Return the last *valid* packed replay emitted by get_demo.py.

    Handles raw strings, quoted strings, labelled output, JSON and full
    combined level+replay records. Uses the optimiser's decoder as the single
    authority on the actual packed-demo format.
    """
    from nv14_replay import decode_complex_replay

    output = ANSI_ESCAPE_RE.sub("", output.lstrip("\ufeff"))
    valid: list[str] = []

    for match in PACKED_CANDIDATE_RE.finditer(output):
        ticks = int(match.group("ticks"))
        words_text = match.group("words") or ""
        words = [str(int(word.strip())) for word in words_text.split("|") if word.strip()]
        candidate = f"{ticks}:{'|'.join(words)}"
        try:
            decoded = decode_complex_replay(candidate)
        except (ValueError, OverflowError):
            continue
        if decoded.tick_count == ticks:
            valid.append(candidate)

    # Sometimes get_demo.py prints a JSON string/object; the regex above
    # handles plain JSON strings and most dictionaries, but this additionally
    # supports escaped replay values inside JSON.
    if not valid:
        try:
            data = json.loads(output.strip())
        except (ValueError, TypeError):
            data = None
        if data is not None:
            values = [data] if isinstance(data, str) else (
                [data[k] for k in ("demo", "demoString", "demo_string", "replay", "replay_string")
                 if k in data and isinstance(data[k], str)] if isinstance(data, dict) else []
            )
            for value in values:
                for match in PACKED_CANDIDATE_RE.finditer(value):
                    ticks = int(match.group("ticks"))
                    words_text = match.group("words") or ""
                    words = [str(int(word.strip())) for word in words_text.split("|") if word.strip()]
                    candidate = f"{ticks}:{'|'.join(words)}"
                    try:
                        decode_complex_replay(candidate)
                    except (ValueError, OverflowError):
                        continue
                    valid.append(candidate)

    if valid:
        # If status/debug output includes other valid-looking snippets, the
        # final replay line is normally the authoritative one.
        return valid[-1]

    excerpt = repr(output[:400])
    raise ValueError(
        "could not find a valid packed replay in get_demo.py output. "
        f"First 400 characters of stdout: {excerpt}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="00-0", help="first level (default: 00-0)")
    parser.add_argument("--end", default="99-4", help="last level (default: 99-4)")
    parser.add_argument("--levels-file", type=Path, help="N levels database; default: external/N v1.4 + NReality levels.txt")
    parser.add_argument("--force", action="store_true", help="overwrite existing CSVs")
    parser.add_argument("--timeout", type=float, default=90, help="timeout in seconds per get_demo.py call")
    parser.add_argument("--fields", help="comma-separated fields, e.g. frame,x,y,vx,vy; default: all")
    parser.add_argument("--no-simulate-enemies", action="store_true", help="disable enemy simulation")
    args = parser.parse_args(argv)

    try:
        first, last = level_index(args.start), level_index(args.end)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if first > last:
        parser.error("--start must not be after --end")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    fields = [value.strip() for value in args.fields.split(",")] if args.fields else None
    if fields is not None and any(not value for value in fields):
        parser.error("--fields contains an empty field")

    fetcher = ROOT / "get_demo.py"
    if not fetcher.is_file():
        parser.error(f"missing get_demo.py at {fetcher}")
    if not OPTIMIZER_DIR.is_dir():
        parser.error(f"missing optimiser directory at {OPTIMIZER_DIR}")

    sys.path.insert(0, str(OPTIMIZER_DIR))
    from nv14_dump import dump_player_data_csv
    from nv14_ltm import LEVEL_DATABASE_NAME, find_level_record
    from nv14_native import require_native
    from nv14_replay import parse_combined_level_replay

    levels_file = args.levels_file or ROOT / "external" / LEVEL_DATABASE_NAME
    if not levels_file.is_file():
        parser.error(f"levels file not found: {levels_file} (pass --levels-file)")
    try:
        native = require_native()
        if not native.backend_info().get("player_dump_abi"):
            raise RuntimeError("player dump ABI unavailable")
    except RuntimeError as exc:
        parser.error(f"{exc}; run python3 build_native.py inside 'optimiser/'")

    DESTINATION.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    failures: list[tuple[str, str]] = []
    count = last - first + 1
    for i, number in enumerate(range(first, last + 1), 1):
        level_id = f"{number // 5:02d}-{number % 5}"
        output = DESTINATION / f"{level_id}.csv"
        if output.is_file() and not args.force:
            skipped += 1
            print(f"[{i}/{count}] {level_id}: already exists (skip)", flush=True)
            continue
        try:
            fetched = subprocess.run(
                [sys.executable, str(fetcher), level_id], cwd=ROOT,
                capture_output=True, text=True, timeout=args.timeout, check=False,
            )
            if fetched.returncode != 0:
                detail = (fetched.stderr or fetched.stdout).strip()
                raise RuntimeError(f"get_demo.py exited with {fetched.returncode}: {detail[-400:]}")
            demo = packed_demo(fetched.stdout)
            record = find_level_record(levels_file, level_id)
            level = parse_combined_level_replay(record + "0:#").level_string
            result = dump_player_data_csv(
                level, demo, output, fields=fields,
                simulate_enemies=not args.no_simulate_enemies,
            )
            written += 1
            print(f"[{i}/{count}] {level_id}: {result.rows} rows ({result.stop_reason})", flush=True)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            failures.append((level_id, str(exc)))
            print(f"[{i}/{count}] {level_id}: FAILED: {exc}", file=sys.stderr, flush=True)

    log_path = DESTINATION / "failed_levels.txt"
    if failures:
        log_path.write_text("".join(f"{level}: {reason}\n" for level, reason in failures), encoding="utf-8")
        print(f"Failures written to {log_path}", file=sys.stderr)
    elif log_path.exists():
        log_path.unlink()
    print(f"Finished: {written} CSVs written, {skipped} skipped, {len(failures)} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted; rerun to resume without overwriting completed CSVs.", file=sys.stderr)
        raise SystemExit(130)
