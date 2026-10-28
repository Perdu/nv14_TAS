"""Verify and benchmark the paired TAS corpus used for Auto regressions.

Examples:
    python -m tools.benchmark_autonomous \
        examples/benchmark/Improved_TASes.txt --verify-only
    python -m tools.benchmark_autonomous \
        examples/benchmark/Improved_TASes.txt --tick 343 \
        --iterations 200 --beam 32 --seed 0
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import time
from pathlib import Path

from nv14_auto import (
    AUTO_REPAIR_SEARCH_ORDER_RANDOM,
    AUTO_REPAIR_SEARCH_ORDERS,
    AutoConfig,
    evaluate_replay_with_sentinel,
    optimise_autonomous,
)
from nv14_engine import parse_level_string
from nv14_replay import (
    decode_complex_replay,
    editable_frames,
    parse_combined_level_replay,
)


def load_corpus(path: Path) -> list[tuple[int, str]]:
    """Return ``(declared_tick, combined_record)`` rows from the pair file."""
    rows: list[tuple[int, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        declared, separator, record = raw.partition(": ")
        if separator and declared.isdigit():
            rows.append((int(declared), record))
    if not rows:
        raise ValueError(f"no 'TICK: $record' rows found in {path}")
    return rows


def verified_row(
    declared: int,
    record: str,
    *,
    simulate_enemies: bool,
) -> tuple[object, object, object]:
    combined = parse_combined_level_replay(record)
    level = parse_level_string(
        combined.level_string,
        strict_shapes=True,
        simulate_enemies=simulate_enemies,
    )
    replay = decode_complex_replay(combined.replay_string)
    frames = editable_frames(replay.frames)
    evaluation = evaluate_replay_with_sentinel(level, frames)
    if (
        len(frames) != declared
        or evaluation.finish_tick != declared
        or not evaluation.valid
    ):
        raise ValueError(
            f"{combined.name or '<unnamed>'}: declared {declared}, "
            f"encoded {len(frames)}, observed {evaluation.finish_tick}, "
            f"dead={evaluation.dead_tick}, unsupported={evaluation.unsupported}"
        )
    return combined, level, replay


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify or benchmark the current Auto optimiser against an "
            "Improved TASes pair file."
        )
    )
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument(
        "--tick",
        type=int,
        help="declared source tick to optimise after corpus verification",
    )
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--beam", type=int, default=32)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-retime", type=int, default=3)
    parser.add_argument("--no-deterministic", action="store_true")
    parser.add_argument("--repair-local-steps", type=int, default=1_000)
    parser.add_argument(
        "--repair-search-order",
        choices=AUTO_REPAIR_SEARCH_ORDERS,
        default=AUTO_REPAIR_SEARCH_ORDER_RANDOM,
    )
    parser.add_argument("--campaign-local-steps", type=int, default=10_000)
    parser.add_argument(
        "--no-enemies",
        action="store_true",
        help="use the exploratory enemy-disabled model instead of full fidelity",
    )
    args = parser.parse_args()

    rows = load_corpus(args.corpus)
    selected = None
    verified: list[dict[str, object]] = []
    for declared, record in rows:
        combined, level, replay = verified_row(
            declared,
            record,
            simulate_enemies=not args.no_enemies,
        )
        verified.append({"name": combined.name, "tick": declared})
        if args.tick == declared:
            selected = (combined, level, replay)

    payload: dict[str, object] = {
        "verified_records": len(verified),
        "enemy_simulation": not args.no_enemies,
        "records": verified,
    }
    if not args.verify_only:
        if args.tick is None:
            parser.error("--tick is required unless --verify-only is used")
        if selected is None:
            parser.error(f"no corpus row has declared tick {args.tick}")
        combined, level, replay = selected
        started = time.perf_counter()
        result = optimise_autonomous(
            level,
            replay.frames,
            AutoConfig(
                iterations=args.iterations,
                beam_width=args.beam,
                max_retime=args.max_retime,
                seed=args.seed,
                deterministic_phase=not args.no_deterministic,
                repair_local_limit=args.repair_local_steps,
                repair_search_order=args.repair_search_order,
                repair_campaign_local_limit=args.campaign_local_steps,
            ),
        )
        payload["benchmark"] = {
            "name": combined.name,
            "baseline_tick": result.baseline_finish_tick,
            "finish_tick": result.finish_tick,
            "elapsed_seconds": time.perf_counter() - started,
            "iterations": args.iterations,
            "beam": args.beam,
            "seed": args.seed,
            "deterministic_phase": not args.no_deterministic,
            "repair_local_steps": args.repair_local_steps,
            "repair_search_order": args.repair_search_order,
            "campaign_local_steps": args.campaign_local_steps,
            "winning_mutations": result.best.mutations,
            "stats": dataclasses.asdict(result.stats),
        }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
