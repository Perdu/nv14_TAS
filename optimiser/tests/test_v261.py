from __future__ import annotations

import sys

import pytest

import nv14_cli
import nv14_local
import optimize_replay as opt
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame, parse_level_string
from nv14_replay import (
    decode_complex_replay,
    editable_frames,
    encode_complex_replay,
    parse_combined_level_replay,
)


EMPTY_MAP = "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)


def _write_local_input(tmp_path, *, objects: str = ""):
    level_string = f"{EMPTY_MAP}|5^100,100"
    if objects:
        level_string += f"!{objects}"
    source = [InputFrame(), InputFrame()]
    input_path = tmp_path / "source.txt"
    input_path.write_text(
        f"$v2.61 checkpoint test#tests##{level_string}#"
        f"{encode_complex_replay(source)}#\n",
        encoding="utf-8",
    )
    return input_path


def _local_argv(input_path, output_path, replay_path=None):
    arguments = [
        "optimize_replay.py",
        "local",
        str(input_path),
        "--target-frame",
        "1",
        "--range",
        "0:0",
        "--window",
        "1",
        "--passes",
        "1",
        "--output",
        str(output_path),
    ]
    if replay_path is not None:
        arguments.extend(("--replay-output", str(replay_path)))
    return arguments


def test_invalid_local_checkpoint_does_not_overwrite_existing_outputs(
    tmp_path, monkeypatch
) -> None:
    input_path = _write_local_input(tmp_path)
    output_path = tmp_path / "optimised.txt"
    replay_path = tmp_path / "optimised.replay.txt"
    output_path.write_text("keep combined output\n", encoding="utf-8")
    replay_path.write_text("keep replay output\n", encoding="utf-8")

    def mismatched_optimise(
        level,
        _frames,
        *,
        target_frame,
        best_run_callback=None,
        **_kwargs,
    ):
        checkpoint_frames = [InputFrame(), InputFrame()]
        reported_frames = [InputFrame(right=True), InputFrame()]
        reported_evaluation = opt.evaluate(
            level,
            reported_frames,
            target_frame,
            opt.objective_function("max-x"),
        )
        run = opt.LocalSearchRunResult(
            checkpoint_frames,
            reported_evaluation,
            "mismatched worker result",
        )
        assert best_run_callback is not None
        assert best_run_callback(run) is False
        return checkpoint_frames, reported_evaluation

    monkeypatch.setattr(opt, "optimise_local_windows", mismatched_optimise)
    monkeypatch.setattr(
        sys,
        "argv",
        _local_argv(input_path, output_path, replay_path),
    )

    with pytest.raises(SystemExit) as caught:
        opt.main()

    message = str(caught.value)
    assert "packed replay player did not match" in message
    assert message.endswith("no output was written")
    assert output_path.read_text(encoding="utf-8") == "keep combined output\n"
    assert replay_path.read_text(encoding="utf-8") == "keep replay output\n"


def test_checkpoint_clean_verification_rechecks_interactions() -> None:
    level = parse_level_string(f"{EMPTY_MAP}|5^100,100!0^83.95,100")
    level.player.g = 0.0
    requirement = opt.resolve_interaction_requirement(level, "gold:0")
    collected_frames = [InputFrame(left=True), InputFrame()]
    collected_evaluation = opt.evaluate(
        level,
        collected_frames,
        1,
        opt.objective_function("max-x"),
        required_interactions=(requirement,),
    )
    assert not collected_evaluation.missing_interactions

    with pytest.raises(ValueError, match=r"lost required interaction.*gold:0"):
        nv14_cli._verify_packed_replay_for_output(
            level,
            [InputFrame(), InputFrame()],
            target_frame=1,
            objective=opt.objective_function("max-x"),
            expected_evaluation=collected_evaluation,
            x_window=None,
            y_window=None,
            required_interactions=(requirement,),
            python_resimulate=True,
        )


