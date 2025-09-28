#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import yaml

from converter import convert_demo_to_libtas


def click(x, y):
    print("|K6e|M%s:%s:A:.....:0|\n|M%s:%s:A:1....:0|" % (x, y, x, y))


if __name__ == "__main__":
    # initial_wait_frames = 7
    # We need to add additional lag frames because ruffle in libTAS is
    # currently broken
    initial_wait_frames = 15
    for i in range(initial_wait_frames):
        print("|")
    click(310, 103)
    with open("tas/level_data.yml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for level_name, level_data in data.items():
        for i in range(level_data["loading_time"]):
            print("|")
        print("|K20|")  # space
        if "Speedrun" in level_data and "demo" in level_data["Speedrun"]:
            demo_str = level_data["Speedrun"]["demo"]
            print(convert_demo_to_libtas(demo_str))
