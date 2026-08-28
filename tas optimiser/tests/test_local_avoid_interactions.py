from __future__ import annotations

import sys
from pathlib import Path

import pytest

import optimize_replay as opt
from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    TestDoor as DoorObject,
    door_control_masks,
    parse_level_string,
)
from nv14_replay import (
    decode_complex_replay,
    encode_complex_replay,
    parse_combined_level_replay,
    simulate_through_frame,
)
from nv14_search import (
    OBJECTIVE_MAX_X,
    NativeSearchSession,
    SearchSpec,
    compile_interaction_groups,
)


EMPTY_MAP = "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)


def make_level(objects: str, *, player_x: float = 100.0, player_y: float = 100.0):
    level = parse_level_string(
        f"{EMPTY_MAP}|5^{player_x:g},{player_y:g}!{objects}"
    )
    level.player.g = 0.0
    return level


def test_avoidance_selectors_use_stable_testdoor_indices_and_aliases() -> None:
    level = make_level(
        "!".join(
            (
                "9^0,0,0,0,17,17,0,0,0",
                "9^60,60,0,1,18,17,0,0,0",
                "9^115,100,0,0,19,17,1,0,0",
            )
        )
    )

    exact = opt.resolve_interaction_avoidance(level, "testdoor:1")
    alias = opt.resolve_interaction_avoidance(level, "trapdoor:1")
    bare_alias = opt.resolve_interaction_avoidance(level, "trapdoor")
    any_trap = opt.resolve_interaction_avoidance(level, "trapdoor:any")
    assert exact.alternatives == alias.alternatives == bare_alias.alternatives
    assert exact.alternatives == any_trap.alternatives
    assert exact.display_label == "testdoor:1"

    any_persistent_door = opt.resolve_interaction_avoidance(level, "testdoor:any")
    assert [atom.label for atom in any_persistent_door.alternatives] == [
        "testdoor:1",
        "testdoor:2",
    ]

    locked = opt.resolve_interaction_avoidance(level, "testdoor:2")
    assert locked.alternatives[0].kind == opt.INTERACTION_LOCKED_DOOR

    with pytest.raises(ValueError, match="transient activation"):
        opt.resolve_interaction_avoidance(level, "testdoor:0")
    with pytest.raises(ValueError, match="not a trapdoor"):
        opt.resolve_interaction_avoidance(level, "trapdoor:2")


def test_avoidance_any_is_violated_by_any_matching_object() -> None:
    level = make_level("0^83.95,100!0^300,100")
    avoidance = opt.resolve_interaction_avoidance(level, "gold:any")
    state = simulate_through_frame(
        level,
        [InputFrame(left=True), InputFrame()],
        1,
    )

    violated = opt.violated_interaction_avoidances((avoidance,), state)
    assert violated == frozenset((avoidance,))


def test_explicit_trapdoor_avoidance_repairs_even_when_max_x_is_worse() -> None:
    level = make_level("9^115.05,100,0,1,20,20,0,0,0")
    source = [InputFrame(right=True), InputFrame()]
    avoidance = opt.resolve_interaction_avoidance(level, "testdoor:0")
    baseline = opt.evaluate(
        level,
        source,
        1,
        opt.objective_function("max-x"),
        avoided_interactions=(avoidance,),
    )
    assert baseline.violated_interactions == frozenset((avoidance,))
    progress: list[str] = []

    optimised, result = opt.optimise_local_windows(
        level,
        source,
        target_frame=1,
        range_start=0,
        range_end=0,
        objective_name="max-x",
        window_size=1,
        passes=1,
        avoided_interactions=(avoidance,),
        progress=progress.append,
    )

    assert not optimised[0].right
    assert result.score < baseline.score
    assert not result.violated_interactions
    assert door_control_masks(simulate_through_frame(level, optimised, 1))[1] == 0
    assert any("avoided forbidden interaction" in line for line in progress)


