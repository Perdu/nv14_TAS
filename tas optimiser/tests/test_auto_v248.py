from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import Future
from dataclasses import replace
from queue import Queue
from threading import Event, Thread, current_thread
from types import SimpleNamespace

import nv14_auto_parallel as parallel
from nv14_auto import (
    AUTO_OBJECTIVE_SPEEDRUN,
    AutoCandidate,
    AutoConfig,
    AutoEvaluation,
    AutoProgress,
    AutoResult,
    AutoStats,
    CompactTracePoint,
)
from nv14_engine import InputFrame


def _point(tick: int) -> CompactTracePoint:
    return CompactTracePoint(
        tick=tick,
        x=0.0,
        y=0.0,
        vx=0.0,
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
        open_exit_mask=1,
        complete=True,
        dead=False,
    )


def _result(
    tick: int,
    proximity: float,
    *,
    marker: InputFrame | None = None,
    replay_id: int | None = None,
    baseline_tick: int | None = None,
    seed: int = 0,
    iterations: int = 0,
) -> AutoResult:
    marker = InputFrame() if marker is None else marker
    evaluation = AutoEvaluation(
        finish_tick=tick,
        dead_tick=None,
        last_tick=tick,
        trace=(_point(tick),),
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
        final_gold_mask=0,
        gold_bonus_ticks=0,
        pre_finish_exit_distance=proximity,
    )
    if replay_id is None:
        frames = (marker,) * tick
    else:
        # Encode a stable exact-replay identity without relying on
        # jump_trigger, which is not part of the serialized held-input body.
        value = replay_id
        prefix: list[InputFrame] = []
        for _index in range(min(4, tick)):
            bits = value & 0b111
            prefix.append(
                InputFrame(
                    left=bool(bits & 0b001),
                    right=bool(bits & 0b010),
                    jump=bool(bits & 0b100),
                )
            )
            value >>= 3
        frames = tuple(prefix) + (marker,) * (tick - len(prefix))
    candidate = AutoCandidate(
        working_frames=frames + (InputFrame(),),
        evaluation=evaluation,
        origin="source" if baseline_tick is None else "test",
        mutations=() if baseline_tick is None else (f"seed {seed}",),
    )
    baseline = tick if baseline_tick is None else baseline_tick
    return AutoResult(
        frames=frames,
        baseline_finish_tick=baseline,
        finish_tick=tick,
        best=candidate,
        stats=AutoStats(macro_candidates=iterations, macro_evaluations=iterations),
        diagnostics=(f"test seed {seed}",),
        objective=AUTO_OBJECTIVE_SPEEDRUN,
        baseline_objective_value=-baseline,
        objective_value=-tick,
    )


def _member(member_id: int, parent_id: int, rank: int) -> parallel._AutoPopulationMember:
    return parallel._AutoPopulationMember(
        member_id=member_id,
        result=_result(100, float(rank), replay_id=member_id),
        parent_member_ids=(parent_id,),
        generation=2,
        mutations=(),
        recipient_member_id=member_id,
        primary_family_id=parent_id,
    )


def test_v303_fixed_selection_caps_recipient_and_primary_family() -> None:
    # Natural top four would all come from family A, including three variants
    # of the same current recipient. Strict selection instead keeps four
    # current recipient routes and no more than two from either real family.
    members = (
        replace(_member(1, 10, 1), recipient_member_id=101),
        replace(_member(2, 10, 2), recipient_member_id=101),
        replace(_member(3, 10, 3), recipient_member_id=101),
        replace(_member(4, 10, 4), recipient_member_id=102),
        replace(_member(5, 20, 5), recipient_member_id=201),
        replace(_member(6, 20, 6), recipient_member_id=202),
        replace(_member(7, 30, 7), recipient_member_id=301),
        replace(_member(8, 40, 8), recipient_member_id=401),
    )
    selected = parallel._select_population_survivors(
        members, 4, enforce_parent_diversity=True
    )
    assert [member.member_id for member in selected] == [1, 4, 5, 6]
    assert len({member.selection_recipient_member_id for member in selected}) == 4
    assert sorted(
        Counter(member.selection_primary_family_id for member in selected).values()
    ) == [2, 2]


def test_v303_fixed_selection_prefers_recipient_and_splice_niche_breadth() -> None:
    splice_one = parallel._AutoPopulationMember(
        member_id=1,
        result=_result(99, 1.0, replay_id=1),
        parent_member_ids=(10, 20),
        generation=3,
        mutations=("splice one",),
        recipient_member_id=10,
        primary_family_id=100,
        splice_parent_pair=(10, 20),
        splice_interval=(20, 40, 22, 39),
    )
    same_pair = parallel._AutoPopulationMember(
        member_id=2,
        result=_result(99, 2.0, replay_id=2),
        parent_member_ids=(10, 20),
        generation=3,
        mutations=("splice two",),
        recipient_member_id=10,
        primary_family_id=100,
        splice_parent_pair=(10, 20),
        splice_interval=(50, 70, 53, 69),
    )
    same_interval = parallel._AutoPopulationMember(
        member_id=3,
        result=_result(99, 3.0, replay_id=3),
        parent_member_ids=(30, 40),
        generation=3,
        mutations=("splice three",),
        recipient_member_id=30,
        primary_family_id=200,
        splice_parent_pair=(30, 40),
        splice_interval=(20, 40, 22, 39),
    )
    ordinary = _member(4, 50, 4)

    selected = parallel._select_population_survivors(
        (splice_one, same_pair, same_interval, ordinary),
        3,
        enforce_parent_diversity=True,
    )

    # The second splice from recipient 10 waits behind the best member from a
    # different recipient. The ordinary candidate supplies the third route.
    assert [member.member_id for member in selected] == [1, 3, 4]
    assert selected[0].parent_member_ids == (10, 20)


def _splice_member(
    member_id: int,
    *,
    recipient_id: int,
    family_id: int,
    finish_tick: int = 99,
    proximity: float = 1.0,
    interval: tuple[int, int, int, int] = (12, 36, 14, 34),
    replay_id: int | None = None,
) -> parallel._AutoPopulationMember:
    donor_id = 10_000 + member_id
    return parallel._AutoPopulationMember(
        member_id=member_id,
        result=_result(
            finish_tick,
            proximity,
            replay_id=member_id if replay_id is None else replay_id,
        ),
        parent_member_ids=(recipient_id, donor_id),
        generation=3,
        mutations=("splice",),
        recipient_member_id=recipient_id,
        primary_family_id=family_id,
        splice_parent_pair=tuple(sorted((recipient_id, donor_id))),
        splice_interval=interval,
    )


