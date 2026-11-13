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
  TAS_RUNS_AUTO (defaults to [auto] runs=10), TAS_RUNS_GOAL=10, TAS_RUNS_MULTI=50
  TAS_STAGNATION_LOCAL (defaults to [local] stagnation-rounds=50), TAS_STAGNATION_RANDOM=10
  TAS_JAFFAR=1 enables the mode-specific preset (or use --jaffar).

Commands execute from the optimiser directory (independent of launch cwd).
Extra optimizer flags appended after defaults take precedence. When the
specifying SPLICE runs the *ordinary* standalone Auto/Local/Hybrid backend
with its usual progress, search budget, and output path. After the search,
verified Auto/Local results are also published as wip/LEVEL_SPLICE.ltm (plus
replay TXT and frontier); Hybrid/Both already use the same stage writer.
If a multi-splicer.toml exists, configured merging/retiming/repair may run
AFTER standalone search, never as an implicit startup operation. Use
--no-propagation to skip those post-search operations while retaining checkpoint
saving. Hybrid stays on its requested splice. Auto without SPLICE retains
the legacy standalone mode. Check mode reads only the positional input and
individual goal files, checks all primary/alternate route splices or one named
splice, and never writes
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


def _shortcut_config_number(env: Mapping[str, str], section: str,
                            name: str, fallback: int) -> str:
    """Read shortcut defaults from the shared TOML without importing goal options.

    Standalone Local passes its level-specific goal as --config, so it cannot
    inherit general [local] settings through the optimiser's TOML loader.
    Read *only* its stagnation default here; the goal and CLI remain stronger.
    """
    config_path = ROOT / env.get("TAS_CONFIG", "examples/config.toml")
    try:
        with config_path.open("rb") as stream:
            data = tomllib.load(stream)
    except FileNotFoundError:
        # Preserve launcher usability when a project uses only goal files.
        return str(fallback)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot read shortcut settings from {config_path}: {exc}") from exc
    values = data.get(section, {})
    if not isinstance(values, Mapping):
        raise ValueError(f"[{section}] must be a TOML table in {config_path}")
    alias = name.replace("-", "_")
    if name in values and alias in values and name != alias:
        raise ValueError(f"[{section}] specifies both {name} and {alias} in {config_path}")
    value = values.get(name, values.get(alias, fallback))
    minimum = 0 if section == "auto" else 1
    if type(value) is not int or value < minimum:
        raise ValueError(f"[{section}] {name} must be an integer >= {minimum} in {config_path}")
    return str(value)


