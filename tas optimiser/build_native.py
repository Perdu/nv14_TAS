"""Build and validate the unified native engine/search module in place."""
from __future__ import annotations

import argparse
import importlib.machinery
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def _extension_candidates(module_name: str) -> tuple[Path, ...]:
    return tuple(
        ROOT / f"{module_name}{suffix}"
        for suffix in importlib.machinery.EXTENSION_SUFFIXES
    )


def _backend_probe() -> dict[str, object]:
    command = [
        sys.executable,
        "-c",
        (
            "import json, nv14_native, nv14_search; "
            "engine = nv14_native.backend_info(); "
            "search = nv14_search.backend_info(); "
            "unified = engine.get('module_file') == search.get('module_file'); "
            "print(json.dumps({'available': bool(engine.get('available') and "
            "search.get('available') and unified), 'unified_module': unified, "
            "'engine': engine, 'search': search}, "
            "sort_keys=True))"
        ),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report the current backend without compiling",
    )
    parser.add_argument(
        "--no-force",
        action="store_true",
        help="allow setuptools to reuse an up-to-date object file",
    )
    args = parser.parse_args()

    if not args.check:
        candidates = _extension_candidates("_nv14_native")
        before = {
            path: path.stat().st_mtime_ns for path in candidates if path.is_file()
        }
        command = [sys.executable, "setup.py", "build_ext", "--inplace"]
        if not args.no_force:
            command.append("--force")
        environment = os.environ.copy()
        # Some embedded Python distributions retain the compiler used to
        # build Python even when it is not installed in the current image.
        # Respect an explicit CC; otherwise use an available conventional C
        # compiler rather than failing on that stale sysconfig value.
        if os.name != "nt" and "CC" not in environment:
            for candidate in ("cc", "gcc", "clang"):
                located = shutil.which(candidate)
                if located is not None:
                    environment["CC"] = located
                    break
        subprocess.run(command, cwd=ROOT, env=environment, check=True)

        after = {
            path: path.stat().st_mtime_ns for path in candidates if path.is_file()
        }
        built = any(path.is_file() for path in candidates)
        if not built:
            raise SystemExit(
                "native build did not produce the required _nv14_native extension"
            )
        if not args.no_force:
            stale = all(
                path in before and before[path] == after[path]
                for path in candidates
                if path in after
            )
            if stale:
                raise SystemExit(
                    "native build did not refresh required extension: "
                    "_nv14_native"
                )

    info = _backend_probe()
    print(json.dumps(info, indent=2, sort_keys=True))
    if not info.get("available"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
