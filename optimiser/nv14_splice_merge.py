"""Verified splice-to-suffix grafting shared by reference and archive propagation.

A seam is just a *proposal*, not proof. Completed grafts must satisfy
canonical replay and persistent-control verification; intermediate-stage
grafts may retain only a death-free prefix for separate endpoint validation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from collections.abc import Sequence

from nv14_auto import evaluate_replay_with_sentinel, verify_trimmed_replay
from nv14_engine import InputFrame, Level
from nv14_random_splice import _control_preserved, _mask_preserved
from nv14_replay import editable_frames


def verified_suffix_grafts(
    level: Level, prefix: Sequence[InputFrame], reference: Sequence[InputFrame],
    *, seam_frame: int, lookback: int = 32, max_results: int = 4,
    completion_required: bool = True, min_prefix_frame: int = 1,
) -> tuple[tuple[InputFrame, ...], ...]:
    """Try matching prefix states to nearby reference ticks and verify joins.

    Does not assume a join is valid merely because (x,y) match. Retains only
    independently verified canonical completions when required, or live stage
    prefixes for separate endpoint validation. No inputs are interpolated.
    """
    if lookback < 1 or max_results < 1:
        return ()
    candidate = tuple(editable_frames(prefix))
    reference = tuple(editable_frames(reference))
    probe = evaluate_replay_with_sentinel(level, candidate)
    original = evaluate_replay_with_sentinel(level, reference)
    if completion_required:
        if not original.valid or original.finish_tick != len(reference):
            return ()
    elif original.dead_tick is not None and original.finish_tick is None:
        # A replay that dies *after* a useful stage remains a valid source of
        # inputs. Its physical trace cannot supply a live seam beyond death,
        # but deleting its later inputs would permanently destroy downstream
        # continuation instructions when the joined movie is saved as a stage
        # checkpoint. Filter dead/terminal seam states below instead of
        # shortening the reference replay.
        if original.dead_tick <= 2:
            return ()
    options: list[tuple[float, int, int]] = []
    low = max(1, min_prefix_frame, seam_frame - lookback)
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
        if check.valid and check.finish_tick is not None:
            trimmed = joined[:check.finish_tick]
            try:
                checked = verify_trimmed_replay(level, trimmed)
            except ValueError:
                continue
        elif not completion_required:
            # A death after the checkpoint must not discard the checkpoint.
            # Verify a live prefix where needed, but return the *original*
            # joined replay below. Cutting at death and then neutral-padding
            # it in the coordinator used to erase every downstream input in
            # the saved stage LTM/TXT (and contaminate subsequent stage seeds).
            live = (joined[:max(0, check.dead_tick - 1)]
                    if check.dead_tick is not None else joined)
            if len(live) < 2:
                continue
            checked = evaluate_replay_with_sentinel(level, live)
            if checked.dead_tick is not None:
                continue
            trimmed = joined
        else:
            continue
        # A stage-only live prefix need not replay *future* control events.
        # But a fully completed graft retains the ordinary strict control
        # preservation requirement, even when offered to a stage helper.
        if (completion_required or checked.finish_tick is not None) and not _control_preserved(original, checked):
            continue
        accepted.append(trimmed)
        if len(accepted) == max_results:
            break
    return tuple(accepted)


@dataclass(frozen=True, slots=True)
class BridgeRepairResult:
    """Bounded endpoint searches and independently verified repaired grafts."""

    grafts: tuple[tuple[InputFrame, ...], ...]
    searches: int = 0
    evaluations: int = 0
    targets: int = 0
    endpoint_candidates: int = 0
    rejected_prefix: int = 0
    failure_reason: str = ""


def repair_backend_schedule(backend: str) -> tuple[str, ...]:
    """Hybrid's bounded bridge equivalent: one Auto phase then one Local phase.

    Hybrid's named-stage scheduler cannot run a temporary bridge goal directly.
    The normal Hybrid carries Auto candidates into Local; restart controls do
    not. All phases share the per-target repair_iterations budget.
    """
    if backend in ("both", "hybrid", "hybrid-restart"):
        return ("endpoint-auto", "local")
    if backend == "hybrid-local-control":
        return ("local", "local")
    if backend in ("endpoint-auto", "local"):
        return (backend,)
    raise ValueError(f"unsupported repair backend: {backend!r}")


def repair_suffix_grafts(
    level: Level, prefix: Sequence[InputFrame], reference: Sequence[InputFrame],
    *, seam_frame: int, config, window: int, targets: int,
    completion_required: bool, seed: int,
    local_search=None, protected_through: int | None = None,
    at_frame: int | None = None,
) -> BridgeRepairResult:
    """Repair a *bounded bridge* and try to graft the untouched saved suffix.

    Direct grafting compares two existing trajectories. This routine instead
    asks the ordinary endpoint Auto/Local engine to reach a nearby *reference
    state*, mutating only the last ``window`` frames of the proposed prefix.
    The endpoint target is guidance, NOT a permission to publish a seam: every
    joined replay still passes ``verified_suffix_grafts``'s full independent
    physics and persistent-control verification. Search work is capped by
    ``targets`` and by ``config.repair_iterations`` per selected backend; the
    ordinary Auto/Local stagnation settings are never inherited. For Hybrid,
    a bounded Auto-then-Local bridge shares candidate replays (not native search
    caches); the two restart controls remain independent. When a checkpoint's
    actual arrival frame is known, preserve all inputs up to that frame.
    """
    from dataclasses import replace
    import random
    from nv14_endpoint import EndpointGoal
    from nv14_random_splice import _local_search

    if window < 2 or targets < 1:
        return BridgeRepairResult((), failure_reason="invalid repair window/targets")
    if at_frame is not None and (type(at_frame) is not int or at_frame < 2):
        raise ValueError("at_frame must be an integer >= 2")
    modes = repair_backend_schedule(config.search_backend)
    search = _local_search if local_search is None else local_search
    reference = tuple(editable_frames(reference))
    candidate = tuple(editable_frames(prefix))
    reference_eval = evaluate_replay_with_sentinel(level, reference)
    if completion_required:
        if not reference_eval.valid or reference_eval.finish_tick != len(reference):
            return BridgeRepairResult((), failure_reason="reference is not a canonical completion")
    elif reference_eval.dead_tick is not None and reference_eval.finish_tick is None:
        # A reference that dies *later* may still supply valid earlier seam
        # states. Keep its full recorded input suffix: cropping it here used to
        # make otherwise useful repaired stage checkpoints lose all inputs
        # after the death. Target selection below excludes dead states, and
        # the final checkpoint is independently checked by the coordinator.
        if reference_eval.dead_tick <= 2:
            return BridgeRepairResult((), failure_reason="reference dies before a live suffix")
    if len(reference) < 5 or len(candidate) < 5:
        return BridgeRepairResult((), failure_reason="prefix or suffix is too short")
    prefix_eval = evaluate_replay_with_sentinel(level, candidate)
    live = (prefix_eval.dead_tick - 1 if prefix_eval.dead_tick is not None else
            prefix_eval.finish_tick - 2 if prefix_eval.finish_tick is not None else
            len(candidate) - 2)
    live = max(2, min(live, len(candidate) - 2))
    # A padded workspace can extend beyond a replay that already completed.
    # Never target an input after that actual completion: it cannot produce
    # a bridge from a live player and can cause endpoint backends to evaluate
    # a trimmed replay at a frame it does not contain. For incomplete/dead
    # prefixes retain the existing forward recovery window.
    target_limit = (live if prefix_eval.finish_tick is not None
                    else len(candidate) - 2)
    seam = max(2, min(seam_frame, live + max(2, window // 4), target_limit))

    # Unlike the old three-point scan, search across the available corridor
    # after the source's *actual* checkpoint arrival. Keeping that exact input
    # prefix is essential: a repaired 527 -> 599 must not buy reconnection by
    # giving back the ten frames gained at checkpoint 527.
    protected = max(-1, protected_through if protected_through is not None else -1)
    if at_frame is not None:
        if at_frame <= protected + 1:
            return BridgeRepairResult((), failure_reason=(
                f"requested repair frame {at_frame} is at/before protected checkpoint "
                f"{protected}; select a later frame"))
        if at_frame > target_limit:
            return BridgeRepairResult((), failure_reason=(
                f"requested repair frame {at_frame} exceeds live prefix frame "
                f"{target_limit}; cannot anchor repair there"))
        # An explicit frame is a *local* seam centre, not permission to scan
        # the whole later stage. The window still determines editable inputs
        # and reference search range; use a small bounded frame neighbourhood
        # for candidate seam ticks and guarantee that the centre is sampled.
        seam = at_frame
        radius = min(16, max(2, window // 4))
        first_tick = max(2, protected + 2, seam - radius)
        last_tick = min(target_limit, seam + radius)
        spacing = max(1, radius // 4)
        ticks = [seam, *range(first_tick, last_tick + 1, spacing),
                 first_tick, last_tick]
    else:
        first_tick = max(2, protected + 2, seam - window // 2)
        last_tick = min(target_limit, seam + window)
        spacing = max(3, window // 6)
        ticks = list(range(first_tick, last_tick + 1, spacing))
        ticks.extend((first_tick, max(first_tick, min(last_tick, seam)), last_tick))
    if first_tick > last_tick:
        return BridgeRepairResult((), failure_reason="no live editable corridor after protected checkpoint")
    # Sample candidate/reference pairs around each live tick. Match quality is
    # primary, but a reference tick behind the candidate loses frames and is
    # penalised heavily to favour preserving (not fabricating) the TAS gain.
    proposed: list[tuple[float, int, int]] = []
    for target_tick in dict.fromkeys(ticks):
        probe = prefix_eval.point(target_tick)
        if probe is None or probe.dead or probe.complete:
            continue
        first_ref = max(2, target_tick - window // 2)
        last_ref = min(len(reference) - 2, target_tick + window)
        stride = max(1, window // 12)
        for ref_tick in range(first_ref, last_ref + 1, stride):
            state = reference_eval.point(ref_tick)
            if state is None or state.dead or state.complete:
                continue
            dx = math.hypot(state.x - probe.x, state.y - probe.y)
            dv = math.hypot(state.vx - probe.vx, state.vy - probe.vy)
            # Do not rank a time-losing connection ahead of a slightly more
            # distant time-saving one solely on physical proximity.
            lost_frames = max(0, target_tick - ref_tick)
            proposed.append((dx + 3 * dv + 2 * lost_frames,
                             target_tick, ref_tick))
    proposed.sort()
    chosen: list[tuple[int, int]] = []
    seen_ticks: set[int] = set()
    for _distance, target_tick, ref_tick in proposed:
        if target_tick in seen_ticks:
            continue
        chosen.append((target_tick, ref_tick))
        seen_ticks.add(target_tick)
        if len(chosen) >= targets:
            break
    if not chosen:
        return BridgeRepairResult((), failure_reason="no live physical target anchors")

    rng = random.Random(seed)
    grafts: list[tuple[InputFrame, ...]] = []
    seen_grafts: set[tuple[InputFrame, ...]] = set()
    searches = evaluations = endpoint_candidates = rejected_prefix = 0
    for target_tick, ref_tick in chosen:
        target_state = reference_eval.point(ref_tick)
        if target_state is None:
            continue
        edit_start = max(0, target_tick - window, protected + 1)
        if edit_start >= target_tick:
            continue
        # The target rectangle is intentionally larger than the actual seam
        # tolerance. Position and velocity constraints guide mutations, while
        # full replay verification alone decides whether a bridge is usable.
        radius = 10.0
        goal = EndpointGoal(
            target_tick, 'earliest-arrival',
            target_region=(target_state.x - radius, target_state.x + radius,
                           target_state.y - radius, target_state.y + radius),
            arrival_start=max(0, target_tick - min(6, window // 4)),
        )
        # The configured repair-iterations is a bounded per-target budget,
        # not normal multi-round stagnation scheduling. A Hybrid repair runs
        # its complementary phases without invoking the named-stage scheduler.
        per_backend = max(1, config.repair_iterations // len(modes))
        handoff: list[tuple[InputFrame, ...]] = []
        for mode in modes:
            kwargs = dict(start=edit_start, editable_end=target_tick,
                          config=replace(config, search_backend=mode,
                                         splice_auto_stagnation_rounds=0,
                                         splice_local_stagnation_rounds=0,
                                         splice_stagnation_rounds=0),
                          iterations=per_backend, rounds=1,
                          seed=rng.getrandbits(63), include_partial=True)
            if config.search_backend == "hybrid":
                if handoff:
                    kwargs["initial_population"] = tuple(handoff[:12])
                if local_search is None:
                    kwargs["population_callback"] = lambda population: handoff.extend(
                        tuple(editable_frames(item)) for item in population)
            try:
                found, used = search(level, candidate, goal, **kwargs)
            except ValueError as exc:
                if not str(exc).startswith('the immutable prefix dies before the editable ranges'):
                    raise
                found, used = (), 0
            searches += 1
            evaluations += used
            endpoint_candidates += len(found)
            if config.search_backend == "hybrid":
                handoff.extend(tuple(editable_frames(frames)) for frames, _ in found[:12])
                handoff = list(dict.fromkeys(handoff))[:12]
            for frames, _frame in found[:12]:
                repaired = tuple(editable_frames(frames))
                if repaired[:edit_start] != candidate[:edit_start]:
                    rejected_prefix += 1
                    continue
                for graft in verified_suffix_grafts(
                    level, repaired, reference, seam_frame=target_tick,
                    lookback=min(window, 48), max_results=4,
                    completion_required=completion_required,
                    min_prefix_frame=max(1, protected + 1),
                ):
                    if graft not in seen_grafts:
                        grafts.append(graft)
                        seen_grafts.add(graft)
                        if len(grafts) >= 4:
                            return BridgeRepairResult(tuple(grafts), searches,
                                                      evaluations, len(chosen),
                                                      endpoint_candidates, rejected_prefix)
    reason = ("" if grafts else
              "no backend search launched" if not searches else
              "no endpoint candidates" if not endpoint_candidates else
              "all endpoint candidates changed the immutable prefix"
              if rejected_prefix >= endpoint_candidates else
              "no replay-verified graft")
    return BridgeRepairResult(tuple(grafts), searches, evaluations, len(chosen),
                              endpoint_candidates, rejected_prefix, reason)


def gain_aware_suffix_retimes(
    prefix: Sequence[InputFrame], reference: Sequence[InputFrame],
    *, prefix_arrival: int, reference_arrival: int,
    offsets: Sequence[int] = (0, -1, 1, -2, 2),
) -> tuple[tuple[int, tuple[InputFrame, ...]], ...]:
    """Deterministically advance a saved continuation by a verified frame lead.

    The checkpoint is aligned at its *actual earliest-arrival frame*, not at
    the nominal stage deadline. Keep the faster replay through that frame,
    and take all later held input states from the reference at its (later)
    arrival. Nearby reference-tick offsets provide a few alternate timing
    boundaries; they do not mutate or erase any of the checkpoint's prefix.

    Results are only **proposals**. The caller must replay, verify persistent
    controls, and compare objective ranks before saving anything. These raw
    inputs do not assert that physics states match at the seam.
    """
    fast = tuple(editable_frames(prefix))
    old = tuple(editable_frames(reference))
    if (type(prefix_arrival) is not int or type(reference_arrival) is not int or
            not 0 <= prefix_arrival < len(fast) or
            not 0 <= reference_arrival < len(old) - 1 or
            reference_arrival <= prefix_arrival):
        return ()
    result: list[tuple[int, tuple[InputFrame, ...]]] = []
    seen: set[tuple[InputFrame, ...]] = set()
    preserved = fast[:prefix_arrival + 1]
    for offset in offsets:
        if type(offset) is not int:
            raise ValueError("retime offsets must be integers")
        take_after = reference_arrival + offset
        if take_after < 0 or take_after >= len(old) - 1:
            continue
        # Do not include a fully old prefix with zero/negative time saving.
        # If the old suffix is already identical to the current fast suffix,
        # deduplicating avoids repeatedly verifying the same full replay.
        trial = preserved + old[take_after + 1:]
        if trial not in seen and trial != fast:
            result.append((offset, trial))
            seen.add(trial)
    return tuple(result)
