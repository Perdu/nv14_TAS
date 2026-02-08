TILE_X_WIDTH = 12
NINJA_RADIUS = TILE_X_WIDTH * 0.8333333333333334
MAX_SPEED_AIR = NINJA_RADIUS * 0.5
AIR_ACCELERATION = 0.099    # This should be 0.1, but it only works if I set it to 0.099
DRAG = 0.99

def step_air(x, old_x, input):
    # PlayerObject.prototype.TickNormal equivalent
    v6 = old_x
    old_x = x
    x += DRAG * (x - v6)

    #  PlayerObject.prototype.Think equivalent
    vx = x - old_x
    new_vx = vx + input * AIR_ACCELERATION
    if abs(new_vx) < MAX_SPEED_AIR:
        vx = new_vx

    return old_x + vx, old_x

def bruteforce(x, old_x, target_x, start_frame, end_frame, input_sequence='??', succcessful_sequences=[]):
    for frame in range(start_frame, end_frame+1):

        # Calculate maximum possible displacement in remaining frames using s = ut + 0.5at^2 and discard paths
        # where it is no longer possible to reach the target. Overestimated by using air acceleration = 0.11.
        frames_remaining = end_frame - frame
        vx = x - old_x
        max_displacement_left = vx * frames_remaining + 0.5 * -0.11 * frames_remaining ** 2
        max_displacement_right = vx * frames_remaining + 0.5 * 0.11 * frames_remaining ** 2

        if max(target_x) - x < 0 and max(target_x) < x + max_displacement_left:
            return succcessful_sequences
        if min(target_x) - x > 0 and min(target_x) > x + max_displacement_right:
            return succcessful_sequences

        if target_x[0] <= x <= target_x[1]:
            print(x, input_sequence)
            succcessful_sequences.append((x, input_sequence))

        bruteforce(*step_air(x, old_x, 1), target_x, frame+1, end_frame, input_sequence + 'R', succcessful_sequences)
        bruteforce(*step_air(x, old_x, 0), target_x, frame+1, end_frame, input_sequence + 'N', succcessful_sequences)
        bruteforce(*step_air(x, old_x, -1), target_x, frame+1, end_frame, input_sequence + 'L', succcessful_sequences)
    return succcessful_sequences

def process_results(result):
    minimum = min(result, key=lambda t: t[0])
    maximum = max(result, key=lambda t: t[0])
    print(f'Maximum position: {maximum}')
    print(f'Minimum position: {minimum}')

if __name__ == '__main__':
    result = bruteforce(x=36.985,               # x-position for 2nd frame
                        old_x=35.5,             # x-position for 1st frame
                        target_x=(34.0, 34.1),  # target range of x-positions
                        start_frame=49,         # frame number for old_x
                        end_frame=79,           # frame number one frame BEFORE the desired position is reached
                        input_sequence='LL')    # the input sequence for the first two frames (for info only)
    process_results(result)
