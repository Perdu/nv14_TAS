from __future__ import annotations

import pickle
from concurrent.futures import Future
from dataclasses import fields, replace

import pytest

import nv14_auto as auto
import nv14_auto_parallel as parallel
from nv14_engine import InputFrame


def _point(tick: int, *, complete: bool = True) -> auto.CompactTracePoint:
    return auto.CompactTracePoint(
        tick=tick,
        x=float(tick),
        y=100.0,
        vx=1.0,
        vy=0.0,
        player_state=0,
        in_air=False,
        near_wall=False,
        wall_x=0,
        floor_x=0,
        floor_y=0,
        previous_jump_held=False,
        jump_events=0,
        collected_gold_mask=0,
        exploded_mine_mask=0,
        open_exit_mask=int(complete),
        complete=complete,
        dead=False,
    )


def _frames(marker: int, length: int = 8) -> tuple[InputFrame, ...]:
    """Return a deterministic, compact replay body with a unique marker."""

    return tuple(
        InputFrame(
            left=bool(marker & (1 << (tick * 2))),
            right=bool(marker & (1 << (tick * 2 + 1))),
            jump=bool(marker & (1 << (tick + 16))),
        )
        for tick in range(length)
    )


def _candidate(
    marker: int,
    *,
    finish_tick: int = 8,
    distance: float = 1.0,
    mutations: tuple[str, ...] = (),
    sentinel_verified: bool = True,
) -> auto.AutoCandidate:
    body = _frames(marker, max(8, finish_tick))
    evaluation = auto.AutoEvaluation(
        finish_tick=finish_tick,
        dead_tick=None,
        last_tick=finish_tick,
        trace=(_point(finish_tick),),
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
        pre_finish_exit_distance=distance,
    )
    return auto.AutoCandidate(
        working_frames=body + (auto.NEUTRAL_INPUT,),
        evaluation=evaluation,
        origin="test",
        mutations=mutations,
        sentinel_verified=sentinel_verified,
    )


def _result(
    best: auto.AutoCandidate,
    *,
    sectional_elites: tuple[auto.AutoCandidate, ...] = (),
) -> auto.AutoResult:
    assert best.finish_tick is not None
    return auto.AutoResult(
        frames=best.frames,
        baseline_finish_tick=best.finish_tick,
        finish_tick=best.finish_tick,
        best=best,
        stats=auto.AutoStats(),
        diagnostics=(),
        objective=auto.AUTO_OBJECTIVE_SPEEDRUN,
        baseline_objective_value=-best.finish_tick,
        objective_value=-best.finish_tick,
        sectional_elites=sectional_elites,
    )


def test_sectional_prearchive_is_independent_of_the_live_beam() -> None:
    winner = _candidate(1, finish_tick=8)
    slower_section_donor = _candidate(
        2,
        finish_tick=10,
        mutations=("excellent corner, slow exit",),
    )
    search = object.__new__(auto._AutonomousSearch)
    search.config = auto.AutoConfig(objective=auto.AUTO_OBJECTIVE_SPEEDRUN)
    search.beam = [winner]
    search.sectional_elites = [winner]

    search._retain_sectional_candidate(slower_section_donor)

    assert slower_section_donor not in search.beam
    assert slower_section_donor in search.sectional_elites


