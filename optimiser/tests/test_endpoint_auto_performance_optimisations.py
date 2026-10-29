"""Performance-only changes must preserve canonical scoring and old proposal streams."""
from dataclasses import replace
from queue import Queue

from nv14_auto_endpoint import (
    AutoEndpointConfig, _EndpointWorkerStats, _endpoint_worker, _input_code,
    optimise_auto_endpoint, optimise_auto_endpoint_campaign,
)
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_engine import InputFrame, parse_level_string, APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS
from nv14_native import require_native
from tests.test_population_exit_distance import completed_variants


def test_packed_single_frame_byte_is_identical_to_native_encoding():
    native = require_native()
    for left in (False, True):
        for right in (False, True):
            for jump in (False, True):
                for trigger in (None, False, True):
                    frame = InputFrame(left, right, jump, trigger)
                    assert _input_code(frame) == native.population_input_key((frame,))[0][0]


def test_native_selected_exit_contains_precise_pre_step_position():
    level, far, close, goal = completed_variants()
    evaluator = EndpointEvaluator(level, goal)
    for replay in (far, close):
        frames = replay + (InputFrame(),)
        key = require_native().population_input_key(frames)[0]
        selection = evaluator._native_plan.scan(
            evaluator._prefix, key, with_pre_position=True)
        assert len(selection) == 8
        assert selection[-1] is not None
        old_api = evaluator._native_plan.scan(evaluator._prefix, key)
        assert len(old_api) == 7
        assert old_api[-2:] == selection[-3:-1]
        expected = evaluator._exact_exit_proximity(
            evaluator._evaluate_state(selection[0],
                                      arrival_eligible=selection[2],
                                      interaction_events=tuple(
                                          goal.interaction_target.alternatives[i]
                                          for i in selection[1])), frames)
        new = evaluator.evaluate(frames)
        assert new.pre_finish_exit_distance == expected.pre_finish_exit_distance
        assert new.objective_key == expected.objective_key


def test_diagnostics_track_duplicates_and_fast_packing_without_extra_budget():
    level = parse_level_string('0' * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + '|5^60,60')
    frames = (InputFrame(),) * 40
    goal = EndpointGoal(target_frame=25, objective='max-x')
    cfg = AutoEndpointConfig(iterations=200, beam_width=12, seed=5,
                             range_start=5, range_end=25, performance_stats=True)
    gathered = []
    baseline, best, count = optimise_auto_endpoint(
        level, frames, goal, cfg, stats_callback=gathered.append)
    assert baseline is not None and best is not None
    assert len(gathered) == 1
    stats = gathered[0]
    assert stats.proposals == cfg.iterations
    assert stats.distinct == count
    assert stats.duplicates == cfg.iterations - count
    assert stats.single_frame_packs > 0
    assert stats.evaluation_seconds >= 0 and stats.total_seconds > 0


def test_supplemental_work_only_begins_after_original_search():
    level_string = '0' * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + '|5^60,60'
    level = parse_level_string(level_string)
    frames = (InputFrame(),) * 40
    goal = EndpointGoal(target_frame=25, objective='max-x')
    _, remote, _ = optimise_auto_endpoint(
        level, frames, goal,
        AutoEndpointConfig(iterations=160, seed=12, range_end=25))
    assert remote is not None
    events = Queue()
    cfg = AutoEndpointConfig(iterations=0, seed=6, range_end=25,
                             shared_refinement_proposals=18, performance_stats=True)
    baseline, best, count = _endpoint_worker((
        level_string, False, frames, goal, cfg, events, 0, 0, (), {'best': remote}))
    assert count > 0
    assert best is not None
    assert best.evaluation.objective_key <= remote.evaluation.objective_key
    items = list(events.queue)
    assert any(isinstance(x, _EndpointWorkerStats) and x.proposals == 0 for x in items)
    assert any(isinstance(x, tuple) and x[0] == 'shared-refinement'
               and x[2] == 18 for x in items)


def test_parallel_stats_and_cli_settings(tmp_path):
    from nv14_cli import parse_arguments
    path = tmp_path / 'config.toml'
    path.write_text('[auto]\nshared-refinement-proposals = 20\nperformance-stats = true\n')
    args = parse_arguments(['auto', 'source.ltm', '--config', str(path)])
    assert args.auto_shared_refinement_proposals == 20
    assert args.auto_performance_stats is True

    level = parse_level_string('0' * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS) + '|5^60,60')
    rows = []
    baseline, best, count = optimise_auto_endpoint_campaign(
        level, (InputFrame(),) * 40,
        EndpointGoal(target_frame=25, objective='max-x'),
        AutoEndpointConfig(iterations=50, seed=11, range_end=25,
                           shared_refinement_proposals=20, performance_stats=True),
        workers=2, runs=1, progress=rows.append)
    assert best is not None and count > 0
    assert any('performance worker' in line for line in rows)
