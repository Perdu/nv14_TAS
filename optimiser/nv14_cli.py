"""Command-line parsing, TOML configuration, dispatch, and output handling."""
from __future__ import annotations

import argparse
import hashlib
import json
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
    evaluate_replay_with_sentinel,
    optimise_autonomous,
    pre_finish_exit_edge_distance,
    verify_trimmed_replay,
)
from nv14_auto_parallel import optimise_autonomous_campaign
from nv14_auto_endpoint import (
    AutoEndpointConfig, endpoint_exit_edge_distance, optimise_auto_endpoint_campaign,
)
from nv14_random_splice import RandomSpliceConfig, optimise_random_splices
from nv14_endpoint import EndpointGoal, RequiredJump, verify_endpoint
from nv14_checkpoint import AutoCheckpointError, read_auto_checkpoint
from nv14_endpoint import EARLIEST_OBJECTIVES, SECONDARY_OBJECTIVES
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
    LtmError,
    LtmMovie,
    discover_levels_file,
    find_level_record,
    infer_level_id_from_ltm_filename,
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
    resolve_interaction_target,
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


def _print_best_line(message: str, *, color: bool) -> None:
    """Highlight a new best on TTYs, keeping redirected logs ANSI-free."""
    _print_colored_line(message, color=color, ansi_color=32)


def _print_temporary_line(message: str, *, color: bool) -> None:
    """Highlight an improving splice checkpoint, not a verified final best."""
    _print_colored_line(message, color=color, ansi_color=33)


def _print_baseline_line(message: str, *, color: bool) -> None:
    """Show the starting result in blue, without ANSI escapes in captured logs."""
    _print_colored_line(message, color=color, ansi_color=34)


def _print_colored_line(message: str, *, color: bool, ansi_color: int) -> None:
    if color and sys.stdout.isatty():
        print(f"\x1b[{ansi_color}m{message}\x1b[0m", flush=True)
    else:
        print(message, flush=True)


def _print_user_splice_progress(message: str, *, color: bool) -> None:
    """Color verified merge results like ordinary multi-splice bests.

    Yellow is a saved, local/temporary gain not yet propagated to a completed
    replay. Green is an independently verified completed improvement. All
    other diagnostics and quiet merge summaries retain their normal style.
    """
    if message.startswith("[auto:user-splice:baseline]"):
        _print_baseline_line(message, color=color)
    elif (message.startswith(("[auto:user-splice:temporary]",
                              "[auto:user-splice:summary:pending]"))
          or "new saved stage best" in message
          or "verified stage join" in message):
        _print_temporary_line(message, color=color)
    elif (message.startswith(("[auto:user-splice] improved ",
                              "[auto:user-splice:summary:propagated]"))
          or "improved verified completed replay" in message
          or "verified completed join" in message):
        _print_best_line(message, color=color)
    else:
        print(message, flush=True)


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
    color: bool = True

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
            color=args.color,
        )


@dataclass(frozen=True, slots=True)
class _LoadedSource:
    """Format-neutral optimiser input plus optional LTM output template."""

    combined: CombinedLevelReplay
    ltm_movie: LtmMovie | None = None
    level_id: str | None = None
    level_record: str | None = None
    levels_file_path: Path | None = None
    promote_ltm_neutral_tail: bool = False


@dataclass(frozen=True, slots=True)
class LocalConfig:
    """Typed local-subcommand configuration.

    Fields deliberately use semantic names (``window_size`` and
    ``jump_start_mutation``) while ``from_namespace`` preserves the existing
    CLI destination names.  Level-dependent values such as the resolved
    interaction atoms and the concrete range are filled by the normal local
    setup after the source replay has been loaded.
    """

    search: str = "windows"
    vx_window: AxisWindow | None = None
    vy_window: AxisWindow | None = None
    target_region: tuple[float, float, float, float] | None = None
    arrival_start: int | None = None
    require_region: tuple[float, float, float, float] | None = None
    require_region_frames: tuple[int, int] | None = None
    require_jump_region: tuple[float, float, float, float] | None = None
    require_jump_frames: tuple[int, int] | None = None
    required_jumps: tuple[RequiredJump, ...] = ()
    require_drone_detection: tuple[str, ...] = ()
    require_drone_detection_frames: tuple[int, int] | None = None
    survive_after_goal: int = 0
    top_results: int = 1
    iterations: int = 10000
    beam: int = 32
    rounds: int = 1
    stagnation_rounds: int = 20
    repair_steps: int = 64
    repair_lookback: int = 32
    mutation_span: int = 32
    checkpoint_path: Path | None = None
    resume: bool = False
    target_frame: int | None = None
    frame_range: str | tuple[str, ...] | None = None
    objective: str = "max-x"
    target_object: str | None = None
    target_point: tuple[float, float] | None = None
    x_window: AxisWindow | None = None
    y_window: AxisWindow | None = None
    window_size: int = 4
    local_beam_width: int = 0
    local_search_cache_entries: int = 0
    local_adaptive_windows: bool = False
    local_search_ticks: int = 0
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
    secondary_objective: str | None = None

    def __post_init__(self) -> None:
        if self.search not in ("windows", "population"):
            raise ValueError("local search must be windows or population")
        if not 0 <= self.local_beam_width <= 4096:
            raise ValueError("local-beam-width must be between 0 and 4096")
        if not 0 <= self.local_search_cache_entries <= 64:
            raise ValueError("local-search-cache-entries must be between 0 and 64")
        if self.local_search_ticks < 0:
            raise ValueError("local-search-ticks must be non-negative")
        if self.search == "population" and (
            self.local_beam_width or self.local_search_cache_entries
            or self.local_adaptive_windows or self.local_search_ticks
        ):
            raise ValueError("local hybrid search options require --search windows; "
                             "population uses a separate proposal engine")
        if self.search == "windows" and (
            self.objective in EARLIEST_OBJECTIVES or self.target_region is not None
            or self.arrival_start is not None or self.top_results != 1
            or self.require_region is not None or self.require_region_frames is not None
            or self.require_jump_region is not None or self.require_jump_frames is not None
            or self.required_jumps
            or self.checkpoint_path is not None or self.resume
            or self.secondary_objective is not None
            or self.survive_after_goal
        ):
            raise ValueError("endpoint extensions require --search population")
        if self.search == "population":
            if type(self.survive_after_goal) is not int or self.survive_after_goal < 0:
                raise ValueError("survive-after-goal must be a non-negative integer")
            if self.require_region_frames is not None and self.require_region is None:
                raise ValueError("require-region-frames requires require-region")
            if self.required_jumps and self.require_jump_region is not None:
                raise ValueError("require-jumps cannot be combined with require-jump-region")
            if self.require_jump_frames is not None:
                if self.require_jump_region is None:
                    raise ValueError("--require-jump-frames requires --require-jump-region")
                if (len(self.require_jump_frames) != 2
                        or any(type(v) is not int for v in self.require_jump_frames)
                        or not 0 <= self.require_jump_frames[0] <= self.require_jump_frames[1]):
                    raise ValueError("--require-jump-frames must be ordered non-negative integer bounds")
                if self.target_frame is not None and self.require_jump_frames[1] > self.target_frame:
                    raise ValueError("--require-jump-frames must not exceed --target-frame")
            if self.secondary_objective is not None:
                if self.secondary_objective not in SECONDARY_OBJECTIVES:
                    raise ValueError("secondary-objective must be one of: " + ", ".join(SECONDARY_OBJECTIVES))
                if self.objective not in EARLIEST_OBJECTIVES:
                    raise ValueError("--secondary-objective requires --objective earliest-arrival or earliest-interaction")
                if (self.secondary_objective == "min-exit-distance"
                        and self.objective != "earliest-interaction"):
                    raise ValueError("--secondary-objective min-exit-distance requires "
                                     "--objective earliest-interaction with an exit-door target")
            for name in ("iterations", "beam", "top_results", "mutation_span"):
                if getattr(self, name) < 1:
                    raise ValueError(f"{name.replace('_', '-')} must be at least 1")
            for name in ("rounds", "stagnation_rounds", "repair_steps", "repair_lookback"):
                if getattr(self, name) < 0:
                    raise ValueError(f"{name.replace('_', '-')} must be non-negative")
            if self.top_results > self.beam:
                raise ValueError("top-results must not exceed beam")
            if self.arrival_start is not None and self.arrival_start < 0:
                raise ValueError("arrival-start must be non-negative")
            if self.resume and self.checkpoint_path is None:
                raise ValueError("--resume requires --checkpoint FILE")
            if self.objective == "earliest-arrival":
                if self.target_region is None:
                    raise ValueError("--objective earliest-arrival requires --target-region")
            elif self.target_region is not None:
                raise ValueError("--target-region requires --objective earliest-arrival")
            if self.objective in EARLIEST_OBJECTIVES:
                if self.arrival_start is not None and self.target_frame is not None and self.arrival_start > self.target_frame:
                    raise ValueError("--arrival-start must not exceed --target-frame")
            elif self.arrival_start is not None:
                raise ValueError("--arrival-start requires --objective earliest-arrival or earliest-interaction")
        if self.objective not in (
            "earliest-arrival",
            "earliest-interaction",
            "max-x",
            "min-x",
            "max-y",
            "min-y",
            "min-distance",
        ):
            raise ValueError(
                "local objective must be one of: max-x, min-x, max-y, "
                "min-y, min-distance, earliest-arrival or earliest-interaction (population only)"
            )
        if self.objective == "earliest-interaction":
            if self.target_object is None:
                raise ValueError("--objective earliest-interaction requires --target-object")
            if self.target_point is not None:
                raise ValueError("--target-point requires objective=min-distance")
        elif self.target_object is not None or self.target_point is not None:
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
            search=args.search,
            vx_window=args.vx_window,
            vy_window=args.vy_window,
            target_region=args.target_region,
            arrival_start=args.arrival_start,
            require_region=args.require_region,
            require_region_frames=args.require_region_frames,
            require_jump_region=args.require_jump_region,
            require_jump_frames=args.require_jump_frames,
            required_jumps=tuple(args.require_jumps),
            require_drone_detection=tuple(args.require_drone_detection),
            require_drone_detection_frames=args.require_drone_detection_frames,
            survive_after_goal=getattr(args, "survive_after_goal", 0),
            top_results=args.top_results,
            iterations=args.iterations,
            beam=args.beam,
            rounds=args.rounds,
            stagnation_rounds=args.stagnation_rounds,
            repair_steps=args.repair_steps,
            repair_lookback=args.repair_lookback,
            mutation_span=args.mutation_span,
            checkpoint_path=args.checkpoint,
            resume=args.resume,
            target_frame=args.target_frame,
            frame_range=args.frame_range,
            objective=args.objective,
            secondary_objective=args.secondary_objective,
            target_object=args.target_object,
            target_point=args.target_point,
            x_window=args.x_window,
            y_window=args.y_window,
            window_size=args.window,
            local_beam_width=args.local_beam_width,
            local_search_cache_entries=args.local_search_cache_entries,
            local_adaptive_windows=args.local_adaptive_windows,
            local_search_ticks=args.local_search_ticks,
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


def parse_auto_mutations(value: str) -> str | tuple[str, ...]:
    """Parse low/medium/high or comma-separated route-scale operator names."""
    from nv14_route_mutations import parse_operators
    try:
        return parse_operators(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


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


def parse_positive_finite_float(text: str) -> float:
    """A positive finite rate, suitable for iterations per editable frame."""
    try:
        value = float(text)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("value must be a positive finite number") from exc
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("value must be a positive finite number")
    return value


def resolve_auto_endpoint_iterations(
    *, full_run_iterations: int, endpoint_iterations: int | None,
    endpoint_iterations_per_frame: float | None,
    range_start: int, range_end: int,
) -> int:
    """Select the per-worker endpoint budget without changing full-run Auto.

    Explicit endpoint-iterations takes priority over the optional per-frame
    rate, and both fall back to the historical --iterations value.
    Ranges are inclusive, including any materialised neutral tail.
    """
    if not 0 <= range_start <= range_end:
        raise ValueError("invalid endpoint editable range for iteration budget")
    if endpoint_iterations is not None:
        if endpoint_iterations < 0:
            raise ValueError("endpoint-iterations must be non-negative")
        return endpoint_iterations
    if endpoint_iterations_per_frame is not None:
        if not math.isfinite(endpoint_iterations_per_frame) or endpoint_iterations_per_frame <= 0:
            raise ValueError("endpoint-iterations-per-frame must be a positive finite number")
        scaled = endpoint_iterations_per_frame * (range_end - range_start + 1)
        if not math.isfinite(scaled):
            raise ValueError("endpoint iteration budget is too large")
        return max(1, math.ceil(scaled))
    return full_run_iterations


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


def parse_auto_frame_range(
    spec: str | None, *, target_frame: int
) -> tuple[int, int | None]:
    """Keep an omitted Auto endpoint relative to each verified search body."""
    if spec is None:
        return 0, None
    texts = _frame_range_texts(spec)
    if len(texts) != 1:
        raise ValueError(
            "multiple optimisation ranges are only supported by local mode"
        )
    start_text, separator, end_text = texts[0].partition(":")
    if separator and not end_text.strip():
        start = int(start_text) if start_text.strip() else 0
        if start < 0:
            raise ValueError("range must satisfy 0 <= start <= end")
        # Auto validates this start after trimming the replay and resolving its
        # highscore workspace. Freezing the end at the input length would make
        # a shorter parent or later round fail the verified-body bounds check.
        return start, None
    return parse_frame_range(texts[0], target_frame=target_frame)


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


def _validate_auto_checkpoint_path(
    checkpoint_path: Path,
    protected_paths: Sequence[tuple[str, Path | None]],
) -> None:
    """Keep campaign state separate from every input and ordinary output."""
    if checkpoint_path.exists() and checkpoint_path.is_dir():
        raise ValueError(
            f"Auto checkpoint must be a file, not a directory: {checkpoint_path}"
        )
    for label, path in protected_paths:
        if path is not None and _paths_alias(checkpoint_path, path):
            raise ValueError(
                f"Auto checkpoint and {label} must be different files: "
                f"{checkpoint_path}"
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
    probe_ltm_neutral_tail: bool = False,
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
        level_id = explicit_level_id
    elif (
        inferred_level_id := infer_level_id_from_ltm_filename(input_path)
    ) is not None:
        level_id = inferred_level_id
    else:
        raise LtmError(
            f"cannot infer an N level id from LTM filename {input_path.name!r}; "
            "pass --level-id (for example --level-id 00-0)"
        )

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
        promote_ltm_neutral_tail=(
            probe_ltm_neutral_tail
            and movie.inferred_neutral_tail_frames > 0
        ),
    )


def _probe_auto_ltm_completion_tail(
    level: Level,
    movie: LtmMovie,
) -> tuple[InputFrame, ...]:
    """Let Auto test the bounded N-neutral tail inferred from a raw LTM.

    When the tail reaches the exit, return the canonical body ending just
    before its neutral completion sentinel.  Cropping here keeps replay retime
    and range handling based on the real route rather than recorder padding.
    If the full probe still does not complete, retain it so Auto reports the
    usual source-route failure after simulating every available movie row.
    """
    probe_frames = movie.auto_completion_probe_frames()
    evaluation = evaluate_replay_with_sentinel(level, probe_frames)
    if not evaluation.valid or evaluation.finish_tick is None:
        return probe_frames
    canonical = probe_frames[: evaluation.finish_tick]
    try:
        verify_trimmed_replay(
            level,
            canonical,
            expected_finish_tick=evaluation.finish_tick,
            expected_gold_mask=evaluation.final_gold_mask,
            expected_gold_bonus_ticks=evaluation.gold_bonus_ticks,
        )
    except ValueError:
        return probe_frames
    return canonical


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
                promote_inferred_neutral_tail=(
                    source.promote_ltm_neutral_tail
                ),
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
    vx_window: AxisWindow | None = None,
    vy_window: AxisWindow | None = None,
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
            vx_window=vx_window,
            vy_window=vy_window,
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
            vx_window=vx_window,
            vy_window=vy_window,
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
        (argument for argument in argv if argument in {"auto", "local", "jump-pattern", "dump-player", "encode-video"}),
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


def parse_target_region(text: str) -> tuple[float, float, float, float]:
    """Parse a finite inclusive rectangle as XMIN:XMAX,YMIN:YMAX."""
    axes = text.split(",")
    if len(axes) != 2 or any(":" not in axis for axis in axes):
        raise ValueError("target-region must be XMIN:XMAX,YMIN:YMAX")
    x_axis, y_axis = (parse_axis_window(axis) for axis in axes)
    values = (x_axis.minimum, x_axis.maximum, y_axis.minimum, y_axis.maximum)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("target-region must have four finite bounds")
    return values


def parse_required_jump_frames(text: str) -> tuple[int, int]:
    """A bounded, inclusive zero-based input interval; separate from editable ranges."""
    parts = text.split(":")
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise ValueError("require-jump-frames must be START:END with both bounds")
    start, end = map(int, parts)
    if not 0 <= start <= end:
        raise ValueError("require-jump-frames must be ordered non-negative integer bounds")
    return start, end


def parse_drone_detection_frames(text: str) -> tuple[int, int]:
    """Inclusive zero-based interval in which acquisition must begin."""
    try:
        return parse_required_jump_frames(text)
    except (ValueError, TypeError) as exc:
        raise ValueError("require-drone-detection-frames must be START:END "
                         "with ordered non-negative bounds") from exc


def parse_required_jump_spec(value: object) -> RequiredJump:
    """Parse CLI REGION@FRAMES or a TOML {region=...,frames=...} table."""
    if isinstance(value, Mapping):
        if set(value) != {"region", "frames"}:
            raise ValueError("each require-jumps entry needs exactly region and frames")
        region, interval = value["region"], value["frames"]
        if isinstance(region, (list, tuple)):
            if len(region) != 4:
                raise ValueError("require-jumps region needs four bounds")
            region = f"{region[0]}:{region[1]},{region[2]}:{region[3]}"
        if isinstance(interval, (list, tuple)):
            if len(interval) != 2 or any(type(v) is not int for v in interval):
                raise ValueError("require-jumps frames need two integers")
            interval = f"{interval[0]}:{interval[1]}"
        if not isinstance(region, str) or not isinstance(interval, str):
            raise ValueError("require-jumps region and frames must be strings or arrays")
    elif isinstance(value, str) and "@" in value:
        region, interval = value.split("@", 1)
    else:
        raise ValueError("require-jumps must be REGION@START:END or {region, frames}")
    return RequiredJump(parse_target_region(region), parse_required_jump_frames(interval))


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
    {"common", "goal", "auto", "local", "multi-splicer", "multi_splicer",
     "jump-pattern", "jump_pattern", "dump-player", "dump_player", "encode-video", "encode_video"}
)
_CONFIG_APPEND_DESTS = frozenset(
    {"retime", "auto_parents", "require_interaction", "avoid_interaction",
     "auto_require_interaction", "auto_avoid_interaction",
     "require_jumps", "auto_require_jumps",
     "require_drone_detection", "auto_require_drone_detection",
     "secondary_replays", "secondary_colors", "secondary_labels"}
)
_CONFIG_RESERVED_DESTS = frozenset({"config", "goal_config", "splice_config", "input", "mode"})


def _find_option_paths(argv: Sequence[str], option: str) -> tuple[Path, ...]:
    """Collect repeated CLI file options in their original left-to-right order."""
    paths: list[Path] = []
    index = 0
    while index < len(argv):
        token = str(argv[index])
        if token == option:
            if index + 1 >= len(argv) or str(argv[index + 1]).startswith("--"):
                raise SystemExit(f"argument {option}: expected one argument")
            paths.append(Path(str(argv[index + 1])))
            index += 2
            continue
        if token.startswith(option + "="):
            value = token.partition("=")[2]
            if not value:
                raise SystemExit(f"argument {option}: expected one argument")
            paths.append(Path(value))
        index += 1
    return tuple(paths)


def _find_config_path(argv: Sequence[str]) -> Path | None:
    """Preserve the historical effective config path (last configured file)."""
    paths = _find_option_paths(argv, "--config")
    return paths[-1] if paths else None


def _config_mode_section(
    data: Mapping[str, object], mode: str
) -> Mapping[str, object]:
    """Return the selected mode table, accepting underscore spelling aliases."""
    section_name = mode.replace("-", "_")
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

    # Splice TOMLs use `runs` for global Auto rounds. Allow `rounds` in
    # [auto] to mean Local population rounds PER randomly selected anchor.
    # This alias is deliberately mode-section-only.
    if mode == "auto":
        _add_config_alias(mode_specific, "rounds", "auto_splice_rounds", overwrite=True)

    return general, mode_specific


