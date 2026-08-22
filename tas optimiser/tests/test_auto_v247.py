from __future__ import annotations

import gc
import multiprocessing
import weakref
from concurrent.futures import Future
from dataclasses import replace

import pytest

import nv14_auto_parallel as parallel
from nv14_auto import (
    AUTO_OBJECTIVE_HIGHSCORE,
    AUTO_OBJECTIVE_SPEEDRUN,
    AutoCandidate,
    AutoConfig,
    AutoEvaluation,
    AutoResult,
    AutoStats,
    CompactTracePoint,
)
from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    parse_level_string,
)


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
    objective: str = AUTO_OBJECTIVE_SPEEDRUN,
    gold_mask: int = 0,
    gold_bonus_ticks: int = 0,
    baseline_tick: int | None = None,
    seed: int = 0,
    iterations: int = 0,
) -> AutoResult:
    if marker is None:
        marker = InputFrame()
    evaluation = AutoEvaluation(
        finish_tick=tick,
        dead_tick=None,
        last_tick=tick,
        trace=(_point(tick),),
        successful_jumps=(),
        jump_edges=(),
        missed_jump_edges=(),
        final_gold_mask=gold_mask,
        gold_bonus_ticks=gold_bonus_ticks,
        pre_finish_exit_distance=proximity,
    )
    frames = (marker,) * tick
    candidate = AutoCandidate(
        working_frames=frames + (InputFrame(),),
        evaluation=evaluation,
        origin="source" if baseline_tick is None else "test",
        mutations=() if baseline_tick is None else (f"seed {seed}",),
    )
    baseline = tick if baseline_tick is None else baseline_tick
    objective_value = (
        gold_bonus_ticks - tick if objective == AUTO_OBJECTIVE_HIGHSCORE else -tick
    )
    return AutoResult(
        frames=frames,
        baseline_finish_tick=baseline,
        finish_tick=tick,
        best=candidate,
        stats=AutoStats(
            macro_candidates=iterations,
            macro_evaluations=iterations,
        ),
        diagnostics=(f"test seed {seed}",),
        objective=objective,
        baseline_gold_mask=0,
        gold_mask=gold_mask,
        baseline_gold_bonus_ticks=0,
        gold_bonus_ticks=gold_bonus_ticks,
        baseline_objective_value=-baseline,
        objective_value=objective_value,
    )


def test_v247_seed_stream_is_unique_and_preserves_first_serial_seed() -> None:
    seeds = [
        parallel.derive_auto_search_seed(41, run, worker, 8)
        for run in range(1, 4)
        for worker in range(1, 9)
    ]
    assert seeds[0] == 41
    assert len(seeds) == len(set(seeds))
    assert seeds == [
        parallel.derive_auto_search_seed(41, run, worker, 8)
        for run in range(1, 4)
        for worker in range(1, 9)
    ]


def test_v247_cross_worker_ranking_uses_exit_proximity_after_objective() -> None:
    farther = _result(100, 9.0)
    closer = _result(100, 3.0)
    earlier = _result(99, 1000.0)
    assert parallel.auto_result_outcome_key(closer) < parallel.auto_result_outcome_key(
        farther
    )
    assert parallel.auto_result_outcome_key(earlier) < parallel.auto_result_outcome_key(
        closer
    )

    highscore_farther = _result(
        101,
        8.0,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        gold_mask=1,
        gold_bonus_ticks=80,
    )
    highscore_closer = _result(
        101,
        2.0,
        objective=AUTO_OBJECTIVE_HIGHSCORE,
        gold_mask=1,
        gold_bonus_ticks=80,
    )
    assert parallel.auto_result_outcome_key(
        highscore_closer
    ) < parallel.auto_result_outcome_key(highscore_farther)


class _InlineProcessPool:
    """ProcessPool-compatible deterministic harness for coordinator tests."""

    def __init__(self, *args, initializer=None, initargs=(), **kwargs) -> None:
        if initializer is not None:
            initializer(*initargs)

    def submit(self, function, task):
        future = Future()
        future.set_result(function(task))
        return future

    def shutdown(self, wait=True, cancel_futures=False) -> None:
        return None


def test_v247_round_winner_seeds_the_next_parallel_round(monkeypatch) -> None:
    worker_count = 2
    seeds = {
        (run, worker): parallel.derive_auto_search_seed(7, run, worker, worker_count)
        for run in (1, 2)
        for worker in (1, 2)
    }
    left = InputFrame(left=True)
    right = InputFrame(right=True)
    neutral = InputFrame()
    calls: list[tuple[int, tuple[InputFrame, ...]]] = []

    outcomes = {
        seeds[(1, 1)]: (10, 5.0, left),
        seeds[(1, 2)]: (10, 2.0, right),
        seeds[(2, 1)]: (9, 4.0, left),
        seeds[(2, 2)]: (9, 1.0, right),
    }

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        source = tuple(frames)
        calls.append((config.seed, source))
        if config.iterations == 0:
            return _result(10, 10.0, marker=neutral, seed=config.seed)
        tick, distance, marker = outcomes[config.seed]
        return _result(
            tick,
            distance,
            marker=marker,
            baseline_tick=len(source),
            seed=config.seed,
            iterations=config.iterations,
        )

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _InlineProcessPool)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)
    campaign = parallel.optimise_autonomous_campaign(
        object(),
        (neutral,) * 10,
        AutoConfig(iterations=3, beam_width=2, seed=7),
        workers=worker_count,
        runs=2,
        search=fake_search,
    )

    assert campaign.completed_runs == 2
    assert campaign.completed_searches == 4
    assert campaign.result.finish_tick == 9
    assert campaign.result.best.evaluation.pre_finish_exit_distance == 1.0
    assert campaign.result.stats.macro_evaluations == 12
    # Initial parent verification is call zero. Both round-two workers must
    # receive round one's closer same-tick worker-two replay.
    assert calls[3][1] == (right,) * 10
    assert calls[4][1] == (right,) * 10


