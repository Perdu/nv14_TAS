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
