"""Standalone Hybrid leaves launch-time inputs after the reached goal alone."""
from __future__ import annotations

import sys

from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_engine import InputFrame
from nv14_replay import (decode_complex_replay, editable_frames, encode_complex_replay,
                         parse_combined_level_replay)
from tests.test_random_splice import _baseline


def test_session_and_stage_outputs_keep_unedited_tail_after_early_arrival(tmp_path, monkeypatch):
    import nv14_user_splice as splices
    from nv14_cli import main

    level, _, _ = _baseline()
    # An initially delayed run; the candidate reaches the same region earlier.
    original = (InputFrame(),) * 5 + (InputFrame(right=True),) * 47
    faster = (InputFrame(right=True),) * 52
    goal = EndpointGoal(18, "earliest-arrival", target_region=(66, 250, 120, 145))
    new_arrival = EndpointEvaluator(level, goal).evaluate(faster)
    old_arrival = EndpointEvaluator(level, goal).evaluate(original)
    assert new_arrival.feasible and old_arrival.feasible
    assert new_arrival.frame < old_arrival.frame
    # This is the regression: a backend candidate rewrites every input after
    # its early arrival, even though its splice score cannot observe them.
    tampered = (faster[:new_arrival.frame + 1]
                + (InputFrame(left=True),) * (len(faster) - new_arrival.frame - 1))
    src = tmp_path / "input.txt"
    src.write_text(f"$test#author#{level.source_level_string}#"
                   f"{encode_complex_replay(original)}#\n")
    cfg = tmp_path / "goal.txt"
    cfg.write_text('[local]\nsearch="population"\nobjective="earliest-arrival"\n'
                   'target-frame=18\nrange="0:18"\ntarget-region="66:250,120:145"\n')

    def backend(_level, _branch, _stage, _config, _rng, **kw):
        kw["candidate_callback"](tampered, new_arrival.frame)
        return (), 1, 1

    monkeypatch.setattr(splices, "_search_stage", backend)
    monkeypatch.setattr(sys, "argv", ["optimize_replay.py", "hybrid", str(src),
        "--goal-config", str(cfg), "--output", str(tmp_path / "out.txt"),
        "--auto-runs", "1", "--workers", "1", "--no-propagation"])
    main()
    for name in ("out_goal.txt", "out_goal.session.txt"):
        path = tmp_path / name
        assert path.exists(), name
        combined = parse_combined_level_replay(path.read_text())
        saved = tuple(editable_frames(decode_complex_replay(combined.replay_string).frames))
        assert saved[:new_arrival.frame + 1] == tampered[:new_arrival.frame + 1]
        assert saved[new_arrival.frame + 1:] == original[new_arrival.frame + 1:]
        assert len(saved) == len(original)
