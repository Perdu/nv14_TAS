import pytest
from nv14_cli import parse_arguments
from nv14_random_splice import RandomSpliceConfig


def test_live_saving_is_opt_in_and_boolean():
    assert not parse_arguments(['auto', 'x.ltm']).auto_splice_live_save_best
    assert parse_arguments(['auto', 'x.ltm', '--splice-live-save-best']).auto_splice_live_save_best
    assert RandomSpliceConfig(live_save_best=True).live_save_best
    with pytest.raises(ValueError, match='boolean'):
        RandomSpliceConfig(live_save_best=1)
