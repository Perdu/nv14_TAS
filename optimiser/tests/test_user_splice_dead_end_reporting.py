"""Dead-end is a reporting annotation, never an eligibility constraint."""
import io
import sys

import pytest

from nv14_cli import _load_named_splice_stages, _print_user_splice_progress, parse_arguments
from nv14_engine import InputFrame
from nv14_endpoint import EndpointEvaluator, EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from tests.test_random_splice import _baseline


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_goal_dead_end_parses_and_does_not_change_stage_goal(tmp_path):
    directory = tmp_path / 'goals'
    directory.mkdir()
    goal_file = directory / '442.txt'
    goal_file.write_text('[local]\nsearch="population"\nobjective="min-x"\n'
                         'target-frame=10\nrange="0:10"\ndead-end=true\n')
    level, frames, _ = _baseline()
    args = parse_arguments(['auto', 'level.ltm', '--auto-splice-files', '442'])
    stage = _load_named_splice_stages(level, frames, args, directory, ('442',))[0]
    assert stage.dead_end is True
    assert stage.goal.objective == 'min-x'
    goal_file.write_text(goal_file.read_text().replace('dead-end=true', 'dead-end=false'))
    stage = _load_named_splice_stages(level, frames, args, directory, ('442',))[0]
    assert stage.dead_end is False
    goal_file.write_text(goal_file.read_text().replace('dead-end=false', 'dead-end="true"'))
    with pytest.raises(ValueError, match='boolean'):
        _load_named_splice_stages(level, frames, args, directory, ('442',))


def test_dead_end_summary_is_informative_not_yellow(monkeypatch):
    level, source, _ = _baseline()
    improved = (InputFrame(left=True),) + source[1:]
    goal = EndpointGoal(10, 'min-x')
    assert (EndpointEvaluator(level, goal).evaluate(improved).objective_key <
            EndpointEvaluator(level, goal).evaluate(source).objective_key)
    events = []
    stage = UserSpliceStage('442', goal, 0, 10, dead_end=True)
    optimise_user_splices(level, source, [stage],
                          RandomSpliceConfig(rounds=1, iterations=2, workers=1),
                          saved_stage_candidates={'442': [improved]},
                          completion_policy='checkpoint', summary_only=True,
                          progress=events.append)
    line = next(message for message in events if 'summary:dead-end' in message)
    assert 'reporting only' in line
    assert "'442'" in line
    buffer = TTY()
    monkeypatch.setattr(sys, 'stdout', buffer)
    _print_user_splice_progress(line, color=True)
    assert '\x1b[33m' not in buffer.getvalue()
    assert '[auto:user-splice:summary:dead-end]' in buffer.getvalue()


def test_dead_end_live_checkpoint_still_improves_and_is_not_yellow(monkeypatch):
    import nv14_user_splice as us
    level, source, _ = _baseline()
    goal = EndpointGoal(10, 'min-x')
    improved = (InputFrame(left=True),) + source[1:]
    monkeypatch.setattr(us, '_search_stage', lambda *args, **kwargs: (((improved, 10),), 1, 3))
    events = []
    writes = []
    optimise_user_splices(level, source, [UserSpliceStage('442', goal, 0, 10, dead_end=True)],
                          RandomSpliceConfig(rounds=1, iterations=2, workers=1),
                          completion_policy='checkpoint',
                          stage_best_callback=lambda *a: writes.append(a), progress=events.append)
    assert writes and writes[-1][0] == '442'
    assert any('temporary:dead-end' in message for message in events)
    buffer = TTY()
    monkeypatch.setattr(sys, 'stdout', buffer)
    for message in events:
        _print_user_splice_progress(message, color=True)
    assert '\x1b[33m' not in buffer.getvalue()
