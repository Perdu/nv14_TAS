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


def test_v420_checkpoint_rejects_ambiguous_previous_numeric_range_end() -> None:
    """Old checkpoints cannot distinguish an explicit end from a frozen one."""
    from nv14_auto_parallel import _validate_checkpoint_identity

    current = _current_identity_with_splice_limit(2)
    current_config = current["configuration"]["auto_config"]
    current_config.update(range_start=100, range_end=None)
    current["configuration_sha256"] = sha256_json(current["configuration"])
    stored = _current_identity_with_splice_limit(2)
    stored_config = stored["configuration"]["auto_config"]
    stored_config.update(range_start=100, range_end=133)
    stored["configuration_sha256"] = sha256_json(stored["configuration"])
    stored["optimiser_version"] = "4.19"
    stored["optimiser_build_sha256"] = (
        "b59df672d93ddd58dd43bbe7820c5e307f6e1c3a52e8a3a853a7aef1f087bfb8"
    )

    with pytest.raises(AutoCheckpointError, match="Auto configuration"):
        _validate_checkpoint_identity(stored, current)


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


@pytest.mark.parametrize("auxiliary_limit", [0, 1, 3])
def test_v313_checkpoint_accepts_exact_v312(auxiliary_limit: int) -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    current = _current_identity_with_splice_limit(5, auxiliary_beam_seeds=auxiliary_limit)
    stored = dict(current)
    stored["optimiser_version"] = "3.12"
    stored["optimiser_build_sha256"] = (
        "e4c5c7f5cb35c7db295ce0f0a41ba44d134818e9729da57d9907130d515dfcf9"
    )
    _validate_checkpoint_identity(stored, current)


def test_v313_checkpoint_rejects_modified_v312() -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    current = _current_identity_with_splice_limit(2)
    stored = dict(current)
    stored["optimiser_version"] = "3.12"
    stored["optimiser_build_sha256"] = "0" * 64
    with pytest.raises(AutoCheckpointError, match="optimiser version/build"):
        _validate_checkpoint_identity(stored, current)


