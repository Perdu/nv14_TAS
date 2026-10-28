"""Live progress for the endpoint Auto workers and coordinator."""
from queue import Queue

from nv14_auto_endpoint import (
    AutoEndpointCandidate, AutoEndpointConfig, _EndpointWorkerProgress,
    _endpoint_worker, optimise_auto_endpoint, optimise_auto_endpoint_campaign,
)
from nv14_endpoint import EndpointGoal
from nv14_engine import APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, InputFrame, parse_level_string


LEVEL = "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + "|5^60,60"
SOURCE = (InputFrame(),) * 36
GOAL = EndpointGoal(target_frame=25, objective="max-x")


def test_search_reports_baseline_and_final_attempts_without_changing_budget():
    updates = []
    baseline, best, count = optimise_auto_endpoint(
        parse_level_string(LEVEL), SOURCE, GOAL,
        AutoEndpointConfig(iterations=130, beam_width=8, seed=3, range_end=25),
        progress=lambda proposals, evaluated, candidate: updates.append(
            (proposals, evaluated, candidate)),
    )
    assert updates[0][:2] == (0, 0)
    assert updates[-1][0] == 130
    assert updates[-1][1] == count
    assert all(a[0] <= b[0] and a[1] <= b[1]
               for a, b in zip(updates, updates[1:]))
    assert best is not None
    assert baseline.evaluation.feasible


def test_worker_emits_lightweight_progress_events():
    queue = Queue()
    baseline, best, count = _endpoint_worker((
        LEVEL, False, SOURCE, GOAL,
        AutoEndpointConfig(iterations=110, seed=17, range_end=25), queue, 4,
    ))
    messages = list(queue.queue)
    heartbeats = [item for item in messages if isinstance(item, _EndpointWorkerProgress)]
    assert heartbeats[0].worker_index == 4
    assert heartbeats[0].proposals == 0
    assert heartbeats[-1].proposals == 110
    assert heartbeats[-1].evaluations == count
    assert all(item.elapsed_seconds >= 0 for item in heartbeats)
    assert any(isinstance(item, AutoEndpointCandidate) for item in messages)
    assert best is not None and baseline.evaluation.feasible


def test_parallel_campaign_prints_worker_activity_and_round_totals():
    output = []
    baseline, best, count = optimise_auto_endpoint_campaign(
        parse_level_string(LEVEL), SOURCE, GOAL,
        AutoEndpointConfig(iterations=110, seed=11, range_end=25),
        workers=2, runs=2, progress=output.append,
    )
    assert best is not None and baseline.evaluation.feasible
    assert count > 0
    assert any("round 1/2: starting 2 worker(s)" in line for line in output)
    assert any("worker 1/2 finished" in line for line in output)
    assert any("worker 2/2 finished" in line for line in output)
    assert any("220/220 proposals" in line for line in output)
    assert any("distinct evaluations" in line for line in output)
    assert any("round 2/2 complete" in line for line in output)


def test_serial_campaign_shows_progress_without_parallel_queue():
    output = []
    _, _, count = optimise_auto_endpoint_campaign(
        parse_level_string(LEVEL), SOURCE, GOAL,
        AutoEndpointConfig(iterations=60, seed=5, range_end=25),
        workers=1, runs=1, progress=output.append,
    )
    assert count > 0
    assert any("60/60 proposals" in line and "worker 1/1" in line
               for line in output)
