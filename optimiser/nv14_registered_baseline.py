"""Persistent read-only replay used only for splice-gain comparisons.

The registered run is not a search seed and is never a best checkpoint.
A digest of the level record prevents silently comparing unrelated levels.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from collections.abc import Sequence

from nv14_engine import InputFrame
from nv14_replay import decode_complex_replay, editable_frames, encode_complex_replay


def registered_path(completed_output: Path) -> Path:
    return completed_output.with_name(completed_output.stem + '.registered.json')


def write_registered_run(path: Path, *, level_id: str, level_string: str,
                         branch: int, frames: Sequence[InputFrame]) -> None:
    """Atomically register a snapshot, never changing input or output movies."""
    if not frames:
        raise ValueError('cannot register an empty input replay')
    payload = {
        'version': 1, 'level_id': level_id,
        'level_sha256': hashlib.sha256(level_string.encode('utf-8')).hexdigest(),
        'source': 'inputs' if branch == 0 else f'inputs{branch}',
        'replay': encode_complex_replay(tuple(editable_frames(frames))),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tempname = tempfile.mkstemp(prefix='.' + path.name + '.',
                                             suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, separators=(',', ':'), sort_keys=True)
            stream.write('\n')
        os.replace(tempname, path)
    finally:
        if os.path.exists(tempname):
            os.unlink(tempname)


def load_registered_run(path: Path, *, level_id: str,
                        level_string: str) -> tuple[InputFrame, ...] | None:
    """Return the registered replay, or None only when no snapshot exists."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(payload, dict) or payload.get('version') != 1 or
                payload.get('level_id') != level_id or
                payload.get('level_sha256') != hashlib.sha256(
                    level_string.encode('utf-8')).hexdigest()):
            raise ValueError('registered run is for a different level or format')
        encoded = payload['replay']
        if not isinstance(encoded, str):
            raise ValueError('registered replay is not a string')
        frames = tuple(editable_frames(decode_complex_replay(encoded).frames))
        if not frames:
            raise ValueError('registered replay is empty')
        return frames
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f'cannot read registered comparison {path}: {exc}') from exc