def _eight_population_recipients() -> tuple[parallel._AutoPopulationMember, ...]:
    return tuple(
        replace(
            _member(member_id, 100 + (member_id - 1) // 2, member_id),
            recipient_member_id=member_id,
        )
        for member_id in range(1, 9)
    )


def test_v303_adaptive_population_adds_up_to_four_competitive_niches() -> None:
    ordinary = _eight_population_recipients()
    expected_sizes = (4, 5, 6, 7, 8, 8)
    for niche_count, expected_size in enumerate(expected_sizes):
        splices = tuple(
            _splice_member(
                100 + index,
                recipient_id=index + 1,
                family_id=100 + index // 2,
                proximity=float(index),
                interval=(12 * index, 12 * index + 24, 12 * index + 2, 12 * index + 22),
            )
            for index in range(niche_count)
        )
        selection = parallel._select_adaptive_population(
            (*ordinary, *splices),
            8,
        )
        assert len(selection.survivors) == expected_size
        assert selection.target == expected_size
        assert selection.competitive_splice_niches == min(niche_count, 4)
        assert len(
            {parallel._population_replay_key(member) for member in selection.survivors}
        ) == expected_size


def test_v303_population_counts_only_distinct_competitive_splice_niches() -> None:
    ordinary = _eight_population_recipients()
    same_niche_best = _splice_member(
        101,
        recipient_id=1,
        family_id=100,
        proximity=1.0,
        interval=(13, 35, 15, 33),
    )
    same_niche_shifted = _splice_member(
        102,
        recipient_id=1,
        family_id=100,
        proximity=2.0,
        interval=(18, 34, 20, 32),
    )
    distinct_recipient = _splice_member(
        103,
        recipient_id=3,
        family_id=101,
        proximity=3.0,
        interval=(13, 35, 15, 33),
    )
    selection = parallel._select_adaptive_population(
        (*ordinary, same_niche_best, same_niche_shifted, distinct_recipient),
        8,
    )
    assert selection.competitive_splice_niches == 2
    assert selection.target == 6
    assert same_niche_best in selection.survivors
    assert same_niche_shifted not in selection.survivors
    assert distinct_recipient in selection.survivors

    different_section_same_recipient = _splice_member(
        105,
        recipient_id=1,
        family_id=100,
        proximity=4.0,
        interval=(48, 72, 50, 70),
    )
    same_recipient_sections = parallel._select_adaptive_population(
        (*ordinary, same_niche_best, different_section_same_recipient),
        8,
    )
    # Both sections expand the target even though initial survivor selection
    # keeps only the better replay from current recipient 1. The added breadth
    # is filled from other recipient trajectories.
    assert same_recipient_sections.competitive_splice_niches == 2
    assert same_recipient_sections.target == 6
    assert same_recipient_sections.selected_splice_niches == 1

    ordinary_same_family = tuple(
        replace(member, primary_family_id=100)
        if member.member_id <= 3
        else member
        for member in ordinary
    )
    same_family_niches = parallel._select_adaptive_population(
        (
            *ordinary_same_family,
            same_niche_best,
            _splice_member(
                106,
                recipient_id=2,
                family_id=100,
                proximity=5.0,
                interval=(48, 72, 50, 70),
            ),
            _splice_member(
                107,
                recipient_id=3,
                family_id=100,
                proximity=6.0,
                interval=(84, 108, 86, 106),
            ),
        ),
        8,
    )
    assert same_family_niches.competitive_splice_niches == 3
    assert same_family_niches.target == 7

    poor_recipient = replace(
        _member(9, 104, 9),
        result=_result(110, 1.0, replay_id=9),
        recipient_member_id=9,
        primary_family_id=104,
    )
    noncompetitive_success = _splice_member(
        104,
        recipient_id=9,
        family_id=104,
        finish_tick=109,
        proximity=1.0,
    )
    without_competitive_addition = parallel._select_adaptive_population(
        (*ordinary, poor_recipient, noncompetitive_success),
        8,
    )
    assert without_competitive_addition.competitive_splice_niches == 0
    assert without_competitive_addition.target == 4


def test_v303_population_exact_dedup_is_hard_and_prefers_ordinary() -> None:
    ordinary = _eight_population_recipients()
    duplicate_splice = replace(
        _splice_member(
            101,
            recipient_id=1,
            family_id=100,
            replay_id=1,
        ),
        result=ordinary[0].result,
    )
    selection = parallel._select_adaptive_population(
        (*ordinary, duplicate_splice),
        8,
    )
    assert selection.exact_unique_candidates == 8
    assert selection.competitive_splice_niches == 0
    assert selection.target == 4
    assert duplicate_splice not in selection.survivors
    assert ordinary[0] in selection.survivors


def test_v303_population_progressively_relaxes_only_soft_caps() -> None:
    same_family = tuple(
        replace(
            _member(index, 77, index),
            recipient_member_id=100 + index,
            primary_family_id=77,
        )
        for index in range(1, 5)
    )
    selected_family = parallel._select_population_survivors(
        same_family,
        4,
        enforce_parent_diversity=True,
    )
    assert len(selected_family) == 4
    assert {member.selection_primary_family_id for member in selected_family} == {77}

    same_recipient = tuple(
        replace(member, recipient_member_id=500)
        for member in same_family
    )
    selected_recipient = parallel._select_population_survivors(
        same_recipient,
        4,
        enforce_parent_diversity=True,
    )
    assert len(selected_recipient) == 4
    assert {member.selection_recipient_member_id for member in selected_recipient} == {500}
    assert len(
        {parallel._population_replay_key(member) for member in selected_recipient}
    ) == 4


def test_v303_eight_worker_quotas_and_keys_are_breadth_first() -> None:
    ordinary = _eight_population_recipients()
    expected = {
        4: [2, 2, 2, 2],
        5: [2, 2, 2, 1, 1],
        6: [2, 2, 1, 1, 1, 1],
        7: [2, 1, 1, 1, 1, 1, 1],
        8: [1, 1, 1, 1, 1, 1, 1, 1],
    }
    for population_size, quota_values in expected.items():
        survivors = ordinary[:population_size]
        quotas = parallel._offspring_quota_by_parent(survivors, 8)
        assert list(quotas.values()) == quota_values
        assert sum(quotas.values()) == 8
        keys = parallel._offspring_keys_breadth_first(3, survivors, 8)
        assert [key[2] for key in keys] == sorted(key[2] for key in keys)
        assert len(keys) == 8


def test_v303_population_summary_reports_requested_diagnostics() -> None:
    selection = parallel._select_adaptive_population(
        (
            *_eight_population_recipients(),
            _splice_member(
                101,
                recipient_id=1,
                family_id=100,
            ),
        ),
        8,
    )
    message = parallel._format_population_round_summary(
        3,
        selection,
        candidate_count=9,
        global_best_finish_tick=99,
    )
    assert "selected population=5/9" in message
    assert "exact-unique replays=5/9 selected/eligible" in message
    assert "primary-family occupancy=" in message
    assert "splice niches=1 selected" in message
    assert "competitive splice additions=1" in message


def test_v295_splice_admission_requires_canonical_trimmed_verification(
    monkeypatch,
) -> None:
    candidate = _result(9, 1.0, marker=InputFrame(right=True)).best
    seen: list[tuple[object, tuple[InputFrame, ...], int]] = []

    def verified(level, frames, *, expected_finish_tick, **kwargs):
        seen.append((level, tuple(frames), expected_finish_tick))
        return candidate.evaluation

    monkeypatch.setattr(parallel, "verify_trimmed_replay", verified)
    canonical = parallel._canonical_splice_candidate(object(), candidate)
    assert canonical is not None
    assert canonical.working_frames == candidate.frames + (InputFrame(),)
    assert seen[0][1] == candidate.frames
    assert seen[0][2] == candidate.finish_tick

    def drifted(*args, **kwargs):
        raise ValueError("completion drift")

    monkeypatch.setattr(parallel, "verify_trimmed_replay", drifted)
    assert parallel._canonical_splice_candidate(object(), candidate) is None


class _SteppedPool:
    events: list[tuple[str, int, int]] = []
    work: dict[Future, tuple[object, object]] = {}

    def __init__(self, *args, initializer=None, initargs=(), **kwargs) -> None:
        type(self).events = []
        type(self).work = {}
        if initializer is not None:
            initializer(*initargs)

    def submit(self, function, task):
        future = Future()
        type(self).work[future] = (function, task)
        type(self).events.append(("submit", task.run_index, task.task_id))
        return future

    def shutdown(self, wait=True, cancel_futures=False) -> None:
        return None


def _stepped_wait(futures, timeout=None, return_when=None):
    candidates = [future for future in futures if not future.done()]
    if not candidates:
        done = {future for future in futures if future.done()}
        return done, set(futures) - done
    future = min(candidates, key=lambda item: _SteppedPool.work[item][1].task_id)
    function, task = _SteppedPool.work[future]
    try:
        future.set_result(function(task))
    except BaseException as exc:  # mirror Future execution semantics
        future.set_exception(exc)
    _SteppedPool.events.append(("complete", task.run_index, task.task_id))
    return {future}, set(futures) - {future}


def test_v304_checkpoint_commits_boundary_and_resumes_next_round(
    monkeypatch,
    tmp_path,
) -> None:
    neutral = InputFrame()
    markers = (
        InputFrame(left=True),
        InputFrame(right=True),
        InputFrame(jump=True),
        InputFrame(left=True, jump=True),
    )
    base_seed = 77
    parent_hash = parallel._replay_sha256((neutral,) * 10)
    seed_markers = {
        parallel._derive_auto_checkpoint_task_seed(
            base_seed, 1, parent_hash, offspring_index
        ): marker
        for offspring_index, marker in enumerate(markers, start=1)
    }
    marker_proximity = {
        marker: float(index) for index, marker in enumerate(markers, start=1)
    }

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        source = tuple(frames)
        marker = source[0]
        if config.iterations == 0:
            proximity = (
                99.0 if marker == neutral else marker_proximity[marker]
            )
            return _result(len(source), proximity, marker=marker, seed=config.seed)
        if marker == neutral:
            output_marker = seed_markers[config.seed]
            return _result(
                10,
                marker_proximity[output_marker],
                marker=output_marker,
                baseline_tick=len(source),
                seed=config.seed,
                iterations=config.iterations,
            )
        return _result(
            9,
            marker_proximity[marker],
            marker=marker,
            baseline_tick=len(source),
            seed=config.seed,
            iterations=config.iterations,
        )

    def no_splice_plans(*args, **kwargs):
        observer = kwargs.get("anchor_runs_observer")
        if observer is not None:
            observer(())
        return ()

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _SteppedPool)
    monkeypatch.setattr(parallel, "wait", _stepped_wait)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)
    monkeypatch.setattr(
        parallel, "find_splice_section_plans", no_splice_plans
    )
    checkpoint_path = tmp_path / "campaign.json"
    real_write = parallel._write_auto_campaign_checkpoint
    write_count = 0

    def interrupt_after_first_commit(*args, **kwargs):
        nonlocal write_count
        real_write(*args, **kwargs)
        write_count += 1
        if write_count == 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(
        parallel,
        "_write_auto_campaign_checkpoint",
        interrupt_after_first_commit,
    )
    config = AutoConfig(iterations=2, beam_width=2, seed=base_seed)
    first = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 10,
        config,
        workers=4,
        runs=2,
        search=fake_search,
        checkpoint_path=checkpoint_path,
        level_identifier="checkpoint-test-level",
    )

    assert first.interrupted is True
    assert first.completed_runs == 1
    envelope = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    first_state = envelope["payload"]["state"]
    assert first_state["completed_runs"] == 1
    assert first_state["next_generation"] == 2
    assert len(first_state["survivors"]) == 2
    assert first_state["seed_strategy"].startswith("stable-generation-")
    assert first_state["consecutive_stagnant_rounds"] == 0

    monkeypatch.setattr(
        parallel, "_write_auto_campaign_checkpoint", real_write
    )
    messages: list[str] = []
    resumed = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 10,
        config,
        workers=4,
        runs=2,
        search=fake_search,
        checkpoint_path=checkpoint_path,
        resume=True,
        level_identifier="checkpoint-test-level",
        status=messages.append,
    )

    assert resumed.interrupted is False
    assert resumed.completed_runs == 2
    assert resumed.result.finish_tick == 9
    assert any(
        message.startswith("[auto:resume] restored") for message in messages
    )
    final_envelope = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert final_envelope["payload"]["state"]["completed_runs"] == 2


