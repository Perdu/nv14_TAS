#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# This script converts a N demo file into libTAS inputs
# Usage: python converter.py


def decode_demo_number(num, debug=False):
    """
    Decode one demo number into 7 frames of inputs.
    Returns list of sets: [{'left','jump'}, {}, {'right'}, ...]
    """
    frames = [set() for _ in range(7)]

    # Each input has weight per frame (powers of 16).
    # All the "hold" cases are not actually jumps, they seem to be
    # meaningless. Dropping them.
    mapping = {
        'left':  [1, 16, 256, 4096, 65536, 1048576, 16777216],
        'right': [2, 32, 512, 8192, 131072, 2097152, 33554432],
        'jump': [12, 192, 3072, 49152, 786432, 12582912, 201326592],  # jump
        # 'jump_hold_prev': [4, 68, 1092, 17476, 279620, 4473924, 71582788], # hold from prev 7 frames (as jump)
        # 'jump_hold': [4, 64, 1024, 16384, 262144, 4194304, 67108864], # hold (theoretical values)
        # 'jump_and_hold': [76, 1216, 19456, 311296, 4980736, 79691776, 0], # jump+hold
        # 'jump_and_hold2': [0, 1100, 17600, 281600, 4505600, 72089600, 0], # jump+hold+hold
        # 'jump_and_hold3': [0, 0, 17484, 279744, 4475904, 71614464, 0], # etc
        # 'jump_and_hold4': [0, 0, 0, 279628, 4474048, 71584768, 0],
        # 'jump_and_hold5': [0, 0, 0, 0, 4473932, 71582912, 0],
        # 'jump_and_hold6': [0, 0, 0, 0, 0, 71582796, 0],
    }

    if debug:
        print("num %s" % num)
    for i in range(7):
        for key, weights in mapping.items():
            if num & weights[i]:
                if key in ['jump_hold_prev', 'jump_hold',
                           'jump_and_hold', 'jump_and_hold2', 'jump_and_hold3',
                           'jump_and_hold4', 'jump_and_hold5', 'jump_and_hold6']:
                    new_key = 'jump'  # they're all just jumps
                else:
                    new_key = key
                if new_key not in frames[i]:  # avoid duplicates
                    frames[i].add(new_key)
                if debug:
                    print("Add key %s to frame %s" % (key, i))
    return frames


def convert_demo_to_libtas(demo_numbers, debug=False):
    """
    demo_numbers: list of integers (each encodes 7 frames)
    output_path: path to save libtas input file
    """
    # Xlib KeySym mapping
    keysym_map = {
        'left': 'ff51',   # XK_Left
        'right': 'ff53',  # XK_Right
        'jump': 'ffe1',  # XK_Shift_L
    }

    for num in demo_numbers:
        frames = decode_demo_number(num, debug)
        for frame in frames:
            if frame:
                pressed = ":".join(keysym_map[key] for key in frame)
                print(f"|K{pressed}|")
            else:
                print("|")


if __name__ == "__main__":
    # demo_str = "17895697|17895697|17895697|79692049|107373636|107374182|107373670|31614566|35791394|17895697|17895697|17895697|89480465|89478485|89478485|22369621|17895697|89478493|89478485|89478485|89478485|17895697|17895697|17895697|17895889|35791377|35791586|17895698|17895889|35791394|35791394|35791394|35791586|35791394|35791394|35791394|35791394|35791394|35791394|18031138|17895697|17895697|17895697|35721489|35791394|35791394|35791394|35791394|139810"  # 00-0 speedrun
    # demo_str = "17895697|17895697|17895697|17895889|17895697|17895697|17895697|17895697|219222289|89478485|18175317|17895697|17895697|17895697|17895697|17895697|237117713|35791394|17895697|17895697|35852561|107374307|107374182|107374182|107374182|35808870|35791394|35791393|35791394|237117986|35808870|35791394|35791394|35791394|35791394|35791394|48374306|35791394|35791394|35791394|35791394|35791394|17896226|17895441|34672913|35791394|35791394|35791394|35791394|17900066|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|89985297|89478485|89478485|89478485|89478485|17895697|17895697|17895697|17895697|17895697|219222289|89478485|17896789|17895697|17895697|48387537|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394"  # 10-0 high-score
    demo_str = "115483170|107374182|107374182|107374182|115500646|107374182|107374182|107374182|89478485|30478613|17895697|17895697|17895697|17895697|97605073|89478485|89478485|89480469|89478485|89478485|89478485|115430741|22369638|17895697|17895697|17895697|35791377|35791394|35791392|35791394|35791394|35791394|35840546|35791394|35791394|35791394|35791394|35791394|35791394|237117986|35791394|17895714|17895697"
    demo_numbers = [int(x) for x in demo_str.strip('|').split('|') if x]

    convert_demo_to_libtas(demo_numbers, debug=False)
