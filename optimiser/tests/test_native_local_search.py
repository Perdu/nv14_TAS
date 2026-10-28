from __future__ import annotations

import ctypes
import inspect
from dataclasses import replace

import pytest

import nv14_search
from nv14_engine import APP_NUM_GRIDROWS, InputFrame, parse_level_string
from nv14_objectives import evaluate, objective_function, target_from_point
from nv14_search import (
    ALL_INPUT_CHOICES,
    INTERACTION_GOLD,
    INTERACTION_LOCKED_DOOR,
    OBJECTIVE_MAX_X,
    OBJECTIVE_MIN_DISTANCE,
    OBJECTIVE_MIN_Y,
    InteractionAtomSpec,
    InteractionGroupSpec,
    NativeSearchSession,
    SearchSpec,
    backend_info,
    build_direction_choices,
)


EMPTY_MAP = "0" * (31 * 23)


def _open_air_level():
    return parse_level_string(EMPTY_MAP + "|5^100,100")


def _native_session(level):
    info = backend_info()
    if not info.get("available"):
        pytest.skip(f"native replay-search kernel is unavailable: {info.get('error')}")
    return NativeSearchSession(level)


def _frame_bits(frames):
    return tuple((frame.left, frame.right, frame.jump) for frame in frames)


def _apply_result(frames, mutable_frames, result):
    candidate = list(frames)
    for frame_index, replacement in zip(
        mutable_frames, result.best_inputs, strict=True
    ):
        candidate[frame_index] = replacement
    return candidate


@pytest.mark.parametrize("local_inputs", ("direction", "all"))
def test_native_search_open_air_direction_and_all_input_golden(
    local_inputs: str,
) -> None:
    level = _open_air_level()
    frames = (InputFrame(), InputFrame(), InputFrame())
    mutable = (0, 1)
    objective = objective_function("max-x")
    incumbent = evaluate(level, frames, 2, objective)
    choices = (
        build_direction_choices(frames, mutable, "max-x")
        if local_inputs == "direction"
        else (ALL_INPUT_CHOICES,) * len(mutable)
    )
    spec = SearchSpec(
        mutable_frames=mutable,
        choices=choices,
        target_frame=2,
        objective=OBJECTIVE_MAX_X,
        incumbent_score=incumbent.score,
        incumbent_feasible=incumbent.feasible,
        prune_inactive_jump=local_inputs == "all",
    )

    result = _native_session(level).search(frames, spec)
    candidate = _apply_result(frames, mutable, result)
    direct = evaluate(level, candidate, 2, objective)

    assert result.improved
    assert _frame_bits(result.best_inputs) == (
        (False, True, False),
        (False, True, False),
    )
    assert result.score == 100.29600999999997
    assert result.score == direct.score
    assert result.player is not None
    assert result.player["pos"] == (
        direct.state.player.pos.x,
        direct.state.player.pos.y,
    )
    assert result.stats.evaluated_leaves == 9
    if local_inputs == "all":
        assert result.stats.inactive_jump_prunes == 12
    else:
        assert result.stats.inactive_jump_prunes == 0


def test_native_min_distance_has_exact_python_score_parity() -> None:
    level = parse_level_string(
        EMPTY_MAP + "|5^60.041353420929184,561.5839583070459"
    )
    target = target_from_point((84.0, 564.0))
    objective = objective_function("min-distance", target)
    frames = (InputFrame(),)
    incumbent = evaluate(level, frames, 0, objective)

    spec = SearchSpec(
        mutable_frames=(0,),
        # Horizontal acceleration changes oldpos but not pos on the first
        # airborne tick, so this candidate has exactly the incumbent score.
        choices=((InputFrame(right=True),),),
        target_frame=0,
        objective=OBJECTIVE_MIN_DISTANCE,
        targets=((84.0, 564.0),),
        incumbent_score=incumbent.score,
        incumbent_feasible=incumbent.feasible,
    )
    session = _native_session(level)
    result = session.search(frames, spec)
    forced_result = session.search(
        frames,
        replace(spec, incumbent_feasible=False),
    )
    direct = evaluate(level, (InputFrame(right=True),), 0, objective)

    assert incumbent.score == direct.score == result.score
    assert result.score == -579.1516908550279
    assert not result.improved
    assert forced_result.improved
    assert forced_result.score == direct.score


