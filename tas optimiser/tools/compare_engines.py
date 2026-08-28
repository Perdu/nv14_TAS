"""Lockstep verification of the Python reference and optional native engine.

The readable ``nv14_engine.py`` file is loaded directly under a private module
name, so an installed extension cannot accidentally become the reference side
of the comparison.  The native adapter is deliberately centralised here while
the native ABI is small: a level constructor, initial state, clone, four-boolean
step, and a state snapshot or state key.

Examples::

    python -m tools.compare_engines nv14_replay_verification_corpus_1489.yml
    python -m tools.compare_engines corpus.yml --clone-stride 64 --json

If the optional native extension is not installed, the command reports a clean
skip.  It never silently compares the Python implementation with itself.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import math
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from tools.verify_corpus import CorpusError, _load_yaml, _validate_document


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ENGINE_PATH = PROJECT_ROOT / "nv14_engine.py"
REFERENCE_MODULE_NAME = "_nv14_python_reference"
NATIVE_MODULE_NAMES = ("_nv14_native", "nv14_native")


class NativeBackendUnavailable(RuntimeError):
    """The optional native module is absent or does not expose its ABI."""


class NativeLevelUnsupported(NotImplementedError):
    """A level is deliberately outside the native core's capability set."""


class DifferentialError(AssertionError):
    """Python and native simulations diverged."""


@dataclass(frozen=True, slots=True)
class RawInput:
    left: bool
    right: bool
    jump: bool
    jump_trigger: bool


NEUTRAL_INPUT = RawInput(False, False, False, False)


@dataclass(frozen=True, slots=True)
class CaseComparison:
    case_id: str
    compared_ticks: int
    final_state_checksum: str
    completed: bool
    dead_on_completion: bool


@dataclass(frozen=True, slots=True)
class CorpusComparisonReport:
    corpus: str
    reference_module: str
    native_module: str
    native_backend_info: object
    corpus_levels: int
    corpus_cases: int
    native_supported_levels: int
    native_unsupported_levels: int
    native_supported_cases: int
    native_unsupported_cases: int
    native_supported_declared_input_ticks: int
    native_unsupported_declared_input_ticks: int
    compared_ticks: int
    clone_stride: int
    completion_tick_deaths: int
    elapsed_seconds: float
    ticks_per_second: float
    deterministic_checksum: str


@dataclass(frozen=True, slots=True)
class SkippedComparisonReport:
    corpus: str
    skipped: bool
    reason: str


