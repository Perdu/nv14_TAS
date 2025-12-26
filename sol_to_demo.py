#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Extract demo data from the sol file
# Usage: python sol_to_demo.py
# Disable "Prevent writing to disk" in libTAS to obtain TASed sol file

# Credits: SolReader class is taken from NHigh by jg9000 (+ modified)


import sys
import struct
import getopt
import re
from ruamel.yaml import YAML

from converter import extract_chunks


SOL_FILE_LOCATION = 'volume/n_tas.sol'
DEMO_DATA_FILE = 'tas/level_data.yml'
RTA_DEMO_DATA_FILE = 'tas/level_data_rta.yml'
LEVEL_DATA_FILE = 'external/level_build_data.yml'
OPTIMIZATION_LEVEL = 2

def usage(ret_code):
    print(f"Usage: python {sys.argv[0]} [-h|-s|--save|-g|--highscore|-a|--authors] LEVEL")
    print("-h: print this help")
    print("-s|--save: save extracted demo data to tas/level_data.yml")
    print("-g|--highscore: save as highscore instead of speedrun")
    print("-a|--authors AUTHORS: change authors")
    sys.exit(ret_code)


class SolReader(object):
    def __init__(self):
        self.readFuncs ={
            0: self.readNumber,
            1: self.readBool,
            2: self.readStr,
            3: self.readObj,
            5: self.readNull,
            6: self.readUndef,
            8: self.readArray,
            #10: self.readRawArr,
            #11: self.readDate,
            #13: self.readObjM,
            #15: self.readObjXML,
            #16: self.readCustomClass,
        }

    def readFromFile(self, size):
        ret = self.f.read(size)
        if len(ret) < size:
            raise EOFError()
        return ret
        
    def readStr(self):
        length, = struct.unpack('>H',self.readFromFile(2))
        if length==0:
            return ''
        s = self.readFromFile(length)
        return s.decode('utf-8')

    def readSol(self, f):
        ret = {}
        try:
            self.f = f
            self.readFromFile(2) #header?
            datasize, = struct.unpack('>L',self.readFromFile(4)) #datasize == filesize-6
            self.readFromFile(4) #filetype=='TCSO' ?
            self.readFromFile(6) #??
            self.readStr() #the .sol name == n_v14b_userdata
            self.readFromFile(4) #??

            while True:
                name = self.readStr()
                val = self.readValue()
                ret[name] = val
                self.readFromFile(1) # == 0
        except EOFError:
            pass
        except (ValueError, TypeError, struct.error):
            raise NHighError('.sol file contains invalid format')
        return ret

    def readNumber(self):
        val, = struct.unpack('>d', self.readFromFile(8))
        return val

    def readBool(self):
        return bool(ord(self.readFromFile(1)))

    def readObj(self):
        ret = {}
        while True:
            name = self.readStr()
            if not name: break
            val = self.readValue()
            ret[name] = val
        self.readFromFile(1) # ==9
        return ret

    def readArray(self):
        length, = struct.unpack('>L',self.readFromFile(4))
        last = -1
        ret = []
        while True:
            name = self.readStr()
            if not name: break
            try:
                now = int(name)
            except ValueError:
                raise NHighError('.sol File contains invalid array object')
            if now != last+1:
                raise NHighError('.sol File contains invalid array object')
            last = now
            ret.append(self.readValue())
        if last != length-1:
            raise NHighError('.sol File contains invalid array object')
        self.readFromFile(1) # ==9
        return ret

    def readNull(self):
        return None

    def readUndef(self):
        return None

    def readValue(self):
        typ = ord(self.readFromFile(1))
        func = self.readFuncs.get(typ)
        if func:
            return func()
        else:
            raise NHighError('.sol File contains unrecognized objects')


def readSolFile():
    filename = SOL_FILE_LOCATION
    if not filename:
        raise NHighError('.sol file not found')
    try:
        f = open(filename, 'rb')
        try:
            return SolReader().readSol(f)
        finally:
            f.close()
    except (IOError,OSError):
        raise NHighError('Error reading .sol file')


