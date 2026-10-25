#!/usr/bin/env python3
"""Create clearly synthetic practice images using only the Python standard library."""
import argparse
import struct
import zlib
from pathlib import Path


def make_png(width=1000, height=500):
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            tooth = 70 < x < width - 70 and x % 65 < 38 and (130 < y < 220 or 280 < y < 370)
            row.extend((202, 209, 205) if tooth else (35, 40, 44))
        rows.append(b"\x00" + bytes(row))
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/images/demo"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "SYNTHETIC_PRACTICE_NOT_PATIENT.png"
    if target.exists():
        raise SystemExit("Refusing to overwrite an existing file: " + str(target))
    target.write_bytes(make_png())
    print("Synthetic practice image only: " + str(target))


if __name__ == "__main__":
    main()