def test_sectional_prearchive_is_bounded_completed_and_replay_deduplicated() -> None:
    candidates = tuple(
        _candidate(marker, finish_tick=20 + marker, distance=float(marker))
        for marker in range(1, 9)
    )
    duplicate_frames = _candidate(99, finish_tick=30, distance=9.0)
    better_duplicate = replace(
        duplicate_frames,
        evaluation=replace(
            duplicate_frames.evaluation,
            finish_tick=20,
            last_tick=20,
            pre_finish_exit_distance=0.5,
        ),
    )
    invalid = _candidate(100, finish_tick=12, sentinel_verified=False)
    incomplete = replace(
        _candidate(101, finish_tick=12),
        evaluation=auto.AutoEvaluation(
            finish_tick=None,
            dead_tick=None,
            last_tick=12,
            trace=(_point(12, complete=False),),
            successful_jumps=(),
            jump_edges=(),
            missed_jump_edges=(),
        ),
    )

    selected = auto._select_sectional_prearchive(
        (
            *reversed(candidates),
            duplicate_frames,
            invalid,
            incomplete,
            better_duplicate,
        ),
        objective=auto.AUTO_OBJECTIVE_SPEEDRUN,
        limit=5,
    )

    assert len(selected) == 5
    assert all(candidate.output_valid for candidate in selected)
    assert all(candidate.finish_tick is not None for candidate in selected)
    assert invalid not in selected
    assert incomplete not in selected
    assert duplicate_frames not in selected
    assert better_duplicate in selected
    assert len({auto._candidate_replay_key(candidate) for candidate in selected}) == 5

    selected_reversed = auto._select_sectional_prearchive(
        reversed(
            (
                *reversed(candidates),
                duplicate_frames,
                invalid,
                incomplete,
                better_duplicate,
            )
        ),
        objective=auto.AUTO_OBJECTIVE_SPEEDRUN,
        limit=5,
    )
    assert [auto._candidate_replay_key(item) for item in selected_reversed] == [
        auto._candidate_replay_key(item) for item in selected
    ]


def test_sectional_prearchive_retains_middle_only_route_diversity() -> None:
    """A distinct middle must survive common start/exit transition seams."""

    common_transitions = (1, 2, 3, 4, 5, 12, 18, 100, 101, 102, 103, 104)
    middle_distinct_transitions = (
        1,
        2,
        3,
        4,
        5,
        50,
        75,
        100,
        101,
        102,
        103,
        104,
    )
    outcome_elites = tuple(
        replace(
            _candidate(marker, finish_tick=120, distance=float(marker)),
            input_transitions=common_transitions,
        )
        for marker in range(1, 5)
    )
    common_middle = replace(
        _candidate(5, finish_tick=120, distance=5.0),
        input_transitions=common_transitions,
    )
    distinct_middle = replace(
        _candidate(6, finish_tick=120, distance=6.0),
        input_transitions=middle_distinct_transitions,
    )

    selected = auto._select_sectional_prearchive(
        (*outcome_elites, common_middle, distinct_middle),
        objective=auto.AUTO_OBJECTIVE_SPEEDRUN,
        limit=5,
    )

    assert len(selected) == 5
    assert distinct_middle in selected
    assert common_middle not in selected
    selected_reversed = auto._select_sectional_prearchive(
        reversed((*outcome_elites, common_middle, distinct_middle)),
        objective=auto.AUTO_OBJECTIVE_SPEEDRUN,
        limit=5,
    )
    assert [auto._candidate_replay_key(item) for item in selected_reversed] == [
        auto._candidate_replay_key(item) for item in selected
    ]


def test_auto_result_exposes_process_local_sectional_elites() -> None:
    winner = _candidate(1)
    donor = _candidate(2, finish_tick=10)

    assert _result(winner).sectional_elites == ()
    assert _result(winner, sectional_elites=(donor,)).sectional_elites == (donor,)


def test_native_profile_detects_a_short_middle_gain_between_route_fifths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipient = _candidate(1, finish_tick=201)
    donor = replace(
        _candidate(2, finish_tick=201),
        input_transitions=(98,),
    )
    recipient_analysis = object()

    class _WindowAnalysis:
        def __init__(self) -> None:
            self.windows: list[tuple[int, int]] = []

        def find_splice_alignment(
            self,
            _recipient_analysis,
            *,
            candidate_start_tick,
            candidate_end_tick,
            **_kwargs,
        ):
            self.windows.append((candidate_start_tick, candidate_end_tick))
            centre = (candidate_start_tick + candidate_end_tick) // 2
            if candidate_start_tick <= 90 <= candidate_end_tick and centre < 98:
                return (90, 90, 0, 0.0, True, True, 0, 6)
            if candidate_start_tick <= 106 <= candidate_end_tick and centre > 98:
                return (106, 109, 3, 0.0, True, True, 0, 6)
            return None

    donor_analysis = _WindowAnalysis()
    monkeypatch.setattr(
        parallel._auto_policy,
        "_native_trace_analysis",
        lambda evaluation: (
            donor_analysis
            if evaluation is donor.evaluation
            else recipient_analysis
        ),
    )

    profile = parallel._native_sectional_donor_profile(
        recipient,
        donor,
        auto.AutoConfig(iterations=1),
    )

    assert profile is not None
    assert profile.objective_gain == profile.predicted_time_gain == 3
    assert profile.entry_donor_tick == 90
    assert profile.exit_donor_tick == 106
    assert len(donor_analysis.windows) <= parallel._SECTIONAL_PROFILE_MAX_WINDOWS
    assert any(start <= 98 <= end for start, end in donor_analysis.windows)


