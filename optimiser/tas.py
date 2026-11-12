#!/usr/bin/env python3
"""Small opt-in TAS command shortcuts; the optimiser CLI stays authoritative.

Examples from optimiser/:
    ./tas.py auto 53-4
    ./tas.py auto 53-4 591  # named checkpoint without route TOML
    ./tas.py local 55-1 end
    ./tas.py goal 53-4 591
    ./tas.py both 53-4 591
    ./tas.py hybrid 53-4 591 --splice-hybrid-local-rounds 5
    ./tas.py random 55-1
    ./tas.py multi 97-2
    ./tas.py check 97-2      # input feasibility for all route splices
    ./tas.py check 97-2 591  # input feasibility for one splice
    ./tas.py merge 88-4
    ./tas.py repair 88-4
    ./tas.py loop 97-2 88-4
    LEVEL=88-4 ./tas.py merge
    ./tas.py multi 88-4 -- --auto-runs 5

See --help for TAS_* environment variables and --jaffar settings.
"""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence

ROOT = Path(__file__).resolve().parent
_MODES = {"auto", "local", "goal", "both", "hybrid", "random", "multi", "merge", "repair", "check"}
_ALIASES = {"auto-local": "goal", "random-splicer": "random",
            "multi-splicer": "multi", "merge-repair": "repair"}
_JAFFAR_AUTO = ("--auto-repair-beam-width", "32",
                "--auto-repair-cache-entries", "16", "--auto-adaptive-repair-windows",
                "--auto-repair-local-steps", "2000")
_JAFFAR_LOCAL = ("--local-beam-width", "32",
                 "--local-search-cache-entries", "16", "--local-adaptive-windows",
                 "--local-search-ticks", "20000")
_HELP = """Usage:
  ./tas.py MODE [LEVEL] [SPLICE] [optimizer flags...]
  ./tas.py loop LEVEL [LEVEL ...] [-- optimizer flags...]

Modes: auto, local, goal (Auto endpoint), both (continuous Auto/Local),
       hybrid (one Auto round then N Local rounds), random,
       multi, merge (fast, standalone), repair (bounded, standalone),
       check (read-only input feasibility), loop.
LEVEL defaults to $TAS_LEVEL or $LEVEL. SPLICE to $TAS_SPLICE or $SPLICE.
Examples:
  ./tas.py auto 53-4
  ./tas.py local 55-1 end
  ./tas.py goal 53-4 591
  ./tas.py both 53-4 591
  ./tas.py hybrid 53-4 591 --splice-hybrid-local-rounds 5
  ./tas.py multi 97-2 --auto-runs 5
  ./tas.py check 97-2
  ./tas.py check 97-2 591
  ./tas.py merge 88-4
  ./tas.py repair 88-4
  ./tas.py loop 97-2 88-4
  ./tas.py auto 53-4 --jaffar
  ./tas.py multi 88-4 --dry-run

Defaults (all optional env overrides):
  TAS_INPUT_TEMPLATE=../n_levels/{level}.ltm
  TAS_OUTPUT_TEMPLATE=wip/{level}.ltm
  TAS_REPLAY_TEMPLATE=wip/{level}.txt
  TAS_GOAL_TEMPLATE=../splices/{level}/{splice}.txt
  TAS_MULTI_TEMPLATE=../splices/{level}/multi-splicer.toml
  TAS_CONFIG=examples/config.toml
  TAS_RANDOM_CONFIG=../splices/random-splice.toml
  TAS_WORKERS=15
  TAS_RUNS_AUTO=10, TAS_RUNS_GOAL=10, TAS_RUNS_MULTI=50
  TAS_STAGNATION_LOCAL=50, TAS_STAGNATION_RANDOM=10
  TAS_JAFFAR=1 enables the mode-specific preset (or use --jaffar).

Commands execute from the optimiser directory (independent of launch cwd).
Extra optimizer flags appended after defaults take precedence. When the
level has multi-splicer.toml, auto/local/goal/both/hybrid share its named
checkpoint and propagation pipeline. With no multi-splicer.toml,
specifying SPLICE and having its .txt/.toml goal file activates a one-stage
named checkpoint run: the verified best is saved as wip/LEVEL_SPLICE.ltm (plus
replay TXT and frontier) for later multi-splicer reuse. No merge/repair/retiming
is attempted without a route. Hybrid never advances to another splice.
Auto without SPLICE retains the legacy standalone mode. Use --no-propagation
to skip merges/repair/retiming with a configured route while retaining checkpoint
saving. Check mode reads only the positional input and individual goal files, checks
all primary/alternate route splices or one named splice, and never writes
checkpoints or starts search/merge/repair. A single splice can be checked
without multi-splicer.toml when its goal file exists.
For merge and repair modes, no normal Auto/Local optimisation is
started. --dry-run only
prints the expanded command and never touches replay/output files.
"""


