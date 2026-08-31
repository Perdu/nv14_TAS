#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Extract demo data from the sol file
# Usage: python sol_to_demo.py
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

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString


SCRIPT_DIR = Path(__file__).resolve().parent
SOL_FILE_LOCATION = SCRIPT_DIR / 'volume' / 'n_tas.sol'
DEMO_DATA_FILE = SCRIPT_DIR / 'tas' / 'level_data.yml'
RTA_DEMO_DATA_FILE = SCRIPT_DIR / 'tas' / 'level_data_rta.yml'
LEVEL_DATA_FILE = SCRIPT_DIR / 'external' / 'N v1.4 + NReality levels.txt'
OPTIMIZER_DIR = SCRIPT_DIR / 'tas optimiser'
DEFAULT_OPTIMIZATION_LEVEL = 2
TICKS_PER_SECOND = 40
INITIAL_TIME_TICKS = 90 * TICKS_PER_SECOND
GOLD_BONUS_TICKS = 2 * TICKS_PER_SECOND
LEVEL_ID_RE = re.compile(r'^(\d{1,2})-([0-4])$')


class NHighError(Exception):
    pass


class FixedThreeFloat(float):
    """A YAML float which is always emitted with three decimal places."""


def _represent_fixed_three(representer, value):
    return representer.represent_scalar(
        'tag:yaml.org,2002:float', f"{value:.3f}"
    )

def usage(ret_code):
    print(f"Usage: python {sys.argv[0]} [-h|-s|--save|-g|--highscore] [-a|--authors AUTHORS] [-o|--optimization-level LEVEL] LEVEL")
    print("-h: print this help")
    print("-s|--save: save extracted demo data to tas/level_data.yml")
    print("-g|--highscore: save as highscore instead of speedrun")
    print("-a|--authors AUTHORS: change authors")
    print("-o|--optimization-level LEVEL: change optimization level")
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


def get_replay_string(demo):
    """Return the final complex-replay field from a raw or combined demo."""
    replay = demo.strip().rstrip('#').rsplit('#', 1)[-1]
    if not re.match(r'^\d+:', replay):
        raise NHighError('Could not find a complex replay in the demo data')
    return replay


def get_demo_frame_count(demo):
    replay = get_replay_string(demo)
    try:
        frame_text, packed_words = replay.split(':', 1)
        number_of_frames = int(frame_text)
        words = [int(word) for word in packed_words.split('|') if word != '']
    except (TypeError, ValueError) as exc:
        raise NHighError('Replay has invalid frame or packed-input data') from exc
    required_words = (number_of_frames + 6) // 7
    if number_of_frames < 0 or len(words) < required_words:
        raise NHighError('Replay has invalid packed input data')
    return number_of_frames


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
            'The SOL does not contain a usable highscore and the optimiser '
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


