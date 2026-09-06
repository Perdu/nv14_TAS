#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Extract demo data from the sol file or an explicitly supplied replay
# Usage: python sol_to_demo.py
# Interactive replay: python sol_to_demo.py -r --hs -s 56-2
# Disable "Prevent writing to disk" in libTAS to obtain TASed sol file

# Credits: SolReader class is taken from NHigh by jg9000 (+ modified)
# Some parts are AI-generated


import sys
import struct
import getopt
import re
import tarfile
import configparser
from decimal import Decimal, InvalidOperation
from itertools import chain
from pathlib import Path
from tempfile import gettempdir

from lib import save_demo, get_demo_frame_count, get_replay_string


SCRIPT_DIR = Path(__file__).resolve().parent
SOL_FILE_LOCATION = SCRIPT_DIR / 'volume' / 'n_tas.sol'
LEVEL_DATA_FILE = SCRIPT_DIR / 'external' / 'N v1.4 + NReality levels.txt'
OPTIMIZER_DIR = SCRIPT_DIR / 'tas optimiser'
DEFAULT_OPTIMIZATION_LEVEL = 2
TICKS_PER_SECOND = 40
INITIAL_TIME_TICKS = 90 * TICKS_PER_SECOND
GOLD_BONUS_TICKS = 2 * TICKS_PER_SECOND
LEVEL_ID_RE = re.compile(r'^(\d{1,2})-([0-4])$')


class NHighError(Exception):
    pass


def usage(ret_code):
    print(f"Usage: python {sys.argv[0]} [-r] [--hs|-g|--highscore] [-s|--save] [-a|--authors AUTHORS] [-o|--optimization-level LEVEL] LEVEL")
    print("-h|--help: print this help")
    print("-s|--save: save extracted demo data to tas/level_data.yml")
    print("--hs|-g|--highscore: save as highscore instead of speedrun")
    print("-a|--authors AUTHORS: change authors in SOL mode")
    print("-o|--optimization-level LEVEL: change optimization level")
    print("-r|--r|--replay: prompt for Demo and Authors on stdin instead of reading the SOL")
    print("Paste the demo on one line; press Enter at Authors to preserve saved authors.")
    print("Replay inputs accept a full level+replay or raw FRAME_COUNT:PACKED_INPUTS.")
    print("Put options before LEVEL. In SOL mode, authors default to the LTM authors.")
    print("Replay highscore mode requires the emulator in 'tas optimiser/'.")
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


def read_replay_input(replay_data, episode, level):
    """Validate pasted replay data without consulting the SOL."""
    text = replay_data.strip().lstrip('\ufeff').strip()
    demo = get_replay_string(text)
    if re.fullmatch(r'[0-9]+:[0-9]+(?:\|[0-9]+)*\|?', demo) is None:
        raise NHighError('Replay has invalid frame or packed-input data')
    get_demo_frame_count(demo)
    if any(int(word) > 0xffffffff for word in demo.split(':', 1)[1].split('|') if word):
        raise NHighError('Replay packed input words must fit in 32 bits')

    if text.startswith('$'):
        fields = text.rstrip('#').split('#')
        if (
            len(fields) != 5
            or '|' not in fields[3]
            or len(fields[3].split('|', 1)[0]) != 31 * 23
        ):
            raise NHighError('Replay has an invalid embedded level record')
        # Optimiser exports may omit the title; LEVEL remains the save key.
        level_data = '#'.join(fields[:-1]) + '#'
    elif '#' in text.rstrip('#'):
        raise NHighError('Replay has an invalid combined level/replay format')
    else:
        level_data = get_level_data(episode, level)
    return demo, f'{level_data}{demo}#'


def parse_decimal_score(value, description):
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise NHighError(f'{description} is not a numeric score: {value!r}') from exc
    if not result.is_finite():
        raise NHighError(f'{description} is not a finite score: {value!r}')
    return result


def parse_saved_highscore(value, description):
    """Parse a numeric score while preserving an archive route qualifier."""
    try:
        return parse_decimal_score(value, description), None
    except NHighError as numeric_error:
        text = str(value).strip()
        match = re.fullmatch(
            r'(?P<prefix>.+?,\s*)(?P<score>[+-]?(?:\d+(?:\.\d*)?|\.\d+))',
            text,
        )
        if match is None:
            raise numeric_error
        return (
            parse_decimal_score(match.group('score'), description),
            match.group('prefix'),
        )


