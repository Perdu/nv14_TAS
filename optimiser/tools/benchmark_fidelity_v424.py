"""Run the same comparative benchmark harness against v4.23 and v4.24.

Run separately per project root to avoid module-cache contamination. The C path
uses the public opaque-state API with prepacked inputs and a reusable state,
matching repeated optimiser suffix evaluation without Python per-tick work.
For example, from the v4.24 project root on Linux::

    taskset -c 8 python tools/benchmark_fidelity_v424.py ../v4.23 > baseline.json
    taskset -c 8 python tools/benchmark_fidelity_v424.py . > final.json

Choose an available CPU for taskset, or omit it on other platforms. Timing
checksums count executed ticks; the regression suite checks behavioral parity.
"""
from __future__ import annotations

import argparse
import ctypes as C
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time


class Input(C.Structure):
    _fields_ = [("left", C.c_uint8), ("right", C.c_uint8),
                ("jump", C.c_uint8), ("jump_trigger", C.c_int8)]


class Result(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in (
        "frame_before", "frame_after", "jump_events_before", "jump_events_after")]
    _fields_ += [(name, C.c_uint8) for name in (
        "dead", "level_complete", "jumped", "collected_gold", "exploded_mine",
        "opened_exit", "unsupported", "jump_callable")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--native-evaluations", type=int, default=1000)
    parser.add_argument("--python-evaluations", type=int, default=40)
    parser.add_argument("--repetitions", type=int, default=7)
    args = parser.parse_args()
    if args.native_evaluations < 4 or args.python_evaluations < 1 or args.repetitions < 1:
        parser.error("native evaluations must be >=4; Python evaluations and repetitions must be positive")
    project = args.project.resolve()
    sys.path.insert(0, str(project))
    import _nv14_native  # Registers each object module's native callbacks.
    from tools.benchmark_engine import _prepare_scenarios, _run_once
    scenarios = _prepare_scenarios(project)
    core_path = next(project.glob("_nv14_native*.so"))
    core = C.CDLL(str(core_path))
    pointer = C.c_void_p
    declarations = {
        "nv14_level_create": (pointer, [C.c_char_p, C.c_size_t, C.c_int, pointer]),
        "nv14_level_release": (None, [pointer]),
        "nv14_state_create": (pointer, [pointer, pointer]),
        "nv14_state_destroy": (None, [pointer]),
        "nv14_state_copy_into": (C.c_int, [pointer, pointer, pointer]),
        "nv14_state_step_many": (C.c_int, [pointer, C.POINTER(Input), C.c_size_t,
            C.c_int, C.c_int, C.POINTER(C.c_size_t), C.POINTER(Result)]),
    }
    for name, (result_type, arguments) in declarations.items():
        function = getattr(core, name)
        function.restype = result_type
        function.argtypes = arguments
    prepared = []
    mutated = []
    for scenario in scenarios:
        source = scenario.level.source_level_string.encode()
        level = core.nv14_level_create(source, len(source), 1, None)
        assert level
        initial = core.nv14_state_create(level, None)
        reusable = core.nv14_state_create(level, None)
        assert initial and reusable
        inputs = (Input * len(scenario.frames))(*(Input(
            frame.left, frame.right, frame.jump,
            -1 if frame.jump_trigger is None else frame.jump_trigger)
            for frame in scenario.frames))
        prepared.append((level, initial, reusable, inputs, len(inputs)))
        for variant in range(4):
            changed = []
            for index, frame in enumerate(scenario.frames):
                left, right, jump = frame.left, frame.right, frame.jump
                trigger = -1 if frame.jump_trigger is None else frame.jump_trigger
                if variant == 0:
                    jump, trigger = False, 0
                elif variant == 1:
                    left, right = right, left
                elif variant == 2 and index < len(inputs) // 2:
                    left, right, jump, trigger = False, False, False, 0
                elif variant == 3 and len(inputs) // 4 <= index < len(inputs) // 2:
                    left, right = right, left
                changed.append(Input(left, right, jump, trigger))
            packed = (Input * len(changed))(*changed)
            mutated.append((level, initial, reusable, packed, len(packed)))

    consumed = C.c_size_t()
    last = Result()
    consumed_pointer, last_pointer = C.byref(consumed), C.byref(last)
    copy, step = core.nv14_state_copy_into, core.nv14_state_step_many

    def native_once(item):
        _, initial, reusable, inputs, count = item
        assert copy(reusable, initial, None) == 0
        assert step(reusable, inputs, count, 1, 1,
                    consumed_pointer, last_pointer) == 0
        assert consumed.value == count and last.level_complete and not last.dead
        return consumed.value

    def native_mutated_once(item):
        _, initial, reusable, inputs, count = item
        assert copy(reusable, initial, None) == 0
        assert step(reusable, inputs, count, 1, 1,
                    consumed_pointer, last_pointer) == 0
        return consumed.value

    mutated_outcomes = []
    for item in mutated:
        native_mutated_once(item)
        mutated_outcomes.append({"ticks": consumed.value,
            "dead": bool(last.dead), "complete": bool(last.level_complete)})

    def measure(backend, items, callback, evaluations):
        for item in items:
            callback(item)
        timings, checksums = [], []
        for _ in range(args.repetitions):
            checksum = 0
            started = time.perf_counter()
            for item in items:
                for _ in range(evaluations):
                    checksum += callback(item)
            timings.append(time.perf_counter() - started)
            checksums.append(checksum)
        assert len(set(checksums)) == 1
        return {"backend": backend, "repetition_seconds": timings,
                "median_seconds": statistics.median(timings),
                "evaluations_per_scenario": evaluations,
                "evaluations_per_second": len(items) * evaluations / statistics.median(timings),
                "ticks_per_second": checksums[0] / statistics.median(timings),
                "checksum": checksums[0]}

    gc.disable()
    try:
        report = {
            "project": str(project), "repetitions": args.repetitions,
            "environment": {
                "python": sys.version,
                "platform": platform.platform(),
                "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                "native_module": str(core_path),
                "native_module_sha256": hashlib.sha256(core_path.read_bytes()).hexdigest(),
                "strict_fp": bool(_nv14_native.backend_info()["strict_fp"]),
            },
            "scenarios": [{"path": s.path, "ticks": len(s.frames)} for s in scenarios],
            "native": measure("native prepacked pooled state", prepared,
                              native_once, args.native_evaluations),
            "native_mutated": measure("native prepacked failed candidates", mutated,
                              native_mutated_once, args.native_evaluations // 4),
            "mutated_candidate_outcomes": mutated_outcomes,
            "python": measure("Python state creation and stepping", scenarios,
                              lambda item: _run_once(item)[0], args.python_evaluations),
        }
    finally:
        for level, initial, reusable, _, _ in prepared:
            core.nv14_state_destroy(reusable)
            core.nv14_state_destroy(initial)
            core.nv14_level_release(level)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