@pytest.mark.parametrize(
    ("local_inputs", "expected_inputs"),
    (
        ("direction", ((False, True, False), (False, True, False))),
        ("all", ((False, True, False), (True, False, False))),
    ),
)
def test_native_search_sparse_fixed_gap_preserves_choice_order_and_fixed_input(
    local_inputs: str,
    expected_inputs: tuple[tuple[bool, bool, bool], ...],
) -> None:
    level = _open_air_level()
    frames = (InputFrame(), InputFrame(left=True), InputFrame())
    mutable = (0, 2)
    objective = objective_function("max-x")
    incumbent = evaluate(level, frames, 2, objective)
    choices = (
        build_direction_choices(frames, mutable, "max-x")
        if local_inputs == "direction"
        else (ALL_INPUT_CHOICES,) * len(mutable)
    )
    spec = SearchSpec(
        mutable_frames=mutable,
        choices=choices,
        target_frame=2,
        objective=OBJECTIVE_MAX_X,
        incumbent_score=incumbent.score,
        incumbent_feasible=True,
        prune_inactive_jump=local_inputs == "all",
    )

    result = _native_session(level).search(frames, spec)
    candidate = _apply_result(frames, mutable, result)
    direct = evaluate(level, candidate, 2, objective)

    assert _frame_bits(result.best_inputs) == expected_inputs
    assert candidate[1] == frames[1]
    assert result.score == 100.09800999999999
    assert result.score == direct.score
    assert result.stats.evaluated_leaves == 9


@pytest.mark.parametrize("local_inputs", ("direction", "all"))
def test_native_search_exact_dedup_and_session_reuse(local_inputs: str) -> None:
    tiles = ["0"] * (31 * 23)
    for tile_y in range(23):
        tiles[4 * APP_NUM_GRIDROWS + tile_y] = "1"
    level = parse_level_string("".join(tiles) + "|5^110,132")
    frames = tuple(InputFrame() for _ in range(5))
    mutable = (0, 1, 2, 3)
    incumbent = evaluate(level, frames, 4, objective_function("max-x"))
    choices = (
        build_direction_choices(frames, mutable, "max-x")
        if local_inputs == "direction"
        else (ALL_INPUT_CHOICES,) * len(mutable)
    )
    spec = SearchSpec(
        mutable_frames=mutable,
        choices=choices,
        target_frame=4,
        objective=OBJECTIVE_MAX_X,
        incumbent_score=incumbent.score,
        incumbent_feasible=True,
        prune_inactive_jump=local_inputs == "all",
    )
    session = _native_session(level)

    first = session.search(frames, spec)
    second = session.search(frames, spec)

    assert not first.improved
    assert first.score == 110.0
    assert _frame_bits(first.best_inputs) == _frame_bits(frames[:4])
    assert first.stats.deduplicated_prunes > 0
    assert first.stats.cloned_states > 0
    assert first == second


def test_native_search_session_invalidates_changed_and_earlier_prefixes() -> None:
    level = _open_air_level()
    objective = objective_function("max-x")
    session = _native_session(level)

    def run(
        frames: tuple[InputFrame, ...], mutable: tuple[int, ...]
    ):
        incumbent = evaluate(level, frames, 7, objective)
        spec = SearchSpec(
            mutable_frames=mutable,
            choices=build_direction_choices(frames, mutable, "max-x"),
            target_frame=7,
            objective=OBJECTIVE_MAX_X,
            incumbent_score=incumbent.score,
            incumbent_feasible=incumbent.feasible,
            skip_unchanged_final_step=True,
        )
        reused = session.search(frames, spec)
        fresh = _native_session(level).search(frames, spec)
        assert reused == fresh

    baseline = tuple(InputFrame() for _ in range(8))
    run(baseline, (4, 5))

    # A change before the cached frame invalidates the stored prefix.
    early_change = list(baseline)
    early_change[1] = InputFrame(right=True)
    run(tuple(early_change), (4, 5))

    # Asking for an earlier search frame also rebuilds from the level start.
    run(tuple(early_change), (2, 3))

    # A suffix-only change retains the prefix but must still affect the search.
    late_change = list(early_change)
    late_change[6] = InputFrame(left=True)
    run(tuple(late_change), (4, 5))


def test_native_search_distinguishes_explicit_and_derived_jump_triggers() -> None:
    tiles = ["0"] * (31 * 23)
    tiles[4 * APP_NUM_GRIDROWS + 5] = "1"
    level = parse_level_string("".join(tiles) + "|5^132,134")
    frames = (InputFrame(jump=True, jump_trigger=False), InputFrame())
    objective = objective_function("min-y")
    incumbent = evaluate(level, frames, 1, objective)

    result = _native_session(level).search(
        frames,
        SearchSpec(
            mutable_frames=(0,),
            # Same held bits, but None derives the real rising edge. It is a
            # changed candidate even though left/right/jump compare equal.
            choices=((InputFrame(jump=True),),),
            target_frame=1,
            objective=OBJECTIVE_MIN_Y,
            incumbent_score=incumbent.score,
            incumbent_feasible=incumbent.feasible,
        ),
    )

    assert result.improved
    assert result.best_inputs == (InputFrame(jump=True),)
    assert result.score > incumbent.score


