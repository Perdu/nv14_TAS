#!/usr/bin/env python3
"""Download speedrun or highscore ghosts and encode them with nv14 optimiser 4.19.

Run tools/encode_leaderboard_ghosts.py from the extracted release, or use
python -m tools.encode_leaderboard_ghosts. The bundled optimiser is discovered
relative to this script; --optimizer-dir DIR explicitly selects another copy.
Relative input/output/cache paths use your current working directory.
See docs/LEADERBOARD_GHOSTS.md for the complete guide.
Requires the optimiser's native extension, Pillow and FFmpeg/libx264 for video.
In the extracted optimiser folder, prepare the encoder once:
  python -m pip install ".[video]"
  python build_native.py
Install FFmpeg separately, on PATH or selected with --ffmpeg-path.
The downloader itself uses only the Python standard library.

Examples:
  python tools/encode_leaderboard_ghosts.py "88-4 TAS.txt" -o comparison.mp4
  python tools/encode_leaderboard_ghosts.py run.ltm --levels-file "N v1.4 + NReality levels.txt"
  python tools/encode_leaderboard_ghosts.py run.txt --level 20-0 --alignment exit
  python tools/encode_leaderboard_ghosts.py --download-only
  python tools/encode_leaderboard_ghosts.py "00-0 HS.txt" --mode highscore --level 00-0 --label-position top-left
  python tools/encode_leaderboard_ghosts.py run.txt --mode highscore --exclude-player AnotherName
  python tools/encode_leaderboard_ghosts.py run.txt --mode highscore --exclude-players-file excluded.txt
  python tools/encode_leaderboard_ghosts.py run.txt --offline
  python tools/encode_leaderboard_ghosts.py run.txt --online
  python tools/encode_leaderboard_ghosts.py run.txt --render-workers 4 --replay-cache-dir pose_cache
  python tools/encode_leaderboard_ghosts.py run.txt --render-quality fast
  python tools/encode_leaderboard_ghosts.py run.txt --primary-label "Optimised TAS" --label-size 10
  python tools/encode_leaderboard_ghosts.py run.txt --label-position top-left
  python tools/encode_leaderboard_ghosts.py run.txt --secondary-gold animated

Default: speedrun mode, 88-4, fastest 1 entry, scale 2, 8 render workers, fast render quality,
simultaneous starts, distinct high-contrast ghost colours.
Colours are selected against the encoder background (#cacad0); the palette
expands without cycling when --count exceeds 20. --ghost-color "#3568a8"
overrides this with one colour for every ghost.
--alignment exit delays starts so native completion ticks coincide; every run
must complete. Only the TAS drives visible objects, enemies and particles.
Combined level/demo text embeds its level; LTM and packed-only text require the
original level database (explicit --levels-file or optimiser autodiscovery).
For combined text, you are responsible for selecting its matching --level.
Downloads and leaderboard metadata are retained under leaderboard_ghost_cache.
Cached leaderboards and replays are reused by default; only missing files are
downloaded. Use --online to force fresh leaderboard and replay downloads
(--refresh is an alias), or --offline to forbid all downloads.
Speedrun count remains strict. Highscore mode fetches Harvey Cartel's published
20 slots, removes excluded names, then takes up to --count remaining entries,
printing a warning if fewer are available. It cannot recover ranks beyond the
server's top 20. It fails if no eligible runs remain or a selected download fails.

Highscore exclusions are case-insensitive exact names. DEFAULT_EXCLUDED_PLAYERS
contains nine user-maintained names, including JC239. Extend them with
repeatable --exclude-player NAME and/or --exclude-players-file FILE (UTF-8,
one name per line, blank lines and lines beginning # ignored). File/CLI entries
ADD to the built-in list. Exclusions apply in highscore mode only and are also
reapplied with --offline. This is a user-maintained exclusion list, not an
automatic detector; unlisted hacked scores can still appear. Highscore responses
and replays are cached separately under --cache-dir/highscore/LEVEL.

Highscore endpoints/protocol adapted from NHigh 2.0.1 by jg9000, with
modifications by eru_bahagon (nhighlib.py). They use HTTP POST at
http://www.harveycartel.org/metanet/n/data13/ :
  get_topscores_query_jg.php (episode_number), get_lv_demo.php (pk).
No Python 2 dependency is needed.
Output is a silent MP4, not a playable multi-player N demo.

4.13 secondary gold: --secondary-gold off (default) disables ghost gold.
static leaves coloured gold after the primary collects it, removing it when
the owning ghost collects it; animated also plays the collection animation.
When several ghosts need the same gold, ownership follows selected leaderboard
order. Works in both modes with the existing colours, alignment and pose cache.
Use the bundled native extension (python build_native.py from the project root).
Animated ghost gold is independent of --particles and --object-animations.

4.12 labels: each ghost uses its leaderboard player name. The primary label
is "TAS" by default; set --primary-label TEXT to override, or "" to hide it.
--no-ghost-labels hides all ghost labels. --label-size 6..32 sets the font size
in game pixels (default 8). Labels use the bundled N GUI font and each player's
colour. --label-position follow (default) follows players; top-left displays
a static legend in the top-left corner. Only top-left labels append scores: " - N f" for speedruns,
or " - 253.050 s" for highscores (the game score in seconds, not elapsed time).
Ghost scores come from the leaderboard. In speedrun mode TAS text uses its declared frame count.
TAS LTM uses its first completion tick minus the final completion-check tick,
excluding menus and recorded postroll; nonfinishing LTMs omit the score.
In highscore mode the TAS is simulated to first completion without rendering;
its score is (3600 + gold_bonus_ticks - (completion_tick - 1)) / 40.
Text follows --final-neutral; LTM never gets an added tick. A nonfinisher omits
its score. Crowded following labels can overlap; unsupported font characters appear as ?.

4.09+ rendering: --render-workers defaults to 8; 0 lets the encoder select
workers, 1 is serial, 2..64 explicitly selects multiple processes.
--render-quality fast (default) quantises positions/angles for more cache reuse;
exact preserves geometry. FFmpeg remains at --preset medium unless explicitly overridden.
--replay-cache-dir DIR enables persistent secondary pose caching (requires a
current native extension). This is separate from --cache-dir, which stores
leaderboard/replay downloads. --offline affects downloads only; --refresh does
not clear the pose cache. --profile prints encoder timings to the console;
--render-memory-mib sets the RGB transport budget (default 128 MiB).
Encoding prints phase/frame progress to stdout about every two seconds.
Use --no-progress to hide these updates. See --help for other switches.
"""
from __future__ import annotations