def test_v305_serial_stagnation_limit_resets_on_improvement_and_stops() -> None:
    source = (InputFrame(),) * 10
    scheduled_ticks = iter((10, 9, 9, 9))
    completed_search_ticks: list[int] = []
    messages: list[str] = []

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        body = tuple(frames)
        if config.iterations == 0:
            return _result(len(body), 1.0, seed=config.seed)
        tick = next(scheduled_ticks)
        completed_search_ticks.append(tick)
        return _result(
            tick,
            1.0,
            baseline_tick=len(body),
            seed=config.seed,
            iterations=config.iterations,
        )

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        source,
        AutoConfig(iterations=1, seed=17),
        workers=1,
        runs=0,
        stagnation_runs=2,
        search=fake_search,
        status=messages.append,
    )

    assert campaign.interrupted is False
    assert campaign.completed_runs == 4
    assert campaign.completed_searches == 4
    assert campaign.result.finish_tick == 9
    assert completed_search_ticks == [10, 9, 9, 9]
    assert messages[-1].startswith("[auto:stagnation] stopping after 2")


def test_v305_stagnation_checkpoint_is_durable_and_resume_stays_stopped(
    tmp_path,
) -> None:
    source = (InputFrame(),) * 10
    checkpoint_path = tmp_path / "stagnant-campaign.json"
    completed_searches = 0

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        nonlocal completed_searches
        body = tuple(frames)
        if config.iterations > 0:
            completed_searches += 1
        return _result(
            len(body),
            1.0,
            baseline_tick=(len(body) if config.iterations > 0 else None),
            seed=config.seed,
            iterations=config.iterations,
        )

    config = AutoConfig(iterations=1, seed=23)
    first = parallel.optimise_autonomous_campaign(
        object(),
        source,
        config,
        workers=1,
        runs=0,
        stagnation_runs=2,
        search=fake_search,
        checkpoint_path=checkpoint_path,
        level_identifier="stagnation-test-level",
    )

    assert first.completed_runs == 2
    assert completed_searches == 2
    envelope = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert envelope["payload"]["identity"]["configuration"][
        "stagnation_runs"
    ] == 2
    assert envelope["payload"]["state"]["consecutive_stagnant_rounds"] == 2

    messages: list[str] = []
    resumed = parallel.optimise_autonomous_campaign(
        object(),
        source,
        config,
        workers=1,
        runs=0,
        stagnation_runs=2,
        search=fake_search,
        checkpoint_path=checkpoint_path,
        resume=True,
        level_identifier="stagnation-test-level",
        status=messages.append,
    )

    assert resumed.completed_runs == 2
    assert resumed.completed_searches == 2
    assert completed_searches == 2
    assert messages[-1].startswith(
        "[auto:stagnation] restored campaign has already reached"
    )


