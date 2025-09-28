#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import yaml

from converter import convert_demo_to_libtas


def start_episode(col, row):
    with open("tas/episode_click_coordinates.yml", "r",
              encoding="utf-8") as f:
        coord = yaml.safe_load(f)
    # On the first frame, press n ("K6e") while moving the mouse to
    # the right coordinates. On the second frame, click on right
    # coordinates
    return f"|K6e|M{coord["column"][col]}:{coord["row"][row]}:A:.....:0|\n|M{coord["column"][col]}:{coord["row"][row]}:A:1....:0|\n"


def build_libtas_input():
    nb_frames = 0
    res = ""
    # initial_wait_frames = 7
    # We need to add additional lag frames because ruffle in libTAS is
    # currently broken
    initial_wait_frames = 15
    for i in range(initial_wait_frames):
        res += "|\n"
        nb_frames += 1
    res += start_episode(0, 0)
    nb_frames += 2
    with open("tas/level_data.yml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for level_name, level_data in data.items():
        for i in range(level_data["loading_time"]):
            res += "|\n"
            nb_frames += 1
        res += "|K20|\n"  # space
        nb_frames += 1
        if "Speedrun" in level_data and "demo" in level_data["Speedrun"]:
            demo_str = level_data["Speedrun"]["demo"]
            libtas_input, nb_frames_demo = convert_demo_to_libtas(demo_str)
            res += libtas_input
            nb_frames += nb_frames_demo
            res += "|K20|\n"  # space
            nb_frames += 1
    return res, nb_frames


if __name__ == "__main__":
    libtas_input, nb_frames = build_libtas_input()
    print(libtas_input)
    # print("nb_frames: %s" % nb_frames)
