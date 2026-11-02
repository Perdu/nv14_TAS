"""Build and validate the native engine/search and rendering modules in place."""
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


def _regenerate_cython_source(*, force: bool = False) -> None:
    """Produce the untracked C wrapper when its Cython source has changed."""
    source = ROOT / "native" / "_nv14_native.pyx"
    generated = source.with_suffix(".c")
    if (
        not force
        and generated.is_file()
        and generated.stat().st_mtime_ns >= source.stat().st_mtime_ns
    ):
        return

    command = [
        sys.executable, "-m", "cython", "-3", "-o",
        str(generated), str(source),
    ]
    try:
        subprocess.run(command, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "Cython regeneration failed. Install the build dependency with "
            "'python -m pip install Cython>=3.2.4' and retry."
        ) from exc


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
            "import json, nv14_native, nv14_search, nv14_vector; "
            "engine = nv14_native.backend_info(); "
            "search = nv14_search.backend_info(); "
            "unified = engine.get('module_file') == search.get('module_file'); "
            "print(json.dumps({'available': bool(engine.get('available') and "
            "search.get('available') and unified), 'unified_module': unified, "
            "'engine': engine, 'search': search, "
            "'renderer': {'available': nv14_vector.native_backend_available()}}, "
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
    rebuild = parser.add_mutually_exclusive_group()
    rebuild.add_argument(
        "--force",
        action="store_true",
        help="force a full native rebuild (incremental builds are the default)",
    )
    rebuild.add_argument(
        "--no-force",
        action="store_true",
        help="legacy alias for the default incremental-build behavior",
    )
    parser.add_argument(
        "--force-cython",
        action="store_true",
        help="regenerate the Cython C wrapper even when it looks up to date",
    )
    args = parser.parse_args()

    if not args.check:
        _regenerate_cython_source(force=args.force_cython)
        candidates = tuple(path for name in ("_nv14_native", "_nv14_render_native")
                           for path in _extension_candidates(name))
        before = {
            path: path.stat().st_mtime_ns for path in candidates if path.is_file()
        }
        command = [sys.executable, "setup.py", "build_ext", "--inplace"]
        if args.force:
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
        for name in ("_nv14_native", "_nv14_render_native"):
            module_candidates = _extension_candidates(name)
            if not any(path.is_file() for path in module_candidates):
                raise SystemExit(
                    f"native build did not produce the required {name} extension"
                )
            if args.force and all(
                    path in before and before[path] == after[path]
                    for path in module_candidates if path in after):
                raise SystemExit(f"native build did not refresh required extension: {name}")

    info = _backend_probe()
    print(json.dumps(info, indent=2, sort_keys=True))
    if not info.get("available"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