def test_v305_parallel_stagnation_limit_stops_after_committed_rounds(
    monkeypatch,
) -> None:
    source = (InputFrame(),) * 10
    messages: list[str] = []

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        body = tuple(frames)
        return _result(
            len(body),
            1.0,
            baseline_tick=(len(body) if config.iterations > 0 else None),
            seed=config.seed,
            iterations=config.iterations,
        )

    def no_splice_plans(*args, **kwargs):
        observer = kwargs.get("anchor_runs_observer")
        if observer is not None:
            observer(())
        return ()

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _SteppedPool)
    monkeypatch.setattr(parallel, "wait", _stepped_wait)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)
    monkeypatch.setattr(
        parallel, "find_splice_section_plans", no_splice_plans
    )

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        source,
        AutoConfig(iterations=1, seed=29),
        workers=2,
        runs=0,
        stagnation_runs=2,
        search=fake_search,
        status=messages.append,
    )

    assert campaign.interrupted is False
    assert campaign.completed_runs == 2
    assert campaign.completed_searches >= 4
    assert any(
        message.startswith("[auto:stagnation] stopping after 2")
        for message in messages
    )


class _RunningSteppedPool(_SteppedPool):
    """Harness whose submitted work has already entered Future.RUNNING."""

    def submit(self, function, task):
        future = super().submit(function, task)
        assert future.set_running_or_notify_cancel()
        return future


class _ObservedBoundedQueue(Queue):
    consumer_thread: Thread | None = None

    def get(self, block=True, timeout=None):
        self.consumer_thread = current_thread()
        return super().get(block=block, timeout=timeout)


class _BackpressurePool:
    def __init__(self, worker: Thread) -> None:
        self.worker = worker
        self.shutdown_calls = 0
        self._processes = {}

    def shutdown(self, wait=True, cancel_futures=False) -> None:
        self.shutdown_calls += 1
        self.worker.join(timeout=1.0)
        assert not self.worker.is_alive()


def test_v297_shutdown_pumps_checkpoint_queue_until_worker_finishes() -> None:
    """A full checkpoint queue must not deadlock executor shutdown."""
    checkpoint_queue = _ObservedBoundedQueue(maxsize=1)
    checkpoint_queue.put("first")
    future: Future[str] = Future()
    assert future.set_running_or_notify_cancel()
    put_started = Event()

    def produce() -> None:
        put_started.set()
        checkpoint_queue.put("second")
        future.set_result("finished")

    worker = Thread(target=produce, name="blocked-checkpoint-producer")
    worker.start()
    assert put_started.wait(timeout=1.0)
    assert not future.done()
    executor = _BackpressurePool(worker)
    stop_event = Event()

    completed, buffered = parallel._stop_executor(
        executor,
        (future,),
        stop_event,
        checkpoint_queue,
    )

    assert completed == (future,)
    assert buffered == ("first", "second")
    assert stop_event.is_set()
    assert executor.shutdown_calls == 1
    assert checkpoint_queue.consumer_thread is not None
    assert not checkpoint_queue.consumer_thread.is_alive()


def _running_stepped_wait(futures, timeout=None, return_when=None):
    candidates = [future for future in futures if not future.done()]
    if not candidates:
        done = {future for future in futures if future.done()}
        return done, set(futures) - done
    future = min(
        candidates,
        key=lambda item: _RunningSteppedPool.work[item][1].task_id,
    )
    function, task = _RunningSteppedPool.work[future]
    event = "complete"
    try:
        future.set_result(function(task))
    except parallel._AutoWorkerCancelled as exc:
        event = "cancelled"
        future.set_exception(exc)
    except BaseException as exc:
        future.set_exception(exc)
    _RunningSteppedPool.events.append((event, task.run_index, task.task_id))
    return {future}, set(futures) - {future}


def test_v248_top_half_seeds_two_children_each_and_starts_speculatively(
    monkeypatch,
) -> None:
    worker_count = 8
    base_seed = 17
    neutral = InputFrame()
    markers = (
        InputFrame(left=True),
        InputFrame(right=True),
        InputFrame(jump=True),
        InputFrame(left=True, jump=True),
        InputFrame(right=True, jump=True),
        InputFrame(left=True, right=True),
        InputFrame(left=True, right=True, jump=True),
        InputFrame(left=True, jump=True, jump_trigger=True),
    )
    first_seeds = {
        parallel._derive_auto_task_seed(base_seed, task_id): task_id
        for task_id in range(1, worker_count + 1)
    }
    calls: list[tuple[int, tuple[InputFrame, ...]]] = []

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        source = tuple(frames)
        calls.append((config.seed, source))
        if config.iterations == 0:
            return _result(10, 20.0, marker=neutral, seed=config.seed)
        first_id = first_seeds.get(config.seed)
        if first_id is not None:
            return _result(
                10,
                float(first_id),
                marker=markers[first_id - 1],
                baseline_tick=len(source),
                seed=config.seed,
                iterations=config.iterations,
            )
        # Round-two children keep their parent's marker so the input ancestry is
        # directly visible in the captured calls.
        marker = source[0]
        return _result(
            9,
            1.0,
            marker=marker,
            baseline_tick=len(source),
            seed=config.seed,
            iterations=config.iterations,
        )

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _SteppedPool)
    monkeypatch.setattr(parallel, "wait", _stepped_wait)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 10,
        AutoConfig(iterations=3, beam_width=2, seed=base_seed),
        workers=worker_count,
        runs=2,
        search=fake_search,
    )

    assert campaign.completed_runs == 2
    assert campaign.completed_searches == 16
    # A round-two search is submitted immediately after the first round-one
    # result completes, before the remaining seven round-one searches finish.
    events = _SteppedPool.events
    first_complete = events.index(("complete", 1, 1))
    first_round2_submit = next(
        index for index, event in enumerate(events) if event[0:2] == ("submit", 2)
    )
    second_round1_complete = events.index(("complete", 1, 2))
    assert first_complete < first_round2_submit < second_round1_complete

    round_two_sources = [
        source
        for seed, source in calls
        if seed not in first_seeds and source and source[0] != neutral
    ]
    parent_markers = [source[0] for source in round_two_sources]
    for marker in markers[:4]:
        assert parent_markers.count(marker) == 2
    assert all(marker in markers[:4] for marker in parent_markers)
    round_two_tasks = {
        task.task_id: task
        for _function, task in _SteppedPool.work.values()
        if isinstance(task, parallel._AutoWorkerTask) and task.run_index == 2
    }
    breadth_order = [
        task.offspring_index
        for task in sorted(round_two_tasks.values(), key=lambda item: item.task_id)
    ]
    assert breadth_order == [1, 1, 1, 1, 2, 2, 2, 2]


def test_v248_worker_checkpoint_carries_exact_evaluation_count(monkeypatch) -> None:
    queue = Queue()
    tokens = [123]
    parallel._initialise_auto_worker(
        parallel._AutoWorkerContext(object(), AutoConfig(iterations=200, seed=1)),
        None,
        queue,
        tokens,
    )
    candidate = _result(9, 1.0, baseline_tick=10, iterations=137).best
    result = _result(9, 1.0, baseline_tick=10, iterations=137)

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        assert progress is not None and best_callback is not None
        progress(
            AutoProgress(
                phase="beam",
                macro_evaluations=137,
                budget=200,
                best_finish_tick=9,
                message="test",
            )
        )
        best_callback(candidate)
        return result

    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)
    output = parallel._run_auto_worker(
        parallel._AutoWorkerTask(
            frames=(InputFrame(),) * 10,
            seed=1,
            run_index=1,
            worker_index=1,
            task_id=123,
            cancel_slot=0,
        )
    )
    checkpoint = queue.get_nowait()
    assert checkpoint.macro_evaluations == 137
    assert output.result.stats.macro_evaluations == 137


