from pathlib import Path

from nv14_engine import parse_level_string
from nv14_replay import decode_complex_replay, parse_combined_level_replay


HERE = Path(__file__).parent


def test_direction_copy_on_write_matches_deep_clone_replay() -> None:
    combined = parse_combined_level_replay(
        (HERE / "example_44_0.txt").read_text(encoding="utf-8")
    )
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string, simulate_enemies=True)

    deep_state = level.initial_state()
    copy_on_write_state = level.initial_state().clone(copy_on_write_objects=True)
    for inputs in replay.frames:
        deep_state.step(inputs, level.tiles)
        copy_on_write_state.step(inputs, level.tiles)
        assert copy_on_write_state.state_key() == deep_state.state_key()


def test_copy_on_write_snapshot_survives_source_progress() -> None:
    combined = parse_combined_level_replay(
        (HERE / "example_44_0.txt").read_text(encoding="utf-8")
    )
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string, simulate_enemies=True)

    deep_source = level.initial_state()
    deep_snapshot = deep_source.clone()
    copy_on_write_source = level.initial_state()
    copy_on_write_snapshot = copy_on_write_source.clone(copy_on_write_objects=True)

    for inputs in replay.frames[:120]:
        deep_source.step(inputs, level.tiles)
        copy_on_write_source.step(inputs, level.tiles)
        assert copy_on_write_snapshot.state_key() == deep_snapshot.state_key()
