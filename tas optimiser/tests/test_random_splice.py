"""Random splice route-control safety, configuration and native integration."""
from dataclasses import replace
import random

import pytest

from nv14_auto import RouteControlEvent, evaluate_replay_with_sentinel
from nv14_cli import parse_arguments
from nv14_engine import InputFrame
from nv14_random_splice import (
    RandomSpliceConfig, _control_preserved, _mask_preserved,
    _validated_improvement, _repair_window_start, choose_waypoints, optimise_random_splices,
)
from tests.test_auto import _running_exit_level


def _baseline():
    level = _running_exit_level()
    frames = tuple(InputFrame(right=True) for _ in range(29))
    check = evaluate_replay_with_sentinel(level, frames)
    assert check.finish_tick == len(frames)
    assert check.route_control_events[0].kind == "exit"
    return level, frames, check


def test_switch_event_cannot_disappear_even_when_endpoint_is_completed():
    _level, _frames, base = _baseline()
    # A candidate completing some other exit must not omit an original switch.
    missing = replace(base, route_control_events=())
    assert not _control_preserved(base, missing)
    assert _control_preserved(base, base)


def test_locked_door_and_trapdoor_must_not_disappear_at_waypoint():
    _level, _frames, base = _baseline()
    point = base.point(20)
    assert point is not None
    required = replace(point, open_exit_mask=1, opened_locked_door_mask=0b100,
                       triggered_trapdoor_mask=0b10)
    assert not _mask_preserved(required, point)
    restored = replace(point, open_exit_mask=3, opened_locked_door_mask=0b101,
                       triggered_trapdoor_mask=0b10)
    assert _mask_preserved(required, restored)


def test_control_event_inserts_mandatory_waypoint():
    _level, _frames, base = _baseline()
    # An event outside the random waypoints must still get an anchor.
    with_mid_switch = replace(base, route_control_events=(
        RouteControlEvent("exit", 0, 8), RouteControlEvent("locked-door", 3, 17),
    ))
    points = choose_waypoints(with_mid_switch,
                              RandomSpliceConfig(points=1, seed=9), random.Random(9))
    assert any(point.mandatory and point.frame == 9 for point in points)
    assert any(point.mandatory and point.frame == 18 for point in points)
    assert tuple(sorted(p.frame for p in points)) == tuple(p.frame for p in points)


def test_shorter_replay_rejected_if_it_does_not_finish_and_preserve_switch():
    level, source, baseline = _baseline()
    assert _validated_improvement(level, source[:13], baseline, len(source)) is None
    assert _validated_improvement(level, source, baseline, len(source)) is None


def test_random_splice_defaults_keep_verified_completed_replay():
    level, source, baseline = _baseline()
    result = optimise_random_splices(level, source, RandomSpliceConfig(
        points=2, iterations=12, repair_iterations=8, lookback=8, rounds=1, seed=7))
    assert result.attempts >= 1
    assert result.evaluations > 0
    checked = evaluate_replay_with_sentinel(level, result.frames)
    assert checked.valid and checked.finish_tick == len(result.frames)
    assert _control_preserved(baseline, checked)
    assert len(result.frames) <= len(source)


def test_cli_random_splice_accepts_native_options_from_toml(tmp_path):
    config = tmp_path / "base.toml"
    config.write_text("""[auto]
objective = "speedrun"
random-splice = true
splice-points = 3
splice-radius = 18
splice-repair-anchors = 4
runs = 1
""", encoding="utf8")
    args = parse_arguments(["auto", "source.txt", "--config", str(config),
                            "--output", str(tmp_path / "result.txt")])
    assert args.auto_random_splice
    assert args.auto_splice_points == 3
    assert args.auto_splice_radius == 18
    assert args.auto_splice_repair_anchors == 4


def test_cli_splice_parameters_without_mode_rejected():
    with pytest.raises(SystemExit, match="require --auto-random-splice"):
        parse_arguments(["auto", "source.txt", "--auto-splice-radius", "12"])
    with pytest.raises(SystemExit, match="requires --objective speedrun"):
        parse_arguments(["auto", "source.txt", "--auto-random-splice", "--objective", "highscore"])


