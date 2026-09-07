import re
from decimal import Decimal
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

SCRIPT_DIR = Path(__file__).resolve().parent
DEMO_DATA_FILE = SCRIPT_DIR / 'tas' / 'level_data.yml'
RTA_DEMO_DATA_FILE = SCRIPT_DIR / 'tas' / 'level_data_rta.yml'
DEFAULT_OPTIMIZATION_LEVEL = 2
TICKS_PER_SECOND = 40


class FixedThreeFloat(float):
    """A YAML float which is always emitted with three decimal places."""


def _represent_fixed_three(representer, value):
    return representer.represent_scalar(
        'tag:yaml.org,2002:float', f"{value:.3f}"
    )


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


def get_replay_string(demo):
    """Return the final complex-replay field from a raw or combined demo."""
    replay = demo.strip().rstrip('#').rsplit('#', 1)[-1]
    if not re.match(r'^\d+:', replay):
        raise NHighError('Could not find a complex replay in the demo data')
    return replay


def save_demo(
    demo,
    episode,
    level,
    score_type="Speedrun",
    authors='zapkt',
    optimization_level=None,
    highscore_ticks=None,
    preserve_default_authors=True,
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
        if authors is None or preserve_default_authors:
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
            "optimization_level": new_optimization_level,
            "demo": LiteralScalarString(demo)
        }
        if authors is None and 'authors' not in existing_record:
            del new_dict['authors']
        # Retain secondary demos, any existing type, and other archive metadata
        # not managed by this script.  Do not add or overwrite a type value.
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
            'optimization_level': new_optimization_level,
            'demo': LiteralScalarString(demo),
        }
        if authors is None:
            del new_record['authors']
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
