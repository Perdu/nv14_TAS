"""Independent source-body oracle for v4.24's terminal traversal fixes.

The JS fixture embeds unchanged bodies from the supplied ActionScript dump and
records the dump SHA-256, source lines and individual LF-normalised body hashes.
Graphics/ragdoll services are stubs. Only ordinary property access and binary64
control flow are tested; this does not substitute for AVM1 null/undefined,
enumeration, scoring UI, or a complete original-game replay verification.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

import nv14_engine as engine


FIXTURE = Path(__file__).with_name("v424_actionscript_oracle.js")


@pytest.fixture(scope="module")
def source_oracle():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed for the extracted source-body oracle")
    run = subprocess.run([node, str(FIXTURE)], check=True, capture_output=True, text=True)
    return json.loads(run.stdout)


def test_extracted_actionscript_bodies_match_recorded_hashes():
    text = FIXTURE.read_text(encoding="utf-8")
    assert "// AS_SOURCE_SHA256 d973c7c4f9a1297e5705fd8807687b6abcc4cd621bba5e38b5743dd685698bdb" in text
    manifest_line = next(line for line in text.splitlines() if line.startswith("// AS_MANIFEST "))
    manifest = json.loads(manifest_line.removeprefix("// AS_MANIFEST "))
    assert len(manifest) == 39
    for name, provenance in manifest.items():
        body = text.split(f"// BEGIN AS {name}\n", 1)[1].split(f"\n// END AS {name}", 1)[0]
        assert hashlib.sha256(body.encode()).hexdigest() == provenance["sha256_lf"]
        assert provenance["line"] > 0


@pytest.mark.parametrize("backend", ["python", "native"])
@pytest.mark.parametrize("case,objects,ticks", [
    ("later_gold", "5^60,60!0^60,76.3!11^60,60,60,60", 2),
    ("same_cell_mine", "5^60,60!12^60,60!11^60,60,60,60", 2),
    ("later_cell_mine", "5^60,60!12^60,74.3!11^60,60,60,60", 2),
    ("death_pad", "5^60,70!12^60,70!2^60,72,0,-1", 1),
])
def test_lifecycle_matches_unchanged_source_bodies(source_oracle, backend, case, objects, ticks):
    module = engine if backend == "python" else pytest.importorskip("_nv14_native")
    level = module.parse_level_string("0" * 713 + "|" + objects, simulate_enemies=True)
    state = level.initial_state()
    for _ in range(ticks):
        if backend == "python":
            state.step(engine.InputFrame(False, False, False, False), level.tiles)
        else:
            state.step(False, False, False, False)
    if backend == "python":
        actual = {"complete": state.level_complete, "dead": state.player.dead,
                  "bonus": state.static_state.gold_bonus_ticks,
                  "x": state.player.pos.x, "y": state.player.pos.y}
    else:
        snapshot = state.snapshot()
        actual = {"complete": snapshot["static_state"]["level_complete"],
                  "dead": snapshot["player"]["dead"],
                  "bonus": snapshot["static_state"]["gold_bonus_ticks"],
                  "x": snapshot["player"]["pos"][0],
                  "y": snapshot["player"]["pos"][1]}
    expected = source_oracle[case]
    for key, value in actual.items():
        assert value == expected[key], (case, key, value, expected[key])
    if case == "death_pad":
        assert expected["state"] == 4
        assert expected["normal_tick"] and expected["think_restored"]
        assert expected["objects_disabled"]


def test_zap_rounded_tangency_matches_unchanged_source_body(source_oracle):
    expected = source_oracle["zap_tangent"]
    assert expected["dead"] is False
    tiles = engine.TileMap("0" * 713)
    drone = engine.ZapDrone.from_spec(
        engine.ObjectSpec(engine.OBJTYPE_DRONE, (36.0, 36.0, 2.0, 0.0, 0.0, 0.0), 0),
        tiles,
    )
    player = engine.Player.spawn(expected["x"], expected["y"])
    drone.test_player(player)
    assert player.dead == expected["dead"]
