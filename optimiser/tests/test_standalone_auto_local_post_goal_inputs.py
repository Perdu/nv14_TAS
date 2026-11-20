"""Standalone Auto and Local must not publish backend edits after goal arrival."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import nv14_cli as cli
from nv14_endpoint import EndpointEvaluator, EndpointGoal, verify_endpoint
from nv14_engine import InputFrame
from nv14_population import PopulationCandidate, PopulationResult
from nv14_replay import (
    decode_complex_replay, editable_frames, encode_complex_replay,
    parse_combined_level_replay,
)
from tests.test_random_splice import _baseline


def _case():
    level, _, _ = _baseline()
    original = (InputFrame(),) * 5 + (InputFrame(right=True),) * 47
    faster = (InputFrame(right=True),) * 52
    goal = EndpointGoal(18, "earliest-arrival", target_region=(66, 250, 120, 145))
    baseline = EndpointEvaluator(level, goal).evaluate(original)
    improvement = EndpointEvaluator(level, goal).evaluate(faster)
    assert baseline.feasible and improvement.feasible and improvement.frame < baseline.frame
    # This is an otherwise valid result but the search has vandalised the tail.
    # Mutate only the editable part of the post-arrival interval. The original
    # tail beyond target_frame is already immutable to both backends.
    tampered = (faster[:improvement.frame + 1]
                + (InputFrame(left=True),) * (goal.target_frame - improvement.frame)
                + original[goal.target_frame + 1:])
    assert verify_endpoint(level, tampered, goal, expected=improvement).feasible
    return level, original, goal, baseline, improvement, tampered


@pytest.mark.parametrize("mode", ("auto", "local"))
@pytest.mark.parametrize("survival", (0, 3))
def test_live_and_final_checkpoint_preserve_invocation_tail(tmp_path, monkeypatch, mode, survival):
    from dataclasses import replace
    level, original, goal, baseline, improvement, tampered = _case()
    goal = replace(goal, survive_after_goal=survival)
    baseline = EndpointEvaluator(level, goal).evaluate(original)
    improvement = EndpointEvaluator(level, goal).evaluate(tampered)
    assert improvement.feasible and improvement.frame < baseline.frame
    src = tmp_path / "source.txt"
    src.write_text(f"$test#author#{level.source_level_string}#"
                   f"{encode_complex_replay(original)}#\n")
    output = tmp_path / "result.txt"
    # Inspect files at the time the live callback returns, before the final write.
    callback_saved = []

    if mode == "auto":
        def stub(_level, _input, _goal, _config, *, best_callback, **_kwargs):
            best_callback(SimpleNamespace(frames=tampered, evaluation=improvement))
            callback_saved.append(output.read_text())
            return SimpleNamespace(evaluation=baseline), SimpleNamespace(
                frames=tampered, evaluation=improvement), 1
        monkeypatch.setattr(cli, "optimise_auto_endpoint_campaign", stub)
        mode_args = ["--auto-runs", "1", "--iterations", "1",
                     "--auto-survive-after-goal", str(survival)]
    else:
        import nv14_population
        def stub(_level, _input, *, goal, frame_ranges, config, best_callback, **_kwargs):
            candidate = PopulationCandidate(frames=tampered, evaluation=improvement)
            assert best_callback(candidate)
            callback_saved.append(output.read_text())
            return PopulationResult(candidates=(candidate,), baseline=baseline, rounds=1,
                                    evaluations=1, stagnant_rounds=0, worker_count=1, seed=1)
        monkeypatch.setattr(nv14_population, "optimise_local_population", stub)
        mode_args = ["--search", "population", "--rounds", "1", "--iterations", "1",
                     "--survive-after-goal", str(survival)]

    monkeypatch.setattr(sys, "argv", [
        "optimize_replay.py", mode, str(src), "--objective", "earliest-arrival",
        "--target-frame", "18", "--range", "0:18", "--target-region", "66:250,120:145",
        "--workers", "1", "--output", str(output), *mode_args,
    ])
    cli.main()
    assert callback_saved, "expected live checkpoint to be saved"
    for text in (*callback_saved, output.read_text()):
        restored = tuple(editable_frames(decode_complex_replay(
            parse_combined_level_replay(text).replay_string).frames))
        assert len(restored) == len(original)
        witness_end = improvement.frame + survival + 1
        assert restored[:witness_end] == tampered[:witness_end]
        assert restored[witness_end:] == original[witness_end:]
        assert verify_endpoint(level, restored, goal, expected=improvement).feasible
    assert src.read_text().endswith(f"{encode_complex_replay(original)}#\n")


def test_survival_window_is_kept_before_restoring_original_suffix():
    _, original, goal, _, improved, tampered = _case()
    from dataclasses import replace
    goal = replace(goal, survive_after_goal=3)
    preserved = cli._preserve_endpoint_post_goal_inputs(original, tampered, goal, improved.frame)
    assert preserved[:improved.frame + 4] == tampered[:improved.frame + 4]
    assert preserved[improved.frame + 4:] == original[improved.frame + 4:]


def test_velocity_window_is_fully_observed_before_restoring_original_suffix():
    _, original, _, _, _, tampered = _case()
    goal = EndpointGoal(18, "max-vx", velocity_frames=(10, 18))
    # Even if the best velocity was observed at frame 11, later observations
    # are needed to establish that it was the maximum for the whole interval.
    preserved = cli._preserve_endpoint_post_goal_inputs(original, tampered, goal, 11)
    assert preserved[:19] == tampered[:19]
    assert preserved[19:] == original[19:]


def test_fixed_frame_local_window_does_not_edit_the_post_target_tail(tmp_path, monkeypatch):
    level, original, _, _, _, _ = _case()
    source = tmp_path / "source.txt"
    source.write_text(f"$test#author#{level.source_level_string}#"
                      f"{encode_complex_replay(original)}#\n")
    output = tmp_path / "window.txt"
    monkeypatch.setattr(sys, "argv", [
        "optimize_replay.py", "local", str(source), "--search", "windows",
        "--objective", "max-x", "--target-frame", "18", "--range", "0:18",
        "--window", "4", "--passes", "1", "--restarts", "1",
        "--workers", "1", "--output", str(output),
    ])
    cli.main()
    saved = tuple(editable_frames(decode_complex_replay(
        parse_combined_level_replay(output.read_text()).replay_string).frames))
    assert saved[19:] == original[19:]