def test_no_plan_pair_skips_native_replay_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipient_candidate = _candidate(1, finish_tick=8)
    donor_candidate = _candidate(2, finish_tick=9)
    recipient = parallel._AutoPopulationMember(
        member_id=1,
        result=_result(recipient_candidate),
        parent_member_ids=(),
        generation=1,
        mutations=(),
    )
    donor = parallel._AutoPopulationMember(
        member_id=2,
        result=_result(donor_candidate),
        parent_member_ids=(),
        generation=1,
        mutations=(),
    )

    def no_plans(*_args, **kwargs):
        kwargs["anchor_runs_observer"](())
        return ()

    def unexpected_reconstruction(*_args, **_kwargs):
        raise AssertionError("no-plan pair reconstructed a native replay")

    monkeypatch.setattr(parallel, "find_splice_section_plans", no_plans)
    monkeypatch.setattr(parallel, "_worker_cancelled", lambda _task=None: False)
    monkeypatch.setattr(
        parallel,
        "_native_splice_parent",
        unexpected_reconstruction,
    )
    task = parallel._SpliceWorkerTask(
        recipient=recipient,
        donor=donor,
        recipient_trace=parallel.prepare_splice_trace(
            recipient.result.best.evaluation,
            recipient.result.frames,
        ),
        donor_trace=parallel.prepare_splice_trace(
            donor.result.best.evaluation,
            donor.result.frames,
        ),
        run_index=1,
        task_id=parallel._SPLICE_TASK_ID_BASE + 1,
    )

    output = parallel._run_splice_worker_in_session(
        task,
        parallel._AutoWorkerContext(object(), auto.AutoConfig(iterations=1)),
    )

    assert output.candidates == ()
    assert output.splice_stats.rejection_counts == {"no-corridors": 1}


def test_worker_donor_selector_is_bounded_lightweight_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    winner = _candidate(1, finish_tick=8)
    nearest = replace(
        _candidate(
            2,
            finish_tick=9,
            distance=7.0,
            mutations=("fast middle",),
        ),
        evaluation=replace(
            _candidate(2, finish_tick=9).evaluation,
            final_gold_mask=0b101,
            gold_bonus_ticks=160,
            pre_finish_exit_distance=7.0,
        ),
    )
    duplicate_worse = replace(
        nearest,
        evaluation=replace(
            nearest.evaluation,
            pre_finish_exit_distance=8.0,
        ),
        mutations=("same replay, worse tie-break",),
    )
    second = _candidate(
        3,
        finish_tick=10,
        distance=2.5,
        mutations=("corner jump",),
    )
    third = _candidate(4, finish_tick=11, mutations=("late route",))
    invalid = _candidate(5, finish_tick=9, sentinel_verified=False)
    malformed_finish = replace(
        _candidate(6, finish_tick=9),
        evaluation=replace(
            _candidate(6, finish_tick=9).evaluation,
            finish_tick=20,
            last_tick=20,
        ),
    )
    result = replace(
        _result(winner),
        beam=(third,),
        sectional_elites=(
            winner,
            duplicate_worse,
            invalid,
            malformed_finish,
            second,
            nearest,
        ),
    )
    config = auto.AutoConfig(objective=auto.AUTO_OBJECTIVE_SPEEDRUN)
    monkeypatch.setattr(
        parallel,
        "_native_sectional_donor_profile",
        lambda *_args, **_kwargs: None,
    )

    selected = parallel._select_worker_splice_donors(result, config, limit=2)
    reversed_result = replace(
        result,
        sectional_elites=tuple(reversed(result.sectional_elites)),
        beam=tuple(reversed(result.beam)),
    )
    selected_reversed = parallel._select_worker_splice_donors(
        reversed_result,
        config,
        limit=2,
    )

    assert selected == selected_reversed
    assert len(selected) == 2
    assert selected[0] == parallel.AutoSpliceDonor(
        frames=nearest.frames,
        finish_tick=9,
        objective_value=-9,
        pre_finish_exit_distance=7.0,
        mutations=("fast middle",),
        gold_mask=0b101,
        gold_bonus_ticks=160,
    )
    assert selected[1].frames == second.frames
    assert all(donor.frames != winner.frames for donor in selected)
    assert all(len(donor.frames) == donor.finish_tick for donor in selected)
    assert parallel._select_worker_splice_donors(result, config, limit=0) == ()
    assert parallel._select_worker_splice_donors(result, config, limit=-1) == ()


