"""Validate and execute the schema-v1 n v1.4 replay verification corpus.

The corpus contract is intentionally stricter than a general replay check:
every declared replay input must run without completing the level, then one
implicit neutral input must complete it.  Stored ``jump_trigger`` bits are
part of the source replay and are therefore passed to the engine unchanged.

Run from the project root with, for example::

    python -m tools.verify_corpus nv14_replay_verification_corpus_1489.yml
    python -m tools.verify_corpus nv14_replay_verification_corpus_1489.yml --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from nv14_engine import InputFrame, Level, UnsupportedTileCollision, parse_level_string
from nv14_replay import decode_complex_replay


SCHEMA_VERSION = 1
NEUTRAL_INPUT = InputFrame(False, False, False, None)


class CorpusError(ValueError):
    """A malformed corpus or a replay-contract failure."""


@dataclass(frozen=True, slots=True)
class ValidatedCase:
    case_id: str
    level_ref: str
    ticks: int
    replay: str


@dataclass(frozen=True, slots=True)
class ValidatedCorpus:
    name: str
    reference_engine: str
    levels: dict[str, str]
    cases: tuple[ValidatedCase, ...]
    declared_input_ticks: int


@dataclass(frozen=True, slots=True)
class VerificationReport:
    corpus: str
    name: str
    schema_version: int
    reference_engine: str
    enemy_simulation: bool
    raw_jump_triggers: bool
    levels: int
    cases: int
    declared_input_ticks: int
    simulated_ticks: int
    stored_jump_triggers: int
    noncanonical_jump_trigger_frames: int
    completion_tick_deaths: int
    yaml_load_seconds: float
    validation_seconds: float
    level_parse_seconds: float
    replay_decode_seconds: float
    simulation_seconds: float
    total_seconds: float
    cases_per_second: float
    ticks_per_second: float


def _load_yaml(path: Path) -> tuple[object, float]:
    try:
        import yaml
    except (ImportError, ModuleNotFoundError) as exc:
        raise CorpusError(
            "PyYAML is required to read verification corpus files; "
            "install it with 'python -m pip install PyYAML'"
        ) from exc

    started = time.perf_counter()
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CorpusError(f"could not read corpus {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise CorpusError(f"invalid YAML in {path}: {exc}") from exc
    return document, time.perf_counter() - started


def _mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CorpusError(f"{location} must be a mapping")
    return value


def _sequence(value: object, location: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise CorpusError(f"{location} must be a list")
    return value


def _string(row: Mapping[str, Any], key: str, location: str) -> str:
    value = row.get(key)
    if not isinstance(value, str):
        raise CorpusError(f"{location}.{key} must be a string")
    return value


def _integer(row: Mapping[str, Any], key: str, location: str) -> int:
    value = row.get(key)
    if type(value) is not int:
        raise CorpusError(f"{location}.{key} must be an integer")
    return value


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_count(
    counts: Mapping[str, Any], key: str, observed: object
) -> None:
    declared = counts.get(key)
    if declared != observed:
        raise CorpusError(
            f"counts.{key} is {declared!r}, but the corpus contains {observed!r}"
        )


def _validate_document(document: object) -> ValidatedCorpus:
    root = _mapping(document, "document root")
    schema_version = _integer(root, "schema_version", "document root")
    if schema_version != SCHEMA_VERSION:
        raise CorpusError(
            f"unsupported schema_version {schema_version}; expected {SCHEMA_VERSION}"
        )

    name = _string(root, "name", "document root")
    reference_engine = _string(root, "reference_engine", "document root")
    contract = _mapping(root.get("verification_contract"), "verification_contract")
    expected_contract: dict[str, object] = {
        "simulate_enemies": True,
        "execute_declared_replay_inputs": True,
        "require_level_incomplete_after_last_input": True,
        "then_execute_neutral_ticks": 1,
        "require_level_complete_after_first_neutral": True,
    }
    for key, expected in expected_contract.items():
        if contract.get(key) != expected:
            raise CorpusError(
                f"verification_contract.{key} must be {expected!r}, "
                f"got {contract.get(key)!r}"
            )
    neutral = _mapping(contract.get("neutral_input"), "verification_contract.neutral_input")
    for key in ("left", "right", "jump"):
        if neutral.get(key) is not False:
            raise CorpusError(
                f"verification_contract.neutral_input.{key} must be false"
            )

    level_rows = _sequence(root.get("levels"), "levels")
    case_rows = _sequence(root.get("cases"), "cases")
    counts = _mapping(root.get("counts"), "counts")

    levels: dict[str, str] = {}
    level_metadata: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    for index, raw_row in enumerate(level_rows):
        location = f"levels[{index}]"
        row = _mapping(raw_row, location)
        ref = _string(row, "ref", location)
        data = _string(row, "data", location)
        declared_hash = _string(row, "sha256", location)
        actual_hash = _sha256(data)
        if declared_hash != actual_hash:
            raise CorpusError(
                f"{location} ({ref}) SHA-256 mismatch: "
                f"declared {declared_hash}, observed {actual_hash}"
            )
        expected_ref = f"level_{actual_hash[:16]}"
        if ref != expected_ref:
            raise CorpusError(
                f"{location}.ref is {ref!r}, expected {expected_ref!r} from SHA-256"
            )
        if ref in levels:
            raise CorpusError(f"duplicate level ref {ref!r}")

        level_ids_raw = _sequence(row.get("level_ids"), f"{location}.level_ids")
        sources_raw = _sequence(row.get("sources"), f"{location}.sources")
        if not all(isinstance(value, str) for value in level_ids_raw):
            raise CorpusError(f"{location}.level_ids must contain only strings")
        if not all(isinstance(value, str) for value in sources_raw):
            raise CorpusError(f"{location}.sources must contain only strings")
        levels[ref] = data
        level_metadata[ref] = (
            frozenset(level_ids_raw),
            frozenset(sources_raw),
        )

    cases: list[ValidatedCase] = []
    case_ids: set[str] = set()
    source_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    replay_key_counts: Counter[str] = Counter()
    for index, raw_row in enumerate(case_rows):
        location = f"cases[{index}]"
        row = _mapping(raw_row, location)
        case_id = _string(row, "id", location)
        if case_id in case_ids:
            raise CorpusError(f"duplicate case id {case_id!r}")
        case_ids.add(case_id)

        level_ref = _string(row, "level_ref", location)
        level_id = _string(row, "level_id", location)
        source = _string(row, "source", location)
        category = _string(row, "category", location)
        replay_key = _string(row, "replay_key", location)
        ticks = _integer(row, "ticks", location)
        replay = _string(row, "replay", location)
        declared_hash = _string(row, "replay_sha256", location)
        if ticks < 0:
            raise CorpusError(f"{location}.ticks must be non-negative")
        if level_ref not in levels:
            raise CorpusError(
                f"{location} ({case_id}) references unknown level {level_ref!r}"
            )
        level_ids, level_sources = level_metadata[level_ref]
        if level_id not in level_ids:
            raise CorpusError(
                f"{location} ({case_id}) level_id {level_id!r} is not listed by "
                f"{level_ref}"
            )
        if source not in level_sources:
            raise CorpusError(
                f"{location} ({case_id}) source {source!r} is not listed by "
                f"{level_ref}"
            )

        actual_hash = _sha256(replay)
        if declared_hash != actual_hash:
            raise CorpusError(
                f"{location} ({case_id}) replay SHA-256 mismatch: "
                f"declared {declared_hash}, observed {actual_hash}"
            )
        tick_text, separator, words_text = replay.partition(":")
        if not separator or not tick_text.isdigit():
            raise CorpusError(
                f"{location} ({case_id}) replay must start with '<ticks>:'"
            )
        encoded_ticks = int(tick_text)
        if encoded_ticks != ticks:
            raise CorpusError(
                f"{location} ({case_id}) declares ticks={ticks}, but replay "
                f"prefix declares {encoded_ticks}"
            )
        packed_words = words_text.split("|") if words_text else []
        required_words = math.ceil(ticks / 7)
        if len(packed_words) < required_words:
            raise CorpusError(
                f"{location} ({case_id}) has {len(packed_words)} packed replay "
                f"words; {required_words} are required"
            )
        try:
            for word in packed_words:
                int(word)
        except ValueError as exc:
            raise CorpusError(
                f"{location} ({case_id}) contains a non-decimal packed replay word"
            ) from exc

        cases.append(ValidatedCase(case_id, level_ref, ticks, replay))
        source_counts[source] += 1
        category_counts[category] += 1
        replay_key_counts[replay_key] += 1

    _validate_count(counts, "cases", len(cases))
    _validate_count(counts, "unique_level_definitions", len(levels))
    _validate_count(counts, "sources", dict(source_counts))
    _validate_count(counts, "categories", dict(category_counts))
    _validate_count(counts, "replay_keys", dict(replay_key_counts))

    return ValidatedCorpus(
        name=name,
        reference_engine=reference_engine,
        levels=levels,
        cases=tuple(cases),
        declared_input_ticks=sum(case.ticks for case in cases),
    )


def _parse_levels(corpus: ValidatedCorpus) -> dict[str, Level]:
    parsed: dict[str, Level] = {}
    for ref, data in corpus.levels.items():
        try:
            parsed[ref] = parse_level_string(
                data,
                strict_shapes=True,
                simulate_enemies=True,
            )
        except Exception as exc:
            raise CorpusError(f"could not parse {ref}: {exc}") from exc
    return parsed


def _verify_case(
    case: ValidatedCase,
    level: Level,
) -> tuple[int, int, int, bool, float, float]:
    decode_started = time.perf_counter()
    try:
        replay = decode_complex_replay(case.replay)
    except (TypeError, ValueError) as exc:
        raise CorpusError(f"{case.case_id}: invalid replay: {exc}") from exc
    decode_seconds = time.perf_counter() - decode_started
    if replay.tick_count != case.ticks:
        raise CorpusError(
            f"{case.case_id}: decoded {replay.tick_count} inputs, "
            f"expected {case.ticks}"
        )

    stored_triggers = 0
    noncanonical_triggers = 0
    previous_jump = False
    for frame in replay.frames:
        stored = bool(frame.jump_trigger)
        derived = frame.jump and not previous_jump
        stored_triggers += int(stored)
        noncanonical_triggers += int(stored != derived)
        previous_jump = frame.jump

    state = level.initial_state()
    simulation_started = time.perf_counter()
    try:
        for tick, frame in enumerate(replay.frames):
            # Do not pass these frames through editable_frames(): the packed
            # trigger bit is part of the verification source of truth.
            state.step(frame, level.tiles)
            if state.level_complete:
                raise CorpusError(
                    f"{case.case_id}: completed at declared input {tick}; "
                    f"expected the level to remain incomplete through input "
                    f"{case.ticks - 1}"
                )
            if state.player.dead:
                raise CorpusError(
                    f"{case.case_id}: player died at declared input {tick}"
                )

        state.step(NEUTRAL_INPUT, level.tiles)
    except UnsupportedTileCollision as exc:
        raise CorpusError(
            f"{case.case_id}: unsupported tile collision at engine frame "
            f"{state.frame}: {exc}"
        ) from exc
    simulation_seconds = time.perf_counter() - simulation_started

    if not state.level_complete:
        status = "dead" if state.player.dead else "alive"
        raise CorpusError(
            f"{case.case_id}: did not complete on the first neutral input "
            f"after {case.ticks} declared inputs (player {status})"
        )
    return (
        case.ticks + 1,
        stored_triggers,
        noncanonical_triggers,
        state.player.dead,
        decode_seconds,
        simulation_seconds,
    )


def verify_corpus(path: Path | str) -> VerificationReport:
    corpus_path = Path(path)
    total_started = time.perf_counter()
    document, yaml_load_seconds = _load_yaml(corpus_path)

    validation_started = time.perf_counter()
    corpus = _validate_document(document)
    validation_seconds = time.perf_counter() - validation_started

    parse_started = time.perf_counter()
    levels = _parse_levels(corpus)
    level_parse_seconds = time.perf_counter() - parse_started

    simulated_ticks = 0
    stored_jump_triggers = 0
    noncanonical_jump_trigger_frames = 0
    completion_tick_deaths = 0
    replay_decode_seconds = 0.0
    simulation_seconds = 0.0
    for case in corpus.cases:
        (
            case_ticks,
            case_triggers,
            case_noncanonical,
            died_on_completion,
            case_decode_seconds,
            case_simulation_seconds,
        ) = _verify_case(case, levels[case.level_ref])
        simulated_ticks += case_ticks
        stored_jump_triggers += case_triggers
        noncanonical_jump_trigger_frames += case_noncanonical
        completion_tick_deaths += int(died_on_completion)
        replay_decode_seconds += case_decode_seconds
        simulation_seconds += case_simulation_seconds

    total_seconds = time.perf_counter() - total_started
    return VerificationReport(
        corpus=str(corpus_path),
        name=corpus.name,
        schema_version=SCHEMA_VERSION,
        reference_engine=corpus.reference_engine,
        enemy_simulation=True,
        raw_jump_triggers=True,
        levels=len(levels),
        cases=len(corpus.cases),
        declared_input_ticks=corpus.declared_input_ticks,
        simulated_ticks=simulated_ticks,
        stored_jump_triggers=stored_jump_triggers,
        noncanonical_jump_trigger_frames=noncanonical_jump_trigger_frames,
        completion_tick_deaths=completion_tick_deaths,
        yaml_load_seconds=yaml_load_seconds,
        validation_seconds=validation_seconds,
        level_parse_seconds=level_parse_seconds,
        replay_decode_seconds=replay_decode_seconds,
        simulation_seconds=simulation_seconds,
        total_seconds=total_seconds,
        cases_per_second=(
            len(corpus.cases) / simulation_seconds
            if simulation_seconds
            else float("inf")
        ),
        ticks_per_second=(
            simulated_ticks / simulation_seconds
            if simulation_seconds
            else float("inf")
        ),
    )


def _print_human(report: VerificationReport) -> None:
    print(
        f"Validated {report.levels:,} levels and {report.cases:,} replay cases "
        f"from {report.name}."
    )
    print(
        f"Verified all {report.cases:,} cases with enemy simulation enabled "
        f"and stored jump-trigger bits preserved."
    )
    print(
        f"Simulated {report.simulated_ticks:,} ticks in "
        f"{report.simulation_seconds:.3f} s "
        f"({report.ticks_per_second:,.0f} ticks/s, "
        f"{report.cases_per_second:,.1f} cases/s)."
    )
    print(
        f"Stored jump triggers: {report.stored_jump_triggers:,}; "
        f"noncanonical trigger frames: "
        f"{report.noncanonical_jump_trigger_frames:,}; "
        f"completion-tick deaths: {report.completion_tick_deaths:,}."
    )
    print(
        "Timing: "
        f"YAML {report.yaml_load_seconds:.3f} s, "
        f"validation {report.validation_seconds:.3f} s, "
        f"level parsing {report.level_parse_seconds:.3f} s, "
        f"replay decoding {report.replay_decode_seconds:.3f} s, "
        f"total {report.total_seconds:.3f} s."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and execute a schema-v1 n v1.4 replay verification corpus"
        )
    )
    parser.add_argument("corpus", type=Path, help="schema-v1 YAML corpus")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a machine-readable JSON report",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = verify_corpus(args.corpus)
    except CorpusError as exc:
        print(f"corpus verification failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
