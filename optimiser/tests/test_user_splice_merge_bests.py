from nv14_cli import parse_arguments
from nv14_splice_merge import verified_suffix_grafts
from tests.test_random_splice import _baseline


def test_opt_in_merge_of_saved_stages():
    assert parse_arguments(['auto', 'x.ltm', '--splice-merge-bests']).auto_splice_merge_bests
    assert not parse_arguments(['auto', 'x.ltm']).auto_splice_merge_bests


def test_merge_helper_handles_intermediate_checkpoint_without_claiming_final():
    level, frames, _ = _baseline()
    # Only the final sentinel may complete; a shortened reference isn't
    # automatically promoted to a verified completion.
    incomplete = frames[:20]
    assert verified_suffix_grafts(level, frames, incomplete,
                                  seam_frame=10, lookback=3,
                                  completion_required=True) == ()
