"""Generate valid side-labelled demonstration camera inputs without external assets.

Depends only on PNG framing, zlib, and struct. Synthetic images are installation
fixtures, not evidence of real camera connectivity or real vehicle damage.
"""
import struct
import zlib


def sample_png(color, width=320, height=240):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            on_body = 45 < x < 275 and 85 < y < 165
            on_cabin = 95 < x < 225 and 55 < y < 100
            on_wheel = ((x - 95)**2 + (y - 165)**2 < 22**2 or (x - 225)**2 + (y - 165)**2 < 22**2)
            row.extend((18, 24, 34) if on_wheel else color if on_body or on_cabin else (210, 218, 228))
        rows.append(b"\0" + row)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")


def prepare_demo_photos(root):
    obsolete = root / "demo.png"
    obsolete.unlink(missing_ok=True)
    for side, color in {"front": (55, 110, 165), "rear": (60, 125, 145),
                        "left": (65, 105, 155), "right": (70, 120, 170)}.items():
        path = root / (side + "_demo.png")
        if not path.exists():
            path.write_bytes(sample_png(color))
