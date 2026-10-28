"""Inspect an n v1.4 combined level/replay at a selected frame."""
from __future__ import annotations

import argparse
from pathlib import Path

from nv14_engine import parse_level_string
from nv14_replay import (
    decode_complex_replay,
    input_symbol,
    parse_combined_level_replay,
    simulate_through_frame,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument(
        "--simulate-enemies",
        action="store_true",
        help=(
            "enable supported enemy simulation (currently floorguards, zap, laser and "
            "chaingun drones, homing launchers and gauss turrets)"
        ),
    )
    args = parser.parse_args()

    combined = parse_combined_level_replay(args.input.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    if args.frame < 0 or args.frame >= replay.tick_count:
        raise SystemExit(f"frame must be between 0 and {replay.tick_count - 1}")
    level = parse_level_string(
        combined.level_string,
        simulate_enemies=args.simulate_enemies,
    )
    state = simulate_through_frame(level, replay.frames, args.frame)
    player = state.player
    frame_input = replay.frames[args.frame]

    print(f"level: {combined.name} by {combined.author}")
    print(f"replay ticks: {replay.tick_count}")
    print(f"frame {args.frame} input: {input_symbol(frame_input)}")
    print(
        f"FRAME {args.frame} Position at start of traced frame: "
        f"{player.pos.x:.15f}, {player.pos.y:.15f}"
    )
    print(f"velocity: {player.vx:.15f}, {player.vy:.15f}")
    print(f"state: {player.state.name}")
    print(f"in_air={player.in_air} near_wall={player.near_wall} dead={player.dead}")


if __name__ == "__main__":
    main()
