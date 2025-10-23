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
"""
    return inputs


def build_libtas_input(episode, level, score_type="Speedrun"):
    nb_frames = 0
    res = ""
    markers = {}
    nb_markers = 0
    lua_infos = ""
    initial_wait_frames = 7
    for i in range(initial_wait_frames):
        res += "|\n"
        nb_frames += 1
    res += start_level(episode, level)
    nb_frames += 6
    with open("tas/loading_times.yml", "r", encoding="utf-8") as f:
        loading_times = yaml.safe_load(f)
        for i in range(loading_times[f"{episode}-{level}"]):
            res += "|\n"
            nb_frames += 1
    res += "|K20|\n"  # space
    nb_frames += 1
    return res, nb_frames, markers


if __name__ == "__main__":
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)
    episode = sys.argv[1].split('-')[0]
    level = sys.argv[1].split('-')[1]
    libtas_input, nb_frames, markers = build_libtas_input(episode, level, "Speedrun")
    config = configparser.ConfigParser(strict=False, delimiters=('='), interpolation=None)
    with open("extract/inputs", "w") as f:
        print(libtas_input, file=f)
    config.read("extract/editor.ini")
    with open("extract/editor.ini", "w") as f:
        config["markers"] = markers
        config.write(f, space_around_delimiters=False)
    config.read("extract/config.ini")
    with open("extract/config.ini", "w") as f:
        config["General"]["rerecord_count"] = "0"
        config.write(f, space_around_delimiters=False)