def highscore_ticks_from_sol(raw_score, number_of_frames):
    """Return a trustworthy integral SOL score, or None for placeholders."""
    if isinstance(raw_score, bool) or raw_score is None:
        return None
    try:
        score = Decimal(str(raw_score))
    except (InvalidOperation, ValueError):
        return None
    if not score.is_finite() or score != score.to_integral_value():
        return None
    score_ticks = int(score)
    if score_ticks <= 0:
        return None

    # N stores the absolute timer score in 1/40-second ticks.  A matching
    # replay must imply a whole, non-negative number of two-second gold awards.
    implied_gold_bonus = score_ticks + number_of_frames - INITIAL_TIME_TICKS
    if implied_gold_bonus < 0 or implied_gold_bonus % GOLD_BONUS_TICKS:
        return None
    return score_ticks


def emulate_highscore_ticks(demo):
    """Calculate the absolute highscore with the optimiser's emulator."""
    if not OPTIMIZER_DIR.is_dir():
        raise NHighError(
            'Highscore calculation requires the optimiser emulator, but its '
            f'directory was not found: {OPTIMIZER_DIR}'
        )

    optimizer_path = str(OPTIMIZER_DIR)
    if optimizer_path in sys.path:
        sys.path.remove(optimizer_path)
    sys.path.insert(0, optimizer_path)
    expected_module_dir = OPTIMIZER_DIR.resolve()
    for module_name in ('nv14_engine', 'nv14_replay'):
        loaded_module = sys.modules.get(module_name)
        loaded_path = getattr(loaded_module, '__file__', None)
        if loaded_path is not None and Path(loaded_path).resolve().parent != expected_module_dir:
            raise NHighError(
                f'Conflicting {module_name} module is already loaded from '
                f'{Path(loaded_path).resolve()}'
            )
    try:
        from nv14_engine import InputFrame, parse_level_string
        from nv14_replay import (
            decode_complex_replay,
            parse_combined_level_replay,
        )
    except (ImportError, OSError) as exc:
        raise NHighError(
            f'Could not import the optimiser emulator from {OPTIMIZER_DIR}: {exc}'
        ) from exc

    try:
        combined = parse_combined_level_replay(demo)
        level = parse_level_string(
            combined.level_string,
            simulate_enemies=True,
        )
        replay = decode_complex_replay(combined.replay_string)
        # Packed trigger bits are part of the recorded replay and are the
        # source of truth during verification.  Re-deriving them from held
        # jump edges can change historical runs.
        frames = replay.frames
        state = level.initial_state()
        for finish_tick, frame in enumerate(chain(frames, (InputFrame(),))):
            state.step(frame, level.tiles)
            # N permits completion and death on the same simulation tick.
            if state.level_complete:
                return (
                    INITIAL_TIME_TICKS
                    + state.static_state.gold_bonus_ticks
                    - finish_tick
                )
            if state.player.dead:
                raise NHighError(
                    f'Highscore replay dies before completion at tick {finish_tick}'
                )
    except NHighError:
        raise
    except (RuntimeError, TypeError, ValueError) as exc:
        raise NHighError(f'Could not emulate the highscore replay: {exc}') from exc
    raise NHighError('Highscore replay does not complete in the optimiser emulator')


def calculate_highscore_ticks(demo, raw_sol_score):
    number_of_frames = get_demo_frame_count(demo)
    score_ticks = highscore_ticks_from_sol(raw_sol_score, number_of_frames)
    if score_ticks is not None:
        return score_ticks, 'stored SOL score'
    print('Stored SOL highscore is unavailable or inconsistent; emulating replay...')
    return emulate_highscore_ticks(demo), 'optimiser emulation'


def print_to_tmp(demo_full, episode, level):
    output_path = Path(gettempdir()) / f"{episode}-{level}.txt"
    with output_path.open('w', encoding='utf-8') as f:
        f.write(demo_full + "\n")


def get_level_data(episode, level):
    level_id = f"{episode}-{level}"
    prefix = f"${level_id} "
    try:
        with open(LEVEL_DATA_FILE, 'r', encoding='utf-8-sig') as f:
            matches = [
                line.rstrip('\r\n')
                for line in f
                if line.startswith(prefix)
            ]
    except (OSError, UnicodeError) as exc:
        raise NHighError(f'Could not read level data from {LEVEL_DATA_FILE}') from exc
    if not matches:
        raise NHighError(f'Level {level_id} was not found in {LEVEL_DATA_FILE}')
    if len(matches) != 1:
        raise NHighError(
            f'Level {level_id} occurs {len(matches)} times in {LEVEL_DATA_FILE}'
        )

    record = matches[0]
    fields = record.split('#')
    level_fields = [
        field for field in fields
        if '|' in field and len(field.split('|', 1)[0]) == 31 * 23
    ]
    if not record.endswith('#') or len(level_fields) != 1:
        raise NHighError(f'Level record for {level_id} has an invalid format')
    return record