def test_auto_splice_donor_payload_contains_no_heavyweight_search_state() -> None:
    donor = parallel.AutoSpliceDonor(
        frames=_frames(7),
        finish_tick=8,
        objective_value=-8,
        pre_finish_exit_distance=float("inf"),
        mutations=("sectional",),
        gold_mask=3,
        gold_bonus_ticks=160,
    )

    assert tuple(field.name for field in fields(donor)) == (
        "frames",
        "finish_tick",
        "objective_value",
        "pre_finish_exit_distance",
        "mutations",
        "gold_mask",
        "gold_bonus_ticks",
    )
    assert not hasattr(donor, "__dict__")
    for heavyweight_name in ("evaluation", "trace", "alignment", "beam"):
        assert not hasattr(donor, heavyweight_name)
    assert pickle.loads(pickle.dumps(donor)) == donor


def test_auto_worker_clears_heavy_archives_after_building_splice_donors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    winner = _candidate(1, finish_tick=8)
    donor = _candidate(
        2,
        finish_tick=10,
        distance=4.5,
        mutations=("retained section",),
    )
    result = replace(
        _result(winner),
        beam=(winner, donor),
        sectional_elites=(winner, donor),
    )
    config = auto.AutoConfig(iterations=1, seed=123)
    parallel._initialise_auto_worker(
        parallel._AutoWorkerContext(object(), config),
        None,
        None,
        None,
    )

    def fake_search(level, frames, search_config, **kwargs):
        assert search_config.seed == 456
        return result

    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)
    monkeypatch.setattr(
        parallel,
        "_native_sectional_donor_profile",
        lambda *_args, **_kwargs: None,
    )
    output = parallel._run_auto_worker(
        parallel._AutoWorkerTask(
            frames=winner.frames,
            seed=456,
            run_index=2,
            worker_index=3,
            task_id=99,
            parent_member_id=7,
            offspring_index=2,
        )
    )

    assert output.result.beam == ()
    assert output.result.sectional_elites == ()
    assert output.splice_donors == (
        parallel.AutoSpliceDonor(
            frames=donor.frames,
            finish_tick=10,
            objective_value=-10,
            pre_finish_exit_distance=4.5,
            mutations=("retained section",),
        ),
    )
    assert (
        output.seed,
        output.run_index,
        output.worker_index,
        output.task_id,
        output.parent_member_id,
        output.offspring_index,
    ) == (456, 2, 3, 99, 7, 2)
    assert pickle.loads(pickle.dumps(output)) == output