@pytest.mark.parametrize("updates", [
    {"radius": 0.0}, {"distance": -2}, {"points": 0}, {"workers": 0},
    {"repair_anchors": -1}, {"rounds": -1},
])
def test_bad_random_splice_configuration_rejected(updates):
    with pytest.raises(ValueError):
        RandomSpliceConfig(**updates)


def test_random_splice_saves_frames_on_delayed_reference_without_losing_switch():
    level, _source, _base = _baseline()
    delayed = tuple([InputFrame()] * 6 + [InputFrame(right=True)] * 29)
    original = evaluate_replay_with_sentinel(level, delayed)
    assert original.valid and original.finish_tick == len(delayed)
    result = optimise_random_splices(level, delayed, RandomSpliceConfig(
        points=4, iterations=2500, repair_iterations=100,
        repair_anchors=1, radius=6, lookback=34, seed=2))
    assert result.improvements >= 1
    assert len(result.frames) == 29
    updated = evaluate_replay_with_sentinel(level, result.frames)
    assert updated.valid and updated.finish_tick == len(result.frames)
    assert _control_preserved(original, updated)


def test_splice_spacing_and_count_both_select_path_positions():
    _level, _source, base = _baseline()
    by_count = choose_waypoints(base, RandomSpliceConfig(points=3), random.Random(5))
    by_spacing = choose_waypoints(base, RandomSpliceConfig(distance=15), random.Random(5))
    assert by_count and by_spacing
    assert all(1 < p.frame < base.finish_tick - 1 for p in by_count + by_spacing)
    assert tuple(p.frame for p in by_spacing) == tuple(sorted(p.frame for p in by_spacing))


def test_cli_toml_random_splice_writes_verified_faster_tas(tmp_path, monkeypatch):
    from nv14_cli import main
    from nv14_replay import (parse_combined_level_replay, decode_complex_replay,
                            encode_complex_replay)
    import sys

    level, _, _ = _baseline()
    delayed = tuple([InputFrame()] * 6 + [InputFrame(right=True)] * 29)
    source = tmp_path / "slow.txt"
    output = tmp_path / "fast.txt"
    config = tmp_path / "settings.toml"
    source.write_text(f"$test#author#{level.source_level_string}#{encode_complex_replay(delayed)}#\n")
    config.write_text("""[common]
workers = 1
simulate-enemies = false
[auto]
objective = "speedrun"
random-splice = true
runs = 1
seed = 2
splice-points = 4
splice-radius = 6
splice-lookback = 34
splice-iterations = 2500
splice-repair-iterations = 100
splice-repair-anchors = 1
""")
    monkeypatch.setattr(sys, "argv", ["optimize_replay.py", "auto", str(source),
                                    "--config", str(config), "--output", str(output)])
    main()
    assert output.exists()
    loaded = parse_combined_level_replay(output.read_text())
    frames = decode_complex_replay(loaded.replay_string).frames
    checked = evaluate_replay_with_sentinel(level, frames)
    assert len(frames) == checked.finish_tick == 29
    assert checked.valid
    assert checked.route_control_events[0].kind == "exit"


def test_actual_later_exit_switch_becomes_mandatory_checkpoint():
    from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, parse_level_string
    cells = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for x in range(APP_NUM_GRIDCOLS):
        cells[x * APP_NUM_GRIDROWS + 5] = "1"
    level = parse_level_string("".join(cells) +
                               "|5^60,134!11^140,134,60,134!11^180,134,95,134")
    frames = [InputFrame(right=True)] * 29
    baseline = evaluate_replay_with_sentinel(level, frames)
    assert baseline.valid
    assert len([e for e in baseline.route_control_events if e.kind == "exit"]) == 2
    later_event = baseline.route_control_events[1]
    checkpoints = choose_waypoints(baseline, RandomSpliceConfig(points=1), random.Random(0))
    assert any(w.frame == later_event.tick + 1 and w.mandatory for w in checkpoints)
    without_later = replace(baseline, route_control_events=baseline.route_control_events[:1])
    assert not _control_preserved(baseline, without_later)


def test_continuous_campaign_configuration_is_supported():
    assert RandomSpliceConfig(rounds=0).rounds == 0


