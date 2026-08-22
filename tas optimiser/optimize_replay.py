"""Executable and import-compatibility facade for the n v1.4 optimiser.

The implementation lives in focused ``nv14_*`` modules.  Existing code may
continue importing the established public helpers from ``optimize_replay``.
"""
from __future__ import annotations

import multiprocessing
import os  # noqa: F401 - retained as part of the compatibility facade
from concurrent.futures import ProcessPoolExecutor
from functools import wraps
from pathlib import Path  # noqa: F401 - retained as part of the compatibility facade

import nv14_cli as _cli
import nv14_jump as _jump
import nv14_local as _local
from nv14_auto import *  # noqa: F403
from nv14_auto import optimise_autonomous
from nv14_auto_parallel import optimise_autonomous_campaign
from nv14_cli import *  # noqa: F403
from nv14_engine import (
    InputFrame,  # noqa: F401
    LaunchPad,  # noqa: F401
    Level,  # noqa: F401
    ObjectSpec,  # noqa: F401
    PlayerState,  # noqa: F401
    SimulationState,  # noqa: F401
    UnsupportedTileCollision,  # noqa: F401
    door_control_masks,  # noqa: F401
    parse_level_string,
)
from nv14_jump import *  # noqa: F403
from nv14_jump import mutate_jump_inputs
from nv14_local import *  # noqa: F403
from nv14_local import successful_jump_frames
from nv14_objectives import *  # noqa: F403
from nv14_objectives import state_before_frame
from nv14_replay import *  # noqa: F403
from nv14_replay import parse_combined_level_replay

# A few implementation helpers were historically imported by the bundled
# regression tests.  Keep aliases here, while their single definitions remain
# in the owner modules.
_atomic_write_text = _cli._atomic_write_text
_paths_alias = _cli._paths_alias
_validate_output_paths = _cli._validate_output_paths
_sample_sparse_local_windows = _local._sample_sparse_local_windows
_sparse_window_capacity = _local._sparse_window_capacity
_search_all_input_frames = _local._search_all_input_frames
_search_direction_frames = _local._search_direction_frames
_local_candidate_better = _local._local_candidate_better
_optimise_local_single_run = _local._optimise_local_single_run

_JUMP_OPTIMISER = _jump.optimise_jump_patterns
_LOCAL_OPTIMISER = _local.optimise_local_windows
_CLI_MAIN = _cli.main


@wraps(_JUMP_OPTIMISER)
def optimise_jump_patterns(*args, **kwargs):
    """Compatibility wrapper around :func:`nv14_jump.optimise_jump_patterns`."""
    _jump.ProcessPoolExecutor = ProcessPoolExecutor
    return _JUMP_OPTIMISER(*args, **kwargs)


@wraps(_LOCAL_OPTIMISER)
def optimise_local_windows(*args, **kwargs):
    """Compatibility wrapper around :func:`nv14_local.optimise_local_windows`.

    The small synchronisation block preserves the test/instrumentation seams
    that existed when all local-search globals lived in this module.
    """
    overrides = {
        "ProcessPoolExecutor": ProcessPoolExecutor,
        "state_before_frame": state_before_frame,
        "successful_jump_frames": successful_jump_frames,
        "mutate_jump_inputs": mutate_jump_inputs,
        "_optimise_local_single_run": _optimise_local_single_run,
    }
    for name, value in overrides.items():
        setattr(_local, name, value)
    return _LOCAL_OPTIMISER(*args, **kwargs)


def main() -> None:
    """Run the CLI while retaining legacy facade-level instrumentation seams."""
    _cli.parse_level_string = parse_level_string
    _cli.optimise_autonomous = optimise_autonomous
    _cli.optimise_autonomous_campaign = optimise_autonomous_campaign
    _cli.optimise_jump_patterns = optimise_jump_patterns
    _cli.optimise_local_windows = optimise_local_windows
    _cli.parse_combined_level_replay = parse_combined_level_replay
    return _CLI_MAIN()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        main()
    except KeyboardInterrupt:
        print(_cli._interrupt_message())
        raise SystemExit(130) from None