def test_native_search_physics_pruning_preserves_winner_and_reduces_work() -> None:
    level = _open_air_level()
    frames = tuple(InputFrame() for _ in range(8))
    mutable = tuple(range(5))
    incumbent = evaluate(level, frames, 7, objective_function("max-x"))
    common = dict(
        mutable_frames=mutable,
        choices=build_direction_choices(frames, mutable, "max-x"),
        target_frame=7,
        objective=OBJECTIVE_MAX_X,
        incumbent_score=incumbent.score,
        incumbent_feasible=True,
    )
    session = _native_session(level)

    exact = session.search(frames, SearchSpec(**common, physics_prune=False))
    pruned = session.search(frames, SearchSpec(**common, physics_prune=True))

    assert pruned.best_inputs == exact.best_inputs
    assert pruned.score == exact.score == 102.42123748364067
    assert pruned.stats.physics_prunes > 0
    assert pruned.stats.simulated_ticks < exact.stats.simulated_ticks
    assert pruned.stats.evaluated_leaves < exact.stats.evaluated_leaves


def test_native_physics_pruning_can_repair_an_infeasible_finite_incumbent() -> None:
    level = _open_air_level()
    frames = (InputFrame(), InputFrame())
    common = dict(
        mutable_frames=(0,),
        choices=build_direction_choices(frames, (0,), "max-x"),
        target_frame=1,
        objective=OBJECTIVE_MAX_X,
        # Generic callers are allowed to carry a diagnostic finite score for
        # an infeasible incumbent. Feasibility must still outrank that score.
        incumbent_score=1e100,
        incumbent_feasible=False,
    )
    session = _native_session(level)

    exact = session.search(frames, SearchSpec(**common, physics_prune=False))
    pruned = session.search(frames, SearchSpec(**common, physics_prune=True))

    assert exact.improved and pruned.improved
    assert pruned.best_inputs == exact.best_inputs
    assert pruned.score == exact.score


def test_native_search_rejects_nonfinite_targets_and_invalid_door_ids() -> None:
    with pytest.raises(ValueError, match="target coordinates must be finite"):
        SearchSpec(
            mutable_frames=(0,),
            choices=((InputFrame(),),),
            target_frame=0,
            objective=OBJECTIVE_MIN_DISTANCE,
            targets=((float("inf"), 0.0),),
        )

    level = parse_level_string(
        EMPTY_MAP + "|5^100,100!9^100,100,0,1,20,20,0,0,0"
    )
    frames = (InputFrame(),)
    invalid_door = InteractionGroupSpec(
        (InteractionAtomSpec(INTERACTION_LOCKED_DOOR, 1 << 32),)
    )
    with pytest.raises(ValueError, match="interaction or jump constraints"):
        _native_session(level).search(
            frames,
            SearchSpec(
                mutable_frames=(0,),
                choices=((InputFrame(left=True),),),
                target_frame=0,
                objective=OBJECTIVE_MAX_X,
                required_groups=(invalid_door,),
                incumbent_missing_requirements=frozenset((0,)),
                incumbent_score=100.0,
                incumbent_feasible=True,
            ),
        )

    with pytest.raises(ValueError, match="jump-preserving choices"):
        _native_session(_open_air_level()).search(
            (InputFrame(),),
            SearchSpec(
                mutable_frames=(0,),
                choices=(ALL_INPUT_CHOICES,),
                target_frame=0,
                objective=OBJECTIVE_MAX_X,
                incumbent_score=100.0,
                incumbent_feasible=True,
                physics_prune=True,
            ),
        )


def test_native_search_constraints_support_masks_above_64_bits() -> None:
    # Indices 0..63 stay distant, while the two high-word identities straddle
    # the player. The winner must collect required gold:65 without touching
    # forbidden gold:64 even though that sacrifices max-x score.
    distant = [f"0^{300 + index % 5},{300 + index // 5}" for index in range(64)]
    objects = "!".join((*distant, "0^116.05,100", "0^83.95,100"))
    level = parse_level_string(EMPTY_MAP + "|5^100,100!" + objects)
    frames = (InputFrame(), InputFrame())
    mutable = (0,)
    incumbent = evaluate(level, frames, 1, objective_function("max-x"))
    required = InteractionGroupSpec((InteractionAtomSpec(INTERACTION_GOLD, 65),))
    avoided = InteractionGroupSpec((InteractionAtomSpec(INTERACTION_GOLD, 64),))
    spec = SearchSpec(
        mutable_frames=mutable,
        choices=build_direction_choices(frames, mutable, "max-x"),
        target_frame=1,
        objective=OBJECTIVE_MAX_X,
        required_groups=(required,),
        avoided_groups=(avoided,),
        incumbent_missing_requirements=frozenset((0,)),
        incumbent_score=incumbent.score,
        incumbent_feasible=True,
    )

    result = _native_session(level).search(frames, spec)
    candidate = _apply_result(frames, mutable, result)
    direct = evaluate(level, candidate, 1, objective_function("max-x"))

    assert result.improved
    assert result.best_inputs == (InputFrame(left=True),)
    assert not result.missing_requirement_indices
    assert not result.violated_avoidance_indices
    assert direct.state.static_state.collected_gold_mask == 1 << 65


