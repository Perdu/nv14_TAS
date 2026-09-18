#!/usr/bin/env python3
"""Retain original SWF paths for scale-independent video outlines.

Development only: Java and JPEXS FFDec 26.3.0. Run after the three PNG asset
extractors with ``python -m tools.extract_vector_assets --swf ...
--ffdec-jar ... --output nv14_assets``. Runtime needs only Pillow.

The pinned artwork uses solid even-odd fills, M/L/Q paths and round hairlines.
Unsupported SVG features fail extraction rather than changing the artwork.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET

from tools.extract_video_assets import (
    FFDEC, IDENTITY, NUMBER, SOURCE_SHA256, SVG, XLINK, export, matrix,
    multiply, sha256,
)


def commands(data, transform):
    """Resolve implicit SVG commands and flatten coordinates, including singular transforms."""
    tokens = re.findall(r"[A-Za-z]|" + NUMBER, data)
    result, index, command = [], 0, None
    a, b, c, d, e, f = transform
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
        if command in ("Z", "z"):
            result.append(["Z"])
            command = None
            continue
        if command not in ("M", "L", "Q"):
            raise ValueError(f"Unsupported SVG path command: {command}")
        count = 4 if command == "Q" else 2
        values = [float(v) for v in tokens[index:index + count]]
        if len(values) != count:
            raise ValueError("Incomplete SVG path command")
        converted = [command]
        for x, y in zip(values[::2], values[1::2]):
            converted.extend((round(a*x + c*y + e, 8), round(b*x + d*y + f, 8)))
        result.append(converted)
        index += count
        if command == "M":
            command = "L"
    return result


def color(value, opacity="1"):
    if value == "none":
        return None
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError(f"Unsupported SVG paint: {value}")
    alpha = float(opacity)
    if not 0 <= alpha <= 1:
        raise ValueError("Invalid SVG opacity")
    return [int(value[i:i+2], 16) for i in (1, 3, 5)] + [round(alpha * 255)]


def extract_svg(path, scale):
    root = ET.parse(path).getroot()
    references = {e.get("id"): e for e in root.iter() if e.get("id")}
    paths = []

    def walk(element, transform, depth=0):
        if depth > 50:
            raise ValueError("SVG reference recursion limit")
        if any(k in element.attrib for k in ("filter", "clip-path", "mask", "style", "opacity")):
            raise ValueError("Unsupported SVG compositing")
        transform = multiply(transform, matrix(element.get("transform", "")))
        kind = element.tag.rsplit("}", 1)[-1]
        if kind == "use":
            reference = element.get("{" + XLINK + "}href", "")
            target = references.get(reference[1:])
            if target is not None:
                walk(target, transform, depth + 1)
            elif not (float(element.get("width", "-1")) ==
                      float(element.get("height", "-1")) == 0):
                # FFDec omits empty ninja registration-marker definitions.
                raise ValueError(f"Missing SVG symbol: {reference}")
        elif kind == "path":
            if element.get("fill-rule", "evenodd") != "evenodd":
                raise ValueError("Unsupported SVG winding rule")
            item = {"commands": commands(element.attrib["d"], transform),
                    "fill": color(element.attrib["fill"], element.get("fill-opacity", "1")),
                    "stroke": color(element.attrib["stroke"], element.get("stroke-opacity", "1"))}
            if item["stroke"] is not None:
                if (element.get("stroke-linecap") != "round" or
                        element.get("stroke-linejoin") != "round"):
                    raise ValueError("Unsupported SVG stroke cap/join")
                # FFDec's display-width compensation can be Infinity for a
                # zero-height limb. Keep the original twip width instead.
                source_width = float(element.get("{" + FFDEC + "}original-stroke-width",
                                                  element.get("stroke-width", "1")))
                determinant = abs(transform[0]*transform[3] - transform[1]*transform[2])
                item["stroke_width"] = round(source_width * math.sqrt(determinant), 8)
            paths.append(item)
        elif kind == "g":
            for child in element:
                walk(child, transform, depth + 1)
        else:
            raise ValueError(f"Unsupported SVG element: {kind}")

    group = root.find("{" + SVG + "}g")
    if group is not None:
        offset = matrix(group.get("transform", ""))
        # SVG viewport offsets are exporter bounds, not MovieClip positions.
        base = multiply((scale, 0, 0, scale, 0, 0),
                        (1, 0, 0, 1, -offset[4], -offset[5]))
        walk(group, base)
    points = [(cmd[i], cmd[i+1]) for item in paths for cmd in item["commands"]
              for i in range(1, len(cmd), 2)]
    bounds = ([min(x for x, _ in points), min(y for _, y in points),
               max(x for x, _ in points), max(y for _, y in points)] if points else [0]*4)
    return {"bounds": bounds, "paths": paths}


def build(swf, jar, output, java="java"):
    swf, jar, output = Path(swf).resolve(), Path(jar).resolve(), Path(output).resolve()
    if sha256(swf) != SOURCE_SHA256:
        raise ValueError("Source SWF SHA-256 mismatch")
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if manifest.get("source_swf_sha256") != SOURCE_SHA256:
        raise ValueError("Existing asset pack uses a different source SWF")
    requests = []
    for name, info in manifest["objects"].items():
        requests.append(("objects/" + name, info, info["symbol_id"], info["symbol"],
                         info["source_frame"], info["source_scale"]))
    for name, clip in [("ninja", manifest["ninja"]), *(
            ("object_animations/" + name, clip)
            for name, clip in manifest["object_animations"]["clips"].items())]:
        for number, info in clip["frames"].items():
            requests.append((name + "/" + number, info, clip["symbol_id"], clip["symbol"],
                             int(number), clip["source_scale"]))
    frames = {}
    for _, _, sid, _, frame, _ in requests:
        frames.setdefault(sid, set()).add(frame)
    selection = ",".join(str(sid) + ":" + ",".join(map(str, sorted(values)))
                         for sid, values in sorted(frames.items()))
    pack = {"schema_version": 1, "source_swf_sha256": SOURCE_SHA256, "sprites": {}}
    with tempfile.TemporaryDirectory(prefix="nv14-vectors-") as temporary:
        temporary = Path(temporary)
        pack["extractor"] = export(java, jar, swf, temporary,
                                   ",".join(map(str, sorted(frames))), selection, "svg")
        for key, info, sid, symbol, frame, scale in requests:
            source = temporary / f"DefineSprite_{sid}_{symbol}" / f"{frame}.svg"
            pack["sprites"][key] = extract_svg(source, scale)
            info["vector"] = key
    destination = output / "vectors.json"
    destination.write_text(json.dumps(pack, separators=(",", ":"), allow_nan=False) + "\n", "utf-8")
    manifest["vectors"] = {"file": destination.name, "sha256": sha256(destination),
                           "schema_version": 1, "sprites": len(requests)}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    print(f"Wrote {len(requests)} source vector frames; original PNGs retained as fallback")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--swf", type=Path, required=True)
    parser.add_argument("--ffdec-jar", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("nv14_assets"))
    parser.add_argument("--java", default="java")
    args = parser.parse_args()
    build(args.swf, args.ffdec_jar, args.output, args.java)


if __name__ == "__main__":
    main()
