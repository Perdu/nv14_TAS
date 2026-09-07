#!/usr/bin/env python3
# AI-generated
# See also https://github.com/ruffle-rs/ruffle/pull/24604

"""
Patch the original N v1.4 SWF so the ninja body renders in Ruffle builds that
do not yet handle minimum-width strokes under a collapsed transform axis.

This reproduces the diagnostic SWF change used to confirm the Ruffle bug:
for eight specific wrapper sprites, character 164 is placed with scaleY = 0.
The patch changes only scaleY, setting it equal to scaleX.

Usage:
    python3 patch_n_v14_ninja.py n_v14.swf
    python3 patch_n_v14_ninja.py n_v14.swf -o n_v14_patched.swf

The input may be CWS (zlib-compressed) or FWS (uncompressed). The output keeps
the same compression type.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import zlib
from pathlib import Path

TARGET_CHARACTER_ID = 164
TARGET_SPRITE_IDS = {165, 168, 171, 172, 890, 892, 894, 895}


class PatchError(RuntimeError):
    pass


class BitReader:
    def __init__(self, data: bytes | bytearray, bitpos: int):
        self.data = data
        self.bitpos = bitpos

    def read_bits(self, count: int, *, signed: bool = False) -> int:
        value = 0
        for _ in range(count):
            byte_index = self.bitpos // 8
            bit_index = 7 - (self.bitpos % 8)
            value = (value << 1) | ((self.data[byte_index] >> bit_index) & 1)
            self.bitpos += 1

        if signed and count and (value & (1 << (count - 1))):
            value -= 1 << count
        return value

    def align_byte(self) -> None:
        self.bitpos = (self.bitpos + 7) & ~7

    @property
    def bytepos(self) -> int:
        return self.bitpos // 8


def write_signed_bits(data: bytearray, bitpos: int, count: int, value: int) -> None:
    minimum = -(1 << (count - 1))
    maximum = (1 << (count - 1)) - 1
    if not minimum <= value <= maximum:
        raise PatchError(
            f"value {value} does not fit in signed {count}-bit MATRIX field"
        )

    encoded = value & ((1 << count) - 1)
    for i in range(count):
        bit = (encoded >> (count - 1 - i)) & 1
        absolute = bitpos + i
        byte_index = absolute // 8
        bit_index = 7 - (absolute % 8)
        mask = 1 << bit_index
        if bit:
            data[byte_index] |= mask
        else:
            data[byte_index] &= ~mask


def parse_rect_end(data: bytes | bytearray, offset: int) -> int:
    reader = BitReader(data, offset * 8)
    nbits = reader.read_bits(5)
    for _ in range(4):
        reader.read_bits(nbits, signed=True)
    reader.align_byte()
    return reader.bytepos


def read_tag_header(data: bytes | bytearray, offset: int) -> tuple[int, int, int]:
    if offset + 2 > len(data):
        raise PatchError("truncated SWF tag header")

    record = struct.unpack_from("<H", data, offset)[0]
    offset += 2
    tag_code = record >> 6
    length = record & 0x3F

    if length == 0x3F:
        if offset + 4 > len(data):
            raise PatchError("truncated long SWF tag header")
        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4

    return tag_code, length, offset


def parse_matrix(data: bytes | bytearray, offset: int) -> dict[str, int | float | bool | None]:
    reader = BitReader(data, offset * 8)

    has_scale = bool(reader.read_bits(1))
    scale_bits = None
    scale_x_raw = None
    scale_y_raw = None
    scale_y_bitpos = None

    if has_scale:
        scale_bits = reader.read_bits(5)
        scale_x_raw = reader.read_bits(scale_bits, signed=True)
        scale_y_bitpos = reader.bitpos
        scale_y_raw = reader.read_bits(scale_bits, signed=True)

    has_rotate = bool(reader.read_bits(1))
    if has_rotate:
        rotate_bits = reader.read_bits(5)
        reader.read_bits(rotate_bits, signed=True)
        reader.read_bits(rotate_bits, signed=True)

    translate_bits = reader.read_bits(5)
    if translate_bits:
        reader.read_bits(translate_bits, signed=True)
        reader.read_bits(translate_bits, signed=True)

    reader.align_byte()

    return {
        "has_scale": has_scale,
        "scale_bits": scale_bits,
        "scale_x_raw": scale_x_raw,
        "scale_y_raw": scale_y_raw,
        "scale_y_bitpos": scale_y_bitpos,
        "end": reader.bytepos,
    }


def patch_place_object2(
    data: bytearray,
    payload_start: int,
    payload_end: int,
    sprite_id: int,
) -> bool:
    flags = data[payload_start]
    pos = payload_start + 1

    if pos + 2 > payload_end:
        raise PatchError(f"truncated PlaceObject2 in sprite {sprite_id}")

    # Depth.
    pos += 2

    has_character = bool(flags & 0x02)
    has_matrix = bool(flags & 0x04)

    if not has_character:
        return False
    if pos + 2 > payload_end:
        raise PatchError(f"truncated character id in sprite {sprite_id}")

    character_id = struct.unpack_from("<H", data, pos)[0]
    pos += 2

    if character_id != TARGET_CHARACTER_ID or not has_matrix:
        return False

    matrix = parse_matrix(data, pos)

    if sprite_id not in TARGET_SPRITE_IDS:
        return False

    if not matrix["has_scale"]:
        raise PatchError(
            f"sprite {sprite_id}: target character {TARGET_CHARACTER_ID} "
            "does not have an explicit scale"
        )

    scale_x_raw = int(matrix["scale_x_raw"])
    scale_y_raw = int(matrix["scale_y_raw"])
    scale_bits = int(matrix["scale_bits"])
    scale_y_bitpos = int(matrix["scale_y_bitpos"])

    if scale_y_raw != 0:
        # Idempotence: an already-patched file should have scaleY == scaleX.
        if scale_y_raw == scale_x_raw:
            return False
        raise PatchError(
            f"sprite {sprite_id}: expected scaleY=0, found "
            f"{scale_y_raw / 65536.0:g}"
        )

    if scale_x_raw == 0:
        raise PatchError(f"sprite {sprite_id}: scaleX is also zero")

    write_signed_bits(data, scale_y_bitpos, scale_bits, scale_x_raw)
    return True


def scan_tags(
    data: bytearray,
    start: int,
    end: int,
    *,
    current_sprite: int | None,
    patched_sprites: set[int],
    seen_targets: set[int],
) -> None:
    offset = start

    while offset < end:
        tag_code, length, payload_start = read_tag_header(data, offset)
        payload_end = payload_start + length

        if payload_end > end or payload_end > len(data):
            raise PatchError(
                f"tag {tag_code} at offset {offset} extends beyond its container"
            )

        if tag_code == 0:  # End
            return

        if tag_code == 39:  # DefineSprite
            if length < 4:
                raise PatchError(f"truncated DefineSprite at offset {offset}")

            sprite_id = struct.unpack_from("<H", data, payload_start)[0]
            scan_tags(
                data,
                payload_start + 4,  # sprite id + frame count
                payload_end,
                current_sprite=sprite_id,
                patched_sprites=patched_sprites,
                seen_targets=seen_targets,
            )

        elif tag_code == 26 and current_sprite is not None:  # PlaceObject2
            # Track whether the target sprite contains the expected target
            # placement even when the SWF is already patched.
            if current_sprite in TARGET_SPRITE_IDS:
                flags = data[payload_start]
                pos = payload_start + 1 + 2  # flags + depth
                if flags & 0x02 and pos + 2 <= payload_end:
                    character_id = struct.unpack_from("<H", data, pos)[0]
                    if character_id == TARGET_CHARACTER_ID:
                        seen_targets.add(current_sprite)

            if patch_place_object2(
                data, payload_start, payload_end, current_sprite
            ):
                patched_sprites.add(current_sprite)

        offset = payload_end


def decode_swf(raw: bytes) -> tuple[bytearray, bytes, int, int]:
    if len(raw) < 8:
        raise PatchError("file is too short to be a SWF")

    signature = raw[:3]
    version = raw[3]
    declared_length = struct.unpack_from("<I", raw, 4)[0]

    if signature == b"FWS":
        uncompressed = bytearray(raw)
    elif signature == b"CWS":
        try:
            body = zlib.decompress(raw[8:])
        except zlib.error as exc:
            raise PatchError(f"invalid CWS zlib stream: {exc}") from exc
        uncompressed = bytearray(
            b"FWS" + bytes([version]) + struct.pack("<I", declared_length) + body
        )
    else:
        raise PatchError(
            f"unsupported SWF signature {signature!r}; only FWS and CWS are supported"
        )

    if len(uncompressed) != declared_length:
        raise PatchError(
            f"SWF declares {declared_length} bytes uncompressed, "
            f"decoded {len(uncompressed)}"
        )

    return uncompressed, signature, version, declared_length


def encode_swf(
    uncompressed: bytearray,
    signature: bytes,
    version: int,
    declared_length: int,
) -> bytes:
    if signature == b"FWS":
        return bytes(uncompressed)

    # Restore the original CWS signature and compress everything after the
    # standard 8-byte SWF header.
    return (
        b"CWS"
        + bytes([version])
        + struct.pack("<I", declared_length)
        + zlib.compress(bytes(uncompressed[8:]), level=9)
    )


def default_output_path(input_path: Path) -> Path:
    return input_path.with_name(input_path.stem + "_patched" + input_path.suffix)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Patch N v1.4's eight collapsed ninja-stroke placement matrices "
            "for diagnostic use."
        )
    )
    parser.add_argument("input", type=Path, help="original n_v14.swf")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output SWF (default: <input>_patched.swf)",
    )
    args = parser.parse_args()

    input_path: Path = args.input
    output_path: Path = args.output or default_output_path(input_path)

    raw = input_path.read_bytes()
    original_sha1 = hashlib.sha1(raw).hexdigest()

    uncompressed, signature, version, declared_length = decode_swf(raw)

    tags_start = parse_rect_end(uncompressed, 8) + 4  # frame rate + frame count

    patched_sprites: set[int] = set()
    seen_targets: set[int] = set()

    scan_tags(
        uncompressed,
        tags_start,
        len(uncompressed),
        current_sprite=None,
        patched_sprites=patched_sprites,
        seen_targets=seen_targets,
    )

    missing = TARGET_SPRITE_IDS - seen_targets
    if missing:
        raise PatchError(
            "input does not match the expected N v1.4 structure; "
            f"missing target placements in sprites {sorted(missing)}"
        )

    if patched_sprites and patched_sprites != TARGET_SPRITE_IDS:
        missing_patches = TARGET_SPRITE_IDS - patched_sprites
        raise PatchError(
            "only some target matrices were patched; refusing partial output. "
            f"Unpatched sprites: {sorted(missing_patches)}"
        )

    if not patched_sprites:
        print(
            "No changes needed: all eight target placements already have "
            "scaleY == scaleX.",
            file=sys.stderr,
        )

    output = encode_swf(uncompressed, signature, version, declared_length)
    output_path.write_bytes(output)

    print(f"Input:  {input_path}")
    print(f"SHA-1:  {original_sha1}")
    print(f"Output: {output_path}")
    print(f"Patched sprites: {sorted(patched_sprites)}")
    print(f"Output SHA-1: {hashlib.sha1(output).hexdigest()}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, PatchError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
