# Some parts are AI-generated

from dataclasses import dataclass

TILE_X_WIDTH = 12
NINJA_RADIUS = TILE_X_WIDTH * 0.8333333333333334
MAX_SPEED_AIR = NINJA_RADIUS * 0.5
AIR_ACCELERATION = 0.1
DRAG = 0.99

def step_air(x: float, old_x: float, input_: int) -> tuple[float, float]:
    # PlayerObject.prototype.Think equivalent
    vx = x - old_x
    new_vx = vx + input_ * AIR_ACCELERATION
    if abs(new_vx) < MAX_SPEED_AIR:
        vx = new_vx

    old_x = x - vx

    # PlayerObject.prototype.TickNormal equivalent
    v6 = old_x
    old_x = x
    x += DRAG * (x - v6)

    return x, old_x

@dataclass(frozen=True)
class State:
    x: float
    old_x: float
    vx: float
    frame: int
    seq: str

def bruteforce(
    old_x: float,
    x: float,
    target_x: tuple[float, float],
    start_frame: int,
    end_frame: int,
    input_sequence: str,
) -> list[tuple[float, float, str]]:
    successful: list[tuple[float, float, str]] = []

    stack: list[State] = [State(x=x, old_x=old_x, vx=x-old_x, frame=start_frame, seq=input_sequence)]

    low, high = target_x

    while stack:
        s = stack.pop()

        if s.frame > end_frame:
            continue

        if s.frame == end_frame and low <= s.x <= high:
            print(s.x, s.vx, s.seq)
            successful.append((s.x, s.vx, s.seq))

        # Calculate maximum possible displacement in remaining frames using s = ut + 0.5at^2 and discard paths
        # where it is no longer possible to reach the target. Overestimated by using air acceleration = 0.11.
        frames_remaining = end_frame - s.frame
        vx = s.x - s.old_x
        max_disp_left  = vx * frames_remaining + 0.5 * (-0.11) * (frames_remaining ** 2)
        max_disp_right = vx * frames_remaining + 0.5 * ( 0.11) * (frames_remaining ** 2)

        if high - s.x < 0 and high < s.x + max_disp_left:
            continue
        if low - s.x > 0 and low > s.x + max_disp_right:
            continue

        # Expand next states.
        for input_, char in [(-1, "L"), (0, "N"), (1, "R")]:
            new_x, new_old = step_air(s.x, s.old_x, input_)
            stack.append(State(x=new_x, old_x=new_old, vx=new_x-new_old, frame=s.frame + 1, seq=s.seq + char))

    return successful


def process_results(result: list[tuple[float, float, str]]) -> None:
    if not result:
        print("No solutions found.")
        return
    minimum = min(result, key=lambda t: t[0])
    maximum = max(result, key=lambda t: t[0])
    print(f"Maximum position: {maximum}")
    print(f"Minimum position: {minimum}")
    minimum = min(result, key=lambda t: t[1])
    maximum = max(result, key=lambda t: t[1])
    print(f"Maximum velocity: {maximum}")
    print(f"Minimum velocity: {minimum}")


if __name__ == "__main__":
    result = bruteforce(
        old_x=107.599,              # x-position for 1st frame
        x=109.28101,                # x-position for 2nd frame
        target_x=(133.9, 134),      # target range of x-positions
        start_frame=2046,           # frame number for 1st frame
        end_frame=2058,             # frame number BEFORE the desired position should be reached
        input_sequence='R'          # input sequence for 1st frame
    )
    process_results(result)