def test_native_search_module_contains_policy_only_not_a_python_dfs() -> None:
    source = inspect.getsource(nv14_search)

    assert "def recurse" not in source
    assert "copy_on_write_objects" not in source
    assert ".state_key()" not in source
    assert "Generic Python policy types" in source


def test_native_c_result_lifecycle_rejects_dirty_reuse() -> None:
    info = backend_info()
    if not info.get("available"):
        pytest.skip(f"native replay-search kernel is unavailable: {info.get('error')}")

    class ResultPrefix(ctypes.Structure):
        _fields_ = (
            ("abi_version", ctypes.c_uint32),
            ("struct_size", ctypes.c_uint32),
            ("improved", ctypes.c_uint8),
            ("feasible", ctypes.c_uint8),
            ("reserved", ctypes.c_uint8 * 6),
            ("score", ctypes.c_double),
            ("best_inputs", ctypes.c_void_p),
        )

    library = ctypes.CDLL(str(info["module_file"]))
    initialise = library.nv14_search_result_init
    initialise.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
    initialise.restype = ctypes.c_int
    run = library.nv14_search_run
    run.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    run.restype = ctypes.c_int
    destroy = library.nv14_search_result_destroy
    destroy.argtypes = (ctypes.c_void_p,)
    destroy.restype = None

    storage = ctypes.create_string_buffer(4096)
    pointer = ctypes.cast(storage, ctypes.c_void_p)
    result = ResultPrefix.from_buffer(storage)
    assert initialise(pointer, len(storage)) == 1

    assert result.abi_version == nv14_search.SEARCH_ABI_VERSION
    assert result.struct_size == len(storage)
    assert result.best_inputs is None

    # An invalid specification leaves an initialized result safe to destroy.
    assert run(None, None, pointer, None) == 1
    assert result.best_inputs is None

    # Owned storage from an undestroyed result is rejected, not overwritten.
    result.best_inputs = 1
    assert run(None, None, pointer, None) == 1
    assert result.best_inputs == 1
    result.best_inputs = None
    destroy(pointer)
    destroy(pointer)
    assert result.abi_version == nv14_search.SEARCH_ABI_VERSION
    assert result.best_inputs is None

    # Caller sizing prevents a newer library from touching bytes that do not
    # exist in an older result layout; run/destroy reject that short buffer.
    short_storage = (ctypes.c_uint8 * 32)(*([0xA5] * 32))
    short_pointer = ctypes.cast(short_storage, ctypes.c_void_p)
    assert initialise(short_pointer, 4) == 0
    assert bytes(short_storage) == bytes([0xA5] * 32)
    assert initialise(short_pointer, 8) == 1
    assert bytes(short_storage)[8:] == bytes([0xA5] * 24)
    assert run(None, None, short_pointer, None) == 1
    before_destroy = bytes(short_storage)
    destroy(short_pointer)
    assert bytes(short_storage) == before_destroy


def test_missing_native_search_has_actionable_build_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(nv14_search, "_search_native", None)
    monkeypatch.setattr(
        nv14_search,
        "_SEARCH_LOAD_ERROR",
        ImportError("synthetic missing extension"),
    )

    assert nv14_search.backend_info()["available"] is False
    with pytest.raises(RuntimeError, match=r"python build_native\.py"):
        nv14_search.NativeSearchSession(_open_air_level())


def test_stale_native_search_abi_has_actionable_build_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StaleSearchModule:
        __file__ = "/synthetic/_nv14_search.so"

        @staticmethod
        def backend_info():
            return {"wrapper_api": 1, "search_abi": 0, "core_abi": 1}

    monkeypatch.setattr(nv14_search, "_search_native", StaleSearchModule())

    info = nv14_search.backend_info()
    assert info["available"] is False
    assert info["backend"] == "incompatible"
    assert (
        "expected wrapper/search/core ABI "
        f"{nv14_search.SEARCH_WRAPPER_API}/"
        f"{nv14_search.SEARCH_ABI_VERSION}/"
        f"{nv14_search.SEARCH_CORE_ABI_VERSION}"
        in str(info["error"])
    )
    with pytest.raises(RuntimeError, match=r"python build_native\.py"):
        nv14_search.NativeSearchSession(_open_air_level())