def _local_needs_default_stagnation(goal_file: str | None,
                                    extra: Sequence[str]) -> bool:
    """Apply shared Local patience only if no goal/CLI stopping rule exists."""
    if any(token.split("=", 1)[0] in (
            "--rounds", "--stagnation-rounds", "--config", "--search")
           for token in extra):
        return False
    if goal_file is None or not (ROOT / goal_file).is_file():
        return True
    try:
        with (ROOT / goal_file).open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        # Allow the optimisation backend to report malformed goal files.
        return False
    for section in (data, data.get("common"), data.get("goal"), data.get("local")):
        if isinstance(section, Mapping) and any(
                str(key).replace("-", "_") in ("rounds", "stagnation_rounds")
                for key in section):
            return False
    local = data.get("local", {})
    return not isinstance(local, Mapping) or local.get("search", "population") == "population"


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
    # A named goal is a search target, not a request to change backends.
    # Use the normal Auto/Local/Hybrid command; checkpoint publication happens
    # separately *after* it finishes so the direct search remains identical.
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
    if mode in ("auto", "goal", "local", "both", "hybrid") and splice and not has_named_goal:
        if mode == "auto" or has_route:
            raise ValueError(f"{mode} {level} {splice} needs a named goal file "
                             f"(expected {goal_file})")
    if mode == "local":
        command = ["local", input_file,
                   "--config", goal_file or path("TAS_GOAL_TEMPLATE", "../splices/{level}/{splice}.txt"),
                   *common]
        if "TAS_STAGNATION_LOCAL" in env:
            command += ["--stagnation-rounds", env["TAS_STAGNATION_LOCAL"]]
        elif _local_needs_default_stagnation(goal_file, extra):
            command += ["--stagnation-rounds", _shortcut_config_number(
                env, "local", "stagnation-rounds", 50)]
    else:
        command = [mode if mode in ("both", "hybrid") else "auto", input_file]
        if mode == "random":
            command += ["--config", env.get("TAS_RANDOM_CONFIG", "../splices/random-splice.toml"),
                        "--simulate-enemies", "--auto-stagnation-runs",
                        env.get("TAS_STAGNATION_RANDOM", "10")]
        else:
            command += shared
            if mode == "auto":
                auto_runs = (env["TAS_RUNS_AUTO"] if "TAS_RUNS_AUTO" in env else
                             _shortcut_config_number(env, "auto", "runs", 10))
                command += ["--auto-runs", auto_runs]
            if mode in ("auto", "goal", "both", "hybrid") and splice:
                command += ["--goal-config", goal_file]
            if mode == "goal":
                command += ["--auto-runs", env.get("TAS_RUNS_GOAL", "10")]
            if mode in ("multi", "merge", "repair"):
                command += ["--splice-config", path("TAS_MULTI_TEMPLATE", "../splices/{level}/multi-splicer.toml")]
            if mode == "multi":
                command += ["--auto-runs", env.get("TAS_RUNS_MULTI", "50")]
            elif mode == "merge":
                command += ["--splice-merge-only"]
            elif mode == "repair":
                command += ["--splice-merge-repair-only"]
            if mode in ("both", "hybrid"):
                # These shortcuts internally reuse the named Hybrid coordinator;
                # disable inherited route operations before search, as the
                # direct Auto/Local paths already do by construction.
                command += ["--no-propagation"]
        command += common
    if jaffar:
        command.extend(_JAFFAR_LOCAL if mode == "local" else _JAFFAR_AUTO)
    # The user-facing propagation opt-out is interpreted here for direct
    # Auto/Local; it isn't a valid option of their standalone search backend.
    if mode not in ("both", "hybrid"):
        extra = tuple(item for item in extra if item not in
                      ("--no-propagation", "--no-splice-propagation"))
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
        skip_propagation = any(flag in extra for flag in
                               ("--no-propagation", "--no-splice-propagation"))
        command = build_command(selected, level, splice, env=env, extra=extra, jaffar=jaffar)
        print(shlex.join(command), flush=True)
        if dry:
            continue
        if selected != "check":
            (ROOT / "wip").mkdir(parents=True, exist_ok=True)

        def last_option(option: str, default: str | None = None) -> str | None:
            value = default
            for index, item in enumerate(command[:-1]):
                if item == option:
                    value = command[index + 1]
                elif item.startswith(option + "="):
                    value = item.split("=", 1)[1]
            return value

        output_name = last_option("--output")
        if output_name is not None:
            (ROOT / output_name).parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(command, cwd=ROOT, check=False)
            exit_code = result.returncode
        except KeyboardInterrupt:
            # Direct optimisers save individual verified improvements while
            # running. Publish the most recent file even when stopped early.
            exit_code = 130
        if not splice or selected not in ("auto", "local", "goal", "both", "hybrid"):
            if exit_code:
                return exit_code
            continue
        if exit_code not in (0, 130):
            return exit_code
        input_name = command[3]
        replay_name = last_option("--replay-output")
        goal_name = _template(env, "TAS_GOAL_TEMPLATE", "../splices/{level}/{splice}.txt",
                              level=level, splice=splice)
        goal_path = ROOT / goal_name
        if not goal_path.exists() and goal_path.suffix == ".txt":
            goal_path = goal_path.with_suffix(".toml")
        legacy_goal = False
        if selected in ("auto", "local", "goal") and goal_path.is_file():
            from nv14_standalone_checkpoint import (publish_named_checkpoint,
                                                    supports_named_publication)
            legacy_goal = not supports_named_publication(goal_path)
            if legacy_goal:
                print("[standalone:checkpoint] legacy Local window goal; "
                      "shared population checkpoint publishing skipped", flush=True)
            else:
                try:
                    publish_named_checkpoint(
                        input_path=ROOT / input_name, output_path=ROOT / output_name,
                        replay_output_path=(ROOT / replay_name if replay_name else None),
                        goal_path=goal_path, name=splice,
                        config_path=(ROOT / last_option("--config")
                                     if selected != "local" and last_option("--config") else None),
                        levels_file_path=(ROOT / last_option("--levels-file")
                                          if last_option("--levels-file") else None),
                    )
                except (ValueError, RuntimeError, OSError) as exc:
                    # Publishing is an add-on, not a reason to invalidate an
                    # otherwise successful direct Auto/Local search.
                    print(f"[standalone:checkpoint] unable to publish {splice!r}: "
                          f"{exc}", file=sys.stderr, flush=True)
        # Keep the existing named-stage propagation as an optional *post*-pass.
        # Crucially, it cannot consume any of the standalone search budget or
        # alter which seeds the direct backend explores.
        if exit_code:
            return exit_code
        route = _template(env, "TAS_MULTI_TEMPLATE",
                          "../splices/{level}/multi-splicer.toml", level=level)
        if skip_propagation or legacy_goal or not (ROOT / route).is_file():
            continue
        from nv14_standalone_checkpoint import post_search_propagation_requested
        config_name = last_option("--config", env.get("TAS_CONFIG", "examples/config.toml"))
        repair, merge = post_search_propagation_requested(ROOT / config_name, ROOT / route)
        if not (repair or merge):
            continue
        follow_up = [sys.executable, str(ROOT / "optimize_replay.py"),
                     "auto", input_name, "--config", config_name,
                     "--splice-config", route, "--output", output_name]
        if replay_name:
            follow_up += ["--replay-output", replay_name]
        follow_up += ["--workers", last_option("--workers", "15"),
                      "--repair" if repair else "--merge"]
        print("[standalone:propagation] post-search merge/repair (no startup merge)", flush=True)
        print(shlex.join(follow_up), flush=True)
        code = subprocess.run(follow_up, cwd=ROOT, check=False).returncode
        if code:
            return code
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as error:
        print(f"tas.py: {error}", file=sys.stderr)
        sys.exit(2)