def save_demo(
    demo,
    episode,
    level,
    score_type="Speedrun",
    authors='zapkt',
    optimization_level=None,
    highscore_ticks=None,
):
    yaml = YAML()
    yaml.preserve_quotes = True  # keep existing quoting
    yaml.width = 8192  # prevent line wrapping
    yaml.representer.add_representer(FixedThreeFloat, _represent_fixed_three)
    with open(DEMO_DATA_FILE, 'r', encoding='utf-8') as f:
        data = yaml.load(f)
    level_id = f"{episode}-{level}"
    number_of_frames = get_demo_frame_count(demo)

    # Calculate difference with rta
    with open(RTA_DEMO_DATA_FILE, 'r', encoding='utf-8') as f:
        data_rta = yaml.load(f)
    if level_id not in data_rta or score_type not in data_rta[level_id]:
        raise NHighError(
            f'{RTA_DEMO_DATA_FILE} has no {score_type} record for {level_id}'
        )
    if score_type == "Speedrun":
        score = f"{number_of_frames} f"
        score_diff = int(str(data_rta[level_id][score_type]["time"]).split(" ", 1)[0])
        difference = score_diff - number_of_frames
        diff_s = 0.025 * difference
        diff_str_total = f"{difference} f ({diff_s:.3f})"
        score_decimal = None
    elif score_type == "Highscore":
        if highscore_ticks is None:
            highscore_ticks = emulate_highscore_ticks(demo)
        score_decimal = Decimal(highscore_ticks) / TICKS_PER_SECOND
        rta_score = parse_decimal_score(
            data_rta[level_id][score_type]["time"],
            f'RTA highscore for {level_id}',
        )
        lead = score_decimal - rta_score
        score = FixedThreeFloat(score_decimal)
        diff_str_total = FixedThreeFloat(lead)
    else:
        raise NHighError(f'Unknown score type: {score_type}')

    if (
        score_type == "Highscore"
        and level_id in data
        and "Highscore" not in data[level_id]
        and "Highsore" in data[level_id]
    ):
        print(f'Correcting misspelled Highsore key for {level_id}.')
        data[level_id]["Highscore"] = data[level_id].pop("Highsore")
    if level_id in data and score_type in data[level_id]:
        existing_record = data[level_id][score_type]
        # Recreating a dict to ensure we insert optimization_level at the right place
        # (because order depends on insert in dict)
        if authors == "zapkt":
            # Don't override authors list if default
            new_authors = existing_record.get("authors", authors)
        else:
            new_authors = authors
        if optimization_level is not None:
            new_optimization_level = optimization_level
        else:
            new_optimization_level = existing_record.get(
                "optimization_level", DEFAULT_OPTIMIZATION_LEVEL
            )
        if score_type == "Speedrun":
            saved_score = int(str(existing_record["time"]).split()[0])
            if saved_score < number_of_frames:
                print(f"Error: saved level already has a better score ({saved_score}). Not saving.")
                return False
        else:
            saved_score, score_prefix = parse_saved_highscore(
                existing_record["time"],
                f'Saved highscore for {level_id}',
            )
            if saved_score > score_decimal:
                print(
                    f"Error: saved level already has a better highscore "
                    f"({saved_score:.3f}). Not saving."
                )
                return False
            if score_prefix is not None:
                score = f'{score_prefix}{score_decimal:.3f}'
        new_dict = {
            "time": score,
            'diff_with_0th': diff_str_total,
            "authors": new_authors,
            "type": "tas",
            "optimization_level": new_optimization_level,
            "demo": LiteralScalarString(demo)
        }
        # Retain secondary demos and any other archive metadata not managed by
        # this script.  Rebuilding the standard keys must not delete them.
        for key, value in existing_record.items():
            if key not in new_dict:
                new_dict[key] = value
        data[level_id][score_type] = new_dict
    else:
        if level_id in data:
            level_data = data[level_id]
        else:
            level_data = {}
        if optimization_level is not None:
            new_optimization_level = optimization_level
        else:
            new_optimization_level = DEFAULT_OPTIMIZATION_LEVEL
        new_record = {
            'time': score,
            'diff_with_0th': diff_str_total,
            'authors': authors,
            'type': 'tas',
            'optimization_level': new_optimization_level,
            'demo': LiteralScalarString(demo),
        }
        if score_type == 'Highscore' and hasattr(level_data, 'insert'):
            level_data.insert(0, score_type, new_record)
        else:
            level_data[score_type] = new_record
        data[level_id] = level_data

    data = {k: data[k] for k in sorted(data.keys())}

    # --- Dump to string first ---
    import io
    buf = io.StringIO()
    yaml.dump(data, buf)
    lines = buf.getvalue().splitlines()

    # --- Insert blank line after demo blocks ---
    block_start_re = re.compile(r'^\s*[^:]+:\s*\|[+-]?\s*(?:#.*)?$')
    result_lines = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        result_lines.append(line)

        # If this line starts a literal block (demo: |  or demo: |+ / |-)
        if block_start_re.match(line):
            key_indent = len(line) - len(line.lstrip(' '))
            # next line must exist and be more indented than the key (block content)
            if i + 1 < n:
                next_line = lines[i + 1]
                next_leading = len(next_line) - len(next_line.lstrip(' '))
                if next_leading > key_indent:
                    # find the end of the block: all following lines that are indented > key_indent
                    j = i + 1
                    while j + 1 < n:
                        nl = lines[j + 1]
                        nl_leading = len(nl) - len(nl.lstrip(' '))
                        # an "indented" blank line (i.e. with spaces) counts as inside the block;
                        # an empty line with no indent is considered outside the block.
                        if nl.strip() == "":
                            if nl_leading <= key_indent:
                                break
                            else:
                                j += 1
                                continue
                        if nl_leading > key_indent:
                            j += 1
                        else:
                            break
                    # append the block content lines (we already appended the block-start)
                    for k in range(i + 1, j + 1):
                        result_lines.append(lines[k])
                    # if the block was a single-line block (only one content line),
                    # ensure exactly one blank line AFTER the block (but don't duplicate).
                    if j == i + 1:
                        if not (j + 1 < n and lines[j + 1].strip() == ""):
                            result_lines.append("")
                    # advance i to the last line of the block (we already appended them)
                    i = j + 1
                    continue  # go to next iteration without the final i += 1
        i += 1

    # --- Write back to file ---
    with open(DEMO_DATA_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(result_lines) + "\n")
    # print(f"Updated {DEMO_DATA_FILE}")

    print()
    if score_type == "Speedrun":
        print(f"Difference with 0th: {difference} f ({diff_s:.3f})")
    else:
        print(f"Highscore: {score_decimal:.3f}")
        print(f"Lead over 0th: {lead:.3f}")
    return True


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
    try:
        opts, args = getopt.getopt(
            argv,
            'a:ghso:',
            ["save", "highscore", 'author=', 'authors=', 'optimization-level='],
        )
    except getopt.GetoptError as err:
        print("Error: ", str(err))
        return 1
    for o, arg in opts:
        if o == '-h':
            usage(0)
        elif o == '-s' or o == '--save':
            save = True
        elif o == '-g' or o =='--highscore':
            score_type = "Highscore"
        elif o == '-a' or o =='--author' or o == '--authors':
            authors = arg
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
            highscore_ticks, score_source = calculate_highscore_ticks(
                demo_full,
                sol_level.get('score'),
            )
            print(
                f'Highscore: {Decimal(highscore_ticks) / TICKS_PER_SECOND:.3f} '
                f'({score_source})'
            )

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
            )
    except NHighError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