def test_canonical_sectional_donor_verifies_frames_and_all_scalar_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = replace(
        _candidate(7, finish_tick=8, distance=3.25),
        evaluation=replace(
            _candidate(7, finish_tick=8, distance=3.25).evaluation,
            final_gold_mask=0b1010,
            gold_bonus_ticks=160,
        ),
    )
    donor = parallel.AutoSpliceDonor(
        frames=candidate.frames,
        finish_tick=8,
        objective_value=-8,
        pre_finish_exit_distance=3.25,
        mutations=("worker archive",),
        gold_mask=0b1010,
        gold_bonus_ticks=160,
    )
    calls: list[tuple[object, tuple[InputFrame, ...], dict[str, object]]] = []

    def verify(level, frames, **kwargs):
        calls.append((level, tuple(frames), kwargs))
        return candidate.evaluation

    level = object()
    monkeypatch.setattr(parallel, "verify_trimmed_replay", verify)

    assert parallel._canonical_sectional_donor(
        level,
        donor,
        auto.AUTO_OBJECTIVE_SPEEDRUN,
    ) is candidate.evaluation
    assert calls == [
        (
            level,
            candidate.frames,
            {
                "expected_finish_tick": 8,
                "expected_gold_mask": 0b1010,
                "expected_gold_bonus_ticks": 160,
            },
        )
    ]

    calls.clear()
    assert parallel._canonical_sectional_donor(
        level,
        replace(donor, finish_tick=7),
        auto.AUTO_OBJECTIVE_SPEEDRUN,
    ) is None
    assert calls == []

    assert parallel._canonical_sectional_donor(
        level,
        replace(donor, objective_value=-9),
        auto.AUTO_OBJECTIVE_SPEEDRUN,
    ) is None
    assert parallel._canonical_sectional_donor(
        level,
        replace(donor, pre_finish_exit_distance=3.5),
        auto.AUTO_OBJECTIVE_SPEEDRUN,
    ) is None


def test_canonical_sectional_donor_normalises_missing_distance_to_infinity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate(8, finish_tick=8)
    evaluation = replace(
        candidate.evaluation,
        pre_finish_exit_distance=None,
    )
    donor = parallel.AutoSpliceDonor(
        frames=candidate.frames,
        finish_tick=8,
        objective_value=-8,
        pre_finish_exit_distance=float("inf"),
        mutations=(),
    )
    monkeypatch.setattr(
        parallel,
        "verify_trimmed_replay",
        lambda *args, **kwargs: evaluation,
    )

    assert parallel._canonical_sectional_donor(
        object(),
        donor,
        auto.AUTO_OBJECTIVE_SPEEDRUN,
    ) is evaluation


class _SteppedPool:
    submitted_tasks: list[object] = []
    work: dict[Future, tuple[object, object]] = {}

    def __init__(self, *args, initializer=None, initargs=(), **kwargs) -> None:
        type(self).submitted_tasks = []
        type(self).work = {}
        if initializer is not None:
            initializer(*initargs)

    def submit(self, function, task):
        future = Future()
        type(self).submitted_tasks.append(task)
        type(self).work[future] = (function, task)
        return future

    def shutdown(self, wait=True, cancel_futures=False) -> None:
        return None


def _stepped_wait(futures, timeout=None, return_when=None):
    pending = [future for future in futures if not future.done()]
    if not pending:
        done = {future for future in futures if future.done()}
        return done, set(futures) - done
    future = min(pending, key=lambda item: _SteppedPool.work[item][1].task_id)
    function, task = _SteppedPool.work[future]
    try:
        future.set_result(function(task))
    except BaseException as exc:  # mirror Future execution semantics
        future.set_exception(exc)
    return {future}, set(futures) - {future}


