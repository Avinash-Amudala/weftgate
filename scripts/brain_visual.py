#!/usr/bin/env python3
"""Original geometric brain artwork, shared by the README and motion film."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

MINT, BLUE, AMBER = "#adffd0", "#879fff", "#f8cd85"


def _font(size, bold=False):
    for path in (
        "/System/Library/Fonts/Avenir Next.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(
                path, size, index=(0 if bold else 5) if path.endswith(".ttc") else 0
            )
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _curve(points):
    out = [points[0]]
    start = points[0]
    for p1, p2, end in points[1:]:
        for j in range(1, 25):
            t = j / 24
            out.append(
                tuple(
                    (1 - t) ** 3 * start[k]
                    + 3 * (1 - t) ** 2 * t * p1[k]
                    + 3 * (1 - t) * t * t * p2[k]
                    + t**3 * end[k]
                    for k in range(2)
                )
            )
        start = end
    return out


HEMISPHERE = _curve(
    [
        (-20, -206),
        ((-62, -266), (-139, -249), (-149, -205)),
        ((-206, -219), (-248, -165), (-228, -125)),
        ((-290, -95), (-294, -25), (-257, 3)),
        ((-293, 54), (-275, 115), (-223, 127)),
        ((-230, 183), (-178, 220), (-131, 198)),
        ((-101, 246), (-31, 228), (-20, 187)),
        ((-30, 98), (-9, -111), (-20, -206)),
    ]
)
NETWORK = [
    (-58, -181),
    (-113, -195),
    (-182, -141),
    (-78, -113),
    (-217, -52),
    (-145, -65),
    (-57, -18),
    (-224, 61),
    (-153, 32),
    (-94, 74),
    (-178, 141),
    (-86, 171),
    (-48, 125),
]
LINKS = [
    (0, 1),
    (0, 3),
    (1, 2),
    (2, 5),
    (3, 5),
    (3, 6),
    (4, 5),
    (4, 7),
    (5, 8),
    (6, 8),
    (6, 9),
    (7, 8),
    (7, 10),
    (8, 9),
    (9, 10),
    (9, 11),
    (9, 12),
    (10, 11),
    (11, 12),
]


def draw_brain(im, center, scale=1, t=0):
    """Draw two sculpted hemispheres with flowing, source-colored neural paths."""
    cx, cy = center
    layer = Image.new("RGBA", im.size)
    d = ImageDraw.Draw(layer)

    def point(p, mirror=1):
        return (cx + p[0] * scale * mirror, cy + p[1] * scale)

    for mirror, color in ((1, MINT), (-1, BLUE)):
        outline = [point(p, mirror) for p in HEMISPHERE]
        d.polygon(outline, fill=(17, 34, 48, 248))
        d.line(outline, fill=color, width=max(2, round(2 * scale)), joint="curve")
        for a, b in LINKS:
            start, end = point(NETWORK[a], mirror), point(NETWORK[b], mirror)
            d.line([start, end], fill=(74, 108, 128, 155), width=max(1, round(scale)))
            phase = (t * 0.16 + a * 0.113 + b * 0.073) % 1
            x, y = [start[k] + (end[k] - start[k]) * phase for k in (0, 1)]
            r = 2.7 * scale
            d.ellipse((x - r, y - r, x + r, y + r), fill=color)
        for i, p in enumerate(NETWORK):
            x, y = point(p, mirror)
            radius = (4.5 + math.sin(t * 1.5 + i) * 1.2) * scale
            d.ellipse(
                (x - radius * 2, y - radius * 2, x + radius * 2, y + radius * 2),
                outline=color,
                width=1,
            )
            d.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    for j in range(3):
        y = cy + (j - 1) * 100 * scale
        d.arc(
            (cx - 62 * scale, y - 28 * scale, cx + 62 * scale, y + 28 * scale),
            5,
            175,
            fill=AMBER,
            width=max(2, round(2 * scale)),
        )
    d.line((cx, cy + 228 * scale, cx, cy + 292 * scale), fill=AMBER, width=max(3, round(4 * scale)))
    d.ellipse((cx - 11 * scale, cy + 285 * scale, cx + 11 * scale, cy + 307 * scale), fill=AMBER)
    glow = layer.filter(ImageFilter.GaussianBlur(14 * scale))
    im.paste(glow, (0, 0), glow)
    im.paste(layer, (0, 0), layer)


def hero():
    im = Image.new("RGB", (1920, 1080), "#09131f")
    d = ImageDraw.Draw(im)
    for x in range(30, 1920, 44):
        for y in range(30, 1080, 44):
            d.ellipse((x, y, x + 2, y + 2), fill="#243443")
    d.rounded_rectangle((72, 64, 270, 113), 24, fill="#15342f", outline="#386554")
    d.text((171, 88), "WEFTGATE", font=_font(22, True), fill=MINT, anchor="mm")
    d.text((76, 191), "A second brain.", font=_font(88, True), fill="#f0f4ec")
    d.text((76, 303), "Grounded in code.", font=_font(76, True), fill=MINT)
    d.text((81, 457), "Give your agent the right context,", font=_font(32), fill="#b2bfca")
    d.text((81, 508), "source-aware memory and verification gates.", font=_font(32), fill="#b2bfca")
    d.text(
        (82, 627),
        "CODEX  /  CLAUDE CODE  /  CURSOR  /  ANTIGRAVITY",
        font=_font(21),
        fill="#a8b8c8",
    )
    draw_brain(im, (1455, 389), 1.12, 2)
    d = ImageDraw.Draw(im)
    d.text((1455, 748), "ONE LOCAL PACKAGE", font=_font(18, True), fill=AMBER, anchor="mm")
    for i, (name, subtitle, color) in enumerate(
        [
            ("Understand", "Source-backed context", MINT),
            ("Remember", "Decisions that notice change", BLUE),
            ("Verify", "Contracts and test evidence", AMBER),
        ]
    ):
        x = 76 + i * 594
        d.rounded_rectangle((x, 805, x + 574, 997), 24, fill="#122231", outline="#334655", width=2)
        d.text((x + 30, 832), f"0{i + 1}", font=_font(20), fill=color)
        d.text((x + 30, 873), name, font=_font(35, True), fill="#f0f4ec")
        d.text((x + 30, 931), subtitle, font=_font(24), fill="#b2bfca")
    return im


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "docs/assets/weftgate-brain.png"
    hero().save(path, optimize=True)
    print(path)
