from __future__ import annotations

import sys

import pytest

import optimize_replay as opt
from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    TestDoor as DoorObject,
    parse_level_string,
)
from nv14_replay import (
    decode_complex_replay,
    encode_complex_replay,
    parse_combined_level_replay,
    simulate_through_frame,
)


EMPTY_MAP = "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)


def make_level(objects: str, *, player_x: float = 100.0, player_y: float = 100.0):
    level = parse_level_string(
        f"{EMPTY_MAP}|5^{player_x:g},{player_y:g}!{objects}"
    )
    # Keep focused local-search fixtures in open space without vertical drift.
    level.player.g = 0.0
    return level


def test_interaction_selectors_use_stable_per_type_indices_and_aliases() -> None:
    objects = "!".join(
        (
            "0^80,100",
            "0^120,100",
            "11^300,100,90,100",
            "11^320,100,110,100",
            # Ordinary, trap, then locked TestDoor. The public index remains
            # stable across every object of the type, not only locked doors.
            "9^0,0,0,0,17,17,0,0,0",
            "9^60,60,0,1,18,17,0,0,0",
            "9^115,100,0,0,19,17,1,0,0",
        )
    )
    level = make_level(objects)

    gold_any = opt.resolve_interaction_requirement(level, "gold:any")
    assert [atom.label for atom in gold_any.alternatives] == ["gold:0", "gold:1"]

    switch = opt.resolve_interaction_requirement(level, "switch:1")
    exit_switch = opt.resolve_interaction_requirement(level, "exit:1.switch")
    assert switch.alternatives == exit_switch.alternatives
    assert switch.display_label == "switch:1"

    with pytest.raises(ValueError, match="must name the switch anchor"):
        opt.resolve_interaction_requirement(level, "exit:1")

    locked = opt.resolve_interaction_requirement(level, "testdoor:2")
    bare_locked = opt.resolve_interaction_requirement(level, "testdoor")
    any_locked = opt.resolve_interaction_requirement(level, "testdoor:any")
    assert locked.alternatives == bare_locked.alternatives == any_locked.alternatives
    assert locked.display_label == "testdoor:2"

    with pytest.raises(ValueError, match="ordinary proximity door"):
        opt.resolve_interaction_requirement(level, "testdoor:0")
    with pytest.raises(ValueError, match="trapdoor"):
        opt.resolve_interaction_requirement(level, "testdoor:1")


def test_reference_requirements_preserve_exact_identities_but_allow_extras() -> None:
    level = make_level(
        "!".join(
            (
                "0^80,100",
                "0^120,100",
                "11^300,100,90,100",
                "11^320,100,110,100",
                "9^85,100,0,0,17,17,1,0,0",
                "9^115,100,0,0,19,17,1,0,0",
            )
        )
    )
    reference = level.initial_state()
    reference.static_state.collected_gold_mask = 0b01
    reference.static_state.open_exit_mask = 0b10
    locked_doors = sorted(
        (obj for obj in reference.objects if isinstance(obj, DoorObject)),
        key=lambda obj: obj.load_index,
    )
    locked_doors[0].is_open = True

    requirements = opt.reference_interaction_requirements(level, reference)
    assert [requirement.display_label for requirement in requirements] == [
        "gold:0",
        "switch:1",
        "testdoor:0",
    ]

    extra_interactions = reference.clone()
    extra_interactions.static_state.collected_gold_mask = 0b11
    extra_interactions.static_state.open_exit_mask = 0b11
    locked_doors = sorted(
        (obj for obj in extra_interactions.objects if isinstance(obj, DoorObject)),
        key=lambda obj: obj.load_index,
    )
    locked_doors[1].is_open = True
    assert not opt.missing_interaction_requirements(requirements, extra_interactions)

    wrong_gold = extra_interactions.clone()
    wrong_gold.static_state.collected_gold_mask = 0b10
    missing = opt.missing_interaction_requirements(requirements, wrong_gold)
    assert [requirement.display_label for requirement in missing] == ["gold:0"]


