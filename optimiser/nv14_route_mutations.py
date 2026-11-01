"""Optional route-scale mutations for endpoint Auto (never Local search).

Each proposal retains the exact frame count and changes only the editable
inclusive range. Return None if the requested operation cannot apply; the
caller then uses its established Auto/Local proposal path.
"""
from __future__ import annotations

import random
from contextvars import ContextVar
from collections.abc import Sequence

from nv14_engine import InputFrame, Level
from nv14_replay import simulate_through_frame
from nv14_native import require_native


_CROSSOVER_SESSION: ContextVar[tuple[Level, object] | None] = ContextVar(
    "route_crossover_native_session", default=None)


def _crossover_session(level: Level):
    existing = _CROSSOVER_SESSION.get()
    if existing is not None and existing[0] is level:
        return existing[1]
    from nv14_search import NativeSearchSession
    session = NativeSearchSession(level)
    _CROSSOVER_SESSION.set((level, session))
    return session


def _native_route_module():
    """Do not run the slower Python operator when this build supports Cython."""
    try:
        extension = require_native()
    except RuntimeError:
        return None
    return extension if hasattr(extension, "route_structural_propose") else None

LOW = ("direction-flip", "gap-repair", "direction-simplify")
MEDIUM = LOW + ("boundary-shift", "jump-rewrite", "passage-rewrite")
HIGH = MEDIUM + ("state-crossover",)
PRESETS = {"low": LOW, "medium": MEDIUM, "high": HIGH}
ALL = frozenset(HIGH)


def parse_operators(value: object) -> str | tuple[str, ...]:
    """Validate a preset or explicit list (empty means original Hybrid only)."""
    if isinstance(value, str):
        name = value.strip().lower().replace("_", "-")
        if not name:
            return ()
        if name in PRESETS:
            return name
        # argparse accepts --auto-mutations=gap-repair,direction-flip
        if name in ALL:
            value = (name,)
        elif "," in name:
            value = name.split(",")
        else:
            raise ValueError(f"mutations must be low/medium/high or an operator list; got {value!r}")
    if not isinstance(value, (list, tuple)):
        raise ValueError("mutations must be low/medium/high or an operator list")
    result = tuple(str(item).strip().lower().replace("_", "-") for item in value)
    invalid = set(result) - ALL
    if invalid or len(set(result)) != len(result):
        raise ValueError(f"unknown or repeated Auto mutations {sorted(invalid or set(result))}; "
                         f"available: {', '.join(HIGH)}")
    return result


def operators(value: str | Sequence[str]) -> tuple[str, ...]:
    return PRESETS[value] if isinstance(value, str) else tuple(value)


def _direction(frame: InputFrame) -> int:
    return (1 if frame.right else 0) - (1 if frame.left else 0)


def _with_direction(frame: InputFrame, direction: int) -> InputFrame:
    return InputFrame(direction < 0, direction > 0, frame.jump, None)


def _replace_jump(frame: InputFrame, jump: bool) -> InputFrame:
    return InputFrame(frame.left, frame.right, jump, None)


def _matching_runs(frames: Sequence[InputFrame], start: int, end: int, minimum: int = 8
                   ) -> list[tuple[int, int, int]]:
    runs: list[tuple[int, int, int]] = []
    i = start
    while i <= end:
        d = _direction(frames[i])
        j = i + 1
        while j <= end and _direction(frames[j]) == d:
            j += 1
        if d and j - i >= minimum:
            runs.append((i, j, d))
        i = j
    return runs


def _boundary_shift(parent: Sequence[InputFrame], result: list[InputFrame],
                    rng: random.Random, start: int, end: int) -> bool:
    seams = [i for i in range(start + 1, end + 1)
             if _direction(parent[i - 1]) != _direction(parent[i])]
    if not seams:
        return False
    seam = rng.choice(seams)
    shift = rng.choice((-96, -64, -32, -16, -8, 8, 16, 32, 64, 96))
    new_seam = max(start + 1, min(end + 1, seam + shift))
    if new_seam == seam:
        return False
    direction = _direction(parent[seam - 1] if new_seam > seam else parent[seam])
    for i in range(min(seam, new_seam), max(seam, new_seam)):
        result[i] = _with_direction(result[i], direction)
    return True


def _jump_rewrite(parent: Sequence[InputFrame], result: list[InputFrame],
                  rng: random.Random, start: int, end: int) -> bool:
    # Move the whole contiguous held-jump interval without losing a release
    # needed before a later distinct press. Never edit the immutable edges.
    pulses: list[tuple[int, int]] = []
    i = start
    while i <= end:
        if not parent[i].jump or (i > 0 and parent[i - 1].jump):
            i += 1
            continue
        j = i + 1
        while j <= end and parent[j].jump:
            j += 1
        pulses.append((i, j))
        i = j
    if not pulses:
        return False
    left, right = rng.choice(pulses)
    if rng.randrange(4) == 0:
        # Delete an optional jump; the simulator decides feasibility.
        for i in range(left, right):
            result[i] = _replace_jump(result[i], False)
        return True
    width = right - left
    destination = max(start, min(end + 1 - width,
                                 left + rng.choice((-32, -16, -8, 8, 16, 32))))
    if destination == left:
        return False
    for i in range(left, right):
        result[i] = _replace_jump(result[i], False)
    for i in range(destination, destination + width):
        result[i] = _replace_jump(result[i], True)
    return True