def test_v297_splice_round_prepares_each_member_once_for_all_pairs(
    monkeypatch,
) -> None:
    """Four traces are indexed once although the scheduler runs 12 pairs."""

    worker_count = 4
    neutral = InputFrame()
    preparation_ids: list[int] = []
    pair_calls: list[tuple[object, object]] = []
    real_prepare = parallel.prepare_splice_trace

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        if config.iterations == 0:
            return _result(10, 20.0, marker=neutral, seed=config.seed)
        return _result(
            10,
            float(config.seed),
            marker=InputFrame(right=True),
            baseline_tick=len(tuple(frames)),
            seed=config.seed,
            iterations=config.iterations,
        )

    def counting_prepare(evaluation, frames):
        preparation_ids.append(id(evaluation))
        return real_prepare(evaluation, frames)

    def no_splice_plans(recipient, donor, *args, **kwargs):
        pair_calls.append((recipient, donor))
        observer = kwargs.get("anchor_runs_observer")
        if observer is not None:
            observer(())
        return ()

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _SteppedPool)
    monkeypatch.setattr(parallel, "wait", _stepped_wait)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)
    monkeypatch.setattr(parallel, "prepare_splice_trace", counting_prepare)
    monkeypatch.setattr(
        parallel,
        "find_splice_section_plans",
        no_splice_plans,
    )

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 10,
        AutoConfig(iterations=1, beam_width=2, seed=73),
        workers=worker_count,
        runs=1,
        search=fake_search,
    )

    assert campaign.completed_runs == 1
    assert len(pair_calls) == worker_count * (worker_count - 1) == 12
    assert len(preparation_ids) == worker_count == 4
    assert len(set(preparation_ids)) == worker_count


def test_v297_native_splice_parent_cache_is_per_generation_and_member(
    monkeypatch,
) -> None:
    class _FakeLevel:
        pass

    level = _FakeLevel()
    first_member = _member(1, 10, 1)
    second_member = _member(2, 10, 2)
    evaluations: list[AutoEvaluation] = []

    def fake_evaluate(_level, _frames):
        evaluation = _result(90 + len(evaluations), 1.0).best.evaluation
        evaluations.append(evaluation)
        return evaluation

    monkeypatch.setattr(parallel, "Level", _FakeLevel)
    monkeypatch.setattr(parallel, "evaluate_replay_with_sentinel", fake_evaluate)
    monkeypatch.setattr(parallel, "_AUTO_WORKER_SPLICE_PARENT_CACHE", {})

    first = parallel._native_splice_parent(level, 3, first_member)
    repeated = parallel._native_splice_parent(level, 3, first_member)
    second = parallel._native_splice_parent(level, 3, second_member)

    assert repeated is first
    assert len(evaluations) == 2
    assert first.result.best.evaluation is evaluations[0]
    assert second.result.best.evaluation is evaluations[1]
    assert set(parallel._AUTO_WORKER_SPLICE_PARENT_CACHE) == {(3, 1), (3, 2)}

    next_generation = parallel._native_splice_parent(level, 4, first_member)

    assert len(evaluations) == 3
    assert next_generation.result.best.evaluation is evaluations[2]
    assert set(parallel._AUTO_WORKER_SPLICE_PARENT_CACHE) == {(4, 1)}


def test_v248_forced_spawn_two_round_population_smoke(monkeypatch) -> None:
    import multiprocessing
    from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, parse_level_string

    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for x in range(APP_NUM_GRIDCOLS):
        chars[x * APP_NUM_GRIDROWS + 5] = "1"
    level = parse_level_string(
        f"{''.join(chars)}|5^60,134!11^140,134,60,134",
        simulate_enemies=False,
    )
    spawn_context = multiprocessing.get_context("spawn")
    monkeypatch.setattr(parallel.multiprocessing, "get_context", lambda: spawn_context)
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    status_messages: list[str] = []
    campaign = parallel.optimise_autonomous_campaign(
        level,
        source,
        AutoConfig(iterations=1, beam_width=2, seed=456),
        workers=4,
        runs=2,
        status=status_messages.append,
    )
    assert campaign.completed_runs == 2
    assert campaign.completed_searches >= 8
    assert campaign.result.finish_tick <= campaign.result.baseline_finish_tick
    splice_summaries = [
        message
        for message in status_messages
        if message.startswith("[auto:splice] round ") and "pairs=" in message
    ]
    assert len(splice_summaries) == 2
    pair_counts = [
        int(message.split("pairs=", 1)[1].split(",", 1)[0])
        for message in splice_summaries
    ]
    # Four worker winners still contribute the original 12 ordered pairs.
    # Every retained sectional donor adds its own independent per-recipient
    # pair job (including its same-worker winner as a recipient).
    assert all(count >= 12 for count in pair_counts)
    assert any("sectional donors=" in message for message in splice_summaries)


def test_v248_pruned_speculation_is_replaced_by_true_survivor_children(
    monkeypatch,
) -> None:
    worker_count = 8
    base_seed = 99
    neutral = InputFrame()
    markers = (
        InputFrame(left=True),
        InputFrame(right=True),
        InputFrame(jump=True),
        InputFrame(left=True, jump=True),
        InputFrame(right=True, jump=True),
        InputFrame(left=True, right=True),
        InputFrame(left=True, right=True, jump=True),
        InputFrame(left=True, jump=True, jump_trigger=True),
    )
    first_seeds = {
        parallel._derive_auto_task_seed(base_seed, task_id): task_id
        for task_id in range(1, worker_count + 1)
    }
    calls: list[tuple[int, tuple[InputFrame, ...]]] = []

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        source = tuple(frames)
        calls.append((config.seed, source))
        if config.iterations == 0:
            return _result(10, 20.0, marker=neutral, seed=config.seed)
        first_id = first_seeds.get(config.seed)
        if first_id is not None:
            # Completion order is 1..8, but the late four are the actual best.
            proximity = float(9 - first_id)
            return _result(
                10,
                proximity,
                marker=markers[first_id - 1],
                baseline_tick=len(source),
                seed=config.seed,
                iterations=config.iterations,
            )
        marker = source[0]
        return _result(
            9,
            1.0,
            marker=marker,
            baseline_tick=len(source),
            seed=config.seed,
            iterations=config.iterations,
        )

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _SteppedPool)
    monkeypatch.setattr(parallel, "wait", _stepped_wait)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 10,
        AutoConfig(iterations=2, beam_width=2, seed=base_seed),
        workers=worker_count,
        runs=2,
        search=fake_search,
    )

    assert campaign.completed_runs == 2
    assert campaign.completed_searches == 16
    round_two_completed_sources = [
        source[0]
        for seed, source in calls
        if seed not in first_seeds and source and source[0] in markers[4:]
    ]
    for marker in markers[4:]:
        assert round_two_completed_sources.count(marker) == 2