@pytest.mark.parametrize(
    ("objects", "selector", "satisfied"),
    (
        (
            "0^83.95,100",
            "gold:0",
            lambda state: state.static_state.collected_gold_mask == 1,
        ),
        (
            "11^300,100,83.95,100",
            "switch:0",
            lambda state: state.static_state.open_exit_mask == 1,
        ),
        (
            "9^84.95,100,0,0,20,20,1,0,0",
            "testdoor:0",
            lambda state: next(
                obj for obj in state.objects if isinstance(obj, DoorObject)
            ).is_open,
        ),
    ),
)
def test_explicit_interaction_repairs_outrank_max_x(
    objects: str,
    selector: str,
    satisfied,
) -> None:
    level = make_level(objects)
    source = [InputFrame(), InputFrame()]
    requirement = opt.resolve_interaction_requirement(level, selector)
    progress: list[str] = []

    serial, serial_result = opt.optimise_local_windows(
        level,
        source,
        target_frame=1,
        range_start=0,
        range_end=0,
        objective_name="max-x",
        window_size=1,
        passes=1,
        required_interactions=(requirement,),
        workers=1,
        progress=None,
    )
    optimised, result = opt.optimise_local_windows(
        level,
        source,
        target_frame=1,
        range_start=0,
        range_end=0,
        objective_name="max-x",
        window_size=1,
        passes=1,
        required_interactions=(requirement,),
        workers=2,
        progress=progress.append,
    )

    # Moving left is strictly worse for max-x but is accepted because it repairs
    # the hard route-state requirement in the fixed suffix at frame 1.
    assert optimised == serial
    assert result.state.state_key() == serial_result.state.state_key()
    assert optimised[0].left
    assert result.score < 100.0
    assert satisfied(result.state)
    assert not result.missing_interactions
    assert any("satisfied required interaction" in line for line in progress)


@pytest.mark.parametrize("local_inputs", ("all", "direction"))
def test_reference_interactions_are_preserved_in_both_local_input_modes(
    local_inputs: str,
) -> None:
    level = make_level("0^83.95,100")
    reference = [InputFrame(left=True), InputFrame()]
    reference_state = simulate_through_frame(level, reference, 1)
    assert reference_state.static_state.collected_gold_mask == 1

    unconstrained, _ = opt.optimise_local_windows(
        level,
        reference,
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

    constrained, result = opt.optimise_local_windows(
        level,
        reference,
        target_frame=1,
        range_start=0,
        range_end=0,
        objective_name="max-x",
        window_size=1,
        passes=1,
        local_inputs=local_inputs,
        require_reference_interactions=True,
        progress=None,
    )
    assert constrained[0].left
    assert result.state.static_state.collected_gold_mask == 1
    assert not result.missing_interactions


def test_interaction_in_immutable_prefix_counts() -> None:
    level = make_level("0^83.95,100")
    source = [InputFrame(left=True), InputFrame(), InputFrame()]
    requirement = opt.resolve_interaction_requirement(level, "gold:0")

    optimised, result = opt.optimise_local_windows(
        level,
        source,
        target_frame=2,
        range_start=2,
        range_end=2,
        objective_name="max-x",
        window_size=1,
        passes=1,
        required_interactions=(requirement,),
        progress=None,
    )

    assert optimised[0].left
    assert result.state.static_state.collected_gold_mask == 1
    assert not result.missing_interactions


def test_impossible_explicit_interaction_produces_no_valid_result(monkeypatch) -> None:
    level = make_level("0^300,100")
    requirement = opt.resolve_interaction_requirement(level, "gold:0")

    def unexpected_pool(*args, **kwargs):
        raise AssertionError("hard-only serial windows must not start a worker pool")

    monkeypatch.setattr(opt, "ProcessPoolExecutor", unexpected_pool)

    with pytest.raises(RuntimeError, match=r"remaining: gold:0"):
        opt.optimise_local_windows(
            level,
            [InputFrame(), InputFrame()],
            target_frame=1,
            range_start=0,
            range_end=0,
            objective_name="max-x",
            window_size=1,
            passes=1,
            required_interactions=(requirement,),
            workers=2,
            progress=None,
        )


def test_candidate_comparison_does_not_exchange_hard_requirements() -> None:
    level = make_level("0^80,100!11^300,100,120,100")
    gold = opt.resolve_interaction_requirement(level, "gold:0")
    switch = opt.resolve_interaction_requirement(level, "switch:0")
    state = level.initial_state()
    incumbent = opt.Evaluation(0.0, state, True, frozenset((gold, switch)))
    best = opt.Evaluation(1.0, state, True, frozenset((switch,)))
    sideways = opt.Evaluation(100.0, state, True, frozenset((gold,)))

    assert not opt._local_candidate_better(
        sideways,
        frozenset(),
        best,
        frozenset(),
        incumbent_eval=incumbent,
        incumbent_missing_jump_frames=frozenset(),
    )

    repaired_interaction_but_lost_jump = opt.Evaluation(
        100.0, state, True, frozenset()
    )
    assert not opt._local_candidate_better(
        repaired_interaction_but_lost_jump,
        frozenset((10,)),
        best,
        frozenset(),
        incumbent_eval=incumbent,
        incumbent_missing_jump_frames=frozenset((10,)),
    )


def test_list_objects_advertises_supported_interaction_selectors() -> None:
    level = make_level(
        "0^80,100!11^300,100,120,100!"
        "9^85,100,0,0,20,20,1,0,0!"
        "9^60,60,0,1,19,20,0,0,0"
    )
    listing = opt.format_level_objects(level)

    assert "interaction=gold:0" in listing
    assert "interaction=switch:0 or exit:0.switch" in listing
    assert "interaction=testdoor:0" in listing
    assert "testdoor:1" in listing
    assert "required interaction unsupported" in listing


def test_cli_require_interaction_writes_a_verified_replay(
    tmp_path, monkeypatch, capsys
) -> None:
    level_string = f"{EMPTY_MAP}|5^100,100!0^83.95,100"
    source = [InputFrame(), InputFrame()]
    input_path = tmp_path / "source.txt"
    output_path = tmp_path / "optimised.txt"
    input_path.write_text(
        f"$Local interaction#tests##{level_string}#{encode_complex_replay(source)}#\n",
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
            "--require-interaction",
            "gold:0",
            "--output",
            str(output_path),
        ],
    )

    opt.main()
    capsys.readouterr()

    combined = parse_combined_level_replay(output_path.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string)
    state = simulate_through_frame(level, replay.frames, 1)
    assert state.static_state.collected_gold_mask == 1


