#!/usr/bin/env python3
"""Rebuild the optional N v1.4 video artwork from the original user-supplied SWF.

Development-only dependencies: Java, JPEXS FFDec 26.3.0, Pillow and PyMuPDF.
Runtime video export does not import this module or need Java, FFDec or PyMuPDF.

    python tools/extract_video_assets.py --swf n_v14.swf \\
        --ffdec-jar /path/to/ffdec.jar --output nv14_assets

FFDec's ordinary PNG exporter drops the ninja's zero-height hairline limbs.
We flatten the original SVG paths into game coordinates first and rasterise
Flash hairlines at one game pixel. No hand-drawn substitute poses are used.
This deliberately supports this SWF's ninja path subset, not arbitrary SWFs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zlib

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
FFDEC = "https://www.free-decompiler.com/flash"
SOURCE_SHA256 = "9db8e7b1e2d15dfa3e378690dd35c17b3818a0cc85dc46e2ae0e9ef4d93b18c1"
IDENTITY = (1, 0, 0, 1, 0, 0)
NUMBER = r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?"
NINJA_FRAMES = tuple(range(1, 105)) + (106,)
# name: (symbol ID, linkage name, source frame, ActionScript _xscale / 100)
OBJECTS = {
    "gold": (889, "debugGoldMC", 1, .06),
    "mine": (882, "debugMineMC", 1, .08),
    "exit": (848, "debugExitMC", 1, .24),
    "exit_open": (848, "debugExitMC", 31, .24),
    "exit_switch": (845, "debugExitTriggerMC", 1, .12),
    "exit_switch_open": (845, "debugExitTriggerMC", 2, .12),
    "thwump": (840, "debugThwompMC", 1, .18),
    "launchpad": (878, "debugLaunchPadMC", 20, .15),
    "launchpad_active": (878, "debugLaunchPadMC", 2, .15),
    "door": (870, "debugTestDoorMC", 55, .24),
    "door_regular": (870, "debugTestDoorMC", 34, .24),
    "door_trap": (870, "debugTestDoorMC", 54, .24),
    "drone": (816, "debugDroneMC", 2, .18),
    "drone_zap": (816, "debugDroneMC", 2, .18),
    "drone_eye": (1305, "debugDroneEyeMC", 1, .18),
    "drone_chaingun_eye": (800, "debugChainTurretMC", 1, .18),
    "drone_chase_idle": (816, "debugDroneMC", 3, .18),
    "drone_chase_active": (816, "debugDroneMC", 4, .18),
    "drone_laser": (816, "debugDroneMC", 51, .18),
    "drone_laser_prefire": (816, "debugDroneMC", 28, .18),
    "drone_laser_firing": (816, "debugDroneMC", 29, .18),
    "drone_chaingun": (816, "debugDroneMC", 52, .18),
    "drone_chaingun_prefire": (816, "debugDroneMC", 54, .18),
    "drone_chaingun_firing": (816, "debugDroneMC", 56, .18),
    "floorguard": (819, "debugFloorGuardMC", 1, .12),
    "floorguard_active": (819, "debugFloorGuardMC", 2, .12),
    "turret": (830, "debugTurretMC", 29, .12),
    "turret_firing": (830, "debugTurretMC", 18, .12),
    "homing_launcher": (839, "debugHomingLauncherMC", 1, .12),
    "homing_launcher_active": (839, "debugHomingLauncherMC", 4, .12),
    "door_switch": (843, "debugDoorTriggerMC", 1, .075),
    "door_switch_trap": (843, "debugDoorTriggerMC", 1, .05),
    "door_switch_open": (843, "debugDoorTriggerMC", 2, .075),
    "door_switch_trap_open": (843, "debugDoorTriggerMC", 2, .05),
    "rocket": (835, "debugHomingRocketMC", 1, 1.0),
    "bounce_block": (879, "debugBounceBlockMC", 1, .192),
    "oneway": (841, "debugOneWayPlatformMC", 1, .24),
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tags(data, offset=0):
    while offset < len(data):
        header, = struct.unpack_from("<H", data, offset)
        offset += 2
        code, length = header >> 6, header & 63
        if length == 63:
            length, = struct.unpack_from("<I", data, offset)
            offset += 4
        yield code, data[offset:offset + length]
        offset += length


def swf_metadata(path):
    raw = Path(path).read_bytes()
    if raw[:3] == b"CWS":
        data = zlib.decompress(raw[8:])
    elif raw[:3] == b"FWS":
        data = raw[8:]
    else:
        raise ValueError("Expected a CWS/FWS Flash SWF")
    offset = (5 + 4 * (data[0] >> 3) + 7) // 8
    fps = struct.unpack_from("<H", data, offset)[0] / 256
    result = {"frame_rate": fps, "labels": {}}
    for code, payload in tags(data, offset + 4):
        if code == 9:
            result["background"] = list(payload)
        elif code == 39:
            sid, count = struct.unpack_from("<HH", payload)
            frame, labels = 1, {}
            for subcode, subdata in tags(payload, 4):
                if subcode == 43:
                    labels[subdata.split(b"\0", 1)[0].decode("utf-8")] = frame
                elif subcode == 1:
                    frame += 1
            result["labels"][str(sid)] = labels
    return result


def matrix(text):
    values = tuple(float(x) for x in re.findall(NUMBER, text))
    if not text:
        return IDENTITY
    if not text.startswith("matrix(") or len(values) != 6:
        raise ValueError(f"Unsupported SVG transform: {text}")
    return values


def multiply(left, right):
    a, b, c, d, e, f = left
    x, y, z, w, p, q = right
    return a*x+c*y, b*x+d*y, a*z+c*w, b*z+d*w, a*p+c*q+e, b*p+d*q+f


def flat_path(path, transform):
    tokens = re.findall(r"[A-Za-z]|" + NUMBER, path)
    result, i = [], 0
    a, b, c, d, e, f = transform
    while i < len(tokens):
        token = tokens[i]
        if token in ("M", "L", "Q", "C", "Z", "z"):
            result.append(token)
            i += 1
        elif token.isalpha():
            raise ValueError(f"Unsupported ninja SVG path command {token}")
        else:
            x, y = float(token), float(tokens[i+1])
            result.extend((f"{a*x+c*y+e:.6f}", f"{b*x+d*y+f:.6f}"))
            i += 2
    return " ".join(result)


def ninja_png(source, destination):
    import fitz
    root = ET.parse(source).getroot()
    references = {e.get("id"): e for e in root.iter() if e.get("id")}
    paths = []

    def walk(element, transform, depth=0):
        if depth > 50:
            raise ValueError("SVG reference recursion limit")
        transform = multiply(transform, matrix(element.get("transform", "")))
        kind = element.tag.split("}")[-1]
        if kind == "use":
            ref = references.get(element.get("{" + XLINK + "}href")[1:])
            # JPEXS omits empty registration-marker sprite definitions.
            if ref is not None:
                walk(ref, transform, depth+1)
        elif kind == "path":
            attributes = {k: v for k, v in element.attrib.items()
                          if not k.startswith("{") and k not in ("id", "transform")}
            attributes["d"] = flat_path(attributes["d"], transform)
            if attributes.get("stroke", "none") != "none":
                if element.get("{" + FFDEC + "}has-small-stroke") == "true":
                    attributes["stroke-width"] = "1"
                else:
                    determinant = abs(transform[0]*transform[3] - transform[1]*transform[2])
                    attributes["stroke-width"] = str(float(attributes.get("stroke-width", "1")) * math.sqrt(determinant))
            paths.append(ET.Element("path", attributes))
        elif kind not in ("defs",):
            for child in element:
                walk(child, transform, depth+1)

    group = root.find("{" + SVG + "}g")
    if group is None:
        raise ValueError("Missing ninja display list")
    offset = matrix(group.get("transform", ""))
    # Fixed canvas; origin (0,0) is (32,32) game pixels in all exported frames.
    base = multiply((.2, 0, 0, .2, 32, 32), (1, 0, 0, 1, -offset[4], -offset[5]))
    walk(group, base)
    normalised = ET.Element("svg", {"xmlns": SVG, "width": "64", "height": "64", "viewBox": "0 0 64 64"})
    normalised.extend(paths)
    with fitz.open(stream=ET.tostring(normalised), filetype="svg") as document:
        document[0].get_pixmap(matrix=fitz.Matrix(4, 4), alpha=True).save(destination)
    joints = {}
    for child in group:
        if child.get("id") in ("footL", "footR", "handL", "handR", "pelvis", "shoulder"):
            local = matrix(child.get("transform", ""))
            joints[child.get("id")] = [round(local[4]*.2, 6), round(local[5]*.2, 6)]
    return joints


def export(java, jar, swf, output, ids, selection, fmt, zoom=1):
    command = [java, "-Djava.awt.headless=true", "-jar", str(jar), "-onerror", "abort",
               "-selectid", ids, "-select", selection, "-zoom", str(zoom),
               "-format", "sprite:"+fmt, "-export", "sprite", str(output), str(swf)]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if completed.returncode:
        raise RuntimeError("JPEXS export failed:\n" + completed.stdout[-6000:])
    return completed.stdout.splitlines()[0]


def build(swf, jar, output, java="java"):
    from PIL import Image
    swf, jar, output = Path(swf).resolve(), Path(jar).resolve(), Path(output).resolve()
    if sha256(swf) != SOURCE_SHA256:
        raise ValueError("This extractor is pinned to the supplied N v1.4 SWF; SHA-256 mismatch")
    metadata = swf_metadata(swf)
    objects_by_id = {}
    for sid, name, frame, scale in OBJECTS.values():
        objects_by_id.setdefault(sid, set()).add(frame)
    ids = ",".join(str(sid) for sid in sorted(objects_by_id))
    selection = ",".join(f"{sid}:" + ",".join(map(str, sorted(frames))) for sid, frames in sorted(objects_by_id.items()))
    with tempfile.TemporaryDirectory(prefix="nv14-assets-") as temporary:
        temporary = Path(temporary)
        print("Exporting original ninja SVG poses...")
        version = export(java, jar, swf, temporary/"ninja", "898", "898:1-104,106", "svg")
        print("Exporting original object artwork...")
        export(java, jar, swf, temporary/"object-svg", ids, selection, "svg")
        export(java, jar, swf, temporary/"object-png", ids, selection, "png", zoom=2)
        (output/"ninja").mkdir(parents=True, exist_ok=True)
        (output/"objects").mkdir(parents=True, exist_ok=True)
        manifest = {"schema_version": 1, "source_swf_sha256": SOURCE_SHA256,
                    "source_swf_name": swf.name, "extractor": version,
                    "source_frame_rate": metadata["frame_rate"], "background": metadata["background"],
                    "ninja": {"symbol_id": 898, "symbol": "testNinjaMCm", "source_scale": .2,
                              "labels": metadata["labels"]["898"], "frames": {}}, "objects": {}}
        for frame in NINJA_FRAMES:
            relative = f"ninja/{frame:04d}.png"
            source = temporary/"ninja"/"DefineSprite_898_testNinjaMCm"/f"{frame}.svg"
            joints = ninja_png(source, output/relative)
            manifest["ninja"]["frames"][str(frame)] = {"file": relative, "origin": [128, 128],
                "pixels_per_unit": 4, "source_frame": frame, "joints": joints, "sha256": sha256(output/relative)}
        for name, (sid, symbol, frame, scale) in OBJECTS.items():
            directory = f"DefineSprite_{sid}_{symbol}"
            svg = ET.parse(temporary/"object-svg"/directory/f"{frame}.svg").getroot()
            transform = matrix(svg.find("{"+SVG+"}g").get("transform", ""))
            relative = f"objects/{name}.png"
            with Image.open(temporary/"object-png"/directory/f"{frame}.png") as raw:
                rgba = raw.convert("RGBA")
                crop = rgba.getbbox()
                if crop is None:
                    raise ValueError(f"Empty artwork: {name}")
                rgba.crop(crop).save(output/relative)
            manifest["objects"][name] = {"file": relative,
                "origin": [round(2*transform[4]-crop[0], 6), round(2*transform[5]-crop[1], 6)],
                "pixels_per_unit": 2/scale, "symbol_id": sid, "symbol": symbol,
                "source_frame": frame, "source_scale": scale, "source_crop_pixels": list(crop),
                "sha256": sha256(output/relative)}
        (output/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
        (output/"__init__.py").write_text('"""Artwork for the optional video renderer. No runtime imports."""\n', encoding="utf-8")
        print(f"Wrote {len(NINJA_FRAMES)} ninja frames and {len(OBJECTS)} object images to {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--swf", required=True, type=Path)
    parser.add_argument("--ffdec-jar", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("nv14_assets"))
    parser.add_argument("--java", default="java")
    args = parser.parse_args()
    build(args.swf, args.ffdec_jar, args.output, args.java)


if __name__ == "__main__":
    main()