def test_v295_splice_parent_reconciles_speculative_children(monkeypatch) -> None:
    """A final splice can replace a provisional parent without losing speculation."""
    worker_count = 4
    neutral = InputFrame()
    ordinary_marker = InputFrame(left=True)
    splice_marker = InputFrame(jump=True)
    calls: list[tuple[int, tuple[InputFrame, ...]]] = []
    plan = SimpleNamespace(
        recipient_entry_tick=2,
        recipient_exit_tick=8,
        donor_entry_tick=3,
        donor_exit_tick=8,
        predicted_time_gain=1,
    )
    splice_candidate = _result(
        9,
        0.5,
        marker=splice_marker,
        baseline_tick=10,
    ).best

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        source = tuple(frames)
        calls.append((config.seed, source))
        if config.iterations == 0:
            return _result(10, 99.0, marker=neutral, seed=config.seed)
        if source and source[0] == splice_marker:
            return _result(
                8,
                0.25,
                marker=splice_marker,
                baseline_tick=len(source),
                seed=config.seed,
                iterations=config.iterations,
            )
        return _result(
            10,
            float(config.seed),
            marker=ordinary_marker,
            baseline_tick=len(source),
            seed=config.seed,
            iterations=config.iterations,
        )

    def fake_repair(*args, **kwargs):
        return SimpleNamespace(
            accepted=True,
            candidate=splice_candidate,
            attempts=0,
            local_simulations=0,
        )

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _SteppedPool)
    monkeypatch.setattr(parallel, "wait", _stepped_wait)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)
    monkeypatch.setattr(
        parallel,
        "find_splice_section_plans",
        lambda *args, **kwargs: (plan,),
    )
    monkeypatch.setattr(parallel, "repair_reference_segment_splice", fake_repair)
    monkeypatch.setattr(
        parallel,
        "_canonical_splice_candidate",
        lambda level, candidate: candidate,
    )
    status_messages: list[str] = []

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 10,
        AutoConfig(iterations=1, beam_width=2, seed=41),
        workers=worker_count,
        runs=2,
        search=fake_search,
        status=status_messages.append,
    )

    events = _SteppedPool.events
    # Task 6 is a speculative descendant of a provisional ordinary parent. It
    # now fills spare capacity and can complete during the splice tail, but the
    # final population still replaces that ancestry with the synthetic splice
    # member. Task 8 is then run from the selected splice replay.
    assert ("submit", 2, 6) in events
    assert ("complete", 2, 6) in events
    assert ("submit", 2, 8) in events
    assert any(source and source[0] == splice_marker for _, source in calls)
    assert campaign.result.finish_tick == 8
    summary = next(
        message
        for message in status_messages
        if message.startswith("[auto:splice] round 1:")
        and "pairs=" in message
    )
    assert "pairs=12" in summary
    assert "plans=12" in summary
    assert "attempted=12" in summary
    assert "completed=12" in summary
    assert "canonical=12" in summary
    assert "beat-recipient=1" in summary
    assert "admitted=1" in summary
    assert "survivors=1" in summary
    assert "predicted gain=1" in summary
    assert "realised gain=1" in summary
    assert "duplicate-replay:11" in summary


def test_v296_splice_summary_formats_rejection_and_gain_ranges() -> None:
    stats = parallel._SpliceRoundStats(
        pairs=56,
        corridors=183,
        plans=71,
        attempted=42,
        repaired=11,
        completed=15,
        canonical=14,
        beat_recipient=6,
        admitted=5,
        survivors=2,
        rejection_counts={
            "canonical-verification": 1,
            "population-selection": 3,
            "repair-no-proposal": 12,
        },
        predicted_gains=[1, 8],
        realised_gains=[1, 6],
    )
    messages: list[str] = []

    parallel._emit_splice_round_summary(3, stats, messages.append)

    assert messages == [
        "[auto:splice] round 3: pairs=56, corridors=183, plans=71, "
        "attempted=42, repaired=11, completed=15, canonical=14, "
        "beat-recipient=6, admitted=5, survivors=2; predicted gain=1..8, "
        "realised gain=1..6; rejected=canonical-verification:1,"
        "population-selection:3,repair-no-proposal:12"
    ]


def test_v298_ready_splice_pairs_preempt_then_refill_with_speculation(
    monkeypatch,
) -> None:
    """Pair jobs outrank provisional Auto without leaving spare slots idle."""
    worker_count = 4
    neutral = InputFrame()

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        if config.iterations == 0:
            return _result(10, 99.0, marker=neutral, seed=config.seed)
        return _result(
            10,
            float(config.seed),
            marker=InputFrame(left=True),
            baseline_tick=len(frames),
            seed=config.seed,
            iterations=config.iterations,
        )

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _SteppedPool)
    monkeypatch.setattr(parallel, "wait", _stepped_wait)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 10,
        AutoConfig(iterations=1, beam_width=2, seed=123),
        workers=worker_count,
        runs=2,
        search=fake_search,
    )

    events = _SteppedPool.events
    round_one_pair_submits = [
        (index, event)
        for index, event in enumerate(events)
        if event[0] == "submit"
        and event[1] == 1
        and event[2] >= parallel._SPLICE_TASK_ID_BASE
    ]
    round_one_pair_completes = [
        index
        for index, event in enumerate(events)
        if event[0] == "complete"
        and event[1] == 1
        and event[2] >= parallel._SPLICE_TASK_ID_BASE
    ]

    assert len(round_one_pair_submits) == worker_count * (worker_count - 1)
    assert len({event[2] for _, event in round_one_pair_submits}) == 12
    assert len(round_one_pair_completes) == 12
    # Parent two makes both ordered 1/2 pairs ready.  One is submitted before
    # parent three completes, rather than waiting for the old round-end pass.
    second_parent = events.index(("complete", 1, 2))
    third_parent = events.index(("complete", 1, 3))
    assert second_parent < round_one_pair_submits[0][0] < third_parent

    speculative_submits = [
        index
        for index, event in enumerate(events)
        if event[0] == "submit"
        and event[1] == 2
        and event[2] < parallel._SPLICE_TASK_ID_BASE
    ]
    speculative_completes = [
        index
        for index, event in enumerate(events)
        if event[0] == "complete"
        and event[1] == 2
        and event[2] < parallel._SPLICE_TASK_ID_BASE
    ]
    assert speculative_submits
    # Speculation starts after parent one and is cooperatively displaced when
    # parent two creates a pair backlog.  Once every ready pair has a worker,
    # the same deterministic task is resubmitted into spare capacity while the
    # splice tail is still running.
    resumed_task_id = worker_count + 1
    resumed_submits = [
        index
        for index, event in enumerate(events)
        if event == ("submit", 2, resumed_task_id)
    ]
    assert len(resumed_submits) == 2
    assert resumed_submits[0] < round_one_pair_submits[0][0]
    last_pair_submit = max(index for index, _event in round_one_pair_submits)
    assert last_pair_submit < resumed_submits[1]
    assert resumed_submits[1] < max(round_one_pair_completes)
    assert min(speculative_completes) < max(round_one_pair_completes)
    assert campaign.completed_runs == 2


def test_v298_running_speculation_is_cancelled_then_resumed_during_splice_tail(
    monkeypatch,
) -> None:
    """A RUNNING speculative Future resumes safely in spare splice capacity."""
    worker_count = 4
    base_seed = 321
    neutral = InputFrame()
    first_seeds = {
        parallel._derive_auto_task_seed(base_seed, task_id): task_id
        for task_id in range(1, worker_count + 1)
    }
    resumed_seed = parallel._derive_auto_task_seed(base_seed, worker_count + 1)
    search_calls: list[tuple[int, int]] = []

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        search_calls.append((config.seed, config.iterations))
        if config.iterations == 0:
            return _result(10, 99.0, marker=neutral, seed=config.seed)
        first_id = first_seeds.get(config.seed)
        if first_id is not None:
            # The first completed parent is also the best survivor, so its
            # preempted offspring record is authoritative in round two.
            return _result(
                10,
                float(first_id),
                marker=InputFrame(left=True),
                baseline_tick=len(frames),
                seed=config.seed,
                iterations=config.iterations,
            )
        return _result(
            9,
            1.0,
            marker=InputFrame(right=True),
            baseline_tick=len(frames),
            seed=config.seed,
            iterations=config.iterations,
        )

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _RunningSteppedPool)
    monkeypatch.setattr(parallel, "wait", _running_stepped_wait)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 10,
        AutoConfig(iterations=1, beam_width=2, seed=base_seed),
        workers=worker_count,
        runs=2,
        search=fake_search,
    )

    events = _RunningSteppedPool.events
    resumed_task_id = worker_count + 1
    assert events.count(("submit", 2, resumed_task_id)) == 2
    assert events.count(("cancelled", 2, resumed_task_id)) == 1
    assert events.count(("complete", 2, resumed_task_id)) == 1
    pair_completions = [
        index
        for index, event in enumerate(events)
        if event[0] == "complete"
        and event[1] == 1
        and event[2] >= parallel._SPLICE_TASK_ID_BASE
    ]
    resumed_completion = events.index(("complete", 2, resumed_task_id))
    assert len(pair_completions) == worker_count * (worker_count - 1)
    assert resumed_completion < max(pair_completions)
    # The cancelled attempt exits before fake_search; only the resubmission
    # performs and contributes one successful Auto search.
    assert search_calls.count((resumed_seed, 1)) == 1
    assert campaign.completed_runs == 2
    assert campaign.completed_searches == 2 * worker_count
    assert campaign.result.stats.macro_evaluations == 2 * worker_count


