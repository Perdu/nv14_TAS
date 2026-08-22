from __future__ import annotations

from pathlib import Path

import pytest

from nv14_engine import (
    HomingLauncher,
    HomingMode,
    Turret,
    ObjectSpec,
    Player,
    TileMap,
    OBJTYPE_HOMINGLAUNCHER,
    parse_level_string,
)
from nv14_replay import decode_complex_replay, parse_combined_level_replay


FIXTURE = Path(__file__).with_name("example_07_3_homing.txt")


def _load_07_3():
    combined = parse_combined_level_replay(FIXTURE.read_text(encoding="utf-8"))
    level = parse_level_string(combined.level_string, simulate_enemies=True)
    frames = decode_complex_replay(combined.replay_string).frames
    return level, frames


def test_homing_launcher_is_optional_and_preserves_mixed_thinker_order() -> None:
    combined = parse_combined_level_replay(FIXTURE.read_text(encoding="utf-8"))

    level = parse_level_string(combined.level_string)
    assert not any(isinstance(obj, HomingLauncher) for obj in level.objects)
    assert level.initial_state().thinker_uids == []

    level = parse_level_string(combined.level_string, simulate_enemies=True)
    launcher = next(obj for obj in level.objects if isinstance(obj, HomingLauncher))
    assert launcher.load_index == 13
    assert launcher.basepos.x == pytest.approx(396.0)
    assert launcher.basepos.y == pytest.approx(348.0)
    turret = next(obj for obj in level.objects if isinstance(obj, Turret))
    assert turret.load_index == 14
    # The real turret now occupies the same source thinker slot formerly kept
    # by the passive placeholder, so the initial launcher cadence is unchanged.
    assert level.passive_thinker_uids == ()
    assert level.initial_state().thinker_uids == [14, 13]


def test_07_3_homing_trace_timing_motion_explosions_and_reacquisition() -> None:
    level, frames = _load_07_3()
    state = level.initial_state()
    launcher = next(obj for obj in state.objects if isinstance(obj, HomingLauncher))

    for frame, inputs in enumerate(frames[:218]):
        state.step(inputs, level.tiles)
        assert state.player.dead is False

        if frame == 79:
            assert launcher.mode == HomingMode.PREFIRE
            assert launcher.fire_delay_timer == 0
            assert state.thinker_uids == [14]
        elif frame == 89:
            assert launcher.mode == HomingMode.HOMING
            assert launcher.pos.x == pytest.approx(396.0, abs=1e-12)
            assert launcher.pos.y == pytest.approx(348.0, abs=1e-12)
            assert launcher.speed == 0.0
            assert launcher.curaccel == pytest.approx(0.1, abs=1e-15)
            assert launcher.mdir.x == pytest.approx(0.695562299072485, abs=5e-16)
            assert launcher.mdir.y == pytest.approx(-0.718465787709477, abs=5e-16)
        elif frame == 90:
            assert launcher.pos.x == pytest.approx(396.076511852898, abs=5e-13)
            assert launcher.pos.y == pytest.approx(347.920968763352, abs=5e-13)
            assert launcher.speed == pytest.approx(0.11, abs=1e-15)
            assert launcher.curaccel == pytest.approx(0.11, abs=1e-15)
            assert launcher.mdir.x == pytest.approx(0.697365266184828, abs=5e-16)
            assert launcher.mdir.y == pytest.approx(-0.716715902934325, abs=5e-16)
        elif frame == 128:
            # Update_Homing hits the tile first, ExplodeMissile starts idle, and
            # the launcher is reinserted into the shared thinker ring.
            assert launcher.mode == HomingMode.IDLE
            assert launcher.pos.x == pytest.approx(432.0646915819, abs=5e-13)
            assert launcher.pos.y == pytest.approx(263.706950975484, abs=5e-13)
            assert launcher.load_index in state.thinker_uids
        elif frame == 131:
            assert launcher.mode == HomingMode.PREFIRE
            assert launcher.fire_delay_timer == 0
        elif frame == 141:
            assert launcher.mode == HomingMode.HOMING
            assert launcher.mdir.x == pytest.approx(0.230759033033819, abs=5e-16)
            assert launcher.mdir.y == pytest.approx(-0.97301092936991, abs=5e-16)
        elif frame == 207:
            # This terrain explosion occurs on a frame whose thinker timer is
            # already due. StartIdle inserts UID 13 at the head and it detects
            # the player in the same ObjectManager.Tick(), exactly as traced.
            assert launcher.pos.x == pytest.approx(347.70791655937, abs=5e-13)
            assert launcher.pos.y == pytest.approx(231.429951903247, abs=5e-13)
            assert launcher.mode == HomingMode.PREFIRE
            assert launcher.fire_delay_timer == 0
            assert state.thinker_uids == [14]
        elif frame == 217:
            assert launcher.mode == HomingMode.HOMING
            assert launcher.mdir.x == pytest.approx(0.312826286773975, abs=5e-16)
            assert launcher.mdir.y == pytest.approx(0.949810357020393, abs=5e-16)


def test_supplied_07_3_replay_matches_final_homing_state_and_survives() -> None:
    level, frames = _load_07_3()
    state = level.initial_state()
    launcher = next(obj for obj in state.objects if isinstance(obj, HomingLauncher))

    for inputs in frames:
        state.step(inputs, level.tiles)
        assert state.player.dead is False

    # The 270-input replay ends after source frame 269's homing update.
    assert launcher.mode == HomingMode.HOMING
    assert launcher.pos.x == pytest.approx(460.397262657131, abs=5e-13)
    assert launcher.pos.y == pytest.approx(479.169371340916, abs=5e-13)
    assert launcher.mdir.x == pytest.approx(-0.0549206425868603, abs=5e-16)
    assert launcher.mdir.y == pytest.approx(0.998490722549712, abs=5e-16)
    assert launcher.speed == pytest.approx(24.0 / 7.0, abs=5e-16)
    assert launcher.curaccel == pytest.approx(0.417724816941565, abs=5e-16)


def test_homing_missile_contact_uses_player_radius_and_kills() -> None:
    tiles = TileMap("0" * (31 * 23))
    launcher = HomingLauncher.from_spec(
        ObjectSpec(OBJTYPE_HOMINGLAUNCHER, (120.0, 120.0), 1), tiles
    )
    player = Player.spawn(130.0, 120.0)
    launcher.mode = HomingMode.HOMING
    launcher.pos.x = 120.0001
    launcher.pos.y = 120.0

    # Strict TestVsPlayer condition is distance < player.r (10), with no
    # launcher radius added.
    launcher.test_player(player)
    assert player.dead is True
    assert launcher.mode == HomingMode.IDLE