@pytest.mark.parametrize("local_inputs", ("all", "direction"))
def test_safe_trapdoor_route_is_preserved_in_both_local_input_modes(
    local_inputs: str,
) -> None:
    level = make_level("9^115.05,100,0,1,20,20,0,0,0")
    source = [InputFrame(), InputFrame()]
    avoidance = opt.resolve_interaction_avoidance(level, "trapdoor:0")

    unconstrained, unconstrained_eval = opt.optimise_local_windows(
        level,
        source,
        target_frame=1,
        range_start=0,
        range_end=0,
        objective_name="max-x",
        window_size=1,
        passes=1,
        local_inputs=local_inputs,
        progress=None,
    )
    assert unconstrained[0].right
    assert (
        door_control_masks(simulate_through_frame(level, unconstrained, 1))[1]
        != 0
    )

    constrained, result = opt.optimise_local_windows(
        level,
        source,
        target_frame=1,
        range_start=0,
        range_end=0,
        objective_name="max-x",
        window_size=1,
        passes=1,
        local_inputs=local_inputs,
        avoided_interactions=(avoidance,),
        progress=None,
    )
    assert not constrained[0].right
    assert not result.violated_interactions
    assert door_control_masks(simulate_through_frame(level, constrained, 1))[1] == 0


@pytest.mark.parametrize("local_inputs", ("direction", "all"))
def test_native_search_prunes_persistent_avoidance_before_fixed_suffix(
    local_inputs: str,
) -> None:
    level = make_level("9^115.05,100,0,1,20,20,0,0,0")
    frames = [InputFrame() for _ in range(121)]
    avoidance = opt.resolve_interaction_avoidance(level, "testdoor:0")
    logs: list[str] = []

    opt.optimise_local_windows(
        level,
        frames,
        target_frame=120,
        range_start=0,
        range_end=3,
        objective_name="max-x",
        window_size=4,
        passes=1,
        local_inputs=local_inputs,
        avoided_interactions=(avoidance,),
        workers=1,
        progress=logs.append,
    )

    search_line = next(
        line
        for line in logs
        if line.startswith("frames 0-3 search:")
    )
    avoided_prunes = int(search_line.rsplit("avoided=", 1)[1])
    assert avoided_prunes > 0


def test_forbidden_interaction_in_immutable_prefix_is_reported() -> None:
    level = make_level("9^115.05,100,0,1,20,20,0,0,0")
    avoidance = opt.resolve_interaction_avoidance(level, "testdoor:0")

    with pytest.raises(RuntimeError, match=r"triggered: testdoor:0"):
        opt.optimise_local_windows(
            level,
            [InputFrame(right=True), InputFrame(), InputFrame()],
            target_frame=2,
            range_start=2,
            range_end=2,
            objective_name="max-x",
            window_size=1,
            passes=1,
            avoided_interactions=(avoidance,),
            progress=None,
        )


def test_native_candidate_does_not_exchange_forbidden_interactions() -> None:
    level = parse_level_string(
        f"{EMPTY_MAP}|5^100,100!"
        "9^84.95,100,0,1,20,20,0,0,0!"
        "9^115.05,100,0,1,21,20,0,0,0"
    )
    avoidances = tuple(
        opt.resolve_interaction_avoidance(level, f"testdoor:{index}")
        for index in range(2)
    )
    frames = (InputFrame(left=True), InputFrame())
    incumbent = opt.evaluate(
        level,
        frames,
        1,
        opt.objective_function("max-x"),
        avoided_interactions=avoidances,
    )
    sideways = opt.evaluate(
        level,
        (InputFrame(right=True), InputFrame()),
        1,
        opt.objective_function("max-x"),
        avoided_interactions=avoidances,
    )
    assert sideways.score > incumbent.score
    assert incumbent.violated_interactions == frozenset((avoidances[0],))
    assert sideways.violated_interactions == frozenset((avoidances[1],))

    result = NativeSearchSession(level).search(
        frames,
        SearchSpec(
            mutable_frames=(0,),
            choices=((InputFrame(right=True),),),
            target_frame=1,
            objective=OBJECTIVE_MAX_X,
            avoided_groups=compile_interaction_groups(avoidances),
            incumbent_violated_avoidances=frozenset((0,)),
            incumbent_score=incumbent.score,
            incumbent_feasible=incumbent.feasible,
        ),
    )

    assert not result.improved
    assert result.best_inputs == (InputFrame(left=True),)
    assert result.violated_avoidance_indices == frozenset((0,))


def test_list_objects_advertises_trapdoor_avoidance_selector() -> None:
    level = make_level(
        "9^60,60,0,1,19,20,0,0,0!9^85,100,0,0,20,20,1,0,0"
    )
    listing = opt.format_level_objects(level)

    assert "avoid-interaction=testdoor:0 or trapdoor:0" in listing
    assert "interaction=testdoor:1" in listing
    assert "avoid-interaction=testdoor:1" in listing