@pytest.mark.parametrize("version,build", [
    ("4.19", "b59df672d93ddd58dd43bbe7820c5e307f6e1c3a52e8a3a853a7aef1f087bfb8"),
    ("4.18", "6fabfc548fd47897f1b50279fc950c5ca7c44417184b586ede495511e0904704"),
    ("4.17", "49481841b51d01c01e7b9bb7dc6d77b7c8340b581ed82ae9a04484575d0e9dc1"),
    ("4.16.1", "84b83da1c8dfc7af283bcb0df7711488c8c4ccd74357fc40ff261db957cadd75"),
    ("4.16", "e0e9694fff1e09972226f546f4b92008bcb102dd3d753f58cee8a67820c12cfb"),
    ("4.15", "d01e9952902390bdf34655c6829107122047a5d4731ba33afb93a5200180f263"),
    ("4.14", "31904e99868ca0999b68e64fc5de4f1268d394db8e0f6d4696c61d6cfae84127"),
    ("4.13", "5c57bc9ed211356c6f5feaf46a1e8d36b5431d824f407381948e88392b5fa667"),
    ("4.12", "b03fff98694b5484ce994a35ff3858133c7e877a296d1b64d7da0f74f44e9caf"),
    ("3.21", "4e14f7fe91d5f9e98c77fe9ed20c3f405b5850b0cc1cd322f074b8a8e5e3f4c0"),
    ("4.00", "8eb8ebac48658d944e3bb704dc1737cac379f6ef7fcf43c47907b8f4884bb0b1"),
    ("4.01", "0b07774c0484180458466818510a3c195ed69659f95037b651b78acf0ec1a4fb"),
    ("4.02", "7194de5087a50029b424aa24d5723e0a17d1e0c2d7475d66a7b7e7169b790a39"),
    ("4.03", "c7b7bf9921313a69ce3bea95ff6cbe6b3e6cbfae4701818a2c39646400eeed4f"),
    ("4.04", "bce21a68e65a6d53d1b356027888a5dc97495fc85894a2acc78fea66334197c3"),
    ("4.05", "527e0eeb51ddb07c495f09749f9f2729792f8b81b8ec19b453fa0180f7ab1531"),
    ("4.06", "1e4b46614c73d789dd76aa2b7bf9b95c5625dfb7b8a77767d7b855480a7f5a8c"),
    ("4.07", "2b8191af0d999db0061fb8b7dc06fb625f945fd9199e0d94c95f559607c8b533"),
    ("4.08", "695db08b11807cfa6ca60193118b3442d4ffcb858db2e796f8563771e5f5f05b"),
    ("4.08.1", "7e14cf84ace05735e5fbe8b22f7428600a68e5ffe73671373155359c59c84704"),
    ("4.11", "1163754396f1032f6a9442f1377e0be463567f926cc26abc4c559bc1335a0571"),
    ("4.10", "651d4adf531cb3935ebe3a04cfa1830f0606578c56c40399677fdeba037bcd01"),
    ("4.09", "d523d67b05a4446d606c4a6dd72b82885fea889204e8e1b2509a2ad8b40aa60d"),
    ("3.13", "225bfb93af3451cfee6fd9601ddd495cb4105b1a21bf025ff0e3f96ff2244371"),
    ("3.14", "5481fae4dab85df23652b933c162c8277338fc1896f3a426a7b7b3beea32f0f7"),
    ("3.15", "7fefdab32516b6ebbdc06f24ddd0f39249ea7a020e1c40b83b94e51d0c977afb"),
])
@pytest.mark.parametrize("auxiliary_limit", [0, 1, 3])
def test_checkpoint_accepts_exact_v313_and_v314(auxiliary_limit: int, version: str, build: str) -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    current = _current_identity_with_splice_limit(5, auxiliary_beam_seeds=auxiliary_limit)
    stored = dict(current)
    stored["optimiser_version"] = version
    stored["optimiser_build_sha256"] = build
    _validate_checkpoint_identity(stored, current)