def _format_config_value_for_type(
    action_type: Callable[[object], object] | None, value: object
) -> object:
    """Translate convenient TOML arrays into the CLI parser's string forms."""
    if not isinstance(value, (list, tuple)):
        return value

    if action_type is parse_auto_mutations:
        from nv14_route_mutations import parse_operators
        return ",".join(parse_operators(value))
    if action_type is parse_target_region:
        if len(value) != 4:
            raise ValueError("target-region arrays must contain XMIN, XMAX, YMIN, YMAX")
        return f"{value[0]}:{value[1]},{value[2]}:{value[3]}"
    if action_type in (parse_required_jump_frames, parse_drone_detection_frames):
        if len(value) != 2 or any(type(v) is not int for v in value):
            raise ValueError("require-jump-frames arrays must contain two integer bounds")
        return f"{value[0]}:{value[1]}"
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

    if isinstance(action, argparse.BooleanOptionalAction):
        if not isinstance(value, bool):
            raise ValueError(f"TOML key {key!r} must be a boolean")
        negative_options = {
            _normalise_config_key(option)
            for option in action.option_strings if option.startswith("--no-")
        }
        return not value if _normalise_config_key(key) in negative_options else value

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

    if action.dest == "auto_splice_round_speeds" and isinstance(value, (list, tuple)):
        if not value or not all(isinstance(item, str) for item in value):
            raise ValueError(f"TOML key {key!r} must contain speed names")
        return parse_splice_round_speeds(",".join(value))
    if action.dest in ("auto_splice_files", "auto_splice_alt_route") and isinstance(value, (list, tuple)):
        if not value or not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError(f"TOML key {key!r} must be a nonempty array of splice file names")
        try:
            return parse_splice_files(",".join(value))
        except argparse.ArgumentTypeError as exc:
            raise ValueError(str(exc)) from exc
    if action.dest == "auto_splice_interactions" and isinstance(value, (list, tuple)):
        if not value or not all(isinstance(item, str) for item in value):
            raise ValueError(f"TOML key {key!r} must be a nonempty string array")
        try:
            return parse_splice_interactions(",".join(value))
        except argparse.ArgumentTypeError as exc:
            raise ValueError(str(exc)) from exc
    if action.dest in ("require_jumps", "auto_require_jumps"):
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"TOML key {key!r} must be an array of jump requirement tables")
        return [parse_required_jump_spec(item) for item in value]
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
) -> tuple[dict[str, object], dict[str, object]]:
    """Return regular and named-splicer defaults separately.

    Keep [multi-splicer] values dormant until a named splice file list is
    supplied. A reusable base config must not change ordinary Auto runs.
    """
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
                "use [common], [goal], [auto], [multi-splicer], [local], "
                "[jump-pattern], [dump-player], or [encode-video]"
            )
        if section_name in _CONFIG_TABLE_NAMES and not isinstance(section, Mapping):
            raise ValueError(
                f"TOML [{section_name}] section must be a table"
            )

    common = data.get("common", {})
    if not isinstance(common, Mapping):
        raise ValueError(f"TOML [common] section must be a table: {config_path}")
    mode_values = _config_mode_section(data, mode)
    # This optional table is confined to Auto. It overlays [auto] values in
    # the same file, but does not change any other optimisation mode.
    multi_values = _config_mode_section(data, "multi-splicer") if mode == "auto" else {}

    raw_values: list[tuple[str, object, bool]] = [
        (str(key), value, False)
        for key, value in data.items()
        if key not in _CONFIG_TABLE_NAMES
    ]
    raw_values.extend(
        (str(key), value, False) for key, value in common.items()
    )
    goal_values = data.get("goal", {})
    if not isinstance(goal_values, Mapping):
        raise ValueError(f"TOML [goal] must be a table: {config_path}")
    # Shared endpoint objective definitions may be consumed by either mode.
    # [auto] and [local] can override any shared goal setting independently.
    if mode in ("auto", "local"):
        raw_values.extend((str(key), value, True) for key, value in goal_values.items())
    raw_values.extend(
        (str(key), value, True) for key, value in mode_values.items()
    )

    general_aliases, mode_aliases = _config_destination_maps(command_parser, mode)
    actions_by_destination = {
        action.dest: action
        for action in command_parser._actions
        if action.dest != "help"
    }
    # Unprefixed names in [multi-splicer] refer to the *named splicer*,
    # not to unrelated Auto settings (in particular iterations/rounds).
    splice_aliases = dict(mode_aliases)
    splice_aliases.update({
        "files": "auto_splice_files",
        "alt_route": "auto_splice_alt_route",
        "directory": "auto_splice_directory",
        "start": "auto_splice_start",
        "stop": "auto_splice_stop",
        "search": "auto_splice_search",
        "iterations": "auto_splice_iterations",
        "rounds": "auto_splice_rounds",
        "stagnation_rounds": "auto_splice_stagnation_rounds",
        "auto_stagnation_rounds": "auto_splice_auto_stagnation_rounds",
        "local_stagnation_rounds": "auto_splice_local_stagnation_rounds",
        "speed": "auto_splice_speed",
        "round_speeds": "auto_splice_round_speeds",
        "frontier": "auto_splice_frontier",
        "save_frontier": "auto_splice_save_frontier",
        "lookback": "auto_splice_stage_lookback",
        "live_save_best": "auto_splice_live_save_best",
            "merge_only": "auto_splice_merge_only",
            "merge_bests": "auto_splice_merge_bests",
        "merge_verbose": "auto_splice_merge_verbose",
        "merge_repair_only": "auto_splice_merge_repair_only",
        "merge_repair_at_end": "auto_splice_merge_repair_at_end",
        "merge_repair_pairs": "auto_splice_merge_repair_pairs",
        "merge_repair_window": "auto_splice_merge_repair_window",
        "merge_repair_targets": "auto_splice_merge_repair_targets",
        "repair_iterations": "auto_splice_repair_iterations",
        "mutations": "auto_mutations",  # endpoint Auto, not Local mutation selection
    })
    # The dedicated table is last within its file: a splice override wins over
    # a general [auto] value, but any explicit CLI flag still wins later.
    raw_values.extend((str(key), value, "splice") for key, value in multi_values.items())
    defaults: dict[str, object] = {}
    multi_defaults: dict[str, object] = {}
    for key, value, allow_mode_aliases in raw_values:
        normalised_key = _normalise_config_key(key)
        destination = (
            (splice_aliases if allow_mode_aliases == "splice" else mode_aliases).get(normalised_key)
            if allow_mode_aliases else None
        ) or general_aliases.get(normalised_key)
        if destination is None:
            raise ValueError(
                f"unknown TOML option {key!r} for [{mode}] in {config_path}"
            )
        action = actions_by_destination[destination]
        selected = multi_defaults if allow_mode_aliases == "splice" else defaults
        selected[destination] = _coerce_config_value(
            action, value, key=key, mode=mode
        )
    return defaults, multi_defaults


# Only goal-related Local values are imported by --goal-config; Local's
# population/window search settings must never alter Auto's search algorithm.
_LOCAL_GOAL_TO_AUTO = {
    "objective": "auto_objective",
    "target_frame": "auto_target_frame",
    "frame_range": "frame_range",
    "target_region": "auto_target_region",
    "target_object": "auto_target_object",
    "target_point": "auto_target_point",
    "arrival_start": "auto_arrival_start",
    "secondary_objective": "auto_secondary_objective",
    "x_window": "auto_x_window",
    "y_window": "auto_y_window",
    "vx_window": "auto_vx_window",
    "vy_window": "auto_vy_window",
    "require_interaction": "auto_require_interaction",
    "avoid_interaction": "auto_avoid_interaction",
    "require_reference_interactions": "auto_require_reference_interactions",
    "require_region": "auto_require_region",
    "require_region_frames": "auto_require_region_frames",
    "require_jump_region": "auto_require_jump_region",
    "require_jump_frames": "auto_require_jump_frames",
    "require_jumps": "auto_require_jumps",
    "require_drone_detection": "auto_require_drone_detection",
    "require_drone_detection_frames": "auto_require_drone_detection_frames",
    "survive_after_goal": "auto_survive_after_goal",
    "simulate_enemies": "simulate_enemies",
}


def _load_local_goal_defaults(
    config_path: Path, local_parser: argparse.ArgumentParser
) -> dict[str, object]:
    """Adapt an unchanged Local splice TOML to Auto endpoint options.

    Parsing through Local's existing loader preserves aliases and TOML value
    conversion, including interaction arrays and rectangle string syntax.
    Unknown or invalid Local configuration still gets a useful error.
    """
    local_values, _ = _load_config_defaults(config_path, local_parser, "local")
    return {
        auto_key: local_values[local_key]
        for local_key, auto_key in _LOCAL_GOAL_TO_AUTO.items()
        if local_key in local_values
    }


_LOCAL_WINDOWS_OPTIONS = frozenset({
    "window", "window_shape", "window_span", "windows_per_pass", "local_inputs",
    "jump_start_mutation", "jump_length_mutation", "immutable_jumps", "physics_prune",
    "passes", "window_order", "restarts", "minimum_improvement",
})
_LOCAL_POPULATION_OPTIONS = frozenset({
    "iterations", "beam", "rounds", "stagnation_rounds", "repair_steps",
    "repair_lookback", "mutation_span", "checkpoint", "resume", "top_results",
    "target_region", "arrival_start",
    "require_region", "require_region_frames",
    "require_jump_region", "require_jump_frames", "require_jumps",
    "require_drone_detection", "require_drone_detection_frames", "survive_after_goal",
    "secondary_objective",
})


def _validate_local_strategy(args: argparse.Namespace, explicit: set[str]) -> None:
    if args.mode != "local":
        return
    incompatible = (
        _LOCAL_WINDOWS_OPTIONS if args.search == "population"
        else _LOCAL_POPULATION_OPTIONS
    ) & explicit
    if incompatible:
        options = ", ".join("--" + name.replace("_", "-") for name in sorted(incompatible))
        needed = "windows" if args.search == "population" else "population"
        raise SystemExit(f"{options} require --search {needed}")
    if args.objective in EARLIEST_OBJECTIVES and args.search != "population":
        raise SystemExit(f"--objective {args.objective} requires --search population")


_AUTO_RANDOM_SPLICE_OPTIONS = frozenset({
    "auto_splice_points", "auto_splice_frames_per_point", "auto_splice_mode",
    "auto_splice_interactions", "auto_splice_skip_probability",
    "auto_splice_distance", "auto_splice_radius",
    "auto_splice_lookback", "auto_splice_iterations",
    "auto_splice_repair_iterations", "auto_splice_repair_anchors",
    "auto_splice_repair_searches", "auto_splice_rounds",
    "auto_splice_stagnation_rounds", "auto_splice_auto_stagnation_rounds",
    "auto_splice_local_stagnation_rounds", "auto_splice_speed", "auto_splice_round_speeds",
    "auto_splice_repair_rounds", "auto_splice_frontier", "auto_splice_save_frontier", "auto_splice_stage_lookback", "auto_splice_waypoint_lookback", "auto_splice_exit_lookback",
    "auto_splice_search", "auto_splice_files", "auto_splice_alt_route", "auto_splice_directory",
    "auto_splice_start", "auto_splice_stop", "auto_splice_from_best",
})


_AUTO_ENDPOINT_ONLY_OPTIONS = frozenset({
    "auto_target_frame", "auto_target_region", "auto_target_object", "auto_target_point",
    "auto_arrival_start", "auto_secondary_objective", "auto_x_window", "auto_y_window",
    "auto_vx_window", "auto_vy_window", "auto_require_interaction", "auto_avoid_interaction",
    "auto_require_reference_interactions", "auto_require_region", "auto_require_region_frames", "auto_require_jump_region",
    "auto_require_jump_frames", "auto_require_jumps",
    "auto_require_drone_detection", "auto_require_drone_detection_frames", "auto_survive_after_goal", "auto_completion_policy", "auto_mutation_span",
})


def _validate_auto_goal_strategy(args: argparse.Namespace, explicit: set[str]) -> None:
    """Keep old complete-route Auto strict about unused endpoint-only switches."""
    if args.mode != "auto":
        return
    unused = sorted(_AUTO_RANDOM_SPLICE_OPTIONS & explicit)
    if unused and not args.auto_random_splice:
        raise SystemExit("--" + ", --".join(n.replace("_", "-") for n in unused)
                         + " require --auto-random-splice")
    if args.auto_random_splice and args.auto_splice_mode == "user" and not args.auto_splice_files:
        raise SystemExit("user splice mode requires --auto-splice-files or [auto] splice-files")
    if args.auto_splice_alt_route and (not args.auto_random_splice or args.auto_splice_mode != "user"):
        raise SystemExit("--splice-alt-route requires named multi-splicer mode")
    # A primary-route start can skip the shared prefix while the alternate
    # campaign still searches its divergent stages. Stop/from-best remain
    # ambiguous across independently ordered named routes.
    if args.auto_splice_alt_route and (args.auto_splice_stop or args.auto_splice_from_best):
        raise SystemExit("alternate routes cannot be combined with --splice-stop/from-best")
    if args.auto_random_splice and args.auto_splice_files and args.auto_splice_mode != "user":
        raise SystemExit("splice-files requires --auto-splice-mode user")
    if (args.auto_random_splice and
            (args.auto_splice_start or args.auto_splice_stop or args.auto_splice_from_best)
            and args.auto_splice_mode != "user"):
        raise SystemExit("--splice-start/--splice-stop/--splice-from-best require named user splice mode")
    if (args.auto_random_splice and args.auto_splice_mode != "user" and
            "auto_splice_stage_lookback" in explicit):
        raise SystemExit("--splice-stage-lookback requires named user splice mode")
    if args.auto_random_splice and args.auto_objective == AUTO_OBJECTIVE_HIGHSCORE:
        raise SystemExit("--auto-random-splice requires --objective speedrun or an endpoint objective (not highscore)")
    if args.auto_random_splice and args.auto_splice_mode == "user":
        # These shared endpoint fields are defaults for each named Local goal,
        # even when Auto itself has the ordinary speedrun objective.
        return
    if args.auto_objective not in AUTO_OBJECTIVES:
        return
    incompatible = sorted(_AUTO_ENDPOINT_ONLY_OPTIONS & explicit)
    if incompatible:
        options = ", ".join("--" + name.replace("_", "-") for name in incompatible)
        raise SystemExit(
            f"{options} require an Auto endpoint objective "
            "(max-x, min-x, max-y, min-y, min-distance, earliest-arrival or earliest-interaction)"
        )


