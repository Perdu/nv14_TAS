"""Command-line parsing, TOML configuration, dispatch, and output handling."""
from __future__ import annotations

import argparse
import math
import multiprocessing
import os
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from nv14_auto import (
    AUTO_OBJECTIVE_HIGHSCORE,
    AUTO_OBJECTIVE_SPEEDRUN,
    AUTO_OBJECTIVES,
    AUTO_REPAIR_SEARCH_ORDER_RANDOM,
    AUTO_REPAIR_SEARCH_ORDERS,
    GOLD_BONUS_TICKS,
    AutoCandidate,
    AutoConfig,
    AutoProgress,
    optimise_autonomous,
    pre_finish_exit_edge_distance,
    verify_trimmed_replay,
)
from nv14_auto_parallel import optimise_autonomous_campaign
from nv14_engine import InputFrame, Level, SimulationState, parse_level_string
from nv14_jump import (
    ImmutableJumpSpec,
    JumpSearchResult,
    apply_jump_pattern,
    optimise_jump_patterns,
)
from nv14_local import (
    LocalSearchRunResult,
    jump_press_frames,
    optimise_local_windows,
    successful_jump_frames,
)
from nv14_ltm import (
    LEVEL_ID_RE,
    LtmError,
    LtmMovie,
    discover_levels_file,
    find_level_record,
    validate_level_id,
)
from nv14_objectives import (
    AxisWindow,
    Evaluation,
    InteractionAvoidance,
    InteractionRequirement,
    TargetSelection,
    evaluate,
    format_interaction_avoidances,
    format_interaction_requirements,
    format_level_objects,
    merge_interaction_avoidances,
    merge_interaction_requirements,
    objective_function,
    parse_target_point,
    reference_interaction_requirements,
    resolve_interaction_avoidance,
    resolve_interaction_requirement,
    resolve_target_object,
    target_from_point,
)
from nv14_replay import (
    CombinedLevelReplay,
    ComplexReplay,
    RetimeMutation,
    apply_suffix_retime,
    changed_frame_indices,
    decode_complex_replay,
    editable_frames,
    encode_complex_replay,
    input_transition_frames,
    parse_combined_level_replay,
)
from nv14_search import evaluate_fixed_replay_native, player_snapshot_key


@dataclass(frozen=True, slots=True)
class CommonConfig:
    """Configuration shared by the three optimisation subcommands.

    This is the small, mode-independent part of the command configuration.
    The TOML loader still accepts the existing command-line spellings; this
    object is the typed representation used after parsing has finished.
    """

    input_path: Path
    output_path: Path | None
    replay_output_path: Path | None
    levels_file_path: Path | None = None
    level_id: str | None = None
    ltm_postroll: int | None = None
    retime: tuple[tuple[str | int, int], ...] = ()
    config_path: Path | None = None
    simulate_enemies: bool | None = None

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "CommonConfig":
        return cls(
            input_path=args.input,
            output_path=args.output,
            replay_output_path=args.replay_output,
            levels_file_path=args.levels_file,
            level_id=args.level_id,
            ltm_postroll=args.ltm_postroll,
            retime=tuple(args.retime),
            config_path=args.config,
            simulate_enemies=args.simulate_enemies,
        )


@dataclass(frozen=True, slots=True)
class _LoadedSource:
    """Format-neutral optimiser input plus optional LTM output template."""

    combined: CombinedLevelReplay
    ltm_movie: LtmMovie | None = None
    level_id: str | None = None
    level_record: str | None = None
    levels_file_path: Path | None = None


@dataclass(frozen=True, slots=True)
class LocalConfig:
    """Typed local-subcommand configuration.

    Fields deliberately use semantic names (``window_size`` and
    ``jump_start_mutation``) while ``from_namespace`` preserves the existing
    CLI destination names.  Level-dependent values such as the resolved
    interaction atoms and the concrete range are filled by the normal local
    setup after the source replay has been loaded.
    """

    target_frame: int | None = None
    frame_range: str | tuple[str, ...] | None = None
    objective: str = "max-x"
    target_object: str | None = None
    target_point: tuple[float, float] | None = None
    x_window: AxisWindow | None = None
    y_window: AxisWindow | None = None
    window_size: int = 4
    window_shape: str = "contiguous"
    window_span: int | None = None
    windows_per_pass: int | None = None
    local_inputs: str = "all"
    jump_start_mutation: int = 0
    jump_length_mutation: int = 0
    immutable_jumps: tuple[ImmutableJumpSpec, ...] = ()
    physics_prune: bool = False
    passes: int = 2
    window_order: str = "forward"
    restarts: int = 10
    seed: int | str | None = None
    minimum_improvement: float = 0.0
    require_interaction: tuple[str, ...] = ()
    require_reference_interactions: bool = False
    avoid_interaction: tuple[str, ...] = ()
    workers: int = 0
    python_resimulate: bool = False

    def __post_init__(self) -> None:
        if self.objective not in (
            "max-x",
            "min-x",
            "max-y",
            "min-y",
            "min-distance",
        ):
            raise ValueError(
                "local objective must be one of: max-x, min-x, max-y, "
                "min-y, min-distance"
            )
        if self.target_object is not None or self.target_point is not None:
            if self.objective != "min-distance":
                raise ValueError(
                    "target-object/target-point require objective=min-distance"
                )
            if (self.target_object is None) == (self.target_point is None):
                raise ValueError(
                    "objective=min-distance requires exactly one of "
                    "target-object or target-point"
                )
        if self.target_frame is not None and self.target_frame < 0:
            raise ValueError("target frame must be non-negative")
        if self.window_size < 1:
            raise ValueError("window size must be at least 1")
        if self.passes < 1:
            raise ValueError("passes must be at least 1")
        if self.window_shape not in ("contiguous", "sparse", "mixed"):
            raise ValueError(
                "window-shape must be contiguous, sparse, or mixed"
            )
        if self.window_shape == "contiguous" and self.window_span is not None:
            raise ValueError(
                "window-span is only available with sparse or mixed windows"
            )
        if self.window_shape == "contiguous" and self.windows_per_pass is not None:
            raise ValueError(
                "windows-per-pass is only available with sparse or mixed windows"
            )
        if self.window_span is not None and self.window_span < 1:
            raise ValueError("window span must be at least 1")
        if self.windows_per_pass is not None and self.windows_per_pass < 1:
            raise ValueError("windows per pass must be at least 1")
        if self.local_inputs not in ("all", "direction"):
            raise ValueError("local-inputs must be all or direction")
        if self.physics_prune and self.local_inputs != "direction":
            raise ValueError(
                "physics-prune requires local-inputs=direction"
            )
        if self.jump_start_mutation < 0 or self.jump_length_mutation < 0:
            raise ValueError(
                "jump-start-mutation and jump-length-mutation must be non-negative"
            )
        jump_mutation_enabled = (
            self.jump_start_mutation > 0 or self.jump_length_mutation > 0
        )
        if jump_mutation_enabled and self.local_inputs != "direction":
            raise ValueError(
                "jump mutation requires local-inputs=direction"
            )
        if jump_mutation_enabled and self.window_order not in (
            "random",
            "mixed",
        ):
            raise ValueError(
                "jump mutation requires window-order random or mixed"
            )
        if self.immutable_jumps and not jump_mutation_enabled:
            raise ValueError(
                "immutable-jumps requires jump-start-mutation or "
                "jump-length-mutation"
            )
        if self.window_order not in ("forward", "reverse", "random", "mixed"):
            raise ValueError(
                "window-order must be forward, reverse, random, or mixed"
            )
        if self.restarts < 1:
            raise ValueError("restarts must be at least 1")
        if self.workers < 0:
            raise ValueError("workers must be zero (auto) or a positive integer")

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "LocalConfig":
        return cls(
            target_frame=args.target_frame,
            frame_range=args.frame_range,
            objective=args.objective,
            target_object=args.target_object,
            target_point=args.target_point,
            x_window=args.x_window,
            y_window=args.y_window,
            window_size=args.window,
            window_shape=args.window_shape,
            window_span=args.window_span,
            windows_per_pass=args.windows_per_pass,
            local_inputs=args.local_inputs,
            jump_start_mutation=args.jump_start_mutation,
            jump_length_mutation=args.jump_length_mutation,
            immutable_jumps=tuple(args.immutable_jumps),
            physics_prune=args.physics_prune,
            passes=args.passes,
            window_order=args.window_order,
            restarts=args.restarts,
            seed=args.seed,
            minimum_improvement=args.minimum_improvement,
            require_interaction=tuple(args.require_interaction),
            require_reference_interactions=args.require_reference_interactions,
            avoid_interaction=tuple(args.avoid_interaction),
            workers=args.workers,
            python_resimulate=getattr(args, "python_resimulate", False),
        )


@dataclass(frozen=True, slots=True)
class JumpPatternConfig:
    """Typed jump-pattern-subcommand configuration."""

    target_frame: int | None = None
    frame_range: str | None = None
    objective: str = "max-x"
    target_object: str | None = None
    target_point: tuple[float, float] | None = None
    x_window: AxisWindow | None = None
    y_window: AxisWindow | None = None
    jumps: tuple[int, int] = (2, 3)
    jump_length: tuple[int, int | None] = (1, None)
    minimum_gap: int = 1
    top_results: int = 10
    fixed_jump_frames: tuple[int, ...] = ()
    workers: int = 0
    python_resimulate: bool = False

    def __post_init__(self) -> None:
        if self.objective not in (
            "max-x",
            "min-x",
            "max-y",
            "min-y",
            "min-distance",
        ):
            raise ValueError(
                "jump-pattern objective must be one of: max-x, min-x, max-y, "
                "min-y, min-distance"
            )
        if self.target_object is not None or self.target_point is not None:
            if self.objective != "min-distance":
                raise ValueError(
                    "target-object/target-point require objective=min-distance"
                )
            if (self.target_object is None) == (self.target_point is None):
                raise ValueError(
                    "objective=min-distance requires exactly one of "
                    "target-object or target-point"
                )
        if self.target_frame is not None and self.target_frame < 0:
            raise ValueError("target frame must be non-negative")
        if (
            len(self.jumps) != 2
            or self.jumps[0] < 1
            or self.jumps[1] < self.jumps[0]
        ):
            raise ValueError("jumps must satisfy 1 <= minimum <= maximum")
        length_min, length_max = self.jump_length
        if length_min < 1:
            raise ValueError("minimum jump hold length must be at least 1")
        if length_max is not None and length_max < length_min:
            raise ValueError("maximum jump hold length cannot be below the minimum")
        if self.minimum_gap < 1:
            raise ValueError("minimum gap must be at least 1 released frame")
        if self.top_results < 1:
            raise ValueError("top-results must be at least 1")
        if self.workers < 0:
            raise ValueError("workers must be zero (auto) or a positive integer")

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "JumpPatternConfig":
        return cls(
            target_frame=args.target_frame,
            frame_range=args.frame_range,
            objective=args.objective,
            target_object=args.target_object,
            target_point=args.target_point,
            x_window=args.x_window,
            y_window=args.y_window,
            jumps=tuple(args.jumps),
            jump_length=tuple(args.jump_length),
            minimum_gap=args.minimum_gap,
            top_results=args.top_results,
            fixed_jump_frames=tuple(args.fixed_jump_frames),
            workers=args.workers,
            python_resimulate=getattr(args, "python_resimulate", False),
        )


@dataclass(frozen=True, slots=True)
class ModeConfigs:
    """Typed mode settings produced from one parsed CLI/TOML namespace."""

    common: CommonConfig
    local: LocalConfig | None = None
    jump_pattern: JumpPatternConfig | None = None


def build_mode_configs(args: argparse.Namespace) -> ModeConfigs:
    """Convert parsed CLI/TOML values into typed mode configuration objects."""
    if args.mode == "local":
        return ModeConfigs(
            common=CommonConfig.from_namespace(args),
            local=LocalConfig.from_namespace(args),
        )
    if args.mode == "jump-pattern":
        return ModeConfigs(
            common=CommonConfig.from_namespace(args),
            jump_pattern=JumpPatternConfig.from_namespace(args),
        )
    return ModeConfigs(common=CommonConfig.from_namespace(args))


