"""Small-section brute-force / beam-search harness for nv14_engine."""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from nv14_engine import (
    InputFrame,
    Level,
    Player,
    SimulationState,
    iter_actions,
    parse_level_string,
)


@dataclass(slots=True)
class Node:
    state: SimulationState
    inputs: tuple[InputFrame, ...]
    score: float

    @property
    def player(self) -> Player:
        return self.state.player


def distance_to_point(x: float, y: float) -> Callable[[Player], float]:
    def score(player: Player) -> float:
        return math.hypot(player.pos.x - x, player.pos.y - y)
    return score


def in_box(x0: float, y0: float, x1: float, y1: float) -> Callable[[Player], bool]:
    lo_x, hi_x = sorted((x0, x1))
    lo_y, hi_y = sorted((y0, y1))

    def goal(player: Player) -> bool:
        return lo_x <= player.pos.x <= hi_x and lo_y <= player.pos.y <= hi_y and not player.dead
    return goal


def beam_search(
    level: Level,
    *,
    max_frames: int,
    score_fn: Callable[[Player], float],
    goal_fn: Callable[[Player], bool] | None = None,
    beam_width: int = 50_000,
    dedupe_precision: int | None = None,
    actions: Iterable[InputFrame] | None = None,
) -> Node | None:
    """Search frame-by-frame, retaining the best states by ``score_fn``.

    For exact exhaustive search, set a sufficiently large beam width and
    ``dedupe_precision=None``. For reconnaissance, rounded deduplication and a
    smaller beam are much faster.
    """
    action_list = tuple(actions or iter_actions())
    start = level.initial_state()
    frontier = [Node(start, (), score_fn(start.player))]

    if goal_fn is not None and goal_fn(start.player):
        return frontier[0]

    for _frame_number in range(max_frames):
        best_by_state: dict[tuple, Node] = {}
        for node in frontier:
            for action in action_list:
                child = node.state.clone()
                child.step(action, level.tiles)
                if child.player.dead:
                    continue
                child_score = score_fn(child.player)
                candidate = Node(child, node.inputs + (action,), child_score)
                if goal_fn is not None and goal_fn(child.player):
                    return candidate
                key = child.state_key(precision=dedupe_precision)
                incumbent = best_by_state.get(key)
                if incumbent is None or child_score < incumbent.score:
                    best_by_state[key] = candidate

        frontier = sorted(best_by_state.values(), key=lambda n: n.score)[:beam_width]
        if not frontier:
            return None

    return frontier[0] if frontier else None


def compact_inputs(inputs: tuple[InputFrame, ...]) -> str:
    chars: list[str] = []
    for frame in inputs:
        h = "L" if frame.left else "R" if frame.right else "."
        chars.append(h + ("J" if frame.jump else "."))
    return " ".join(chars)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("level_file", type=Path, help="text file containing one raw n level string")
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--target-x", type=float, required=True)
    parser.add_argument("--target-y", type=float, required=True)
    parser.add_argument("--beam", type=int, default=50_000)
    parser.add_argument("--dedupe-precision", type=int)
    parser.add_argument(
        "--simulate-enemies",
        action="store_true",
        help=(
            "enable supported enemy simulation (currently floorguards, zap, laser and "
            "chaingun drones, homing launchers and gauss turrets)"
        ),
    )
    args = parser.parse_args()

    level_text = args.level_file.read_text(encoding="utf-8").strip()
    level = parse_level_string(
        level_text,
        simulate_enemies=args.simulate_enemies,
    )
    result = beam_search(
        level,
        max_frames=args.frames,
        score_fn=distance_to_point(args.target_x, args.target_y),
        beam_width=args.beam,
        dedupe_precision=args.dedupe_precision,
    )
    if result is None:
        raise SystemExit("no live states remained")
    print(f"score={result.score:.17g}")
    print(f"pos=({result.player.pos.x:.17g}, {result.player.pos.y:.17g})")
    print(f"vel=({result.player.vx:.17g}, {result.player.vy:.17g})")
    print(compact_inputs(result.inputs))


if __name__ == "__main__":
    main()
