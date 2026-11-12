"""A large repair budget must explore independent seams before deepening one."""
from __future__ import annotations

import nv14_user_splice as us
from nv14_cli import parse_arguments
from nv14_engine import InputFrame
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_splice_merge import BridgeRepairResult
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline
from tests.test_user_splice_manual_input_merge import _finished_slow_run


def test_sweep_option_cli_and_toml(tmp_path):
    defaults = parse_arguments(['auto', 'replay.ltm'])
    assert defaults.auto_splice_merge_repair_sweep_iterations == 2000
    assert defaults.auto_splice_merge_repair_seams == 3
    config = tmp_path / 'route.toml'
    config.write_text('[multi-splicer]\nsplice-files=["first"]\n'
                      'merge-repair-sweep-iterations=73\n'
                      'merge-repair-seams=4\n', encoding='utf-8')
    parsed = parse_arguments(['auto', 'replay.ltm', '--splice-config', str(config)])
    assert parsed.auto_splice_merge_repair_sweep_iterations == 73
    assert parsed.auto_splice_merge_repair_seams == 4
    assert (parse_arguments(['auto', 'replay.ltm', '--splice-config', str(config),
                            '--splice-merge-repair-sweep-iterations', '11',
                            '--splice-merge-repair-seams', '2'])
            .auto_splice_merge_repair_sweep_iterations == 11)
    assert (parse_arguments(['auto', 'replay.ltm', '--splice-config', str(config),
                            '--splice-merge-repair-seams', '2'])
            .auto_splice_merge_repair_seams == 2)


def test_repair_visits_all_pairs_before_deepening_any(monkeypatch):
    level, manual, _ = _baseline()
    previous = _finished_slow_run(level)
    assert previous != manual
    alt = (InputFrame(left=True),) + previous[1:]
    seen = []

    def fake_repair(_level, prefix, suffix, **kw):
        seen.append((tuple(prefix), tuple(suffix), kw['config'].repair_iterations,
                     kw['seam_frame']))
        return BridgeRepairResult((), searches=1, evaluations=kw['config'].repair_iterations)

    monkeypatch.setattr(us, 'repair_suffix_grafts', fake_repair)
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_k: ())
    messages = []
    stages = [UserSpliceStage('first', EndpointGoal(10, 'min-x'), 0, 10),
              UserSpliceStage('later', EndpointGoal(20, 'min-x'), 10, 20)]
    optimise_user_splices(
        level, manual, stages,
        RandomSpliceConfig(iterations=2, repair_iterations=5),
        completion_policy='checkpoint', merge_stage_bests=True,
        merge_only=True, merge_repair_only=True, merge_repair_pairs=2,
        merge_repair_seams=1, merge_repair_sweep_iterations=2,
        saved_final_frames=previous,
        saved_stage_candidates={'later': [alt]}, progress=messages.append)
    assert len(seen) == 6
    # First pass considers two different pairs; later passes revisit each.
    assert seen[0][:2] != seen[1][:2]
    assert seen[0][:2] == seen[2][:2] == seen[4][:2]
    assert seen[1][:2] == seen[3][:2] == seen[5][:2]
    assert [item[2] for item in seen] == [2, 2, 2, 2, 1, 1]
    assert any('bridge scheduling: 2 independent pair(s); 2 physical seam centre(s); 3 sweep(s)' in x
               for x in messages)
    assert any('bridge repair done: 2 independent' in x for x in messages)


def test_explicit_repair_frame_remains_fixed_across_sweeps(monkeypatch):
    level, manual, _ = _baseline()
    previous = _finished_slow_run(level)
    seen = []

    def fake_repair(_level, prefix, suffix, **kw):
        seen.append((kw['at_frame'], kw['seam_frame'], kw['config'].repair_iterations))
        return BridgeRepairResult((), searches=1, evaluations=1)

    monkeypatch.setattr(us, 'repair_suffix_grafts', fake_repair)
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_k: ())
    optimise_user_splices(
        level, manual, [UserSpliceStage('first', EndpointGoal(20, 'min-x'), 0, 20)],
        RandomSpliceConfig(iterations=2, repair_iterations=5),
        completion_policy='checkpoint', merge_stage_bests=True,
        merge_only=True, merge_repair_only=True, merge_repair_pairs=1,
        merge_repair_sweep_iterations=2, merge_repair_at_frame=17,
        saved_final_frames=previous)
    assert seen == [(17, 17, 2), (17, 17, 2), (17, 17, 1)]


