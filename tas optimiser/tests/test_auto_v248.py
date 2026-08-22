from __future__ import annotations

from concurrent.futures import Future
from queue import Queue

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
    frames = (marker,) * tick
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
        result=_result(100, float(rank)),
        parent_member_id=parent_id,
        generation=2,
        mutations=(),
    )


def test_v248_survivor_filter_keeps_three_immediate_parent_lineages() -> None:
    # Natural top four would be A1, A2, B1, B2. The one-generation diversity
    # rule reserves the final slot for C1 instead.
    members = (
        _member(1, 10, 1),
        _member(2, 10, 2),
        _member(3, 20, 3),
        _member(4, 20, 4),
        _member(5, 30, 5),
        _member(6, 40, 6),
        _member(7, 30, 7),
        _member(8, 40, 8),
    )
    selected = parallel._select_population_survivors(
        members, 4, enforce_parent_diversity=True
    )
    assert [member.member_id for member in selected] == [1, 2, 3, 5]
    assert len({member.parent_member_id for member in selected}) == 3


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
    campaign = parallel.optimise_autonomous_campaign(
        level,
        source,
        AutoConfig(iterations=1, beam_width=2, seed=456),
        workers=4,
        runs=2,
    )
    assert campaign.completed_runs == 2
    assert campaign.completed_searches >= 8
    assert campaign.result.finish_tick <= campaign.result.baseline_finish_tick


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