def test_sectional_donors_schedule_independent_donor_only_jobs_including_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neutral = InputFrame()
    worker_results: list[auto.AutoResult] = []
    donor_evaluations: dict[tuple[InputFrame, ...], auto.AutoEvaluation] = {}
    prepared: list[tuple[auto.AutoEvaluation, tuple[InputFrame, ...]]] = []
    real_prepare = parallel.prepare_splice_trace

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        if config.iterations == 0:
            return _result(_candidate(0, finish_tick=10, distance=20.0))
        worker_number = len(worker_results) + 1
        winner = _candidate(
            worker_number,
            finish_tick=10,
            distance=float(worker_number),
            mutations=(f"winner {worker_number}",),
        )
        donor = _candidate(
            worker_number + 10,
            finish_tick=12,
            distance=float(10 + worker_number),
            mutations=(f"section {worker_number}",),
        )
        donor_evaluations[donor.frames] = donor.evaluation
        result = replace(
            _result(winner),
            beam=(winner, donor),
            sectional_elites=(winner, donor),
        )
        worker_results.append(result)
        return result

    def verify_donor(level, frames, **kwargs):
        evaluation = donor_evaluations[tuple(frames)]
        assert kwargs == {
            "expected_finish_tick": evaluation.finish_tick,
            "expected_gold_mask": evaluation.final_gold_mask,
            "expected_gold_bonus_ticks": evaluation.gold_bonus_ticks,
        }
        return evaluation

    def counting_prepare(evaluation, frames):
        prepared.append((evaluation, tuple(frames)))
        return real_prepare(evaluation, frames)

    def no_plans(*args, **kwargs):
        observer = kwargs.get("anchor_runs_observer")
        if observer is not None:
            observer(())
        return ()

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _SteppedPool)
    monkeypatch.setattr(parallel, "wait", _stepped_wait)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)
    monkeypatch.setattr(parallel, "verify_trimmed_replay", verify_donor)
    monkeypatch.setattr(parallel, "prepare_splice_trace", counting_prepare)
    monkeypatch.setattr(parallel, "find_splice_section_plans", no_plans)
    monkeypatch.setattr(
        parallel,
        "_native_sectional_donor_profile",
        lambda *_args, **_kwargs: None,
    )

    status: list[str] = []
    campaign = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 10,
        auto.AutoConfig(iterations=1, beam_width=2, seed=73),
        workers=2,
        runs=1,
        search=fake_search,
        status=status.append,
    )

    splice_tasks = [
        task
        for task in _SteppedPool.submitted_tasks
        if isinstance(task, parallel._SpliceWorkerTask)
    ]
    assert campaign.completed_runs == 1
    assert len(splice_tasks) == 6
    assert len(prepared) == 4
    assert len({id(evaluation) for evaluation, _frames in prepared}) == 4

    main_pairs = {
        (
            task.recipient.member_id,
            task.donor_source.owner_member_id,
            task.donor_source.donor_index,
        )
        for task in splice_tasks
        if task.donor_source is not None
    }
    ordinary_ids = {task.recipient.member_id for task in splice_tasks}
    assert len(ordinary_ids) == 2
    assert main_pairs == {
        (recipient, owner, donor_index)
        for recipient in ordinary_ids
        for owner in ordinary_ids
        for donor_index in (0, 1)
        if not (recipient == owner and donor_index == 0)
    }
    assert all(
        task.recipient.result.frames not in donor_evaluations
        for task in splice_tasks
    )
    assert {
        task.recipient.member_id
        for task in splice_tasks
        if task.donor_source is not None
        and task.donor_source.is_sectional
        and task.recipient.member_id == task.donor_source.owner_member_id
    } == ordinary_ids
    assert any("pairs=6," in message for message in status)


