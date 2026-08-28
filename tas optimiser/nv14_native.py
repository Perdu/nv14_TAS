"""Safe loader for the optional native n v1.4 simulation core.

This module deliberately does not replace :mod:`nv14_engine`.  The C backend
has an independently versioned, capability-checked batch API; callers can use
it only for levels it reports as supported and retain the Python emulator as
the fidelity fallback.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any
import sys


try:
    import _nv14_native as _native
except (ImportError, OSError) as _load_error:
    _native = None
    _NATIVE_LOAD_ERROR: BaseException | None = _load_error
else:
    _NATIVE_LOAD_ERROR = None


NATIVE_CORE_AVAILABLE = _native is not None


def backend_info() -> dict[str, object]:
    """Return machine-readable availability and native ABI information."""
    if _native is None:
        return {
            "available": False,
            "backend": "python",
            "error": (
                None
                if _NATIVE_LOAD_ERROR is None
                else f"{type(_NATIVE_LOAD_ERROR).__name__}: {_NATIVE_LOAD_ERROR}"
            ),
        }
    info = dict(_native.backend_info())
    info.update(
        {
            "available": True,
            "backend": "native-core",
            "module_file": _native.__file__,
        }
    )
    return info


def require_native() -> Any:
    """Return the extension module or raise a useful build instruction."""
    if _native is None:
        detail = "" if _NATIVE_LOAD_ERROR is None else f": {_NATIVE_LOAD_ERROR}"
        raise RuntimeError(
            "the optional native core is unavailable; run "
            f"'{sys.executable} build_native.py' to build it{detail}"
        )
    return _native


def parse_level_string(
    level_string: str,
    *,
    strict_shapes: bool = True,
    simulate_enemies: bool = False,
) -> object:
    """Return a native ``NativeLevel`` when complete, else Python ``Level``.

    A native result is selected only when the C parser advertises complete-step
    coverage and a zero unsupported-object mask. Unsupported tiles, objects, or
    an unavailable extension take the ordinary ``nv14_engine`` parser path.
    Invalid input errors are propagated; they are not treated as a reason to
    switch implementations. Call :func:`is_native_level` to identify a result.
    """
    if _native is not None:
        try:
            return _native.parse_level_string(
                level_string,
                strict_shapes=strict_shapes,
                simulate_enemies=simulate_enemies,
            )
        except NotImplementedError:
            pass

    from nv14_engine import parse_level_string as parse_python_level

    return parse_python_level(
        level_string,
        strict_shapes=strict_shapes,
        simulate_enemies=simulate_enemies,
    )


def is_native_level(level: object) -> bool:
    """Return whether *level* is owned by the compiled native core."""
    return _native is not None and isinstance(level, _native.NativeLevel)


def simulate_batch(
    level_string: str,
    frames: Sequence[object],
    *,
    simulate_enemies: bool = False,
    stop_on_dead: bool = True,
    stop_on_complete: bool = False,
) -> dict[str, object]:
    """Run a supported replay prefix in C and return one compact result dict.

    Frames may be ``nv14_engine.InputFrame`` instances or four-item tuples in
    ``(left, right, jump, jump_trigger)`` order. The result contains the number
    consumed, the final step event, and the final player/static-state snapshot.
    This function deliberately has no silent Python fallback because the native
    result shape differs from ``nv14_engine.simulate``. Unsupported level
    features raise ``NotImplementedError`` so the caller can choose its own
    fallback and result adapter.
    """
    native = require_native()
    return native.simulate_batch(
        level_string,
        frames,
        simulate_enemies=simulate_enemies,
        stop_on_dead=stop_on_dead,
        stop_on_complete=stop_on_complete,
    )
