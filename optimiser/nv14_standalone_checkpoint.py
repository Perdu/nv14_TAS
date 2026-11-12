"""Publish a direct single-goal result into the named-splice checkpoint store.

This runs *after* standalone Auto/Local/Hybrid. It must never influence their
candidate seeds, per-round scheduling, stdout, or completed-result destination.
"""
from __future__ import annotations

from pathlib import Path
import json
import time


def publish_named_checkpoint(*, input_path: Path, output_path: Path,
                             replay_output_path: Path | None, goal_path: Path,
                             name: str, config_path: Path | None = None,
                             levels_file_path: Path | None = None) -> bool:
    from nv14_cli import (
        _load_source, _load_named_splice_stages, _user_splice_output_paths,
        _load_user_splice_checkpoints, _load_user_splice_frontiers,
        _user_splice_frontier_identity, _user_splice_frontier_path,
        _protect_unreadable_splice_output, _write_result, _atomic_write_text,
        _user_splice_alias_ltm_path, _atomic_write_binary,
        parse_arguments,
    )
    from nv14_engine import parse_level_string
    from nv14_endpoint import EndpointEvaluator
    from nv14_ltm import LtmMovie
    from nv14_replay import decode_complex_replay, encode_complex_replay, editable_frames
    from nv14_user_splice import _materialise_splice_tail

    input_path, output_path, goal_path = map(Path, (input_path, output_path, goal_path))
    if not output_path.is_file():
        return False
    if not goal_path.is_file():
        raise ValueError(f"missing named goal file: {goal_path}")
    # Build just the goal's parser settings. In particular do not import the
    # route's merge settings or launch any part of its optimizer coordinator.
    parser_args = ['auto', str(input_path), '--auto-splice-files', name,
                   '--auto-splice-directory', str(goal_path.parent)]
    if config_path is not None:
        parser_args += ['--config', str(config_path)]
    if levels_file_path is not None:
        parser_args += ['--levels-file', str(levels_file_path)]
    parsed = parse_arguments(parser_args)
    source = _load_source(input_path, levels_file_path=levels_file_path,
                          explicit_level_id=None, ltm_postroll=None,
                          probe_ltm_neutral_tail=False)
    completed = _load_source(output_path, levels_file_path=levels_file_path,
                             explicit_level_id=None, ltm_postroll=None,
                             probe_ltm_neutral_tail=False)
    if completed.combined.level_string != source.combined.level_string:
        raise ValueError(f"direct result {output_path} belongs to a different level")
    level = parse_level_string(source.combined.level_string, simulate_enemies=True)
    stage = _load_named_splice_stages(
        level, decode_complex_replay(source.combined.replay_string).frames,
        parsed, goal_path.parent, (name,))[0]
    stage_level = (level if stage.simulate_enemies == level.simulate_enemies else
                   parse_level_string(source.combined.level_string,
                                      simulate_enemies=stage.simulate_enemies))
    evaluator = EndpointEvaluator(stage_level, stage.goal)
    candidate = tuple(editable_frames(decode_complex_replay(
        completed.combined.replay_string).frames))

    def check(frames):
        return evaluator.evaluate(_materialise_splice_tail(frames, stage.goal.target_frame))

    evaluated = check(candidate)
    if not evaluated.feasible:
        print(f"[standalone:checkpoint] {name!r}: direct output does not meet its "
              "named goal; previous checkpoint retained", flush=True)
        return False
    outputs = _user_splice_output_paths((name,), output_path, replay_output_path,
                                        protected_paths=(('input', input_path),
                                                         ('goal', goal_path),
                                                         ('config', config_path)))
    older = _load_user_splice_checkpoints(outputs, output_path, replay_output_path)
    old_best = None
    for existing in older.get(name, ()):
        score = check(existing)
        if score.feasible and (old_best is None or score.objective_key < old_best):
            old_best = score.objective_key
    if old_best is not None and evaluated.objective_key >= old_best:
        print(f"[standalone:checkpoint] {name!r}: existing named checkpoint "
              "is at least as good; retained", flush=True)
        return False

    main, replay_path = outputs[name]
    _protect_unreadable_splice_output(main)
    _protect_unreadable_splice_output(replay_path)
    replay_text = encode_complex_replay(candidate)
    if source.ltm_movie is not None and replay_path is not None:
        _write_result(source, main, None, replay_text)
        persisted = LtmMovie.load(main).replay_frames
        _atomic_write_text(replay_path, encode_complex_replay(persisted) + '\n')
    else:
        _write_result(source, main, replay_path, replay_text)
        persisted = candidate
    alias = _user_splice_alias_ltm_path(output_path, replay_output_path, name)
    if alias is not None:
        _atomic_write_binary(alias, main.read_bytes())
    # Retain compatible older frontier candidates and add this new verified
    # winner. A direct search does not alter the route or its saved best seed.
    restored = _load_user_splice_frontiers(level, (stage,), outputs)
    prior = list(restored.get(name, ()))
    ranked = [tuple(editable_frames(persisted))]
    for candidate_frames in prior:
        if candidate_frames not in ranked:
            ranked.append(candidate_frames)
    identity = _user_splice_frontier_identity(level, stage)
    payload = dict(identity)
    payload['replays'] = [encode_complex_replay(item) for item in ranked[:64]]
    _atomic_write_text(_user_splice_frontier_path(main),
                       json.dumps(payload, separators=(',', ':'), sort_keys=True) + '\n')
    print(f"[{time.strftime('%H:%M:%S')}] [standalone:checkpoint] {name!r}: "
          f"published direct result at frame {evaluated.frame} to {main}; "
          "original backend output unchanged", flush=True)
    return True


def post_search_propagation_requested(config_path: Path, route_path: Path) -> tuple[bool, bool]:
    """Read only propagation feature flags; never adopt standalone merge mode."""
    import tomllib
    settings = {}
    for path in (config_path, route_path):
        if path is not None and path.is_file():
            with path.open('rb') as stream:
                settings.update(tomllib.load(stream).get('multi-splicer', {}))
    merge = any(bool(settings.get(key, False)) for key in
                ('merge-bests', 'merge-retime-gains', 'merge-repair-at-end'))
    return bool(settings.get('merge-repair-at-end', False)), merge


def supports_named_publication(goal_path: Path) -> bool:
    """Do not replace legacy Local windows by managed population semantics."""
    import tomllib
    with Path(goal_path).open('rb') as stream:
        goal = tomllib.load(stream).get('local', {})
    return goal.get('search', 'population') == 'population'
