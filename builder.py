#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import getopt
import yaml
import configparser
from string import Template

from converter import convert_demo_to_libtas


def usage():
    print(f"Usage: {sys.argv[0]} [-e END_EPISODE|-s START_EPISODE|-r|-h]")
    print("-r: build RTA scores")
    print("-h: print this help")


def start_episode(col, row):
    with open("tas/episode_click_coordinates.yml", "r",
              encoding="utf-8") as f:
        coord = yaml.safe_load(f)
    # On the first frame, press n ("K6e") while moving the mouse to
    # the right coordinates. On the second frame, click on right
    # coordinates
    return f"|K6e|M{coord["column"][col]}:{coord["row"][row]}:A:.....:0|\n|M{coord["column"][col]}:{coord["row"][row]}:A:1....:0|\n|\n"


def build_libtas_input(begin_episode=0, end_episode=99, rta=False, score_type="Speedrun"):
    nb_frames = 0
    res = ""
    markers = {}
    nb_markers = 0
    lua_infos = ""
    initial_wait_frames = 7
    for i in range(initial_wait_frames):
        res += "|\n"
        nb_frames += 1
    start_col = int(begin_episode/10)
    start_row = begin_episode % 10
    res += start_episode(start_col, start_row)
    nb_frames += 3
    if rta:
        level_data_file="tas/level_data_rta.yml"
    else:
        level_data_file="tas/level_data.yml"
    with open(level_data_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    with open("tas/loading_times.yml", "r", encoding="utf-8") as f:
        loading_times = yaml.safe_load(f)

    for level_name, level_data in data.items():
        episode = int(level_name.split("-")[0])
        level = int(level_name.split("-")[1])
        if episode < begin_episode:
            # skip to the beginning
            continue
        elif episode > end_episode:
            # we reached the end
            break
        if loading_times[level_name] is None:
            loading_time = 58  # fill missing ones so as to be able to calculate them with script
        else:
            loading_time = int(loading_times[level_name])
        for i in range(loading_time):
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
            try:
                date = level_data[score_type]['time'].strftime("%Y-%m-%d")
            except AttributeError:
                # for the kryX-orange 25-2 case, which is not a date
                date = level_data[score_type]['time']
            lua_infos += f"    {{{nb_frames}, {nb_frames+nb_frames_demo}, \"{level_data[score_type]['authors']}, {level_data[score_type]['time']}, {date}\"}},\n"
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
                nb_frames += 4
    markers["size"] = nb_markers
    return res, nb_frames, markers, lua_infos


def parse_args():
    starting_episode = 0
    end_episode = 99
    rta = False
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'e:hrs:')
    except getopt.GetoptError as err:
        print("Error: ", str(err))
        sys.exit(1)

    for o, arg in opts:
        if o == '-e':
            end_episode = int(arg)
        if o == '-r':
            rta = True
        if o == '-s':
            starting_episode = int(arg)
        if o == '-h':
            usage()
    return starting_episode, end_episode, rta


if __name__ == "__main__":
    starting_episode, end_episode, rta = parse_args()
    config = configparser.ConfigParser(strict=False, delimiters=('='), interpolation=None)
    config.read("extract/editor.ini")
    libtas_input, nb_frames, markers, lua_infos = build_libtas_input(starting_episode, end_episode, rta=rta, score_type="Speedrun")
    with open("extract/inputs", "w") as f:
        print(libtas_input, file=f)
    with open("extract/editor.ini", "w") as f:
        config["markers"] = markers
        config.write(f, space_around_delimiters=False)
    with open("display_infos.lua.template") as f:
        template = Template(f.read())
    lua_script_filled = template.substitute(infos=lua_infos)
    with open("volume/lua/display_infos.lua", "w") as f:
        print(lua_script_filled, file=f)
