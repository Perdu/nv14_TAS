from __future__ import annotations

import sys

import pytest

import nv14_cli
import optimize_replay as opt
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame
from nv14_replay import (
    decode_complex_replay,
    editable_frames,
    encode_complex_replay,
    parse_combined_level_replay,
)


EMPTY_MAP = "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)


def test_cli_saves_first_live_local_improvement_before_trajectory_finishes(
    tmp_path,
    monkeypatch,
) -> None:
    level_string = f"{EMPTY_MAP}|5^100,100"
    source_frames = [InputFrame() for _ in range(10)]
    input_path = tmp_path / "source.txt"
    output_path = tmp_path / "checkpointed.txt"
    input_path.write_text(
        f"$v2.66 live checkpoint test#tests##{level_string}#"
        f"{encode_complex_replay(source_frames)}#\n",
        encoding="utf-8",
    )

    original_atomic_write = nv14_cli._atomic_write_text
    writes = 0

    def interrupt_after_first_checkpoint(path, text):
        nonlocal writes
        original_atomic_write(path, text)
        writes += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(nv14_cli, "_atomic_write_text", interrupt_after_first_checkpoint)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "local",
            str(input_path),
            "--target-frame",
            "9",
            "--range",
            "0:9",
            "--window",
            "1",
            "--passes",
            "1",
            "--local-inputs",
            "direction",
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(KeyboardInterrupt):
        opt.main()

    assert writes == 1
    saved = parse_combined_level_replay(output_path.read_text(encoding="utf-8"))
    saved_frames = editable_frames(decode_complex_replay(saved.replay_string).frames)
    assert saved_frames[0].right
    assert not any(
        frame.left or frame.right or frame.jump
        for frame in saved_frames[1:]
    )

    level = opt.parse_level_string(level_string)
    objective = opt.objective_function("max-x")
    baseline = opt.evaluate(level, source_frames, 9, objective)
    checkpoint = opt.evaluate(level, saved_frames, 9, objective)
    assert checkpoint.score > baseline.score