def test_malformed_static_record_does_not_shift_later_mask_identity() -> None:
    level = make_level("0^999!0^83.95,100")
    with pytest.raises(ValueError, match="expected 2"):
        opt.resolve_interaction_requirement(level, "gold:0")

    requirement = opt.resolve_interaction_requirement(level, "gold:1")
    atom = requirement.alternatives[0]
    assert atom.type_index == 1
    assert atom.state_index == 0

    state = simulate_through_frame(
        level,
        [InputFrame(left=True), InputFrame()],
        1,
    )
    assert state.static_state.collected_gold_mask == 1
    assert not opt.missing_interaction_requirements((requirement,), state)


def test_physics_pruning_keeps_lower_scoring_interaction_repair() -> None:
    level = make_level("0^83.95,100")
    requirement = opt.resolve_interaction_requirement(level, "gold:0")

    optimised, result = opt.optimise_local_windows(
        level,
        [InputFrame(), InputFrame()],
        target_frame=1,
        range_start=0,
        range_end=0,
        objective_name="max-x",
        window_size=1,
        passes=1,
        local_inputs="direction",
        physics_prune=True,
        required_interactions=(requirement,),
        progress=None,
    )

    assert optimised[0].left
    assert result.state.static_state.collected_gold_mask == 1


def test_interaction_in_sparse_window_gap_counts() -> None:
    level = make_level("0^83.95,100")
    frames = [InputFrame(left=True), InputFrame(), InputFrame()]
    requirement = opt.resolve_interaction_requirement(level, "gold:0")

    state_after_first_mutable_frame = simulate_through_frame(level, frames, 0)
    assert state_after_first_mutable_frame.static_state.collected_gold_mask == 0

    result = opt.evaluate_frame_set_candidate(
        level,
        level.initial_state(),
        frames,
        (0, 2),
        (InputFrame(left=True), InputFrame()),
        target_frame=2,
        objective=opt.objective_function("max-x"),
        required_interactions=(requirement,),
    )

    # Fixed frame 1 lies in the sparse gap and performs the actual contact.
    assert result.state.static_state.collected_gold_mask == 1
    assert not result.missing_interactions


def test_parser_accepts_repeatable_interaction_requirements() -> None:
    args = opt.build_parser().parse_args(
        [
            "local",
            "input.txt",
            "--require-interaction",
            "gold:2",
            "--require-interaction",
            "switch:any",
            "--require-reference-interactions",
        ]
    )
    assert args.require_interaction == ["gold:2", "switch:any"]
    assert args.require_reference_interactions


def test_cli_impossible_requirement_writes_no_output(tmp_path, monkeypatch) -> None:
    level_string = f"{EMPTY_MAP}|5^100,100!0^300,100"
    source = [InputFrame(), InputFrame()]
    input_path = tmp_path / "source.txt"
    output_path = tmp_path / "optimised.txt"
    input_path.write_text(
        f"$Impossible interaction#tests##{level_string}#"
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
            "--require-interaction",
            "gold:0",
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit, match=r"remaining: gold:0"):
        opt.main()
    assert not output_path.exists()


