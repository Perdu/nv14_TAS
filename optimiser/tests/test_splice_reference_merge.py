"""Reference suffixes are proposals, never unverified completed results."""
import pytest

from nv14_cli import parse_arguments
from nv14_engine import InputFrame
from nv14_splice_merge import verified_suffix_grafts
from nv14_user_splice import UserSpliceStage, optimise_user_splices
from nv14_endpoint import EndpointGoal
from nv14_random_splice import RandomSpliceConfig
from tests.test_random_splice import _baseline


def test_reference_grafts_are_canonical_completed_replays():
    level, frames, baseline = _baseline()
    grafts = verified_suffix_grafts(level, frames, frames, seam_frame=15, lookback=3)
    assert frames in grafts
    for trial in grafts:
        from nv14_auto import verify_trimmed_replay
        assert verify_trimmed_replay(level, trial).finish_tick == len(trial)


def test_invalid_reference_is_rejected_before_search():
    level, frames, _ = _baseline()
    stages = (UserSpliceStage('end', EndpointGoal(10, 'max-x'), 0, 10),)
    with pytest.raises(ValueError, match='verified completed replay'):
        optimise_user_splices(level, frames, stages,
                              RandomSpliceConfig(rounds=1, iterations=2),
                              reference_frames=(InputFrame(),))


def test_reference_cli_opt_in():
    args = parse_arguments(['auto', 'run.ltm', '--splice-reference', 'reference.ltm'])
    assert str(args.auto_splice_reference) == 'reference.ltm'