def test_parser_accepts_repeatable_avoidance_requirements() -> None:
    args = opt.build_parser().parse_args(
        [
            "local",
            "input.txt",
            "--avoid-interaction",
            "testdoor:1",
            "--avoid-interaction",
            "gold:any",
        ]
    )
    assert args.avoid_interaction == ["testdoor:1", "gold:any"]


def test_cli_avoid_interaction_writes_verified_replay(
    tmp_path, monkeypatch, capsys
) -> None:
    level_string = (
        f"{EMPTY_MAP}|5^100,100!9^115.05,100,0,1,20,20,0,0,0"
    )
    source = [InputFrame(right=True), InputFrame()]
    input_path = tmp_path / "source.txt"
    output_path = tmp_path / "optimised.txt"
    input_path.write_text(
        f"$Local trapdoor avoidance#tests##{level_string}#"
        f"{encode_complex_replay(source)}#\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "local", str(input_path),
            "--target-frame",
            "1",
            "--range",
            "0:0",
            "--window",
            "1",
            "--passes",
            "1",
            "--avoid-interaction",
            "testdoor:0",
            "--output",
            str(output_path),
        ],
    )

    opt.main()
    output = capsys.readouterr().out
    assert "forbidden interactions avoided: testdoor:0" in output

    combined = parse_combined_level_replay(output_path.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string)
    state = simulate_through_frame(level, replay.frames, 1)
    assert door_control_masks(state)[1] == 0
    assert not replay.frames[0].right


def test_cli_impossible_avoidance_leaves_existing_output_unchanged(
    tmp_path, monkeypatch
) -> None:
    level_string = (
        f"{EMPTY_MAP}|5^100,100!9^115.05,100,0,1,20,20,0,0,0"
    )
    input_path = tmp_path / "source.txt"
    output_path = tmp_path / "optimised.txt"
    input_path.write_text(
        f"$Impossible avoidance#tests##{level_string}#"
        f"{encode_complex_replay([InputFrame(right=True), InputFrame(), InputFrame()])}#\n",
        encoding="utf-8",
    )
    output_path.write_text("keep this output\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "local", str(input_path),
            "--target-frame",
            "2",
            "--range",
            "2:2",
            "--window",
            "1",
            "--passes",
            "1",
            "--avoid-interaction",
            "testdoor:0",
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit, match=r"triggered: testdoor:0"):
        opt.main()
    assert output_path.read_text(encoding="utf-8") == "keep this output\n"


def test_supplied_00_1_speedrun_avoids_trapdoor_and_completes() -> None:
    fixture = parse_combined_level_replay(
        Path(__file__).with_name("example_00_1_speedrun.txt").read_text(
            encoding="utf-8"
        )
    )
    level = parse_level_string(fixture.level_string)
    frames = decode_complex_replay(fixture.replay_string).frames
    requirement = opt.resolve_interaction_requirement(level, "switch:1")
    avoidance = opt.resolve_interaction_avoidance(level, "testdoor:1")
    target = opt.resolve_target_object(level, "exit:1.door")
    objective = opt.objective_function("min-distance", target)
    baseline = opt.evaluate(
        level,
        frames,
        300,
        objective,
        required_interactions=(requirement,),
        avoided_interactions=(avoidance,),
    )
    assert not baseline.missing_interactions
    assert not baseline.violated_interactions
    assert baseline.state.static_state.open_exit_mask & (1 << 1)
    assert door_control_masks(baseline.state)[1] == 0
    baseline_postroll = baseline.state.clone()
    baseline_postroll.step(InputFrame(), level.tiles)
    assert baseline_postroll.level_complete
    assert baseline_postroll.static_state.completed_exit_index == 1

    optimised, result = opt.optimise_local_windows(
        level,
        frames,
        target_frame=300,
        range_start=280,
        range_end=285,
        objective_name="min-distance",
        objective_target=target,
        window_size=2,
        passes=1,
        local_inputs="direction",
        required_interactions=(requirement,),
        avoided_interactions=(avoidance,),
        progress=None,
    )
    assert result.score > baseline.score
    assert not result.missing_interactions
    assert not result.violated_interactions
    checked = simulate_through_frame(level, optimised, 300)
    assert checked.static_state.open_exit_mask & (1 << 1)
    assert door_control_masks(checked)[1] == 0
    assert not checked.player.dead
    postroll = checked.clone()
    postroll.step(InputFrame(), level.tiles)
    assert postroll.level_complete
    assert postroll.static_state.completed_exit_index == 1
