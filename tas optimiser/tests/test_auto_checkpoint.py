from __future__ import annotations

import json

import pytest

from nv14_checkpoint import (
    AUTO_CHECKPOINT_FORMAT_VERSION,
    AUTO_CHECKPOINT_KIND,
    OPTIMISER_VERSION,
    AutoCheckpointError,
    read_auto_checkpoint,
    sha256_json,
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


def test_v308_checkpoint_identity_accepts_exact_released_v305_build() -> None:
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


def test_v308_checkpoint_identity_rejects_other_v305_build() -> None:
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


def test_v308_checkpoint_identity_accepts_exact_released_v306_build() -> None:
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


def test_v308_checkpoint_identity_rejects_other_v306_build() -> None:
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


def test_v308_checkpoint_identity_accepts_exact_released_v307_build() -> None:
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
    stored["optimiser_version"] = "3.07"
    stored["optimiser_build_sha256"] = (
        "9ee3cd695e42f53bc157f9edb2970914a276ffc1e640e6a39e5d7817bbf8b79e"
    )

    _validate_checkpoint_identity(stored, expected)


def test_v308_checkpoint_identity_rejects_other_v307_build() -> None:
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
    stored["optimiser_version"] = "3.07"
    stored["optimiser_build_sha256"] = "0" * 64

    with pytest.raises(AutoCheckpointError, match="optimiser version/build"):
        _validate_checkpoint_identity(stored, expected)


def _current_identity_with_splice_limit(
    limit: int,
    *,
    auxiliary_beam_seeds: int = 1,
) -> dict[str, object]:
    configuration = {
        "auto_config": {
            "iterations": 100,
            "splice_plans_per_pair": limit,
            "auxiliary_beam_seeds": auxiliary_beam_seeds,
        },
        "requested_runs": 0,
        "seed_strategy": "resolved-base-seed-v1",
        "stagnation_runs": 5,
        "workers": 8,
    }
    return {
        "optimiser_version": OPTIMISER_VERSION,
        "optimiser_build_sha256": "current",
        "level_identifier": "39-1",
        "level_sha256": "level",
        "simulate_enemies": False,
        "input_replay_sha256": "input",
        "parent_replay_sha256": ["parent"],
        "configuration": configuration,
        "configuration_sha256": sha256_json(configuration),
    }


def _released_v308_identity_without_splice_limit() -> dict[str, object]:
    identity = _current_identity_with_splice_limit(2)
    configuration = dict(identity["configuration"])
    auto_config = dict(configuration["auto_config"])
    auto_config.pop("splice_plans_per_pair")
    auto_config.pop("auxiliary_beam_seeds")
    configuration["auto_config"] = auto_config
    identity.update(
        {
            "optimiser_version": "3.08",
            "optimiser_build_sha256": (
                "0403296b82bdd9c711a35f719608cea5982da23413d2d476f4b2bfcaffdd47e5"
            ),
            "configuration": configuration,
            "configuration_sha256": sha256_json(configuration),
        }
    )
    return identity


def test_v310_checkpoint_accepts_released_v308_with_old_default_plan_limit() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    _validate_checkpoint_identity(
        _released_v308_identity_without_splice_limit(),
        _current_identity_with_splice_limit(2),
    )


def test_v310_checkpoint_rejects_v308_when_new_plan_limit_is_nondefault() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    with pytest.raises(AutoCheckpointError, match="Auto configuration"):
        _validate_checkpoint_identity(
            _released_v308_identity_without_splice_limit(),
            _current_identity_with_splice_limit(4),
        )


def _released_v309_identity(limit: int = 2) -> dict[str, object]:
    identity = _current_identity_with_splice_limit(limit)
    configuration = dict(identity["configuration"])
    auto_config = dict(configuration["auto_config"])
    auto_config.pop("auxiliary_beam_seeds")
    configuration["auto_config"] = auto_config
    identity.update(
        {
            "optimiser_version": "3.09",
            "optimiser_build_sha256": (
                "759ff49138cbafe636c515d26f033255b11079da4ffe1d5fb5ccb9d7073a8220"
            ),
            "configuration": configuration,
            "configuration_sha256": sha256_json(configuration),
        }
    )
    return identity


def test_v310_checkpoint_accepts_exact_released_v309_build() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    _validate_checkpoint_identity(
        _released_v309_identity(),
        _current_identity_with_splice_limit(2),
    )


def test_v310_checkpoint_rejects_modified_v309_build() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    stored = _released_v309_identity()
    stored["optimiser_build_sha256"] = "0" * 64
    with pytest.raises(AutoCheckpointError, match="optimiser version/build"):
        _validate_checkpoint_identity(
            stored,
            _current_identity_with_splice_limit(2),
        )


def test_v310_checkpoint_accepts_v309_nondefault_plan_limit_when_equal() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    _validate_checkpoint_identity(
        _released_v309_identity(5),
        _current_identity_with_splice_limit(5),
    )


def test_v310_checkpoint_rejects_v309_changed_plan_limit() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    with pytest.raises(AutoCheckpointError, match="Auto configuration"):
        _validate_checkpoint_identity(
            _released_v309_identity(5),
            _current_identity_with_splice_limit(4),
        )


def _released_v310_identity_without_auxiliary_limit(
    splice_plans_per_pair: int = 2,
) -> dict[str, object]:
    identity = _current_identity_with_splice_limit(splice_plans_per_pair)
    configuration = dict(identity["configuration"])
    auto_config = dict(configuration["auto_config"])
    auto_config.pop("auxiliary_beam_seeds")
    configuration["auto_config"] = auto_config
    identity.update(
        {
            "optimiser_version": "3.10",
            "optimiser_build_sha256": (
                "48e851b680b4be8c460210fe270d8be51a7f622aa866c59a0112d05456a07879"
            ),
            "configuration": configuration,
            "configuration_sha256": sha256_json(configuration),
        }
    )
    return identity


def test_v311_checkpoint_accepts_exact_v310_at_new_default() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    _validate_checkpoint_identity(
        _released_v310_identity_without_auxiliary_limit(),
        _current_identity_with_splice_limit(2),
    )


def test_v311_checkpoint_accepts_v310_nondefault_existing_limit() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    _validate_checkpoint_identity(
        _released_v310_identity_without_auxiliary_limit(5),
        _current_identity_with_splice_limit(5),
    )


def test_v311_checkpoint_rejects_v310_at_nondefault_auxiliary_limit() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    with pytest.raises(AutoCheckpointError, match="Auto configuration"):
        _validate_checkpoint_identity(
            _released_v310_identity_without_auxiliary_limit(),
            _current_identity_with_splice_limit(
                2,
                auxiliary_beam_seeds=2,
            ),
        )


def test_v311_checkpoint_rejects_modified_v310_build() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    stored = _released_v310_identity_without_auxiliary_limit()
    stored["optimiser_build_sha256"] = "0" * 64
    with pytest.raises(AutoCheckpointError, match="optimiser version/build"):
        _validate_checkpoint_identity(
            stored,
            _current_identity_with_splice_limit(2),
        )


@pytest.mark.parametrize("auxiliary_limit", [0, 1, 3])
def test_v312_checkpoint_accepts_exact_v311_with_matching_configuration(
    auxiliary_limit: int,
) -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    current = _current_identity_with_splice_limit(
        5, auxiliary_beam_seeds=auxiliary_limit
    )
    stored = dict(current)
    stored["optimiser_version"] = "3.11"
    stored["optimiser_build_sha256"] = (
        "2ec99abdb9288c9774443f8a104eda2003eb1f4691c8d17075f285b45465c218"
    )
    _validate_checkpoint_identity(stored, current)


@pytest.mark.parametrize("mismatch", ["build", "configuration"])
def test_v312_checkpoint_rejects_v311_identity_mismatches(mismatch: str) -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    current = _current_identity_with_splice_limit(2, auxiliary_beam_seeds=1)
    stored = _current_identity_with_splice_limit(
        2, auxiliary_beam_seeds=2 if mismatch == "configuration" else 1
    )
    stored["optimiser_version"] = "3.11"
    stored["optimiser_build_sha256"] = (
        "0" * 64 if mismatch == "build" else
        "2ec99abdb9288c9774443f8a104eda2003eb1f4691c8d17075f285b45465c218"
    )
    message = "optimiser version/build" if mismatch == "build" else "Auto configuration"
    with pytest.raises(AutoCheckpointError, match=message):
        _validate_checkpoint_identity(stored, current)
