from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

import tools.verify_corpus as corpus_tool
from tools.benchmark_engine import run_benchmark


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _corpus_document(
    *,
    replay: str = "1:8",
    level_data: str | None = None,
) -> dict[str, object]:
    if level_data is None:
        # The first input overlaps and removes the exit switch.  The exit door
        # replaces it in the grid, so the first implicit neutral tick wins.
        level_data = "0" * (31 * 23) + "|5^100,100!11^100,100,100,100"
    level_hash = _sha256(level_data)
    level_ref = f"level_{level_hash[:16]}"
    return {
        "schema_version": 1,
        "name": "test corpus",
        "description": "one-case verifier fixture",
        "reference_engine": "test-oracle",
        "verification_contract": {
            "simulate_enemies": True,
            "execute_declared_replay_inputs": True,
            "require_level_incomplete_after_last_input": True,
            "then_execute_neutral_ticks": 1,
            "require_level_complete_after_first_neutral": True,
            "neutral_input": {"left": False, "right": False, "jump": False},
        },
        "counts": {
            "cases": 1,
            "unique_level_definitions": 1,
            "sources": {"test_collection": 1},
            "categories": {"Speedrun": 1},
            "replay_keys": {"demo": 1},
        },
        "excluded_invalid_source_records": [],
        "format_notes": [],
        "levels": [
            {
                "ref": level_ref,
                "sha256": level_hash,
                "level_ids": ["00-0"],
                "names": ["fixture"],
                "authors": ["tests"],
                "sources": ["test_collection"],
                "data": level_data,
            }
        ],
        "cases": [
            {
                "id": "test:00-0:Speedrun:demo",
                "source": "test_collection",
                "level_id": "00-0",
                "level_ref": level_ref,
                "category": "Speedrun",
                "replay_key": "demo",
                "declared_time": 1,
                "replay_authors": "tests",
                "replay_type": "tas",
                "timestamp": "",
                "ticks": 1,
                "replay_sha256": _sha256(replay),
                "replay": replay,
            }
        ],
    }


def _write_document(path: Path, document: dict[str, object]) -> Path:
    # JSON is valid YAML and keeps this fixture independent of PyYAML's dump
    # formatting while the verifier still exercises yaml.safe_load().
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_verify_corpus_runs_the_schema_v1_contract(tmp_path: Path) -> None:
    path = _write_document(tmp_path / "corpus.yml", _corpus_document())

    report = corpus_tool.verify_corpus(path)

    assert report.levels == 1
    assert report.cases == 1
    assert report.declared_input_ticks == 1
    assert report.simulated_ticks == 2
    assert report.enemy_simulation is True
    assert report.raw_jump_triggers is True
    assert report.stored_jump_triggers == 1
    assert report.noncanonical_jump_trigger_frames == 1
    assert report.completion_tick_deaths == 0


def test_verify_corpus_passes_stored_trigger_bits_to_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_document(tmp_path / "corpus.yml", _corpus_document())
    observed = []

    class FakePlayer:
        dead = False

    class FakeState:
        def __init__(self) -> None:
            self.player = FakePlayer()
            self.level_complete = False
            self.frame = 0

        def step(self, frame, _tiles) -> None:
            observed.append(frame)
            self.frame += 1
            if self.frame == 2:
                self.level_complete = True

    class FakeLevel:
        tiles = object()

        def initial_state(self) -> FakeState:
            return FakeState()

    monkeypatch.setattr(
        corpus_tool,
        "parse_level_string",
        lambda *_args, **_kwargs: FakeLevel(),
    )

    report = corpus_tool.verify_corpus(path)

    assert report.cases == 1
    assert len(observed) == 2
    assert observed[0].jump is False
    assert observed[0].jump_trigger is True
    assert (observed[1].left, observed[1].right, observed[1].jump) == (
        False,
        False,
        False,
    )


def test_validate_corpus_rejects_hash_ref_and_count_mismatches() -> None:
    bad_hash = _corpus_document()
    bad_hash["cases"][0]["replay_sha256"] = "0" * 64
    with pytest.raises(corpus_tool.CorpusError, match="replay SHA-256 mismatch"):
        corpus_tool._validate_document(bad_hash)

    bad_ref = _corpus_document()
    bad_ref["cases"][0]["level_ref"] = "level_missing"
    with pytest.raises(corpus_tool.CorpusError, match="unknown level"):
        corpus_tool._validate_document(bad_ref)

    bad_count = _corpus_document()
    bad_count["counts"]["cases"] = 2
    with pytest.raises(corpus_tool.CorpusError, match=r"counts\.cases"):
        corpus_tool._validate_document(bad_count)


def test_load_yaml_has_clear_missing_dependency_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "yaml", None)
    with pytest.raises(corpus_tool.CorpusError, match="PyYAML is required"):
        corpus_tool._load_yaml(tmp_path / "unused.yml")


def test_seven_replay_engine_benchmark_smoke() -> None:
    report = run_benchmark(evaluations_per_scenario=1, repetitions=1)

    assert len(report.scenarios) == 7
    assert report.evaluations_per_repetition == 7
    assert report.simulated_ticks_per_repetition == 2_753
    assert report.median_seconds > 0.0
    assert report.checksum > 0
