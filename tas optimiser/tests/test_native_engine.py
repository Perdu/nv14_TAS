from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.benchmark_engine import SCENARIO_PATHS
from tools.benchmark_native import measure_corpus_coverage, run_native_benchmark
from tools.compare_engines import (
    DifferentialHarness,
    NativeBackendUnavailable,
    NativeLevelUnsupported,
    compare_corpus,
    decode_raw_replay,
    load_native_module,
    load_reference_engine,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _native_or_skip():
    try:
        return load_native_module()
    except NativeBackendUnavailable as exc:
        pytest.skip(f"optional native engine is unavailable: {exc}")


def _combined_fields(path: Path) -> tuple[str, str]:
    fields = path.read_text(encoding="utf-8").strip().split("#")
    for index in range(len(fields) - 1):
        level_string = fields[index]
        replay_string = fields[index + 1]
        if (
            "|" in level_string
            and len(level_string.split("|", 1)[0]) == 31 * 23
            and replay_string.partition(":")[0].isdigit()
        ):
            return level_string, replay_string
    raise AssertionError(f"could not find level/replay fields in {path}")


def test_reference_engine_is_loaded_from_python_source() -> None:
    reference = load_reference_engine()

    assert Path(reference.__file__).resolve() == PROJECT_ROOT / "nv14_engine.py"
    assert reference.__name__ == "_nv14_python_reference"


def test_native_backend_advertises_complete_engine() -> None:
    native = _native_or_skip()
    info = native.backend_info()

    assert info["strict_fp"] is True
    assert info["complete_enemy_engine"] is True
    assert info["native_object_type_mask"] == (1 << 13) - 1
    assert info["native_tile_id_count"] == 34


def test_raw_decoder_does_not_canonicalise_trigger_bits() -> None:
    frame = decode_raw_replay("1:8")[0]

    assert frame.jump is False
    assert frame.jump_trigger is True


def test_native_parser_rejects_trailing_empty_object_entry() -> None:
    native = _native_or_skip()
    level_string = "0" * (31 * 23) + "|5^100,100!"

    with pytest.raises(ValueError, match="empty object entry"):
        native.parse_level_string(level_string)


def test_native_parser_matches_ignored_malformed_static_objects() -> None:
    native = _native_or_skip()
    level_string = (
        "0" * (31 * 23)
        + "|5^100,100!0^1!12^2,3,4!11^1,2"
    )

    level = native.parse_level_string(level_string)

    assert level.object_count == 4
    assert level.gold_count == 0
    assert level.mine_count == 0
    assert level.exit_count == 0


def test_native_parser_routes_unknown_drone_weapon_to_fallback() -> None:
    native = _native_or_skip()
    import nv14_native

    level_string = (
        "0" * (31 * 23)
        + "|5^100,100!6^120,120,0,1,99,0"
    )

    with pytest.raises(NotImplementedError):
        native.parse_level_string(level_string, simulate_enemies=True)
    fallback = nv14_native.parse_level_string(
        level_string,
        simulate_enemies=True,
    )
    assert nv14_native.is_native_level(fallback) is False


def test_completed_state_clears_tick_events_and_keys_include_frame() -> None:
    native = _native_or_skip()
    level_string = (
        "0" * (31 * 23)
        + "|5^23,100!11^25,100,23,100"
    )
    state = native.parse_level_string(level_string).initial_state()

    completion = state.step(False, False, False, False)
    first_key = state.state_key()
    after_completion = state.step(False, False, False, False)
    second_key = state.state_key()

    assert completion["opened_exit"] is True
    assert completion["level_complete"] is True
    assert after_completion["collected_gold"] is False
    assert after_completion["exploded_mine"] is False
    assert after_completion["opened_exit"] is False
    assert first_key.startswith(b"NV14KEY4")
    assert second_key != first_key


def test_static_heavy_state_key_omits_immutable_runtime_slots() -> None:
    native = _native_or_skip()
    gold = "!".join(f"0^{48 + index},96" for index in range(100))
    level_string = "0" * (31 * 23) + "|5^100,100!" + gold

    key = native.parse_level_string(level_string).initial_state().state_key()

    assert len(key) < 2_048


def test_native_matches_synthetic_replay_and_clone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = _native_or_skip()
    level_string = "0" * (31 * 23) + "|5^100,100!11^100,100,100,100"
    harness = DifferentialHarness(native_module=native)
    clone_calls = {"python": 0, "native": 0}
    reference_state_type = harness.reference.SimulationState
    original_reference_clone = reference_state_type.clone
    original_native_clone = harness.native.clone

    def counted_reference_clone(state):
        clone_calls["python"] += 1
        return original_reference_clone(state)

    def counted_native_clone(state):
        clone_calls["native"] += 1
        return original_native_clone(state)

    monkeypatch.setattr(reference_state_type, "clone", counted_reference_clone)
    monkeypatch.setattr(harness.native, "clone", counted_native_clone)

    result = harness.compare_replay(
        case_id="synthetic-trigger-and-exit",
        level_id="synthetic-trigger-and-exit",
        level_string=level_string,
        # Stored trigger=true while jump-held=false is deliberately
        # noncanonical and must reach NativeState.step unchanged.
        replay_string="1:8",
        clone_stride=1,
    )

    assert result.compared_ticks == 2
    assert result.completed is True
    assert result.dead_on_completion is False
    assert clone_calls == {"python": 2, "native": 2}


def test_native_boundary_thwomp_can_leave_dense_grid() -> None:
    native = _native_or_skip()
    # This reproduces the source's left-facing boundary-thwomp quirk.  Its
    # fall goal is three pixels to the right of its anchor; StartRaise then
    # combines movedir=-1 with dir.x=-1 and sends it right indefinitely.  The
    # Python grid accepts the resulting unbounded cell keys.  Native removes
    # the object from its bounded dense grid once it reaches cell 34 instead
    # of failing the whole evaluation.
    map_chars = ["0"] * (31 * 23)
    for tile_x in range(31):
        map_chars[tile_x * 23 + 5] = "1"
    level_string = "".join(map_chars) + "|8^24,108,2!5^47,134"
    tick_count = 520
    replay_string = (
        f"{tick_count}:"
        + "|".join("0" for _ in range((tick_count + 6) // 7))
    )

    result = DifferentialHarness(native_module=native).compare_replay(
        case_id="boundary-left-thwomp",
        level_id="boundary-left-thwomp",
        level_string=level_string,
        replay_string=replay_string,
        clone_stride=37,
    )

    assert result.compared_ticks == 521
    assert result.final_state_checksum == (
        "39509700b6245000fb5188b6d6d6eab06ec8201936a1e6dbb858d6c882a3c9bc"
    )
    assert result.completed is False


def test_native_supported_synthetic_benchmark_has_equal_checksums() -> None:
    native = _native_or_skip()

    report = run_native_benchmark(
        evaluations=1,
        repetitions=1,
        native_module=native,
    )

    assert report.frames_per_evaluation == 512
    assert report.python.runtime_checksum == report.native.runtime_checksum
    assert report.deterministic_state_checksum
    assert report.speedup > 0.0


def test_native_matches_all_seven_benchmark_replays_per_frame() -> None:
    native = _native_or_skip()
    harness = DifferentialHarness(native_module=native)

    results = []
    unsupported = 0
    for relative_path in SCENARIO_PATHS:
        level_string, replay_string = _combined_fields(PROJECT_ROOT / relative_path)
        try:
            result = harness.compare_replay(
                case_id=relative_path,
                level_id=relative_path,
                level_string=level_string,
                replay_string=replay_string,
                clone_stride=37,
            )
        except NativeLevelUnsupported:
            unsupported += 1
        else:
            results.append(result)

    assert len(results) + unsupported == 7
    assert all(result.completed for result in results)


def _verification_corpus_path() -> Path | None:
    configured = os.environ.get("NV14_VERIFICATION_CORPUS")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(
        PROJECT_ROOT.parent / "upload" / "nv14_replay_verification_corpus_1489.yml"
    )
    return next((path for path in candidates if path.is_file()), None)


def test_native_matches_supplied_1489_case_corpus_per_frame() -> None:
    native = _native_or_skip()
    corpus_path = _verification_corpus_path()
    if corpus_path is None:
        pytest.skip(
            "full corpus not available; set NV14_VERIFICATION_CORPUS to run it"
        )

    report = compare_corpus(
        corpus_path,
        clone_stride=0,
        progress_every=0,
        native_module=native,
    )

    assert report.corpus_cases == 1_489
    assert report.native_supported_cases + report.native_unsupported_cases == 1_489
    assert (
        report.native_supported_declared_input_ticks
        + report.native_unsupported_declared_input_ticks
        == 1_039_607
    )
    info = report.native_backend_info
    claims_complete_enemy_engine = bool(
        isinstance(info, dict) and info.get("complete_enemy_engine")
    )
    if claims_complete_enemy_engine:
        assert report.native_supported_cases == 1_489
        assert report.compared_ticks == 1_041_096
        assert report.completion_tick_deaths == 8


def test_native_corpus_coverage_totals_are_explicit() -> None:
    native = _native_or_skip()
    corpus_path = _verification_corpus_path()
    if corpus_path is None:
        pytest.skip(
            "full corpus not available; set NV14_VERIFICATION_CORPUS to run it"
        )

    coverage = measure_corpus_coverage(corpus_path, native_module=native)

    assert coverage.total_levels == 504
    assert coverage.supported_levels + coverage.unsupported_levels == 504
    assert coverage.total_cases == 1_489
    assert coverage.supported_cases + coverage.unsupported_cases == 1_489
    assert coverage.total_declared_input_ticks == 1_039_607
    assert (
        coverage.supported_declared_input_ticks
        + coverage.unsupported_declared_input_ticks
        == 1_039_607
    )