def test_v297_splice_worker_returns_and_checkpoints_partial_success_on_cancel(
    monkeypatch,
) -> None:
    """Cancellation before plan two must not discard verified plan one."""
    recipient = parallel._AutoPopulationMember(
        member_id=1,
        result=_result(10, 5.0),
        parent_member_ids=(0,),
        generation=1,
        mutations=(),
    )
    donor = parallel._AutoPopulationMember(
        member_id=2,
        result=_result(10, 6.0, marker=InputFrame(left=True)),
        parent_member_ids=(0,),
        generation=1,
        mutations=(),
    )
    candidate = _result(
        9,
        1.0,
        marker=InputFrame(jump=True),
        baseline_tick=10,
    ).best
    plan = SimpleNamespace(
        recipient_entry_tick=2,
        recipient_exit_tick=8,
        donor_entry_tick=3,
        donor_exit_tick=8,
        predicted_time_gain=1,
    )
    checkpoint_queue = Queue()
    cancellation_checks = iter((False, False, True))

    def plans(*args, **kwargs):
        observer = kwargs.get("anchor_runs_observer")
        if observer is not None:
            observer((object(),))
        return (plan, plan)

    repair = SimpleNamespace(
        accepted=True,
        candidate=candidate,
        raw_candidate=candidate,
        attempts=0,
        local_simulations=0,
        rejection_reason=None,
    )
    monkeypatch.setattr(
        parallel,
        "_worker_cancelled",
        lambda task=None: next(cancellation_checks),
    )
    monkeypatch.setattr(parallel, "find_splice_section_plans", plans)
    monkeypatch.setattr(
        parallel,
        "repair_reference_segment_splice",
        lambda *args, **kwargs: repair,
    )
    monkeypatch.setattr(
        parallel,
        "_canonical_splice_candidate",
        lambda level, value: value,
    )
    monkeypatch.setattr(
        parallel,
        "_AUTO_WORKER_CHECKPOINT_QUEUE",
        checkpoint_queue,
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
        parallel._AutoWorkerContext(object(), AutoConfig(iterations=1)),
    )
    checkpoint = checkpoint_queue.get_nowait()

    assert len(output.candidates) == 1
    assert output.candidates[0].candidate is candidate
    assert output.splice_stats.attempted == 1
    assert output.splice_stats.canonical == 1
    assert isinstance(checkpoint, parallel._SpliceWorkerCheckpoint)
    assert checkpoint.task_id == task.task_id
    assert checkpoint.proposal.candidate is candidate


def test_v297_interrupt_reaps_splice_finishing_during_shutdown_grace(
    monkeypatch,
) -> None:
    """A successful pair future finishing after Ctrl+C remains recoverable."""
    neutral = InputFrame()
    candidate = _result(
        9,
        0.5,
        marker=InputFrame(jump=True),
        baseline_tick=10,
    ).best
    normal_waits = 0

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        if config.iterations == 0:
            return _result(10, 99.0, marker=neutral, seed=config.seed)
        return _result(
            10,
            float(config.seed),
            marker=InputFrame(left=True),
            baseline_tick=len(frames),
            seed=config.seed,
            iterations=config.iterations,
        )

    def fake_splice_worker(task):
        proposal = parallel._SpliceWorkerCandidate(
            candidate=candidate,
            recipient_entry_tick=2,
            recipient_exit_tick=8,
            donor_entry_tick=3,
            donor_exit_tick=8,
            predicted_time_gain=1,
        )
        return parallel._SpliceWorkerResult(
            task_id=task.task_id,
            run_index=task.run_index,
            recipient_member_id=task.recipient.member_id,
            donor_member_id=task.donor.member_id,
            candidates=(proposal,),
            splice_stats=parallel._SpliceRoundStats(
                pairs=1,
                plans=1,
                attempted=1,
                completed=1,
                canonical=1,
            ),
            auto_stats=AutoStats(),
        )

    def interrupt_then_finish(futures, timeout=None, return_when=None):
        nonlocal normal_waits
        pending = [future for future in futures if not future.done()]
        if timeout == 2.0:
            for future in pending:
                function, task = _RunningSteppedPool.work[future]
                try:
                    future.set_result(function(task))
                except BaseException as exc:
                    future.set_exception(exc)
            return set(pending), set()

        normal_waits += 1
        if normal_waits > 2:
            raise KeyboardInterrupt
        future = next(
            item
            for item in pending
            if _RunningSteppedPool.work[item][1].task_id == normal_waits
        )
        function, task = _RunningSteppedPool.work[future]
        try:
            future.set_result(function(task))
        except BaseException as exc:
            future.set_exception(exc)
        return {future}, set(futures) - {future}

    saved: list[AutoCandidate] = []
    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _RunningSteppedPool)
    monkeypatch.setattr(parallel, "wait", interrupt_then_finish)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)
    monkeypatch.setattr(parallel, "_run_splice_worker", fake_splice_worker)

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 10,
        AutoConfig(iterations=1, beam_width=2, seed=91),
        workers=4,
        runs=1,
        search=fake_search,
        best_callback=saved.append,
    )

    assert campaign.interrupted is True
    assert campaign.result.finish_tick == 9
    assert saved[-1].finish_tick == 9


def test_v297_final_round_runs_splices_without_starting_speculation(
    monkeypatch,
) -> None:
    neutral = InputFrame()

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        return _result(
            10,
            float(config.seed),
            marker=neutral,
            baseline_tick=None if config.iterations == 0 else len(frames),
            seed=config.seed,
            iterations=config.iterations,
        )

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _SteppedPool)
    monkeypatch.setattr(parallel, "wait", _stepped_wait)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 10,
        AutoConfig(iterations=1, beam_width=2, seed=77),
        workers=4,
        runs=1,
        search=fake_search,
    )

    pair_submits = [
        event
        for event in _SteppedPool.events
        if event[0] == "submit" and event[2] >= parallel._SPLICE_TASK_ID_BASE
    ]
    assert len(pair_submits) == 12
    assert not any(
        event[0] == "submit"
        and event[1] == 2
        and event[2] < parallel._SPLICE_TASK_ID_BASE
        for event in _SteppedPool.events
    )
    assert campaign.completed_searches == 4


