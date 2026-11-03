"""Verified splice-to-suffix grafting shared by reference and archive propagation.

A seam is just a *proposal*, not proof. Only canonically completed, replayed
movies whose persistent controls survive can be offered to the optimiser.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

from nv14_auto import evaluate_replay_with_sentinel, verify_trimmed_replay
from nv14_engine import InputFrame, Level
from nv14_random_splice import _control_preserved, _mask_preserved
from nv14_replay import editable_frames


def verified_suffix_grafts(
    level: Level, prefix: Sequence[InputFrame], reference: Sequence[InputFrame],
    *, seam_frame: int, lookback: int = 32, max_results: int = 4,
) -> tuple[tuple[InputFrame, ...], ...]:
    """Try matching prefix states to nearby reference ticks and verify joins.

    Does not assume a join is valid merely because (x,y) match. Retains only
    independently replayed canonical completions that preserve reference
    switches, doors, and other persistent controls. No inputs are interpolated.
    """
    if lookback < 1 or max_results < 1:
        return ()
    candidate = tuple(editable_frames(prefix))
    reference = tuple(editable_frames(reference))
    probe = evaluate_replay_with_sentinel(level, candidate)
    original = evaluate_replay_with_sentinel(level, reference)
    if not original.valid or original.finish_tick != len(reference):
        return ()
    options: list[tuple[float, int, int]] = []
    low = max(1, seam_frame - lookback)
    high = min(seam_frame + lookback, len(candidate)-2)
    for tick in range(low, high+1):
        state = probe.point(tick)
        if state is None or state.dead or state.complete:
            continue
        for reference_tick in range(max(1, tick-lookback),
                                    min(len(reference)-2, tick+lookback)+1):
            old = original.point(reference_tick)
            if old is None or old.dead or old.complete:
                continue
            if (not _mask_preserved(old, state) or
                    state.player_state != old.player_state or
                    state.in_air != old.in_air or
                    state.near_wall != old.near_wall):
                continue
            dx = math.hypot(state.x-old.x, state.y-old.y)
            dv = math.hypot(state.vx-old.vx, state.vy-old.vy)
            if dx <= 4.0 and dv <= 0.5:
                options.append((dx+5*dv, tick, reference_tick))
    options.sort()
    accepted = []
    seen = set()
    for _distance, tick, reference_tick in options[:24]:
        joined = candidate[:tick+1] + reference[reference_tick+1:]
        if joined in seen:
            continue
        seen.add(joined)
        check = evaluate_replay_with_sentinel(level, joined)
        if not check.valid or check.finish_tick is None:
            continue
        trimmed = joined[:check.finish_tick]
        try:
            checked = verify_trimmed_replay(level, trimmed)
        except ValueError:
            continue
        if not _control_preserved(original, checked):
            continue
        accepted.append(trimmed)
        if len(accepted) == max_results:
            break
    return tuple(accepted)