def test_serial_sectional_donors_each_receive_an_independent_pair_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    winner = _candidate(1, finish_tick=8)
    result = _result(winner)
    donor_candidates = (
        _candidate(2, finish_tick=9),
        _candidate(3, finish_tick=10),
    )
    donors = tuple(
        parallel.AutoSpliceDonor(
            frames=candidate.frames,
            finish_tick=candidate.finish_tick,
            objective_value=-candidate.finish_tick,
            pre_finish_exit_distance=(
                candidate.evaluation.pre_finish_exit_distance
                if candidate.evaluation.pre_finish_exit_distance is not None
                else float("inf")
            ),
            mutations=candidate.mutations,
        )
        for candidate in donor_candidates
    )
    evaluations = {
        donor.frames: candidate.evaluation
        for donor, candidate in zip(donors, donor_candidates)
    }
    tasks: list[parallel._SpliceWorkerTask] = []

    monkeypatch.setattr(
        parallel,
        "_canonical_sectional_donor",
        lambda level, donor, objective: evaluations[donor.frames],
    )

    def fake_pair(task, context):
        tasks.append(task)
        return parallel._SpliceWorkerResult(
            task_id=task.task_id,
            run_index=task.run_index,
            recipient_member_id=task.recipient.member_id,
            donor_member_id=task.donor_source.owner_member_id,
            donor_index=task.donor_source.donor_index,
            candidates=(),
            splice_stats=parallel._SpliceRoundStats(
                pairs=1,
                sectional_pairs=1,
            ),
            auto_stats=auto.AutoStats(),
        )

    monkeypatch.setattr(
        parallel, "_run_splice_worker_in_session", fake_pair
    )

    child, stats, repair_stats, interrupted = (
        parallel._run_serial_sectional_splices(
            object(),
            result,
            donors,
            auto.AutoConfig(iterations=1),
            run_index=4,
        )
    )

    assert child is None
    assert not interrupted
    assert repair_stats == auto.AutoStats()
    assert stats.sectional_donors == 2
    assert stats.pairs == stats.sectional_pairs == 2
    assert [task.donor_source.donor_index for task in tasks] == [1, 2]
    assert all(task.recipient is task.donor for task in tasks)


def test_serial_interrupt_retains_an_earlier_verified_sectional_splice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    winner = _candidate(1, finish_tick=10)
    result = _result(winner)
    donor_candidates = (
        _candidate(2, finish_tick=11),
        _candidate(3, finish_tick=12),
    )
    donors = tuple(
        parallel.AutoSpliceDonor(
            frames=candidate.frames,
            finish_tick=candidate.finish_tick,
            objective_value=-candidate.finish_tick,
            pre_finish_exit_distance=(
                candidate.evaluation.pre_finish_exit_distance
                if candidate.evaluation.pre_finish_exit_distance is not None
                else float("inf")
            ),
            mutations=candidate.mutations,
        )
        for candidate in donor_candidates
    )
    donor_evaluations = {
        donor.frames: candidate.evaluation
        for donor, candidate in zip(donors, donor_candidates)
    }
    improved = _candidate(9, finish_tick=9, distance=0.5)
    pair_calls = 0

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        return result

    monkeypatch.setattr(
        parallel,
        "_select_worker_splice_donors",
        lambda result, config: donors,
    )
    monkeypatch.setattr(
        parallel,
        "_canonical_sectional_donor",
        lambda level, donor, objective: donor_evaluations[donor.frames],
    )

    def fake_pair(task, context):
        nonlocal pair_calls
        pair_calls += 1
        if pair_calls == 2:
            raise KeyboardInterrupt
        proposal = parallel._SpliceWorkerCandidate(
            candidate=improved,
            recipient_entry_tick=1,
            recipient_exit_tick=6,
            donor_entry_tick=1,
            donor_exit_tick=5,
            predicted_time_gain=1,
            donor_index=task.donor_source.donor_index,
        )
        return parallel._SpliceWorkerResult(
            task_id=task.task_id,
            run_index=task.run_index,
            recipient_member_id=task.recipient.member_id,
            donor_member_id=task.donor_source.owner_member_id,
            donor_index=task.donor_source.donor_index,
            candidates=(proposal,),
            splice_stats=parallel._SpliceRoundStats(
                pairs=1,
                sectional_pairs=1,
                canonical=1,
            ),
            auto_stats=auto.AutoStats(local_simulations=7),
        )

    monkeypatch.setattr(
        parallel, "_run_splice_worker_in_session", fake_pair
    )

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        winner.frames,
        auto.AutoConfig(iterations=1, seed=17),
        workers=1,
        runs=1,
        search=fake_search,
    )

    assert pair_calls == 2
    assert campaign.interrupted
    assert campaign.completed_searches == 1
    assert campaign.completed_runs == 0
    assert campaign.result.finish_tick == improved.finish_tick
    assert campaign.result.frames == improved.frames
    assert any(
        "sectional #1" in mutation
        for mutation in campaign.result.best.mutations
    )


# Coordinator validation and scheduling tests follow below.  They deliberately
# exercise only the small v3.01 helpers rather than running a native search.