def test_v247_serial_interrupt_retains_latest_live_checkpoint() -> None:
    source = (InputFrame(),) * 10
    checkpoint = _result(
        9,
        1.0,
        marker=InputFrame(right=True),
        baseline_tick=10,
        seed=99,
    ).best
    saved: list[AutoCandidate] = []

    def interrupting_search(
        level, frames, config, *, progress=None, best_callback=None
    ):
        if config.iterations == 0:
            return _result(10, 5.0)
        assert best_callback is not None
        best_callback(checkpoint)
        raise KeyboardInterrupt

    campaign = parallel.optimise_autonomous_campaign(
        object(),
        source,
        AutoConfig(iterations=10, seed=99),
        workers=1,
        runs=0,
        best_callback=saved.append,
        search=interrupting_search,
    )
    assert campaign.interrupted
    assert campaign.result.finish_tick == 9
    assert campaign.result.best.evaluation.pre_finish_exit_distance == 1.0
    assert saved == [checkpoint]


def test_v247_rejects_an_indefinite_zero_budget_campaign() -> None:
    with pytest.raises(ValueError, match="positive iteration budget"):
        parallel.optimise_autonomous_campaign(
            object(),
            (),
            AutoConfig(iterations=0),
            workers=1,
            runs=0,
        )


def _running_exit_level():
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    for x in range(APP_NUM_GRIDCOLS):
        chars[x * APP_NUM_GRIDROWS + 5] = "1"
    return parse_level_string(
        f"{''.join(chars)}|5^60,134!11^140,134,60,134",
        simulate_enemies=False,
    )


def test_v247_forced_spawn_process_smoke(monkeypatch) -> None:
    spawn_context = multiprocessing.get_context("spawn")
    monkeypatch.setattr(
        parallel.multiprocessing,
        "get_context",
        lambda: spawn_context,
    )
    source = [InputFrame()] * 5 + [InputFrame(right=True)] * 80
    campaign = parallel.optimise_autonomous_campaign(
        _running_exit_level(),
        source,
        AutoConfig(iterations=1, beam_width=2, seed=123),
        workers=2,
        runs=1,
    )
    assert campaign.completed_runs == 1
    assert campaign.completed_searches == 2
    assert campaign.result.finish_tick <= campaign.result.baseline_finish_tick


def test_v263_campaign_history_pruning_keeps_only_live_scheduler_state() -> None:
    def record(
        task_id: int,
        parent_member_id: int,
        *,
        completed: bool,
    ) -> parallel._AutoTaskRecord:
        output = (
            parallel._AutoWorkerResult(
                result=_result(10, float(task_id)),
                seed=task_id,
                run_index=task_id,
                worker_index=1,
                task_id=task_id,
                parent_member_id=parent_member_id,
            )
            if completed
            else None
        )
        return parallel._AutoTaskRecord(
            task_id=task_id,
            generation=task_id,
            parent_member_id=parent_member_id,
            offspring_index=1,
            seed=task_id,
            output=output,
        )

    task_records = {
        1: record(1, 0, completed=True),
        2: record(2, 1, completed=False),
        3: record(3, 1, completed=True),
        4: record(4, 3, completed=False),
        5: record(5, 0, completed=True),
    }
    records_by_key = {
        (item.generation, item.parent_member_id, item.offspring_index): item
        for item in task_records.values()
    }
    members = {
        member_id: parallel._AutoPopulationMember(
            member_id=member_id,
            result=_result(10, float(member_id)),
            parent_member_id=None,
            generation=member_id,
            mutations=(),
        )
        for member_id in (0, 1, 3, 5)
    }
    active_future: Future[parallel._AutoWorkerResult] = Future()

    parallel._prune_campaign_history(
        task_records,
        records_by_key,
        members,
        {2, 3},
        {active_future: task_records[4]},
    )

    assert set(task_records) == {2, 3, 4}
    assert {item.task_id for item in records_by_key.values()} == {2, 3, 4}
    assert set(members) == {1, 3}


class _CampaignLifetimeProbe(str):
    pass


def test_v263_indefinite_parallel_campaign_bounds_retained_results(
    monkeypatch,
) -> None:
    workers = 4
    stop_after_calls = 205
    calls = 0
    probe_refs: list[weakref.ReferenceType[_CampaignLifetimeProbe]] = []
    live_counts: list[int] = []

    def fake_search(level, frames, config, *, progress=None, best_callback=None):
        nonlocal calls
        calls += 1
        gc.collect()
        live_counts.append(sum(ref() is not None for ref in probe_refs))
        if calls >= stop_after_calls:
            raise KeyboardInterrupt
        probe = _CampaignLifetimeProbe(f"result {calls}")
        probe_refs.append(weakref.ref(probe))
        result = _result(
            10,
            1.0,
            baseline_tick=None if config.iterations == 0 else len(frames),
            seed=config.seed,
            iterations=config.iterations,
        )
        return replace(result, diagnostics=(probe,))

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _InlineProcessPool)
    monkeypatch.setattr(parallel, "optimise_autonomous", fake_search)
    campaign = parallel.optimise_autonomous_campaign(
        object(),
        (InputFrame(),) * 10,
        AutoConfig(iterations=1, beam_width=2, seed=7),
        workers=workers,
        runs=0,
        search=fake_search,
    )

    assert campaign.interrupted
    assert campaign.completed_runs >= 40
    assert campaign.completed_searches >= 160
    assert max(live_counts[-40:]) <= 4 * workers
