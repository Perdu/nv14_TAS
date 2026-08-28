"""Build metadata for the unified n v1.4 native extension.

The optimiser remains importable directly from the extracted source tree when
the extension cannot be built, although Auto, Local and jump-pattern search
require it. ``build_native.py`` is the supported command for an in-place native
build; keeping the extension optional here lets packaging tools install the
Python orchestration and portable reference emulator on machines without a C
compiler.
"""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import sysconfig
import tempfile

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext


def _repair_missing_configured_compiler() -> None:
    """Handle embedded Pythons whose recorded build compiler is unavailable."""
    if os.name == "nt" or "CC" in os.environ:
        return
    configured = shlex.split(sysconfig.get_config_var("CC") or "")
    if not configured or shutil.which(configured[0]) is not None:
        return
    for candidate in ("cc", "gcc", "clang"):
        located = shutil.which(candidate)
        if located is not None:
            os.environ["CC"] = located
            return


_repair_missing_configured_compiler()


class StrictFloatingPointBuildExt(build_ext):
    """Apply optimising flags without changing IEEE-754 expression semantics."""

    def _supports_unix_flag(self, flag: str) -> bool:
        compiler_command = self.compiler.compiler_so
        if isinstance(compiler_command, str):
            compiler_command = [compiler_command]
        with tempfile.TemporaryDirectory(prefix="nv14-cc-probe-") as directory:
            source = Path(directory) / "probe.c"
            output = Path(directory) / "probe.o"
            source.write_text("double f(double x) { return x + 1.0; }\n")
            completed = subprocess.run(
                [
                    *compiler_command,
                    flag,
                    "-Werror",
                    "-c",
                    str(source),
                    "-o",
                    str(output),
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return completed.returncode == 0

    def build_extensions(self) -> None:
        compiler_type = self.compiler.compiler_type
        if compiler_type == "msvc":
            compile_args = ["/std:c11", "/O2", "/fp:strict"]
            if struct.calcsize("P") == 4:
                compile_args.append("/arch:SSE2")
        else:
            # GCC, Clang and Apple Clang all accept these options.  In
            # particular, do not use -ffast-math: collision-side tests depend
            # on exact double-precision rounding and NaN behaviour.
            compile_args = [
                "-std=c11",
                "-O3",
                "-fno-fast-math",
                "-ffp-contract=off",
            ]
            # Prevent legacy x87 intermediates from retaining more precision
            # than binary64. GCC supports this directly; some Clang/Apple
            # Clang releases reject it, so probe instead of assuming.
            if self._supports_unix_flag("-fexcess-precision=standard"):
                compile_args.append("-fexcess-precision=standard")
            if struct.calcsize("P") == 4:
                # On 32-bit x86, prefer SSE2 binary64 arithmetic to the x87
                # extended-precision register stack. Probing keeps this safe
                # for non-x86 32-bit targets.
                for flag in ("-msse2", "-mfpmath=sse"):
                    if self._supports_unix_flag(flag):
                        compile_args.append(flag)

        for extension in self.extensions:
            extension.extra_compile_args = [
                *extension.extra_compile_args,
                *compile_args,
            ]
        super().build_extensions()


native_core_sources = [
    "native/nv14_core.c",
    "native/nv14_rays.c",
    "native/nv14_objects_basic.c",
    "native/nv14_objects_guard.c",
    "native/nv14_objects_ranged.c",
    "native/nv14_objects_drones.c",
    "native/nv14_drone_weapons.c",
]

native_core_depends = [
    "native/nv14_core.h",
    "native/nv14_internal.h",
    "native/nv14_rays.h",
    "native/nv14_objects_basic.h",
    "native/nv14_objects_guard.h",
    "native/nv14_objects_ranged.h",
    "native/nv14_drones_internal.h",
    "native/nv14_objects_drones.h",
    "native/nv14_drone_weapons.h",
]


native_extension = Extension(
    "_nv14_native",
    sources=[
        "native/_nv14_native.c",
        "native/nv14_auto.c",
        "native/nv14_patch.c",
        "native/nv14_search.c",
        *native_core_sources,
    ],
    include_dirs=["native"],
    depends=[
        *native_core_depends,
        "native/nv14_search.h",
        "native/nv14_auto.h",
        "native/nv14_patch.h",
    ],
    define_macros=[("NV14_STRICT_FP", "1")],
    export_symbols=[
        "nv14_search_result_init",
        "nv14_search_run",
        "nv14_search_result_destroy",
    ],
    optional=True,
)


setup(
    ext_modules=[native_extension],
    cmdclass={"build_ext": StrictFloatingPointBuildExt},
)