import argparse
import colorsys
import math
from datetime import datetime, timezone
from html.parser import HTMLParser
import inspect
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

BASE = "https://n.infunity.com/"
ENDPOINT = "get_lv_demo_only_speedrun.php"
HIGHSCORE_BASE = "http://www.harveycartel.org/metanet/n/data13/"
# User-maintained highscore exclusions; exact names, compared case-insensitively.
DEFAULT_EXCLUDED_PLAYERS = (
    "alllan", "Marcao", "JoaoGCNunes", "asda", "dnawrkshp",
    "haxYOscoreboard", "Cuppy33", "Yvsk", "JC239",
)


def configure_optimizer_path(optimizer_dir=None):
    """Find source/installed modules without changing the caller's directory.

    An explicit path wins, then the script's directory (standalone copies),
    then its parent (the bundled tools package). Otherwise normal installed
    module lookup applies. Called only for encoding, never for downloading.
    """
    if optimizer_dir is not None:
        root = Path(optimizer_dir).resolve()
        if not (root / "nv14_video.py").is_file():
            raise ValueError("--optimizer-dir must contain nv14_video.py")
    else:
        script_dir = Path(__file__).resolve().parent
        root = next((candidate for candidate in (script_dir, script_dir.parent)
                     if (candidate / "nv14_video.py").is_file()), None)
    if root is not None:
        sys.path.insert(0, str(root))
    return root


def score_label(name, frames, position, mode="speedrun"):
    """Preserve hidden labels and follow captions; fit the encoder's 128-char limit."""
    if not name:
        return None
    # Remote player names can contain layout whitespace or excessive text.
    # Keep the original in metadata; make only the displayed caption safe.
    name = "".join(char if char.isprintable() else " " for char in name)
    if position != "top-left" or frames is None:
        return name[:128]
    suffix = f" - {format_highscore(frames)} s" if mode == "highscore" else f" - {frames} f"
    return name[:128 - len(suffix)] + suffix


