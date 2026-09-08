"""User-facing population workflows checked with independent Python physics."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from nv14_engine import InputFrame, parse_level_string
from nv14_ltm import LtmMovie
from nv14_replay import decode_complex_replay, encode_complex_replay, parse_combined_level_replay
from test_ltm import _basic_config, _member_bytes, _write_ltm


ROOT = Path(__file__).resolve().parents[1]
EMPTY_MAP = "0" * (31 * 23)


def _held(frames):
    return tuple((f.left, f.right, f.jump) for f in frames)


def _write_replay(path, frames, objects=""):
    level = EMPTY_MAP + "|5^100,100" + ("!" + objects if objects else "")
    path.write_text(
        f"$Population integration#tests##{level}#{encode_complex_replay(frames)}#\n",
        encoding="utf-8",
    )
    return level


def _read_replay(path):
    combined = parse_combined_level_replay(path.read_text(encoding="utf-8"))
    return combined.level_string, decode_complex_replay(combined.replay_string).frames


def _run(*args):
    completed = subprocess.run(
        [sys.executable, str(ROOT / "optimize_replay.py"), "local", *map(str, args)],
        cwd=ROOT, capture_output=True, text=True, timeout=40,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout


def _scan(level_string, frames):
    """Do not use EndpointEvaluator or verify_endpoint as an oracle."""
    level = parse_level_string(level_string, simulate_enemies=True)
    state = level.initial_state()
    rows = []
    for frame in frames:
        state.step(frame, level.tiles)
        player = state.player
        rows.append((player.pos.x, player.pos.y,
                     player.pos.x - player.oldpos.x,
                     player.pos.y - player.oldpos.y,
                     player.dead, state.static_state.level_complete,
                     state.static_state.collected_gold_mask))
        if player.dead:
            break
    return rows


def test_population_toml_sparse_ranges_velocity_and_diverse_ranked_outputs(tmp_path):
    source = tmp_path / "source.txt"
    original = [InputFrame()] * 100
    # Preserve simultaneous left/right and a held jump in an immutable gap.
    original[7] = InputFrame(left=True, right=True, jump=True)
    level = _write_replay(source, original, "0^100,100!0^300,100")
    config = tmp_path / "population.toml"
    config.write_text(
        '[local]\nsearch = "population"\nrange = ["2:5", "9:11"]\n'
        'target_frame = 14\nobjective = "min-x"\n'
        'vx_window = [-2.0, -0.05]\nvy_window = [1.0, 3.0]\n'
        'require_interaction = ["gold:0"]\navoid_interaction = ["gold:1"]\n'
        'iterations = 80\nbeam = 16\nrounds = 2\nworkers = 1\nseed = 41\n'
        'repair_steps = 8\nrepair_lookback = 50\nmutation_span = 40\ntop_results = 3\n',
        encoding="utf-8",
    )
    output = tmp_path / "optimised.txt"
    stdout = _run(source, "--config", config, "--output", output)
    assert "feasible outputs=3/3" in stdout
    assert "required interactions satisfied: gold:0" in stdout
    mutable = set(range(2, 6)) | set(range(9, 12))
    vectors = []
    for rank in range(1, 4):
        path = output if rank == 1 else tmp_path / f"optimised.rank{rank:02d}.txt"
        actual_level, frames = _read_replay(path)
        assert actual_level == level
        assert len(frames) == len(original)
        assert all(_held([frames[i]]) == _held([original[i]])
                   for i in range(len(original)) if i not in mutable)
        rows = _scan(level, frames)
        x, y, vx, vy, dead, complete, gold = rows[14]
        assert not dead and not complete
        assert -2 <= vx <= -0.05 and 1 <= vy <= 3
        assert gold == 1
        vectors.append((x, y, vx, vy))
        # The source has no exit, and the unchanged tail later dies out of bounds.
        assert rows[-1][4] and not rows[-1][5]
    assert len(set(vectors)) == 3
    assert [v[0] for v in vectors] == sorted(v[0] for v in vectors)
    assert vectors[0][0] < _scan(level, original)[14][0]


@pytest.mark.parametrize("workers", [1, 2])
def test_earliest_arrival_reports_first_tick_satisfying_velocity_not_endpoint(tmp_path, workers):
    source = tmp_path / "source.txt"
    original = [InputFrame(right=True)] * 100
    level = _write_replay(source, original)
    output = tmp_path / "arrival.txt"
    stdout = _run(
        source, "--search", "population", "--range", "2:25",
        "--target-frame", 25, "--objective", "earliest-arrival",
        "--target-region", "104:110,100:150", "--arrival-start", 2,
        "--vx-window", "1:2", "--iterations", 40, "--beam", 8,
        "--rounds", 1, "--workers", workers, "--seed", 7,
        "--repair-steps", 4, "--output", output,
    )
    _, frames = _read_replay(output)
    assert len(frames) == len(original)
    assert _held(frames[:2]) == _held(original[:2])
    assert _held(frames[26:]) == _held(original[26:])
    rows = _scan(level, frames)
    position_entries = [i for i, (x, y, *_rest) in enumerate(rows[:26])
                        if i >= 2 and 104 <= x <= 110 and 100 <= y <= 150]
    arrivals = [i for i, (x, y, vx, _vy, dead, *_rest) in enumerate(rows[:26])
                if i >= 2 and 104 <= x <= 110 and 100 <= y <= 150
                and 1 <= vx <= 2 and not dead]
    assert position_entries and arrivals
    assert arrivals[0] == 10
    assert position_entries[0] < arrivals[0]
    reported = re.search(r"  1\. frame=(\d+); score=([^;]+);", stdout)
    assert reported is not None
    assert int(reported[1]) == arrivals[0]
    assert float(reported[2]) == -arrivals[0]
    assert rows[-1][4] and not rows[-1][5]


def test_population_ltm_preserves_external_inputs_postroll_and_ranked_replays(tmp_path):
    level = EMPTY_MAP + "|5^100,100"
    record = f"$00-0 Population LTM#tests##{level}#"
    levels_file = tmp_path / "levels.txt"
    levels_file.write_text(record + "\n", encoding="utf-8")
    frames = [InputFrame()] * 11 + [InputFrame(right=True)]
    lines = ["|Mboot:0|", "|K20|Mboot:1|"]
    lines += [f"|{'Kff53|' if frame.right else ''}Mbody:{i}|" for i, frame in enumerate(frames)]
    lines += ["|K61|Mpost:0|", "|Mpost:1|"]
    source = _write_ltm(
        tmp_path / "00-0.ltm", ("\n".join(lines) + "\n").encode(),
        config=_basic_config(len(lines)),
        extra_members=(("inputs7", b"alternate branch\n"), ("notes.txt", b"manual TAS notes\n")),
    )
    output = tmp_path / "segment.ltm"
    packed = tmp_path / "segment.replay.txt"
    stdout = _run(
        source, "--search", "population", "--levels-file", levels_file,
        "--ltm-postroll", 2, "--range", "1:8", "--target-frame", 9,
        "--objective", "max-x", "--iterations", 60, "--beam", 12,
        "--rounds", 1, "--workers", 1, "--seed", 12,
        "--top-results", 2, "--repair-steps", 4,
        "--output", output, "--replay-output", packed,
    )
    assert "feasible outputs=2/2" in stdout
    for rank in (1, 2):
        movie_path = output if rank == 1 else tmp_path / "segment.rank02.ltm"
        replay_path = packed if rank == 1 else tmp_path / "segment.replay.rank02.txt"
        movie = LtmMovie.load(movie_path)
        assert movie.warning is None
        assert movie.embedded_level_record == record
        assert len(movie.replay_frames) == len(frames)
        assert _held(movie.replay_frames[:1]) == _held(frames[:1])
        assert _held(movie.replay_frames[9:]) == _held(frames[9:])
        replay_frames = decode_complex_replay(replay_path.read_text().strip()).frames
        assert _held(replay_frames) == _held(movie.replay_frames)
        output_lines = _member_bytes(movie_path, "inputs").decode().splitlines()
        assert output_lines[:2] == lines[:2]
        assert output_lines[-2:] == lines[-2:]
        assert all(f"Mbody:{i}|" in line for i, line in enumerate(output_lines[2:-2]))
        assert _member_bytes(movie_path, "inputs7") == b"alternate branch\n"
        assert _member_bytes(movie_path, "notes.txt") == b"manual TAS notes\n"
        endpoint = _scan(level, movie.replay_frames)[9]
        assert endpoint[0] > _scan(level, frames)[9][0]
        assert not endpoint[4] and not endpoint[5]


def test_population_cli_resume_matches_uninterrupted_campaign(tmp_path):
    source = tmp_path / "source.txt"
    _write_replay(source, [InputFrame()] * 24)
    common = (
        source, "--search", "population", "--range", "2:5,8:11",
        "--target-frame", 14, "--objective", "min-x", "--workers", 1,
        "--iterations", 40, "--beam", 8, "--repair-steps", 4, "--seed", 71,
    )
    checkpoint = tmp_path / "campaign.json"
    resumed_output = tmp_path / "resumed.txt"
    _run(*common, "--rounds", 1, "--checkpoint", checkpoint, "--output", resumed_output)
    assert json.loads(checkpoint.read_text())["payload"]["rounds"] == 1
    resumed_stdout = _run(*common, "--rounds", 2, "--checkpoint", checkpoint,
                          "--resume", "--output", resumed_output)
    assert json.loads(checkpoint.read_text())["payload"]["rounds"] == 2
    uninterrupted_output = tmp_path / "uninterrupted.txt"
    uninterrupted_stdout = _run(*common, "--rounds", 2, "--output", uninterrupted_output)
    assert resumed_output.read_bytes() == uninterrupted_output.read_bytes()
    final_summary = r"local population: objective=([^\n]+)"
    assert re.search(final_summary, resumed_stdout)[0] == re.search(final_summary, uninterrupted_stdout)[0]


def test_unreachable_arrival_does_not_overwrite_existing_output(tmp_path):
    source = tmp_path / "source.txt"
    _write_replay(source, [InputFrame()] * 15)
    output = tmp_path / "existing.txt"
    output.write_text("preserve my earlier manual TAS\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "optimize_replay.py"), "local", str(source),
         "--search", "population", "--range", "2:5", "--target-frame", "8",
         "--objective", "earliest-arrival", "--target-region", "500:510,100:150",
         "--iterations", "20", "--beam", "4", "--rounds", "1", "--workers", "1",
         "--repair-steps", "3", "--seed", "12", "--output", str(output)],
        cwd=ROOT, capture_output=True, text=True, timeout=40,
    )
    assert completed.returncode != 0
    assert "no feasible endpoint candidate was found" in completed.stderr
    assert "no output was written" in completed.stderr
    assert output.read_text() == "preserve my earlier manual TAS\n"