class _ConfigArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that applies TOML defaults before parsing the CLI."""

    def parse_args(self, args=None, namespace=None) -> argparse.Namespace:
        actual_args = list(sys.argv[1:] if args is None else args)
        config_paths = _find_option_paths(actual_args, "--config")
        splice_config_paths = _find_option_paths(actual_args, "--splice-config")
        goal_config_paths = _find_option_paths(actual_args, "--goal-config")
        command_parsers = getattr(self, "_command_parsers", {})
        mode = actual_args[0] if actual_args else None
        command_parser = command_parsers.get(mode)
        defaults = {}
        splice_overrides: set[str] = set()
        if command_parser is not None:
            try:
                # Preserve per-file precedence while keeping reusable
                # [multi-splicer] settings out of ordinary Auto campaigns.
                # Each layer is (regular settings, named-splicer settings).
                layers: list[tuple[dict[str, object], dict[str, object]]] = []
                for config_path in config_paths:
                    layers.append(_load_config_defaults(
                        config_path, command_parser, mode))
                if splice_config_paths:
                    if mode != "auto":
                        raise ValueError("--splice-config is only supported in auto mode")
                    for splice_config_path in splice_config_paths:
                        layer = _load_config_defaults(
                            splice_config_path, command_parser, mode)
                        layers.append(layer)
                        splice_overrides.update(layer[0])
                        splice_overrides.update(layer[1])

                # The shared settings may appear in examples/config.toml
                # without a files array; a later per-level --splice-config
                # supplies just that array. Do not activate the shared table
                # for unrelated Auto searches that never name splice files.
                named_splices = (mode == "auto" and (
                    any("auto_splice_files" in regular or
                        "auto_splice_files" in multi
                        for regular, multi in layers)
                    or any(token.split("=", 1)[0] == "--auto-splice-files"
                           for token in actual_args)))
                for regular, multi in layers:
                    defaults.update(regular)
                    if named_splices:
                        defaults.update(multi)

                if ("auto_splice_files" in splice_overrides
                        and "auto_splice_mode" not in splice_overrides):
                    # An explicitly selected named-splice config overrides
                    # unrelated random/physics defaults inherited from Auto.
                    defaults["auto_splice_mode"] = "user"
                if ("auto_splice_files" in splice_overrides
                        and "auto_random_splice" not in splice_overrides):
                    defaults["auto_random_splice"] = True
                if goal_config_paths:
                    if mode != "auto":
                        raise ValueError("--goal-config is only supported in auto mode")
                    for goal_config_path in goal_config_paths:
                        defaults.update(_load_local_goal_defaults(
                            goal_config_path, command_parsers["local"]))
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
        # Track command-line options separately from TOML-provided values.
        # A --rounds CLI override takes precedence over a stagnation value
        # supplied by a config file; explicit CLI --stagnation-rounds still wins.
        cli_explicit: set[str] = set()
        explicit = set(defaults)
        if command_parser is not None:
            option_destinations = {
                option: action.dest for action in command_parser._actions
                for option in action.option_strings
            }
            cli_explicit.update(
                option_destinations[token.split("=", 1)[0]]
                for token in actual_args
                if token.split("=", 1)[0] in option_destinations
            )
            explicit.update(cli_explicit)
        saved_action_defaults = (
            [(action, action.default) for action in command_parser._actions
             if action.dest in defaults] if command_parser is not None else []
        )
        saved_parser_defaults = dict(command_parser._defaults) if command_parser is not None else {}
        if command_parser is not None:
            command_parser.set_defaults(**defaults)
        try:
            result = super().parse_args(actual_args, namespace)
        finally:
            if command_parser is not None:
                command_parser._defaults.clear()
                command_parser._defaults.update(saved_parser_defaults)
                for action, default in saved_action_defaults:
                    action.default = default
        if command_parser is not None:
            for token in actual_args:
                option = token.split("=", 1)[0]
                if option.startswith("--") and option not in option_destinations:
                    matches = {destination for name, destination in option_destinations.items()
                               if name.startswith(option)}
                    if len(matches) == 1:
                        explicit.update(matches)
                        cli_explicit.update(matches)
        # A requested stagnation stop must not silently inherit the default
        # one-round cap.  A CLI stagnation limit overrides TOML rounds; an
        # explicit --rounds still caps the run when both CLI flags are given.
        # The same rule applies to a TOML-only stagnation limit without rounds.
        if mode == "local" and result.search == "population":
            if result.stagnation_rounds > 0 and (
                ("stagnation_rounds" in cli_explicit and "rounds" not in cli_explicit)
                or ("stagnation_rounds" in defaults and "rounds" not in defaults
                    and "rounds" not in cli_explicit)
            ):
                result.rounds = 0
            # An explicitly requested finite round count uses its full budget
            # unless stagnation is also explicitly selected at that level.
            elif result.rounds > 0 and (
                ("rounds" in cli_explicit and "stagnation_rounds" not in cli_explicit)
                or ("rounds" in defaults and "rounds" not in cli_explicit
                    and "stagnation_rounds" not in defaults)
            ):
                result.stagnation_rounds = 0
        if mode == "auto" and result.auto_splice_files:
            # A named file list is sufficient to activate the integrated
            # multi-splicer: no extra random-splice flag or mode is required.
            if "auto_splice_mode" not in explicit:
                result.auto_splice_mode = "user"
            if "auto_random_splice" not in explicit:
                result.auto_random_splice = True
        _validate_local_strategy(result, explicit)
        _validate_auto_goal_strategy(result, explicit)
        result._explicit_options = frozenset(explicit)
        result._cli_explicit_options = frozenset(cli_explicit)
        return result


def parse_splice_round_speeds(value: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise argparse.ArgumentTypeError("round-speeds requires comma-separated preset names")
    modes = tuple(mode.strip().lower() for mode in value.split(","))
    if not modes or any(mode not in ("current", "fast", "normal", "slow") for mode in modes):
        raise argparse.ArgumentTypeError("round-speeds requires current,fast,normal,slow")
    return modes


def parse_splice_files(value: str) -> tuple[str, ...]:
    """Named files only, not arbitrary paths; ordering is user-controlled."""
    if not isinstance(value, str):
        raise argparse.ArgumentTypeError("splice-files requires comma-separated names")
    names = tuple(name.strip() for name in value.split(","))
    if (not names or any(not name or name in (".", "..") or "/" in name or "\\" in name
                         for name in names) or len(set(names)) != len(names)):
        raise argparse.ArgumentTypeError("splice-files requires unique, nonempty filenames without paths")
    return names


def _resolve_named_splice_files(directory: Path, names: Sequence[str]) -> tuple[tuple[str, Path], ...]:
    """Resolve .txt/.toml Local goal configurations in the given order."""
    resolved = []
    for name in names:
        suffix = Path(name).suffix.lower()
        if suffix not in ("", ".txt", ".toml"):
            raise ValueError(f"unsupported splice file extension: {name}")
        candidates = ([directory / name] if suffix else
                      [directory / (name + ".txt"), directory / (name + ".toml")])
        found = [path for path in candidates if path.is_file()]
        if len(found) != 1:
            raise ValueError(f"splice {name!r}: expected exactly one .txt/.toml file in "
                             f"{directory}, found {len(found)}")
        resolved.append((name, found[0]))
    return tuple(resolved)


# These are the population-level knobs that can be applied to BOTH Auto and
# Local inside an individual named splice. The stage goal and the backend's
# optimization settings are independent of [multi-splicer] search="both".
_SPLICE_LOCAL_BACKEND_OPTIONS: dict[str, tuple[str, ...]] = {
    "iterations": ("iterations",),
    "beam": ("beam",),
    "mutation_span": ("endpoint_mutation_span", "local_mutation_span"),
    "repair_steps": ("endpoint_repair_steps", "local_repair_steps"),
    "repair_lookback": ("endpoint_repair_lookback", "local_repair_lookback"),
    "top_results": ("backend_top_results",),
    "workers": ("workers",),
}


def _named_splice_directory(args: argparse.Namespace) -> Path:
    """Use the identical directory for pre-level physics and stage goal loading."""
    explicit_directory = getattr(args, "auto_splice_directory", None)
    if explicit_directory is not None:
        return Path(explicit_directory)
    splice_config = getattr(args, "splice_config", None)
    if splice_config is None:
        option_paths = (_find_option_paths(sys.argv[1:], "--splice-config") or
                        _find_option_paths(sys.argv[1:], "--auto-splice-config"))
        splice_config = option_paths[-1] if option_paths else None
    if splice_config is not None:
        return Path(splice_config).parent
    input_value = getattr(args, "input", None)
    if input_value is None:  # lightweight unit-test namespaces
        return Path.cwd()
    input_path = Path(input_value)
    return input_path.parent.parent / "splices" / input_path.stem


def _load_named_splice_stages(level, frames, args, directory: Path, names: Sequence[str]):
    """Apply a Local file's goal and meaningful search overrides to each stage.

    Per-stage constraints are shared by Auto and Local. A Local file's
    ``search=population`` only documents its standalone Local strategy; it
    never overrides [multi-splicer] search="both". Options that cannot be
    honored by this managed search are rejected, not silently discarded.
    """
    from nv14_user_splice import UserSpliceStage, _materialise_splice_tail
    parser = build_parser()._command_parsers["local"]
    stages = []
    cli_explicit = getattr(args, "_cli_explicit_options", frozenset())
    # The full-run Level can have guards enabled for safety even when one
    # particular stage disables them. Each stage gets its own physics Level.
    shared_enemies = (True if getattr(args, "simulate_enemies", None) is None
                      else args.simulate_enemies)
    worlds = {level.simulate_enemies: level}
    for name, path in _resolve_named_splice_files(directory, names):
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
        for section in ("auto", "multi-splicer", "jump-pattern", "dump-player", "encode-video"):
            if section in raw and raw[section]:
                raise ValueError(f"splice {name!r} ({path}): [{section}] is not a Local stage; "
                                 "use [local] and the per-level [multi-splicer] file")
        local_values, _ = _load_config_defaults(path, parser, "local")
        values = {auto_key: local_values[local_key]
                  for local_key, auto_key in _LOCAL_GOAL_TO_AUTO.items()
                  if local_key in local_values}
        if "auto_objective" not in values or "auto_target_frame" not in values:
            raise ValueError(f"splice {name!r} ({path}) requires objective and target-frame")
        search = local_values.get("search", "population")
        if search != "population":
            raise ValueError(f"splice {name!r} ({path}): search={search!r} is not supported "
                             "in the named Auto/Local population multi-splicer")
        permitted = (set(_LOCAL_GOAL_TO_AUTO) | set(_SPLICE_LOCAL_BACKEND_OPTIONS) |
                     {"search", "rounds", "stagnation_rounds"})
        unsupported = sorted(set(local_values) - permitted)
        if unsupported:
            raise ValueError(f"splice {name!r} ({path}): unsupported per-splice "
                             f"option(s): {', '.join(unsupported)}; these cannot be "
                             "applied to both managed backends")
        stage_enemies = (shared_enemies if _splice_enemy_cli_explicit(args)
                         else local_values.get("simulate_enemies", shared_enemies))
        if stage_enemies not in worlds:
            worlds[stage_enemies] = parse_level_string(
                level.source_level_string, simulate_enemies=stage_enemies)
        stage_level = worlds[stage_enemies]
        stage_args = argparse.Namespace(**vars(args))
        # Shared values are defaults, not unrelated goals to be discarded.
        # Explicit stage options override inherited shared Auto goal values.
        vars(stage_args).update(values)
        overrides: dict[str, object] = {}
        for local_key, config_fields in _SPLICE_LOCAL_BACKEND_OPTIONS.items():
            if local_key not in local_values:
                continue
            # Explicit CLI backend options have higher precedence than TOML.
            cli_destinations = {
                "iterations": {"auto_splice_iterations"},
                "beam": {"beam"},
                "mutation_span": {"auto_mutation_span"},
                "repair_steps": {"auto_endpoint_repair_steps"},
                "repair_lookback": {"auto_endpoint_repair_lookback"},
                "workers": {"workers"},
            }.get(local_key, set())
            if cli_destinations & cli_explicit:
                continue
            for field in config_fields:
                overrides[field] = local_values[local_key]
        if "rounds" in local_values:
            if args.auto_splice_auto_stagnation_rounds or args.auto_splice_local_stagnation_rounds:
                raise ValueError(f"splice {name!r} ({path}): rounds is unused with "
                                 "independent Auto/Local stagnation; remove it")
            if "auto_splice_rounds" not in cli_explicit:
                overrides["splice_rounds"] = local_values["rounds"]
        if "stagnation_rounds" in local_values:
            # An explicit per-stage population patience overrides both backend
            # patience limits when [multi-splicer] search="both". This remains
            # a backend-round threshold, NEVER the older whole-cycle limit.
            patience = local_values["stagnation_rounds"]
            if "auto_splice_stagnation_rounds" not in cli_explicit:
                overrides["splice_stagnation_rounds"] = 0
            if (args.auto_splice_search in ("both", "endpoint-auto") and
                    "auto_splice_auto_stagnation_rounds" not in cli_explicit):
                overrides["splice_auto_stagnation_rounds"] = patience
            if (args.auto_splice_search in ("both", "local") and
                    "auto_splice_local_stagnation_rounds" not in cli_explicit):
                overrides["splice_local_stagnation_rounds"] = patience
        try:
            goal_frames = _materialise_splice_tail(frames, values["auto_target_frame"])
            goal, start, end = _auto_goal_from_options(stage_level, goal_frames, stage_args)
        except (ValueError, RuntimeError) as exc:
            raise ValueError(f"invalid splice {name!r} ({path}): {exc}") from exc
        stages.append(UserSpliceStage(name, goal, start,
                                      goal.target_frame if end is None else end,
                                      config_overrides=overrides,
                                      simulate_enemies=stage_enemies))
    return tuple(stages)


def parse_splice_interactions(value: str) -> tuple[str, ...]:
    """Parse the optional physics event kinds (TOML also accepts string arrays)."""
    if not isinstance(value, str):
        raise argparse.ArgumentTypeError("splice interactions must be comma-separated")
    choices = {"switch", "walljump", "landing", "bounceblock"}
    values = tuple(part.strip().lower() for part in value.split(","))
    if not values or any(part not in choices for part in values) or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError(
            "splice interactions must be unique names from switch, walljump, landing, bounceblock")
    return values


def _single_splice_both_arguments(argv: Sequence[str]) -> list[str]:
    """Adapt `both IN.ltm --goal-config goal.txt` to one named stage.

    This reuses multi-splicer's exact Auto/Local coordinator, checkpoint
    verification and independent backend stagnation instead of maintaining a
    second single-goal mutation engine. Explicit backend patience and run
    counts are respected; otherwise one complete until-stagnant pass is run.
    """
    command = list(argv)
    if not command or command[0] != "both":
        return command
    command[0] = "auto"
    goal = None
    for index, item in enumerate(tuple(command)):
        if item == "--goal-config" and index + 1 < len(command):
            goal = command[index + 1]
            del command[index:index + 2]
            break
        if item.startswith("--goal-config="):
            goal = item.split("=", 1)[1]
            command.remove(item)
            break
    if goal is None:
        raise SystemExit("both mode requires --goal-config SPLICE.txt")
    goal_path = Path(goal)
    if goal_path.suffix not in (".txt", ".toml"):
        raise SystemExit("both goal must be a named .txt or .toml Local goal file")
    command.extend(("--auto-splice-directory", str(goal_path.parent),
                    "--auto-splice-files", goal_path.stem,
                    "--auto-splice-search", "both"))
    explicit = {item.split("=", 1)[0] for item in command}
    for options, default in (
        (("--splice-auto-stagnation-rounds", "--auto-splice-auto-stagnation-rounds"), "5"),
        (("--splice-local-stagnation-rounds", "--auto-splice-local-stagnation-rounds"), "20"),
        (("--auto-runs",), "1"),
    ):
        if not any(option in explicit for option in options):
            command.extend((options[0], default))
    return command


def _expand_named_splice_alt_route(
    primary: Sequence[str], alternate: Sequence[str],
) -> tuple[str, ...]:
    """Expand a short alternative branch between two primary-route seams.

    ``[A, X, Y, B]`` replaces the primary stages strictly between A and B.
    Full routes ending in ``end`` retain their historical meaning.
    """
    primary, alternate = tuple(primary), tuple(alternate)
    if not alternate or alternate[-1] == "end":
        return alternate
    if len(alternate) < 3:
        raise ValueError("short alt-route must contain start seam, at least one "
                         "divergent splice, and end seam")
    if len(set(primary)) != len(primary) or len(set(alternate)) != len(alternate):
        raise ValueError("splice-files and short alt-route must not contain duplicate names")
    left, right = alternate[0], alternate[-1]
    if left not in primary or right not in primary:
        raise ValueError("short alt-route must start and end at names in splice-files "
                         f"(got {left!r} and {right!r})")
    start, stop = primary.index(left), primary.index(right)
    if stop <= start:
        raise ValueError("short alt-route end seam must follow its start seam "
                         "in splice-files")
    duplicate = [name for name in alternate[1:-1] if name in primary]
    if duplicate:
        raise ValueError("short alt-route divergent splices must not duplicate "
                         f"primary-route splices: {', '.join(duplicate)}")
    return primary[:start + 1] + alternate[1:-1] + primary[stop:]


def parse_arguments(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse CLI arguments, applying TOML defaults before explicit CLI values."""
    actual_argv = list(sys.argv[1:] if argv is None else argv)
    both_mode = bool(actual_argv and actual_argv[0] == "both")
    actual_argv = _single_splice_both_arguments(actual_argv)
    namespace = build_parser().parse_args(actual_argv)
    namespace._both_mode = both_mode
    if (getattr(namespace, "auto_splice_alt_route", ()) and
            getattr(namespace, "auto_splice_files", ())):
        try:
            namespace.auto_splice_alt_route = _expand_named_splice_alt_route(
                namespace.auto_splice_files, namespace.auto_splice_alt_route)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    if namespace.mode in {"dump-player", "encode-video"}:
        return namespace
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
            "Optimise an n v1.4 replay, dump player state, or encode video. Choose "
            "auto, local, both (single-goal Auto -> Local), jump-pattern, dump-player, or encode-video."
        )
    )
    subparsers = parser.add_subparsers(
        dest="mode",
        required=True,
        metavar="{auto,local,jump-pattern,dump-player,encode-video}",
        title="subcommands",
        description="select an optimisation strategy, player dump, or video export",
    )
    command_parsers = {
        "auto": subparsers.add_parser(
            "auto",
            help="autonomous whole-level speedrun/highscore search",
            description="Run autonomous whole-level speedrun/highscore search.",
        ),
        "local": subparsers.add_parser(
            "local",
            help="bounded window or population endpoint search",
            description=(
                "Optimise a bounded replay segment with sliding windows or an "
                "evolving population; level completion is not required."
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
        "--color", action=argparse.BooleanOptionalAction, default=True,
        help="show baselines in blue and verified new bests in green (default: enabled; --no-color disables)",
    )
    command.add_argument(
        "--levels-file",
        type=Path,
        help=(
            "N level database used to resolve the level data for an .ltm input"
        ),
    )
    command.add_argument(
        "--level-id",
        type=parse_ltm_level_id,
        metavar="NN-N",
        help=(
            "level identifier for an .ltm whose filename does not begin with "
            "an ID such as 00-0 or 00-0_rta; normally inferred from the filename"
        ),
    )
    command.add_argument(
        "--ltm-postroll",
        type=parse_nonnegative_int,
        metavar="N",
        help=(
            "for a raw .ltm, treat exactly N frames at the end of the active "
            "input log as post-roll instead of inferring all trailing N-idle "
            "frames; this boundary remains authoritative in Auto; use 0 to "
            "keep every post-Space frame in the replay"
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
        "--auto-endpoint-iterations", modes=auto_modes,
        type=parse_nonnegative_int, default=None, metavar="N",
        help=("per-worker proposal budget for Auto with Local-style goals; "
              "defaults to --iterations, does not affect full-run Auto"),
    )
    command.add_argument(
        "--auto-endpoint-iterations-per-frame", modes=auto_modes,
        type=parse_positive_finite_float, default=None, metavar="RATE",
        help=("Auto endpoint proposals per editable frame (inclusive); "
              "used when --auto-endpoint-iterations is unset, "
              "does not affect full-run Auto"),
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
        "--auto-stagnation-runs",
        modes=auto_modes,
        type=parse_nonnegative_int,
        default=0,
        metavar="N",
        help=(
            "stop after N consecutive completed Auto rounds without an "
            "objective gain or at least 0.5 px of exit-distance gain since "
            "the prior round; 0 disables this limit (default: 0)"
        ),
    )
    command.add_argument(
        "--auto-checkpoint",
        modes=auto_modes,
        type=Path,
        metavar="FILE",
        help=(
            "atomically save the complete committed Auto population and "
            "campaign state to FILE after every finished round"
        ),
    )
    command.add_argument(
        "--auto-resume",
        modes=auto_modes,
        action="store_true",
        help=(
            "resume a compatible existing --auto-checkpoint; if FILE does "
            "not yet exist, start a new checkpointed campaign"
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
        "--auto-objective", "--objective",
        modes=auto_modes, dest="auto_objective",
        choices=(*AUTO_OBJECTIVES, "max-x", "min-x", "max-y", "min-y", "min-distance", "earliest-arrival", "earliest-interaction"),
        default=AUTO_OBJECTIVE_SPEEDRUN,
        help=(
            "auto mode objective: speedrun minimises raw completion tick; "
            "highscore maximises gold bonus ticks minus completion tick "
            "(default: speedrun)"
        ),
    )
    command.add_argument(
        "--auto-random-splice", modes=auto_modes, action="store_true",
        help="switch-safe stochastic route waypoint splicing; requires completed speedrun",
    )
    command.add_argument("--auto-clean-air-jumps", modes=auto_modes,
                         action="store_true",
                         help="remove provably ineffective airborne Shift/jump pulses "
                              "from saved splice results; full replay trace is reverified")
    command.add_argument("--auto-splice-search", modes=auto_modes,
                         choices=("local", "endpoint-auto", "both"), default="local",
                         help="splice search: Local population (default), endpoint Auto Hybrid, or both (all splice modes; shared budget)")
    command.add_argument("--auto-splice-mode", modes=auto_modes,
                         choices=("random", "complexity", "physics", "user"), default="random",
                         help="waypoint selection: random (default), complexity boundaries, physical interactions, or user-named goal files")
    command.add_argument("--splice-alt-route", "--auto-splice-alt-route",
                         dest="auto_splice_alt_route", modes=auto_modes,
                         type=parse_splice_files, metavar="NAMES",
                         help="alternate named splice route, or short branch bounded by two "
                              "primary-route seam names; only divergent stages are searched")
    command.add_argument("--auto-splice-files", modes=auto_modes,
                         type=parse_splice_files, metavar="NAMES",
                         help="ordered comma-separated Local splice names; [auto] splice-files accepts a TOML array")
    command.add_argument("--auto-splice-directory", modes=auto_modes,
                         type=Path, metavar="DIR",
                         help="directory containing named .txt/.toml goals (default: ../splices/LEVEL relative to input)")
    command.add_argument("--splice-start", "--start-at-splice", "--auto-splice-start", dest="auto_splice_start",
                         modes=auto_modes, metavar="NAME",
                         help="first named splice to optimise (inclusive; earlier helper goals are non-binding)")
    command.add_argument("--splice-stop", "--auto-splice-stop", dest="auto_splice_stop",
                         modes=auto_modes, metavar="NAME",
                         help="last named splice to optimise (inclusive; completed outputs require canonical verification)")
    command.add_argument("--splice-from-best", dest="auto_splice_from_best",
                         modes=auto_modes, metavar="NAME",
                         help="seed from the best saved LTM/TXT for NAME and, by default, "
                              "search from the next splice; preserve the current verified "
                              "run as the final-score baseline")
    command.add_argument("--splice-merge-bests", dest="auto_splice_merge_bests",
                         modes=auto_modes, action="store_true",
                         help="attempt replay-verified joins of saved best checkpoints "
                              "across preceding named splices")
    command.add_argument("--splice-merge-verbose", dest="auto_splice_merge_verbose",
                         modes=auto_modes, action="store_true",
                         help="log every merge pairing/rejection (default: compact progress and saved gains)")
    command.add_argument("--splice-merge-only", dest="auto_splice_merge_only",
                         modes=auto_modes, action="store_true",
                         help="attempt verified merges of saved named-splice bests, "
                              "report rejected joins and saved gains, then exit "
                              "without Auto/Local search (implies --splice-merge-bests)")
    command.add_argument("--splice-merge-repair-only", dest="auto_splice_merge_repair_only",
                         modes=auto_modes, action="store_true",
                         help="standalone: try fast saved-route merges, then bounded Auto/Local "
                              "bridge repairs; save verified gains and exit (implies --splice-merge-only)")
    command.add_argument("--splice-merge-repair-at-end", dest="auto_splice_merge_repair_at_end",
                         modes=auto_modes, action="store_true",
                         help="run bounded bridge repairs after the final normal multi-splicer "
                              "merge pass (implies --splice-merge-bests)")
    command.add_argument("--splice-merge-repair-pairs", dest="auto_splice_merge_repair_pairs",
                         modes=auto_modes, type=parse_positive_int, default=48, metavar="N",
                         help="maximum independent source/suffix repair pairs per pass (default 48)")
    command.add_argument("--splice-merge-repair-window", dest="auto_splice_merge_repair_window",
                         modes=auto_modes, type=parse_positive_int, default=48, metavar="N",
                         help="editable bridge frames, independent of stage lookback (default 48)")
    command.add_argument("--splice-merge-repair-targets", dest="auto_splice_merge_repair_targets",
                         modes=auto_modes, type=parse_positive_int, default=2, metavar="N",
                         help="distinct physical suffix targets to try per pair (default 2)")
    command.add_argument("--splice-reference", dest="auto_splice_reference",
                         modes=auto_modes, type=Path, metavar="FILE",
                         help="completed same-level replay to use as a reference suffix "
                              "for verified merging of earlier gains")
    command.add_argument("--splice-each-best", dest="auto_splice_each_best",
                         modes=auto_modes, action="store_true",
                         help="also start every named splice from its own saved best checkpoint")
    command.add_argument("-l", "--ls-splice", "--ls-splices", dest="auto_ls_splice",
                         modes=auto_modes, action="store_true",
                         help="show saved named-splice checkpoint propagation summary and exit; "
                              "do not optimize, create or overwrite replay files")
    command.add_argument("--auto-splice-interactions", modes=auto_modes,
                         type=parse_splice_interactions,
                         default=("switch", "walljump", "landing"),
                         metavar="LIST", help="physics events, comma-separated; optional bounceblock (default switch,walljump,landing)")
    command.add_argument("--auto-splice-skip-probability", modes=auto_modes,
                         type=float, default=0.35, metavar="P",
                         help="probability of testing a route without each optional physics contact; never skip switches (default 0.35)")
    command.add_argument("--auto-splice-points", modes=auto_modes, type=int, default=5,
                         metavar="N", help="number of distinct random path waypoints per round; no extra control anchors (default 5)")
    command.add_argument("--auto-splice-frames-per-point", modes=auto_modes,
                         type=parse_positive_int, metavar="FRAMES",
                         help="derive waypoint count from current run length: approximately one per N frames, rounded half up; overrides --auto-splice-points")
    command.add_argument("--auto-splice-distance", modes=auto_modes, type=float,
                         metavar="PIXELS", help="sample every N pixels of travel instead of by count")
    command.add_argument("--auto-splice-radius", modes=auto_modes, type=float, default=16.0,
                         metavar="PIXELS", help="half-width/height of each waypoint rectangle (default 16)")
    command.add_argument("--auto-splice-lookback", modes=auto_modes, type=int, default=32,
                         metavar="N", help="seam matching and local mutation span; entire preceding waypoint interval is editable (default 32)")
    command.add_argument("--auto-splice-iterations", modes=auto_modes, type=int, default=400,
                         metavar="N", help="proposals per worker per waypoint search round (default 400)")
    command.add_argument("--auto-splice-repair-iterations", modes=auto_modes, type=int, default=250,
                         metavar="N", help="proposals per worker per continuation repair round (default 250)")
    command.add_argument("--auto-splice-rounds", modes=auto_modes, type=int, default=1,
                         metavar="N", help="fixed backend search rounds per waypoint (default 1); ignored when named-splice Auto/Local stagnation limits are set")
    command.add_argument("--splice-stagnation-rounds", "--auto-splice-stagnation-rounds",
                         dest="auto_splice_stagnation_rounds", modes=auto_modes,
                         type=int, default=0, metavar="N",
                         help="named multi-splicer: alternate Auto/Local until N consecutive cycles have no eligible stage improvement (0=legacy fixed rounds)")
    command.add_argument("--splice-live-save-best", dest="auto_splice_live_save_best",
                         modes=auto_modes, action="store_true",
                         help="verify and save each live stage improvement immediately "
                              "rather than throttle parent callbacks (costs CPU)")
    command.add_argument("--splice-auto-stagnation-rounds", "--auto-splice-auto-stagnation-rounds",
                         dest="auto_splice_auto_stagnation_rounds", modes=auto_modes,
                         type=int, default=0, metavar="N",
                         help="Auto phase stops after N consecutive Auto backend rounds without an eligible improvement")
    command.add_argument("--splice-local-stagnation-rounds", "--auto-splice-local-stagnation-rounds",
                         dest="auto_splice_local_stagnation_rounds", modes=auto_modes,
                         type=int, default=0, metavar="N",
                         help="Local phase stops after N consecutive Local backend rounds without an eligible improvement")
    command.add_argument("--splice-speed", "--auto-splice-speed", dest="auto_splice_speed",
                         modes=auto_modes, choices=("fast", "normal", "slow"),
                         help="set Auto/Local stagnation patience to fast=3/10, normal=5/20, slow=10/50")
    command.add_argument("--splice-round-speeds", "--auto-splice-round-speeds",
                         dest="auto_splice_round_speeds", modes=auto_modes,
                         type=parse_splice_round_speeds, default=(), metavar="MODES",
                         help="comma-separated speed schedule for outer rounds, e.g. current,slow")
    command.add_argument("--auto-splice-repair-rounds", modes=auto_modes, type=int, default=1,
                         metavar="N", help="backend search rounds PER continuation repair (default 1)")
    command.add_argument("--auto-splice-repair-anchors", modes=auto_modes, type=int, default=2,
                         metavar="N", help="subsequent waypoints to repair after a splice (default 2)")
    command.add_argument("--auto-splice-frontier", modes=auto_modes, type=int,
                         default=3, metavar="N",
                         help="max partial routes carried across waypoint segments (default 3, 0 disables)")
    command.add_argument("--splice-save-frontier", "--auto-splice-save-frontier",
                         dest="auto_splice_save_frontier", modes=auto_modes,
                         type=parse_positive_int, default=64, metavar="N",
                         help="named splices: persist up to N stage routes independently of active frontier (default 64, maximum 256)")
    command.add_argument("--splice-waypoint-lookback", "--auto-splice-waypoint-lookback",
                         dest="auto_splice_waypoint_lookback", modes=auto_modes,
                         type=parse_positive_int, default=1, metavar="N",
                         help="random/complexity/physics: retain preceding N sampled "
                              "waypoint frontiers (default 1 preserves old behavior)")
    command.add_argument("--splice-stage-lookback", "--auto-splice-stage-lookback",
                         dest="auto_splice_stage_lookback", modes=auto_modes,
                         type=parse_positive_int, default=2, metavar="N",
                         help="named multi-splicer: use up to N preceding stage frontiers as search seeds (default 2: n-1 and n-2)")
    command.add_argument("--auto-splice-exit-lookback", modes=auto_modes, type=int,
                         default=96, metavar="FRAMES",
                         help="minimum editable exit-approach horizon; overlaps nearby waypoints (default 96)")
    command.add_argument("--auto-splice-repair-searches", modes=auto_modes, type=int,
                         default=8, metavar="N",
                         help="maximum Local continuation repair searches per waypoint (default 8; 0 disables)")
    # Endpoint objectives share Local's native EndpointGoal and [goal] TOML.
    # Keep the existing completed-route speedrun/highscore CLI untouched.
    command.add_argument("--auto-target-frame", "--target-frame", modes=auto_modes, type=parse_nonnegative_int,
                         metavar="FRAME", help="endpoint objective deadline/frame (defaults to replay's last input)")
    command.add_argument("--auto-target-region", "--target-region", modes=auto_modes, type=parse_target_region,
                         metavar="XMIN:XMAX,YMIN:YMAX", help="earliest-arrival goal rectangle")
    command.add_argument("--auto-target-object", "--target-object", modes=auto_modes,
                         metavar="SELECTOR", help="min-distance or earliest-interaction object selector")
    command.add_argument("--auto-target-point", "--target-point", modes=auto_modes, type=parse_target_point,
                         metavar="X,Y", help="min-distance point")
    command.add_argument("--auto-arrival-start", "--arrival-start", modes=auto_modes, type=parse_nonnegative_int,
                         metavar="FRAME", help="first eligible earliest-goal frame")
    command.add_argument("--auto-secondary-objective", "--secondary-objective", modes=auto_modes,
                         choices=SECONDARY_OBJECTIVES, help="earliest goal velocity/position tie break")
    for _axis in ("x", "y", "vx", "vy"):
        command.add_argument("--auto-" + _axis + "-window", "--" + _axis + "-window", modes=auto_modes,
                             type=parse_axis_window, metavar="MIN:MAX",
                             help="inclusive endpoint constraint on " + _axis)
    command.add_argument("--auto-require-interaction", "--require-interaction", modes=auto_modes,
                         action="append", default=[], metavar="SELECTOR",
                         help="required persistent interaction at the endpoint")
    command.add_argument("--auto-require-reference-interactions", "--require-reference-interactions", modes=auto_modes,
                         action="store_true", help="require the source's persistent interactions at target-frame")
    command.add_argument("--auto-avoid-interaction", "--avoid-interaction", modes=auto_modes,
                         action="append", default=[], metavar="SELECTOR",
                         help="forbidden persistent interaction at the endpoint")
    command.add_argument("--auto-require-region", "--require-region", modes=auto_modes,
                         type=parse_target_region, metavar="XMIN:XMAX,YMIN:YMAX",
                         help="require the player to visit this inclusive rectangle")
    command.add_argument("--auto-require-region-frames", "--require-region-frames", modes=auto_modes,
                         type=parse_required_jump_frames, metavar="START:END",
                         help="inclusive interval to visit required region (default 0:target-frame)")
    command.add_argument("--auto-require-jump-region", "--require-jump-region", modes=auto_modes,
                         type=parse_target_region, metavar="XMIN:XMAX,YMIN:YMAX",
                         help="require a jump originating within this region")
    command.add_argument("--auto-require-jump-frames", "--require-jump-frames", modes=auto_modes,
                         type=parse_required_jump_frames, metavar="START:END",
                         help="eligible actual jump frames")
    command.add_argument("--auto-require-jumps", "--require-jumps", modes=auto_modes,
                         action="append", type=parse_required_jump_spec, default=[],
                         metavar="REGION@START:END", help="repeatable required actual jump (also TOML require-jumps list)")
    command.add_argument("--auto-require-drone-detection", "--require-drone-detection", modes=auto_modes,
                         action="append", default=[], metavar="drone:INDEX",
                         help="require the named drone to detect the player (repeatable)")
    command.add_argument("--auto-survive-after-goal", "--survive-after-goal", modes=auto_modes,
                         dest="auto_survive_after_goal", type=parse_nonnegative_int, default=0,
                         metavar="N", help="endpoint goal: reject replay if player dies in next N frames after objective")
    command.add_argument("--auto-require-drone-detection-frames", "--require-drone-detection-frames", modes=auto_modes,
                         type=parse_drone_detection_frames, metavar="START:END",
                         help="inclusive detection interval for all required drones")
    command.add_argument("--auto-completion-policy", modes=auto_modes,
                         choices=("checkpoint", "complete"), default="checkpoint",
                         help="endpoint search: allow a partial route or require a full verified finish")
    command.add_argument("--auto-mutation-span", modes=auto_modes, type=int,
                         default=24, help="maximum endpoint macro edit span")
    command.add_argument("--auto-mutations", "--splice-mutations", dest="auto_mutations",
                         modes=auto_modes, type=parse_auto_mutations, default="low",
                         metavar="PRESET|NAMES",
                         help="Auto route-scale operators: low (default), medium, high, "
                              "or comma-separated operator names; TOML arrays accepted")
    # Backward compatibility for existing TOMLs. Endpoint Auto always runs the
    # hybrid algorithm; the former legacy beam is no longer selectable.
    command.add_argument("--auto-endpoint-strategy", modes=auto_modes,
                         choices=("hybrid",), default="hybrid",
                         help=argparse.SUPPRESS)
    command.add_argument("--auto-endpoint-auto-mutation-share", modes=auto_modes,
                         type=float, default=0.5,
                         help="share of endpoint Hybrid proposals using Auto mutations "
                              "(0=Local only, 1=Auto only; default 0.5)")
    command.add_argument("--auto-progressive-refinement", modes=auto_modes,
                         action=argparse.BooleanOptionalAction, default=True,
                         help="interleave Hybrid Auto exploration with persistent Local refinement "
                              "(disable to restore the previous Hybrid search)")
    command.add_argument("--auto-refinement-share", modes=auto_modes,
                         type=float, default=0.25,
                         help="initial fraction of Auto endpoint proposals reserved for Local "
                              "refinement (default 0.25)")
    command.add_argument("--auto-adaptive-refinement", modes=auto_modes,
                         action=argparse.BooleanOptionalAction, default=True,
                         help="adapt the exploration/refinement split on verified gains")
    command.add_argument("--auto-refinement-cycle", modes=auto_modes,
                         type=int, default=128,
                         help="proposal slots per interleaved refinement cycle (default 128)")
    command.add_argument("--auto-refinement-polish", modes=auto_modes,
                         action=argparse.BooleanOptionalAction, default=True,
                         help="use budgeted single-frame sweeps around each verified new best "
                              "(default enabled; --no-auto-refinement-polish disables)")
    command.add_argument("--auto-refinement-chain-steps", modes=auto_modes,
                         type=int, default=32,
                         help="bounded Local-style multi-frame probes per promising mutation, "
                              "spent in existing Local proposal slots (0 disables; default 32)")
    command.add_argument("--auto-shared-refinement-proposals", modes=auto_modes,
                         type=int, default=0,
                         help="additional post-search worker proposals using a best result "
                              "shared during the same round (0 disables; original budget intact)")
    command.add_argument("--auto-performance-stats", modes=auto_modes,
                         action=argparse.BooleanOptionalAction, default=False,
                         help="log per-worker duplicates, packing, survivor fast-path and timings")
    command.add_argument("--auto-endpoint-repair-steps", modes=auto_modes, type=int,
                         default=32, help="maximum goal-guided repair proposals per mutation (shared budget)")
    command.add_argument("--auto-endpoint-repair-lookback", modes=auto_modes, type=int,
                         default=40, help="frames to search around mutations, deaths and required jumps")
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
        "--auto-repair-beam-width",
        modes=auto_modes,
        type=int,
        default=0,
        metavar="N",
        help="use native reward-guided repair beam of width N; 0 keeps DFS (default: 0)",
    )
    command.add_argument(
        "--auto-repair-cache-entries", modes=auto_modes,
        type=int, default=0, metavar="N",
        help="memoize up to N completed identical native repairs per worker (0 disables; max 64)",
    )
    command.add_argument(
        "--auto-adaptive-repair-windows", modes=auto_modes,
        action="store_true",
        help="try short local repair horizons before longer ones with one shared tick budget",
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
        "--auto-splice-plans-per-pair",
        modes=auto_modes,
        type=parse_positive_int,
        default=2,
        metavar="N",
        help=(
            "maximum ranked sectional splice plans attempted for each "
            "ordered recipient/donor pair; larger values can expose lower-"
            "ranked productive splices but increase repair work (default: 2)"
        ),
    )
    command.add_argument(
        "--auto-auxiliary-beam-seeds",
        modes=auto_modes,
        type=parse_nonnegative_int,
        default=1,
        metavar="N",
        help=(
            "maximum promising rejected splice-repair candidates seeded "
            "into one next-round child beam per surviving recipient; "
            "includes normal corridors and junctions; 0 disables "
            "(default: 1)"
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
            "frames; omit END to follow each current verified replay/search "
            "workspace (default: complete verified replay)"
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
        modes=jump_pattern_modes,
        choices=("max-x", "min-x", "max-y", "min-y", "min-distance"),
        default="max-x",
    )
    command.add_argument(
        "--objective", modes=local_modes,
        choices=("max-x", "min-x", "max-y", "min-y", "min-distance", "earliest-arrival", "earliest-interaction"),
        default="max-x",
    )
    command.add_argument(
        "--search", modes=local_modes, choices=("windows", "population"),
        default="windows", help="local search strategy (default: windows)",
    )
    command.add_argument(
        "--local-beam-width", "--beam-width", modes=local_modes,
        dest="local_beam_width", type=int, default=0, metavar="N",
        help="windows only: native reward-guided beam width; 0 uses original DFS (default: 0)",
    )
    command.add_argument(
        "--local-search-cache-entries", "--search-cache-entries", modes=local_modes,
        dest="local_search_cache_entries", type=int, default=0, metavar="N",
        help="windows only: cache up to N identical complete native searches per run (0 disables, max 64)",
    )
    command.add_argument(
        "--local-adaptive-windows", "--adaptive-windows", modes=local_modes,
        dest="local_adaptive_windows", action="store_true",
        help="windows only: search short trailing subsets before each full window with a shared tick budget",
    )
    command.add_argument(
        "--local-search-ticks", modes=local_modes, type=int, default=0, metavar="N",
        help="windows only: native simulation ceiling per window; 0 is unlimited unless adaptive (default: 20000)",
    )
    for option, default, help_text in (
        ("iterations", 10000, "proposal budget per worker per population round"),
        ("beam", 32, "maximum retained population candidates"),
        ("rounds", 1, "population rounds; explicit positive count disables default stagnation stopping"),
        ("stagnation-rounds", 20, "stop after this many rounds without primary or configured secondary objective gain; 0 disables; explicitly setting it restores early stopping with --rounds"),
        ("repair-steps", 64, "goal-aware repair proposals per selected failed candidate; 0 disables"),
        ("repair-lookback", 32, "maximum repair lookback, clipped to editable ranges"),
        ("mutation-span", 32, "maximum pulse or bounded section length"),
        ("top-results", 1, "number of diverse feasible output replays, best first"),
    ):
        command.add_argument("--" + option, modes=local_modes, type=int, default=default,
                             metavar="N", help=f"population only: {help_text} (default: {default})")
    command.add_argument("--checkpoint", modes=local_modes, type=Path, metavar="FILE",
                         help="population only: save campaign state at completed round boundaries")
    command.add_argument("--resume", modes=local_modes, action="store_true",
                         help="population only: resume --checkpoint after validating seed, level and goal")
    command.add_argument("--vx-window", modes=local_modes, type=parse_axis_window,
                         metavar="MIN:MAX", help="inclusive endpoint horizontal velocity bounds (windows and population)")
    command.add_argument("--vy-window", modes=local_modes, type=parse_axis_window,
                         metavar="MIN:MAX", help="inclusive endpoint vertical velocity bounds (windows and population)")
    command.add_argument("--target-region", modes=local_modes, type=parse_target_region,
                         metavar="XMIN:XMAX,YMIN:YMAX", help="earliest-arrival population goal: inclusive target rectangle")
    command.add_argument("--require-region", modes=local_modes, type=parse_target_region,
                         metavar="XMIN:XMAX,YMIN:YMAX",
                         help="population only: player must visit this rectangle within the required interval")
    command.add_argument("--require-region-frames", modes=local_modes, type=parse_required_jump_frames,
                         metavar="START:END", help="population only: inclusive visit interval")
    command.add_argument("--require-jump-region", modes=local_modes, type=parse_target_region,
                         metavar="XMIN:XMAX,YMIN:YMAX",
                         help="population only: require an actual jump originating inside this inclusive rectangle")
    command.add_argument("--require-jump-frames", modes=local_modes, type=parse_required_jump_frames,
                         metavar="START:END",
                         help="population only: inclusive jump interval (default: first editable frame through target-frame)")
    command.add_argument("--require-jumps", modes=local_modes, action="append",
                         type=parse_required_jump_spec, default=[], metavar="REGION@START:END",
                         help="population only: repeatable actual jump constraints (also TOML require-jumps list)")
    command.add_argument("--require-drone-detection", modes=local_modes,
                         action="append", default=[], metavar="drone:INDEX",
                         help="population only: require named drone acquisition (repeatable)")
    command.add_argument("--survive-after-goal", modes=local_modes,
                         type=parse_nonnegative_int, default=0, metavar="N",
                         help="population only: require survival for N frames after the objective")
    command.add_argument("--require-drone-detection-frames", modes=local_modes,
                         type=parse_drone_detection_frames, metavar="START:END",
                         help="population only: inclusive required detection interval")
    command.add_argument("--arrival-start", modes=local_modes, type=parse_nonnegative_int,
                         metavar="FRAME", help="first eligible arrival or interaction frame (default: first editable frame)")
    command.add_argument("--secondary-objective", modes=local_modes,
                         choices=SECONDARY_OBJECTIVES, default=None,
                         help="earliest-arrival/earliest-interaction population only: tie-break at equal endpoint frames; min-exit-distance requires an exit-door earliest-interaction goal (default: none)")
    command.add_argument(
        "--target-object",
        modes=fixed_frame_modes,
        metavar="SELECTOR",
        help=(
            "min-distance anchor or earliest-interaction object: TYPE, TYPE:INDEX, "
            "TYPE:INDEX.ANCHOR or TYPE:any; exits support .door/.switch; "
            "interaction targets support gold, switches, locked doors, trapdoors and exit completion"
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
            "randomized local repair traversal; auto and local population accept 'random' to "
            "choose and print a fresh 64-bit seed once per run, otherwise auto "
            "defaults to 0; window search generates and prints one when needed"
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
            "TOML defaults file; repeat --config to layer files left-to-right "
            "(later values win); command-line options override all files"
        ),
    )
    command.add_argument(
        "--splice-config",
        modes=auto_modes,
        type=Path,
        metavar="MULTI_SPLICER.toml",
        help=(
            "additional named multi-splicer TOML applied after --config "
            "(use [multi-splicer] for splice-files and per-run overrides; "
            "old [auto] splice files are also supported); CLI flags win"
        ),
    )
    command.add_argument(
        "--goal-config",
        modes=auto_modes,
        type=Path,
        metavar="LOCAL_SPLICE.toml",
        help=(
            "Auto endpoint goal from an unchanged [local] splice TOML; "
            "only goal, range and enemy-simulation keys are imported, "
            "overriding --config defaults but not explicit CLI switches"
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
            "default in auto and local population; disabled in local windows and jump-pattern"
        ),
    )
    enemy_group.add_argument(
        "--no-simulate-enemies",
        dest="simulate_enemies",
        action="store_false",
        default=None,
        help="disable supported enemy simulation (overrides the auto-mode default)",
    )
    from nv14_dump import add_player_dump_arguments

    dump_parser = subparsers.add_parser(
        "dump-player", help="dump native player/visual state to CSV",
        description="Write one post-tick player/visual CSV row through completion, death, or input end.",
    )
    add_player_dump_arguments(dump_parser)
    command_parsers["dump-player"] = dump_parser
    from nv14_video import add_video_arguments

    video_parser = subparsers.add_parser(
        "encode-video", help="render a native replay to a silent MP4 (optional Pillow + FFmpeg)",
        description="Render the level, animated ninja and live native objects through completion, death, or input end.",
    )
    add_video_arguments(video_parser)
    command_parsers["encode-video"] = video_parser
    return parser


def _ranked_output_path(path: Path, rank: int) -> Path:
    return path if rank == 1 else path.with_name(f"{path.stem}.rank{rank:02d}{path.suffix}")



def _user_splice_output_paths(
    stage_names: Sequence[str],
    output_path: Path,
    replay_output_path: Path | None,
    *,
    protected_paths: Sequence[tuple[str, Path | None]] = (),
) -> dict[str, tuple[Path, Path | None]]:
    """Separate trial checkpoints beside final output, one per named splice.

    Names may explicitly include .txt/.toml, but the output label always uses
    the filename's stem. Detect collisions before running any searches, so a
    stage checkpoint cannot overwrite the input, config, or main result.
    """
    # When --replay-output is not specified, keep the LTM movie AND a TXT
    # companion for each temporary checkpoint; don't alter final output.
    if replay_output_path is None and output_path.suffix.lower() == ".ltm":
        replay_output_path = output_path.with_suffix(".txt")
    destinations: dict[str, tuple[Path, Path | None]] = {}
    occupied: list[tuple[str, Path | None]] = [
        ("final output", output_path),
        ("final replay output", replay_output_path),
        *protected_paths,
    ]
    for name in stage_names:
        label = Path(name).stem if Path(name).suffix.lower() in (".txt", ".toml") else name
        if not label or label in (".", "..") or "/" in label or "\\" in label:
            raise ValueError(f"invalid named splice output label: {name!r}")
        main_path = output_path.with_name(f"{output_path.stem}_{label}{output_path.suffix}")
        replay_path = (replay_output_path.with_name(
            f"{replay_output_path.stem}_{label}{replay_output_path.suffix}")
            if replay_output_path is not None else None)
        for title, candidate in ((f"splice {name!r} output", main_path),
                                 (f"splice {name!r} replay output", replay_path)):
            if candidate is None:
                continue
            if candidate.exists() and candidate.is_dir():
                raise ValueError(f"{title} must be a file: {candidate}")
            for other_title, other_path in occupied:
                if other_path is not None and _paths_alias(candidate, other_path):
                    raise ValueError(f"{title} and {other_title} must be different files: {candidate}")
            occupied.append((title, candidate))
        destinations[name] = main_path, replay_path
    return destinations


def _atomic_write_binary(path: Path, data: bytes) -> None:
    """Atomically copy an already-serialized LTM to an alias checkpoint."""
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.",
                                         suffix=".tmp", delete=False) as file:
            temp = Path(file.name)
            file.write(data)
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _user_splice_alias_ltm_path(
    output_path: Path, replay_output_path: Path | None, name: str,
) -> Path | None:
    """An LTM named like the TXT companion, in addition to optim_STAGE.ltm."""
    if output_path.suffix.lower() != ".ltm" or replay_output_path is None:
        return None
    label = Path(name).stem if Path(name).suffix.lower() in (".txt", ".toml") else name
    alias = replay_output_path.with_name(f"{replay_output_path.stem}_{label}.ltm")
    primary = output_path.with_name(f"{output_path.stem}_{label}.ltm")
    return None if _paths_alias(alias, primary) else alias


def _user_splice_frontier_path(main_path: Path) -> Path:
    """Compact, atomic sidecar beside the existing best-stage checkpoint."""
    return main_path.with_suffix(".frontier.json")


def _user_splice_frontier_identity(level: Level, stage) -> dict[str, object]:
    enabled = level.simulate_enemies if stage.simulate_enemies is None else stage.simulate_enemies
    return {
        "version": 1,
        "level_sha256": hashlib.sha256(
            (level.source_level_string or "").encode("utf-8")).hexdigest(),
        "stage": stage.name,
        "range": [stage.start, stage.end],
        "goal": repr(stage.goal),
        "simulate_enemies": enabled,
    }


def _load_user_splice_frontiers(
    level: Level, stages, stage_outputs: Mapping[str, tuple[Path, Path | None]],
) -> dict[str, tuple[tuple[InputFrame, ...], ...]]:
    """Restore only matching stage/level populations, never trust raw scores."""
    restored = {}
    for stage in stages:
        path = _user_splice_frontier_path(stage_outputs[stage.name][0])
        if not path.exists():
            continue
        try:
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("frontier checkpoint exceeds 16 MiB")
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or document.get("version") != 1:
                raise ValueError("unknown frontier checkpoint format")
            expected = _user_splice_frontier_identity(level, stage)
            if any(document.get(key) != value for key, value in expected.items()):
                print(f"[auto:user-splice:resume] {stage.name!r}: "
                      "skipped frontier for changed level or splice settings", flush=True)
                continue
            replay_strings = document.get("replays")
            if not isinstance(replay_strings, list) or len(replay_strings) > 256 or not all(
                    isinstance(value, str) for value in replay_strings):
                raise ValueError("invalid frontier replay list")
            entries = []
            for record in replay_strings:
                frames = tuple(editable_frames(decode_complex_replay(record).frames))
                if frames not in entries:
                    entries.append(frames)
            restored[stage.name] = tuple(entries)
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            print(f"[auto:user-splice:resume] skipping unreadable frontier "
                  f"{path}: {exc}", flush=True)
    return restored


def _protect_unreadable_splice_output(path: Path | None) -> None:
    """Back up unreadable old checkpoints *when* replacing them, not on load."""
    if path is None or not path.is_file():
        return
    try:
        if path.suffix.lower() == ".ltm":
            LtmMovie.load(path)
        else:
            record = path.read_text(encoding="utf-8").strip()
            try:
                decode_complex_replay(record)
            except (TypeError, ValueError):
                decode_complex_replay(parse_combined_level_replay(record).replay_string)
    except (OSError, UnicodeError, ValueError, LtmError):
        backup = path.with_name(path.name + ".unverified.bak")
        if not backup.exists():
            _atomic_write_binary(backup, path.read_bytes())
        print(f"[auto:user-splice:resume] preserved unreadable old checkpoint "
              f"at {backup}", flush=True)


def _load_user_splice_checkpoints(
    stage_outputs: dict[str, tuple[Path, Path | None]],
    output_path: Path,
    replay_output_path: Path | None,
) -> dict[str, tuple[tuple[InputFrame, ...], ...]]:
    """Read all existing stage files, allowing older and newer output names.

    An unreadable existing checkpoint is an error: overwriting an unknown
    previous score would violate the never-regress checkpoint guarantee.
    """
    checkpoints: dict[str, tuple[tuple[InputFrame, ...], ...]] = {}
    for name, (main, replay) in stage_outputs.items():
        alias = _user_splice_alias_ltm_path(output_path, replay_output_path, name)
        candidates: list[tuple[InputFrame, ...]] = []
        seen_paths: set[Path] = set()
        for path in (main, alias, replay):
            if path is None or not path.exists() or path.resolve() in seen_paths:
                continue
            seen_paths.add(path.resolve())
            try:
                if path.suffix.lower() == ".ltm":
                    frames = LtmMovie.load(path).replay_frames
                else:
                    text = path.read_text(encoding="utf-8").strip()
                    try:
                        frames = decode_complex_replay(text).frames
                    except (ValueError, TypeError):
                        frames = decode_complex_replay(
                            parse_combined_level_replay(text).replay_string).frames
            except (OSError, UnicodeError, ValueError, LtmError) as exc:
                print(f"[auto:user-splice:resume] skipping unreadable stage "
                      f"checkpoint {path}: {exc}", flush=True)
                continue
            canonical = tuple(editable_frames(frames))
            if canonical not in candidates:
                candidates.append(canonical)
        if candidates:
            checkpoints[name] = tuple(candidates)
    return checkpoints


def _population_output_paths(
    config: LocalConfig,
    *,
    input_path: Path,
    output_path: Path,
    replay_output_path: Path | None,
    levels_file_path: Path | None = None,
    config_path: Path | None = None,
) -> tuple[tuple[Path, Path | None], ...]:
    """Check every possible ranked destination before any checkpoint is saved."""
    destinations = tuple(
        (_ranked_output_path(output_path, rank),
         _ranked_output_path(replay_output_path, rank) if replay_output_path is not None else None)
        for rank in range(1, config.top_results + 1)
    )
    protected = [("input", input_path), ("levels file", levels_file_path),
                 ("TOML configuration", config_path)]
    outputs = []
    for rank, (main_path, packed_path) in enumerate(destinations, 1):
        outputs.append((f"rank {rank} output", main_path))
        if packed_path is not None:
            outputs.append((f"rank {rank} replay output", packed_path))
    if config.checkpoint_path is not None:
        outputs.append(("population checkpoint", config.checkpoint_path))
    for index, (label, path) in enumerate(outputs):
        if path.exists() and path.is_dir():
            raise ValueError(f"{label} must be a file: {path}")
        for other_label, other_path in protected + outputs[:index]:
            if other_path is not None and _paths_alias(path, other_path):
                raise ValueError(f"{label} and {other_label} must be different files: {path}")
    return destinations


def _run_local_population(
    source: _LoadedSource,
    level: Level,
    frames: Sequence[InputFrame],
    config: LocalConfig,
    *,
    input_path: Path,
    output_path: Path,
    replay_output_path: Path | None,
    config_path: Path | None = None,
    color: bool = True,
) -> None:
    """Dispatch bounded population search independently of Local's window loop."""
    from nv14_endpoint import EndpointGoal, RequiredJump, verify_endpoint
    from nv14_population import PopulationConfig, optimise_local_population
    from nv14_replay import simulate_through_frame

    target_frame = config.target_frame
    if target_frame is None or not 0 <= target_frame < len(frames):
        raise SystemExit(f"target frame must be between 0 and {len(frames) - 1}")
    try:
        ranges = parse_frame_ranges(config.frame_range or f"0:{target_frame}", target_frame=target_frame)
        destinations = _population_output_paths(
            config, input_path=input_path, output_path=output_path,
            replay_output_path=replay_output_path, levels_file_path=source.levels_file_path,
            config_path=config_path,
        )
        target = None
        interaction_target = None
        if config.objective == "min-distance":
            if (config.target_object is None) == (config.target_point is None):
                raise ValueError("--objective min-distance requires exactly one of --target-object or --target-point")
            target = (resolve_target_object(level, config.target_object)
                      if config.target_object is not None else target_from_point(config.target_point))
        elif config.objective == "earliest-interaction":
            interaction_target = resolve_interaction_target(level, config.target_object)
        required = tuple(resolve_interaction_requirement(level, selector) for selector in config.require_interaction)
        if config.require_reference_interactions:
            reference_state = simulate_through_frame(level, frames, target_frame)
            required = merge_interaction_requirements(
                required, reference_interaction_requirements(level, reference_state),
            )
        avoided = merge_interaction_avoidances(tuple(
            resolve_interaction_avoidance(level, selector) for selector in config.avoid_interaction
        ))
        goal = EndpointGoal(
            target_frame=target_frame, objective=config.objective, target=target,
            x_window=config.x_window, y_window=config.y_window,
            vx_window=config.vx_window, vy_window=config.vy_window,
            target_region=config.target_region,
            arrival_start=(config.arrival_start if config.arrival_start is not None else ranges[0][0])
            if config.objective in EARLIEST_OBJECTIVES else 0,
            required_interactions=required, avoided_interactions=avoided,
            secondary_objective=config.secondary_objective,
            interaction_target=interaction_target,
            required_jumps=config.required_jumps,
            require_region=config.require_region,
            require_region_frames=config.require_region_frames,
            required_drone_detections=_resolve_drone_detection(level, config.require_drone_detection),
            require_drone_detection_frames=config.require_drone_detection_frames,
            survive_after_goal=config.survive_after_goal,
            require_jump_region=config.require_jump_region,
            require_jump_frames=(config.require_jump_frames or (ranges[0][0], target_frame))
            if config.require_jump_region is not None else None,
        )
        search_config = PopulationConfig(
            iterations=config.iterations, beam=config.beam, rounds=config.rounds,
            stagnation_rounds=config.stagnation_rounds, workers=config.workers,
            seed=config.seed, top_results=config.top_results,
            repair_steps=config.repair_steps, repair_lookback=config.repair_lookback,
            mutation_span=config.mutation_span, checkpoint_path=config.checkpoint_path,
            resume=config.resume,
        )
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    original = tuple(frames)
    mutable = {frame for start, end in ranges for frame in range(start, end + 1)}
    checkpoint_written = False

    def verified_candidate(candidate):
        replay_string = encode_complex_replay(candidate.frames)
        packed = decode_complex_replay(replay_string).frames
        if len(packed) != len(original):
            raise ValueError("population output changed the replay length")
        for index, (before, after) in enumerate(zip(original, packed)):
            if index not in mutable and (before.left, before.right, before.jump) != (after.left, after.right, after.jump):
                raise ValueError(f"population output changed held input outside --range at frame {index}")
        evaluation = verify_endpoint(
            level, packed, goal, expected=candidate.evaluation,
            python_resimulate=config.python_resimulate,
        )
        if not evaluation.feasible:
            raise ValueError("population output does not satisfy the endpoint goal")
        return replay_string, packed, evaluation

    def secondary_summary(evaluation) -> str:
        if config.secondary_objective is None or not evaluation.feasible:
            return ""
        return f"; secondary {config.secondary_objective}={evaluation.secondary_value:.15g}"

    def interaction_summary(evaluation) -> str:
        summary = ("; interaction=" + ",".join(atom.label for atom in evaluation.interaction_events)
                   if evaluation.interaction_events else "")
        if goal.required_jumps:
            for index, event in enumerate(evaluation.jump_events, 1):
                summary += (f"; required jump {index} missing" if event is None else
                            f"; required jump {index} at frame {event[0]}")
        if goal.require_jump_region is not None:
            if evaluation.jump_event is None:
                summary += "; required jump missing"
            else:
                frame, x, y = evaluation.jump_event
                summary += f"; required jump at frame {frame}, origin ({x:.12g}, {y:.12g})"
        return summary

    def save_best(candidate) -> bool:
        nonlocal checkpoint_written
        replay_string, _packed, evaluation = verified_candidate(candidate)
        _write_result(source, output_path, replay_output_path, replay_string)
        checkpoint_written = True
        _print_best_line(
            f"[local:best] frame {evaluation.frame}; score {evaluation.score:.15g}; "
            f"position ({evaluation.x:.12g}, {evaluation.y:.12g}); "
            f"velocity ({evaluation.vx:.12g}, {evaluation.vy:.12g})"
            f"{secondary_summary(evaluation)}{interaction_summary(evaluation)}",
            color=color,
        )
        return True

    try:
        result = optimise_local_population(
            level, frames, goal=goal, frame_ranges=ranges, config=search_config,
            best_callback=save_best,
            progress=lambda message: (
                _print_baseline_line(message, color=color)
                if message.startswith("[local:population:baseline]")
                else _print_best_line(message, color=color)
                if message.endswith(" [NEW BEST SO FAR]")
                else print(message, flush=True)
            ),
        )
        if not result.candidates:
            if result.interrupted:
                # Ctrl+C before a feasible result exists is still an interrupt,
                # not a failed optimisation. Do not touch any prior output.
                print("population search interrupted; no feasible endpoint found; "
                      "existing output retained", flush=True)
                raise SystemExit(130)
            raise ValueError("no feasible endpoint candidate was found")
        # Verify every ranked replay before publishing the final result set.
        verified = [(candidate, *verified_candidate(candidate)) for candidate in result.candidates[:config.top_results]]
    except (RuntimeError, ValueError) as exc:
        status = ("the most recent verified best replay remains on disk" if checkpoint_written
                  else "no output was written")
        raise SystemExit(f"{exc}; {status}") from exc

    print()
    baseline = result.baseline
    _print_baseline_line(
        f"baseline frame {baseline.frame}: score={baseline.score:.15g}; "
        f"position=({baseline.x:.15g}, {baseline.y:.15g}); "
        f"velocity=({baseline.vx:.15g}, {baseline.vy:.15g}); feasible={baseline.feasible}"
        f"{secondary_summary(baseline)}{interaction_summary(baseline)}",
        color=color,
    )
    print(f"local population: objective={config.objective}; rounds={result.rounds}; "
          f"evaluations={result.evaluations}; feasible outputs={len(verified)}/{config.top_results}")
    if config.objective == "earliest-arrival":
        print(f"arrival region: {config.target_region}; eligible frames {goal.arrival_start}:{target_frame}; "
              "position, velocity and interaction constraints apply at the arrival frame")
    elif config.objective == "earliest-interaction":
        print(f"interaction target: {interaction_target.selector}; eligible frames {goal.arrival_start}:{target_frame}; "
              "position, velocity and route constraints apply on a fresh interaction tick")
        print("resolved interaction targets: " + ", ".join(atom.label for atom in interaction_target.alternatives))
    else:
        print(f"endpoint verification through frame {target_frame}; later replay inputs retained")
    if config.objective in EARLIEST_OBJECTIVES and config.secondary_objective is not None:
        label = "interaction" if interaction_target is not None else "arrival"
        print(f"{label} tie-break: {config.secondary_objective}, then fewer changed frames, then encoded inputs")
    for index, requirement in enumerate(goal.required_jumps, 1):
        print(f"required jump {index}: region={requirement.region}; eligible frames "
              f"{requirement.frames[0]}:{requirement.frames[1]}")
    if goal.require_jump_region is not None:
        print(f"required jump region: {goal.require_jump_region}; eligible frames "
              f"{goal.require_jump_frames[0]}:{goal.require_jump_frames[1]} (jump origin, inclusive)")
    if required:
        print("required interactions satisfied: " + format_interaction_requirements(required))
    if avoided:
        print("forbidden interactions avoided: " + format_interaction_avoidances(avoided))
    for rank, ((_candidate, replay_string, packed, evaluation), (main_path, packed_path)) in enumerate(zip(verified, destinations), 1):
        _write_result(source, main_path, packed_path, replay_string)
        changed = changed_frame_indices(original, packed)
        print(f"  {rank}. frame={evaluation.frame}; score={evaluation.score:.15g}; "
              f"position=({evaluation.x:.15g}, {evaluation.y:.15g}); "
              f"velocity=({evaluation.vx:.15g}, {evaluation.vy:.15g}); changed frames={len(changed)}"
              f"{secondary_summary(evaluation)}{interaction_summary(evaluation)}")
        print(f"wrote {main_path}")
        if packed_path is not None:
            print(f"wrote {packed_path}")
    if getattr(result, "interrupted", False):
        print("population search interrupted; saved the best verified results")
        raise SystemExit(130)


def _resolve_drone_detection(level, selectors: Sequence[str]) -> tuple[int, ...]:
    """Resolve drone:N as the Nth type-6 object, not a native scene id."""
    if not selectors:
        return ()
    if not getattr(level, "simulate_enemies", False):
        raise ValueError("require-drone-detection needs simulate-enemies = true for this stage")
    descriptors = (level.object_descriptors() if hasattr(level, "object_descriptors") else
                   ({"object_type": spec.obj_type, "load_index": spec.load_index}
                    for spec in level.all_specs))
    drones = [int(item["load_index"]) for item in descriptors if item["object_type"] == 6]
    result = []
    for selector in selectors:
        selector = selector.strip().lower()
        if selector == "drone":
            if len(drones) != 1:
                raise ValueError("drone is ambiguous: use drone:N")
            index = 0
        elif selector.startswith("drone:") and selector[6:].isdigit():
            index = int(selector[6:])
        else:
            raise ValueError(f"require-drone-detection needs a drone:N selector, got {selector!r}")
        if index >= len(drones):
            raise ValueError(f"drone:{index} does not exist (level has {len(drones)} drones)")
        result.append(drones[index])
    if len(result) != len(set(result)):
        raise ValueError("require-drone-detection contains duplicate drones")
    return tuple(result)


def _auto_goal_from_options(level: Level, replay_frames: Sequence[InputFrame],
                            args: argparse.Namespace) -> tuple[EndpointGoal, int, int | None]:
    """Resolve Auto/--goal-config endpoint options identically for all searches."""
    frame = (len(replay_frames) - 1 if args.auto_target_frame is None
             else args.auto_target_frame)
    if not 0 <= frame < len(replay_frames):
        raise ValueError("auto target-frame must lie inside the replay")
    start, end = parse_auto_frame_range(args.frame_range, target_frame=frame)
    if end is not None and end > frame:
        raise ValueError("auto endpoint range must not extend beyond target-frame")
    if args.auto_objective == "min-distance":
        if (args.auto_target_object is None) == (args.auto_target_point is None):
            raise ValueError("min-distance requires exactly one of target-object or target-point")
        target = (resolve_target_object(level, args.auto_target_object)
                  if args.auto_target_object is not None else target_from_point(args.auto_target_point))
    else:
        if args.auto_target_point is not None or (args.auto_target_object is not None
                and args.auto_objective != "earliest-interaction"):
            raise ValueError("target-point/object requires min-distance or earliest-interaction")
        target = None
    if args.auto_objective == "earliest-interaction" and args.auto_target_object is None:
        raise ValueError("earliest-interaction requires target-object")
    if args.auto_arrival_start is not None and args.auto_objective not in EARLIEST_OBJECTIVES:
        raise ValueError("arrival-start requires earliest-arrival or earliest-interaction")
    if args.auto_require_jumps and args.auto_require_jump_region is not None:
        raise ValueError("require-jumps cannot be combined with require-jump-region")
    if args.auto_require_jump_frames is not None and args.auto_require_jump_region is None:
        raise ValueError("require-jump-frames requires require-jump-region")
    interaction_target = (resolve_interaction_target(level, args.auto_target_object)
                          if args.auto_objective == "earliest-interaction" else None)
    required = tuple(resolve_interaction_requirement(level, name)
                     for name in args.auto_require_interaction)
    if args.auto_require_reference_interactions:
        from nv14_replay import simulate_through_frame
        reference_state = simulate_through_frame(level, replay_frames, frame)
        required = merge_interaction_requirements(required,
            reference_interaction_requirements(level, reference_state))
    avoided = tuple(resolve_interaction_avoidance(level, name)
                    for name in args.auto_avoid_interaction)
    goal = EndpointGoal(
        target_frame=frame, objective=args.auto_objective, target=target,
        target_region=args.auto_target_region,
        arrival_start=(start if args.auto_arrival_start is None else args.auto_arrival_start)
        if args.auto_objective in EARLIEST_OBJECTIVES else 0,
        secondary_objective=args.auto_secondary_objective,
        interaction_target=interaction_target,
        x_window=args.auto_x_window, y_window=args.auto_y_window,
        vx_window=args.auto_vx_window, vy_window=args.auto_vy_window,
        required_interactions=required, avoided_interactions=avoided,
        required_jumps=tuple(args.auto_require_jumps),
        require_region=args.auto_require_region,
        require_region_frames=args.auto_require_region_frames,
        required_drone_detections=_resolve_drone_detection(level, args.auto_require_drone_detection),
        require_drone_detection_frames=args.auto_require_drone_detection_frames,
        survive_after_goal=getattr(args, "auto_survive_after_goal", 0),
        require_jump_region=args.auto_require_jump_region,
        require_jump_frames=(args.auto_require_jump_frames or (start, frame))
        if args.auto_require_jump_region is not None else None,
    )
    return goal, start, end


def _named_splice_enemy_simulation(args: argparse.Namespace, default: bool) -> bool:
    """Choose safe physics for full-run verification, not per-stage search.

    Individual named splices may enable or disable enemies independently.
    Search and checkpoint evaluation use each stage's own physics world;
    final run verification keeps enemies enabled if ANY stage needs them.
    Explicit CLI flags override both the default and all stage flags.
    """
    if (getattr(args, "mode", None) != "auto" or
            getattr(args, "auto_splice_mode", None) != "user"):
        return default
    names = tuple(dict.fromkeys((*(getattr(args, "auto_splice_files", ()) or ()),
                                 *(getattr(args, "auto_splice_alt_route", ()) or ()))))
    if not names:
        return default
    if _splice_enemy_cli_explicit(args):
        return default
    parser = build_parser()._command_parsers["local"]
    any_enabled = False
    for _, path in _resolve_named_splice_files(_named_splice_directory(args), names):
        values, _ = _load_config_defaults(path, parser, "local")
        any_enabled |= bool(values.get("simulate_enemies", default))
    return default or any_enabled


def _splice_enemy_cli_explicit(args: argparse.Namespace) -> bool:
    """Recognize a real CLI flag rather than a default loaded from TOML."""
    explicit = getattr(args, "_cli_explicit_options", None)
    if explicit is not None:
        return "simulate_enemies" in explicit
    return any(arg.split("=", 1)[0] in ("--simulate-enemies", "--no-simulate-enemies")
               for arg in sys.argv[1:])


def main() -> None:
    args = parse_arguments()
    if args.mode == "dump-player":
        from nv14_dump import run_player_dump

        return run_player_dump(args)
    if args.mode == "encode-video":
        from nv14_video import run_video_encode

        return run_video_encode(args)
    mode_configs = getattr(args, "_mode_configs", None)
    if mode_configs is None:
        mode_configs = build_mode_configs(args)
    common_config = mode_configs.common
    local_config = mode_configs.local
    jump_pattern_config = mode_configs.jump_pattern
    input_path = common_config.input_path
    output_path = common_config.output_path
    replay_output_path = common_config.replay_output_path
    if getattr(args, "auto_ls_splice", False) and not (
        args.mode == "auto" and args.auto_random_splice and args.auto_splice_mode == "user"
    ):
        raise SystemExit("-l/--ls-splice/--ls-splices requires named multi-splicer Auto mode with splice files")
    if getattr(args, "auto_ls_splice", False) and args.auto_splice_from_best:
        raise SystemExit("--ls-splice cannot be combined with --splice-from-best")
    repair_only = getattr(args, "auto_splice_merge_repair_only", False)
    repair_at_end = getattr(args, "auto_splice_merge_repair_at_end", False)
    merge_only = getattr(args, "auto_splice_merge_only", False) or repair_only
    if (repair_only or repair_at_end) and not (args.mode == "auto" and
            args.auto_random_splice and args.auto_splice_mode == "user" and
            args.auto_splice_files):
        raise SystemExit("splice merge repair requires named multi-splicer Auto mode")
    if merge_only:
        # Standalone fast merge and standalone bridge repair both take priority
        # over a persistent [multi-splicer] merge-repair-at-end setting. There
        # is no normal search end in either mode, so do not run end repairs.
        repair_at_end = False
    if merge_only:
        if not (args.mode == "auto" and args.auto_random_splice and
                args.auto_splice_mode == "user" and args.auto_splice_files):
            raise SystemExit("--splice-merge-only requires named multi-splicer Auto mode with splice files")
        if args.auto_ls_splice:
            raise SystemExit("--splice-merge-only cannot be combined with --ls-splice")
        if (args.auto_splice_from_best or args.auto_splice_start or
                args.auto_splice_stop or args.auto_splice_reference is not None):
            raise SystemExit("--splice-merge-only uses all saved named splice bests; "
                             "omit --splice-from-best, --splice-start/stop and --splice-reference")
    try:
        source = _load_source(
            input_path,
            levels_file_path=common_config.levels_file_path,
            explicit_level_id=common_config.level_id,
            ltm_postroll=common_config.ltm_postroll,
            probe_ltm_neutral_tail=args.mode == "auto",
        )
    except LtmError as exc:
        raise SystemExit(str(exc)) from exc
    combined = source.combined
    if source.ltm_movie is not None and source.ltm_movie.warning is not None:
        print(f"warning: {source.ltm_movie.warning}", file=sys.stderr)
    simulate_enemies = (
        (args.mode == "auto" or (local_config is not None and local_config.search == "population"))
        if common_config.simulate_enemies is None
        else common_config.simulate_enemies
    )
    # Full-run verification retains guards when any named splice needs them.
    # Each named stage separately constructs its selected physics world.
    try:
        simulate_enemies = _named_splice_enemy_simulation(args, simulate_enemies)
    except (ValueError, OSError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    level = parse_level_string(
        combined.level_string,
        simulate_enemies=simulate_enemies,
    )
    if (args.mode == "auto" and
            getattr(args, "auto_splice_mode", None) == "user" and
            not getattr(args, "auto_ls_splice", False)):
        print(f"[auto:user-splice:physics] final-run simulate-enemies="
              f"{str(simulate_enemies).lower()} (individual stages may differ)",
              flush=True)

    if args.list_objects:
        print(format_level_objects(level))
        return

    if common_config.output_path is None:
        if getattr(args, "auto_ls_splice", False):
            raise SystemExit("--ls-splice requires --output (the existing final-replay path) "
                             "to locate saved splice checkpoints")
        raise SystemExit("--output is required unless --list-objects is used")
    assert output_path is not None
    if source.ltm_movie is not None and output_path.suffix.lower() != ".ltm":
        raise SystemExit("an .ltm input requires an .ltm --output path")
    if source.ltm_movie is None and output_path.suffix.lower() == ".ltm":
        raise SystemExit(
            "a combined text input cannot create an .ltm output without an LTM template"
        )

    auto_parent_sources: list[tuple[Path, _LoadedSource]] = []
    if args.mode == "auto" and not (getattr(args, "auto_ls_splice", False) or merge_only):
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
                    probe_ltm_neutral_tail=(
                        parent_path.suffix.lower() == ".ltm"
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
        if args.mode == "auto":
            if args.auto_resume and args.auto_checkpoint is None:
                raise ValueError(
                    "--auto-resume requires --auto-checkpoint FILE"
                )
            if args.auto_checkpoint is not None:
                protected_paths: list[tuple[str, Path | None]] = [
                    ("input", input_path),
                    ("output", output_path),
                    ("replay output", replay_output_path),
                    ("levels file", source.levels_file_path),
                ]
                for parent_number, (parent_path, parent_source) in enumerate(
                    auto_parent_sources,
                    start=2,
                ):
                    protected_paths.extend(
                        (
                            (f"auto parent #{parent_number}", parent_path),
                            (
                                f"auto parent #{parent_number} levels file",
                                parent_source.levels_file_path,
                            ),
                        )
                    )
                _validate_auto_checkpoint_path(
                    args.auto_checkpoint,
                    protected_paths,
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
    if source.promote_ltm_neutral_tail:
        assert source.ltm_movie is not None
        try:
            replay = ComplexReplay(
                _probe_auto_ltm_completion_tail(level, source.ltm_movie)
            )
        except (RuntimeError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
    source_frames = editable_frames(replay.frames)
    retimed_frames = source_frames
    applied_retimes: list[RetimeMutation] = []
    for spec_index, (start_spec, delta) in enumerate(
            () if getattr(args, "auto_ls_splice", False) else common_config.retime, start=1):
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
    # A cut-off replay implicitly holds no buttons after its last input.
    # Materialise neutral ticks through the inclusive target frame so Local
    # and endpoint Auto can both optimise and verify an otherwise absent tail.
    # Also pad the reference, which is used to score the baseline. Completed-
    # run Auto is deliberately unaffected: its replay length is significant.
    target = None
    tail_mode = None
    if args.mode == "local" and local_config is not None:
        target = local_config.target_frame
        tail_mode = "local"
    elif (args.mode == "auto" and not args.auto_random_splice
          and args.auto_objective not in AUTO_OBJECTIVES):
        target = args.auto_target_frame
        tail_mode = "auto:goal"
    if target is not None and target >= 0:
        needed = target + 1
        source_frames = source_frames + [InputFrame()] * max(0, needed - len(source_frames))
        extra = max(0, needed - len(retimed_frames))
        if extra:
            retimed_frames = retimed_frames + [InputFrame()] * extra
            print(f"{tail_mode}: appended {extra} neutral input frame(s) through frame {target}")
    replay = ComplexReplay(retimed_frames)

    auto_parent_frames: list[tuple[InputFrame, ...]] = []
    for parent_number, (_parent_path, parent_source) in enumerate(
        auto_parent_sources,
        start=2,
    ):
        parent_replay = decode_complex_replay(parent_source.combined.replay_string)
        if parent_source.promote_ltm_neutral_tail:
            assert parent_source.ltm_movie is not None
            try:
                parent_replay = ComplexReplay(
                    _probe_auto_ltm_completion_tail(
                        level,
                        parent_source.ltm_movie,
                    )
                )
            except (RuntimeError, ValueError) as exc:
                raise SystemExit(
                    f"could not probe auto parent #{parent_number} "
                    f"neutral tail: {exc}"
                ) from exc
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

    if args.mode == "auto" and args.auto_random_splice:
        if args.auto_clean_air_jumps:
            print("[auto:splice:clean] enabled: clean saved checkpoints and "
                  "completed outputs after replay-trace verification", flush=True)
        def clean_splice_output(frames):
            if not args.auto_clean_air_jumps:
                return frames
            from nv14_replay import clean_ineffective_air_jumps
            cleaned = clean_ineffective_air_jumps(level, frames)
            if cleaned != tuple(editable_frames(frames)):
                print("[auto:splice:clean] removed ineffective airborne jump "
                      "holds; verified identical full trace", flush=True)
            return cleaned

        if (args.auto_splice_mode == "user" and not getattr(args, "_both_mode", False)
                and _find_option_paths(sys.argv[1:], "--goal-config")):
            raise SystemExit("user splice mode uses its own named goal files; omit --goal-config")
        target_goal = None
        target_start, target_end = 0, None
        if (args.auto_splice_mode != "user"
                and args.auto_objective != AUTO_OBJECTIVE_SPEEDRUN):
            try:
                target_goal, target_start, target_end = _auto_goal_from_options(
                    level, replay.frames, args)
            except (ValueError, RuntimeError) as exc:
                raise SystemExit(str(exc)) from exc
        if not args.auto_ls_splice and (args.auto_parents or args.auto_checkpoint or args.auto_resume):
            raise SystemExit("random splice does not support auto parents or checkpoint/resume")
        try:
            if args.auto_splice_mode == "user":
                from nv14_user_splice import optimise_user_splices
                directory = _named_splice_directory(args)
                stages = _load_named_splice_stages(level, replay.frames, args,
                                                   directory, args.auto_splice_files)
                alternate_stages = (_load_named_splice_stages(
                    level, replay.frames, args, directory, args.auto_splice_alt_route)
                    if args.auto_splice_alt_route else ())
                all_stages = tuple({stage.name: stage for stage in
                                    (*stages, *alternate_stages)}.values())
                all_names = tuple(stage.name for stage in all_stages)
                if (alternate_stages and not (args.auto_ls_splice or
                                               args.auto_splice_merge_only or
                                               args.auto_splice_merge_repair_only) and
                        args.auto_runs == 0):
                    raise SystemExit("alt-route requires finite --auto-runs: "
                                     "an unlimited primary campaign would never reach "
                                     "the alternate route")
                stage_outputs = _user_splice_output_paths(
                    all_names, output_path, replay_output_path,
                    protected_paths=(("input", input_path),
                                     ("TOML config", args.config),
                                     ("splice config", args.splice_config),
                                     ("levels file", source.levels_file_path),
                                     *((f"splice goal {name}", path) for name, path in
                                       _resolve_named_splice_files(directory, all_names))),
                )

                # Restore best stage checkpoints and their small diverse frontier
                # sidecars before searching. Every stored replay is reverified
                # under the current stage goals in optimise_user_splices.
                saved_stage_candidates = _load_user_splice_checkpoints(
                    stage_outputs, output_path, replay_output_path)
                saved_stage_frontiers = ({} if args.auto_ls_splice else
                                         _load_user_splice_frontiers(
                                             level, all_stages, stage_outputs))
                for stage_name, main_pair in stage_outputs.items():
                    archive_path = _user_splice_frontier_path(main_pair[0])
                    for title, protected in (("input", input_path),
                                             ("output", output_path),
                                             ("replay output", replay_output_path),
                                             ("config", args.config),
                                             ("splice config", args.splice_config),
                                             ("levels file", source.levels_file_path),
                                             *((f"stage {name}", path)
                                               for name, pair in stage_outputs.items()
                                               for path in pair if path is not None)):
                        if protected is not None and _paths_alias(archive_path, protected):
                            raise ValueError(f"frontier path {archive_path} conflicts with {title}")

                def save_frontier(name: str, frames: tuple[tuple[InputFrame, ...], ...]) -> None:
                    path = _user_splice_frontier_path(stage_outputs[name][0])
                    stage = next(item for item in all_stages if item.name == name)
                    document = _user_splice_frontier_identity(level, stage)
                    document["replays"] = [encode_complex_replay(item) for item in frames]
                    _atomic_write_text(path, json.dumps(document, separators=(",", ":")) + "\n")
                if not args.auto_ls_splice:
                    for stage_name, candidates in saved_stage_candidates.items():
                        print(f"[auto:user-splice:resume] {stage_name!r}: "
                              f"read {len(candidates)} distinct saved replay(s)", flush=True)
                # The alternate LTM name shares the replay output basename.
                # Collision checks cover it before the first checkpoint write.
                alias_outputs = {}
                for stage_name in stage_outputs:
                    alias = _user_splice_alias_ltm_path(
                        output_path, replay_output_path, stage_name)
                    if alias is not None and source.ltm_movie is not None:
                        for label, protected in (("input", input_path),
                                                 ("config", args.config),
                                                 ("splice config", args.splice_config),
                                                 ("final output", output_path),
                                                 ("final replay", replay_output_path),
                                                 *((f"splice {key} output", path)
                                                   for key, pair in stage_outputs.items()
                                                   for path in pair if path is not None)):
                            if protected is not None and _paths_alias(alias, protected):
                                raise ValueError(f"splice LTM alias {alias} conflicts with {label}")
                        alias_outputs[stage_name] = alias

                def save_stage_best(name: str, frames: tuple[InputFrame, ...]) -> None:
                    main_path, packed_path = stage_outputs[name]
                    replay_text = encode_complex_replay(clean_splice_output(frames))
                    _protect_unreadable_splice_output(main_path)
                    _protect_unreadable_splice_output(packed_path)
                    if source.ltm_movie is not None and packed_path is not None:
                        # An LTM may regard trailing neutral ticks as implicit
                        # post-roll. Save the plain replay as it will actually
                        # load from the new movie, not as the search workspace.
                        _write_result(source, main_path, None, replay_text)
                        loaded = LtmMovie.load(main_path)
                        try:
                            _atomic_write_text(packed_path, encode_complex_replay(
                                loaded.replay_frames) + "\n")
                        except OSError as exc:
                            raise SystemExit(f"could not write stage replay output {packed_path}: {exc}") from exc
                    else:
                        _write_result(source, main_path, packed_path, replay_text)
                    alias = alias_outputs.get(name)
                    if alias is not None:
                        # Copy the exact movie that was just written, rather
                        # than reserializing frames and risking LTM differences.
                        alias.parent.mkdir(parents=True, exist_ok=True)
                        _atomic_write_binary(alias, main_path.read_bytes())
                    print(f"[auto:user-splice:stage-checkpoint] {name!r}: saved "
                          f"{main_path}" + (f" and {packed_path}" if packed_path else "") +
                          " (stage-feasible; full-run completion not required)", flush=True)

                splice_config = RandomSpliceConfig(
                    iterations=args.auto_splice_iterations,
                    splice_rounds=args.auto_splice_rounds,
                    splice_stagnation_rounds=args.auto_splice_stagnation_rounds,
                    splice_auto_stagnation_rounds=args.auto_splice_auto_stagnation_rounds,
                    splice_local_stagnation_rounds=args.auto_splice_local_stagnation_rounds,
                    splice_speed=args.auto_splice_speed,
                    splice_round_speeds=args.auto_splice_round_speeds,
                    live_save_best=args.auto_splice_live_save_best,
                    search_backend=args.auto_splice_search,
                    endpoint_max_retime=args.max_retime,
                    endpoint_mutation_span=args.auto_mutation_span,
                    endpoint_route_mutations=args.auto_mutations,
                    endpoint_repair_steps=args.auto_endpoint_repair_steps,
                    endpoint_repair_lookback=args.auto_endpoint_repair_lookback,
                    endpoint_auto_mutation_share=args.auto_endpoint_auto_mutation_share,
                    endpoint_progressive_refinement=args.auto_progressive_refinement,
                    endpoint_refinement_share=args.auto_refinement_share,
                    endpoint_adaptive_refinement=args.auto_adaptive_refinement,
                    endpoint_refinement_cycle=args.auto_refinement_cycle,
                    endpoint_refinement_polish=args.auto_refinement_polish,
                    endpoint_refinement_chain_steps=args.auto_refinement_chain_steps,
                    endpoint_shared_refinement_proposals=args.auto_shared_refinement_proposals,
                    endpoint_performance_stats=args.auto_performance_stats,
                    lookback=args.auto_splice_lookback,
                    beam=args.beam, workers=max(1, args.workers),
                    repair_iterations=args.auto_splice_repair_iterations,
                    rounds=args.auto_runs, stagnation_rounds=args.auto_stagnation_runs,
                    frontier=max(1, args.auto_splice_frontier),
                    save_frontier=args.auto_splice_save_frontier,
                    stage_lookback=args.auto_splice_stage_lookback,
                    seed=(int.from_bytes(os.urandom(8), "big") if args.seed == "random"
                          else 0 if args.seed is None else int(args.seed)),
                )
                summary_frames = replay.frames
                saved_final_frames = None
                if output_path.is_file():
                    # A named-splice summary compares saved intermediate bests
                    # against the *saved final replay*, not the original input.
                    try:
                        saved_final = _load_source(
                            output_path, levels_file_path=source.levels_file_path,
                            explicit_level_id=common_config.level_id,
                            ltm_postroll=common_config.ltm_postroll)
                    except (LtmError, OSError, ValueError) as exc:
                        print(f"[auto:user-splice:resume] ignoring unreadable saved output "
                              f"{output_path}: {exc}", flush=True)
                    else:
                        if saved_final.combined.level_string != combined.level_string:
                            raise ValueError(f"saved final replay {output_path} belongs to "
                                             "a different level; choose a different output path")
                        saved_final_frames = tuple(editable_frames(
                            decode_complex_replay(saved_final.combined.replay_string).frames))
                        if args.auto_ls_splice:
                            summary_frames = saved_final_frames
                reference_frames = None
                if args.auto_splice_reference is not None and not args.auto_ls_splice:
                    ref_path = args.auto_splice_reference
                    try:
                        ref_source = _load_source(
                            ref_path, levels_file_path=source.levels_file_path,
                            explicit_level_id=common_config.level_id,
                            ltm_postroll=common_config.ltm_postroll)
                        if ref_source.combined.level_string != combined.level_string:
                            raise ValueError("reference replay is for a different level")
                        reference_frames = tuple(editable_frames(decode_complex_replay(
                            ref_source.combined.replay_string).frames))
                        if ref_source.promote_ltm_neutral_tail and ref_source.ltm_movie is not None:
                            reference_frames = tuple(editable_frames(
                                _probe_auto_ltm_completion_tail(level, ref_source.ltm_movie)))
                    except (LtmError, OSError, ValueError) as exc:
                        # Bare complex replay .txt files are also supported.
                        if ref_path.suffix.lower() != '.txt':
                            raise ValueError(f"cannot load splice reference {ref_path}: {exc}") from exc
                        reference_frames = tuple(editable_frames(
                            decode_complex_replay(ref_path.read_text(encoding='utf-8')).frames))
                    print(f"[auto:user-splice:reference] loaded {ref_path}; "
                          f"{len(reference_frames)} frames; full replay will be verified", flush=True)
                resume_state_path = output_path.with_suffix(".splice-search.json")
                resume_state = None
                if not (args.auto_ls_splice or merge_only) and resume_state_path.is_file():
                    try:
                        if resume_state_path.stat().st_size > 128 * 1024:
                            raise ValueError("named splice resume state exceeds 128 KiB")
                        resume_state = json.loads(resume_state_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError, UnicodeError) as exc:
                        print(f"[auto:user-splice:resume] ignoring unreadable active "
                              f"search state {resume_state_path}: {exc}", flush=True)
                def persist_resume_state(state):
                    if state is None:
                        resume_state_path.unlink(missing_ok=True)
                    else:
                        # Begin a fresh campaign with a clean backend checkpoint;
                        # otherwise stale results from an earlier source seed
                        # could be accepted after a crash before round one.
                        if (resume_state is None or
                                state.get("phase") != resume_state.get("phase")):
                            name = state["stage"]
                            backend = state["phase"]["backend"]
                            path = stage_outputs[name][0].with_suffix(
                                f".{backend}.round.json")
                            path.unlink(missing_ok=True)
                            path.with_suffix(path.suffix + ".prev").unlink(missing_ok=True)
                        _atomic_write_text(resume_state_path, json.dumps(
                            state, separators=(",", ":"), sort_keys=True) + "\n")

                # Save the completed outer-pass number separately from the
                # in-flight backend state. This covers Ctrl+C between phases.
                progress_file = output_path.with_suffix(".splice-progress.json")
                progress_identity = {
                    "level": hashlib.sha256(level.source_level_string.encode()).hexdigest(),
                    "source": hashlib.sha256(encode_complex_replay(tuple(
                        editable_frames(replay.frames))).encode()).hexdigest(),
                    "stages": [repr(stage) for stage in stages],
                    "alternate_stages": [repr(stage) for stage in alternate_stages],
                    "config": repr(splice_config),
                    "from_best": args.auto_splice_from_best,
                    "start_from_stage_bests": args.auto_splice_each_best,
                    "reference_sha256": (hashlib.sha256(encode_complex_replay(reference_frames).encode()).hexdigest()
                                          if reference_frames is not None else None),
                    "merge_stage_bests": args.auto_splice_merge_bests or merge_only or repair_at_end,
                    "merge_repair_at_end": repair_at_end,
                    "merge_repair_pairs": args.auto_splice_merge_repair_pairs,
                    "merge_repair_window": args.auto_splice_merge_repair_window,
                    "merge_repair_targets": args.auto_splice_merge_repair_targets,
                    "start_at": args.auto_splice_start,
                    "stop_at": args.auto_splice_stop,
                }
                completed_passes = 0
                if not (args.auto_ls_splice or merge_only) and progress_file.is_file():
                    try:
                        record = json.loads(progress_file.read_text(encoding="utf-8"))
                        if record["identity"] != progress_identity or (
                                type(record["next_round"]) is not int or
                                record["next_round"] < 0 or
                                (splice_config.rounds and record["next_round"] > splice_config.rounds)):
                            raise ValueError("incompatible completed-pass checkpoint")
                        completed_passes = record["next_round"]
                    except (OSError, ValueError, KeyError, TypeError) as exc:
                        print(f"[auto:user-splice:resume] ignoring stale completed-pass "
                              f"state {progress_file}: {exc}", flush=True)
                # A completed run is not an instruction to skip a new manual
                # invocation with the same source and --auto-runs budget. Keep
                # genuine *in-flight* resumes, but restart a finished campaign.
                if (resume_state is None and splice_config.rounds and
                        completed_passes >= splice_config.rounds):
                    print("[auto:user-splice:resume] previous outer campaign "
                          "finished; starting a fresh pass from the current "
                          "input (saved stage bests retained)", flush=True)
                    completed_passes = 0
                def persist_outer_round(round_no):
                    if round_no is None:
                        progress_file.unlink(missing_ok=True)
                    else:
                        _atomic_write_text(progress_file, json.dumps(
                            {"identity": progress_identity, "next_round": round_no},
                            separators=(",", ":"), sort_keys=True) + "\n")

                def backend_round_path(name: str, backend: str) -> str:
                    return str(stage_outputs[name][0].with_suffix(
                        f".{backend}.round.json"))

                if merge_only:
                    report = "repair-only" if repair_only else "merge-only"
                    print(f"[auto:user-splice:{report}] current input: "
                          f"{input_path.resolve()}; saved completed run: "
                          f"{output_path.resolve()} (if verified); "
                          "only the positional input is treated as manual edits",
                          flush=True)
                # Interleave alternate branches before searching their shared
                # suffix. Both reconvergence candidates are independently
                # searched and retained; the lower-ranked route is not lost
                # merely because the other branch reaches the seam first.
                if (alternate_stages and not (args.auto_ls_splice or merge_only)):
                    from nv14_endpoint import EndpointEvaluator
                    from nv14_user_splice import _materialise_splice_tail

                    primary_names = [item.name for item in stages]
                    alt_names = [item.name for item in alternate_stages]
                    prefix_count = 0
                    for left, right in zip(primary_names, alt_names):
                        if left != right:
                            break
                        prefix_count += 1
                    tail_names = set(primary_names[prefix_count:])
                    rejoin_name = next((name for name in alt_names[prefix_count:]
                                        if name in tail_names), None)
                    rejoin_index = (primary_names.index(rejoin_name)
                                    if rejoin_name is not None else None)
                    start_index = (primary_names.index(args.auto_splice_start)
                                   if args.auto_splice_start is not None else 0)
                    if (rejoin_index is not None and start_index < rejoin_index
                            and prefix_count <= rejoin_index):
                        alt_rejoin_index = alt_names.index(rejoin_name, prefix_count)
                        shared_prefix = stages[start_index:prefix_count]
                        primary_branch = stages[max(start_index, prefix_count):rejoin_index]
                        other_branch = alternate_stages[prefix_count:alt_rejoin_index]
                        shared_rejoin = stages[rejoin_index]
                        shared_suffix = stages[rejoin_index + 1:]
                        # Every segment has its own interrupted-backend state;
                        # one branch must never load another route's checkpoint.
                        input_completion = evaluate_replay_with_sentinel(level, replay.frames)
                        completed_best = [saved_final_frames if saved_final_frames is not None else
                                          tuple(editable_frames(replay.frames))
                                          if (input_completion.valid and
                                              input_completion.finish_tick == len(replay.frames))
                                          else None]
                        phase_attempts = phase_evaluations = phase_improvements = 0
                        captured: dict[str, tuple[InputFrame, ...]] = {}

                        def stage_world(stage):
                            enabled = (level.simulate_enemies if stage.simulate_enemies is None
                                       else stage.simulate_enemies)
                            if enabled == level.simulate_enemies:
                                return level
                            return parse_level_string(level.source_level_string,
                                                      simulate_enemies=enabled)

                        def stage_rank(stage, frames):
                            if frames is None:
                                return None
                            workspace = _materialise_splice_tail(
                                tuple(editable_frames(frames)), stage.goal.target_frame)
                            evaluation = EndpointEvaluator(stage_world(stage), stage.goal).evaluate(workspace)
                            return evaluation.objective_key if evaluation.feasible else None

                        def better_stage(stage, left, right):
                            left_score = stage_rank(stage, left)
                            right_score = stage_rank(stage, right)
                            if left_score is None:
                                return right
                            if right_score is None:
                                return left
                            return left if left_score <= right_score else right

                        def phase_best_callback(frames):
                            canonical = tuple(editable_frames(frames))
                            checked = evaluate_replay_with_sentinel(level, canonical)
                            if not checked.valid or checked.finish_tick != len(canonical):
                                # A branch may have only a provisional endpoint
                                # checkpoint. Never publish it as the final run.
                                return
                            verify_trimmed_replay(level, canonical)
                            completed_best[0] = canonical
                            _write_result(source, output_path, replay_output_path,
                                          encode_complex_replay(clean_splice_output(canonical)))

                        def run_route_phase(label, phase_stages, phase_input, *,
                                            checkpoints=None, frontiers=None,
                                            checkpoint_writer=None, frontier_writer=None,
                                            extra_seeds=(), from_saved_final=True,
                                            merge_at_start=False, repair_at_finish=False):
                            nonlocal phase_attempts, phase_evaluations, phase_improvements
                            if not phase_stages:
                                return tuple(editable_frames(phase_input)), {}
                            phase_results = {}
                            def save_result(name, frames):
                                if frames is not None:
                                    previous = phase_results.get(name)
                                    phase_results[name] = better_stage(
                                        next(item for item in phase_stages if item.name == name),
                                        previous, tuple(editable_frames(frames)))

                            # Saved stage checkpoints can be read by the next
                            # phase, but never by a different branch's join
                            # search. That is what preserves route identity.
                            loaded = (_load_user_splice_checkpoints(
                                stage_outputs, output_path, replay_output_path)
                                if checkpoints is None else checkpoints)
                            archive = (_load_user_splice_frontiers(
                                level, phase_stages, stage_outputs)
                                if frontiers is None else frontiers)
                            checkpoint_path = output_path.with_suffix(
                                f".{label}.splice-search.json")
                            checkpoint = None
                            if checkpoint_path.is_file():
                                try:
                                    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                                except (OSError, UnicodeError, ValueError):
                                    print(f"[auto:user-splice:resume] ignoring unreadable "
                                          f"{checkpoint_path}", flush=True)
                            def save_phase_state(state):
                                if state is None:
                                    checkpoint_path.unlink(missing_ok=True)
                                else:
                                    _atomic_write_text(checkpoint_path,
                                                       json.dumps(state, separators=(',', ':')) + '\n')
                            def phase_backend(name, backend):
                                return str(stage_outputs[name][0].with_suffix(
                                    f".{label}.{backend}.round.json"))
                            print(f"[auto:user-splice:route] {label}: " +
                                  ' -> '.join(item.name for item in phase_stages), flush=True)
                            phase_result = optimise_user_splices(
                                level, phase_input, phase_stages, splice_config,
                                completion_policy=args.auto_completion_policy,
                                start_from_stage_bests=(args.auto_splice_each_best
                                                       if from_saved_final else False),
                                reference_frames=reference_frames,
                                merge_stage_bests=merge_at_start or repair_at_finish,
                                merge_verbose=args.auto_splice_merge_verbose,
                                merge_repair_at_end=repair_at_finish,
                                merge_repair_pairs=args.auto_splice_merge_repair_pairs,
                                merge_repair_window=args.auto_splice_merge_repair_window,
                                merge_repair_targets=args.auto_splice_merge_repair_targets,
                                best_callback=phase_best_callback,
                                stage_best_callback=(checkpoint_writer if checkpoint_writer is not None
                                                     else save_stage_best),
                                stage_result_callback=save_result,
                                initial_seeds=extra_seeds,
                                seed_from_saved_final=from_saved_final,
                                saved_stage_candidates=loaded,
                                saved_stage_frontiers=archive,
                                saved_final_frames=completed_best[0],
                                reporting_input_frames=replay.frames,
                                frontier_callback=(frontier_writer if frontier_writer is not None
                                                   else save_frontier),
                                resume_state=checkpoint,
                                save_resume_state=save_phase_state,
                                backend_checkpoint_path=phase_backend,
                                progress=lambda message: _print_user_splice_progress(
                                    message, color=common_config.color),
                            )
                            phase_attempts += phase_result.attempts
                            phase_evaluations += phase_result.evaluations
                            phase_improvements += phase_result.improvements
                            return phase_result.frames, phase_results

                        def saved_stage_seed(name):
                            candidates = _load_user_splice_checkpoints(
                                stage_outputs, output_path, replay_output_path).get(name, ())
                            stage = next(item for item in all_stages if item.name == name)
                            feasible = [(stage_rank(stage, candidate), candidate)
                                        for candidate in candidates]
                            feasible = [(rank, candidate) for rank, candidate in feasible
                                        if rank is not None]
                            return min(feasible, key=lambda item: item[0])[1] if feasible else None

                        initial_input = tuple(editable_frames(replay.frames))

                        def merge_all_saved_stages(phase, *, repair=False):
                            nonlocal phase_attempts, phase_evaluations, phase_improvements
                            # The merge pass needs *both* branch populations,
                            # not just the current suffix's stage subset.
                            joined_branches = sorted(
                                (*primary_branch, *other_branch),
                                key=lambda item: item.goal.target_frame)
                            joined_stages = tuple((
                                *stages[:prefix_count], *joined_branches,
                                *stages[rejoin_index:]))
                            print(f"[auto:user-splice:route] {phase}: "
                                  "merge across both branch archives", flush=True)
                            merged = optimise_user_splices(
                                level, initial_input, joined_stages, splice_config,
                                completion_policy=args.auto_completion_policy,
                                merge_stage_bests=True, merge_only=True,
                                merge_repair_only=repair,
                                merge_verbose=args.auto_splice_merge_verbose,
                                merge_repair_pairs=args.auto_splice_merge_repair_pairs,
                                merge_repair_window=args.auto_splice_merge_repair_window,
                                merge_repair_targets=args.auto_splice_merge_repair_targets,
                                saved_final_frames=completed_best[0],
                                saved_stage_candidates=_load_user_splice_checkpoints(
                                    stage_outputs, output_path, replay_output_path),
                                saved_stage_frontiers=_load_user_splice_frontiers(
                                    level, joined_stages, stage_outputs),
                                reference_frames=reference_frames,
                                reporting_input_frames=replay.frames,
                                best_callback=phase_best_callback,
                                stage_best_callback=save_stage_best,
                                frontier_callback=save_frontier,
                                progress=lambda message: _print_user_splice_progress(
                                    message, color=common_config.color),
                            )
                            phase_attempts += merged.attempts
                            phase_evaluations += merged.evaluations
                            phase_improvements += merged.improvements

                        if args.auto_splice_merge_bests or repair_at_end:
                            merge_all_saved_stages('startup')
                        shared_seed = initial_input
                        if shared_prefix:
                            _, prefix_results = run_route_phase(
                                'shared-prefix', shared_prefix, shared_seed)
                            shared_seed = (prefix_results.get(shared_prefix[-1].name)
                                           or saved_stage_seed(shared_prefix[-1].name)
                                           or initial_input)
                        elif prefix_count:
                            shared_seed = (saved_stage_seed(stages[prefix_count - 1].name)
                                           or initial_input)
                        main_seed = shared_seed
                        alt_seed = shared_seed
                        _, main_results = run_route_phase(
                            'primary-branch', primary_branch, main_seed,
                            extra_seeds=(initial_input,), from_saved_final=False)
                        if primary_branch:
                            main_seed = (main_results.get(primary_branch[-1].name)
                                         or saved_stage_seed(primary_branch[-1].name)
                                         or main_seed)
                        _, other_results = run_route_phase(
                            'alternate-branch', other_branch, alt_seed,
                            extra_seeds=(initial_input,), from_saved_final=False)
                        if other_branch:
                            alt_seed = (other_results.get(other_branch[-1].name)
                                        or saved_stage_seed(other_branch[-1].name)
                                        or alt_seed)

                        rejoin_candidates = {}
                        frontier_additions = []
                        for branch_label, branch_seed in (('primary', main_seed),
                                                          ('alternate', alt_seed)):
                            def capture_rejoin(_name, candidates):
                                for candidate in candidates:
                                    frontier_additions.append(tuple(editable_frames(candidate)))
                            _, join_results = run_route_phase(
                                branch_label + '-rejoin', (shared_rejoin,), branch_seed,
                                checkpoints={}, frontiers={}, from_saved_final=False,
                                checkpoint_writer=lambda _name, _frames: None,
                                frontier_writer=capture_rejoin)
                            candidate = join_results.get(rejoin_name)
                            if candidate is not None and stage_rank(shared_rejoin, candidate) is not None:
                                rejoin_candidates[branch_label] = candidate
                                frontier_additions.append(candidate)
                        # Recover the best saved replay for each *route* before
                        # ranking this run. A good alternative must not vanish
                        # merely because it was not rediscovered today.
                        main_path, main_text = stage_outputs[rejoin_name]
                        other_main = main_path.with_name(
                            f"{main_path.stem}_other_route{main_path.suffix}")
                        other_text = (main_text.with_name(
                            f"{main_text.stem}_other_route{main_text.suffix}")
                            if main_text is not None else None)
                        main_meta = main_path.with_suffix('.route.json')
                        other_meta = other_main.with_suffix('.other_route.json')
                        checkpoint_identity = _user_splice_frontier_identity(
                            level, shared_rejoin)
                        protected = (input_path, output_path, replay_output_path,
                                     args.config, args.splice_config, source.levels_file_path,
                                     *alias_outputs.values(),
                                     *(path for pair in stage_outputs.values()
                                       for path in pair if path is not None))
                        for destination in (other_main, other_text, other_meta, main_meta):
                            if destination is not None and any(
                                    path is not None and _paths_alias(destination, path)
                                    for path in protected):
                                raise ValueError(
                                    f"other-route checkpoint {destination} aliases a protected file")

                        def read_routed_checkpoint(path, meta_path):
                            if not path.is_file() or not meta_path.is_file():
                                return None, None
                            try:
                                record = json.loads(meta_path.read_text(encoding='utf-8'))
                                if (record.get('version') != 1 or
                                        record.get('identity') != checkpoint_identity or
                                        record.get('route') not in ('primary', 'alternate')):
                                    return None, None
                                if path.suffix.lower() == '.ltm':
                                    frames = LtmMovie.load(path).replay_frames
                                else:
                                    text = path.read_text(encoding='utf-8').strip()
                                    try:
                                        frames = decode_complex_replay(text).frames
                                    except (ValueError, TypeError):
                                        frames = decode_complex_replay(
                                            parse_combined_level_replay(text).replay_string).frames
                                frames = tuple(editable_frames(frames))
                                if stage_rank(shared_rejoin, frames) is not None:
                                    return record['route'], frames
                            except (OSError, UnicodeError, ValueError, TypeError, LtmError):
                                pass
                            return None, None

                        for path, meta in ((main_path, main_meta),
                                           (other_main, other_meta)):
                            old_route, old_frames = read_routed_checkpoint(path, meta)
                            if old_route is not None:
                                rejoin_candidates[old_route] = better_stage(
                                    shared_rejoin, rejoin_candidates.get(old_route), old_frames)

                        ranked_routes = sorted(rejoin_candidates.items(),
                                               key=lambda item: stage_rank(shared_rejoin, item[1]))
                        if ranked_routes:
                            preferred_route, preferred = ranked_routes[0]
                            old_saved = saved_stage_seed(rejoin_name)
                            old_rank = stage_rank(shared_rejoin, old_saved)
                            new_rank = stage_rank(shared_rejoin, preferred)
                            if old_rank is None or new_rank < old_rank:
                                save_stage_best(rejoin_name, preferred)
                            if old_rank is None or new_rank <= old_rank:
                                _atomic_write_text(main_meta, json.dumps({
                                    'version': 1, 'route': preferred_route,
                                    'identity': checkpoint_identity,
                                }, sort_keys=True) + '\n')
                            if (len(ranked_routes) > 1 and
                                    ranked_routes[1][1] != preferred):
                                slower_route, slower = ranked_routes[1]
                                # One named stage has one overall checkpoint;
                                # the lower-ranked *branch* gets a separate LTM
                                # and companion TXT for future merge/searches.
                                old_route, old_other = read_routed_checkpoint(
                                    other_main, other_meta)
                                if (old_route != slower_route or old_other != slower):
                                    _protect_unreadable_splice_output(other_main)
                                    _protect_unreadable_splice_output(other_text)
                                    slower_replay = encode_complex_replay(clean_splice_output(slower))
                                    if source.ltm_movie is not None and other_text is not None:
                                        _write_result(source, other_main, None, slower_replay)
                                        # Reflect the exact replay the LTM stores,
                                        # including its implicit neutral post-roll.
                                        loaded = LtmMovie.load(other_main)
                                        _atomic_write_text(other_text,
                                            encode_complex_replay(loaded.replay_frames) + '\n')
                                    else:
                                        _write_result(source, other_main, other_text, slower_replay)
                                    _atomic_write_text(other_meta, json.dumps({
                                        'version': 1, 'route': slower_route,
                                        'identity': checkpoint_identity,
                                    }, sort_keys=True) + '\n')
                                frontier_additions.append(tuple(editable_frames(slower)))
                                print(f"[auto:user-splice:route] {rejoin_name!r}: "
                                      f"retained {slower_route} branch at {other_main} "
                                      '(other route, independently reusable)', flush=True)
                            persisted = _load_user_splice_frontiers(
                                level, (shared_rejoin,), stage_outputs).get(rejoin_name, ())
                            # Never allow a large primary frontier to evict
                            # the lower-ranked route when the archive reaches
                            # its 64-replay cap. Both branch winners are first.
                            combined_archive = list(dict.fromkeys((
                                *(frames for _, frames in ranked_routes),
                                *frontier_additions, *persisted)))
                            if combined_archive:
                                save_frontier(rejoin_name, tuple(combined_archive[:64]))
                            continuation = preferred
                            if shared_suffix:
                                run_route_phase('shared-suffix', shared_suffix, continuation,
                                                extra_seeds=tuple(value for _, value in ranked_routes[1:]),
                                                repair_at_finish=False)
                        else:
                            # No branch reached the reconvergence objective.
                            # Do not discard both prefixes or invent a saved
                            # seam checkpoint; try the shared suffix from both.
                            print(f"[auto:user-splice:route] {rejoin_name!r}: "
                                  'neither branch reached the seam goal; '
                                  'preserving both as shared-suffix search seeds', flush=True)
                            if shared_suffix:
                                run_route_phase('shared-suffix', shared_suffix, main_seed,
                                                extra_seeds=(alt_seed,),
                                                repair_at_finish=False)
                        if args.auto_splice_merge_bests or repair_at_end:
                            merge_all_saved_stages('final', repair=repair_at_end)
                        print(f"[auto:user-splice] {phase_attempts} stage searches; "
                              f"{phase_evaluations} evaluations; "
                              f"{phase_improvements} verified improvements")
                        return

                result = optimise_user_splices(
                    level, summary_frames, stages, splice_config,
                    completion_policy=args.auto_completion_policy,
                    start_at=args.auto_splice_start, stop_at=args.auto_splice_stop,
                    from_best=args.auto_splice_from_best,
                    start_from_stage_bests=args.auto_splice_each_best,
                    reference_frames=reference_frames,
                    merge_stage_bests=args.auto_splice_merge_bests or merge_only or repair_at_end,
                    merge_only=merge_only,
                    merge_verbose=args.auto_splice_merge_verbose,
                    merge_repair_only=repair_only,
                    merge_repair_at_end=repair_at_end,
                    merge_repair_pairs=args.auto_splice_merge_repair_pairs,
                    merge_repair_window=args.auto_splice_merge_repair_window,
                    merge_repair_targets=args.auto_splice_merge_repair_targets,
                    summary_only=args.auto_ls_splice,
                    best_callback=lambda frames: _write_result(
                        source, output_path, replay_output_path,
                        encode_complex_replay(clean_splice_output(frames))),
                    stage_best_callback=save_stage_best,
                    saved_stage_candidates=saved_stage_candidates,
                    saved_stage_frontiers=saved_stage_frontiers,
                    saved_final_frames=(None if args.auto_ls_splice else saved_final_frames),
                    reporting_input_frames=replay.frames,
                    frontier_callback=save_frontier,
                    resume_state=resume_state,
                    save_resume_state=(None if args.auto_ls_splice or merge_only else persist_resume_state),
                    backend_checkpoint_path=backend_round_path,
                    resume_outer_round=(0 if args.auto_ls_splice else completed_passes),
                    save_outer_round=(None if args.auto_ls_splice or merge_only else persist_outer_round),
                    progress=lambda message: _print_user_splice_progress(
                        message, color=common_config.color),
                )
                if alternate_stages:
                    primary_names = [stage.name for stage in stages]
                    alternate_names = [stage.name for stage in alternate_stages]
                    shared_prefix = 0
                    for left, right in zip(primary_names, alternate_names):
                        if left != right:
                            break
                        shared_prefix += 1
                    primary_tail = set(primary_names[shared_prefix:])
                    rejoin_name = next((name for name in alternate_names[shared_prefix:]
                                        if name in primary_tail), None)
                    if rejoin_name is None:
                        alternate_branch = alternate_stages[shared_prefix:]
                    else:
                        rejoin_index = alternate_names.index(rejoin_name, shared_prefix)
                        alternate_branch = alternate_stages[shared_prefix:rejoin_index]
                    # --start-at-splice refers to the primary route. If the
                    # start is already at/past the rejoin, the branch lies
                    # entirely before the requested starting point.
                    skipped_before_start = False
                    if (args.auto_splice_start is not None and rejoin_name is not None and
                            primary_names.index(args.auto_splice_start) >=
                            primary_names.index(rejoin_name)):
                        alternate_branch = ()
                        skipped_before_start = True
                    if alternate_branch:
                        print("[auto:user-splice:route] alternate branch: " +
                              " -> ".join(stage.name for stage in alternate_branch) +
                              (f" (shared prefix through {alternate_names[shared_prefix - 1]!r}; "
                               f"rejoin at {rejoin_name!r})"
                               if shared_prefix and rejoin_name is not None else
                               f" (rejoin at {rejoin_name!r})" if rejoin_name is not None else
                               f" (shared prefix through {alternate_names[shared_prefix - 1]!r})"
                               if shared_prefix else ""),
                              flush=True)
                    elif skipped_before_start:
                        print("[auto:user-splice:route] alternate branch skipped: "
                              f"--start-at-splice {args.auto_splice_start!r} is at/after "
                              f"rejoin {rejoin_name!r}", flush=True)
                    else:
                        print("[auto:user-splice:route] alternate branch has no unique stages; "
                              "shared prefix and rejoin are already covered by the primary route",
                              flush=True)
                    # The primary route may have saved fresh checkpoints.
                    # Re-load them for the alternate route, and compare against
                    # the primary's independently verified completed best.
                    alt_candidates = _load_user_splice_checkpoints(
                        stage_outputs, output_path, replay_output_path)
                    alt_frontiers = ({} if args.auto_ls_splice else
                                     _load_user_splice_frontiers(
                                         level, alternate_branch, stage_outputs))
                    primary_eval = evaluate_replay_with_sentinel(level, result.frames)
                    alt_best = (result.frames if primary_eval.valid and
                                primary_eval.finish_tick == len(result.frames)
                                else saved_final_frames)
                    # Distinct backend checkpoint names prevent an alternate
                    # route from loading an interrupted *primary* backend.
                    def alt_backend_path(name, backend):
                        return str(stage_outputs[name][0].with_suffix(
                            f".alt.{backend}.round.json"))
                    if alternate_branch:
                        alt_result = optimise_user_splices(
                            level, summary_frames, alternate_branch, splice_config,
                            completion_policy=args.auto_completion_policy,
                            start_from_stage_bests=args.auto_splice_each_best,
                            reference_frames=reference_frames,
                            merge_stage_bests=args.auto_splice_merge_bests or merge_only or repair_at_end,
                            merge_only=merge_only,
                            merge_verbose=args.auto_splice_merge_verbose,
                            merge_repair_only=repair_only,
                            merge_repair_at_end=repair_at_end,
                            merge_repair_pairs=args.auto_splice_merge_repair_pairs,
                            merge_repair_window=args.auto_splice_merge_repair_window,
                            merge_repair_targets=args.auto_splice_merge_repair_targets,
                            summary_only=args.auto_ls_splice,
                            best_callback=lambda frames: _write_result(
                                source, output_path, replay_output_path,
                                encode_complex_replay(clean_splice_output(frames))),
                            stage_best_callback=save_stage_best,
                            saved_stage_candidates=alt_candidates,
                            saved_stage_frontiers=alt_frontiers,
                            saved_final_frames=(None if args.auto_ls_splice else alt_best),
                            reporting_input_frames=replay.frames,
                            frontier_callback=save_frontier,
                            backend_checkpoint_path=alt_backend_path,
                            progress=lambda message: _print_user_splice_progress(
                                message, color=common_config.color),
                        )
                    else:
                        alt_result = type(result)(result.frames, 0, 0, 0)
                    # Each route owns its stage objectives and frontier order.
                    # Never promote an incomplete alternate replay over a
                    # verified primary completed result.
                    alt_eval = evaluate_replay_with_sentinel(level, alt_result.frames)
                    if alt_eval.valid and alt_eval.finish_tick == len(alt_result.frames):
                        chosen_frames = alt_result.frames
                    else:
                        chosen_frames = result.frames
                    result = type(result)(
                        chosen_frames,
                        result.improvements + alt_result.improvements,
                        result.attempts + alt_result.attempts,
                        result.evaluations + alt_result.evaluations,
                    )
                if args.auto_ls_splice or merge_only:
                    return
                if not result.improvements:
                    print("[auto:user-splice] no verified improvement; existing output retained")
                print(f"[auto:user-splice] {result.attempts} stage searches; "
                      f"{result.evaluations} evaluations; {result.improvements} improvements")
                return
            splice_config = RandomSpliceConfig(
                points=args.auto_splice_points,
                mode=args.auto_splice_mode,
                physics_interactions=args.auto_splice_interactions,
                physics_skip_probability=args.auto_splice_skip_probability,
                frames_per_point=args.auto_splice_frames_per_point,
                distance=args.auto_splice_distance,
                radius=args.auto_splice_radius, lookback=args.auto_splice_lookback,
                iterations=args.auto_splice_iterations,
                search_backend=args.auto_splice_search,
                endpoint_max_retime=args.max_retime,
                endpoint_mutation_span=args.auto_mutation_span,
                endpoint_route_mutations=args.auto_mutations,
                endpoint_repair_steps=args.auto_endpoint_repair_steps,
                endpoint_repair_lookback=args.auto_endpoint_repair_lookback,
                endpoint_auto_mutation_share=args.auto_endpoint_auto_mutation_share,
                endpoint_progressive_refinement=args.auto_progressive_refinement,
                endpoint_refinement_share=args.auto_refinement_share,
                endpoint_adaptive_refinement=args.auto_adaptive_refinement,
                endpoint_refinement_cycle=args.auto_refinement_cycle,
                endpoint_refinement_polish=args.auto_refinement_polish,
                endpoint_refinement_chain_steps=args.auto_refinement_chain_steps,
                endpoint_shared_refinement_proposals=args.auto_shared_refinement_proposals,
                endpoint_performance_stats=args.auto_performance_stats,
                repair_iterations=args.auto_splice_repair_iterations,
                splice_rounds=args.auto_splice_rounds,
                splice_stagnation_rounds=args.auto_splice_stagnation_rounds,
                splice_auto_stagnation_rounds=args.auto_splice_auto_stagnation_rounds,
                splice_local_stagnation_rounds=args.auto_splice_local_stagnation_rounds,
                splice_speed=args.auto_splice_speed,
                splice_round_speeds=args.auto_splice_round_speeds,
                waypoint_stage_lookback=args.auto_splice_waypoint_lookback,
                live_save_best=args.auto_splice_live_save_best,
                repair_rounds=args.auto_splice_repair_rounds,
                repair_anchors=args.auto_splice_repair_anchors,
                beam=args.beam, workers=max(1, args.workers), rounds=args.auto_runs,
                stagnation_rounds=args.auto_stagnation_runs,
                max_repair_searches=args.auto_splice_repair_searches,
                frontier=args.auto_splice_frontier,
                exit_lookback=args.auto_splice_exit_lookback,
                seed=(int.from_bytes(os.urandom(8), "big") if args.seed == "random"
                      else 0 if args.seed is None else int(args.seed)),
            )
            # Speedrun publishes only canonically completed improvements.
            # Endpoint mode instead publishes only independently verified goal
            # improvements (optionally requiring full completion).
            result = optimise_random_splices(
                level, replay.frames, splice_config,
                best_callback=lambda frames: _write_result(
                    source, output_path, replay_output_path,
                    encode_complex_replay(clean_splice_output(frames))),
                progress=lambda message: (
                    _print_baseline_line(message, color=common_config.color)
                    if message.startswith((
                        "[auto:random-splice:baseline]",
                        "[auto:random-splice:goal:baseline]",
                    ))
                    else _print_best_line(message, color=common_config.color)
                    if message.startswith((
                        "[auto:random-splice:goal] improved ",
                        "[auto:random-splice] speedrun improved:",
                        "[auto:random-splice] exit proximity improved:",
                    ))
                    else print(message, flush=True)
                ),
                target_goal=target_goal, range_start=target_start,
                range_end=target_end, completion_policy=args.auto_completion_policy,
            )
            if not result.improvements:
                # Do not overwrite previous files without a verified improvement.
                if target_goal is None:
                    print("[auto:random-splice] no shorter or closer switch-safe completed replay found")
                else:
                    print("[auto:random-splice:goal] no verified target improvement found; no output written")
            else:
                _write_result(source, output_path, replay_output_path,
                              encode_complex_replay(result.frames))
            print(f"[auto:random-splice] {result.attempts} searches tried; "
                  f"{result.improvements} improvements; {len(result.frames)} frames"
                  + (f"; target {target_goal.objective} at frame {target_goal.target_frame}"
                     if target_goal is not None else ""))
        except (ValueError, RuntimeError) as exc:
            raise SystemExit(str(exc)) from exc
        except KeyboardInterrupt:
            # Best improvements were atomically published through the callback.
            # Use the conventional interrupt exit status rather than claiming
            # normal campaign completion (and never start another anchor).
            print("\n[auto:random-splice] interrupted; last verified best retained", flush=True)
            raise SystemExit(130) from None
        return

    if args.mode == "auto" and args.auto_objective not in AUTO_OBJECTIVES:
        # Endpoint Auto uses Local's *exact* evaluator, but its own structural
        # mutation beam. Incomplete routes cannot enter Auto's completed-route
        # repair/splice campaign, so reject options that belong to that engine.
        unsupported = []
        if args.auto_checkpoint is not None or args.auto_resume:
            unsupported.append("--auto-checkpoint/--auto-resume")
        if args.auto_parents:
            unsupported.append("--auto-parent")
        if args.auto_runs == 0:
            unsupported.append("--auto-runs 0 (endpoint Auto needs a finite round count)")
        if args.auto_max_extra_ticks is not None or args.auto_require_reference_gold:
            unsupported.append("highscore-only settings")
        if args.auto_postroll != 1:
            unsupported.append("--auto-postroll other than 1")
        if unsupported:
            raise SystemExit("endpoint Auto does not support " + ", ".join(unsupported))
        try:
            frame = (len(replay.frames) - 1 if args.auto_target_frame is None
                     else args.auto_target_frame)
            if not 0 <= frame < len(replay.frames):
                raise ValueError("auto target-frame must lie inside the replay")
            start, end = parse_auto_frame_range(args.frame_range, target_frame=frame)
            if end is not None and end > frame:
                raise ValueError("auto endpoint range must not extend beyond target-frame")
            if args.auto_objective == "min-distance":
                if (args.auto_target_object is None) == (args.auto_target_point is None):
                    raise ValueError("min-distance requires exactly one of target-object or target-point")
                target = (resolve_target_object(level, args.auto_target_object)
                          if args.auto_target_object is not None else target_from_point(args.auto_target_point))
            else:
                if args.auto_target_point is not None or (args.auto_target_object is not None
                        and args.auto_objective != "earliest-interaction"):
                    raise ValueError("target-point/object requires min-distance or earliest-interaction")
                target = None
            if args.auto_objective == "earliest-interaction" and args.auto_target_object is None:
                raise ValueError("earliest-interaction requires target-object")
            if args.auto_arrival_start is not None and args.auto_objective not in EARLIEST_OBJECTIVES:
                raise ValueError("arrival-start requires earliest-arrival or earliest-interaction")
            if args.auto_require_jumps and args.auto_require_jump_region is not None:
                raise ValueError("require-jumps cannot be combined with require-jump-region")
            if args.auto_require_jump_frames is not None and args.auto_require_jump_region is None:
                raise ValueError("require-jump-frames requires require-jump-region")
            interaction_target = (resolve_interaction_target(level, args.auto_target_object)
                                  if args.auto_objective == "earliest-interaction" else None)
            required = tuple(resolve_interaction_requirement(level, name)
                             for name in args.auto_require_interaction)
            if args.auto_require_reference_interactions:
                from nv14_replay import simulate_through_frame
                reference_state = simulate_through_frame(level, replay.frames, frame)
                required = merge_interaction_requirements(required,
                    reference_interaction_requirements(level, reference_state))
            avoided = tuple(resolve_interaction_avoidance(level, name)
                            for name in args.auto_avoid_interaction)
            goal = EndpointGoal(
                target_frame=frame, objective=args.auto_objective, target=target,
                target_region=args.auto_target_region,
                arrival_start=(start if args.auto_arrival_start is None else args.auto_arrival_start)
                if args.auto_objective in EARLIEST_OBJECTIVES else 0,
                secondary_objective=args.auto_secondary_objective,
                interaction_target=interaction_target,
                x_window=args.auto_x_window, y_window=args.auto_y_window,
                vx_window=args.auto_vx_window, vy_window=args.auto_vy_window,
                required_interactions=required, avoided_interactions=avoided,
                required_jumps=tuple(args.auto_require_jumps),
                require_region=args.auto_require_region,
                require_region_frames=args.auto_require_region_frames,
                required_drone_detections=_resolve_drone_detection(level, args.auto_require_drone_detection),
                require_drone_detection_frames=args.auto_require_drone_detection_frames,
                survive_after_goal=getattr(args, "auto_survive_after_goal", 0),
                require_jump_region=args.auto_require_jump_region,
                require_jump_frames=(args.auto_require_jump_frames or (start, frame))
                if args.auto_require_jump_region is not None else None,
            )
            endpoint_budget = resolve_auto_endpoint_iterations(
                full_run_iterations=args.iterations,
                endpoint_iterations=args.auto_endpoint_iterations,
                endpoint_iterations_per_frame=args.auto_endpoint_iterations_per_frame,
                range_start=start,
                range_end=frame if end is None else end,
            )
            endpoint_config = AutoEndpointConfig(
                iterations=endpoint_budget, beam_width=args.beam,
                max_retime=args.max_retime,
                seed=(int.from_bytes(os.urandom(8), "big") if args.seed == "random"
                      else 0 if args.seed is None else int(args.seed)),
                range_start=start, range_end=end,
                mutation_span=args.auto_mutation_span,
                route_mutations=args.auto_mutations,
                completion_policy=args.auto_completion_policy,
                repair_steps=args.auto_endpoint_repair_steps,
                repair_lookback=args.auto_endpoint_repair_lookback,
                auto_mutation_share=args.auto_endpoint_auto_mutation_share,
                progressive_refinement=args.auto_progressive_refinement,
                refinement_share=args.auto_refinement_share,
                adaptive_refinement=args.auto_adaptive_refinement,
                refinement_cycle=args.auto_refinement_cycle,
                refinement_polish=args.auto_refinement_polish,
                refinement_chain_steps=args.auto_refinement_chain_steps,
                shared_refinement_proposals=args.auto_shared_refinement_proposals,
                performance_stats=args.auto_performance_stats,
            )
        except (ValueError, RuntimeError) as exc:
            raise SystemExit(str(exc)) from exc

        endpoint_start = time.monotonic()
        endpoint_checkpoints = 0

        def endpoint_elapsed() -> str:
            seconds = max(0, int(time.monotonic() - endpoint_start))
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        def endpoint_status(phase: str, message: str, *, new_best: bool = False,
                            baseline: bool = False) -> None:
            line = (f"[{time.strftime('%H:%M:%S')}] [auto:{phase}] "
                    f"{message}; elapsed {endpoint_elapsed()}")
            if new_best:
                _print_best_line(line, color=common_config.color)
            elif baseline:
                _print_baseline_line(line, color=common_config.color)
            else:
                print(line, flush=True)

        endpoint_status(
            "parallel", f"endpoint objective {goal.objective}; "
            f"editable frames {endpoint_config.range_start}:"
            f"{frame if endpoint_config.range_end is None else endpoint_config.range_end}; "
            f"iterations per worker {endpoint_config.iterations}; seed {endpoint_config.seed}; "
            f"workers {max(1, args.workers)}; rounds {args.auto_runs}; "
            f"Auto mutation share {endpoint_config.auto_mutation_share:.0%}; "
            f"progressive refinement {'on' if endpoint_config.progressive_refinement else 'off'}; "
            f"initial Local share {endpoint_config.refinement_share:.0%}; "
            f"one-frame polishing {'on' if endpoint_config.progressive_refinement and endpoint_config.refinement_polish else 'off'}; "
            f"Local repair chain {endpoint_config.refinement_chain_steps if endpoint_config.progressive_refinement else 0} slots",
        )

        def save_endpoint_best(candidate):
            nonlocal endpoint_checkpoints
            # The campaign checks the candidate independently and invokes this
            # only for a strict improvement over the starting objective.
            replay_text = encode_complex_replay(candidate.frames)
            _write_result(source, output_path, replay_output_path, replay_text)
            endpoint_checkpoints += 1

            e = candidate.evaluation
            gap = endpoint_exit_edge_distance(level, goal, e)
            distance_text = (f" (distance to exit {gap:.2f})"
                             if gap is not None else "")
            endpoint_status(
                "checkpoint", f"saved best #{endpoint_checkpoints}: "
                f"frame {e.frame}{distance_text}; score {e.score:.12g}; "
                f"position ({e.x:.12g}, {e.y:.12g}); "
                f"velocity ({e.vx:.12g}, {e.vy:.12g})" +
                (f"; secondary {goal.secondary_objective}={e.secondary_value:.15g}"
                 if goal.secondary_objective is not None else ""),
                new_best=True,
            )

        def show_endpoint_progress(message: str) -> None:
            if message.startswith("baseline:"):
                endpoint_status("baseline", message[len("baseline:"):].strip(), baseline=True)
            elif "starting " in message or " finished; " in message:
                endpoint_status("parallel", message)
            elif "proposals (" in message or "distinct evaluations;" in message:
                endpoint_status("beam", message)
            else:
                endpoint_status("parallel", message)

        try:
            baseline, winner, count = optimise_auto_endpoint_campaign(
                level, replay.frames, goal, endpoint_config,
                workers=max(1, args.workers), runs=args.auto_runs,
                best_callback=save_endpoint_best,
                progress=show_endpoint_progress,
            )
            if winner is None:
                raise ValueError("no feasible endpoint found; no output was written")
            packed = tuple(editable_frames(decode_complex_replay(
                encode_complex_replay(winner.frames)).frames))
            verified = verify_endpoint(level, packed, goal, expected=winner.evaluation)
            if not verified.feasible:
                raise ValueError("packed replay does not satisfy endpoint goal")
            if endpoint_config.completion_policy == "complete":
                completed = evaluate_replay_with_sentinel(level, packed)
                if not completed.valid or completed.finish_tick != len(packed):
                    raise ValueError("packed endpoint replay does not complete on its neutral sentinel")
            _write_result(source, output_path, replay_output_path, encode_complex_replay(packed))
        except (ValueError, RuntimeError) as exc:
            raise SystemExit(str(exc)) from exc
        final_gap = endpoint_exit_edge_distance(level, goal, verified)
        final_distance = (f" (distance to exit {final_gap:.2f})"
                          if final_gap is not None else "")
        endpoint_status(
            "parallel", f"endpoint search complete: {count:,} distinct evaluations; "
            f"baseline score {baseline.evaluation.score:.12g}; "
            f"final score {verified.score:.12g}; frame {verified.frame}{final_distance}; "
            f"{endpoint_checkpoints} verified improvement(s)" +
            (f"; secondary {goal.secondary_objective}={verified.secondary_value:.15g}"
             if goal.secondary_objective is not None and verified.feasible else ""),
        )
        return

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
            auto_range_start, auto_range_end = parse_auto_frame_range(
                args.frame_range,
                target_frame=(
                    len(replay.frames) - 1 + effective_auto_extra_ticks
                ),
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
            resume_seed: int | None = None
            if (
                args.auto_resume
                and args.auto_checkpoint is not None
                and args.auto_checkpoint.exists()
            ):
                try:
                    checkpoint_payload = read_auto_checkpoint(
                        args.auto_checkpoint
                    )
                except AutoCheckpointError as exc:
                    raise SystemExit(str(exc)) from exc
                checkpoint_state = checkpoint_payload.get("state")
                if not isinstance(checkpoint_state, Mapping) or type(
                    checkpoint_state.get("base_seed")
                ) is not int:
                    raise SystemExit(
                        "Auto checkpoint does not contain a valid base seed"
                    )
                resume_seed = checkpoint_state["base_seed"]
            if resume_seed is None:
                auto_seed = int.from_bytes(os.urandom(8), "big")
                print(f"[auto:seed] random seed {auto_seed}", flush=True)
            else:
                auto_seed = resume_seed
                print(
                    f"[auto:seed] restored checkpoint seed {auto_seed}",
                    flush=True,
                )
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
                repair_beam_width=args.auto_repair_beam_width,
                repair_cache_entries=args.auto_repair_cache_entries,
                repair_adaptive_windows=args.auto_adaptive_repair_windows,
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
                splice_plans_per_pair=args.auto_splice_plans_per_pair,
                auxiliary_beam_seeds=args.auto_auxiliary_beam_seeds,
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
                if update.phase == "baseline":
                    _print_baseline_line(text, color=common_config.color)
                else:
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
                    _print_best_line(
                        f"[{auto_system_time()}] "
                        f"[auto:checkpoint] saved best #{checkpoint_count}: "
                        f"score {candidate.evaluation.highscore_value}; "
                        f"finish {candidate.finish_tick}{distance}; "
                        f"gold {candidate.evaluation.gold_count}; "
                        f"elapsed {auto_elapsed()}",
                        color=common_config.color,
                    )
                else:
                    _print_best_line(
                        f"[{auto_system_time()}] "
                        f"[auto:checkpoint] saved best #{checkpoint_count}: "
                        f"finish {candidate.finish_tick}{distance}; "
                        f"elapsed {auto_elapsed()}",
                        color=common_config.color,
                    )

            auto_campaign = optimise_autonomous_campaign(
                level,
                replay.frames,
                auto_config,
                parent_frames=auto_parent_frames,
                workers=args.workers,
                runs=args.auto_runs,
                stagnation_runs=args.auto_stagnation_runs,
                progress=show_auto_progress,
                best_callback=save_auto_best,
                status=show_auto_status,
                search=optimise_autonomous,
                checkpoint_path=args.auto_checkpoint,
                resume=args.auto_resume,
                level_identifier=(source.level_id or combined.name or None),
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
            _print_baseline_line(
                f"auto baseline: finish {auto_result.baseline_finish_tick}; "
                f"gold {auto_result.baseline_gold_count}; "
                f"gold bonus {auto_result.baseline_gold_bonus_ticks}; "
                f"highscore value {auto_result.baseline_objective_value}",
                color=common_config.color,
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
            _print_baseline_line(
                f"auto baseline finish tick: {auto_result.baseline_finish_tick} "
                f"({auto_result.baseline_finish_tick} serialized inputs)",
                color=common_config.color,
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

    if local_config is not None and local_config.search == "population":
        _run_local_population(
            source, level, replay.frames, local_config,
            input_path=input_path, output_path=output_path,
            replay_output_path=replay_output_path,
            config_path=common_config.config_path,
            color=common_config.color,
        )
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
    vx_window = mode_config.vx_window if isinstance(mode_config, LocalConfig) else None
    vy_window = mode_config.vy_window if isinstance(mode_config, LocalConfig) else None
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
        vx_window=vx_window,
        vy_window=vy_window,
    )
    retimed_seed_eval = (
        evaluate(
            level,
            replay.frames,
            target_frame,
            objective,
            x_window=x_window,
            y_window=y_window,
            vx_window=vx_window,
            vy_window=vy_window,
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

    bp = baseline.state.player
    _print_baseline_line(
        f"baseline frame {target_frame}: "
        f"x={bp.pos.x:.15f}, y={bp.pos.y:.15f}; score={baseline.score:.15g}",
        color=common_config.color,
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
                        vx_window=vx_window,
                        vy_window=vy_window,
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
            e = _packed_evaluation
            p = e.state.player
            _print_best_line(
                f"[local:best] verified checkpoint at frame {target_frame}; "
                f"score {e.score:.15g}; "
                f"position ({p.pos.x:.12g}, {p.pos.y:.12g})",
                color=common_config.color,
            )
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
                local_beam_width=mode_config.local_beam_width,
                local_search_cache_entries=mode_config.local_search_cache_entries,
                local_adaptive_windows=mode_config.local_adaptive_windows,
                local_search_ticks=mode_config.local_search_ticks,
                passes=passes,
                minimum_improvement=minimum_improvement,
                x_window=x_window,
                y_window=y_window,
                vx_window=vx_window,
                vy_window=vy_window,
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
                vx_window=vx_window,
                vy_window=vy_window,
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
    fp = final_eval.state.player
    print()
    if jump_results is not None:
        print("ranked jump patterns (start+hold):")
        for rank, result in enumerate(jump_results, start=1):
            p = result.evaluation.state.player
            pulse_text = ", ".join(str(pulse) for pulse in result.pulses)
            line = (
                f"  {rank:>2}. score={result.score:.17g}; "
                f"position=({p.pos.x:.15g}, {p.pos.y:.15g}); "
                f"jumps={pulse_text}"
            )
            if rank == 1 and result.evaluation.score < baseline.score:
                _print_best_line(line, color=common_config.color)
            else:
                print(line)
        print()
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
