"""Patch 86: explicitly centred bridge repair, with unchanged safety gates."""
from __future__ import annotations

import pytest

import nv14_user_splice as us
from nv14_auto import evaluate_replay_with_sentinel
from nv14_cli import parse_arguments
from nv14_engine import InputFrame
from nv14_random_splice import RandomSpliceConfig
from nv14_splice_merge import BridgeRepairResult, repair_suffix_grafts
from nv14_user_splice import optimise_user_splices
from tas import build_command
from tests.test_random_splice import _baseline
from tests.test_user_splice_manual_input_merge import _finished_slow_run
from tests.test_user_splice_repair_targeted import _stages


@pytest.mark.parametrize("option", [
    "--merge-repair-at-frame", "--splice-merge-repair-at-frame", "--at"
])
def test_frame_option_aliases_select_one_destination(option):
    args = parse_arguments(["auto", "replay.ltm", option, "800"])
    assert args.auto_splice_merge_repair_at_frame == 800
    assert parse_arguments(["auto", "replay.ltm"]).auto_splice_merge_repair_at_frame is None


def test_frame_option_cli_overrides_toml(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[multi-splicer]\nfiles = ["527", "599"]\nmerge-repair-at-frame = 800\n', encoding="utf-8")
    args = parse_arguments(["auto", "replay.ltm", "--splice-config", str(config)])
    assert args.auto_splice_merge_repair_at_frame == 800
    args = parse_arguments(["auto", "replay.ltm", "--splice-config", str(config), "--at", "810"])
    assert args.auto_splice_merge_repair_at_frame == 810
    assert parse_arguments(["auto", "replay.ltm", "--at", "12",
                            "--merge-repair-at-frame", "18"]).auto_splice_merge_repair_at_frame == 18


@pytest.mark.parametrize("value", ["0", "-1", "wrong", "2.5"])
def test_frame_cli_rejects_invalid_frame(value):
    with pytest.raises(SystemExit):
        parse_arguments(["auto", "replay.ltm", "--at", value])


def test_multi_forwards_frame_alias():
    args = build_command("multi", "81-1", extra=("--repair", "--from", "527",
                                                  "--to", "completed", "--at", "800"))
    assert args[-7:] == ["--repair", "--from", "527", "--to", "completed", "--at", "800"]


def test_direct_user_splice_passes_requested_frame_without_stage_clamping(monkeypatch):
    level, fast, _ = _baseline()
    saved = _finished_slow_run(level)
    seen = []

    def fake_repair(_level, prefix, reference, **kwargs):
        seen.append(kwargs)
        return BridgeRepairResult((), searches=1, evaluations=2)

    monkeypatch.setattr(us, "repair_suffix_grafts", fake_repair)
    monkeypatch.setattr(us, "verified_suffix_grafts", lambda *_a, **_kw: ())
    messages = []
    optimise_user_splices(
        level, saved, _stages(level, fast), RandomSpliceConfig(iterations=2),
        merge_stage_bests=True, merge_only=True, merge_repair_only=True,
        merge_repair_from="527", merge_repair_to="599", merge_repair_at_frame=25,
        saved_final_frames=saved,
        saved_stage_candidates={"527": [fast], "599": [saved]},
        progress=messages.append, merge_verbose=True,
    )
    assert seen
    assert all(k["seam_frame"] == k["at_frame"] == 25 for k in seen)
    assert any("repair frame 25" in message for message in messages)
    assert any("seam 25" in message for message in messages)


@pytest.mark.parametrize("bad", [0, -1, 1, 3.5, True, "800"])
def test_programmatic_frame_validation(bad):
    level, frames, _ = _baseline()
    with pytest.raises(ValueError, match="merge_repair_at_frame"):
        optimise_user_splices(level, frames, _stages(level, frames),
                              RandomSpliceConfig(iterations=1),
                              merge_repair_at_frame=bad)


def test_requested_frame_is_not_silently_clamped_and_respects_prefix():
    level, frames, _ = _baseline()
    saved = _finished_slow_run(level)
    modified = list(saved)
    modified[16] = InputFrame(left=True)
    config = RandomSpliceConfig(search_backend="local", repair_iterations=4)

    out = repair_suffix_grafts(level, modified, saved, seam_frame=15, at_frame=100,
                               window=8, targets=2, completion_required=True,
                               seed=3, config=config)
    assert not out.grafts and not out.searches
    assert "requested repair frame 100 exceeds live prefix" in out.failure_reason

    out = repair_suffix_grafts(level, modified, saved, seam_frame=20, at_frame=17,
                               window=8, targets=2, protected_through=16,
                               completion_required=True, seed=3, config=config)
    assert not out.grafts and not out.searches
    assert "at/before protected checkpoint" in out.failure_reason


def test_requested_frame_limits_search_near_centre_without_changing_prefix():
    level, _, _ = _baseline()
    saved = _finished_slow_run(level)
    modified = list(saved)
    modified[16] = InputFrame(left=True)
    starts_and_ends = []

    def backend(_level, branch, goal, **kwargs):
        starts_and_ends.append((kwargs["start"], kwargs["editable_end"]))
        return ((saved, kwargs["editable_end"]),), 1

    out = repair_suffix_grafts(
        level, modified, saved, seam_frame=11, at_frame=20, window=8,
        targets=3, protected_through=15, completion_required=True,
        seed=2, config=RandomSpliceConfig(search_backend="local", repair_iterations=4),
        local_search=backend,
    )
    assert starts_and_ends and out.searches >= 1
    assert all(18 <= end <= 22 and start >= 16 for start, end in starts_and_ends)
    assert all(tuple(graft[:16]) == tuple(modified[:16]) for graft in out.grafts)