def get_ltm_path(level, score_type):
    levels_dir = SCRIPT_DIR / 'volume' / 'n_levels'
    ltm_path = levels_dir / (
        f'{level}_hs.ltm' if score_type == 'Highscore' else f'{level}.ltm'
    )
    if ltm_path.is_file():
        return ltm_path
    raise NHighError(f'LTM file not found: {ltm_path}')


def get_authors_from_ltm_file(level, score_type):
    config = configparser.ConfigParser(
        strict=False,
        delimiters=('=',),
        interpolation=None,
    )
    ltm_path = get_ltm_path(level, score_type)
    try:
        # Read config.ini directly from the LTM without extracting the archive.
        with tarfile.open(ltm_path, "r:*") as tar:
            member = tar.getmember("config.ini")
            extracted = tar.extractfile(member)
            if extracted is None:
                raise NHighError(f'Could not read config.ini from {ltm_path}')
            with extracted:
                config_data = extracted.read().decode("utf-8")
    except (KeyError, OSError, tarfile.TarError, UnicodeError) as exc:
        raise NHighError(f'Could not read config.ini from {ltm_path}: {exc}') from exc
    config.read_string(config_data)
    try:
        return config["General"]["authors"].strip().strip('"')
    except KeyError as exc:
        raise NHighError(f'{ltm_path} config.ini has no General.authors value') from exc


def parse_level_id(value):
    match = LEVEL_ID_RE.fullmatch(value)
    if match is None:
        raise NHighError('LEVEL must have the form NN-N, with level 0 through 4')
    episode_number = int(match.group(1))
    if episode_number > 99:
        raise NHighError('The SOL contains official episodes 00 through 99 only')
    episode = f'{episode_number:02d}'
    level = match.group(2)
    return episode, level, f'{episode}-{level}'


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    save = False
    score_type = "Speedrun"
    optimization_level = DEFAULT_OPTIMIZATION_LEVEL
    authors = None
    interactive_replay = False
    try:
        opts, args = getopt.getopt(
            argv,
            'a:ghso:r',
            ["save", "highscore", 'hs', 'author=', 'authors=', 'optimization-level=',
             'help', 'r', 'replay'],
        )
    except getopt.GetoptError as err:
        print("Error: ", str(err))
        return 1
    for o, arg in opts:
        if o in ('-h', '--help'):
            usage(0)
        elif o == '-s' or o == '--save':
            save = True
        elif o in ('--hs', '-g', '--highscore'):
            score_type = "Highscore"
        elif o == '-a' or o == '--author' or o == '--authors':
            authors = arg
        elif o in ('-r', '--r', '--replay'):
            interactive_replay = True
        elif o == '-o' or o == '--optimization-level':
            try:
                optimization_level = int(arg)
            except ValueError:
                print(f'Error: invalid optimization level: {arg!r}', file=sys.stderr)
                return 1
    if len(args) != 1:
        usage(1)
    try:
        episode, level, level_id = parse_level_id(args[0])
        if interactive_replay:
            if authors is not None:
                raise NHighError('With -r, enter authors at the prompt instead of using --authors')
            try:
                replay_data = input('Demo: ')
                authors = input('Authors (enter to leave unchanged): ').strip() or None
            except EOFError as exc:
                raise NHighError('Input ended before both prompts were answered') from exc
            demo, demo_full = read_replay_input(replay_data, episode, level)
        else:
            if authors is None:
                authors = get_authors_from_ltm_file(level_id, score_type)
            sol_data = readSolFile()
            try:
                sol_level = sol_data['persBest'][int(episode)]['lev'][int(level)]
                demo = sol_level['demo']
            except (KeyError, IndexError, TypeError) as exc:
                raise NHighError(f'The SOL has no replay for {level_id}') from exc
            if not isinstance(demo, str) or not demo:
                raise NHighError(f'The SOL replay for {level_id} is empty')

            level_data = get_level_data(episode, level)
            demo_full = f"{level_data}{demo}#"
        highscore_ticks = None
        if score_type == 'Highscore':
            if interactive_replay:
                print('Calculating replay highscore with the optimiser emulator...')
                highscore_ticks = emulate_highscore_ticks(demo_full)
                score_source = 'optimiser emulation'
            else:
                highscore_ticks, score_source = calculate_highscore_ticks(
                    demo_full,
                    sol_level.get('score'),
                )
            print(
                f'Highscore: {Decimal(highscore_ticks) / TICKS_PER_SECOND:.3f} '
                f'({score_source})'
            )

        if not interactive_replay:
            print(demo)
            print()
            print(demo_full)
        print_to_tmp(demo_full, episode, level)
        if save:
            save_demo(
                demo_full,
                episode,
                level,
                score_type=score_type,
                authors=authors,
                optimization_level=optimization_level,
                highscore_ticks=highscore_ticks,
                preserve_default_authors=not interactive_replay,
            )
    except NHighError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
