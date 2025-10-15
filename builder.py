#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import yaml
import configparser

from converter import convert_demo_to_libtas


def start_episode(col, row):
    with open("tas/episode_click_coordinates.yml", "r",
              encoding="utf-8") as f:
        coord = yaml.safe_load(f)
    # On the first frame, press n ("K6e") while moving the mouse to
    # the right coordinates. On the second frame, click on right
    # coordinates
    return f"|K6e|M{coord["column"][col]}:{coord["row"][row]}:A:.....:0|\n|M{coord["column"][col]}:{coord["row"][row]}:A:1....:0|\n"


def build_libtas_input(begin_episode=0, end_episode=99, rta=False, score_type="Speedrun"):
    nb_frames = 0
    res = ""
    markers = {}
    nb_markers = 0
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
    if rta:
        level_data_file="tas/level_data_rta.yml"
    else:
        level_data_file="tas/level_data.yml"
    with open(level_data_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for level_name, level_data in data.items():
        episode = int(level_name.split("-")[0])
        level = int(level_name.split("-")[1])
        if episode < begin_episode:
            # skip to the beginning
            continue
        elif episode > end_episode:
            # we reached the end
            break
        for i in range(level_data["loading_time"]):
            res += "|\n"
            nb_frames += 1
        res += "|K20|\n"  # space
        nb_frames += 1
        if score_type in level_data and "demo" in level_data[score_type]:
            nb_markers += 1
            markers[f"{nb_markers}\\frame"] = nb_frames
            markers[f"{nb_markers}\\text"] = level_name
            demo_str = level_data[score_type]["demo"]
            libtas_input, nb_frames_demo = convert_demo_to_libtas(demo_str)
            res += libtas_input
            nb_frames += nb_frames_demo
            res += "|K20|\n"  # space
            nb_frames += 1
        if int(level_name.split("-")[1]) == 4:
            # pass end of episode screen
            res += "|\n|K20|\n"
            nb_frames += 2
            if episode % 10 == 9 and episode < end_episode:
                res += "|\n"
                res += start_episode(int((episode + 1) / 10), 0)
                nb_frames += 3
    markers["size"] = nb_markers
    return res, nb_frames, markers


if __name__ == "__main__":
    config = configparser.ConfigParser(strict=False, delimiters=('='), interpolation=None)
    config.read("extract/editor.ini")
    libtas_input, nb_frames, markers = build_libtas_input(0, 99, rta=True, score_type="Highscore")
    print(libtas_input)
    with open("extract/editor.ini", "w") as f:
        config["markers"] = markers
        config.write(f, space_around_delimiters=False)