def test_real_two_switches_are_kept_after_six_frame_gain():
    from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, parse_level_string
    cells = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for x in range(APP_NUM_GRIDCOLS):
        cells[x * APP_NUM_GRIDROWS + 5] = "1"
    level = parse_level_string("".join(cells) +
                               "|5^60,134!11^140,134,60,134!11^180,134,95,134")
    frames = tuple([InputFrame()] * 6 + [InputFrame(right=True)] * 29)
    reference = evaluate_replay_with_sentinel(level, frames)
    assert len([e for e in reference.route_control_events if e.kind == "exit"]) == 2
    result = optimise_random_splices(level, frames, RandomSpliceConfig(
        points=4, iterations=2500, repair_iterations=100,
        repair_anchors=2, radius=6, lookback=34, seed=2))
    improved = evaluate_replay_with_sentinel(level, result.frames)
    assert improved.valid
    assert len(result.frames) == 29
    assert improved.finish_tick == 29
    assert _control_preserved(reference, improved)
    assert {(e.kind, e.index) for e in improved.route_control_events} == {
        ("exit", 0), ("exit", 1)
    }


@pytest.mark.parametrize("dead_tick, suggested, immutable_end, expected", [
    (None, 35, 10, 35),
    (22, 35, 10, 22),  # Rewind before the dying frame was frozen.
    (11, 35, 10, 11),  # Last repairable frame immediately after the seam.
    (10, 35, 10, None),  # Dead in the immutable splice prefix.
    (5, 35, 10, None),
    (40, 35, 10, 35),  # Death after the editable window begins.
])
def test_continuation_repair_rewinds_fatal_prefix(dead_tick, suggested, immutable_end, expected):
    _level, _frames, baseline = _baseline()
    provisional = replace(baseline, dead_tick=dead_tick, finish_tick=None)
    assert _repair_window_start(
        provisional, suggested=suggested, immutable_end=immutable_end,
    ) == expected


def test_continuation_cannot_repair_already_finished_prefix():
    _level, _frames, baseline = _baseline()
    assert _repair_window_start(
        replace(baseline, finish_tick=14), suggested=35, immutable_end=10,
    ) is None

@pytest.mark.parametrize("death_frame, repair_start", [
    (8, 8),   # The splice has a repairable death before the normal window.
    (4, None),  # The new route died at the frozen seam; skip it.
])
def test_random_splice_does_not_abort_on_fatal_continuation_prefix(
    monkeypatch, death_frame, repair_start,
):
    import nv14_random_splice as splice
    level, source, baseline = _baseline()
    anchor_a = splice.Waypoint(5, baseline.point(5).x, baseline.point(5).y)
    anchor_b = splice.Waypoint(21, baseline.point(21).x, baseline.point(21).y)
    monkeypatch.setattr(splice, "choose_waypoints", lambda *args: (anchor_a, anchor_b))
    monkeypatch.setattr(splice, "_candidate_seams", lambda *args: ((4, 5),))
    monkeypatch.setattr(splice, "_validated_improvement", lambda *args: None)
    actual_evaluate = splice.evaluate_replay_with_sentinel

    def evaluate(level, frames):
        result = actual_evaluate(level, frames)
        if len(frames) < len(source):
            return replace(result, finish_tick=None, dead_tick=death_frame)
        return result

    monkeypatch.setattr(splice, "evaluate_replay_with_sentinel", evaluate)
    calls = []

    def local_search(level, frames, goal, *, start, **kwargs):
        calls.append((goal.target_frame, start))
        if len(calls) == 1:
            return ((source, 4),), 1
        return (), 0

    monkeypatch.setattr(splice, "_local_search", local_search)
    result = optimise_random_splices(level, source, RandomSpliceConfig(
        points=2, lookback=8, iterations=5, repair_iterations=5, rounds=1,
    ))
    assert result.improvements == 0
    assert result.frames == source
    if repair_start is not None:
        assert calls[1] == (20, repair_start)
    else:
        assert (20, 8) not in calls