def parse_seed(text: str) -> int | str:
    """Parse an explicit RNG seed or the auto-mode ``random`` sentinel."""
    if text == "random":
        return text
    try:
        return int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "seed must be an integer or 'random'"
        ) from exc


def parse_ltm_level_id(text: str) -> str:
    """Parse a built-in N level identifier used for LTM input."""
    try:
        validate_level_id(text)
    except LtmError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return text


def parse_nonnegative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "value must be a non-negative integer"
        ) from exc
    if value < 0:
        raise argparse.ArgumentTypeError("value must be a non-negative integer")
    return value


def parse_positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "value must be a positive integer"
        ) from exc
    if value < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return value


def parse_retime_spec(text: str) -> tuple[str | int, int]:
    """Parse ``START:DELTA`` where START is a transition frame or ``whole``."""
    if ":" not in text:
        raise ValueError("retime must use START:DELTA, for example 120:-1 or whole:+2")
    start_text, delta_text = (part.strip() for part in text.split(":", 1))
    if not start_text or not delta_text:
        raise ValueError("retime must use START:DELTA, for example 120:-1 or whole:+2")
    if start_text.lower() == "whole":
        start: str | int = "whole"
    else:
        try:
            start = int(start_text)
        except ValueError as exc:
            raise ValueError("retime START must be a non-negative frame or 'whole'") from exc
        if start < 0:
            raise ValueError("retime START must be a non-negative frame or 'whole'")
    try:
        delta = int(delta_text)
    except ValueError as exc:
        raise ValueError("retime DELTA must be one of -3,-2,-1,+1,+2,+3") from exc
    if delta == 0 or abs(delta) > 3:
        raise ValueError("retime DELTA must be one of -3,-2,-1,+1,+2,+3")
    return start, delta

def _frame_range_texts(spec: str | Sequence[str]) -> tuple[str, ...]:
    """Return the non-empty comma/list-delimited intervals in one range spec."""
    values: Sequence[str] = (spec,) if isinstance(spec, str) else spec
    texts: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("range entries must be strings such as '90:105'")
        for text in value.split(","):
            text = text.strip()
            if not text:
                raise ValueError("range entries must not be empty")
            texts.append(text)
    if not texts:
        raise ValueError("at least one optimisation range is required")
    return tuple(texts)


def _parse_frame_range_text(text: str, *, target_frame: int) -> tuple[int, int]:
    """Parse one inclusive frame interval after list syntax is expanded."""
    if ":" not in text:
        value = int(text)
        if value < 0 or value > target_frame:
            raise ValueError(
                f"range frame must be between 0 and the target frame ({target_frame})"
            )
        return value, value
    start_text, end_text = text.split(":", 1)
    start = int(start_text) if start_text else 0
    end = int(end_text) if end_text else target_frame
    if start < 0 or end < start:
        raise ValueError("range must satisfy 0 <= start <= end")
    if end > target_frame:
        raise ValueError("the optimisation range cannot end after the target frame")
    return start, end


def parse_frame_ranges(
    spec: str | Sequence[str], *, target_frame: int
) -> tuple[tuple[int, int], ...]:
    """Parse, sort, and coalesce one or more inclusive frame intervals.

    TOML may supply a string array and the CLI may use a comma-delimited value.
    Overlapping or adjacent intervals are coalesced because they describe the
    same mutable frame set as their union.
    """
    parsed = sorted(
        _parse_frame_range_text(text, target_frame=target_frame)
        for text in _frame_range_texts(spec)
    )
    merged: list[tuple[int, int]] = []
    for start, end in parsed:
        if merged and start <= merged[-1][1] + 1:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


def parse_frame_range(
    spec: str | Sequence[str], *, target_frame: int
) -> tuple[int, int]:
    """Parse the legacy single-interval form used by Auto and jump-pattern."""
    ranges = parse_frame_ranges(spec, target_frame=target_frame)
    if len(ranges) != 1:
        raise ValueError(
            "multiple optimisation ranges are only supported by local mode"
        )
    return ranges[0]


def _paths_alias(first: Path, second: Path) -> bool:
    """Return whether two input/output paths resolve to the same file."""
    if first.resolve(strict=False) == second.resolve(strict=False):
        return True
    try:
        return first.exists() and second.exists() and os.path.samefile(first, second)
    except OSError:
        return False


def _validate_output_paths(
    input_path: Path,
    output_path: Path,
    replay_output_path: Path | None,
) -> None:
    labelled = [("input", input_path), ("output", output_path)]
    if replay_output_path is not None:
        labelled.append(("replay output", replay_output_path))
    for first_index, (first_label, first_path) in enumerate(labelled):
        for second_label, second_path in labelled[first_index + 1 :]:
            if _paths_alias(first_path, second_path):
                raise ValueError(
                    f"{first_label} and {second_label} must be different files: "
                    f"{first_path}"
                )


def _validate_levels_output_paths(
    levels_file_path: Path | None,
    output_path: Path,
    replay_output_path: Path | None,
) -> None:
    if levels_file_path is None:
        return
    for label, path in (
        ("output", output_path),
        ("replay output", replay_output_path),
    ):
        if path is not None and _paths_alias(levels_file_path, path):
            raise ValueError(
                f"levels file and {label} must be different files: {path}"
            )


