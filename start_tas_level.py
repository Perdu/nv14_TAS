#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import getopt
import yaml
import configparser

from converter import convert_demo_to_libtas


def usage():
    print(f"Usage: {sys.argv[0]} LEVEL]")


def start_level(episode, level):
    with open("tas/level_click_coordinates.yml", "r",
              encoding="utf-8") as f:
        coord = yaml.safe_load(f)
    # On the first frame, press y ("K79") while moving the mouse to
    # the right coordinates. On the second frame, click on right
    # coordinates
    col = int(int(episode)/10)
    row = int(episode) % 10
    inputs = f"""|K79|M{coord["column"][col]}:{coord["row"][row]}:A:.....:0|
|M{coord["column"][col]}:{coord["row"][row]}:A:1....:0|
|M{coord["level"]["x"]}:{coord["level"]["y"][int(level)]}:A:.....:0|
|M{coord["level"]["x"]}:{coord["level"]["y"][int(level)]}:A:1....:0|
|M{coord["start"]["x"]}:{coord["start"]["y"]}:A:.....:0|
|M{coord["start"]["x"]}:{coord["start"]["y"]}:A:1....:0|
|
"""
    return inputs


def build_libtas_input(episode, level, score_type="Speedrun", add_rta_run=False, add_hs_run=False):
    nb_frames = 0
    res = ""
    markers = {}
    nb_markers = 0
    lua_infos = ""
    initial_wait_frames = 7
    # Insert all input frames
    for i in range(initial_wait_frames):
        res += "|\n"
        nb_frames += 1
    res += start_level(episode, level)
    nb_frames += 7
    with open("tas/loading_times.yml", "r", encoding="utf-8") as f:
        loading_times = yaml.safe_load(f)
        for i in range(loading_times[f"{episode}-{level}"]):
            res += "|\n"
            nb_frames += 1
    res += "|K20|\n"  # space
    nb_frames += 1
    init_frames = nb_frames

    # Now extract meaningful information from the rta run
    with open("tas/level_data_rta.yml", "r", encoding="utf-8") as f:
        rta_data = yaml.safe_load(f)
    with open("tas/level_data.yml", "r", encoding="utf-8") as f:
        tas_data = yaml.safe_load(f)
    level_name = f"{episode}-{level}"
    rta_time = rta_data[level_name][score_type]['time']
    demo = rta_data[level_name][score_type]['demo']
    libtas_input_rta, nb_frames_demo_rta = convert_demo_to_libtas(demo)
    if level_name in tas_data:
        for score in tas_data[level_name]:
            print(f"{score} TAS exists")
    if add_rta_run:
        res += libtas_input_rta
        nb_frames += nb_frames_demo_rta
    elif add_hs_run:
        if "Highscore" not in tas_data[level_name]:
            print("Error: no known highscore TAS for this level")
        else:
            demo_hs = tas_data[level_name]["Highscore"]['demo']
            libtas_input_hs, nb_frames_demo_hs = convert_demo_to_libtas(demo_hs)
            res += libtas_input_hs
            nb_frames += nb_frames_demo_hs
    elif level_name in tas_data and score_type in tas_data[level_name]:
        # A TAS already exists
        print("Using existing TAS data")
        demo = tas_data[level_name][score_type]['demo']
        libtas_input, nb_frames_demo = convert_demo_to_libtas(demo)
        res += libtas_input
        nb_frames += nb_frames_demo
        while nb_frames < init_frames + nb_frames_demo_rta:
            res += "|\n"
            nb_frames += 1
    else:
        for i in range(rta_time):
            res += "|\n"
            nb_frames += 1
    # additional frame to trigger the exit
    res += "|\n|\n|\n"
    nb_frames += 3
    nb_markers += 1
    markers[f"{nb_markers}\\frame"] = init_frames + nb_frames_demo_rta + 2
    markers[f"{nb_markers}\\text"] = f"RTA score ({rta_time})"
    markers["size"] = nb_markers
    return res, nb_frames, markers


if __name__ == "__main__":
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)
    episode = sys.argv[1].split('-')[0]
    level = sys.argv[1].split('-')[1]
    rta_run = False
    hs_run = False
    if len(sys.argv) > 2:
        if sys.argv[2] == 'rta':
            rta_run = True
        elif sys.argv[2] == 'hs':
            hs_run = True
    libtas_input, nb_frames, markers = build_libtas_input(episode, level, "Speedrun", rta_run, hs_run)
    config = configparser.ConfigParser(strict=False, delimiters=('='), interpolation=None)
    with open("extract/inputs", "w") as f:
        print(libtas_input, file=f)
    config.read("extract/editor.ini")
    with open("extract/editor.ini", "w") as f:
        config["markers"] = markers
        config.write(f, space_around_delimiters=False)
    config = configparser.ConfigParser(strict=False, delimiters=('='), interpolation=None)
    config.read("extract/config.ini")
    with open("extract/config.ini", "w") as f:
        config["General"]["rerecord_count"] = "0"
        config.write(f, space_around_delimiters=False)
