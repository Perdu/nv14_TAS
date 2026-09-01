from __future__ import annotations

import json

import pytest

from nv14_checkpoint import (
    AUTO_CHECKPOINT_FORMAT_VERSION,
    AUTO_CHECKPOINT_KIND,
    AutoCheckpointError,
    read_auto_checkpoint,
    write_auto_checkpoint,
)


def test_v304_checkpoint_envelope_round_trips_and_detects_torn_content(
    tmp_path,
) -> None:
    path = tmp_path / "campaign.json"
    write_auto_checkpoint(
        path,
        {
            "identity": {"test": "identity"},
            "state": {"completed_runs": 3},
        },
    )

    payload = read_auto_checkpoint(path)
    assert payload["kind"] == AUTO_CHECKPOINT_KIND
    assert payload["format_version"] == AUTO_CHECKPOINT_FORMAT_VERSION
    assert payload["state"]["completed_runs"] == 3
    assert not tuple(path.parent.glob(f".{path.name}.*.tmp"))

    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["state"]["completed_runs"] = 4
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(AutoCheckpointError, match="integrity hash"):
        read_auto_checkpoint(path)


def test_v304_checkpoint_format_rejects_non_checkpoint_json(tmp_path) -> None:
    path = tmp_path / "not-a-checkpoint.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(AutoCheckpointError, match="envelope is incomplete"):
        read_auto_checkpoint(path)


def test_v307_checkpoint_identity_accepts_exact_released_v305_build() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity
    from nv14_checkpoint import OPTIMISER_VERSION, optimiser_build_hash

    expected = {
        "optimiser_version": OPTIMISER_VERSION,
        "optimiser_build_sha256": optimiser_build_hash(),
        "level_identifier": "00-3",
        "level_sha256": "level",
        "simulate_enemies": True,
        "input_replay_sha256": "input",
        "parent_replay_sha256": ["parent"],
        "configuration_sha256": "config",
    }
    stored = dict(expected)
    stored["optimiser_version"] = "3.05"
    stored["optimiser_build_sha256"] = (
        "d0a7ea78c7b24de46bac1ff1c00774de833ef23107a07b743ebffe67d755e43e"
    )

    _validate_checkpoint_identity(stored, expected)


def test_v307_checkpoint_identity_rejects_other_v305_build() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity
    from nv14_checkpoint import OPTIMISER_VERSION, optimiser_build_hash

    expected = {
        "optimiser_version": OPTIMISER_VERSION,
        "optimiser_build_sha256": optimiser_build_hash(),
        "level_identifier": "00-3",
        "level_sha256": "level",
        "simulate_enemies": True,
        "input_replay_sha256": "input",
        "parent_replay_sha256": ["parent"],
        "configuration_sha256": "config",
    }
    stored = dict(expected)
    stored["optimiser_version"] = "3.05"
    stored["optimiser_build_sha256"] = "0" * 64

    with pytest.raises(AutoCheckpointError, match="optimiser version/build"):
        _validate_checkpoint_identity(stored, expected)


def test_v307_checkpoint_identity_accepts_exact_released_v306_build() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity
    from nv14_checkpoint import OPTIMISER_VERSION, optimiser_build_hash

    expected = {
        "optimiser_version": OPTIMISER_VERSION,
        "optimiser_build_sha256": optimiser_build_hash(),
        "level_identifier": "00-3",
        "level_sha256": "level",
        "simulate_enemies": True,
        "input_replay_sha256": "input",
        "parent_replay_sha256": ["parent"],
        "configuration_sha256": "config",
    }
    stored = dict(expected)
    stored["optimiser_version"] = "3.06"
    stored["optimiser_build_sha256"] = (
        "f394554d7ca12ac8a9e1d05b443a709a7e9597f7340e511ef3bd1e029d6f3475"
    )

    _validate_checkpoint_identity(stored, expected)


def test_v307_checkpoint_identity_rejects_other_v306_build() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity
    from nv14_checkpoint import OPTIMISER_VERSION, optimiser_build_hash

    expected = {
        "optimiser_version": OPTIMISER_VERSION,
        "optimiser_build_sha256": optimiser_build_hash(),
        "level_identifier": "00-3",
        "level_sha256": "level",
        "simulate_enemies": True,
        "input_replay_sha256": "input",
        "parent_replay_sha256": ["parent"],
        "configuration_sha256": "config",
    }
    stored = dict(expected)
    stored["optimiser_version"] = "3.06"
    stored["optimiser_build_sha256"] = "0" * 64

    with pytest.raises(AutoCheckpointError, match="optimiser version/build"):
        _validate_checkpoint_identity(stored, expected)
