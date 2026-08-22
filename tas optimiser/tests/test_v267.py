from __future__ import annotations

from pathlib import Path

import optimize_replay as opt
from nv14_engine import InputFrame, parse_level_string


def _open_air_level():
    return parse_level_string("0" * (31 * 23) + "|5^100,100")


def _frame_bits(frames):
    return [(frame.left, frame.right, frame.jump) for frame in frames]


def test_mixed_window_shape_starts_sparse_and_alternates_every_pass() -> None:
    logs: list[str] = []

    opt.optimise_local_windows(
        _open_air_level(),
        [InputFrame() for _ in range(6)],
        target_frame=5,
        range_start=0,
        range_end=5,
        objective_name="max-x",
        window_size=2,
        passes=4,
        minimum_improvement=float("inf"),
        local_inputs="direction",
        window_shape="mixed",
        window_span=4,
        windows_per_pass=2,
        seed=314159,
        workers=1,
        progress=logs.append,
    )

    pass_headers = [
        line
        for line in logs
        if line.startswith("forward, pass ")
        and (": sampled " in line or line.endswith("window order"))
    ]
    assert pass_headers == [
        "forward, pass 1: sampled 2 sparse windows (max span 4); "
        "forward window order",
        "forward, pass 2: forward window order",
        "forward, pass 3: sampled 2 sparse windows (max span 4); "
        "forward window order",
        "forward, pass 4: forward window order",
    ]
    assert any(
        "pass 1: no replay changes; continuing because the next pass uses "
        "contiguous windows" in line
        for line in logs
    )
    assert any(
        "pass 2: no replay changes; continuing because sparse windows are "
        "sampled next pass" in line
        for line in logs
    )


def test_mixed_window_shape_toml_accepts_sparse_pass_controls(tmp_path: Path) -> None:
    config = tmp_path / "mixed.toml"
    config.write_text(
        """
[local]
window_shape = "mixed"
window_span = 6
windows_per_pass = 3
passes = 4
seed = 12345
""",
        encoding="utf-8",
    )

    args = opt.parse_arguments(
        ["local", "input.txt", "--config", str(config)]
    )

    assert args.window_shape == "mixed"
    assert args.window_span == 6
    assert args.windows_per_pass == 3
    assert args._mode_configs.local == opt.LocalConfig(
        window_shape="mixed",
        window_span=6,
        windows_per_pass=3,
        passes=4,
        seed=12345,
    )


def test_seeded_mixed_window_shape_matches_parallel_window_search() -> None:
    level = _open_air_level()
    frames = [InputFrame() for _ in range(9)]
    kwargs = dict(
        target_frame=8,
        range_start=0,
        range_end=8,
        objective_name="max-x",
        window_size=3,
        passes=4,
        local_inputs="direction",
        window_order="forward",
        window_shape="mixed",
        window_span=6,
        windows_per_pass=5,
        seed=267,
        progress=None,
    )

    serial, serial_result = opt.optimise_local_windows(
        level, frames, workers=1, **kwargs
    )
    parallel, parallel_result = opt.optimise_local_windows(
        level, frames, workers=3, **kwargs
    )

    assert parallel_result.score == serial_result.score
    assert parallel_result.state.state_key() == serial_result.state.state_key()
    assert _frame_bits(parallel) == _frame_bits(serial)


def test_seeded_mixed_random_trajectories_match_multiprocessing() -> None:
    level = _open_air_level()
    frames = [InputFrame() for _ in range(8)]
    kwargs = dict(
        target_frame=7,
        range_start=0,
        range_end=7,
        objective_name="max-x",
        window_size=2,
        passes=3,
        local_inputs="direction",
        window_order="random",
        window_shape="mixed",
        window_span=5,
        windows_per_pass=4,
        restarts=3,
        seed=267267,
        progress=None,
    )

    serial, serial_result = opt.optimise_local_windows(
        level, frames, workers=1, **kwargs
    )
    parallel, parallel_result = opt.optimise_local_windows(
        level, frames, workers=2, **kwargs
    )

    assert parallel_result.score == serial_result.score
    assert parallel_result.state.state_key() == serial_result.state.state_key()
    assert _frame_bits(parallel) == _frame_bits(serial)