def test_valid_local_checkpoint_is_saved_before_interrupted_search(
    tmp_path, monkeypatch
) -> None:
    input_path = _write_local_input(tmp_path)
    output_path = tmp_path / "checkpointed.txt"
    replay_path = tmp_path / "checkpointed.replay.txt"
    expected_state_key = None

    def interrupting_optimise(
        level,
        _frames,
        *,
        target_frame,
        best_run_callback=None,
        **_kwargs,
    ):
        nonlocal expected_state_key
        checkpoint_frames = [InputFrame(right=True), InputFrame()]
        checkpoint_evaluation = opt.evaluate(
            level,
            checkpoint_frames,
            target_frame,
            opt.objective_function("max-x"),
        )
        expected_state_key = checkpoint_evaluation.state.state_key()
        run = opt.LocalSearchRunResult(
            checkpoint_frames,
            checkpoint_evaluation,
            "completed restart before interrupt",
        )
        assert best_run_callback is not None
        assert best_run_callback(run) is True
        assert output_path.exists()
        assert replay_path.exists()
        raise KeyboardInterrupt

    monkeypatch.setattr(opt, "optimise_local_windows", interrupting_optimise)
    monkeypatch.setattr(
        sys,
        "argv",
        _local_argv(input_path, output_path, replay_path),
    )

    with pytest.raises(KeyboardInterrupt):
        opt.main()

    combined = parse_combined_level_replay(output_path.read_text(encoding="utf-8"))
    assert replay_path.read_text(encoding="utf-8").strip() == combined.replay_string
    packed_frames = editable_frames(
        decode_complex_replay(combined.replay_string).frames
    )
    packed_evaluation = opt.evaluate(
        parse_level_string(combined.level_string),
        packed_frames,
        1,
        opt.objective_function("max-x"),
    )
    assert packed_evaluation.state.state_key() == expected_state_key


def test_final_rejection_reports_that_verified_checkpoint_remains(
    tmp_path, monkeypatch
) -> None:
    input_path = _write_local_input(tmp_path)
    output_path = tmp_path / "checkpointed.txt"
    valid_replay = encode_complex_replay(
        [InputFrame(right=True), InputFrame()]
    )

    def valid_then_invalid_optimise(
        level,
        _frames,
        *,
        target_frame,
        best_run_callback=None,
        **_kwargs,
    ):
        assert best_run_callback is not None
        valid_frames = [InputFrame(right=True), InputFrame()]
        valid_evaluation = opt.evaluate(
            level,
            valid_frames,
            target_frame,
            opt.objective_function("max-x"),
        )
        assert best_run_callback(
            opt.LocalSearchRunResult(
                valid_frames,
                valid_evaluation,
                "verified checkpoint",
            )
        ) is True

        invalid_frames = [InputFrame(), InputFrame()]
        mismatched_evaluation = opt.evaluate(
            level,
            [InputFrame(left=True), InputFrame()],
            target_frame,
            opt.objective_function("max-x"),
        )
        assert best_run_callback(
            opt.LocalSearchRunResult(
                invalid_frames,
                mismatched_evaluation,
                "invalid final winner",
            )
        ) is False
        return invalid_frames, mismatched_evaluation

    monkeypatch.setattr(opt, "optimise_local_windows", valid_then_invalid_optimise)
    monkeypatch.setattr(
        sys,
        "argv",
        _local_argv(input_path, output_path),
    )

    with pytest.raises(SystemExit) as caught:
        opt.main()

    assert str(caught.value).endswith(
        "the most recent verified local checkpoint remains on disk"
    )
    saved = parse_combined_level_replay(output_path.read_text(encoding="utf-8"))
    assert saved.replay_string == valid_replay


def test_rejected_checkpoint_candidate_does_not_hide_later_valid_candidate(
    monkeypatch,
) -> None:
    level = parse_level_string(f"{EMPTY_MAP}|5^100,100")
    frames = [InputFrame(), InputFrame()]
    scores = iter((300.0, 200.0))

    def fabricated_run(
        context,
        spec,
        _progress,
        *,
        improvement_progress=None,
        window_workers=1,
    ):
        del improvement_progress, window_workers
        return nv14_local.LocalSearchRunResult(
            list(context.original_frames),
            opt.Evaluation(
                next(scores),
                context.baseline.state.clone(),
                True,
            ),
            spec.label,
        )

    attempted: list[float] = []

    def accept_only_clean_candidate(run):
        attempted.append(run.evaluation.score)
        return run.evaluation.score != 300.0

    monkeypatch.setattr(nv14_local, "_execute_local_run", fabricated_run)
    _optimised, final_evaluation = nv14_local.optimise_local_windows(
        level,
        frames,
        target_frame=1,
        range_start=0,
        range_end=0,
        objective_name="max-x",
        window_size=1,
        passes=1,
        window_order="random",
        restarts=2,
        seed=261,
        workers=1,
        progress=None,
        best_run_callback=accept_only_clean_candidate,
    )

    assert attempted == [300.0, 200.0]
    assert final_evaluation.score == 300.0