def _template(env: Mapping[str, str], key: str, fallback: str,
              *, level: str, splice: str = "") -> str:
    try:
        return env.get(key, fallback).format(level=level, splice=splice)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid template ${key}: {exc}") from exc


def build_command(mode: str, level: str, splice: str | None = None,
                  *, env: Mapping[str, str] | None = None,
                  extra: Sequence[str] = (), jaffar: bool = False) -> list[str]:
    """Return literal argv; do not use a shell or expand file contents."""
    mode = _ALIASES.get(mode, mode)
    if mode not in _MODES:
        raise ValueError(f"unsupported TAS mode {mode!r}")
    if not level or level.startswith("-"):
        raise ValueError("a LEVEL is required (argument or TAS_LEVEL/LEVEL)")
    if mode in ("local", "goal", "both", "hybrid") and not splice:
        raise ValueError(f"{mode} requires SPLICE (argument or TAS_SPLICE/SPLICE)")
    env = os.environ if env is None else env
    def path(name: str, default: str) -> str:
        return _template(env, name, default, level=level, splice=splice or "")
    input_file = path("TAS_INPUT_TEMPLATE", "../n_levels/{level}.ltm")
    output = path("TAS_OUTPUT_TEMPLATE", "wip/{level}.ltm")
    replay = path("TAS_REPLAY_TEMPLATE", "wip/{level}.txt")
    # Do not permit a shortcut to silently overwrite its own input movie.
    if mode != "check" and (ROOT / input_file).resolve() == (ROOT / output).resolve():
        raise ValueError("input and output are the same file; change TAS_OUTPUT_TEMPLATE")
    common = ["--output", output, "--replay-output", replay,
              "--workers", env.get("TAS_WORKERS", "15")]
    shared = ["--config", env.get("TAS_CONFIG", "examples/config.toml")]
    named_route = path("TAS_MULTI_TEMPLATE", "../splices/{level}/multi-splicer.toml")
    # Named checkpoint persistence is independent of a multi-splicer route:
    # the same verified per-stage writer also supports a one-goal route.
    # A standalone Auto launch *without* a named SPLICE still behaves as before.
    has_route = (ROOT / named_route).is_file()
    goal_file = (path("TAS_GOAL_TEMPLATE", "../splices/{level}/{splice}.txt")
                 if splice else None)
    if (goal_file and not (ROOT / goal_file).is_file() and
            goal_file.endswith(".txt") and
            (ROOT / (goal_file[:-4] + ".toml")).is_file()):
        # Named stages accept either extension, even if the shortcut's
        # default goal template happens to spell out the .txt suffix.
        goal_file = goal_file[:-4] + ".toml"
    has_named_goal = bool(splice and goal_file and
                          (ROOT / goal_file).is_file() and
                          Path(goal_file).name in (splice + ".txt", splice + ".toml"))
    if has_named_goal and not has_route:
        try:
            with (ROOT / goal_file).open("rb") as stream:
                goal_settings = tomllib.load(stream)
            strategy = goal_settings.get("local", {}).get("search", "population")
        except (OSError, ValueError, TypeError, AttributeError):
            # Let the real config loader show the malformed-file error.
            strategy = "population"
        if strategy != "population":
            # Legacy Local window goals are not compatible with the managed
            # population backend. Never silently switch their search engine.
            has_named_goal = False
    managed = mode in ("auto", "local", "goal", "both", "hybrid") and (
        has_route or has_named_goal)
    if mode == "check":
        if splice is None and not has_route:
            raise ValueError("check without SPLICE requires a multi-splicer.toml route")
        if splice is not None and not has_named_goal and not has_route:
            raise ValueError(f"check {level} {splice} needs a named goal file "
                             f"(expected {goal_file})")
        command = ["auto", input_file, *shared, "--check-splices"]
        if has_route:
            command += ["--splice-config", named_route]
        else:
            command += ["--auto-splice-files", splice,
                        "--auto-splice-mode", "user", "--auto-random-splice",
                        "--auto-splice-directory", str(Path(goal_file).parent)]
        if splice:
            command += ["--check-splice", splice]
        return [sys.executable, str(ROOT / "optimize_replay.py"), *command, *extra]
    if mode == "auto" and splice and not managed:
        raise ValueError(f"auto {level} {splice} needs a named goal file "
                         f"(expected {goal_file}) or multi-splicer.toml")
    if managed:
        backend = {"auto": "endpoint-auto", "goal": "endpoint-auto",
                   "local": "local", "both": "both", "hybrid": "hybrid"}[mode]
        command = ["auto", input_file, *shared]
        if has_route:
            command += ["--splice-config", named_route]
        else:
            # With no named route there are no configured downstream stages.
            # Run the real named-stage coordinator with precisely one goal,
            # retaining its LTM/TXT and frontier checkpoint compatibility.
            command += ["--auto-splice-files", splice,
                        "--auto-splice-mode", "user", "--auto-random-splice",
                        "--auto-splice-directory", str(Path(goal_file).parent),
                        "--no-propagation"]
        command += ["--auto-splice-search", backend]
        if splice:
            command += ["--single-splice", splice]
        if mode == "hybrid":
            command += ["--auto-runs", "1"]
        elif mode == "auto":
            command += ["--auto-runs", env.get("TAS_RUNS_AUTO", "10")]
        elif mode == "goal":
            command += ["--auto-runs", env.get("TAS_RUNS_GOAL", "10")]
        else:
            command += ["--auto-runs", "1"]
        command += common
    elif mode == "local":
        command = ["local", input_file,
                   "--config", path("TAS_GOAL_TEMPLATE", "../splices/{level}/{splice}.txt"),
                   "--stagnation-rounds", env.get("TAS_STAGNATION_LOCAL", "50"), *common]
    else:
        command = [mode if mode in ("both", "hybrid") else "auto", input_file]
        if mode == "random":
            command += ["--config", env.get("TAS_RANDOM_CONFIG", "../splices/random-splice.toml"),
                        "--simulate-enemies", "--auto-stagnation-runs",
                        env.get("TAS_STAGNATION_RANDOM", "10")]
        else:
            command += shared
            if mode == "auto":
                command += ["--auto-runs", env.get("TAS_RUNS_AUTO", "10")]
            if mode in ("both", "hybrid"):
                command += ["--goal-config", path("TAS_GOAL_TEMPLATE", "../splices/{level}/{splice}.txt")]
            if mode == "goal":
                command += ["--goal-config", path("TAS_GOAL_TEMPLATE", "../splices/{level}/{splice}.txt"),
                            "--auto-runs", env.get("TAS_RUNS_GOAL", "10")]
            if mode in ("multi", "merge", "repair"):
                command += ["--splice-config", path("TAS_MULTI_TEMPLATE", "../splices/{level}/multi-splicer.toml")]
            if mode == "multi":
                command += ["--auto-runs", env.get("TAS_RUNS_MULTI", "50")]
            elif mode == "merge":
                command += ["--splice-merge-only"]
            elif mode == "repair":
                command += ["--splice-merge-repair-only"]
        command += common
    if jaffar:
        # Managed Local runs through the named Auto coordinator, not the
        # legacy Local-only window engine.
        command.extend(_JAFFAR_LOCAL if mode == "local" and not managed else _JAFFAR_AUTO)
    # Caller-controlled flags at the end override the shortcut defaults.
    return [sys.executable, str(ROOT / "optimize_replay.py"), *command, *extra]


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    if not args or "--help" in args or "-h" in args:
        print(_HELP)
        return 0
    dry = "--dry-run" in args
    jaffar = "--jaffar" in args or env.get("TAS_JAFFAR", "").lower() in ("1", "true", "yes")
    args = [value for value in args if value not in ("--dry-run", "--jaffar")]
    raw_mode = args.pop(0)
    mode = _ALIASES.get(raw_mode, raw_mode)
    if mode == "loop":
        if "--" in args:
            index = args.index("--")
            levels, extra = args[:index], args[index + 1:]
        else:
            levels, extra = args, []
        if not levels:
            levels = [env.get("TAS_LEVEL") or env.get("LEVEL") or ""]
        tasks = [("multi", level, None, extra) for level in levels]
    else:
        if mode not in _MODES:
            raise ValueError(f"unknown mode {mode!r}; see --help")
        level = (args.pop(0) if args and not args[0].startswith("-")
                 else env.get("TAS_LEVEL") or env.get("LEVEL") or "")
        splice = (args.pop(0) if mode in ("auto", "local", "goal", "both", "hybrid", "check") and args and not args[0].startswith("-")
                  else None if mode == "check" else env.get("TAS_SPLICE") or env.get("SPLICE"))
        if args and args[0] == "--":
            args.pop(0)
        tasks = [(mode, level, splice, args)]
    for selected, level, splice, extra in tasks:
        command = build_command(selected, level, splice, env=env, extra=extra, jaffar=jaffar)
        print(shlex.join(command), flush=True)
        if not dry:
            if selected != "check":
                (ROOT / "wip").mkdir(parents=True, exist_ok=True)
            # The user may override output directory; create its parent too.
            if "--output" in command:
                output_index = command.index("--output") + 1
                (ROOT / command[output_index]).parent.mkdir(parents=True, exist_ok=True)
            code = subprocess.run(command, cwd=ROOT, check=False).returncode
            if code:
                return code
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as error:
        print(f"tas.py: {error}", file=sys.stderr)
        sys.exit(2)
