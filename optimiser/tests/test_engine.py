from nv14_engine import (
    APP_NUM_GRIDCOLS,
    APP_NUM_GRIDROWS,
    InputFrame,
    Player,
    PlayerState,
    TileMap,
)


def empty_map() -> str:
    return "0" * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)


def test_empty_air_first_frame() -> None:
    tiles = TileMap(empty_map())
    p = Player.spawn(100.0, 100.0)
    p.step(InputFrame(), tiles)
    assert p.pos.x == 100.0
    assert p.pos.y == 100.15
    assert p.state == PlayerState.FALLING


def test_air_acceleration_changes_implicit_velocity() -> None:
    tiles = TileMap(empty_map())
    p = Player.spawn(100.0, 100.0)
    p.step(InputFrame(right=True), tiles)
    assert p.vx == 100.0 - 99.9


def test_solid_floor_supports_player() -> None:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    # Internal tile x=4, y=5. Level storage is x-major.
    chars[4 * APP_NUM_GRIDROWS + 5] = "1"
    tiles = TileMap("".join(chars))
    # Tile centre=(132,156), top=144; player radius=10, so supported centre y=134.
    p = Player.spawn(132.0, 134.0)
    p.step(InputFrame(), tiles)
    assert not p.in_air
    assert p.pos.y == 134.0
    assert p.floor_n.y == -1.0


def test_landing_from_jump_restores_normal_gravity() -> None:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    chars[4 * APP_NUM_GRIDROWS + 5] = "1"
    tiles = TileMap("".join(chars))
    p = Player.spawn(132.0, 134.0)
    p.state = PlayerState.JUMPING
    p.g = p.jump_grav

    p.step(InputFrame(right=True), tiles)

    assert p.state == PlayerState.RUNNING
    assert p.g == p.norm_grav


def test_jump_event_counter_only_tracks_successful_player_jump_calls() -> None:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    chars[4 * APP_NUM_GRIDROWS + 5] = "1"
    tiles = TileMap("".join(chars))
    p = Player.spawn(132.0, 134.0)

    # Grounded rising edge performs a real jump.
    p.step(InputFrame(jump=True), tiles)
    assert p.jump_events == 1

    # Continuing to hold jump extends the same jump; it is not a new event.
    p.step(InputFrame(jump=True), tiles)
    assert p.jump_events == 1

    # A fresh rising edge while freely airborne does not call Player.jump().
    p.step(InputFrame(jump=False), tiles)
    p.step(InputFrame(jump=True), tiles)
    assert p.jump_events == 1


def test_alternate_jump_input_probe_matches_held_player_branch() -> None:
    chars = ["0"] * (APP_NUM_GRIDCOLS * APP_NUM_GRIDROWS)
    chars[4 * APP_NUM_GRIDROWS + 5] = "1"
    tiles = TileMap("".join(chars))
    released = Player.spawn(132.0, 134.0)
    held = released.clone()
    compact_probe = released.clone()

    alternate = released.step(
        InputFrame(),
        tiles,
        alternate_inputs=InputFrame(jump=True),
    )
    compact_alternate = compact_probe.step(
        InputFrame(),
        tiles,
        alternate_jump=True,
    )
    held.step(InputFrame(jump=True), tiles)

    assert alternate is not None
    assert compact_alternate is not None
    assert alternate.state_key() == held.state_key()
    assert compact_alternate.state_key() == held.state_key()
    assert alternate.jump_events == held.jump_events == 1
    assert compact_alternate.jump_events == 1
    assert released.jump_events == 0
    assert compact_probe.state_key() == released.state_key()
