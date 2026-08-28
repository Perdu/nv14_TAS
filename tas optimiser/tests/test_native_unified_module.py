from __future__ import annotations

from pathlib import Path

import pytest

import nv14_native
import nv14_search


ROOT = Path(__file__).parents[1]


def test_build_defines_one_extension_and_links_core_once() -> None:
    setup_source = (ROOT / "setup.py").read_text(encoding="utf-8")

    assert setup_source.count("Extension(") == 1
    assert setup_source.count('"native/nv14_core.c"') == 1
    assert '"_nv14_search"' not in setup_source
    assert '"native/_nv14_native.c"' in setup_source
    assert not (ROOT / "native" / "_nv14_search_module.c").exists()


def test_cython_source_owns_all_python_facing_native_wrappers() -> None:
    wrapper = (ROOT / "native" / "_nv14_native.pyx").read_text(
        encoding="utf-8"
    )

    assert "cdef class NativeLevel" in wrapper
    assert "cdef class NativeState" in wrapper
    assert "cdef class NativeTrace" in wrapper
    assert "NativeReplayAnalysis = NativeTrace" in wrapper
    assert "cdef class SearchSession" in wrapper
    assert "def evaluate_replay" in wrapper
    assert "return trace.to_dict()" not in wrapper
    assert "return trace" in wrapper
    assert "def evaluate_patches" in wrapper
    assert "def search_patterns" in wrapper
    assert "def search_backend_info" in wrapper


def test_generated_wrapper_avoids_msvc_signed_boundary_literal() -> None:
    """Keep trace-target validation portable to Windows' 32-bit C long."""
    wrapper = (ROOT / "native" / "_nv14_native.pyx").read_text(
        encoding="utf-8"
    )
    generated = (ROOT / "native" / "_nv14_native.c").read_text(
        encoding="utf-8"
    )

    assert "if player_state < 0 or player_state > 7:" in wrapper
    assert "if (player_state < -2147483648" not in wrapper
    assert "__pyx_v_player_state < -2147483648L" not in generated


def test_engine_and_search_facades_resolve_the_same_binary() -> None:
    engine = nv14_native.backend_info()
    search = nv14_search.backend_info()
    if not engine.get("available") or not search.get("available"):
        pytest.skip("unified native extension is not built")

    assert Path(str(engine["module_file"])).resolve() == Path(
        str(search["module_file"])
    ).resolve()
    assert engine["implementation"] == "cython-unified-native"
    assert search["implementation"] == "cython-unified-native"