def primary_score_frames(source, simulate_enemies):
    """Text uses its declared score; LTM excludes the terminal check and postroll."""
    if source.input_kind == "demo":
        return len(source.frames)
    from nv14_native import require_native
    from nv14_video import _completion_ticks
    level = require_native().parse_level_string(source.level_string, simulate_enemies=simulate_enemies)
    try:
        return max(0, _completion_ticks(level, source.frames, False, 0) - 1)
    except ValueError:
        print("WARNING: TAS LTM did not complete; omitting its frame score.", file=sys.stderr)
        return None


def format_highscore(ticks):
    # Integer formatting avoids floating point rounding of 0.025-second units.
    milliseconds = abs(ticks) * 25
    return f"{'-' if ticks < 0 else ''}{milliseconds // 1000}.{milliseconds % 1000:03d}"


def primary_highscore_ticks(source, simulate_enemies, final_neutral):
    """Native completed level score, including the game's 90-second base."""
    from nv14_native import require_native
    from nv14_engine import InputFrame
    state = require_native().parse_level_string(
        source.level_string, simulate_enemies=simulate_enemies).initial_state(track_visuals=False)
    total = len(source.frames) + int(source.input_kind == "demo" and final_neutral)
    for start in range(0, total, 4096):
        end = min(total, start + 4096)
        batch = list(source.frames[start:min(end, len(source.frames))])
        if end > len(source.frames):
            batch.append(InputFrame())
        result = state.step_many(batch, stop_on_dead=True, stop_on_complete=True)
        if state.level_complete:
            return 3600 + int(state.static_state()["gold_bonus_ticks"]) - max(0, int(state.frame) - 1)
        event = result["last_step"]
        if event and event["dead"]:
            break
    print("WARNING: TAS did not complete; omitting its highscore.", file=sys.stderr)
    return None


def excluded_players(args):
    names = set(DEFAULT_EXCLUDED_PLAYERS)
    names.update(args.exclude_player)
    if args.exclude_players_file:
        names.update(line.strip() for line in args.exclude_players_file.read_text(
            encoding="utf-8-sig").splitlines() if line.strip() and not line.lstrip().startswith("#"))
    return {name.strip().casefold() for name in names if name.strip()}


def flash_fields(text):
    """The legacy server emits raw ampersand-delimited values, not URL encoding.

    In particular, preserve literal '+' and '%' in player names, as NHigh does.
    """
    fields = {}
    for assignment in text.replace("\r", "").strip().split("&"):
        key, sep, value = assignment.partition("=")
        if sep:
            fields[key] = value
    if "results" not in fields or not fields["results"].isdigit():
        raise ValueError("Invalid highscore response (possibly a server error page)")
    return fields


def parse_highscores(text, episode, level, count, excluded):
    fields = flash_fields(text)
    ranks = sorted(int(m.group(1)) for key in fields
                   if (m := re.fullmatch(fr"{level}score(\d+)", key)))
    if not ranks:
        raise ValueError(f"No highscore entries returned for {episode:02d}-{level}")
    entries, removed, seen = [], [], set()
    for rank in ranks:
        prefix = str(level)
        try:
            name = fields[f"{prefix}name{rank}"].strip()
            score = int(fields[f"{prefix}score{rank}"])
            pk = fields[f"{prefix}pkey{rank}"].strip()
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Malformed highscore slot {rank}") from exc
        for key, expected in ((f"{prefix}epnum{rank}", episode), (f"{prefix}levnum{rank}", level)):
            if key in fields and fields[key] != str(expected):
                raise ValueError("Highscore response contains a different level")
        if not name or score <= 0:
            continue  # Empty published slot, not a playable submission.
        if name.casefold() in excluded:
            removed.append(dict(player=name, site_rank=rank, score_ticks=score))
            continue
        if not pk.isdigit() or int(pk) <= 0:
            raise ValueError(f"Invalid replay ID in highscore slot {rank}")
        if pk in seen:
            continue
        seen.add(pk)
        entries.append(dict(pk=pk, player=name, score_ticks=score,
                            site_rank=rank, url=HIGHSCORE_BASE + "get_lv_demo.php"))
    entries.sort(key=lambda entry: -entry["score_ticks"])
    if not entries:
        raise ValueError(f"No eligible highscore runs remain for {episode:02d}-{level}")
    if len(entries) < count:
        print(f"WARNING: requested {count} highscore ghosts; using {len(entries)} eligible "
              f"of {len(ranks)} published slots after excluding {len(removed)}. "
              "The endpoint only exposes the top 20 slots.", file=sys.stderr)
    return [dict(e, position=i + 1) for i, e in enumerate(entries[:count])], removed