def save_demo(demo, episode, level, score_type="Speedrun", authors='zapkt'):
    yaml = YAML()
    yaml.preserve_quotes = True  # keep existing quoting
    yaml.width = 8192  # prevent line wrapping
    with open(DEMO_DATA_FILE, 'r', encoding='utf-8') as f:
        data = yaml.load(f)
    level_id = f"{episode}-{level}"
    chunks, number_of_frames = extract_chunks(demo)
    score = f"{number_of_frames} f"
    if score_type != "Speedrun":
        print("Please manually enter score")
    if level_id in data and score_type in data[level_id]:
        # Recreating a dict to ensure we insert optimization_level at the right place
        # (because order depends on insert in dict)
        new_dict = {
            "time": score,
            # Don't override authors list
            "authors": data[level_id][score_type]["authors"],
            "type": "tas",
            "optimization_level": 2,
            "demo": demo
        }
        saved_score = int(data[level_id][score_type]["time"].split()[0])
        if score_type == "Speedrun" and saved_score < number_of_frames:
            print(f"Error: saved level already has a better score ({saved_score}). Not saving.")
            return
        data[level_id][score_type] = new_dict
    else:
        if level_id in data:
            level_data = data[level_id]
        else:
            level_data = {}
        level_data[score_type] = {'time': score, 'authors': authors, 'type': 'tas', 'optimization_level': OPTIMIZATION_LEVEL, 'demo': demo}
        data[level_id] = level_data

    data = {k: data[k] for k in sorted(data.keys())}

    # --- Dump to string first ---
    import io
    buf = io.StringIO()
    yaml.dump(data, buf)
    lines = buf.getvalue().splitlines()

    # --- Insert blank line after each demo: line if missing ---
    result_lines = []
    i = 0
    while i < len(lines):
        result_lines.append(lines[i])
        if lines[i].strip().startswith("demo:"):
            # If next line exists and is not blank, insert a blank line
            if i + 1 < len(lines) and lines[i + 1].strip() != "":
                result_lines.append("")  # insert one blank line
        i += 1

    # --- Write back to file ---
    with open(DEMO_DATA_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(result_lines) + "\n")
    # print(f"Updated {DEMO_DATA_FILE}")

    # Calculate difference with rta
    with open(RTA_DEMO_DATA_FILE, 'r', encoding='utf-8') as f:
        data_rta = yaml.load(f)
    if score_type == "Speedrun":
        score = int(str(data_rta[level_id][score_type]["time"]).split(" ", 1)[0])
    else:
        score = data_rta[level_id][score_type]["time"]
    difference =  score - number_of_frames
    diff_s = 0.025 * diff
    print()
    print(f"Difference with 0th: {difference} ({diff_s:.3f})")


def print_to_tmp(demo_full, episode, level):
    with open(f"/tmp/{episode}-{level}.txt", 'w', encoding='utf-8') as f:
        f.write(demo_full + "\n")

def get_level_data(episode, level):
    yaml = YAML()
    with open(LEVEL_DATA_FILE, 'r', encoding='utf-8') as f:
        data = yaml.load(f)
    return data[f"{episode}-{level}"]

if __name__ == "__main__":
    save = False
    score_type = "Speedrun"
    authors = 'zapkt'
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'a:ghs', ["save", "highscore", 'author=', 'authors='])
    except getopt.GetoptError as err:
        print("Error: ", str(err))
        sys.exit(1)
    for o, arg in opts:
        if o == '-h':
            usage(0)
        elif o == '-s' or o == '--save':
           save = True
        elif o == '-g' or o =='--highscore':
            score_type = "Highscore"
        elif o == '-a' or o =='--author' or o == '--authors':
            authors = arg
    if not args:
        usage(1)
    episode = args[0].split("-")[0]
    level = args[0].split("-")[1]
    solData = readSolFile()
    demo = solData['persBest'][int(episode)]['lev'][int(level)]['demo']
    print(demo)
    level_data = get_level_data(episode, level)
    demo_full = f"{level_data}{demo}#"
    print()
    print(demo_full)
    print_to_tmp(demo_full, episode, level)
    if save:
        save_demo(demo_full, episode, level, score_type=score_type, authors=authors)