def _atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 beside the destination, then atomically replace it.

    Windows can briefly deny a replace while an antivirus scanner, indexer, or
    another reader has the existing destination open without delete sharing.
    Keep the completed temporary file and retry only those Windows sharing /
    access-denied failures; all other errors still fail immediately.
    """
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        retry_delays = (0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.0)
        for retry_delay in (*retry_delays, None):
            try:
                os.replace(temporary_path, path)
                break
            except OSError as exc:
                retryable_windows_error = getattr(exc, "winerror", None) in {
                    5,   # ERROR_ACCESS_DENIED
                    32,  # ERROR_SHARING_VIOLATION
                    33,  # ERROR_LOCK_VIOLATION
                }
                if not retryable_windows_error or retry_delay is None:
                    raise
                time.sleep(retry_delay)
    except BaseException:
        try:
            temporary_path.unlink()
        except OSError:
            # Preserve the original write/replace exception. A scanner can
            # transiently hold the temporary file too; a stale dotfile is less
            # harmful than hiding the actual output failure.
            pass
        raise


def _load_source(
    input_path: Path,
    *,
    levels_file_path: Path | None,
    explicit_level_id: str | None,
    ltm_postroll: int | None,
) -> _LoadedSource:
    """Load either the established combined text format or a libTAS movie."""
    if input_path.suffix.lower() != ".ltm":
        if (
            levels_file_path is not None
            or explicit_level_id is not None
            or ltm_postroll is not None
        ):
            raise LtmError(
                "--levels-file, --level-id and --ltm-postroll are only valid "
                "with an .ltm input"
            )
        try:
            text = input_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise LtmError(f"could not read input file {input_path}: {exc}") from exc
        try:
            combined = parse_combined_level_replay(text)
        except (TypeError, ValueError) as exc:
            raise LtmError(f"could not parse input file {input_path}: {exc}") from exc
        return _LoadedSource(combined=combined)

    movie = LtmMovie.load(input_path, postroll_frames=ltm_postroll)
    if explicit_level_id is not None:
        validate_level_id(explicit_level_id)
        if (
            movie.embedded_level_id is not None
            and movie.embedded_level_id != explicit_level_id
        ):
            raise LtmError(
                f"--level-id {explicit_level_id!r} conflicts with the embedded "
                f"LTM level id {movie.embedded_level_id!r}"
            )
        level_id = explicit_level_id
    elif movie.embedded_level_id is not None:
        level_id = movie.embedded_level_id
    elif LEVEL_ID_RE.fullmatch(input_path.stem):
        level_id = input_path.stem
    else:
        raise LtmError(
            f"cannot infer an N level id from LTM filename {input_path.name!r}; "
            "pass --level-id (for example --level-id 00-0)"
        )

    if levels_file_path is None and movie.embedded_level_record is not None:
        level_record = movie.embedded_level_record
        resolved_levels_path = None
    else:
        levels_path = discover_levels_file(
            input_path,
            levels_file_path,
            program_root=Path(__file__).resolve().parent,
        )
        level_record = find_level_record(levels_path, level_id)
        resolved_levels_path = levels_path

    replay_string = encode_complex_replay(movie.replay_frames)
    try:
        combined = parse_combined_level_replay(level_record + replay_string + "#")
    except (TypeError, ValueError) as exc:
        raise LtmError(
            f"could not combine LTM replay with level {level_id}: {exc}"
        ) from exc
    return _LoadedSource(
        combined=combined,
        ltm_movie=movie,
        level_id=level_id,
        level_record=level_record,
        levels_file_path=resolved_levels_path,
    )


def _write_result(
    source: _LoadedSource,
    output_path: Path,
    replay_output_path: Path | None,
    replay_string: str,
) -> None:
    """Write one verified final/checkpoint result in the source format."""
    try:
        if source.ltm_movie is None:
            output_record = source.combined.replace_replay(replay_string)
            _atomic_write_text(output_path, output_record.dump() + "\n")
        else:
            assert source.level_id is not None
            assert source.level_record is not None
            frames = decode_complex_replay(replay_string).frames
            source.ltm_movie.write(
                output_path,
                frames,
                level_id=source.level_id,
                level_record=source.level_record,
            )
    except (LtmError, OSError) as exc:
        raise SystemExit(f"could not write output {output_path}: {exc}") from exc
    if replay_output_path is not None:
        try:
            _atomic_write_text(replay_output_path, replay_string + "\n")
        except OSError as exc:
            raise SystemExit(
                f"could not write replay output {replay_output_path}: {exc}"
            ) from exc


def _verify_packed_replay_for_output(
    level: Level,
    frames: Sequence[InputFrame],
    *,
    target_frame: int,
    objective: Callable[[SimulationState], float],
    expected_evaluation: Evaluation,
    x_window: AxisWindow | None,
    y_window: AxisWindow | None,
    required_interactions: Sequence[InteractionRequirement] = (),
    avoided_interactions: Sequence[InteractionAvoidance] = (),
    expected_missing_jump_frames: frozenset[int] = frozenset(),
    require_successful_jump_presses: bool = False,
    python_resimulate: bool = False,
) -> tuple[str, list[InputFrame], Evaluation]:
    """Canonicalise and verify a fixed-frame result before writing it.

    Local workers can evaluate from cached prefix states, while the file on disk
    contains a canonical packed replay. The normal path verifies it from frame
    zero in the independent native engine and matches the native winner's full
    exported player snapshot. ``python_resimulate`` selects the slower Python
    reference-emulator parity path for debugging.
    """
    if not expected_evaluation.feasible:
        raise ValueError("the in-memory result is infeasible")
    if expected_evaluation.missing_interactions:
        missing_text = format_interaction_requirements(
            tuple(expected_evaluation.missing_interactions)
        )
        raise ValueError(
            f"the in-memory result is missing required interaction(s): {missing_text}"
        )
    if expected_evaluation.violated_interactions:
        violated_text = format_interaction_avoidances(
            tuple(expected_evaluation.violated_interactions)
        )
        raise ValueError(
            "the in-memory result triggered forbidden interaction(s): "
            f"{violated_text}"
        )
    if expected_missing_jump_frames:
        missing_text = ", ".join(map(str, sorted(expected_missing_jump_frames)))
        raise ValueError(
            "the in-memory direction-only result missed required jump "
            f"press(es) at frame(s) {missing_text}"
        )

    replay_string = encode_complex_replay(frames)
    packed_frames = editable_frames(
        decode_complex_replay(replay_string).frames
    )
    source_bits = tuple(
        (frame.left, frame.right, frame.jump) for frame in frames
    )
    packed_bits = tuple(
        (frame.left, frame.right, frame.jump) for frame in packed_frames
    )
    if source_bits != packed_bits:
        raise ValueError("the packed replay changed its held-input stream")

    if python_resimulate:
        packed_evaluation = evaluate(
            level,
            packed_frames,
            target_frame,
            objective,
            x_window=x_window,
            y_window=y_window,
            required_interactions=required_interactions,
            avoided_interactions=avoided_interactions,
        )
    else:
        packed_evaluation = evaluate_fixed_replay_native(
            level,
            packed_frames,
            target_frame,
            objective,
            x_window=x_window,
            y_window=y_window,
        )
    if not packed_evaluation.feasible:
        raise ValueError("the packed replay failed clean frame-zero verification")
    if python_resimulate and packed_evaluation.missing_interactions:
        missing_text = format_interaction_requirements(
            tuple(packed_evaluation.missing_interactions)
        )
        raise ValueError(
            f"the packed replay lost required interaction(s): {missing_text}"
        )
    if python_resimulate and packed_evaluation.violated_interactions:
        violated_text = format_interaction_avoidances(
            tuple(packed_evaluation.violated_interactions)
        )
        raise ValueError(
            "the packed replay triggered forbidden interaction(s): "
            f"{violated_text}"
        )
    if python_resimulate and require_successful_jump_presses:
        packed_required_jumps = jump_press_frames(packed_frames, target_frame)
        packed_missing_jumps = packed_required_jumps - successful_jump_frames(
            level, packed_frames, target_frame
        )
        if packed_missing_jumps:
            missing_text = ", ".join(map(str, sorted(packed_missing_jumps)))
            raise ValueError(
                "the packed direction-only replay missed required jump "
                f"press(es) at frame(s) {missing_text}"
            )
    if python_resimulate:
        if (
            packed_evaluation.state.state_key()
            != expected_evaluation.state.state_key()
        ):
            raise ValueError(
                "the packed replay state did not match the Python-resimulated "
                "in-memory result"
            )
    elif player_snapshot_key(
        packed_evaluation.state.player
    ) != player_snapshot_key(expected_evaluation.state.player):
        raise ValueError(
            "the packed replay player did not match the in-memory native result"
        )
    if packed_evaluation.score != expected_evaluation.score:
        raise ValueError(
            "the packed replay score did not match the in-memory native result"
        )
    return replay_string, packed_frames, packed_evaluation


def _interrupt_message(arguments: Sequence[str] | None = None) -> str:
    """Return a mode-accurate top-level Ctrl+C shutdown message."""
    argv = sys.argv[1:] if arguments is None else arguments
    mode = next(
        (argument for argument in argv if argument in {"auto", "local", "jump-pattern"}),
        None,
    )
    prefix = f"[{mode}:interrupt]" if mode is not None else "[interrupt]"
    return f"\n{prefix} Ctrl+C received; shutting down cleanly"


def parse_axis_window(text: str) -> AxisWindow:
    """Parse an inclusive ``MIN:MAX`` coordinate interval.

    Either endpoint may be omitted, allowing forms such as ``:350`` or
    ``500:``. A single value is treated as an exact window for convenience.
    """
    if ":" not in text:
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("an exact coordinate window must be finite")
        return AxisWindow(value, value)

    minimum_text, maximum_text = text.split(":", 1)
    if not minimum_text and not maximum_text:
        raise ValueError("a coordinate window must include at least one endpoint")
    minimum = float(minimum_text) if minimum_text else float("-inf")
    maximum = float(maximum_text) if maximum_text else float("inf")
    if math.isnan(minimum) or math.isnan(maximum):
        raise ValueError("coordinate-window endpoints cannot be NaN")
    if minimum > maximum:
        raise ValueError("coordinate window must satisfy MIN <= MAX")
    return AxisWindow(minimum, maximum)


def parse_jump_count_range(text: str) -> tuple[int, int]:
    """Parse ``N`` or inclusive ``MIN:MAX`` successful-jump counts."""
    if ":" not in text:
        value = int(text)
        minimum = maximum = value
    else:
        minimum_text, maximum_text = text.split(":", 1)
        if not minimum_text or not maximum_text:
            raise ValueError("jump count range must include both endpoints")
        minimum = int(minimum_text)
        maximum = int(maximum_text)
    if minimum < 1 or maximum < minimum:
        raise ValueError("jump count range must satisfy 1 <= MIN <= MAX")
    return minimum, maximum


def parse_jump_length_range(text: str) -> tuple[int, int | None]:
    """Parse ``N`` or ``MIN:MAX`` hold lengths; an omitted MAX is unbounded."""
    if ":" not in text:
        value = int(text)
        minimum = maximum = value
    else:
        minimum_text, maximum_text = text.split(":", 1)
        if not minimum_text:
            raise ValueError("jump length range must include a minimum")
        minimum = int(minimum_text)
        maximum = int(maximum_text) if maximum_text else None
    if minimum < 1:
        raise ValueError("jump hold length must be at least 1 frame")
    if maximum is not None and maximum < minimum:
        raise ValueError("jump length range must satisfy MIN <= MAX")
    return minimum, maximum


def parse_worker_count(text: str) -> int:
    """Parse a positive process count or ``auto`` as zero."""
    if text.lower() == "auto":
        return 0
    try:
        workers = int(text)
    except ValueError as exc:
        raise ValueError("workers must be a positive integer or 'auto'") from exc
    if workers < 1:
        raise ValueError("workers must be a positive integer or 'auto'")
    return workers


def parse_frame_list(text: str) -> tuple[int, ...]:
    """Parse a comma-separated list of non-negative replay frame numbers."""
    parts = text.split(",")
    if not parts or any(not part.strip() for part in parts):
        raise ValueError("frame list must be comma-separated integers")
    frames = tuple(int(part.strip()) for part in parts)
    if any(frame < 0 for frame in frames):
        raise ValueError("frame numbers must be non-negative")
    if len(set(frames)) != len(frames):
        raise ValueError("frame list must not contain duplicates")
    return frames


def parse_immutable_jumps(text: str) -> tuple[ImmutableJumpSpec, ...]:
    """Parse ``FRAME[:start|length|both],...`` immutable jump specs."""
    parts = text.split(",")
    if not parts or any(not part.strip() for part in parts):
        raise ValueError(
            "immutable jumps must be comma-separated FRAME[:start|length|both] specs"
        )

    specs: list[ImmutableJumpSpec] = []
    seen_frames: set[int] = set()
    for raw_part in parts:
        part = raw_part.strip()
        fields = [field.strip() for field in part.split(":")]
        if len(fields) > 2 or not fields[0]:
            raise ValueError(
                "immutable jump specs must use FRAME[:start|length|both]"
            )
        try:
            frame = int(fields[0])
        except ValueError as exc:
            raise ValueError(
                "immutable jump frames must be non-negative integers"
            ) from exc
        if frame < 0:
            raise ValueError("immutable jump frames must be non-negative integers")
        if frame in seen_frames:
            raise ValueError("immutable jump frames must not contain duplicates")
        seen_frames.add(frame)

        mode = fields[1].lower() if len(fields) == 2 else "both"
        if mode == "start":
            specs.append(ImmutableJumpSpec(frame, True, False))
        elif mode == "length":
            specs.append(ImmutableJumpSpec(frame, False, True))
        elif mode == "both":
            specs.append(ImmutableJumpSpec(frame, True, True))
        else:
            raise ValueError(
                "immutable jump property must be start, length, or both"
            )
    return tuple(specs)


_CONFIG_TABLE_NAMES = frozenset(
    {"common", "auto", "local", "jump-pattern", "jump_pattern"}
)
_CONFIG_APPEND_DESTS = frozenset(
    {"retime", "auto_parents", "require_interaction", "avoid_interaction"}
)
_CONFIG_RESERVED_DESTS = frozenset({"config", "input", "mode"})


def _find_config_path(argv: Sequence[str]) -> Path | None:
    """Return the last --config path in an argument vector."""
    config_path: Path | None = None
    index = 0
    while index < len(argv):
        token = str(argv[index])
        if token == "--config":
            if index + 1 >= len(argv):
                raise SystemExit("argument --config: expected one argument")
            config_path = Path(str(argv[index + 1]))
            index += 2
            continue
        if token.startswith("--config="):
            value = token.partition("=")[2]
            if not value:
                raise SystemExit("argument --config: expected one argument")
            config_path = Path(value)
        index += 1
    return config_path


def _config_mode_section(
    data: Mapping[str, object], mode: str
) -> Mapping[str, object]:
    """Return the selected mode table, accepting jump_pattern as an alias."""
    section_name = "jump_pattern" if mode == "jump-pattern" else mode
    section = data.get(mode)
    alias_section = data.get(section_name)
    if section is not None and not isinstance(section, Mapping):
        raise ValueError(f"TOML [{mode}] section must be a table")
    if alias_section is not None and not isinstance(alias_section, Mapping):
        raise ValueError(f"TOML [{section_name}] section must be a table")
    if section is not None and alias_section is not None and section is not alias_section:
        raise ValueError(
            f"TOML configuration must not define both [{mode}] and "
            f"[{section_name}] sections"
        )
    selected = section if section is not None else alias_section
    return selected if isinstance(selected, Mapping) else {}


def _normalise_config_key(key: str) -> str:
    """Normalise a TOML key or CLI option spelling to an argparse spelling."""
    return key.strip().lstrip("-").replace("-", "_")


def _add_config_alias(
    aliases: dict[str, str],
    key: str,
    destination: str,
    *,
    overwrite: bool = False,
) -> None:
    key = _normalise_config_key(key)
    if not key:
        return
    if overwrite or key not in aliases:
        aliases[key] = destination


def _config_destination_maps(
    command_parser: argparse.ArgumentParser, mode: str
) -> tuple[dict[str, str], dict[str, str]]:
    """Build general and mode-section aliases from the argparse actions."""
    general: dict[str, str] = {}
    mode_specific: dict[str, str] = {}
    mode_prefix = f"{mode.replace('-', '_')}_"

    for action in command_parser._actions:
        destination = action.dest
        if destination in _CONFIG_RESERVED_DESTS or destination == "help":
            continue
        _add_config_alias(general, destination, destination)
        for option in action.option_strings:
            _add_config_alias(general, option, destination)

        if destination.startswith(mode_prefix):
            _add_config_alias(
                mode_specific,
                destination[len(mode_prefix) :],
                destination,
                overwrite=True,
            )
        for option in action.option_strings:
            option_key = _normalise_config_key(option)
            if option_key.startswith(mode_prefix):
                _add_config_alias(
                    mode_specific,
                    option_key[len(mode_prefix) :],
                    destination,
                    overwrite=True,
                )

    return general, mode_specific


def _format_config_value_for_type(
    action_type: Callable[[object], object] | None, value: object
) -> object:
    """Translate convenient TOML arrays into the CLI parser's string forms."""
    if not isinstance(value, (list, tuple)):
        return value

    if action_type is parse_target_point:
        if len(value) != 2:
            raise ValueError("target-point arrays must contain exactly two values")
        return ",".join(str(item) for item in value)
    if action_type is parse_axis_window:
        if len(value) == 1:
            return str(value[0])
        if len(value) == 2:
            return ":".join("" if item is None else str(item) for item in value)
        raise ValueError("axis-window arrays must contain one or two values")
    if action_type in (parse_jump_count_range, parse_jump_length_range):
        if len(value) == 1:
            return str(value[0])
        if len(value) == 2:
            return ":".join("" if item is None else str(item) for item in value)
        raise ValueError("jump range arrays must contain one or two values")
    if action_type in (parse_frame_list, parse_immutable_jumps):
        return ",".join(str(item) for item in value)
    raise ValueError("this TOML option does not accept an array")


