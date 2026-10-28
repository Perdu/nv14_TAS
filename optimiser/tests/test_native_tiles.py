from __future__ import annotations

import pytest

from tools.compare_engines import (
    DifferentialHarness,
    NativeBackendUnavailable,
    RawInput,
    load_native_module,
)


_MAP_I = 15
_MAP_J = 11
_CENTRE_X = 12.0 + (_MAP_I + 1) * 24.0
_CENTRE_Y = 12.0 + (_MAP_J + 1) * 24.0
_OFFSETS = (
    (-18.0, -18.0),
    (0.0, -14.0),
    (18.0, -18.0),
    (-14.0, 0.0),
    (0.0, 0.0),
    (14.0, 0.0),
    (-18.0, 18.0),
    (0.0, 14.0),
    (18.0, 18.0),
)


def _native_or_skip():
    try:
        return load_native_module()
    except NativeBackendUnavailable as exc:
        pytest.skip(f"optional native engine is unavailable: {exc}")


@pytest.mark.parametrize("tile_id", range(34))
def test_native_circle_projection_matches_every_tile_family(tile_id: int) -> None:
    """Probe centre, axis and corner paths for every serialized tile ID."""
    native = _native_or_skip()
    harness = DifferentialHarness(native_module=native, simulate_enemies=False)
    map_chars = ["0"] * (31 * 23)
    map_chars[_MAP_I * 23 + _MAP_J] = chr(48 + tile_id)
    map_string = "".join(map_chars)
    neutral = RawInput(False, False, False, False)

    for offset_x, offset_y in _OFFSETS:
        level_string = (
            f"{map_string}|5^{_CENTRE_X + offset_x},{_CENTRE_Y + offset_y}"
        )
        reference_level, native_level = harness._levels(
            f"tile-{tile_id}-{offset_x}-{offset_y}",
            level_string,
        )
        reference_state = reference_level.initial_state()
        native_state = harness.native.initial_state(native_level)
        reference_state.step(
            harness.reference.InputFrame(False, False, False, False),
            reference_level.tiles,
        )
        harness.native.step(native_state, neutral)
        harness.native.compare_state(
            reference_state,
            native_state,
            case_id=f"tile-{tile_id}@{offset_x},{offset_y}",
            tick=0,
        )
