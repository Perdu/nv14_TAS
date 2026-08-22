from pathlib import Path

from nv14_engine import InputFrame, Thwomp, parse_level_string
from nv14_replay import decode_complex_replay, parse_combined_level_replay


HERE = Path(__file__).parent
EXAMPLE = HERE / "example_21_2_greedo.txt"


def load_example():
    combined = parse_combined_level_replay(EXAMPLE.read_text(encoding="utf-8"))
    replay = decode_complex_replay(combined.replay_string)
    level = parse_level_string(combined.level_string)
    return replay, level


def test_greedo_loads_six_thwomps() -> None:
    _replay, level = load_example()
    thwomps = [obj for obj in level.objects if isinstance(obj, Thwomp)]
    assert len(thwomps) == 6


def test_greedo_matches_libtas_through_thwomp_boost() -> None:
    replay, level = load_example()
    state = level.initial_state()

    for frame_index in range(112):
        state.step(replay.frames[frame_index], level.tiles)

    p = state.player
    assert abs(p.pos.x - 296.5) < 1e-12
    assert abs(p.pos.y - 163.954392815411) < 1e-12
    assert abs(p.vx - 11.468042036634) < 1e-12
    assert abs(p.vy - (-2.1)) < 1e-12


def test_greedo_matches_libtas_multi_object_contact() -> None:
    replay, level = load_example()
    state = level.initial_state()

    for frame_index in range(138):
        state.step(replay.frames[frame_index], level.tiles)

    p = state.player
    assert abs(p.pos.x - 557.342665745073) < 1e-12
    assert abs(p.pos.y - 161.0) < 1e-12
    assert abs(p.vx - 8.59522072984714) < 1e-12
    assert abs(p.vy) < 1e-12


def test_greedo_matches_libtas_replay_end_and_post_replay_tick() -> None:
    replay, level = load_example()
    state = level.initial_state()

    for frame in replay.frames:
        state.step(frame, level.tiles)

    p = state.player
    assert abs(p.pos.x - 730.456854194837) < 1e-12
    assert abs(p.pos.y - 273.614390948882) < 1e-12
    assert abs(p.vx - (-2.22178640600896)) < 1e-12
    assert abs(p.vy - 5.08967802071834) < 1e-12

    # The supplied libTAS trace includes frame 190 after the 190 replay inputs.
    # The packed word has no input at that point, so this is a neutral tick.
    state.step(InputFrame(), level.tiles)
    p = state.player
    assert abs(p.pos.x - 728.257285652889) < 1e-12
    assert abs(p.pos.y - 278.0) < 1e-12
    assert abs(p.vx - (-2.19956854194891)) < 1e-12
    assert abs(p.vy - 4.38560905111774) < 1e-12