def _coerce_config_value(
    action: argparse.Action, value: object, *, key: str, mode: str
) -> object:
    """Validate and convert one TOML value as if it came from the CLI."""
    if action.dest in _CONFIG_RESERVED_DESTS:
        if action.dest == "input":
            raise ValueError(
                "the input file remains positional and cannot be set in TOML"
            )
        raise ValueError(f"TOML key {key!r} is reserved for the command line")

    if action.dest == "frame_range" and isinstance(value, (list, tuple)):
        if mode != "local":
            raise ValueError(
                "multiple optimisation ranges are only supported by [local]"
            )
        if not value:
            raise ValueError(f"TOML key {key!r} must contain at least one range")
        ranges = tuple(value)
        if not all(isinstance(item, str) and item.strip() for item in ranges):
            raise ValueError(
                f"TOML key {key!r} range arrays must contain non-empty strings"
            )
        return ranges

    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        if not isinstance(value, bool):
            raise ValueError(f"TOML key {key!r} must be a boolean")
        if isinstance(action, argparse._StoreFalseAction):
            key_name = _normalise_config_key(key)
            option_names = {
                _normalise_config_key(option)
                for option in action.option_strings
            }
            mode_prefix = f"{mode.replace('-', '_')}_"
            option_names.update(
                option_name[len(mode_prefix) :]
                for option_name in tuple(option_names)
                if option_name.startswith(mode_prefix)
            )
            if key_name in option_names:
                return not value
        return value

    if action.dest in _CONFIG_APPEND_DESTS:
        values = value if isinstance(value, (list, tuple)) else [value]
        return [
            _coerce_config_scalar(action, item, key=key)
            for item in values
        ]
    return _coerce_config_scalar(action, value, key=key)


def _coerce_config_scalar(
    action: argparse.Action, value: object, *, key: str
) -> object:
    action_type = action.type
    value = _format_config_value_for_type(action_type, value)

    if action_type is None:
        if not isinstance(value, str):
            raise ValueError(f"TOML key {key!r} must be a string")
        converted = value
    elif action_type is Path:
        if not isinstance(value, str):
            raise ValueError(f"TOML key {key!r} must be a string path")
        converted = Path(value)
    elif action_type is str:
        if not isinstance(value, str):
            raise ValueError(f"TOML key {key!r} must be a string")
        converted = value
    else:
        try:
            converted = action_type(str(value))
        except (TypeError, ValueError, argparse.ArgumentTypeError) as exc:
            raise ValueError(
                f"invalid value for TOML key {key!r}: {value!r} ({exc})"
            ) from exc

    if action.choices is not None and converted not in action.choices:
        choices = ", ".join(map(str, action.choices))
        raise ValueError(
            f"invalid value for TOML key {key!r}: {converted!r}; "
            f"choose from {choices}"
        )
    return converted


def _load_config_defaults(
    config_path: Path,
    command_parser: argparse.ArgumentParser,
    mode: str,
) -> dict[str, object]:
    """Load and validate common plus selected-mode TOML defaults."""
    try:
        with config_path.open("rb") as stream:
            data = tomllib.load(stream)
    except FileNotFoundError as exc:
        raise ValueError(f"TOML configuration file not found: {config_path}") from exc
    except OSError as exc:
        raise ValueError(
            f"could not read TOML configuration file {config_path}: {exc}"
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"invalid TOML configuration file {config_path}: {exc}"
        ) from exc

    if not isinstance(data, Mapping):
        raise ValueError(f"TOML configuration root must be a table: {config_path}")

    for section_name, section in data.items():
        if isinstance(section, Mapping) and section_name not in _CONFIG_TABLE_NAMES:
            raise ValueError(
                f"unknown TOML section [{section_name}] in {config_path}; "
                "use [common], [auto], [local], or [jump-pattern]"
            )
        if section_name in _CONFIG_TABLE_NAMES and not isinstance(section, Mapping):
            raise ValueError(
                f"TOML [{section_name}] section must be a table"
            )

    common = data.get("common", {})
    if not isinstance(common, Mapping):
        raise ValueError(f"TOML [common] section must be a table: {config_path}")
    mode_values = _config_mode_section(data, mode)

    raw_values: list[tuple[str, object, bool]] = [
        (str(key), value, False)
        for key, value in data.items()
        if key not in _CONFIG_TABLE_NAMES
    ]
    raw_values.extend(
        (str(key), value, False) for key, value in common.items()
    )
    raw_values.extend(
        (str(key), value, True) for key, value in mode_values.items()
    )

    general_aliases, mode_aliases = _config_destination_maps(command_parser, mode)
    actions_by_destination = {
        action.dest: action
        for action in command_parser._actions
        if action.dest != "help"
    }
    defaults: dict[str, object] = {}
    for key, value, allow_mode_aliases in raw_values:
        normalised_key = _normalise_config_key(key)
        destination = (
            mode_aliases.get(normalised_key) if allow_mode_aliases else None
        ) or general_aliases.get(normalised_key)
        if destination is None:
            raise ValueError(
                f"unknown TOML option {key!r} for [{mode}] in {config_path}"
            )
        action = actions_by_destination[destination]
        defaults[destination] = _coerce_config_value(
            action, value, key=key, mode=mode
        )
    return defaults


class _ConfigArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that applies TOML defaults before parsing the CLI."""

    def parse_args(
        self,
        args: Sequence[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> argparse.Namespace:
        actual_args = list(sys.argv[1:] if args is None else args)
        config_path = _find_config_path(actual_args)
        command_parsers = getattr(self, "_command_parsers", {})
        mode = actual_args[0] if actual_args else None
        if config_path is None or mode not in command_parsers:
            return super().parse_args(actual_args, namespace)

        try:
            defaults = _load_config_defaults(
                config_path, command_parsers[mode], mode
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

        command_parser = command_parsers[mode]
        saved_action_defaults = [
            (action, action.default)
            for action in command_parser._actions
            if action.dest in defaults
        ]
        saved_parser_defaults = dict(command_parser._defaults)
        command_parser.set_defaults(**defaults)
        try:
            return super().parse_args(actual_args, namespace)
        finally:
            command_parser._defaults.clear()
            command_parser._defaults.update(saved_parser_defaults)
            for action, default in saved_action_defaults:
                action.default = default


def parse_arguments(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse CLI arguments, applying TOML defaults before explicit CLI values."""
    actual_argv = list(sys.argv[1:] if argv is None else argv)
    namespace = build_parser().parse_args(actual_argv)
    if namespace.mode != "local" and namespace.frame_range is not None:
        try:
            range_count = len(_frame_range_texts(namespace.frame_range))
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if range_count != 1:
            raise SystemExit(
                "multiple optimisation ranges are only supported by local mode"
            )
    # Keep the historical Namespace return type for callers that use the
    # parser directly, while also materialising the typed configuration layer
    # once for the executable path.
    try:
        namespace._mode_configs = build_mode_configs(namespace)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return namespace