@pytest.mark.parametrize("version,build", [
    ("4.19", "b59df672d93ddd58dd43bbe7820c5e307f6e1c3a52e8a3a853a7aef1f087bfb8"),
    ("4.18", "6fabfc548fd47897f1b50279fc950c5ca7c44417184b586ede495511e0904704"),
    ("4.17", "49481841b51d01c01e7b9bb7dc6d77b7c8340b581ed82ae9a04484575d0e9dc1"),
    ("4.16.1", "84b83da1c8dfc7af283bcb0df7711488c8c4ccd74357fc40ff261db957cadd75"),
    ("4.16", "e0e9694fff1e09972226f546f4b92008bcb102dd3d753f58cee8a67820c12cfb"),
    ("4.15", "d01e9952902390bdf34655c6829107122047a5d4731ba33afb93a5200180f263"),
    ("4.14", "31904e99868ca0999b68e64fc5de4f1268d394db8e0f6d4696c61d6cfae84127"),
    ("4.13", "5c57bc9ed211356c6f5feaf46a1e8d36b5431d824f407381948e88392b5fa667"),
    ("4.12", "b03fff98694b5484ce994a35ff3858133c7e877a296d1b64d7da0f74f44e9caf"),
    ("3.21", "4e14f7fe91d5f9e98c77fe9ed20c3f405b5850b0cc1cd322f074b8a8e5e3f4c0"),
    ("4.00", "8eb8ebac48658d944e3bb704dc1737cac379f6ef7fcf43c47907b8f4884bb0b1"),
    ("4.01", "0b07774c0484180458466818510a3c195ed69659f95037b651b78acf0ec1a4fb"),
    ("4.02", "7194de5087a50029b424aa24d5723e0a17d1e0c2d7475d66a7b7e7169b790a39"),
    ("4.03", "c7b7bf9921313a69ce3bea95ff6cbe6b3e6cbfae4701818a2c39646400eeed4f"),
    ("4.04", "bce21a68e65a6d53d1b356027888a5dc97495fc85894a2acc78fea66334197c3"),
    ("4.05", "527e0eeb51ddb07c495f09749f9f2729792f8b81b8ec19b453fa0180f7ab1531"),
    ("4.06", "1e4b46614c73d789dd76aa2b7bf9b95c5625dfb7b8a77767d7b855480a7f5a8c"),
    ("4.07", "2b8191af0d999db0061fb8b7dc06fb625f945fd9199e0d94c95f559607c8b533"),
    ("4.08", "695db08b11807cfa6ca60193118b3442d4ffcb858db2e796f8563771e5f5f05b"),
    ("4.08.1", "7e14cf84ace05735e5fbe8b22f7428600a68e5ffe73671373155359c59c84704"),
    ("4.11", "1163754396f1032f6a9442f1377e0be463567f926cc26abc4c559bc1335a0571"),
    ("4.10", "651d4adf531cb3935ebe3a04cfa1830f0606578c56c40399677fdeba037bcd01"),
    ("4.09", "d523d67b05a4446d606c4a6dd72b82885fea889204e8e1b2509a2ad8b40aa60d"),
    ("3.13", "225bfb93af3451cfee6fd9601ddd495cb4105b1a21bf025ff0e3f96ff2244371"),
    ("3.14", "5481fae4dab85df23652b933c162c8277338fc1896f3a426a7b7b3beea32f0f7"),
    ("3.15", "7fefdab32516b6ebbdc06f24ddd0f39249ea7a020e1c40b83b94e51d0c977afb"),
])
@pytest.mark.parametrize("mismatch", ["build", "configuration"])
def test_checkpoint_rejects_v313_and_v314_mismatches(mismatch: str, version: str, build: str) -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    current = _current_identity_with_splice_limit(2)
    stored = _current_identity_with_splice_limit(5 if mismatch == "configuration" else 2)
    stored["optimiser_version"] = version
    stored["optimiser_build_sha256"] = "0" * 64 if mismatch == "build" else build
    message = "optimiser version/build" if mismatch == "build" else "Auto configuration"
    with pytest.raises(AutoCheckpointError, match=message):
        _validate_checkpoint_identity(stored, current)


@pytest.mark.parametrize("version", ["4.08.1", "4.10", "modified-4.09"])
def test_v410_checkpoint_requires_exact_v409_version_and_build_pair(version: str) -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    current = _current_identity_with_splice_limit(2)
    stored = dict(current)
    stored["optimiser_version"] = version
    stored["optimiser_build_sha256"] = (
        "d523d67b05a4446d606c4a6dd72b82885fea889204e8e1b2509a2ad8b40aa60d"
    )
    with pytest.raises(AutoCheckpointError, match="optimiser version/build"):
        _validate_checkpoint_identity(stored, current)


@pytest.mark.parametrize("version", ["4.09", "4.11", "modified-4.10"])
def test_v411_checkpoint_requires_exact_v410_version_and_build_pair(version: str) -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    current = _current_identity_with_splice_limit(2)
    stored = dict(current)
    stored["optimiser_version"] = version
    stored["optimiser_build_sha256"] = (
        "651d4adf531cb3935ebe3a04cfa1830f0606578c56c40399677fdeba037bcd01"
    )
    with pytest.raises(AutoCheckpointError, match="optimiser version/build"):
        _validate_checkpoint_identity(stored, current)


@pytest.mark.parametrize("version", ["4.10", "4.12", "modified-4.11"])
def test_v412_checkpoint_requires_exact_v411_version_and_build_pair(version: str) -> None:
    from nv14_auto_parallel import _validate_checkpoint_identity

    current = _current_identity_with_splice_limit(2)
    stored = dict(current)
    stored["optimiser_version"] = version
    stored["optimiser_build_sha256"] = (
        "1163754396f1032f6a9442f1377e0be463567f926cc26abc4c559bc1335a0571"
    )
    with pytest.raises(AutoCheckpointError, match="optimiser version/build"):
        _validate_checkpoint_identity(stored, current)
