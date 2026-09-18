#!/usr/bin/env python3
"""Rebuild rendering-only particle clips from the pinned original n_v14.swf.

Uses the same development-only FFDec/Pillow dependencies as the video asset
extractor. Each clip excludes its removeMovieClip frame. Run from the source
root with: python -m tools.extract_particle_assets --swf n_v14.swf
    --ffdec-jar /path/to/ffdec.jar --output nv14_assets
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET

from tools.extract_video_assets import SOURCE_SHA256, SVG, export, matrix, sha256

# (linkage, character ID, removeMovieClip frame), from the supplied SWF/AS.
# BloodSpurtMC1 is referenced by AS but is absent from this SWF's exports.
CLIPS = (
    ("debugDustMC1", 922, 33), ("debugDustMC2", 917, 31),
    ("debugBloodSpurtMC2", 925, 32),
    ("debugZapMC1", 973, 10), ("debugZapMC2", 941, 13), ("debugZapMC3", 933, 15),
    ("debugZapVMC1", 945, 10), ("debugZapVMC2", 937, 13), ("debugZapVMC3", 929, 15),
    ("debugFireBallMC1", 969, 15), ("debugFireBallMC2", 948, 14), ("debugFireBallMC3", 951, 11),
    ("debugFireBurstMC1", 966, 19), ("debugFireBurstMC2", 958, 17),
    ("debugRocketSmokeMC1", 985, 28), ("debugRocketSmokeMC2", 977, 23), ("debugRocketSmokeMC3", 981, 27),
    ("debugTurretBulletMC1", 997, 10), ("debugTurretDebrisMC1", 994, 12),
    ("debugChainFlashMC1", 1264, 7), ("debugChainFlashMC2", 1261, 9),
    ("debugChainBulletMC1", 1266, 7), ("debugChainDebrisMC1", 1274, 10),
    ("debugChainDebrisMC2", 1269, 8), ("debugChainDebrisMC3", 1272, 13),
    ("debugLaserChargeMC1", 1288, 10), ("debugLaserChargeMC2", 1285, 14), ("debugLaserChargeMC3", 1282, 15),
)


def build(swf, jar, output, java="java"):
    from PIL import Image
    swf, jar, output = Path(swf).resolve(), Path(jar).resolve(), Path(output).resolve()
    if sha256(swf) != SOURCE_SHA256:
        raise ValueError("Source SWF SHA-256 mismatch")
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if manifest.get("source_swf_sha256") != SOURCE_SHA256:
        raise ValueError("Existing asset pack uses a different source SWF")
    ids = ",".join(str(sid) for _, sid, _ in CLIPS)
    selection = ",".join(f"{sid}:1-{stop-1}" for _, sid, stop in CLIPS)
    clips = {}
    with tempfile.TemporaryDirectory(prefix="nv14-particles-") as temporary:
        temporary = Path(temporary)
        version = export(java, jar, swf, temporary / "svg", ids, selection, "svg")
        export(java, jar, swf, temporary / "png", ids, selection, "png", zoom=2)
        for symbol, sid, stop in CLIPS:
            directory = f"DefineSprite_{sid}_{symbol}"
            (output / "particles" / symbol).mkdir(parents=True, exist_ok=True)
            clip = {"symbol_id": sid, "symbol": symbol, "remove_frame": stop, "frames": {}}
            for frame in range(1, stop):
                svg = ET.parse(temporary / "svg" / directory / f"{frame}.svg").getroot()
                transform = matrix(svg.find("{" + SVG + "}g").get("transform", ""))
                relative = f"particles/{symbol}/{frame:04d}.png"
                with Image.open(temporary / "png" / directory / f"{frame}.png") as raw:
                    rgba = raw.convert("RGBA")
                    crop = rgba.getbbox() or (0, 0, 1, 1)
                    rgba.crop(crop).save(output / relative)
                clip["frames"][str(frame)] = {"file": relative,
                    "origin": [round(2 * transform[4] - crop[0], 6),
                               round(2 * transform[5] - crop[1], 6)],
                    "pixels_per_unit": 2, "source_frame": frame,
                    "sha256": sha256(output / relative)}
                # A Flash hairline remains visible when a gauss shot has
                # zero x/y scale. Preserve its vector path, avoiding singular
                # raster transforms and angle-dependent line widths.
                paths = list(svg.iter("{" + SVG + "}path"))
                if symbol in ("debugTurretBulletMC1", "debugChainBulletMC1") and len(paths) == 1:
                    path = paths[0]
                    values = re.findall(r"[-+]?(?:\d*\.\d+|\d+)", path.get("d", ""))
                    if len(values) == 4 and path.get("stroke"):
                        clip["frames"][str(frame)]["line"] = {
                            "points": [[float(v) for v in values[:2]], [float(v) for v in values[2:]]],
                            "color": path.get("stroke"),
                            "opacity": float(path.get("stroke-opacity", "1")),
                        }
            clips[symbol] = clip
    manifest["particles"] = {"schema_version": 1, "extractor": version,
        "source_frame_rate": 120, "clips": clips,
        "notes": ["Scales are applied at render time in source MovieClip units.",
                  "Missing debugBloodSpurtMC1 uses the exported debugBloodSpurtMC2.",
                  "Source calls to SpawnLaserSpark/SpawnRocketDeath are absent; their unused clips are not included."]}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(clips)} clips, {sum(len(c['frames']) for c in clips.values())} frames")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--swf", required=True, type=Path)
    parser.add_argument("--ffdec-jar", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("nv14_assets"))
    parser.add_argument("--java", default="java")
    args = parser.parse_args()
    build(args.swf, args.ffdec_jar, args.output, args.java)


if __name__ == "__main__":
    main()
