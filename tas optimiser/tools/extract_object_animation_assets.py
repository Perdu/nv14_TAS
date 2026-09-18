#!/usr/bin/env python3
"""Rebuild complete object MovieClip timelines from the pinned original SWF.

Development dependencies: Java, JPEXS FFDec 26.3.0 and Pillow. Runtime rendering
does not import this tool or require the original SWF. Run from the source root:

    python -m tools.extract_object_animation_assets --swf n_v14.swf \
        --ffdec-jar /path/to/ffdec.jar --output nv14_assets

Original frame numbers, labels and timeline actions are retained. Stop frames
are pictures, not removal frames. The source scale is applied exactly once by
encoding it into each image's pixels_per_unit, just like the static object pack.
Morph shapes are rendered by FFDec with their original per-frame ratios. The
dependency audit recursively checks sprite children: the pinned gameplay clips
currently contain shapes/morphs only, so there is no independently ticking child
MovieClip that would need its own runtime clock or action interpreter.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import tempfile
import xml.etree.ElementTree as ET
import zlib

from tools.extract_video_assets import SOURCE_SHA256, SVG, export, matrix, sha256, tags


# key: (original character ID, linkage name, ActionScript _xscale / 100).
# Tile xw in the source is 12 (half of the 24-pixel tile width).
CLIPS = {
    "gold": (889, "debugGoldMC", .06),
    "exit": (848, "debugExitMC", .24),
    "door": (870, "debugTestDoorMC", .24),
    "launchpad": (878, "debugLaunchPadMC", .15),
    "turret": (830, "debugTurretMC", .12),
    "turret_crosshair": (824, "debugTurretCrosshairMC", .18),
    "homing_launcher": (839, "debugHomingLauncherMC", .12),
    "drone": (816, "debugDroneMC", .18),
    "laser_blast": (1296, "debugLaserBlastMC", 1.0),
    "rocket": (835, "debugHomingRocketMC", 1.0),
    "floorguard": (819, "debugFloorGuardMC", .12),
    "mine": (882, "debugMineMC", .08),
    "door_switch": (843, "debugDoorTriggerMC", .075),
    "exit_switch": (845, "debugExitTriggerMC", .12),
}

CHARACTER_TAGS = {2: "DefineShape", 22: "DefineShape2", 32: "DefineShape3",
                  83: "DefineShape4", 39: "DefineSprite", 46: "DefineMorphShape",
                  84: "DefineMorphShape2"}


def decode_actions(data):
    """Interpret only the AVM1 subset actually used by these frame scripts.

    Fail closed on unfamiliar bytecode instead of silently ignoring a source
    action. This is metadata extraction, not an arbitrary ActionScript VM.
    """
    result, stack, offset = [], [], 0
    while offset < len(data):
        opcode = data[offset]
        offset += 1
        if opcode == 0:
            break
        size = 0
        if opcode >= 0x80:
            size = struct.unpack_from("<H", data, offset)[0]
            offset += 2
        payload = data[offset:offset + size]
        offset += size
        if opcode == 0x96:  # Push
            cursor = 0
            while cursor < len(payload):
                kind = payload[cursor]
                cursor += 1
                if kind == 0:
                    end = payload.index(0, cursor)
                    value = payload[cursor:end].decode("utf-8")
                    cursor = end + 1
                elif kind == 5:
                    value = bool(payload[cursor])
                    cursor += 1
                elif kind == 6:
                    # AVM1 doubles store the two little-endian words reversed.
                    value = struct.unpack("<d", payload[cursor+4:cursor+8]
                                          + payload[cursor:cursor+4])[0]
                    cursor += 8
                elif kind == 7:
                    value = struct.unpack_from("<i", payload, cursor)[0]
                    cursor += 4
                else:
                    raise ValueError(f"Unexpected AVM1 Push type {kind}")
                stack.append(value)
        elif opcode == 0x1C:  # GetVariable
            if stack[-1] != "this":
                raise ValueError("Object timeline refers to an unexpected variable")
        elif opcode == 0x52:  # CallMethod
            method, target, count = stack.pop(), stack.pop(), int(stack.pop())
            args = [stack.pop() for _ in range(count)]
            if target != "this":
                raise ValueError(f"Unexpected action target: {target}")
            if method in ("stop", "play", "removeMovieClip") and not args:
                result.append({"op": {"removeMovieClip": "remove"}.get(method, method)})
            elif method in ("gotoAndStop", "gotoAndPlay") and len(args) == 1:
                result.append({"op": "goto_and_stop" if method == "gotoAndStop"
                               else "goto_and_play", "target": args[0]})
            else:
                raise ValueError(f"Unexpected timeline method: {method} {args}")
            stack.append(None)
        elif opcode == 0x4F:  # SetMember
            value, member, target = stack.pop(), stack.pop(), stack.pop()
            if (target, member) != ("this", "_visible"):
                raise ValueError(f"Unexpected timeline assignment: {target}.{member}")
            result.append({"op": "set_visible", "visible": bool(value)})
        elif opcode == 0x17:  # Pop
            stack.pop()
        elif opcode in (0x06, 0x07):  # Native Play / Stop
            result.append({"op": "play" if opcode == 0x06 else "stop"})
        else:
            raise ValueError(f"Unexpected AVM1 opcode 0x{opcode:02x}")
    if stack:
        raise ValueError("Unbalanced object timeline bytecode")
    return result


def inspect_source(path):
    """Read labels/actions and audit display-list dependencies from SWF tags."""
    raw = Path(path).read_bytes()
    data = zlib.decompress(raw[8:]) if raw[:3] == b"CWS" else raw[8:]
    header_end = (5 + 4 * (data[0] >> 3) + 7) // 8
    frame_rate = struct.unpack_from("<H", data, header_end)[0] / 256
    characters, linkage = {}, {}
    for code, payload in tags(data, header_end + 4):
        if code in CHARACTER_TAGS:
            sid = struct.unpack_from("<H", payload)[0]
            characters[sid] = {"type": CHARACTER_TAGS[code], "payload": payload}
        elif code == 56:  # ExportAssets
            cursor = 2
            for _ in range(struct.unpack_from("<H", payload)[0]):
                sid = struct.unpack_from("<H", payload, cursor)[0]
                cursor += 2
                end = payload.index(0, cursor)
                linkage[sid] = payload[cursor:end].decode("utf-8")
                cursor = end + 1

    def inspect_sprite(sid, ancestors=()):
        if sid in ancestors:
            raise ValueError("Recursive sprite display list")
        payload = characters[sid]["payload"]
        _, frame_count = struct.unpack_from("<HH", payload)
        result = {"symbol_id": sid, "symbol": linkage.get(sid, ""),
                  "frame_count": frame_count, "labels": {}, "actions": {},
                  "action_bytecode": {}, "children": []}
        children, frame = set(), 1
        for code, body in tags(payload, 4):
            if code == 1:
                frame += 1
            elif code == 43:
                result["labels"][body.split(b"\0", 1)[0].decode("utf-8")] = frame
            elif code == 12:
                result["actions"].setdefault(str(frame), []).extend(decode_actions(body))
                result["action_bytecode"].setdefault(str(frame), []).append(body.hex())
            elif code == 26:  # PlaceObject2
                flags = body[0]
                if flags & 128:
                    raise ValueError(f"Sprite {sid} has instance clip actions to audit")
                if flags & 2:
                    children.add(struct.unpack_from("<H", body, 3)[0])
            elif code == 4:  # PlaceObject
                children.add(struct.unpack_from("<H", body)[0])
            elif code in (70, 94):
                raise ValueError(f"Sprite {sid} uses an unaudited placement tag {code}")
        if frame - 1 != frame_count:
            raise ValueError(f"Sprite {sid} frame count mismatch")
        for child in sorted(children):
            character = characters[child]
            metadata = {"symbol_id": child, "type": character["type"]}
            if character["type"] == "DefineSprite":
                metadata["timeline"] = inspect_sprite(child, (*ancestors, sid))
                # FFDec advances embedded timelines by export frame and does not
                # execute AVM1. Require an explicit runtime-clock design rather
                # than quietly baking an incorrect child snapshot into PNGs.
                if metadata["timeline"]["frame_count"] > 1 or metadata["timeline"]["actions"]:
                    raise ValueError(f"Sprite {sid} has independently animated child {child}")
            result["children"].append(metadata)
        return result

    return frame_rate, {key: inspect_sprite(sid) for key, (sid, _, _) in CLIPS.items()}


def build(swf, jar, output, java="java"):
    from PIL import Image

    swf, jar, output = Path(swf).resolve(), Path(jar).resolve(), Path(output).resolve()
    if sha256(swf) != SOURCE_SHA256:
        raise ValueError("Source SWF SHA-256 mismatch")
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if manifest.get("source_swf_sha256") != SOURCE_SHA256:
        raise ValueError("Existing asset pack uses a different source SWF")
    frame_rate, clips = inspect_source(swf)
    ids = ",".join(str(sid) for sid, _, _ in CLIPS.values())
    selection = ",".join(f"{clip['symbol_id']}:1-{clip['frame_count']}"
                         for clip in clips.values())
    with tempfile.TemporaryDirectory(prefix="nv14-object-animations-") as temporary:
        temporary = Path(temporary)
        version = export(java, jar, swf, temporary / "svg", ids, selection, "svg")
        export(java, jar, swf, temporary / "png", ids, selection, "png", zoom=2)
        for key, (sid, symbol, scale) in CLIPS.items():
            clip = clips[key]
            if clip["symbol"] != symbol:
                raise ValueError(f"Linkage mismatch for {key}")
            clip.update(source_scale=scale, frames={})
            directory = f"DefineSprite_{sid}_{symbol}"
            destination = output / "object_animations" / key
            destination.mkdir(parents=True, exist_ok=True)
            for frame in range(1, clip["frame_count"] + 1):
                if any(action["op"] == "remove" for action in clip["actions"].get(str(frame), [])):
                    continue
                svg = ET.parse(temporary / "svg" / directory / f"{frame}.svg").getroot()
                group = svg.find("{" + SVG + "}g")
                transform = matrix(group.get("transform", "")) if group is not None else (1, 0, 0, 1, 0, 0)
                relative = f"object_animations/{key}/{frame:04d}.png"
                with Image.open(temporary / "png" / directory / f"{frame}.png") as raw:
                    rgba = raw.convert("RGBA")
                    crop = rgba.getbbox() or (0, 0, 1, 1)
                    rgba.crop(crop).save(output / relative)
                clip["frames"][str(frame)] = {
                    "file": relative,
                    "origin": [round(2 * transform[4] - crop[0], 6),
                               round(2 * transform[5] - crop[1], 6)],
                    "pixels_per_unit": 2 / scale,
                    "source_frame": frame,
                    "source_crop_pixels": list(crop),
                    "sha256": sha256(output / relative),
                }
    manifest["object_animations"] = {
        "schema_version": 1,
        "extractor": version,
        "source_frame_rate": frame_rate,
        "clips": clips,
        "notes": [
            "Full original one-based timelines include source stop frames and unused authored frames.",
            "source_scale is applied once through pixels_per_unit=2/source_scale; runtime scale defaults to 1.",
            "actions execute on frame entry before painting; goto actions change the displayed frame immediately.",
            "Gold frame 30 sets _visible=false; it is retained because the source does not remove the clip.",
            "Only frames containing removeMovieClip are omitted; none of these object clips removes itself.",
            "Recursive dependency audit found shapes and morph shapes, with no animated child MovieClips.",
            "Laser blast 1296 contains four morph shapes (1291-1294) and final shape 1295, all rendered per frame.",
            "Laser blast scale is dynamic: 0 on firing entry, then 0.3+2*laserTimer/laserRate in Update_FiringLaser.",
            "Trap switch uses door_switch artwork with runtime scale 2/3 (source .05 versus .075).",
            "Parent playback, visibility, loops, stop and goto actions are executed by the rendering-only visual tracker.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(clips)} object clips, {sum(len(c['frames']) for c in clips.values())} frames")


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
