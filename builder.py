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


def build_libtas_input(begin_episode=0, end_episode=99):
    nb_frames = 0
    res = ""
    # initial_wait_frames = 7
    # We need to add additional lag frames because ruffle in libTAS is
    # currently broken
    initial_wait_frames = 15
    for i in range(initial_wait_frames):
        res += "|\n"
        nb_frames += 1
    start_col = int(begin_episode/10)
    start_row = begin_episode % 10
    res += start_episode(start_col, start_row)
    nb_frames += 2
    with open("tas/level_data.yml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for level_name, level_data in data.items():
        if int(level_name.split("-")[0]) < begin_episode:
            # skip to the beginning
            continue
        elif int(level_name.split("-")[0]) > end_episode:
            # we reached the end
            break
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
    libtas_input, nb_frames = build_libtas_input(0, 0)
    print(libtas_input)
