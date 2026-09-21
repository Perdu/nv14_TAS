from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import nv14_auto_parallel as parallel
import optimize_replay as opt
from nv14_auto import evaluate_replay_with_sentinel, verify_trimmed_replay
from nv14_checkpoint import read_auto_checkpoint
from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    parse_level_string,
)
from nv14_replay import (
    decode_complex_replay,
    editable_frames,
    encode_complex_replay,
    parse_combined_level_replay,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_source(
    path: Path, *, idle: int = 105, padded: bool = False, gold: str = ""
) -> int:
    tiles = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for column in range(APP_NUM_GRIDCOLS):
        tiles[column * APP_NUM_GRIDROWS + 5] = "1"
    level_text = f"{''.join(tiles)}|5^60,134!{gold}11^140,134,60,134"
    frames = [InputFrame()] * idle + [InputFrame(right=True)] * 80
    evaluation = evaluate_replay_with_sentinel(
        parse_level_string(level_text, simulate_enemies=False), frames
    )
    assert evaluation.valid and evaluation.finish_tick == idle + 29
    if not padded:
        frames = frames[:evaluation.finish_tick]
    path.write_text(
        f"$Auto range#tests##{level_text}#{encode_complex_replay(frames)}#\n",
        encoding="utf-8",
    )
    return evaluation.finish_tick


def _command(source: Path, output: Path, *args: str) -> list[str]:
    return [
        sys.executable, str(ROOT / "optimize_replay.py"), "auto", str(source),
        "--workers", "1", "--iterations", "1", "--beam", "2",
        "--max-retime", "1", "--no-simulate-enemies", "--seed", "123",
        "--output", str(output), *args,
    ]


def _run(source: Path, output: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        _command(source, output, *args), cwd=ROOT, capture_output=True,
        text=True, timeout=60, check=False,
    )


def _verify_output(path: Path) -> int:
    combined = parse_combined_level_replay(path.read_text(encoding="utf-8"))
    packed = decode_complex_replay(combined.replay_string)
    verified = verify_trimmed_replay(
        parse_level_string(combined.level_string, simulate_enemies=False),
        editable_frames(packed.frames), expected_finish_tick=packed.tick_count,
    )
    assert verified.valid and verified.finish_tick == packed.tick_count
    return packed.tick_count


@pytest.mark.parametrize("workers", [1, 2])
@pytest.mark.parametrize("via_toml", [False, True])
@pytest.mark.parametrize("objective", ["speedrun", "highscore"])
def test_open_range_survives_shorter_later_rounds(
    tmp_path: Path, workers: int, via_toml: bool, objective: str
) -> None:
    source, output = tmp_path / "source.txt", tmp_path / "output.txt"
    gold = "0^100,134!" if objective == "highscore" else ""
    assert _write_source(source, gold=gold) == 134
    if via_toml:
        config = tmp_path / "auto.toml"
        config.write_text('[auto]\nrange = "100: "\n', encoding="utf-8")
        range_args = ["--config", str(config)]
    else:
        range_args = ["--range", "100: "]

    completed = _run(
        source, output, *range_args, "--auto-runs", "3",
        "--workers", str(workers), "--auto-objective", objective,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "rounds=3/3" in completed.stdout
    assert _verify_output(output) < 134


@pytest.mark.parametrize("range_spec", ["100:", " 100: ", "0:", ":"])
@pytest.mark.parametrize(
    "objective,gold,extra_args",
    [
        ("speedrun", "", []),
        ("highscore", "", []),
        ("highscore", "0^100,134!", []),  # Every gold collected: no extra ticks.
        ("highscore", "0^35,134!", []),  # Missing gold: extra search workspace.
        ("highscore", "0^100,134!", ["--auto-max-extra-ticks", "80"]),
    ],
)
def test_open_range_resolves_after_trimming_and_highscore_workspace_selection(
    tmp_path: Path, range_spec: str, objective: str, gold: str,
    extra_args: list[str],
) -> None:
    source, output = tmp_path / "padded.txt", tmp_path / "output.txt"
    _write_source(source, padded=True, gold=gold)

    completed = _run(
        source, output, "--range", range_spec, "--iterations", "0",
        "--auto-objective", objective, *extra_args,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert _verify_output(output) == 134


def test_open_range_accepts_a_shorter_starting_parent(tmp_path: Path) -> None:
    source, parent = tmp_path / "source.txt", tmp_path / "parent.txt"
    output = tmp_path / "output.txt"
    _write_source(source)
    _write_source(parent, idle=103)

    completed = _run(
        source, output, "--range", "100:", "--auto-parent", str(parent),
        "--iterations", "0",
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "2 unique starting parent(s)" in completed.stdout
    assert _verify_output(output) == 132


@pytest.mark.parametrize("range_spec", ["100:120", ":120", "120"])
def test_numeric_ranges_remain_valid(tmp_path: Path, range_spec: str) -> None:
    source, output = tmp_path / "source.txt", tmp_path / "output.txt"
    _write_source(source, padded=True)
    completed = _run(source, output, "--range", range_spec, "--iterations", "0")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert _verify_output(output) == 134


@pytest.mark.parametrize(
    "range_spec,message",
    [
        ("100:134", "auto mutation range must stay within the verified replay body"),
        ("140:", "auto mutation range must stay within the verified replay body"),
        ("100:90", "range must satisfy"),
        ("-1:", "range must satisfy"),
        ("100:1000", "range cannot end after the target frame"),
        ("100:110,120:130", "multiple optimisation ranges are only supported by local"),
    ],
)
def test_invalid_ranges_are_not_clamped(
    tmp_path: Path, range_spec: str, message: str
) -> None:
    source, output = tmp_path / "source.txt", tmp_path / "output.txt"
    _write_source(source, padded=True)
    completed = _run(
        source, output, f"--range={range_spec}", "--iterations", "0"
    )
    assert completed.returncode != 0
    assert message in completed.stderr
    assert not output.exists()


def test_open_range_is_preserved_across_checkpoint_resume(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    source, output = tmp_path / "source.txt", tmp_path / "output.txt"
    checkpoint = tmp_path / "campaign.json"
    _write_source(source)
    command = _command(
        source, output, "--range", "100:", "--auto-runs", "3",
        "--auto-checkpoint", str(checkpoint),
    )
    real_write = parallel._write_auto_campaign_checkpoint

    def interrupt_after_commit(*args, **kwargs):
        real_write(*args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(parallel, "_write_auto_campaign_checkpoint", interrupt_after_commit)
    monkeypatch.setattr(sys, "argv", command[1:])
    with pytest.raises(KeyboardInterrupt):
        opt.main()
    saved = read_auto_checkpoint(checkpoint)
    assert saved["state"]["completed_runs"] == 1
    saved_config = saved["identity"]["configuration"]["auto_config"]
    assert saved_config["range_start"] == 100
    assert saved_config["range_end"] is None
    assert _verify_output(output) < 134
    capsys.readouterr()

    monkeypatch.setattr(parallel, "_write_auto_campaign_checkpoint", real_write)
    monkeypatch.setattr(sys, "argv", [*command[1:], "--auto-resume"])
    opt.main()

    stdout = capsys.readouterr().out
    assert "committed round 1" in stdout
    assert "rounds=3/3" in stdout
    assert read_auto_checkpoint(checkpoint)["state"]["completed_runs"] == 3
    assert _verify_output(output) < 134