def test_each_automatic_seam_gets_full_budget_without_drift(monkeypatch):
    level, manual, _ = _baseline()
    previous = _finished_slow_run(level)
    changed = (InputFrame(left=True),) + manual[1:]
    seen = []
    messages = []

    def fake_repair(_level, _prefix, _suffix, **kw):
        seen.append((kw['seam_frame'], kw['config'].repair_iterations))
        return BridgeRepairResult((), searches=1, evaluations=1)

    monkeypatch.setattr(us, 'repair_suffix_grafts', fake_repair)
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_k: ())
    stages = [UserSpliceStage('first', EndpointGoal(10, 'min-x'), 0, 10),
              UserSpliceStage('later', EndpointGoal(20, 'min-x'), 10, 20)]
    optimise_user_splices(
        level, manual, stages,
        RandomSpliceConfig(iterations=2, repair_iterations=5),
        completion_policy='checkpoint', merge_stage_bests=True,
        merge_only=True, merge_repair_only=True, merge_repair_pairs=1,
        merge_repair_from='first', merge_repair_to='later',
        merge_repair_seams=3, merge_repair_sweep_iterations=2,
        saved_stage_candidates={'first': [changed], 'later': [previous]},
        progress=messages.append)
    assert len(seen) == 9
    first_sweep = [seam for seam, _ in seen[:3]]
    assert first_sweep == sorted(set(first_sweep))  # Three distinct centres
    assert [seam for seam, _ in seen] == first_sweep * 3
    assert [budget for _, budget in seen] == [2] * 6 + [1] * 3
    for seam in first_sweep:
        assert sum(budget for frame, budget in seen if frame == seam) == 5
    assert any('1 independent pair(s); 3 physical seam centre(s); '
               '3 sweep(s) per seam' in line for line in messages)
    assert any('5 per worker/target FOR EACH seam, not globally' in line
               for line in messages)


def test_automatic_two_pairs_each_seam_has_independent_budget(monkeypatch):
    level, manual, _ = _baseline()
    previous = _finished_slow_run(level)
    alt = (InputFrame(left=True),) + previous[1:]
    seen = []

    def fake_repair(_level, prefix, suffix, **kw):
        seen.append((tuple(prefix), tuple(suffix), kw['seam_frame'],
                     kw['config'].repair_iterations))
        return BridgeRepairResult((), searches=1, evaluations=1)

    monkeypatch.setattr(us, 'repair_suffix_grafts', fake_repair)
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_k: ())
    stages = [UserSpliceStage('first', EndpointGoal(10, 'min-x'), 0, 10),
              UserSpliceStage('later', EndpointGoal(20, 'min-x'), 10, 20)]
    optimise_user_splices(
        level, manual, stages,
        RandomSpliceConfig(iterations=2, repair_iterations=5),
        completion_policy='checkpoint', merge_stage_bests=True,
        merge_only=True, merge_repair_only=True, merge_repair_pairs=2,
        merge_repair_seams=3, merge_repair_sweep_iterations=2,
        saved_final_frames=previous,
        saved_stage_candidates={'later': [alt]})
    # Both pairings are visited in the first quantum, not just the first pair.
    assert seen[0][:2] != seen[1][:2]
    jobs = [(prefix, suffix, frame) for prefix, suffix, frame, _ in seen]
    assert len(set(jobs)) >= 3
    for job in set(jobs):
        assert sum(budget for prefix, suffix, frame, budget in seen
                   if (prefix, suffix, frame) == job) == 5
    assert len(seen) == len(set(jobs)) * 3


def test_explicit_at_skips_extra_automatic_seam_centres(monkeypatch):
    level, manual, _ = _baseline()
    previous = _finished_slow_run(level)
    seen = []

    def fake_repair(_level, _prefix, _suffix, **kw):
        seen.append((kw['seam_frame'], kw['config'].repair_iterations))
        return BridgeRepairResult((), searches=1, evaluations=1)

    monkeypatch.setattr(us, 'repair_suffix_grafts', fake_repair)
    monkeypatch.setattr(us, 'verified_suffix_grafts', lambda *_a, **_k: ())
    optimise_user_splices(
        level, manual, [UserSpliceStage('first', EndpointGoal(20, 'min-x'), 0, 20)],
        RandomSpliceConfig(iterations=2, repair_iterations=5),
        completion_policy='checkpoint', merge_stage_bests=True,
        merge_only=True, merge_repair_only=True, merge_repair_pairs=1,
        merge_repair_seams=12, merge_repair_sweep_iterations=2,
        merge_repair_at_frame=17, saved_final_frames=previous)
    assert seen == [(17, 2), (17, 2), (17, 1)]