def test_cli_reference_interactions_are_derived_after_retime(
    tmp_path, monkeypatch
) -> None:
    level_string = f"{EMPTY_MAP}|5^100,100!0^116.15,100"
    level = parse_level_string(level_string)
    source = [
        InputFrame(),
        InputFrame(right=True),
        InputFrame(right=True),
        InputFrame(),
        InputFrame(),
    ]
    assert simulate_through_frame(
        level, source, 2
    ).static_state.collected_gold_mask == 0

    input_path = tmp_path / "source.txt"
    output_path = tmp_path / "optimised.txt"
    input_path.write_text(
        f"$Post-retime reference#tests##{level_string}#"
        f"{encode_complex_replay(source)}#\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "local", str(input_path),
            "--retime",
            "1:-1",
            "--target-frame",
            "2",
            "--range",
            "0:0",
            "--objective",
            "min-x",
            "--window",
            "1",
            "--passes",
            "1",
            "--require-reference-interactions",
            "--output",
            str(output_path),
        ],
    )

    opt.main()
    combined = parse_combined_level_replay(output_path.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    assert replay.frames[0].right
    assert simulate_through_frame(
        level, replay.frames, 2
    ).static_state.collected_gold_mask == 1


def test_malformed_static_records_do_not_shift_later_interaction_mask_indices() -> None:
    level = make_level(
        "!".join(
            (
                # Public selectors still count these records, but StaticWorld
                # allocates no mask bit for their invalid parameter shapes.
                "0^70,100,999",
                "0^83.95,100",
                "11^300,100,90",
                "11^320,100,115,100",
            )
        )
    )

    with pytest.raises(ValueError, match=r"gold:0 has 3 parameters"):
        opt.resolve_interaction_requirement(level, "gold:0")
    with pytest.raises(ValueError, match=r"exit:0 has 3 parameters"):
        opt.resolve_interaction_requirement(level, "switch:0")

    gold = opt.resolve_interaction_requirement(level, "gold:1")
    switch = opt.resolve_interaction_requirement(level, "switch:1")
    assert gold.alternatives[0].state_index == 0
    assert switch.alternatives[0].state_index == 0
    assert [atom.label for atom in opt.resolve_interaction_requirement(
        level, "gold:any"
    ).alternatives] == ["gold:1"]

    state = level.initial_state()
    state.static_state.collected_gold_mask = 1
    state.static_state.open_exit_mask = 1
    assert not opt.missing_interaction_requirements((gold, switch), state)


def test_physics_pruning_keeps_lower_scoring_interaction_repair_branches() -> None:
    level = make_level("0^83.95,100")
    requirement = opt.resolve_interaction_requirement(level, "gold:0")

    optimised, result = opt.optimise_local_windows(
        level,
        [InputFrame(), InputFrame()],
        target_frame=1,
        range_start=0,
        range_end=0,
        objective_name="max-x",
        window_size=1,
        passes=1,
        local_inputs="direction",
        physics_prune=True,
        required_interactions=(requirement,),
        progress=None,
    )

    assert optimised[0].left
    assert result.state.static_state.collected_gold_mask == 1


def test_cli_interaction_failure_leaves_existing_output_unchanged(
    tmp_path, monkeypatch, capsys
) -> None:
    level_string = f"{EMPTY_MAP}|5^100,100!0^300,100"
    input_path = tmp_path / "source.txt"
    output_path = tmp_path / "optimised.txt"
    input_path.write_text(
        f"$Impossible interaction#tests##{level_string}#"
        f"{encode_complex_replay([InputFrame(), InputFrame()])}#\n",
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
            "1",
            "--range",
            "0:0",
            "--window",
            "1",
            "--passes",
            "1",
            "--require-interaction",
            "gold:0",
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit, match=r"remaining: gold:0"):
        opt.main()
    capsys.readouterr()
    assert output_path.read_text(encoding="utf-8") == "keep this output\n"


def test_cli_reference_interactions_are_derived_after_retime(
    tmp_path, monkeypatch, capsys
) -> None:
    level_string = f"{EMPTY_MAP}|5^100,100!0^83.95,100"
    source = [
        InputFrame(),
        InputFrame(left=True),
        InputFrame(),
        InputFrame(),
    ]
    source_level = parse_level_string(level_string)
    assert (
        simulate_through_frame(source_level, source, 2)
        .static_state.collected_gold_mask
        == 1
    )

    input_path = tmp_path / "source.txt"
    output_path = tmp_path / "optimised.txt"
    input_path.write_text(
        f"$Post-retime reference#tests##{level_string}#"
        f"{encode_complex_replay(source)}#\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_replay.py",
            "local", str(input_path),
            "--retime",
            "1:+1",
            "--target-frame",
            "2",
            "--range",
            "0:0",
            "--window",
            "1",
            "--passes",
            "1",
            "--require-reference-interactions",
            "--output",
            str(output_path),
        ],
    )

    opt.main()
    capsys.readouterr()

    combined = parse_combined_level_replay(output_path.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    output_level = parse_level_string(combined.level_string)
    state = simulate_through_frame(output_level, replay.frames, 2)

    # Retiming moves the source's left press from frame 1 to frame 2. The gold
    # is therefore not yet collected at the target frame and must not become a
    # reference-derived requirement. Local max-x search is free to move right.
    assert replay.frames[0].right
    assert state.static_state.collected_gold_mask == 0