def load_reference_engine(path: Path = REFERENCE_ENGINE_PATH) -> ModuleType:
    """Load the source reference even when ``nv14_engine`` is shadowed."""
    resolved = path.resolve()
    cached = sys.modules.get(REFERENCE_MODULE_NAME)
    if cached is not None:
        cached_path = Path(getattr(cached, "__file__", "")).resolve()
        if cached_path != resolved:
            raise RuntimeError(
                f"{REFERENCE_MODULE_NAME} already refers to {cached_path}, "
                f"not {resolved}"
            )
        return cached

    spec = importlib.util.spec_from_file_location(REFERENCE_MODULE_NAME, resolved)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load Python reference engine from {resolved}")
    module = importlib.util.module_from_spec(spec)
    # Dataclass and pickle machinery resolve the defining module while class
    # bodies execute, so it must already be visible here.
    sys.modules[REFERENCE_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(REFERENCE_MODULE_NAME, None)
        raise
    return module


def _native_module_has_api(module: ModuleType) -> bool:
    level_type = getattr(module, "NativeLevel", None)
    return bool(
        (
            level_type is not None
            and callable(getattr(level_type, "from_level_string", None))
        )
        or callable(getattr(module, "parse_level_string", None))
    )


def load_native_module() -> ModuleType:
    errors: list[str] = []
    for module_name in NATIVE_MODULE_NAMES:
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            errors.append(f"{module_name}: {exc}")
            continue
        if module_name == "nv14_native":
            require_native = getattr(module, "require_native", None)
            if not callable(require_native):
                errors.append("nv14_native: require_native is absent")
                continue
            try:
                module = require_native()
            except RuntimeError as exc:
                errors.append(f"nv14_native: {exc}")
                continue
        if _native_module_has_api(module):
            return module
        errors.append(
            f"{module_name}: neither NativeLevel.from_level_string nor "
            "parse_level_string is available"
        )
    details = "; ".join(errors) if errors else "no native module candidates"
    raise NativeBackendUnavailable(details)


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return repr(value)


def native_backend_info(module: ModuleType) -> object:
    info = getattr(module, "backend_info", None)
    if not callable(info):
        return {"module": module.__name__, "backend_info": "unavailable"}
    try:
        return _json_safe(info())
    except Exception as exc:
        return {
            "module": module.__name__,
            "backend_info_error": f"{type(exc).__name__}: {exc}",
        }


def decode_raw_replay(replay_string: str) -> tuple[RawInput, ...]:
    try:
        tick_text, words_text = replay_string.strip().split(":", 1)
        tick_count = int(tick_text)
        words = [int(word) for word in words_text.split("|") if word]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "complex replay must contain '<ticks>:<decimal packed words>'"
        ) from exc
    if tick_count < 0:
        raise ValueError("complex replay tick count must be non-negative")
    required_words = math.ceil(tick_count / 7)
    if len(words) < required_words:
        raise ValueError(
            f"replay declares {tick_count} ticks but has {len(words)} words; "
            f"{required_words} are required"
        )
    frames: list[RawInput] = []
    for frame_index in range(tick_count):
        nibble = (words[frame_index // 7] >> (4 * (frame_index % 7))) & 0xF
        frames.append(
            RawInput(
                left=bool(nibble & 0x1),
                right=bool(nibble & 0x2),
                jump=bool(nibble & 0x4),
                jump_trigger=bool(nibble & 0x8),
            )
        )
    return tuple(frames)


def _freeze(value: object) -> object:
    """Normalise native list/dict containers without changing scalar values."""
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, Mapping):
        return tuple(
            sorted((str(key), _freeze(item)) for key, item in value.items())
        )
    return value


def _first_difference(expected: object, observed: object, path: str = "state") -> str:
    if isinstance(expected, tuple) and isinstance(observed, tuple):
        if len(expected) != len(observed):
            return f"{path} length: Python {len(expected)}, native {len(observed)}"
        for index, (left, right) in enumerate(zip(expected, observed, strict=True)):
            if left != right:
                return _first_difference(left, right, f"{path}[{index}]")
    return f"{path}: Python {expected!r}, native {observed!r}"


def _reference_player_snapshot(player: object) -> dict[str, object]:
    return {
        "pos": (player.pos.x, player.pos.y),
        "oldpos": (player.oldpos.x, player.oldpos.y),
        "r": player.r,
        "xw": player.xw,
        "yw": player.yw,
        "maxspeed_air": player.maxspeed_air,
        "maxspeed_ground": player.maxspeed_ground,
        "ground_accel": player.ground_accel,
        "air_accel": player.air_accel,
        "norm_grav": player.norm_grav,
        "jump_grav": player.jump_grav,
        "norm_drag": player.norm_drag,
        "win_drag": player.win_drag,
        "wall_friction": player.wall_friction,
        "skid_friction": player.skid_friction,
        "stand_friction": player.stand_friction,
        "jump_amt": player.jump_amt,
        "jump_y_bias": player.jump_y_bias,
        "max_jump_time": player.max_jump_time,
        "terminal_vel": player.terminal_vel,
        "g": player.g,
        "d": player.d,
        "state": int(player.state),
        "jump_timer": player.jump_timer,
        "was_in_air": player.was_in_air,
        "in_air": player.in_air,
        "near_wall": player.near_wall,
        "dead": player.dead,
        "wall_n": (player.wall_n.x, player.wall_n.y),
        "floor_n": (player.floor_n.x, player.floor_n.y),
        "floor_n0": (player.floor_n0.x, player.floor_n0.y),
        "floor_n1": (player.floor_n1.x, player.floor_n1.y),
        "old_v": (player.old_v.x, player.old_v.y),
        "floor_count": player.floor_count,
        "previous_jump_held": player.previous_jump_held,
        "celeb_was_in_air": player.celeb_was_in_air,
        "jump_events": player.jump_events,
        "cell_i": player.cell_i,
        "cell_j": player.cell_j,
    }


def _reference_static_snapshot(static: object) -> dict[str, object]:
    return {
        "collected_gold_mask": static.collected_gold_mask,
        "exploded_mine_mask": static.exploded_mine_mask,
        "open_exit_mask": static.open_exit_mask,
        "level_complete": static.level_complete,
        "gold_bonus_ticks": static.gold_bonus_ticks,
        "completed_exit_index": static.completed_exit_index,
    }


def _reference_extra_snapshot(state: object) -> dict[str, object]:
    player = state.player
    return {
        "frame": state.frame,
        "state_key": state.state_key(),
        "player": _reference_player_snapshot(player),
        "static_state": _reference_static_snapshot(state.static_state),
        "level_complete": state.level_complete,
        "player_dead": player.dead,
        "jump_events": player.jump_events,
        # These transient player values are intentionally absent from the
        # optimiser's state_key(), but comparing them catches arithmetic/order
        # drift before it can affect a later collision or stale-normal exploit.
        "player_wall_n": (player.wall_n.x, player.wall_n.y),
        "player_was_in_air": player.was_in_air,
        "player_floor_n0": (player.floor_n0.x, player.floor_n0.y),
        "player_floor_n1": (player.floor_n1.x, player.floor_n1.y),
        "player_old_v": (player.old_v.x, player.old_v.y),
        "player_floor_count": player.floor_count,
    }


_SNAPSHOT_ALIASES = {
    "key": "state_key",
    "complete": "level_complete",
    "dead": "player_dead",
    "wall_n": "player_wall_n",
    "was_in_air": "player_was_in_air",
    "floor_n0": "player_floor_n0",
    "floor_n1": "player_floor_n1",
    "old_v": "player_old_v",
    "floor_count": "player_floor_count",
}


class NativeAdapter:
    """All assumptions about the deliberately narrow native ABI live here."""

    def __init__(self, module: ModuleType) -> None:
        if not _native_module_has_api(module):
            raise NativeBackendUnavailable(
                f"{module.__name__} has no native level parser"
            )
        self.module = module

    def parse_level(self, level_string: str, *, simulate_enemies: bool) -> object:
        level_type = getattr(self.module, "NativeLevel", None)
        constructor = (
            getattr(level_type, "from_level_string", None)
            if level_type is not None
            else None
        )
        if not callable(constructor):
            constructor = getattr(self.module, "parse_level_string")
        attempts = (
            lambda: constructor(
                level_string,
                strict_shapes=True,
                simulate_enemies=simulate_enemies,
            ),
            lambda: constructor(level_string, simulate_enemies=simulate_enemies),
            lambda: constructor(level_string, simulate_enemies),
        )
        errors: list[TypeError] = []
        for attempt in attempts:
            try:
                return attempt()
            except NotImplementedError as exc:
                raise NativeLevelUnsupported(str(exc)) from exc
            except TypeError as exc:
                errors.append(exc)
        raise NativeBackendUnavailable(
            "NativeLevel.from_level_string does not accept a supported signature: "
            + "; ".join(str(error) for error in errors)
        )

    @staticmethod
    def initial_state(level: object) -> object:
        method = getattr(level, "initial_state", None)
        if not callable(method):
            raise NativeBackendUnavailable("NativeLevel.initial_state is absent")
        return method()

    @staticmethod
    def clone(state: object) -> object:
        method = getattr(state, "clone", None)
        if not callable(method):
            raise NativeBackendUnavailable("NativeState.clone is absent")
        return method()

    @staticmethod
    def step(state: object, frame: RawInput) -> object:
        method = getattr(state, "step", None)
        if not callable(method):
            raise NativeBackendUnavailable("NativeState.step is absent")
        try:
            return method((frame.left, frame.right, frame.jump, frame.jump_trigger))
        except TypeError as sequence_error:
            try:
                return method(
                    frame.left,
                    frame.right,
                    frame.jump,
                    frame.jump_trigger,
                )
            except TypeError:
                raise NativeBackendUnavailable(
                    "NativeState.step accepts neither four booleans nor one "
                    "four-item input sequence"
                ) from sequence_error

    @staticmethod
    def _snapshot_mapping(state: object) -> Mapping[str, object] | None:
        method = getattr(state, "snapshot", None)
        if not callable(method):
            return None
        snapshot = method()
        if isinstance(snapshot, Mapping):
            return snapshot
        # A tuple/list snapshot is treated as the optimiser-compatible key.
        return {"state_key": snapshot}

    @classmethod
    def compare_state(
        cls,
        reference_state: object,
        native_state: object,
        *,
        case_id: str,
        tick: int,
    ) -> tuple:
        expected = _reference_extra_snapshot(reference_state)
        native_key_method = getattr(native_state, "state_key", None)
        compared_fields: set[str] = set()
        if callable(native_key_method):
            raw_native_key = native_key_method()
            # The narrow C core uses canonical bytes as its fast deduplication
            # key.  That representation is intentionally not the public
            # Python tuple, so full snapshot fields below are the cross-backend
            # oracle in that case.
            if not isinstance(raw_native_key, (bytes, bytearray, memoryview)):
                observed_key = _freeze(raw_native_key)
                expected_key = _freeze(expected["state_key"])
                if observed_key != expected_key:
                    detail = _first_difference(expected_key, observed_key)
                    raise DifferentialError(f"{case_id} tick {tick}: {detail}")
                compared_fields.add("state_key")

        snapshot = cls._snapshot_mapping(native_state)
        if snapshot is not None:
            for raw_name, observed in snapshot.items():
                name = _SNAPSHOT_ALIASES.get(str(raw_name), str(raw_name))
                if name not in expected:
                    continue
                if name == "static_state" and isinstance(observed, Mapping):
                    observed = dict(observed)
                    if observed.get("completed_exit_index") == -1:
                        observed["completed_exit_index"] = None
                expected_value = _freeze(expected[name])
                observed_value = _freeze(observed)
                if observed_value != expected_value:
                    detail = _first_difference(
                        expected_value,
                        observed_value,
                        f"state.{name}",
                    )
                    raise DifferentialError(f"{case_id} tick {tick}: {detail}")
                compared_fields.add(name)

        # Some wrappers expose cheap scalar properties instead of including
        # them in snapshot().  Compare them when present.
        for native_name, expected_name in (
            ("frame", "frame"),
            ("level_complete", "level_complete"),
            ("dead", "player_dead"),
            ("jump_events", "jump_events"),
        ):
            if hasattr(native_state, native_name):
                observed = getattr(native_state, native_name)
                if observed != expected[expected_name]:
                    raise DifferentialError(
                        f"{case_id} tick {tick}: state.{expected_name}: "
                        f"Python {expected[expected_name]!r}, native {observed!r}"
                    )
                compared_fields.add(expected_name)

        complete_snapshot = {
            "frame",
            "player",
            "static_state",
        }.issubset(compared_fields)
        if "state_key" not in compared_fields and not complete_snapshot:
            raise NativeBackendUnavailable(
                "NativeState must expose a Python-compatible state_key() or a "
                "snapshot containing frame, full player, and static_state"
            )
        return expected["state_key"]


class DifferentialHarness:
    def __init__(
        self,
        *,
        reference_module: ModuleType | None = None,
        native_module: ModuleType | None = None,
        simulate_enemies: bool = True,
    ) -> None:
        self.reference = reference_module or load_reference_engine()
        self.native = NativeAdapter(native_module or load_native_module())
        self.simulate_enemies = simulate_enemies
        self._reference_levels: dict[str, object] = {}
        self._native_levels: dict[str, object] = {}
        self._unsupported_levels: dict[str, str] = {}

    def _levels(self, level_id: str, level_string: str) -> tuple[object, object]:
        if level_id in self._unsupported_levels:
            raise NativeLevelUnsupported(self._unsupported_levels[level_id])
        if level_id not in self._reference_levels:
            self._reference_levels[level_id] = self.reference.parse_level_string(
                level_string,
                strict_shapes=True,
                simulate_enemies=self.simulate_enemies,
            )
            try:
                self._native_levels[level_id] = self.native.parse_level(
                    level_string,
                    simulate_enemies=self.simulate_enemies,
                )
            except NativeLevelUnsupported as exc:
                self._unsupported_levels[level_id] = str(exc)
                raise
        return self._reference_levels[level_id], self._native_levels[level_id]

    def compare_replay(
        self,
        *,
        case_id: str,
        level_id: str,
        level_string: str,
        replay_string: str,
        clone_stride: int = 0,
    ) -> CaseComparison:
        if clone_stride < 0:
            raise ValueError("clone_stride must be non-negative")
        reference_level, native_level = self._levels(level_id, level_string)
        reference_state = reference_level.initial_state()
        native_state = self.native.initial_state(native_level)
        frames = decode_raw_replay(replay_string) + (NEUTRAL_INPUT,)
        final_key: tuple | None = None
        for tick, frame in enumerate(frames):
            reference_input = self.reference.InputFrame(
                frame.left,
                frame.right,
                frame.jump,
                frame.jump_trigger,
            )
            try:
                reference_state.step(reference_input, reference_level.tiles)
            except Exception as exc:
                raise DifferentialError(
                    f"{case_id} tick {tick}: Python raised "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            try:
                self.native.step(native_state, frame)
            except Exception as exc:
                raise DifferentialError(
                    f"{case_id} tick {tick}: native raised "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            final_key = self.native.compare_state(
                reference_state,
                native_state,
                case_id=case_id,
                tick=tick,
            )
            if tick < len(frames) - 1:
                if reference_state.level_complete:
                    raise DifferentialError(
                        f"{case_id} tick {tick}: both backends complete before "
                        "the implicit neutral sentinel"
                    )
                if reference_state.player.dead:
                    raise DifferentialError(
                        f"{case_id} tick {tick}: both backends kill the player "
                        "before completion"
                    )
            if clone_stride and (tick + 1) % clone_stride == 0:
                reference_state = reference_state.clone()
                native_state = self.native.clone(native_state)
                final_key = self.native.compare_state(
                    reference_state,
                    native_state,
                    case_id=case_id,
                    tick=tick,
                )

        assert final_key is not None
        checksum = hashlib.sha256(repr(final_key).encode("utf-8")).hexdigest()
        return CaseComparison(
            case_id=case_id,
            compared_ticks=len(frames),
            final_state_checksum=checksum,
            completed=reference_state.level_complete,
            dead_on_completion=(
                reference_state.level_complete and reference_state.player.dead
            ),
        )


def compare_corpus(
    path: Path | str,
    *,
    max_cases: int | None = None,
    clone_stride: int = 0,
    progress_every: int = 100,
    progress_stream: object | None = None,
    reference_module: ModuleType | None = None,
    native_module: ModuleType | None = None,
) -> CorpusComparisonReport:
    if max_cases is not None and max_cases < 1:
        raise ValueError("max_cases must be positive when supplied")
    if progress_every < 0:
        raise ValueError("progress_every must be non-negative")
    corpus_path = Path(path)
    document, _yaml_seconds = _load_yaml(corpus_path)
    corpus = _validate_document(document)
    cases = corpus.cases[:max_cases]
    harness = DifferentialHarness(
        reference_module=reference_module,
        native_module=native_module,
        simulate_enemies=True,
    )
    digest = hashlib.sha256()
    compared_ticks = 0
    completion_tick_deaths = 0
    supported_levels: set[str] = set()
    unsupported_levels: set[str] = set()
    supported_cases = 0
    unsupported_cases = 0
    supported_declared_input_ticks = 0
    unsupported_declared_input_ticks = 0
    started = time.perf_counter()
    stream = progress_stream if progress_stream is not None else sys.stderr
    for index, case in enumerate(cases, start=1):
        try:
            result = harness.compare_replay(
                case_id=case.case_id,
                level_id=case.level_ref,
                level_string=corpus.levels[case.level_ref],
                replay_string=case.replay,
                clone_stride=clone_stride,
            )
        except NativeLevelUnsupported:
            unsupported_levels.add(case.level_ref)
            unsupported_cases += 1
            unsupported_declared_input_ticks += case.ticks
        else:
            if not result.completed:
                raise DifferentialError(
                    f"{case.case_id}: both backends agree but do not complete"
                )
            supported_levels.add(case.level_ref)
            supported_cases += 1
            supported_declared_input_ticks += case.ticks
            compared_ticks += result.compared_ticks
            completion_tick_deaths += int(result.dead_on_completion)
            digest.update(case.case_id.encode("utf-8"))
            digest.update(b"\0")
            digest.update(result.final_state_checksum.encode("ascii"))
        if progress_every and index % progress_every == 0:
            print(
                f"Compared {index:,}/{len(cases):,} cases "
                f"({compared_ticks:,} ticks)...",
                file=stream,
                flush=True,
            )
    elapsed = time.perf_counter() - started
    return CorpusComparisonReport(
        corpus=str(corpus_path),
        reference_module=str(Path(harness.reference.__file__).resolve()),
        native_module=harness.native.module.__name__,
        native_backend_info=native_backend_info(harness.native.module),
        corpus_levels=len({case.level_ref for case in cases}),
        corpus_cases=len(cases),
        native_supported_levels=len(supported_levels),
        native_unsupported_levels=len(unsupported_levels),
        native_supported_cases=supported_cases,
        native_unsupported_cases=unsupported_cases,
        native_supported_declared_input_ticks=supported_declared_input_ticks,
        native_unsupported_declared_input_ticks=unsupported_declared_input_ticks,
        compared_ticks=compared_ticks,
        clone_stride=clone_stride,
        completion_tick_deaths=completion_tick_deaths,
        elapsed_seconds=elapsed,
        ticks_per_second=compared_ticks / elapsed if elapsed else 0.0,
        deterministic_checksum=digest.hexdigest(),
    )


def _positive_integer(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _nonnegative_integer(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if value < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the Python reference and optional native nv14 engines "
            "after every corpus tick"
        )
    )
    parser.add_argument("corpus", type=Path, help="schema-v1 YAML corpus")
    parser.add_argument(
        "--max-cases",
        type=_positive_integer,
        help="compare only the first N cases (useful for a quick smoke test)",
    )
    parser.add_argument(
        "--clone-stride",
        type=_nonnegative_integer,
        default=0,
        help="replace both live states with clones every N ticks (default: 0/off)",
    )
    parser.add_argument(
        "--progress-every",
        type=_nonnegative_integer,
        default=100,
        help="write progress after every N cases; 0 disables it (default: 100)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a machine-readable JSON report",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = compare_corpus(
            args.corpus,
            max_cases=args.max_cases,
            clone_stride=args.clone_stride,
            progress_every=args.progress_every,
        )
    except NativeBackendUnavailable as exc:
        skipped = SkippedComparisonReport(
            corpus=str(args.corpus),
            skipped=True,
            reason=f"native backend unavailable: {exc}",
        )
        if args.json:
            print(json.dumps(asdict(skipped), indent=2, sort_keys=True))
        else:
            print(f"Skipped native differential verification: {skipped.reason}")
        return 0
    except (CorpusError, DifferentialError, OSError, ValueError) as exc:
        print(f"native differential verification failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    else:
        print(
            f"Python/native lockstep passed for "
            f"{report.native_supported_cases:,}/{report.corpus_cases:,} cases "
            f"({report.native_supported_levels:,}/{report.corpus_levels:,} "
            f"levels) and "
            f"{report.compared_ticks:,} ticks in {report.elapsed_seconds:.3f} s "
            f"({report.ticks_per_second:,.0f} ticks/s)."
        )
        if report.native_unsupported_cases:
            print(
                f"Native capability exclusions: "
                f"{report.native_unsupported_levels:,} levels, "
                f"{report.native_unsupported_cases:,} cases, "
                f"{report.native_unsupported_declared_input_ticks:,} declared "
                "ticks (not timed as native work)."
            )
        print(
            f"Native backend: {report.native_module}; "
            f"completion-tick deaths: {report.completion_tick_deaths}; "
            f"checksum: {report.deterministic_checksum}."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
