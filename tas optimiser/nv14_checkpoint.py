"""Durable, versioned Auto campaign checkpoint storage.

The checkpoint payload is deliberately ordinary JSON.  Native state, trace
pointers, multiprocessing primitives and futures never enter this module.
Writes use a same-directory temporary file, ``fsync`` and ``os.replace`` so a
spot-instance interruption leaves either the preceding committed checkpoint
or the complete new one.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

OPTIMISER_VERSION = "3.08"
AUTO_CHECKPOINT_KIND = "nv14-auto-campaign"
AUTO_CHECKPOINT_FORMAT_VERSION = 1

_BUILD_FINGERPRINT_FILES = (
    "nv14_auto.py",
    "nv14_auto_parallel.py",
    "nv14_checkpoint.py",
    "nv14_engine.py",
    "nv14_native.py",
    "nv14_objectives.py",
    "nv14_replay.py",
    "nv14_search.py",
    "nv14_splice_index.py",
    "native/nv14_auto.c",
    "native/nv14_auto.h",
    "native/nv14_core.c",
    "native/nv14_core.h",
    "native/nv14_patch.c",
    "native/nv14_patch.h",
    "native/nv14_search.c",
    "native/nv14_search.h",
)


class AutoCheckpointError(ValueError):
    """A checkpoint is missing, corrupt, incompatible or internally invalid."""


def canonical_json_bytes(value: object) -> bytes:
    """Return the strict canonical JSON representation used by all hashes."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: object) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def optimiser_build_hash() -> str:
    """Hash the policy and native sources which determine resumed behaviour."""
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    digest.update(f"nv14-tas-replay-optimiser:{OPTIMISER_VERSION}\n".encode())
    found = 0
    for relative_name in _BUILD_FINGERPRINT_FILES:
        path = root / relative_name
        try:
            content = path.read_bytes()
        except OSError:
            continue
        found += 1
        digest.update(relative_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    # An unpacked source archive contains every entry.  Retaining the version
    # string as a fallback keeps installed/minimal distributions identifiable.
    digest.update(found.to_bytes(4, "big"))
    return digest.hexdigest()


def _checkpoint_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    body["kind"] = AUTO_CHECKPOINT_KIND
    body["format_version"] = AUTO_CHECKPOINT_FORMAT_VERSION
    return {
        "integrity_sha256": sha256_json(body),
        "payload": body,
    }


def write_auto_checkpoint(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically commit one complete checkpoint payload to *path*."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AutoCheckpointError(
            f"could not create Auto checkpoint directory {path.parent}: {exc}"
        ) from exc

    envelope = _checkpoint_envelope(payload)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(
                envelope,
                stream,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        # Persist the directory entry on POSIX.  Windows does not support
        # opening directories this way; os.replace is still atomic there.
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except (OSError, TypeError, ValueError) as exc:
        raise AutoCheckpointError(
            f"could not write Auto checkpoint {path}: {exc}"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def read_auto_checkpoint(path: Path) -> dict[str, Any]:
    """Read and integrity-check a checkpoint envelope."""
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as stream:
            envelope = json.load(stream)
    except FileNotFoundError as exc:
        raise AutoCheckpointError(f"Auto checkpoint does not exist: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AutoCheckpointError(
            f"could not read Auto checkpoint {path}: {exc}"
        ) from exc

    if not isinstance(envelope, dict):
        raise AutoCheckpointError("Auto checkpoint root must be a JSON object")
    payload = envelope.get("payload")
    integrity = envelope.get("integrity_sha256")
    if not isinstance(payload, dict) or not isinstance(integrity, str):
        raise AutoCheckpointError("Auto checkpoint envelope is incomplete")
    if sha256_json(payload) != integrity:
        raise AutoCheckpointError(
            "Auto checkpoint integrity hash does not match its payload"
        )
    if payload.get("kind") != AUTO_CHECKPOINT_KIND:
        raise AutoCheckpointError("file is not an n v1.4 Auto campaign checkpoint")
    version = payload.get("format_version")
    if version != AUTO_CHECKPOINT_FORMAT_VERSION:
        raise AutoCheckpointError(
            "unsupported Auto checkpoint format version "
            f"{version!r}; expected {AUTO_CHECKPOINT_FORMAT_VERSION}"
        )
    return payload


__all__ = [
    "AUTO_CHECKPOINT_FORMAT_VERSION",
    "AUTO_CHECKPOINT_KIND",
    "OPTIMISER_VERSION",
    "AutoCheckpointError",
    "canonical_json_bytes",
    "optimiser_build_hash",
    "read_auto_checkpoint",
    "sha256_bytes",
    "sha256_json",
    "write_auto_checkpoint",
]
