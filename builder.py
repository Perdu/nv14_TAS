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
    print("|K6e|M%s:%s:A:.....:0|\n|M%s:%s:A:1....:0|" %
          (coord["column"][col], coord["row"][row],
           coord["column"][col], coord["row"][row]))


if __name__ == "__main__":
    # initial_wait_frames = 7
    # We need to add additional lag frames because ruffle in libTAS is
    # currently broken
    initial_wait_frames = 15
    for i in range(initial_wait_frames):
        print("|")
    start_episode(0, 0)
    with open("tas/level_data.yml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for level_name, level_data in data.items():
        for i in range(level_data["loading_time"]):
            print("|")
        print("|K20|")  # space
        if "Speedrun" in level_data and "demo" in level_data["Speedrun"]:
            demo_str = level_data["Speedrun"]["demo"]
            print(convert_demo_to_libtas(demo_str))