def test_random_splice_skips_local_dead_prefix_failure_without_exiting(monkeypatch):
    import nv14_random_splice as splice
    level, source, baseline = _baseline()
    anchor_a = splice.Waypoint(5, baseline.point(5).x, baseline.point(5).y)
    anchor_b = splice.Waypoint(21, baseline.point(21).x, baseline.point(21).y)
    monkeypatch.setattr(splice, "choose_waypoints", lambda *args: (anchor_a, anchor_b))
    monkeypatch.setattr(splice, "_candidate_seams", lambda *args: ((4, 5),))
    monkeypatch.setattr(splice, "_validated_improvement", lambda *args: None)
    local_calls = []

    def local_search(level, frames, goal, *, start, **kwargs):
        local_calls.append(start)
        if len(local_calls) == 1:
            return ((source, 4),), 1
        if len(local_calls) == 2:
            raise ValueError(
                "the immutable prefix dies before the editable ranges; move the range start earlier"
            )
        return (), 0

    monkeypatch.setattr(splice, "_local_search", local_search)
    result = optimise_random_splices(level, source, RandomSpliceConfig(
        points=2, lookback=8, iterations=5, repair_iterations=5, rounds=1,
    ))
    assert result.improvements == 0 and result.frames == source
    assert len(local_calls) >= 2


def test_random_splice_stagnation_stops_unbounded_campaign(monkeypatch):
    import nv14_random_splice as splice
    level, source, _baseline_eval = _baseline()
    monkeypatch.setattr(splice, "choose_waypoints", lambda *args: ())
    messages = []
    result = optimise_random_splices(
        level, source, RandomSpliceConfig(rounds=0, stagnation_rounds=2),
        progress=messages.append,
    )
    assert result.attempts == 0 and result.frames == source
    assert sum("round " in m and "completed in" in m for m in messages) == 2
    assert any("stopping after 2 rounds" in m for m in messages)


def test_random_splice_anchor_progress_and_population_forwarding(monkeypatch):
    import nv14_random_splice as splice
    level, source, baseline = _baseline()
    anchor = splice.Waypoint(10, baseline.point(10).x, baseline.point(10).y)
    monkeypatch.setattr(splice, "choose_waypoints", lambda *args: (anchor,))

    def local_search(level, frames, goal, *, progress=None, **kwargs):
        if progress:
            progress("[local:population] seed 13; 3 worker(s); beam 16")
        return (), 12

    monkeypatch.setattr(splice, "_local_search", local_search)
    messages = []
    result = optimise_random_splices(
        level, source, RandomSpliceConfig(rounds=1, workers=3),
        progress=messages.append,
    )
    assert result.evaluations == 12
    assert any("anchor 1/1 frame 10: searching" in m and "3 workers" in m for m in messages)
    assert any("anchor 1/1 frame 10: seed 13; 3 worker(s)" in m for m in messages)
    assert any("anchor 1/1 frame 10: search finished" in m for m in messages)


def test_random_splice_repair_searches_capped_per_waypoint(monkeypatch):
    import nv14_random_splice as splice
    level, source, baseline = _baseline()
    anchors = (splice.Waypoint(6, baseline.point(6).x, baseline.point(6).y),
               splice.Waypoint(20, baseline.point(20).x, baseline.point(20).y))
    monkeypatch.setattr(splice, "choose_waypoints", lambda *args: anchors)
    monkeypatch.setattr(splice, "_candidate_seams", lambda *args: ((4, 6), (3, 6)))
    monkeypatch.setattr(splice, "_validated_improvement", lambda *args: None)
    monkeypatch.setattr(splice, "_repair_window_start", lambda p, *, suggested, immutable_end: suggested)
    calls = []

    def local_search(level, frames, goal, *, start, **kwargs):
        calls.append(goal.target_frame)
        if len(calls) == 1:
            return ((source, 4),), 1
        return (), 1

    monkeypatch.setattr(splice, "_local_search", local_search)
    messages = []
    result = optimise_random_splices(
        level, source, RandomSpliceConfig(rounds=1, points=2,
                                          max_repair_searches=1),
        progress=messages.append,
    )
    assert calls.count(18) <= 1
    assert len(calls) == 3  # One initial search per anchor, one continuation repair total.
    assert any("repair limit reached (1 searches)" in m for m in messages)
    assert result.improvements == 0


def test_cli_random_splice_new_limits_load_from_toml(tmp_path):
    config = tmp_path / "limits.toml"
    config.write_text("[auto]\nobjective = 'speedrun'\nrandom-splice = true\n"
                      "splice-repair-searches = 2\nstagnation-runs = 3\n", encoding="utf8")
    args = parse_arguments(["auto", "input.txt", "--config", str(config)])
    assert args.auto_splice_repair_searches == 2
    assert args.auto_stagnation_runs == 3
