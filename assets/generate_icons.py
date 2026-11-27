"""Generate the ProxyHunter Windows icon without third-party libraries.

Produces a 64x64 32-bit BMP-based ICO with the network-shield mark.
"""

from __future__ import annotations

import struct
from pathlib import Path

SIZE = 64
NAVY = (11, 18, 32)
EMERALD = (16, 185, 129)
LIGHT = (110, 231, 183)


def pixel(x: int, y: int):
    # Shield outline: polygon-ish shape with a pointed bottom.
    cx = 32
    top, bottom = 12, 54
    half = 20
    if top <= y <= 38:
        edge = half - max(0, (y - 12) // 4)
    elif 38 < y <= 46:
        edge = 14 - (y - 38)
    else:
        edge = max(0, 6 - (y - 46) * 2)
    inside = abs(x - cx) <= edge
    border = abs(abs(x - cx) - edge) <= 2
    if border or (inside and top <= y <= bottom):
        # Connected nodes and edges inside the shield.
        nodes = [(32, 24), (22, 36), (42, 36), (32, 46)]
        for nx, ny in nodes:
            if (x - nx) ** 2 + (y - ny) ** 2 <= 9:
                return LIGHT
        edges = [((32, 24), (22, 36)), ((32, 24), (42, 36)),
                 ((22, 36), (32, 46)), ((42, 36), (32, 46))]
        for (x1, y1), (x2, y2) in edges:
            t = max(0.0, min(1.0, ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) /
                             ((x2 - x1) ** 2 + (y2 - y1) ** 2)))
            px, py = x1 + t * (x2 - x1), y1 + t * (y2 - y1)
            if (x - px) ** 2 + (y - py) ** 2 <= 2:
                return LIGHT
        return EMERALD if border else (14, 42, 36)
    return NAVY


def make_ico(path: Path) -> None:
    rows = []
    for y in range(SIZE):
        row = bytearray()
        for x in range(SIZE):
            r, g, b = pixel(x, y)
            row += bytes((b, g, r, 255))
        rows.append(bytes(row))
    pixels = b"".join(reversed(rows))  # BMP rows are bottom-up
    mask = b"\x00" * (SIZE * SIZE // 8)
    header = struct.pack("<IIIHHIIIIII", 40, SIZE, SIZE * 2, 1, 32, 0,
                         len(pixels), 0, 0, 0, 0)
    image = header + pixels + mask
    ico = struct.pack("<HHH", 0, 1, 1) + struct.pack(
        "<BBBBHHII", SIZE, SIZE, 0, 0, 1, 32, len(image), 22
    ) + image
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ico)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    make_ico(root / "assets" / "proxyhunter.ico")
    make_ico(root / "desktop" / "ProxyHunter.ico")
    print("generated assets/proxyhunter.ico and desktop/ProxyHunter.ico")