def build_parser() -> argparse.ArgumentParser:
    parser = _ConfigArgumentParser(
        description=(
            "Optimise an n v1.4 complex replay. Choose the auto, local, or "
            "jump-pattern subcommand."
        )
    )
    subparsers = parser.add_subparsers(
        dest="mode",
        required=True,
        metavar="{auto,local,jump-pattern}",
        title="subcommands",
        description="select one optimisation strategy",
    )
    command_parsers = {
        "auto": subparsers.add_parser(
            "auto",
            help="autonomous whole-level speedrun/highscore search",
            description="Run autonomous whole-level speedrun/highscore search.",
        ),
        "local": subparsers.add_parser(
            "local",
            help="sliding-window local search",
            description=(
                "Run sliding-window local search using all-input or "
                "direction-only mutations."
            ),
        ),
        "jump-pattern": subparsers.add_parser(
            "jump-pattern",
            help="successful-jump pulse search",
            description="Run exhaustive successful-jump pulse search.",
        ),
    }
    setattr(parser, "_command_parsers", command_parsers)

    auto_modes = frozenset({"auto"})
    local_modes = frozenset({"local"})
    jump_pattern_modes = frozenset({"jump-pattern"})
    fixed_frame_modes = frozenset({"local", "jump-pattern"})
    auto_and_local_modes = frozenset({"auto", "local"})

    class _CommandArguments:
        """Define an option only on the subcommands where it is valid."""

        def __init__(self, targets):
            self._targets = (
                tuple(targets.items())
                if isinstance(targets, Mapping)
                else tuple(targets)
            )

        def add_argument(self, *args, modes=None, **kwargs):
            for mode, target in self._targets:
                if modes is not None and mode not in modes:
                    # Inapplicable actions must be absent, rather than merely
                    # hidden from help. Besides allowing wrong-mode CLI flags,
                    # hidden actions would also become accepted TOML aliases in
                    # _config_destination_maps() and then be silently ignored.
                    continue
                target.add_argument(*args, **kwargs)

        def add_mutually_exclusive_group(self, **kwargs):
            return _CommandArguments(
                (
                    mode,
                    target.add_mutually_exclusive_group(**kwargs),
                )
                for mode, target in self._targets
            )

    command = _CommandArguments(command_parsers)
    command.add_argument(
        "input",
        type=Path,
        help="combined custom-level/replay text file or libTAS .ltm movie",
    )
    command.add_argument(
        "--levels-file",
        type=Path,
        help=(
            "N level database used to resolve a raw .ltm input; optimiser-written "
            "LTMs embed the selected level record"
        ),
    )
    command.add_argument(
        "--level-id",
        type=parse_ltm_level_id,
        metavar="NN-N",
        help=(
            "level identifier for an .ltm whose filename is not exactly such as "
            "00-0; normally inferred or read from optimiser LTM metadata"
        ),
    )
    command.add_argument(
        "--ltm-postroll",
        type=parse_nonnegative_int,
        metavar="N",
        help=(
            "for a raw .ltm, treat exactly N frames at the end of the active "
            "input log as post-roll instead of inferring all trailing N-idle "
            "frames; use 0 to keep every post-Space frame in the replay"
        ),
    )
    command.add_argument(
        "--retime",
        type=parse_retime_spec,
        action="append",
        default=[],
        metavar="START:DELTA",
        help=(
            "pre-search replay retime; START must be an input-transition frame or "
            "'whole', DELTA is -3..-1 or +1..+3. Every transition from START "
            "onward moves together while replay length stays fixed. Repeatable; "
            "multiple specs are applied sequentially before the selected search mode"
        ),
    )
    command.add_argument(
        "--iterations",
        modes=auto_modes,
        type=int,
        default=5000,
        metavar="N",
        help=(
            "auto mode macro candidate evaluation budget per independent "
            "worker search and round (default: 5000)"
        ),
    )
    command.add_argument(
        "--auto-runs",
        modes=auto_modes,
        type=int,
        default=1,
        metavar="N",
        help=(
            "auto mode parallel rounds; every round restarts all workers from "
            "the best prior result; 0 repeats indefinitely until Ctrl+C "
            "(default: 1)"
        ),
    )
    command.add_argument(
        "--auto-parent",
        modes=auto_modes,
        dest="auto_parents",
        type=Path,
        action="append",
        default=[],
        metavar="FILE",
        help=(
            "additional completed replay used as a generation-0 Auto parent; "
            "must contain exactly the same level as positional INPUT. "
            "Repeatable"
        ),
    )
    command.add_argument(
        "--beam",
        modes=auto_modes,
        type=int,
        default=32,
        metavar="N",
        help="auto mode retained candidate population (default: 32)",
    )
    command.add_argument(
        "--max-retime",
        modes=auto_modes,
        type=int,
        default=3,
        metavar="N",
        help="auto mode maximum suffix shift in frames, from 1 to 3 (default: 3)",
    )
    command.add_argument(
        "--auto-objective",
        modes=auto_modes,
        choices=AUTO_OBJECTIVES,
        default=AUTO_OBJECTIVE_SPEEDRUN,
        help=(
            "auto mode objective: speedrun minimises raw completion tick; "
            "highscore maximises gold bonus ticks minus completion tick "
            "(default: speedrun)"
        ),
    )
    command.add_argument(
        "--auto-require-reference-gold",
        modes=auto_modes,
        action="store_true",
        help=(
            "highscore mode hard constraint requiring every gold collected by "
            "the verified source replay to remain collected"
        ),
    )
    command.add_argument(
        "--auto-max-extra-ticks",
        modes=auto_modes,
        type=int,
        metavar="N",
        help=(
            "highscore mode editable search time after the source finish; "
            f"defaults to up to {GOLD_BONUS_TICKS} (one gold's timer value, "
            "or zero when the source already has every gold); "
            "speedrun mode uses 0"
        ),
    )
    command.add_argument(
        "--auto-repair-window",
        "--auto-window",
        modes=auto_modes,
        dest="auto_repair_window",
        type=int,
        default=6,
        metavar="N",
        help="auto mode consecutive direction frames in a bounded repair (default: 6)",
    )
    command.add_argument(
        "--auto-repair-lookback",
        modes=auto_modes,
        type=int,
        default=192,
        metavar="N",
        help=(
            "auto mode maximum history considered by sparse direction and "
            "+/-1 jump-boundary repair (default: 192)"
        ),
    )
    command.add_argument(
        "--auto-lookahead",
        modes=auto_modes,
        type=int,
        default=3,
        metavar="N",
        help="auto mode repair scoring lookahead in frames (default: 3)",
    )
    command.add_argument(
        "--auto-max-alignment",
        "--auto-alignment",
        modes=auto_modes,
        dest="auto_max_alignment",
        type=int,
        default=3,
        metavar="N",
        help="auto mode maximum future reference offset searched (default: 3)",
    )
    command.add_argument(
        "--auto-no-deterministic",
        modes=auto_modes,
        dest="auto_deterministic",
        action="store_false",
        default=True,
        help=(
            "skip the structured retime/pulse/jump bootstrap and start directly "
            "with the stochastic beam"
        ),
    )
    command.add_argument(
        "--auto-repair-local-steps",
        modes=auto_modes,
        type=int,
        default=1_000,
        metavar="N",
        help=(
            "fresh local-simulation ceiling for every admitted repair; there "
            "is no global repair-count limit; jump lookback, direction search, "
            "and all-input fallback share this budget; 0 makes it unlimited "
            "(default: 1000)"
        ),
    )
    command.add_argument(
        "--auto-repair-search-order",
        modes=auto_modes,
        choices=AUTO_REPAIR_SEARCH_ORDERS,
        default=AUTO_REPAIR_SEARCH_ORDER_RANDOM,
        help=(
            "local repair traversal: random uses reproducible independent "
            "seeded branch orders; fixed restores the v2.12.5 branch order; "
            "the jump-vs-direction primary order is seed-derived in both modes "
            "(default: random)"
        ),
    )
    command.add_argument(
        "--auto-frame-ahead-repair-multiplier",
        modes=auto_modes,
        type=int,
        default=10,
        metavar="N",
        help=(
            "multiply both per-repair and per-campaign local-step allowances "
            "after a measured positive trajectory offset is seen in that repair "
            "campaign; 1 disables the bonus and a base allowance of 0 remains "
            "unlimited (default: 10)"
        ),
    )
    command.add_argument(
        "--auto-campaign-local-steps",
        modes=auto_modes,
        type=int,
        default=10_000,
        metavar="N",
        help=(
            "soft local-simulation ceiling per repair campaign, checked "
            "between attempts; frame-ahead campaigns multiply this by "
            "--auto-frame-ahead-repair-multiplier; 0 disables it "
            "(default: 10000)"
        ),
    )
    command.add_argument(
        "--auto-beam-repair-revisit-limit",
        modes=auto_modes,
        type=parse_positive_int,
        default=2,
        metavar="N",
        help=(
            "maximum visits to the same eight-frame failure region in one "
            "beam repair campaign before that campaign stops (default: 2)"
        ),
    )
    command.add_argument(
        "--auto-splice-repair-revisit-limit",
        modes=auto_modes,
        type=parse_positive_int,
        default=3,
        metavar="N",
        help=(
            "maximum visits to the same eight-frame failure region in one "
            "splice repair campaign before that campaign stops (default: 3)"
        ),
    )
    command.add_argument(
        "--auto-cheap-pulses",
        modes=auto_modes,
        type=int,
        default=96,
        metavar="N",
        help=(
            "auto mode budget for the deterministic one-frame horizontal "
            "pre-sweep (default: 96)"
        ),
    )
    command.add_argument(
        "--auto-position-tolerance",
        modes=auto_modes,
        type=float,
        default=3.0,
        metavar="D",
        help="auto mode trajectory-alignment position tolerance (default: 3)",
    )
    command.add_argument(
        "--auto-velocity-tolerance",
        modes=auto_modes,
        type=float,
        default=0.75,
        metavar="D",
        help="auto mode trajectory-alignment velocity tolerance (default: 0.75)",
    )
    command.add_argument(
        "--auto-match-tolerance",
        modes=auto_modes,
        type=float,
        metavar="D",
        help=(
            "compatibility form of the integrated v2.8 weighted tolerance; "
            "maps D to position sqrt(D) and velocity sqrt(D)/2"
        ),
    )
    command.add_argument(
        "--auto-postroll",
        modes=auto_modes,
        type=int,
        default=1,
        metavar="N",
        help=(
            "compatibility option; Auto requires exactly one neutral sentinel "
            "after the encoded replay (default: 1)"
        ),
    )
    command.add_argument(
        "--auto-no-all-input-repair",
        modes=auto_modes,
        dest="auto_all_input_repair",
        action="store_false",
        default=True,
        help="disable the third-stage bounded all-input repair fallback",
    )
    command.add_argument(
        "--target-frame", modes=fixed_frame_modes, type=int
    )
    command.add_argument(
        "--range",
        modes=local_modes,
        dest="frame_range",
        metavar="START:END[,START:END...]",
        help=(
            "one or more inclusive mutable ranges; delimit CLI intervals with "
            "commas or use a TOML string array (default: complete target range)"
        ),
    )
    command.add_argument(
        "--range",
        modes=auto_modes,
        dest="frame_range",
        metavar="START:END",
        help=(
            "inclusive mutation seam/start range; suffixes may alter later "
            "frames (default: complete verified replay)"
        ),
    )
    command.add_argument(
        "--range",
        modes=jump_pattern_modes,
        dest="frame_range",
        metavar="START:END",
        help="inclusive mutable jump-pattern range (default: complete target range)",
    )
    command.add_argument(
        "--objective",
        modes=fixed_frame_modes,
        choices=("max-x", "min-x", "max-y", "min-y", "min-distance"),
        default="max-x",
    )
    command.add_argument(
        "--target-object",
        modes=fixed_frame_modes,
        metavar="SELECTOR",
        help=(
            "min-distance target selector: TYPE, TYPE:INDEX, "
            "TYPE:INDEX.ANCHOR or TYPE:any; exits support .door/.switch"
        ),
    )
    command.add_argument(
        "--target-point",
        modes=fixed_frame_modes,
        type=parse_target_point,
        metavar="X,Y",
        help="min-distance target as an explicit point rather than a level object",
    )
    command.add_argument(
        "--list-objects",
        action="store_true",
        help=(
            "list stable target-object selectors and supported local required/"
            "forbidden interaction selectors in the level, then exit"
        ),
    )
    command.add_argument(
        "--require-interaction",
        modes=local_modes,
        action="append",
        default=[],
        metavar="SELECTOR",
        help=(
            "local mode hard route-state requirement; repeatable selectors support "
            "gold:INDEX, gold:any, switch:INDEX, switch:any, "
            "exit:INDEX.switch, locked testdoor:INDEX, and testdoor:any"
        ),
    )
    command.add_argument(
        "--require-reference-interactions",
        modes=local_modes,
        action="store_true",
        help=(
            "local mode: require every exact gold, exit switch, and locked-door "
            "switch interaction made by the post-retime reference replay through "
            "--target-frame"
        ),
    )
    command.add_argument(
        "--avoid-interaction",
        modes=local_modes,
        action="append",
        default=[],
        metavar="SELECTOR",
        help=(
            "local mode hard prohibition; repeatable selectors support gold:INDEX, "
            "gold:any, switch:INDEX, switch:any, exit:INDEX.switch, persistent "
            "testdoor:INDEX/testdoor:any, and trapdoor:TESTDOOR_INDEX/"
            "trapdoor:any; :any forbids every matching object"
        ),
    )
    command.add_argument(
        "--window",
        modes=local_modes,
        type=int,
        default=4,
        help=(
            "number of mutable frames searched together; consecutive by default, "
            "or selected sparsely on sparse/mixed passes"
        ),
    )
    command.add_argument(
        "--window-shape",
        modes=local_modes,
        choices=("contiguous", "sparse", "mixed"),
        default="contiguous",
        help=(
            "local mode frame-set shape: contiguous = ordinary consecutive "
            "windows; sparse = randomly select --window mutable frames while "
            "intervening replay frames stay fixed; mixed = alternate sparse then "
            "contiguous on successive passes (default: contiguous)"
        ),
    )
    command.add_argument(
        "--window-span",
        modes=local_modes,
        type=int,
        metavar="N",
        help=(
            "sparse and mixed shapes: maximum inclusive span containing the "
            "selected frames on sparse passes; must be at least --window "
            "(default: full mutable range)"
        ),
    )
    command.add_argument(
        "--windows-per-pass",
        modes=local_modes,
        type=int,
        metavar="N",
        help=(
            "sparse and mixed shapes: distinct random frame sets sampled on each "
            "sparse pass; defaults to the number of ordinary contiguous windows"
        ),
    )
    command.add_argument(
        "--local-inputs",
        modes=local_modes,
        choices=("all", "direction"),
        default="all",
        help=(
            "local mode input alphabet: all = L/N/R crossed with jump held/released "
            "using default inactive-jump DFS pruning; direction = vary only L/N/R and preserve "
            "the replay's jump-held sequence (default: all)"
        ),
    )
    command.add_argument(
        "--jump-start-mutation",
        modes=local_modes,
        type=int,
        default=0,
        metavar="X",
        help=(
            "direction-only local random/mixed search: independently mutate each "
            "complete in-range jump pulse start by an integer in [-X,+X] on every "
            "random restart; 0 is included (default: 0)"
        ),
    )
    command.add_argument(
        "--jump-length-mutation",
        modes=local_modes,
        type=int,
        default=0,
        metavar="Y",
        help=(
            "direction-only local random/mixed search: independently mutate each "
            "complete in-range jump hold length by an integer in [-Y,+Y] on every "
            "random restart; length remains >=1 and 0 is included (default: 0)"
        ),
    )
    command.add_argument(
        "--immutable-jumps",
        modes=local_modes,
        type=parse_immutable_jumps,
        default=(),
        metavar="F[:PROPERTY],...",
        help=(
            "direction-only local jump mutation: comma-separated source jump "
            "starts with optional :start, :length, or :both; bare frames default "
            "to :both (example: 42,73:start,105:length)"
        ),
    )
    command.add_argument(
        "--physics-prune",
        modes=local_modes,
        action="store_true",
        help=(
            "direction-only local mode: enable optional horizontal kinematic "
            "branch-and-bound; assumes no future object/collision-derived "
            "horizontal boosts"
        ),
    )
    command.add_argument("--passes", modes=local_modes, type=int, default=2)
    command.add_argument(
        "--window-order",
        modes=local_modes,
        choices=("forward", "reverse", "random", "mixed"),
        default="forward",
        help=(
            "local mode window traversal: forward/reverse order by temporal centre; "
            "random uses independent shuffled restarts; mixed compares one forward, "
            "one reverse and the requested random restarts (default: forward)"
        ),
    )
    command.add_argument(
        "--restarts",
        modes=local_modes,
        type=int,
        default=10,
        help=(
            "local random/mixed window order: number of independent randomized "
            "runs; direction-only jump mutation is re-sampled for every random "
            "restart (default: 10)"
        ),
    )
    command.add_argument(
        "--seed",
        modes=auto_and_local_modes,
        type=parse_seed,
        metavar="N|random",
        help=(
            "reproducible random seed for auto mode, local sparse/mixed sampling, "
            "random/mixed window order, direction-only jump mutation, and Auto's "
            "randomized local repair traversal; auto also accepts 'random' to "
            "choose and print a fresh 64-bit seed once per run, otherwise auto "
            "defaults to 0; local mode generates and prints one when needed"
        ),
    )
    command.add_argument(
        "--minimum-improvement",
        modes=local_modes,
        type=float,
        default=0.0,
    )
    command.add_argument(
        "--python-resimulate",
        modes=fixed_frame_modes,
        action="store_true",
        help=(
            "debugging only: re-simulate returned native Local or jump-pattern "
            "results with the Python reference emulator and require exact parity; "
            "disabled by default"
        ),
    )
    command.add_argument(
        "--jumps",
        modes=jump_pattern_modes,
        type=parse_jump_count_range,
        default=(2, 3),
        metavar="MIN:MAX",
        help=(
            "jump-pattern mode: successful Player.jump() count to search; "
            "a single integer requests exactly that many (default: 2:3)"
        ),
    )
    command.add_argument(
        "--jump-length",
        modes=jump_pattern_modes,
        type=parse_jump_length_range,
        default=(1, None),
        metavar="MIN:MAX",
        help=(
            "jump-pattern mode: inclusive held-jump length range in frames; "
            "omit MAX for the longest pulse that fits (default: 1:)"
        ),
    )
    command.add_argument(
        "--minimum-gap",
        modes=jump_pattern_modes,
        type=int,
        default=1,
        help=(
            "jump-pattern mode: minimum released frames between pulses "
            "(default: 1)"
        ),
    )
    command.add_argument(
        "--top-results",
        modes=jump_pattern_modes,
        type=int,
        default=10,
        help="jump-pattern mode: number of ranked feasible patterns to retain",
    )
    command.add_argument(
        "--workers",
        type=parse_worker_count,
        default=0,
        metavar="N|auto",
        help=(
            "mode-aware parallelism: auto and local use worker processes for "
            "independent searches or trajectories; jump-pattern uses native C "
            "shards in worker threads; auto selects up to 8 available CPUs "
            "and 1 always forces serial (default: auto)"
        ),
    )
    command.add_argument(
        "--fixed-jump-frames",
        modes=jump_pattern_modes,
        type=parse_frame_list,
        default=(),
        metavar="F1,F2,...",
        help=(
            "jump-pattern mode: comma-separated source replay jump-start frames "
            "whose start timing is fixed while hold length remains searchable"
        ),
    )
    command.add_argument(
        "--x-window",
        modes=fixed_frame_modes,
        type=parse_axis_window,
        metavar="MIN:MAX",
        help=(
            "inclusive permitted x range at the target frame; normally used "
            "with a max-y or min-y objective (one endpoint may be omitted)"
        ),
    )
    command.add_argument(
        "--y-window",
        modes=fixed_frame_modes,
        type=parse_axis_window,
        metavar="MIN:MAX",
        help=(
            "inclusive permitted y range at the target frame; normally used "
            "with a max-x or min-x objective (one endpoint may be omitted)"
        ),
    )
    command.add_argument(
        "-o",
        "--output",
        type=Path,
        help=(
            "same-format main output: combined text for text input or an .ltm "
            "movie for .ltm input"
        ),
    )
    command.add_argument(
        "--config",
        type=Path,
        help=(
            "TOML file supplying defaults; explicit command-line options "
            "override its values"
        ),
    )
    command.add_argument(
        "--replay-output",
        type=Path,
        help="optional file receiving only the packed replay string",
    )
    enemy_group = command.add_mutually_exclusive_group()
    enemy_group.add_argument(
        "--simulate-enemies",
        dest="simulate_enemies",
        action="store_true",
        default=None,
        help=(
            "enable supported enemy simulation (currently floorguards, zap, laser and "
            "chaingun drones, homing launchers and gauss turrets); enabled by "
            "default in auto and disabled by default in local and jump-pattern"
        ),
    )
    enemy_group.add_argument(
        "--no-simulate-enemies",
        dest="simulate_enemies",
        action="store_false",
        default=None,
        help="disable supported enemy simulation (overrides the auto-mode default)",
    )
    return parser


