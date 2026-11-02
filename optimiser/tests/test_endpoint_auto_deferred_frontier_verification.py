"""Coordinator verifies only selected Auto survivors, not every worker's donors."""
from concurrent.futures import ThreadPoolExecutor

from nv14_auto_endpoint import AutoEndpointCandidate, AutoEndpointConfig, optimise_auto_endpoint_campaign
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_engine import InputFrame, parse_level_string, APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS


def test_many_worker_donors_only_selected_survivors_rechecked(monkeypatch):
    import concurrent.futures
    import nv14_auto_endpoint as auto

    # Keep this deterministic and count only independent coordinator checks.
    class FakeProcessPool(ThreadPoolExecutor):
        def __init__(self, max_workers, mp_context=None):
            super().__init__(max_workers=max_workers)

    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", FakeProcessPool)
    level = parse_level_string('0' * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + '|5^60,60')
    frames = (InputFrame(),) * 40
    goal = EndpointGoal(target_frame=25, objective='max-x')
    evaluator = EndpointEvaluator(level, goal)

    def fake_worker(payload):
        seed_frames, worker_id = payload[2], payload[6]
        donors = []
        for j in range(16):
            replay = list(seed_frames)
            # Three workers produce overlapping but distinct physical routes.
            frame = 5 + ((worker_id * 7 + j) % 21)
            replay[frame] = (InputFrame(left=True) if j % 3 == 0 else
                             InputFrame(right=True) if j % 3 == 1 else
                             InputFrame(jump=True))
            replay = tuple(replay)
            donors.append(AutoEndpointCandidate(replay, evaluator.evaluate(replay)))
        return None, None, 12, tuple(donors)

    monkeypatch.setattr(auto, '_endpoint_worker', fake_worker)
    original_verify = auto.verify_endpoint
    checked = []

    def counted(*args, **kwargs):
        checked.append(args[1])
        return original_verify(*args, **kwargs)

    monkeypatch.setattr(auto, 'verify_endpoint', counted)
    exported = []
    optimise_auto_endpoint_campaign(
        level, frames, goal,
        AutoEndpointConfig(iterations=200, beam_width=16, seed=42,
                           range_start=5, range_end=25),
        workers=3, runs=2, frontier_callback=exported.extend,
        frontier_limit=6,
    )
    assert exported
    # 3 x 16 x 2 = 96 incoming donor records; only up to 16 inherited
    # and 6 exported candidates need independent physics verification.
    assert len(checked) <= 22, len(checked)
    assert set(x.frames for x in exported).issubset(set(checked))