def test_v297_splice_future_completion_order_does_not_change_admission(
    monkeypatch,
) -> None:
    neutral = InputFrame()
    splice_candidate = _result(
        9,
        0.5,
        marker=InputFrame(jump=True),
        baseline_tick=10,
    ).best

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        if config.iterations == 0:
            return _result(10, 99.0, marker=neutral, seed=config.seed)
        return _result(
            10,
            float(config.seed),
            marker=InputFrame(left=True),
            baseline_tick=len(frames),
            seed=config.seed,
            iterations=config.iterations,
        )

    def fake_splice_worker(task):
        proposal = parallel._SpliceWorkerCandidate(
            candidate=splice_candidate,
            recipient_entry_tick=2,
            recipient_exit_tick=8,
            donor_entry_tick=3,
            donor_exit_tick=8,
            predicted_time_gain=1,
        )
        return parallel._SpliceWorkerResult(
            task_id=task.task_id,
            run_index=task.run_index,
            recipient_member_id=task.recipient.member_id,
            donor_member_id=task.donor.member_id,
            candidates=(proposal,),
            splice_stats=parallel._SpliceRoundStats(
                pairs=1,
                plans=1,
                attempted=1,
                completed=1,
                canonical=1,
                predicted_gains=[1],
                realised_gains=[1],
            ),
            auto_stats=AutoStats(),
        )

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _SteppedPool)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)
    monkeypatch.setattr(parallel, "_run_splice_worker", fake_splice_worker)

    def run_campaign(*, reverse_pairs: bool):
        def ordered_wait(futures, timeout=None, return_when=None):
            candidates = [future for future in futures if not future.done()]
            if not candidates:
                done = {future for future in futures if future.done()}
                return done, set(futures) - done
            auto_candidates = [
                future
                for future in candidates
                if _SteppedPool.work[future][1].task_id
                < parallel._SPLICE_TASK_ID_BASE
            ]
            pool = auto_candidates or candidates
            future = (max if reverse_pairs and not auto_candidates else min)(
                pool,
                key=lambda item: _SteppedPool.work[item][1].task_id,
            )
            function, task = _SteppedPool.work[future]
            try:
                future.set_result(function(task))
            except BaseException as exc:
                future.set_exception(exc)
            _SteppedPool.events.append(
                ("complete", task.run_index, task.task_id)
            )
            return {future}, set(futures) - {future}

        monkeypatch.setattr(parallel, "wait", ordered_wait)
        messages: list[str] = []
        campaign = parallel.optimise_autonomous_campaign(
            object(),
            (neutral,) * 10,
            AutoConfig(iterations=1, beam_width=2, seed=222),
            workers=4,
            runs=1,
            search=fake_search,
            status=messages.append,
        )
        summary = next(
            message
            for message in messages
            if message.startswith("[auto:splice] round 1:")
            and "pairs=" in message
        )
        return campaign, summary

    forward, forward_summary = run_campaign(reverse_pairs=False)
    reverse, reverse_summary = run_campaign(reverse_pairs=True)

    assert forward.result.frames == reverse.result.frames
    assert forward.result.best.mutations == reverse.result.best.mutations
    assert forward.result.finish_tick == reverse.result.finish_tick == 9
    assert forward_summary == reverse_summary
    assert "admitted=1" in forward_summary
    assert "duplicate-replay:11" in forward_summary


def test_v300_round_one_distributes_searches_across_ranked_unique_founders(
    monkeypatch,
) -> None:
    neutral = InputFrame()
    right = InputFrame(right=True)
    left = InputFrame(left=True)
    finish_by_marker = {
        neutral: 12,
        right: 9,
        left: 10,
    }
    searched_markers: list[InputFrame] = []
    verification_markers: list[InputFrame] = []

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        source = tuple(frames)
        marker = source[0]
        finish = finish_by_marker[marker]
        if config.iterations == 0:
            verification_markers.append(marker)
            return _result(finish, 1.0, marker=marker)
        searched_markers.append(marker)
        return _result(
            finish,
            1.0,
            marker=marker,
            baseline_tick=len(source),
            seed=config.seed,
            iterations=config.iterations,
        )

    def no_splice_plans(*args, **kwargs):
        observer = kwargs.get("anchor_runs_observer")
        if observer is not None:
            observer(())
        return ()

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _SteppedPool)
    monkeypatch.setattr(parallel, "wait", _stepped_wait)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)
    monkeypatch.setattr(parallel, "find_splice_section_plans", no_splice_plans)
    messages: list[str] = []

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 20,
        AutoConfig(iterations=1, beam_width=2, seed=300),
        parent_frames=(
            (right,) * 30,
            (left,) * 25,
            (right,) * 40,
        ),
        workers=8,
        runs=1,
        search=fake_search,
        status=messages.append,
    )

    assert verification_markers == [neutral, right, left, right]
    assert searched_markers.count(right) == 3
    assert searched_markers.count(left) == 3
    assert searched_markers.count(neutral) == 2
    assert campaign.completed_searches == 8
    assert campaign.result.baseline_finish_tick == 12
    assert campaign.result.finish_tick == 9
    assert campaign.result.best.mutations[0] == "starting parent #2"
    assert any(
        "3 unique starting parent(s) from 4 supplied" in message
        and "collapsed 1 canonical duplicate(s)" in message
        for message in messages
    )


def test_v300_zero_iteration_campaign_returns_best_supplied_parent() -> None:
    neutral = InputFrame()
    right = InputFrame(right=True)

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        marker = tuple(frames)[0]
        return _result(12 if marker == neutral else 9, 1.0, marker=marker)

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 20,
        AutoConfig(iterations=0, beam_width=2),
        parent_frames=((right,) * 20,),
        workers=4,
        runs=1,
        search=fake_search,
    )

    assert campaign.completed_runs == 0
    assert campaign.completed_searches == 0
    assert campaign.result.baseline_finish_tick == 12
    assert campaign.result.finish_tick == 9
    assert campaign.result.frames == (right,) * 9
    assert campaign.result.best.mutations == ("starting parent #2",)


def test_v300_strict_gold_rejects_a_founder_missing_positional_reference_gold() -> None:
    neutral = InputFrame()
    right = InputFrame(right=True)

    def with_gold(result: AutoResult, mask: int) -> AutoResult:
        evaluation = replace(
            result.best.evaluation,
            final_gold_mask=mask,
            gold_bonus_ticks=80 * mask.bit_count(),
        )
        candidate = replace(result.best, evaluation=evaluation)
        return replace(
            result,
            best=candidate,
            objective="highscore",
            baseline_gold_mask=mask,
            gold_mask=mask,
            baseline_gold_bonus_ticks=evaluation.gold_bonus_ticks,
            gold_bonus_ticks=evaluation.gold_bonus_ticks,
            baseline_objective_value=(
                evaluation.gold_bonus_ticks - result.finish_tick
            ),
            objective_value=evaluation.gold_bonus_ticks - result.finish_tick,
            require_reference_gold=True,
        )

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        marker = tuple(frames)[0]
        result = _result(12 if marker == neutral else 9, 1.0, marker=marker)
        return with_gold(result, 0b1 if marker == neutral else 0)

    try:
        parallel.optimise_autonomous_campaign(
            object(),
            (neutral,) * 20,
            AutoConfig(
                iterations=0,
                objective="highscore",
                require_reference_gold=True,
            ),
            parent_frames=((right,) * 20,),
            workers=4,
            runs=1,
            search=fake_search,
        )
    except ValueError as exc:
        assert "auto parent #2 is missing positional reference gold: gold:0" in str(exc)
    else:
        raise AssertionError("missing positional reference gold was accepted")