def parse_highscore_demo(text, entry):
    fields = flash_fields(text)
    if fields["results"] != "1":
        raise ValueError(f"Replay {entry['pk']} is unavailable")
    try:
        name, score = fields["name"].strip(), int(fields["score"])
        demo = validate_demo(fields["demo"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid highscore replay response for {entry['player']}") from exc
    if name.casefold() != entry["player"].casefold() or score != entry["score_ticks"]:
        raise ValueError(f"Replay/leaderboard mismatch for {entry['player']}; refresh the snapshot with --online")
    return demo


def ghost_palette(count):
    """Deterministic, noncycling colours, separated in perceptual Oklab space.

    All candidates have >=3:1 contrast against v4.09's #cacad0 background.
    Greedy farthest-point selection spreads hue AND lightness; the fixed seed
    keeps existing rank colours stable when count increases. Hundreds of ghosts
    inevitably look similar even though their RGB values remain different.
    """
    def linear(rgb):
        return tuple(v / 12.92 if v <= .04045 else ((v + .055) / 1.055)**2.4
                     for v in (c / 255 for c in rgb))

    def luminance(rgb):
        r, g, b = linear(rgb)
        return .2126*r + .7152*g + .0722*b

    def lab(rgb):
        r, g, b = linear(rgb)
        l = (.4122214708*r + .5363325363*g + .0514459929*b)**(1/3)
        m = (.2119034982*r + .6806995451*g + .1073969566*b)**(1/3)
        t = (.0883024619*r + .2817188376*g + .6299787005*b)**(1/3)
        return (.2104542553*l + .7936177850*m - .0040720468*t,
                1.9779984951*l - 2.4285922050*m + .4505937099*t,
                .0259040371*l + .7827717662*m - .8086757660*t)

    background = luminance((202, 202, 208))
    candidates = {}
    for hue in range(360):
        for saturation in (.55, .75, .95):
            for value in (.38, .52, .66, .80):
                rgb = tuple(round(c * 255) for c in
                            colorsys.hsv_to_rgb(hue / 360, saturation, value))
                if (background + .05) / (luminance(rgb) + .05) >= 3:
                    candidates[rgb] = lab(rgb)
    selected = [(53, 104, 168)]
    candidates.pop(selected[0], None)
    distances = dict.fromkeys(candidates, math.inf)
    if count > len(candidates) + 1:
        raise ValueError("Too many ghosts for the distinct-colour palette; use --ghost-color #RRGGBB")
    while len(selected) < count:
        last = lab(selected[-1])
        for rgb, position in candidates.items():
            distance = sum((a-b)**2 for a, b in zip(position, last))
            distances[rgb] = min(distances[rgb], distance)
        chosen = max(distances, key=distances.get)
        selected.append(chosen)
        del candidates[chosen]
        del distances[chosen]
    return ["#{:02x}{:02x}{:02x}".format(*rgb) for rgb in selected[:count]]


class Rows(HTMLParser):
    """Extract table cells and their links without depending on site styling."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = {"text": "", "links": []}
        elif tag == "a" and self.cell is not None:
            self.cell["links"].append(dict(attrs).get("href", ""))

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = self.cell = None


def parse_leaderboard(html, episode, level, count):
    parser = Rows()
    parser.feed(html)
    entries = {}
    for row in parser.rows:
        if len(row) < 5:
            continue
        cells = [c["text"].strip() for c in row]
        if cells[:2] != [str(episode), str(level)]:
            continue
        for href in row[2]["links"]:
            url = urlparse(urljoin(BASE, href))
            if url.hostname != "n.infunity.com" or url.path != "/" + ENDPOINT:
                continue
            pk = parse_qs(url.query).get("pk", [""])[0]
            if not pk.isdigit() or not cells[2].isdigit():
                raise ValueError("Leaderboard contains an invalid replay ID/frame count")
            entries.setdefault(pk, dict(pk=pk, frames=int(cells[2]),
                                       site_rank=cells[3], player=cells[4],
                                       url=BASE + ENDPOINT + "?" + urlencode({"pk": pk})))
    ordered = sorted(entries.values(), key=lambda e: e["frames"])
    if len(ordered) < count:
        raise ValueError(f"Found {len(ordered)} runs for {episode:02d}-{level}; "
                         f"requested {count}. Check the site or reduce --count explicitly.")
    return [dict(e, position=i + 1) for i, e in enumerate(ordered[:count])]


def validate_demo(text, expected_frames=None):
    text = text.strip().lstrip("\ufeff").strip()
    if not re.fullmatch(r"\d+:(?:\d+\|)*\d+\|?", text):
        raise ValueError("Replay response is not packed demo text (possibly a server error page)")
    count, payload = text.split(":", 1)
    words = payload.rstrip("|").split("|")
    if expected_frames is not None and int(count) != expected_frames:
        raise ValueError(f"Leaderboard says {expected_frames} frames; replay declares {count}")
    if len(words) < (int(count) + 6) // 7:
        raise ValueError("Truncated replay: insufficient packed words")
    if any(int(word) >= 2**28 for word in words):
        raise ValueError("Replay word exceeds the seven-nibble complex demo format")
    return text


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def fetch(url, timeout, delay, form=None):
    for attempt in range(3):
        try:
            time.sleep(delay if attempt == 0 else max(delay, 2**attempt))
            request = Request(url, data=urlencode(form).encode("ascii") if form is not None else None,
                              headers={"User-Agent": "nv14-leaderboard-ghosts/2.0",
                                            "Accept": "text/html,text/plain"})
            with urlopen(request, timeout=timeout) as response:
                body = response.read(8 * 1024 * 1024 + 1)
                if len(body) > 8 * 1024 * 1024:
                    raise ValueError("Unexpectedly large server response")
                charset = response.headers.get_content_charset()
                if charset:
                    return body.decode(charset)
                try:
                    return body.decode("utf-8")
                except UnicodeDecodeError:
                    return body.decode("latin-1")
        except (URLError, TimeoutError, OSError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError(f"Download failed: {url}: {exc}") from exc
            if attempt == 2:
                raise RuntimeError(f"Download failed after 3 attempts: {url}: {exc}") from exc
            print(f"Retrying {url}: {exc}", file=sys.stderr, flush=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tas", nargs="?", type=Path, help="Primary TAS .ltm or demo .txt")
    p.add_argument("--level", "--level-id", default="88-4", help="Episode-level, default 88-4")
    p.add_argument("--mode", choices=("speedrun", "highscore"), default="speedrun")
    p.add_argument("--count", type=int, default=1, help="Requested ghosts (default: 1); highscore mode uses up to the available eligible slots")
    p.add_argument("--exclude-player", action="append", default=[], metavar="NAME",
                   help="Extra excluded highscore player (repeatable, case-insensitive)")
    p.add_argument("--exclude-players-file", type=Path,
                   help="Extra highscore exclusions: UTF-8 text, one name per line; adds to built-ins")
    p.add_argument("-o", "--output", type=Path)
    p.add_argument("--optimizer-dir", type=Path,
                   help="Explicit optimiser root; default discovers the bundled parent directory")
    p.add_argument("--levels-file", type=Path,
                   help="Level database for LTM or packed-only input; omit for combined demos")
    p.add_argument("--alignment", "--replay-alignment", choices=("start", "exit"), default="start")
    p.add_argument("--secondary-gold", choices=("off", "static", "animated"), default="off",
                   help="Ghost gold after primary pickups: off (default), static, or animated collection")
    p.add_argument("--primary-label", default="TAS", metavar="TEXT",
                   help='Label following the TAS player (default: TAS); empty string hides it')
    p.add_argument("--ghost-labels", action=argparse.BooleanOptionalAction, default=True,
                   help="Label ghosts with leaderboard player names (default: enabled)")
    p.add_argument("--label-position", choices=("follow", "top-left"), default="follow",
                   help="Follow each player (default), or show a static top-left legend")
    p.add_argument("--label-size", type=int, choices=range(6, 33), default=8, metavar="PIXELS",
                   help="Label font size in game pixels, 6..32 (default: 8)")
    p.add_argument("--ghost-color", default="palette", help="Default: distinct contrasting palette; #RRGGBB sets all ghosts to one colour")
    p.add_argument("--cache-dir", type=Path, default=Path("leaderboard_ghost_cache"),
                   help="Download cache, relative to the working directory (default: leaderboard_ghost_cache)")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--online", "--refresh", dest="online", action="store_true",
                       help="Force fresh leaderboard and replay downloads; default reuses cached files")
    group.add_argument("--offline", action="store_true",
                       help="Use cached files only; fail if any required file is missing")
    p.add_argument("--download-only", action="store_true")
    p.add_argument("--timeout", type=float, default=30)
    p.add_argument("--request-delay", type=float, default=0.25)
    p.add_argument("--ltm-postroll", type=int)
    p.add_argument("--scale", type=int, choices=range(1, 5), default=2, help="Integer output scale (default: 2)")
    p.add_argument("--fps", type=int, choices=range(40, 241), default=40)
    p.add_argument("--crf", type=int, choices=range(52), default=18)
    p.add_argument("--preset", default="medium")
    p.add_argument("--ffmpeg-path")
    p.add_argument("--terminal-hold-seconds", type=float, default=1)
    p.add_argument("--render-workers", type=int, default=8, metavar="N",
                   help="0=encoder auto, 1=serial, 2..64=render processes (default: 8)")
    p.add_argument("--render-quality", choices=("exact", "fast"), default="fast",
                   help="exact geometry, or fast quantised sprite transforms (default: fast)")
    p.add_argument("--render-memory-mib", type=int, default=128, metavar="MIB",
                   help="RGB transport memory budget, 16..65536 MiB (default: 128)")
    p.add_argument("--progress", action=argparse.BooleanOptionalAction, default=True,
                   help="Print periodic encoding progress to stdout (default: enabled)")
    p.add_argument("--profile", action="store_true",
                   help="Print encoder timing/cache statistics to the console")
    p.add_argument("--replay-cache-dir", type=Path,
                   help="Persistent ghost pose cache; separate from downloaded replay --cache-dir")
    p.add_argument("--particles", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--particle-seed", type=int, default=0)
    p.add_argument("--object-animations", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--simulate-enemies", action=argparse.BooleanOptionalAction, default=True,
                   help="Disable only for motion-only visualisation")
    p.add_argument("--final-neutral", action=argparse.BooleanOptionalAction, default=True,
                   help="Append final neutral input to text demos; never applies to LTM")
    p.add_argument("--assets-path", type=Path, help="Custom graphics asset pack")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    match = re.fullmatch(r"(\d{1,3})-([0-4])", args.level)
    if not match:
        p.error("--level must be episode-level, e.g. 88-4 (level 0..4)")
    ep, lv = map(int, match.groups())
    level_id = f"{ep:02d}-{lv}"
    if (args.count < 1 or not math.isfinite(args.timeout) or args.timeout <= 0
            or not math.isfinite(args.request_delay) or args.request_delay < 0):
        p.error("count/timeout must be positive and request-delay nonnegative; times must be finite")
    if not 0 <= args.render_workers <= 64:
        p.error("--render-workers must be from 0 to 64")
    if not 16 <= args.render_memory_mib <= 65536:
        p.error("--render-memory-mib must be from 16 to 65536")
    if args.ltm_postroll is not None and args.ltm_postroll < 0:
        p.error("--ltm-postroll must be nonnegative")
    if not 0 <= args.terminal_hold_seconds <= 3600:
        p.error("--terminal-hold-seconds must be from 0 to 3600")
    if not args.download_only and (args.tas is None or not args.tas.is_file()):
        p.error("provide an existing TAS file, or use --download-only")
    if args.ghost_color != "palette" and not re.fullmatch(r"#[0-9a-fA-F]{6}", args.ghost_color):
        p.error("--ghost-color must be #RRGGBB or palette")
    if args.mode == "highscore" and ep >= 100:
        p.error("The Harvey Cartel highscore server supports episodes 00..99")
    if args.mode != "highscore" and (args.exclude_player or args.exclude_players_file):
        p.error("Exclusion options apply to --mode highscore")
    excluded = excluded_players(args) if args.mode == "highscore" else set()
    cache_root = args.cache_dir / "highscore" if args.mode == "highscore" else args.cache_dir
    cache = (cache_root / level_id).resolve()
    mode_suffix = "_highscore" if args.mode == "highscore" else ""
    output = (args.output or Path(f"{level_id}_TAS{mode_suffix}_top{args.count}_{args.alignment}.mp4")).resolve()
    encode_options = {}
    tas_score = None
    primary_label = args.primary_label or None
    if not args.download_only:
        try:
            configure_optimizer_path(args.optimizer_dir)
        except ValueError as exc:
            p.error(str(exc))
        try:
            from nv14_video import encode_replay_video
            from nv14_dump import load_player_dump_source
        except ImportError as exc:
            raise RuntimeError("Cannot import optimiser. Keep this script in the release's tools/ "
                               "directory, install the optimiser, or pass --optimizer-dir DIR. "
                               f"Import error: {exc}") from exc
        required = {"secondary_replays", "render_workers", "render_quality", "replay_cache_dir",
                    "primary_label", "secondary_labels", "label_size", "label_position", "secondary_gold",
                    "render_memory_mib", "profile", "progress"}
        if not required.issubset(inspect.signature(encode_replay_video).parameters):
            raise RuntimeError("Encoder is too old: use the bundled optimiser 4.19 (--optimizer-dir DIR)")
        from nv14_render import validate_player_label
        validate_player_label(args.primary_label)
        packed = args.tas.suffix.lower() != ".ltm" and bool(re.match(
            r"^\d+:", args.tas.read_text(encoding="utf-8-sig").strip()))
        if packed or args.tas.suffix.lower() == ".ltm":
            encode_options.update(levels_file=args.levels_file, level_id=level_id)
        elif args.levels_file:
            p.error("Combined text already embeds its level; omit --levels-file")
        source = load_player_dump_source(args.tas, ltm_postroll=args.ltm_postroll, **encode_options)
        protected = [args.tas.resolve(), Path(__file__).resolve()]
        if source.levels_file:
            protected.append(source.levels_file.resolve())
        if args.exclude_players_file:
            protected.append(args.exclude_players_file.resolve())
        from nv14_cli import _paths_alias
        if (any(_paths_alias(output, item) for item in protected)
                or output.is_relative_to(args.cache_dir.resolve())):
            p.error("video output must not overwrite inputs, this script, or the download cache")
        if output.suffix.lower() != ".mp4":
            p.error("output must have .mp4 extension")
        # Check prerequisites before any leaderboard/replay downloads.
        from nv14_native import require_native
        native = require_native()
        if args.replay_cache_dir is not None and not hasattr(native.NativeState, "capture_visual_frames"):
            raise RuntimeError("Replay caching requires the 4.09 native extension; run python build_native.py")
        from PIL import Image  # noqa: F401
        from nv14_video import _find_ffmpeg
        _find_ffmpeg(args.ffmpeg_path)
        if args.label_position == "top-left" and primary_label:
            tas_score = (primary_highscore_ticks(source, args.simulate_enemies, args.final_neutral)
                         if args.mode == "highscore" else primary_score_frames(source, args.simulate_enemies))
            primary_label = score_label(primary_label, tas_score, args.label_position, args.mode)
    removed = []
    if args.mode == "highscore":
        url = HIGHSCORE_BASE + "get_topscores_query_jg.php"
        board_path = cache / "leaderboard.txt"
        form = {"episode_number": ep}
    else:
        url = BASE + "lv_speedrun.php?" + urlencode({"epnum": ep, "levnum": lv})
        board_path = cache / "leaderboard.html"
        form = None
    board_cached = board_path.is_file() and not args.online
    if args.offline and not board_cached:
        raise FileNotFoundError(f"Offline cache missing {board_path}; run without --offline first")
    body = (board_path.read_text(encoding="utf-8") if board_cached else
            fetch(url, args.timeout, args.request_delay, form))
    if args.mode == "highscore":
        entries, removed = parse_highscores(body, ep, lv, args.count, excluded)
        for entry in removed:
            print(f"Excluded highscore slot {entry['site_rank']}: {entry['player']}", flush=True)
    else:
        entries = parse_leaderboard(body, ep, lv, args.count)
    if not board_cached:
        atomic_text(board_path, body)
    colors = ghost_palette(len(entries)) if args.ghost_color == "palette" else [args.ghost_color] * len(entries)
    paths = []
    for entry in entries:
        path = cache / f"demo_{entry['pk']}.txt"
        response_path = cache / f"demo_{entry['pk']}.response.txt" if args.mode == "highscore" else path
        if response_path.exists() and not args.online:
            body = response_path.read_text(encoding="utf-8")
        elif args.offline:
            raise FileNotFoundError(f"Offline cache missing {response_path}; run online first")
        else:
            print(f"Downloading ghost {entry['position']}/{len(entries)}: {entry['player']} ...", flush=True)
            body = fetch(entry["url"], args.timeout, args.request_delay,
                         {"pk": entry["pk"]} if args.mode == "highscore" else None)
        demo = (parse_highscore_demo(body, entry) if args.mode == "highscore" else
                validate_demo(body, entry["frames"]))
        if args.mode == "highscore":
            entry["frames"] = int(demo.split(":", 1)[0])
            if not response_path.exists() or args.online:
                atomic_text(response_path, body)
        if not path.exists() or args.online or path.read_text(encoding="utf-8").strip() != demo:
            atomic_text(path, demo + "\n")
        paths.append(path)
        entry["file"] = str(path)
        entry["color"] = colors[entry["position"] - 1]
        entry["label"] = score_label(entry["player"], entry["score_ticks"] if args.mode == "highscore" else entry["frames"], args.label_position, args.mode) if args.ghost_labels else None
        score_text = f"{format_highscore(entry['score_ticks'])} s" if args.mode == "highscore" else f"{entry['frames']} frames"
        print(f"{entry['position']:2d}. {entry['player']} — {score_text}", flush=True)
    manifest = dict(level=level_id, mode=args.mode, leaderboard_url=url,
                    requested_count=args.count, actual_count=len(entries),
                    excluded_players=sorted(excluded), excluded_entries=removed,
                    created_utc=datetime.now(timezone.utc).isoformat(),
                    offline=args.offline, online=args.online,
                    download_policy="offline" if args.offline else "online" if args.online else "cache-first",
                    tas=str(args.tas.resolve()) if args.tas else None,
                    alignment=args.alignment, primary_label=primary_label,
                    primary_score_frames=tas_score if args.mode == "speedrun" else None,
                    primary_highscore_ticks=tas_score if args.mode == "highscore" else None,
                    label_size=args.label_size, label_position=args.label_position, ghosts=entries)
    atomic_text(cache / "selection.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    if args.download_only:
        print(f"Downloaded/validated {len(paths)} ghosts: {cache}")
        return 0
    print(f"Encoding TAS + {len(paths)} ghosts ({args.alignment} alignment): {output}", flush=True)
    result = encode_replay_video(args.tas, output,
        secondary_replays=paths, replay_alignment=args.alignment,
        secondary_colors=colors, secondary_gold=args.secondary_gold,
        primary_label=primary_label,
        secondary_labels=[entry["label"] for entry in entries], label_size=args.label_size,
        label_position=args.label_position,
        ltm_postroll=args.ltm_postroll, simulate_enemies=args.simulate_enemies,
        final_neutral=args.final_neutral, assets_path=args.assets_path,
        render_workers=args.render_workers, render_quality=args.render_quality,
        render_memory_mib=args.render_memory_mib, profile=args.profile, progress=args.progress,
        replay_cache_dir=args.replay_cache_dir,
        fps=args.fps, scale=args.scale, crf=args.crf, preset=args.preset,
        ffmpeg_path=args.ffmpeg_path, terminal_hold_seconds=args.terminal_hold_seconds,
        particles=args.particles, particle_seed=args.particle_seed,
        object_animations=args.object_animations, **encode_options)
    for replay in result.replays:
        name = "TAS" if replay.index == 0 else entries[replay.index - 1]["player"]
        print(f"{name}: {replay.stop_reason}, {replay.simulated_ticks} ticks, offset {replay.start_offset_ticks}")
        if not replay.complete:
            print(f"WARNING: {name} did not complete in native simulation.", file=sys.stderr)
    print(f"Renderer: {result.render_workers} worker(s), {result.render_quality} quality")
    if result.timings is not None:
        print("performance: " + json.dumps(result.timings, sort_keys=True))
    print(f"Saved {result.output_path} ({result.duration_seconds:.2f}s)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