def main() -> None:
    args = parse_arguments()
    mode_configs = getattr(args, "_mode_configs", None)
    if mode_configs is None:
        mode_configs = build_mode_configs(args)
    common_config = mode_configs.common
    local_config = mode_configs.local
    jump_pattern_config = mode_configs.jump_pattern
    input_path = common_config.input_path
    output_path = common_config.output_path
    replay_output_path = common_config.replay_output_path
    try:
        source = _load_source(
            input_path,
            levels_file_path=common_config.levels_file_path,
            explicit_level_id=common_config.level_id,
            ltm_postroll=common_config.ltm_postroll,
        )
    except LtmError as exc:
        raise SystemExit(str(exc)) from exc
    combined = source.combined
    if source.ltm_movie is not None and source.ltm_movie.warning is not None:
        print(f"warning: {source.ltm_movie.warning}", file=sys.stderr)
    simulate_enemies = (
        args.mode == "auto"
        if common_config.simulate_enemies is None
        else common_config.simulate_enemies
    )
    level = parse_level_string(
        combined.level_string,
        simulate_enemies=simulate_enemies,
    )

    if args.list_objects:
        print(format_level_objects(level))
        return

    if common_config.output_path is None:
        raise SystemExit("--output is required unless --list-objects is used")
    assert output_path is not None
    if source.ltm_movie is not None and output_path.suffix.lower() != ".ltm":
        raise SystemExit("an .ltm input requires an .ltm --output path")
    if source.ltm_movie is None and output_path.suffix.lower() == ".ltm":
        raise SystemExit(
            "a combined text input cannot create an .ltm output without an LTM template"
        )

    auto_parent_sources: list[tuple[Path, _LoadedSource]] = []
    if args.mode == "auto":
        for parent_number, parent_path in enumerate(args.auto_parents, start=2):
            try:
                parent_source = _load_source(
                    parent_path,
                    levels_file_path=(
                        common_config.levels_file_path
                        if parent_path.suffix.lower() == ".ltm"
                        else None
                    ),
                    explicit_level_id=(
                        common_config.level_id
                        if parent_path.suffix.lower() == ".ltm"
                        else None
                    ),
                    ltm_postroll=(
                        common_config.ltm_postroll
                        if parent_path.suffix.lower() == ".ltm"
                        else None
                    ),
                )
            except LtmError as exc:
                raise SystemExit(
                    f"could not load auto parent #{parent_number} "
                    f"{parent_path}: {exc}"
                ) from exc
            if parent_source.combined.level_string != combined.level_string:
                raise SystemExit(
                    f"auto parent #{parent_number} {parent_path} is not for "
                    "exactly the same level as positional INPUT"
                )
            if (
                parent_source.ltm_movie is not None
                and parent_source.ltm_movie.warning is not None
            ):
                print(
                    f"warning: auto parent #{parent_number}: "
                    f"{parent_source.ltm_movie.warning}",
                    file=sys.stderr,
                )
            auto_parent_sources.append((parent_path, parent_source))

    try:
        _validate_output_paths(
            input_path,
            output_path,
            replay_output_path,
        )
        _validate_levels_output_paths(
            source.levels_file_path,
            output_path,
            replay_output_path,
        )
        for parent_path, parent_source in auto_parent_sources:
            _validate_output_paths(
                parent_path,
                output_path,
                replay_output_path,
            )
            _validate_levels_output_paths(
                parent_source.levels_file_path,
                output_path,
                replay_output_path,
            )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.mode != "auto" and (
        (local_config is not None and local_config.target_frame is None)
        or (jump_pattern_config is not None and jump_pattern_config.target_frame is None)
    ):
        raise SystemExit(
            "--target-frame is required for local and jump-pattern unless "
            "--list-objects is used"
        )

    replay = decode_complex_replay(combined.replay_string)
    source_frames = editable_frames(replay.frames)
    retimed_frames = source_frames
    applied_retimes: list[RetimeMutation] = []
    for spec_index, (start_spec, delta) in enumerate(common_config.retime, start=1):
        transitions = input_transition_frames(retimed_frames)
        if not transitions:
            raise SystemExit("cannot retime a replay with no input transitions")
        suffix_start = transitions[0] if start_spec == "whole" else start_spec
        mutation = RetimeMutation(int(suffix_start), delta)
        try:
            retimed_frames = apply_suffix_retime(retimed_frames, mutation)
        except ValueError as exc:
            raise SystemExit(f"invalid --retime #{spec_index}: {exc}") from exc
        applied_retimes.append(mutation)
        print(
            f"retime {spec_index}: suffix transition {mutation.suffix_start} "
            f"{mutation.delta:+d} frame(s)"
        )
    replay = ComplexReplay(retimed_frames)

    auto_parent_frames: list[tuple[InputFrame, ...]] = []
    for parent_number, (_parent_path, parent_source) in enumerate(
        auto_parent_sources,
        start=2,
    ):
        parent_replay = decode_complex_replay(parent_source.combined.replay_string)
        parent_retimed_frames = editable_frames(parent_replay.frames)
        for spec_index, (start_spec, delta) in enumerate(
            common_config.retime,
            start=1,
        ):
            transitions = input_transition_frames(parent_retimed_frames)
            if not transitions:
                raise SystemExit(
                    f"cannot apply --retime #{spec_index} to auto parent "
                    f"#{parent_number}: replay has no input transitions"
                )
            suffix_start = transitions[0] if start_spec == "whole" else start_spec
            mutation = RetimeMutation(int(suffix_start), delta)
            try:
                parent_retimed_frames = apply_suffix_retime(
                    parent_retimed_frames,
                    mutation,
                )
            except ValueError as exc:
                raise SystemExit(
                    f"invalid --retime #{spec_index} for auto parent "
                    f"#{parent_number}: {exc}"
                ) from exc
        auto_parent_frames.append(tuple(parent_retimed_frames))

    if args.mode == "auto":
        if args.auto_postroll != 1:
            raise SystemExit(
                "Auto uses exactly one neutral sentinel; --auto-postroll must be 1"
            )
        effective_auto_extra_ticks = (
            args.auto_max_extra_ticks
            if args.auto_max_extra_ticks is not None
            else GOLD_BONUS_TICKS
            if args.auto_objective == AUTO_OBJECTIVE_HIGHSCORE
            else 0
        )
        if effective_auto_extra_ticks < 0:
            raise SystemExit("--auto-max-extra-ticks must be non-negative")
        try:
            auto_range_start, auto_range_end = (
                parse_frame_range(
                    args.frame_range,
                    target_frame=(
                        len(replay.frames) - 1 + effective_auto_extra_ticks
                    ),
                )
                if args.frame_range is not None
                else (0, None)
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        position_tolerance = args.auto_position_tolerance
        velocity_tolerance = args.auto_velocity_tolerance
        if args.auto_match_tolerance is not None:
            if (
                not math.isfinite(args.auto_match_tolerance)
                or args.auto_match_tolerance < 0
            ):
                raise SystemExit(
                    "--auto-match-tolerance must be finite and non-negative"
                )
            position_tolerance = math.sqrt(args.auto_match_tolerance)
            velocity_tolerance = position_tolerance / 2.0
        if args.seed == "random":
            auto_seed = int.from_bytes(os.urandom(8), "big")
            print(f"[auto:seed] random seed {auto_seed}", flush=True)
        else:
            auto_seed = 0 if args.seed is None else args.seed
        try:
            auto_config = AutoConfig(
                iterations=args.iterations,
                beam_width=args.beam,
                max_retime=args.max_retime,
                seed=auto_seed,
                repair_window=args.auto_repair_window,
                repair_lookback=args.auto_repair_lookback,
                repair_lookahead=args.auto_lookahead,
                max_alignment=args.auto_max_alignment,
                deterministic_phase=args.auto_deterministic,
                repair_local_limit=args.auto_repair_local_steps,
                repair_search_order=args.auto_repair_search_order,
                frame_ahead_repair_multiplier=(
                    args.auto_frame_ahead_repair_multiplier
                ),
                repair_campaign_local_limit=args.auto_campaign_local_steps,
                beam_repair_revisit_limit=(
                    args.auto_beam_repair_revisit_limit
                ),
                splice_repair_revisit_limit=(
                    args.auto_splice_repair_revisit_limit
                ),
                range_start=auto_range_start,
                range_end=auto_range_end,
                cheap_pulse_limit=args.auto_cheap_pulses,
                all_input_repair=args.auto_all_input_repair,
                alignment_position_tolerance=position_tolerance,
                alignment_velocity_tolerance=velocity_tolerance,
                objective=args.auto_objective,
                require_reference_gold=args.auto_require_reference_gold,
                max_extra_ticks=args.auto_max_extra_ticks,
            )

            def show_auto_progress(update: AutoProgress) -> None:
                if update.phase == "baseline" and update.best_finish_tick is None:
                    text = f"[auto:baseline] {update.message}"
                elif update.phase == "baseline":
                    distance = (
                        f" (distance to exit {update.best_exit_edge_distance:.2f})"
                        if update.best_exit_edge_distance is not None
                        else ""
                    )
                    score = (
                        f"; score {update.best_objective_value}; "
                        f"gold {update.best_gold_count} "
                        f"(+{update.best_gold_bonus_ticks} ticks)"
                        if update.objective == AUTO_OBJECTIVE_HIGHSCORE
                        else ""
                    )
                    message = update.message
                    prefix = f"source verified at finish tick {update.best_finish_tick}"
                    if message.startswith(prefix):
                        message = f"{prefix}{distance}{message[len(prefix):]}"
                    text = (
                        f"[auto:baseline] {message}{score}; "
                        f"budget {update.budget} evaluations"
                    )
                else:
                    if update.objective == AUTO_OBJECTIVE_HIGHSCORE:
                        best = (
                            f"best score {update.best_objective_value} "
                            f"(finish {update.best_finish_tick}, "
                            f"gold {update.best_gold_count}, "
                            f"bonus {update.best_gold_bonus_ticks}); "
                            if update.best_finish_tick is not None
                            else ""
                        )
                    else:
                        best = (
                            f"best {update.best_finish_tick}; "
                            if update.best_finish_tick is not None
                            else ""
                        )
                    if update.repair_index:
                        campaign = (
                            f"campaign {update.campaign_index}; "
                            if update.campaign_index
                            else ""
                        )
                        repair = (
                            f"repair {update.repair_index}; {campaign}"
                            f"{update.local_simulations:,} local steps; "
                        )
                    else:
                        repair = ""
                    text = (
                        f"[auto:{update.phase}] "
                        f"{update.macro_evaluations}/{update.budget} evaluations; "
                        f"{best}{repair}{update.message}"
                    )
                print(text, flush=True)

            auto_stdout_start = time.monotonic()

            def auto_elapsed() -> str:
                seconds = max(0, int(time.monotonic() - auto_stdout_start))
                hours, remainder = divmod(seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            def auto_system_time() -> str:
                return time.strftime("%H:%M:%S")

            def show_auto_status(message: str) -> None:
                print(
                    f"[{auto_system_time()}] {message}; elapsed {auto_elapsed()}",
                    flush=True,
                )

            checkpoint_count = 0

            def save_auto_best(candidate: AutoCandidate) -> None:
                nonlocal checkpoint_count
                checkpoint_frames = candidate.frames
                checkpoint_replay = encode_complex_replay(checkpoint_frames)
                packed_frames = editable_frames(
                    decode_complex_replay(checkpoint_replay).frames
                )
                try:
                    verify_trimmed_replay(
                        level,
                        packed_frames,
                        expected_finish_tick=candidate.finish_tick,
                        expected_gold_mask=candidate.evaluation.final_gold_mask,
                        expected_gold_bonus_ticks=candidate.evaluation.gold_bonus_ticks,
                    )
                except ValueError as exc:
                    raise RuntimeError(
                        f"best-run checkpoint verification failed: {exc}"
                    ) from exc
                _write_result(
                    source,
                    output_path,
                    replay_output_path,
                    checkpoint_replay,
                )
                checkpoint_count += 1
                edge_distance = pre_finish_exit_edge_distance(
                    level, candidate.evaluation
                )
                distance = (
                    f" (distance to exit {edge_distance:.2f})"
                    if edge_distance is not None
                    else ""
                )
                if auto_config.objective == AUTO_OBJECTIVE_HIGHSCORE:
                    print(
                        f"[{auto_system_time()}] "
                        f"[auto:checkpoint] saved best #{checkpoint_count}: "
                        f"score {candidate.evaluation.highscore_value}; "
                        f"finish {candidate.finish_tick}{distance}; "
                        f"gold {candidate.evaluation.gold_count}; "
                        f"elapsed {auto_elapsed()}",
                        flush=True,
                    )
                else:
                    print(
                        f"[{auto_system_time()}] "
                        f"[auto:checkpoint] saved best #{checkpoint_count}: "
                        f"finish {candidate.finish_tick}{distance}; "
                        f"elapsed {auto_elapsed()}",
                        flush=True,
                    )

            auto_campaign = optimise_autonomous_campaign(
                level,
                replay.frames,
                auto_config,
                parent_frames=auto_parent_frames,
                workers=args.workers,
                runs=args.auto_runs,
                progress=show_auto_progress,
                best_callback=save_auto_best,
                status=show_auto_status,
                search=optimise_autonomous,
            )
            auto_result = auto_campaign.result
        except (RuntimeError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc

        optimised_frames = auto_result.frames
        replay_string = encode_complex_replay(optimised_frames)

        # Verify the actual serialized representation, including canonicalized
        # jump-trigger bits, rather than trusting only the in-memory proposal.
        packed_frames = editable_frames(
            decode_complex_replay(replay_string).frames
        )
        try:
            packed_verification = verify_trimmed_replay(
                level,
                packed_frames,
                expected_finish_tick=auto_result.finish_tick,
                expected_gold_mask=auto_result.gold_mask,
                expected_gold_bonus_ticks=auto_result.gold_bonus_ticks,
            )
        except ValueError as exc:
            raise SystemExit(
                f"final packed replay verification failed: {exc}; no output was written"
            ) from exc
        if not packed_verification.valid:
            raise SystemExit(
                "final packed replay was not a live completed route; "
                "no output was written"
            )

        _write_result(source, output_path, replay_output_path, replay_string)

        changed = changed_frame_indices(source_frames, optimised_frames)
        saved = auto_result.baseline_finish_tick - auto_result.finish_tick
        stats = auto_result.stats
        print()
        print(f"auto objective: {auto_result.objective}")
        if auto_result.objective == AUTO_OBJECTIVE_HIGHSCORE:
            raw_change = auto_result.finish_tick - auto_result.baseline_finish_tick
            raw_change_text = (
                f"{raw_change} ticks slower"
                if raw_change > 0
                else f"{-raw_change} ticks faster"
                if raw_change < 0
                else "same raw time"
            )
            print(
                f"auto baseline: finish {auto_result.baseline_finish_tick}; "
                f"gold {auto_result.baseline_gold_count}; "
                f"gold bonus {auto_result.baseline_gold_bonus_ticks}; "
                f"highscore value {auto_result.baseline_objective_value}"
            )
            print(
                f"auto optimised: finish {auto_result.finish_tick} "
                f"({raw_change_text}); gold {auto_result.gold_count}; "
                f"gold bonus {auto_result.gold_bonus_ticks}; "
                f"highscore value {auto_result.objective_value}; "
                f"improvement {auto_result.objective_value - auto_result.baseline_objective_value}"
            )

            def format_gold_indices(mask: int) -> str:
                return ", ".join(
                    f"gold:{index}"
                    for index in range(mask.bit_length())
                    if mask & (1 << index)
                ) or "none"

            print(
                "missing reference gold: "
                + format_gold_indices(
                    auto_result.baseline_gold_mask & ~auto_result.gold_mask
                )
            )
            print(
                "additional gold: "
                + format_gold_indices(
                    auto_result.gold_mask & ~auto_result.baseline_gold_mask
                )
            )
        else:
            print(
                f"auto baseline finish tick: {auto_result.baseline_finish_tick} "
                f"({auto_result.baseline_finish_tick} serialized inputs)"
            )
            print(
                f"auto optimised finish tick: {auto_result.finish_tick} "
                f"({auto_result.finish_tick} serialized inputs; saved {saved})"
            )
        if auto_result.best.mutations:
            print("winning mutation chain:")
            for mutation in auto_result.best.mutations:
                print(f"  - {mutation}")
        else:
            print("winning mutation chain: source replay retained")
        gold_repair_stats = (
            f"gold repairs={stats.successful_gold_repairs}/"
            f"{stats.gold_repair_attempts}, "
            if auto_result.objective == AUTO_OBJECTIVE_HIGHSCORE
            else ""
        )
        route_control_repair_stats = (
            f"route-control repairs={stats.successful_route_control_repairs}/"
            f"{stats.route_control_repair_attempts}, "
        )
        if auto_campaign.requested_runs == 0:
            evaluation_budget = (
                f"{stats.macro_evaluations} across completed searches"
            )
        else:
            maximum_evaluations = (
                auto_config.iterations
                * auto_campaign.worker_count
                * auto_campaign.requested_runs
            )
            evaluation_budget = (
                f"{stats.macro_evaluations}/{maximum_evaluations}"
            )
        print(
            "parallel campaign: "
            f"workers={auto_campaign.worker_count}, "
            f"rounds={auto_campaign.completed_runs}"
            + (
                "/indefinite"
                if auto_campaign.requested_runs == 0
                else f"/{auto_campaign.requested_runs}"
            )
            + f", completed searches={auto_campaign.completed_searches}, "
            f"iterations per search={auto_config.iterations}"
        )
        print(
            "search statistics: "
            f"macro candidates={stats.macro_candidates}, "
            f"evaluations={evaluation_budget}, "
            f"suffix retimes={stats.raw_retimes}, boundary retimes={stats.boundary_retimes}, "
            f"suffix splices={stats.suffix_splices}, jump mutations={stats.jump_mutations}, "
            f"horizontal pulses={stats.pulse_mutations}, "
            f"direction mutations={stats.direction_mutations}, "
            f"repairs={stats.successful_repairs}/{stats.repair_attempts} "
            f"(jump lookback attempts={stats.jump_repair_attempts}, "
            f"all-input fallbacks={stats.all_input_repairs}), "
            f"structured repairs={stats.structured_repair_attempts}, "
            f"beam repairs={stats.beam_quick_repair_attempts} quick/"
            f"{stats.beam_strategic_repair_attempts} strategic, "
            f"campaigns={stats.repair_campaigns} "
            f"({stats.repair_campaign_attempts} attempts), "
            f"repair frontiers={stats.repair_frontiers_queued} queued/"
            f"{stats.repair_frontiers_dropped} dropped, "
            f"{route_control_repair_stats}"
            f"{gold_repair_stats}"
            f"reference epochs={stats.reference_epochs}, "
            f"local branches={stats.local_branches}, "
            f"local simulations={stats.local_simulations}, "
            f"deduplicated={stats.deduplicated}"
        )
        print("verification diagnostics:")
        for diagnostic in auto_result.diagnostics:
            print(f"  - {diagnostic}")
        print(f"changed frames ({len(changed)}): " + ", ".join(map(str, changed)))
        print(f"wrote {output_path}")
        if replay_output_path is not None:
            print(f"wrote {replay_output_path}")
        if auto_campaign.interrupted:
            print(
                "auto search interrupted cleanly; wrote the best verified "
                "result produced before shutdown"
            )
            raise SystemExit(130)
        return

    mode_config = local_config if args.mode == "local" else jump_pattern_config
    if mode_config is None:
        raise SystemExit(f"no typed configuration was built for mode {args.mode!r}")
    target_frame = mode_config.target_frame
    if target_frame is None:
        raise SystemExit(
            "--target-frame is required for local and jump-pattern unless "
            "--list-objects is used"
        )
    frame_range_spec = mode_config.frame_range
    objective_name = mode_config.objective
    target_object_selector = mode_config.target_object
    target_point_value = mode_config.target_point
    x_window = mode_config.x_window
    y_window = mode_config.y_window
    python_resimulate = mode_config.python_resimulate

    if isinstance(mode_config, LocalConfig):
        local_inputs = mode_config.local_inputs
        physics_prune = mode_config.physics_prune
        jump_start_mutation = mode_config.jump_start_mutation
        jump_length_mutation = mode_config.jump_length_mutation
        immutable_jumps = mode_config.immutable_jumps
        window_order = mode_config.window_order
        require_interaction_selectors = mode_config.require_interaction
        avoid_interaction_selectors = mode_config.avoid_interaction
        require_reference_interactions = mode_config.require_reference_interactions
        window_size = mode_config.window_size
        passes = mode_config.passes
        minimum_improvement = mode_config.minimum_improvement
        local_window_shape = mode_config.window_shape
        window_span = mode_config.window_span
        windows_per_pass = mode_config.windows_per_pass
        restarts = mode_config.restarts
        local_workers = mode_config.workers
    else:
        local_inputs = "all"
        physics_prune = False
        jump_start_mutation = 0
        jump_length_mutation = 0
        immutable_jumps = ()
        window_order = "forward"
        require_interaction_selectors = ()
        avoid_interaction_selectors = ()
        require_reference_interactions = False
        window_size = 0
        passes = 0
        minimum_improvement = 0.0
        local_window_shape = "contiguous"
        window_span = None
        windows_per_pass = None
        restarts = 1
        local_workers = 0

    mode_seed = local_config.seed if local_config is not None else None
    if mode_seed == "random":
        raise SystemExit("--seed random is only supported with the auto subcommand")

    if target_frame < 0 or target_frame >= replay.tick_count:
        raise SystemExit(
            f"target frame must be between 0 and {replay.tick_count - 1}"
        )
    try:
        if args.mode == "local":
            frame_ranges = parse_frame_ranges(
                frame_range_spec or f"0:{target_frame}",
                target_frame=target_frame,
            )
            range_start = frame_ranges[0][0]
            range_end = frame_ranges[-1][1]
        else:
            range_start, range_end = parse_frame_range(
                frame_range_spec or f"0:{target_frame}",
                target_frame=target_frame,
            )
            frame_ranges = ((range_start, range_end),)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    objective_target: TargetSelection | None = None
    if objective_name == "min-distance":
        if (target_object_selector is None) == (target_point_value is None):
            raise SystemExit(
                "--objective min-distance requires exactly one of "
                "--target-object or --target-point"
            )
        try:
            objective_target = (
                resolve_target_object(level, target_object_selector)
                if target_object_selector is not None
                else target_from_point(target_point_value)
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    elif target_object_selector is not None or target_point_value is not None:
        raise SystemExit(
            "--target-object/--target-point require --objective min-distance"
        )

    objective = objective_function(objective_name, objective_target)

    if args.mode != "local" and (
        require_interaction_selectors
        or require_reference_interactions
        or avoid_interaction_selectors
    ):
        raise SystemExit(
            "--require-interaction, --require-reference-interactions, and "
            "--avoid-interaction require the local subcommand"
        )
    try:
        required_interactions = tuple(
            resolve_interaction_requirement(level, selector)
            for selector in require_interaction_selectors
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        avoided_interactions = tuple(
            resolve_interaction_avoidance(level, selector)
            for selector in avoid_interaction_selectors
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    original_editable = source_frames
    baseline = evaluate(
        level,
        original_editable,
        target_frame,
        objective,
        x_window=x_window,
        y_window=y_window,
    )
    retimed_seed_eval = (
        evaluate(
            level,
            replay.frames,
            target_frame,
            objective,
            x_window=x_window,
            y_window=y_window,
        )
        if applied_retimes
        else None
    )
    reference_required_interactions: tuple[InteractionRequirement, ...] = ()
    if args.mode == "local" and require_reference_interactions:
        reference_state = (
            retimed_seed_eval.state
            if retimed_seed_eval is not None
            else baseline.state
        )
        reference_required_interactions = reference_interaction_requirements(
            level, reference_state
        )
    effective_required_interactions = merge_interaction_requirements(
        required_interactions,
        reference_required_interactions,
    )
    effective_avoided_interactions = merge_interaction_avoidances(
        avoided_interactions
    )

    jump_mutation_enabled = (
        jump_start_mutation != 0 or jump_length_mutation != 0
    )
    if jump_start_mutation < 0 or jump_length_mutation < 0:
        raise SystemExit("--jump-start-mutation and --jump-length-mutation must be non-negative")
    if jump_mutation_enabled and (
        args.mode != "local" or local_inputs != "direction"
    ):
        raise SystemExit(
            "jump mutation requires the local subcommand with "
            "--local-inputs direction"
        )
    if jump_mutation_enabled and window_order not in ("random", "mixed"):
        raise SystemExit(
            "jump mutation requires --window-order random or mixed"
        )
    if immutable_jumps and not jump_mutation_enabled:
        raise SystemExit(
            "--immutable-jumps requires --jump-start-mutation or "
            "--jump-length-mutation"
        )

    if physics_prune and (
        args.mode != "local" or local_inputs != "direction"
    ):
        raise SystemExit(
            "--physics-prune requires the local subcommand with "
            "--local-inputs direction"
        )

    fixed_jump_frames = (
        jump_pattern_config.fixed_jump_frames
        if jump_pattern_config is not None
        else ()
    )
    if fixed_jump_frames and args.mode != "jump-pattern":
        raise SystemExit(
            "--fixed-jump-frames requires the jump-pattern subcommand"
        )

    jump_results: list[JumpSearchResult] | None = None
    local_checkpoint_written = False
    if args.mode == "jump-pattern":
        assert jump_pattern_config is not None
        jump_min, jump_max = jump_pattern_config.jumps
        length_min, length_max = jump_pattern_config.jump_length
        jump_results = optimise_jump_patterns(
            level,
            replay.frames,
            target_frame=target_frame,
            range_start=range_start,
            range_end=range_end,
            objective_name=objective_name,
            objective_target=objective_target,
            jump_count_min=jump_min,
            jump_count_max=jump_max,
            jump_length_min=length_min,
            jump_length_max=length_max,
            minimum_gap=jump_pattern_config.minimum_gap,
            top_results=jump_pattern_config.top_results,
            fixed_jump_frames=fixed_jump_frames,
            x_window=x_window,
            y_window=y_window,
            workers=jump_pattern_config.workers,
            python_resimulate=python_resimulate,
        )
        if not jump_results:
            raise SystemExit(
                "no feasible jump pattern with the requested successful-jump "
                "count/length/fixed-frame constraints was found; no output was written"
            )
        best = jump_results[0]
        optimised_frames = apply_jump_pattern(
            replay.frames,
            range_start=range_start,
            range_end=range_end,
            pulses=best.pulses,
        )
        # The retained result already carries the native terminal view or the
        # opt-in Python-resimulated state. Packed-output verification below is
        # the only additional full replay pass.
        final_eval = best.evaluation
    else:
        def checkpoint_local_best(run: LocalSearchRunResult) -> bool:
            nonlocal local_checkpoint_written
            # A completed worker trajectory is only a proposal. Verify the
            # exact serialized replay from frame zero before it can replace a
            # previously valid checkpoint on disk.
            try:
                checkpoint_replay, _packed_frames, _packed_evaluation = (
                    _verify_packed_replay_for_output(
                        level,
                        run.frames,
                        target_frame=target_frame,
                        objective=objective,
                        expected_evaluation=run.evaluation,
                        x_window=x_window,
                        y_window=y_window,
                        required_interactions=effective_required_interactions,
                        avoided_interactions=effective_avoided_interactions,
                        expected_missing_jump_frames=(
                            run.missing_required_jump_frames
                        ),
                        require_successful_jump_presses=(
                            local_inputs == "direction"
                        ),
                        python_resimulate=python_resimulate,
                    )
                )
            except ValueError:
                return False
            _write_result(
                source,
                output_path,
                replay_output_path,
                checkpoint_replay,
            )
            local_checkpoint_written = True
            return True

        try:
            optimised_frames, final_eval = optimise_local_windows(
                level,
                replay.frames,
                target_frame=target_frame,
                range_start=range_start,
                range_end=range_end,
                frame_ranges=frame_ranges,
                objective_name=objective_name,
                objective_target=objective_target,
                window_size=window_size,
                passes=passes,
                minimum_improvement=minimum_improvement,
                x_window=x_window,
                y_window=y_window,
                local_inputs=local_inputs,
                physics_prune=physics_prune,
                window_order=window_order,
                window_shape=local_window_shape,
                window_span=window_span,
                windows_per_pass=windows_per_pass,
                restarts=restarts,
                seed=mode_seed,
                jump_start_mutation=jump_start_mutation,
                jump_length_mutation=jump_length_mutation,
                immutable_jumps=immutable_jumps,
                required_interactions=required_interactions,
                avoided_interactions=avoided_interactions,
                require_reference_interactions=require_reference_interactions,
                workers=local_workers,
                best_run_callback=checkpoint_local_best,
                python_resimulate=python_resimulate,
            )
        except (RuntimeError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc

    try:
        replay_string, packed_frames, packed_eval = (
            _verify_packed_replay_for_output(
                level,
                optimised_frames,
                target_frame=target_frame,
                objective=objective,
                expected_evaluation=final_eval,
                x_window=x_window,
                y_window=y_window,
                required_interactions=(
                    effective_required_interactions
                    if args.mode == "local"
                    else ()
                ),
                avoided_interactions=(
                    effective_avoided_interactions
                    if args.mode == "local"
                    else ()
                ),
                require_successful_jump_presses=(
                    args.mode == "local" and local_inputs == "direction"
                ),
                python_resimulate=python_resimulate,
            )
        )
    except ValueError as exc:
        output_status = (
            "the most recent verified local checkpoint remains on disk"
            if args.mode == "local" and local_checkpoint_written
            else "no output was written"
        )
        raise SystemExit(
            f"final packed replay verification failed: {exc}; {output_status}"
        ) from exc
    optimised_frames = packed_frames
    final_eval = packed_eval

    _write_result(source, output_path, replay_output_path, replay_string)

    changed = changed_frame_indices(original_editable, optimised_frames)
    bp = baseline.state.player
    fp = final_eval.state.player
    print()
    if jump_results is not None:
        print("ranked jump patterns (start+hold):")
        for rank, result in enumerate(jump_results, start=1):
            p = result.evaluation.state.player
            pulse_text = ", ".join(str(pulse) for pulse in result.pulses)
            print(
                f"  {rank:>2}. score={result.score:.17g}; "
                f"position=({p.pos.x:.15g}, {p.pos.y:.15g}); "
                f"jumps={pulse_text}"
            )
        print()
    print(
        f"baseline frame {target_frame}: "
        f"x={bp.pos.x:.15f}, y={bp.pos.y:.15f}"
    )
    if retimed_seed_eval is not None:
        rp = retimed_seed_eval.state.player
        print(
            f"retimed seed frame {target_frame}: "
            f"x={rp.pos.x:.15f}, y={rp.pos.y:.15f}"
        )
    print(
        f"optimised frame {target_frame}: "
        f"x={fp.pos.x:.15f}, y={fp.pos.y:.15f}"
    )
    if objective_target is not None:
        baseline_target, baseline_d2 = objective_target.closest(baseline.state)
        final_target, final_d2 = objective_target.closest(final_eval.state)
        print(
            f"distance target: {objective_target.selector}; "
            f"baseline nearest={baseline_target.label}, "
            f"distance={math.sqrt(baseline_d2):.15f}; "
            f"optimised nearest={final_target.label}, "
            f"distance={math.sqrt(final_d2):.15f}"
        )
    if effective_required_interactions:
        print(
            "required interactions satisfied: "
            + format_interaction_requirements(effective_required_interactions)
        )
    if effective_avoided_interactions:
        print(
            "forbidden interactions avoided: "
            + format_interaction_avoidances(effective_avoided_interactions)
        )
    print(f"changed frames ({len(changed)}): " + ", ".join(map(str, changed)))
    print(f"wrote {output_path}")
    if replay_output_path is not None:
        print(f"wrote {replay_output_path}")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        main()
    except KeyboardInterrupt:
        print(_interrupt_message())
        raise SystemExit(130) from None
