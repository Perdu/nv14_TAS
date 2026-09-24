"""Source-order regression cases from the v4.22 glitch audit, sections 6.4–6.10."""
from __future__ import annotations

import pytest

from tools.compare_engines import load_native_module, load_reference_engine


@pytest.fixture(params=['python', 'native'])
def backend(request):
    engine = load_reference_engine() if request.param == 'python' else load_native_module()
    return request.param, engine


def _run(backend, objects, frames=1):
    name, engine = backend
    level = engine.parse_level_string('0' * 713 + '|' + objects)
    state = level.initial_state()
    for _ in range(frames):
        if name == 'python':
            state.step(engine.InputFrame(), level.tiles)
        else:
            state.step(False, False, False, False)
    if name == 'python':
        p, s = state.player, state.static_state
        result = dict(dead=p.dead, complete=s.level_complete, gold=s.gold_bonus_ticks,
                      collected=s.collected_gold_mask, exploded=s.exploded_mine_mask,
                      open=s.open_exit_mask, x=p.pos.x, y=p.pos.y, mode=int(p.state))
    else:
        p, s = state.player_snapshot(), state.static_state()
        result = dict(dead=p['dead'], complete=s['level_complete'], gold=s['gold_bonus_ticks'],
                      collected=s['collected_gold_mask'], exploded=s['exploded_mine_mask'],
                      open=s['open_exit_mask'], x=p['pos'][0], y=p['pos'][1], mode=p['state'])
    return state, result


def test_exit_unlinks_before_older_same_cell_mine(backend):
    _, result = _run(backend, '5^60,60!12^60,60!11^60,60,60,60', 2)
    assert result['complete'] and not result['dead']
    assert result['exploded'] == 0


def test_completion_removes_later_gold_without_collecting_it(backend):
    _, result = _run(backend, '5^60,60!0^60,76.3!11^60,60,60,60', 2)
    assert result['complete'] and not result['dead']
    assert result['gold'] == result['collected'] == 0
    assert result['y'] == 60.448499999999996


def test_later_cell_mine_still_kills_on_completion_tick(backend):
    _, result = _run(backend, '5^60,60!12^60,74.3!11^60,60,60,60', 2)
    assert result['complete'] and result['dead']
    assert result['exploded'] == 1
    assert result['mode'] == 6  # Die replaces Think with null and state with RAGDOLL.


def test_later_pad_runs_exit_die_and_preserves_ghost_collision_state(backend):
    state, result = _run(backend, '5^60,70!12^60,70!2^60,72,0,-1')
    assert not result['dead'] and result['exploded'] == 1
    assert result['mode'] == 4
    assert result['y'] == pytest.approx(59.86428571428572)
    # The next frame continues TickNormal. Its disabled object collision
    # callback is also preserved by a search clone.
    cloned = state.clone()
    assert cloned.state_key() == state.state_key()
    _, after = _run(backend, '5^60,70!12^60,70!2^60,72,0,-1', 2)
    assert not after['dead'] and after['y'] == pytest.approx(49.83142857142858)


def test_multiple_exit_triggers_share_the_undefined_removal_guard(backend):
    _, result = _run(backend,
        '5^60,60!0^60,72!11^300,300,60,60!11^500,300,60,72')
    # The first trigger removes itself although gridList[undefined] referred
    # to the other trigger. The second opens its exit, but cannot remove
    # itself, so traversal reaches the older gold in that second cell.
    assert result['open'] == 3 and result['gold'] == 80


def test_death_idles_gold_before_later_pad_restores_player(backend):
    _, result = _run(backend, '5^60,70!12^60,70!0^62,74!2^60,72,0,-1')
    assert not result['dead'] and result['exploded'] == 1
    assert result['gold'] == result['collected'] == 0


def test_second_mine_after_revival_runs_a_new_death_callback(backend):
    _, result = _run(backend, '5^70,70!12^70,70!12^80,70!2^72,70,1,0')
    assert result['dead'] and result['exploded'] == 3
    assert result['mode'] == 6


def test_orphan_exit_trigger_can_open_after_death_during_current_scan(backend):
    _, result = _run(backend,
        '5^70,69.7!11^74,47.95,74,70!11^600,300,500,300!12^70,69.7!2^72,70,1,0')
    # Idle removes the newest trigger through UID=undefined. The older one
    # remains linked, then opens a door visited later in this same invocation.
    assert not result['dead'] and result['complete']
    assert result['open'] == 1 and result['exploded'] == 1