def _passage_rewrite(parent: Sequence[InputFrame], result: list[InputFrame],
                     rng: random.Random, start: int, end: int) -> bool:
    # A passage is delimited by successive jump *presses*. Retain the jump
    # pattern but replace the directional program between two jump events.
    presses = [i for i in range(start, end + 1)
               if parent[i].jump and (i == 0 or not parent[i - 1].jump)]
    if len(presses) < 2:
        return False
    first, second = rng.sample(presses, 2)
    left, right = sorted((first, second))
    if right - left < 8:
        return False
    d = rng.choice((-1, 0, 1))
    for i in range(left, right):
        result[i] = _with_direction(result[i], d)
    return True


def _state_crossover(parent: Sequence[InputFrame], donor: Sequence[InputFrame],
                     result: list[InputFrame], rng: random.Random, start: int, end: int,
                     level: Level | None) -> bool:
    if level is None or donor == parent or end - start < 32:
        return False
    # Expensive preset: evaluate a handful of compatible physical seams and
    # join only where both routes are close in position/velocity and alive.
    count = min(4, end - start - 1)
    seams = rng.sample(range(start + 1, end), count)
    scored = []
    native = _native_route_module()
    if (native is not None and hasattr(native, "route_crossover_seam")
            and getattr(level, "source_level_string", None) is not None):
        # The native replay analyser computes *both* trajectories once, then
        # checks all candidate join points in C. The Python reference below is
        # retained for platforms without the compiled extension.
        session = _crossover_session(level)
        # Only simulate through the latest requested seam; later replay frames
        # cannot affect any physical state being considered.
        needed = max(seams)
        pa = session.evaluate_replay(parent[:needed], trace_stride=1)
        pb = session.evaluate_replay(donor[:needed], trace_stride=1)
        seam = native.route_crossover_seam(pa, pb, seams)
        if seam is None or _direction(parent[seam - 1]) != _direction(donor[seam - 1]):
            return False
        result[seam:end + 1] = donor[seam:end + 1]
        return True
    for seam in seams:
        pa = simulate_through_frame(level, parent, seam - 1).player
        pb = simulate_through_frame(level, donor, seam - 1).player
        if pa.dead or pb.dead or pa.in_air != pb.in_air or pa.state != pb.state:
            continue
        distance = (pa.pos.x - pb.pos.x)**2 + (pa.pos.y - pb.pos.y)**2
        velocity = ((pa.pos.x - pa.oldpos.x) - (pb.pos.x - pb.oldpos.x))**2 + (
            (pa.pos.y - pa.oldpos.y) - (pb.pos.y - pb.oldpos.y))**2
        # Do not pretend a route segment from a distant position or very
        # different velocity can simply be grafted onto the other trajectory.
        if distance > 24.0**2 or velocity > 1.5**2:
            continue
        scored.append((distance + 20.0 * velocity, seam))
    if not scored:
        return False
    _, seam = min(scored)
    if _direction(parent[seam - 1]) != _direction(donor[seam - 1]):
        # Avoid discontinuity in held direction exactly at the seam.
        return False
    result[seam:end + 1] = donor[seam:end + 1]
    return True


def propose(name: str, parent: tuple[InputFrame, ...], *, rng: random.Random,
            start: int, end: int, donor: tuple[InputFrame, ...] | None = None,
            level: Level | None = None) -> tuple[InputFrame, ...] | None:
    """One route-scale proposal, bound to the original editable interval."""
    if not 0 <= start <= end < len(parent):
        raise ValueError("invalid route mutation range")
    native = _native_route_module() if name != "state-crossover" else None
    if native is not None:
        return native.route_structural_propose(name, parent, rng, start, end)
    result = list(parent)
    if name == "direction-flip":
        runs = _matching_runs(parent, start, end)
        if not runs:
            return None
        left, right, direction = rng.choice(runs)
        # Invert either the full run or a large contiguous portion of it.
        if right - left > 32 and rng.randrange(2):
            length = rng.randint(16, right - left)
            left = rng.randint(left, right - length)
            right = left + length
        for i in range(left, right):
            result[i] = _with_direction(result[i], -direction)
    elif name in ("gap-repair", "direction-simplify"):
        limit = 6 if name == "gap-repair" else 12
        gaps = []
        for i in range(start + 1, end):
            direction = _direction(parent[i - 1])
            if not direction or _direction(parent[i]) == direction:
                continue
            j = i + 1
            while j <= end and _direction(parent[j]) != direction and j - i < limit:
                j += 1
            if j <= end and _direction(parent[j]) == direction and j > i:
                if name == "gap-repair" and any(_direction(parent[k]) != 0 for k in range(i, j)):
                    continue
                gaps.append((i, j, direction))
        if not gaps:
            return None
        left, right, direction = rng.choice(gaps)
        for i in range(left, right):
            result[i] = _with_direction(result[i], direction)
    elif name == "boundary-shift":
        if not _boundary_shift(parent, result, rng, start, end):
            return None
    elif name == "jump-rewrite":
        if not _jump_rewrite(parent, result, rng, start, end):
            return None
    elif name == "passage-rewrite":
        if not _passage_rewrite(parent, result, rng, start, end):
            return None
    elif name == "state-crossover":
        if not _state_crossover(parent, donor or parent, result, rng, start, end, level):
            return None
    else:
        raise ValueError(f"unknown Auto mutation operator {name!r}")
    changed = tuple(result)
    return changed if changed != parent else None
