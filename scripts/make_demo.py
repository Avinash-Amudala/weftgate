#!/usr/bin/env python3
"""Render a motion-designed product film backed by real CLI results.

Install the optional demo extra, then run python scripts/make_demo.py.
All geometry, animation, and sound are generated locally; no stock assets or network.
"""

from __future__ import annotations

import argparse
import array
import json
import math
import os
import subprocess
import sys
import tempfile
import wave
from functools import lru_cache
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS, DURATION = 1920, 1080, 30, 58
INK = "#101d29"
TEXT = "#f0f4ec"
MUTED = "#94a6b2"
MINT = "#adffd0"
BLUE = "#879fff"
RED = "#ff918a"
AMBER = "#f8cd85"
PAPER = "#edf1e7"
STARTS = (0, 5, 11, 24, 33, 41, 48)


@lru_cache(maxsize=200)
def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    if mono:
        candidates = [
            ("/System/Library/Fonts/Menlo.ttc", int(bold)),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 0),
        ]
    else:
        candidates = [
            ("/System/Library/Fonts/Avenir Next.ttc", 0 if bold else 5),
            (
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
                if bold
                else "/System/Library/Fonts/Supplemental/Arial.ttf",
                0,
            ),
            (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                if bold
                else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                0,
            ),
        ]
    for path, index in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size, index=index)
    raise SystemExit("Install DejaVu Sans and DejaVu Sans Mono to render the demo.")


def rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))


def mix(a: str, b: str, p: float) -> str:
    return "#" + "".join(
        f"{round(x + (y - x) * p):02x}" for x, y in zip(rgb(a), rgb(b), strict=True)
    )


def clamp(v: float) -> float:
    return min(1, max(0, v))


def ease(v: float) -> float:
    v = clamp(v)
    return 1 - (1 - v) ** 3


def text(
    d: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    value: str,
    size: int = 30,
    color: str = TEXT,
    bold: bool = False,
    mono: bool = False,
    anchor: str = "lt",
    max_width: int | None = None,
) -> None:
    while max_width and d.textlength(value, font=font(size, bold, mono)) > max_width:
        size -= 1
    d.text(xy, value, font=font(size, bold, mono), fill=color, anchor=anchor)


def panel(
    d: ImageDraw.ImageDraw,
    bounds: tuple[float, float, float, float],
    color: str = "#142631",
    outline: str = "#314752",
    radius: int = 22,
) -> None:
    d.rounded_rectangle(bounds, radius=radius, fill=color, outline=outline, width=2)


def check(d: ImageDraw.ImageDraw, x: float, y: float, color: str, size: int = 18) -> None:
    d.line(
        [(x - size, y), (x - size / 4, y + size * 0.7), (x + size, y - size)],
        fill=color,
        width=5,
        joint="curve",
    )


def cross(d: ImageDraw.ImageDraw, x: float, y: float, color: str, size: int = 11) -> None:
    d.line((x - size, y - size, x + size, y + size), fill=color, width=4)
    d.line((x - size, y + size, x + size, y - size), fill=color, width=4)


def badge(
    d: ImageDraw.ImageDraw, x: float, y: float, value: str, color: str, light: bool = False
) -> None:
    width = d.textlength(value, font=font(23, True, True)) + 36
    panel(
        d,
        (x, y, x + width, y + 48),
        mix(PAPER if light else INK, color, 0.15),
        mix(PAPER if light else INK, color, 0.5),
        10,
    )
    text(d, (x + 18, y + 11), value, 23, color, True, True)


@lru_cache(maxsize=2)
def background(light: bool = False) -> Image.Image:
    if light:
        im = Image.new("RGB", (W, H), PAPER)
    else:
        tiny = Image.new("RGB", (192, 108))
        px = tiny.load()
        for y in range(108):
            for x in range(192):
                glow = math.exp(-((x - 130) ** 2 / 3700 + (y - 50) ** 2 / 2500))
                px[x, y] = (int(7 + glow * 9), int(17 + glow * 18), int(26 + glow * 21))
        im = tiny.resize((W, H), Image.Resampling.BICUBIC)
    d = ImageDraw.Draw(im)
    grid = "#dae0d7" if light else "#1a303b"
    for x in range(80, W, 48):
        for y in range(150, H - 75, 48):
            d.ellipse((x, y, x + 2, y + 2), fill=grid)
    return im


def mark(d: ImageDraw.ImageDraw, x: float, y: float, scale: float = 1, color: str = MINT) -> None:
    for i in range(3):
        points = [
            (x, y + i * 15 * scale),
            (x + 18 * scale, y + i * 15 * scale),
            (x + 46 * scale, y + (2 - i) * 15 * scale),
            (x + 66 * scale, y + (2 - i) * 15 * scale),
        ]
        d.line(points, fill=color, width=max(2, round(4 * scale)), joint="curve")


def chrome(im: Image.Image, t: float, chapter: str, light: bool = False) -> None:
    d = ImageDraw.Draw(im)
    c = INK if light else TEXT
    muted = "#586c76" if light else MUTED
    mark(d, 82, 57, 0.8, INK if light else MINT)
    text(d, (155, 50), "weftgate", 31, c, True)
    text(d, (1838, 62), chapter, 19, muted, mono=True, anchor="rt")
    text(d, (82, 1014), "ANIMATED WALKTHROUGH / REAL CLI RESULTS", 18, muted, mono=True)
    text(d, (1838, 1014), "LOCAL BY DEFAULT", 18, muted, mono=True, anchor="rt")
    d.rectangle((0, 1075, W * t / DURATION, 1080), fill=INK if light else MINT)


def reveal(
    im: Image.Image,
    xy: tuple[float, float],
    value: str,
    size: int,
    elapsed: float,
    delay: float = 0,
    color: str = TEXT,
    bold: bool = True,
    mono: bool = False,
    max_width: int | None = None,
) -> None:
    p = ease((elapsed - delay) / 0.7)
    if p <= 0:
        return
    layer = Image.new("RGBA", (W, H))
    text(
        ImageDraw.Draw(layer),
        (xy[0], xy[1] + 28 * (1 - p)),
        value,
        size,
        color,
        bold,
        mono,
        max_width=max_width,
    )
    if p < 1:
        layer.putalpha(layer.getchannel("A").point(lambda a: int(a * p)))
    im.paste(layer, (0, 0), layer)


def wire(
    d: ImageDraw.ImageDraw,
    a: tuple[float, float],
    b: tuple[float, float],
    t: float,
    color: str,
    phase: float = 0,
    broken: bool = False,
) -> None:
    x1, y1 = a
    x2, y2 = b
    pts = []
    for i in range(61):
        p = i / 60
        s = p * p * (3 - 2 * p)
        pts.append((x1 + (x2 - x1) * p, y1 + (y2 - y1) * s))
    if broken:
        d.line(pts[:26], fill=mix(INK, color, 0.5), width=3)
        d.line(pts[35:], fill=mix(INK, color, 0.5), width=3)
        cross(d, (x1 + x2) / 2, (y1 + y2) / 2, color, 9)
    else:
        d.line(pts, fill=mix(INK, color, 0.4), width=3)
    p = (t * 0.28 + phase) % 1
    if broken:
        p *= 0.41
    s = p * p * (3 - 2 * p)
    x, y = x1 + (x2 - x1) * p, y1 + (y2 - y1) * s
    d.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color)


def sculpture(
    im: Image.Image,
    t: float,
    cx: float = 1370,
    cy: float = 536,
    scale: float = 1,
    light: bool = False,
) -> None:
    """A perspective gate with three moving woven evidence filaments."""
    layer = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(layer)
    rotation = -0.28 + 0.12 * math.sin(t * 0.4)

    def project(x: float, y: float, z: float) -> tuple[float, float]:
        xx = x * math.cos(rotation) + z * math.sin(rotation)
        zz = -x * math.sin(rotation) + z * math.cos(rotation)
        perspective = 900 / (900 + zz)
        return cx + xx * perspective * scale, cy + (y - zz * 0.15) * perspective * scale

    gate_color = "#6f858b" if light else "#668d9d"
    for z in (-80, 80):
        corners = [
            project(x, y, z)
            for x, y in [(-125, -315), (125, -315), (125, 315), (-125, 315), (-125, -315)]
        ]
        d.line(corners, fill=gate_color, width=2)
    for x in (-125, 125):
        for y in (-315, 315):
            d.line([project(x, y, -80), project(x, y, 80)], fill=gate_color, width=2)
    for i in range(21):
        x = -120 + i * 12
        d.line(
            [project(x, -310, 0), project(x, 310, 0)],
            fill="#bbd3c7" if light else "#264c57",
            width=1,
        )
    for j, color in enumerate(("#138462", "#6678d7", "#ce855c") if light else (MINT, BLUE, AMBER)):
        points = []
        for k in range(141):
            x = -440 + k * 880 / 140
            y = (j - 1) * 115 * math.tanh(-x / 95) + math.sin(x * 0.008 + t * 1.4 + j) * 24
            z = math.sin(x * 0.011 + j * 2.09 + t * 0.6) * 90
            points.append(project(x, y, z))
        d.line(points, fill=color, width=max(2, round(4 * scale)), joint="curve")
        k = int((t * 0.25 + j / 3) % 1 * 130)
        d.line(
            points[k : k + 10],
            fill=TEXT if not light else "#17372c",
            width=max(4, round(7 * scale)),
            joint="curve",
        )
        for x, y in [points[0], points[-1]]:
            d.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color)
    # A restrained glow preserves the crisp filament edges.
    if not light:
        glow = layer.filter(ImageFilter.GaussianBlur(14))
        glow.putalpha(glow.getchannel("A").point(lambda a: int(a * 0.32)))
        im.paste(glow, (0, 0), glow)
    im.paste(layer, (0, 0), layer)


def evidence(python: str) -> dict:
    # Generate the fixture and execute the public CLI in an isolated temporary repo.
    with tempfile.TemporaryDirectory(prefix="weftgate-demo-") as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        build = (
            "from weftgate.eval.fixture import write_fixture; import sys; "
            "write_fixture(sys.argv[1], broken=True)"
        )
        subprocess.run([python, "-c", build, str(root)], check=True)
        env = dict(
            os.environ,
            WEFTGATE_CACHE=str(Path(tmp) / "cache"),
            WEFTGATE_LEDGER="0",
            XDG_CONFIG_HOME=str(Path(tmp) / "config"),
        )

        def run() -> dict:
            cmd = [
                python,
                "-m",
                "weftgate",
                "--repo",
                str(root),
                "check",
                "app/broken.py",
                "--format=json",
            ]
            proc = subprocess.run(
                cmd, cwd=root, env=env, text=True, capture_output=True, check=False
            )
            return {"exit_code": proc.returncode, "result": json.loads(proc.stdout)}

        broken = run()
        path = root / "app/broken.py"
        path.write_text(
            path.read_text()
            .replace("requestz", "requests")
            .replace("DATABSE_URL", "DATABASE_URL")
            .replace("helth", "health")
        )
        fixed = run()
        path.write_text('import os\nkey = "DATABASE_URL"\nvalue = os.environ[key]\n')
        dynamic = run()
        assert broken["exit_code"] == 1 and broken["result"]["stats"]["reject"] == 3
        assert fixed["exit_code"] == 0 and fixed["result"]["verdict"] == "accept"
        assert dynamic["exit_code"] == 0 and dynamic["result"]["verdict"] == "review"
        for item in (broken, fixed, dynamic):
            item["result"]["stats"].pop("commit", None)
        return {
            "source": "Built-in fixture; illustrative demonstration, not a field benchmark.",
            "broken": broken,
            "fixed": fixed,
            "dynamic": dynamic,
        }


def rows(data: dict) -> list[tuple[str, str, str, str]]:
    rejected = {
        f["oracle"]: f for f in data["broken"]["result"]["findings"] if f["level"] == "reject"
    }
    return [
        ("IMPORT", "requestz", rejected["imports_lockfile"]["suggestions"][0], "requirements.txt"),
        ("ENV READ", "DATABSE_URL", rejected["env_vars"]["suggestions"][0], ".env.example"),
        ("HANDLER", "helth", rejected["routes_fastapi"]["suggestions"][0], "app/handlers.py"),
    ]


def scene(index: int, u: float, t: float, data: dict) -> Image.Image:
    light = index in (3, 5)
    im = background(light).copy()
    d = ImageDraw.Draw(im)
    if index == 0:
        reveal(im, (90, 240), "The code", 104, u)
        reveal(im, (90, 360), "looks right.", 104, u, 0.25)
        reveal(im, (94, 516), "But does it connect?", 42, u, 1.2, MINT, False)
        nodes = [("requestz", 1275, 277), ("DATABSE_URL", 1400, 501), ("helth", 1265, 730)]
        for i, (value, x, y) in enumerate(nodes):
            y += math.sin(t * 0.8 + i) * 9
            wire(d, (1060, 520), (x, y + 50), t, RED if u > 2 else BLUE, i * 0.17, broken=u > 2)
            panel(d, (x, y, x + 360, y + 106))
            text(d, (x + 25, y + 20), ["IMPORT", "ENV", "ROUTE"][i], 17, MUTED, mono=True)
            text(d, (x + 25, y + 49), value, 30, RED if u > 2 else TEXT, mono=True)
        d.ellipse((1020, 480, 1100, 560), fill=MINT)
        text(d, (1060, 520), "+", 44, INK, anchor="mm")
        reveal(
            im, (94, 812), "Three tiny typos. Three broken references.", 30, u, 2.4, MUTED, False
        )
    elif index == 1:
        sculpture(im, t, 1390, 545, 0.92)
        reveal(im, (90, 251), "Verify the", 97, u)
        reveal(im, (90, 369), "connections.", 97, u, 0.18, MINT)
        reveal(
            im,
            (95, 533),
            "Ground code in your repo’s own contracts.",
            34,
            u,
            0.6,
            MUTED,
            False,
            max_width=810,
        )
        reveal(im, (96, 713), "ENV  /  IMPORTS  /  FASTAPI ROUTES", 25, u, 1.2, TEXT, False, True)
        badge(d, 100, 809, "NO API KEY", MINT)
        badge(d, 350, 809, "RUNS LOCALLY", BLUE)
    elif index == 2:
        reveal(im, (86, 169), "Follow the reference.", 78, u)
        reveal(im, (90, 271), "$ weftgate check app/broken.py", 30, u, 0.3, MINT, False, True)
        text(d, (96, 360), "CHANGED CODE", 19, MUTED, mono=True)
        text(d, (1224, 360), "REPOSITORY EVIDENCE", 19, MUTED, mono=True)
        count = 0
        for i, (kind, wrong, right, source) in enumerate(rows(data)):
            y = 410 + i * 170
            found = u >= 2.1 + i * 3.0
            count += found
            color = RED if found else BLUE
            panel(d, (90, y, 704, y + 132))
            text(d, (117, y + 22), f"0{i + 1} / {kind}", 18, MUTED, mono=True)
            text(d, (117, y + 58), wrong, 39, color, True, True)
            wire(d, (704, y + 66), (1215, y + 66), t, color, i * 0.18, broken=found)
            panel(d, (1215, y, 1830, y + 132))
            text(d, (1244, y + 22), source, 20, MUTED, mono=True)
            text(d, (1244, y + 61), right, 35, MINT, True, True)
            if found:
                badge(d, 860, y + 92, "REJECT", RED)
        text(d, (96, 961), f"{count} proven broken references", 29, RED if count else MUTED)
        text(d, (1830, 961), "suggestions from your repo", 24, MUTED, anchor="rt")
    elif index == 3:
        reveal(im, (88, 161), "Repair the connection.", 80, u, color=INK)
        text(d, (94, 269), "Apply the suggested names, then run the same check.", 31, "#586c76")
        completed = 0
        for i, (kind, wrong, right, _) in enumerate(rows(data)):
            y = 375 + i * 146
            p = ease((u - 1.0 - i * 1.3) / 0.7)
            done = p >= 1
            completed += done
            panel(d, (92, y, 1320, y + 118), "#f9fbf6", "#d4dfd4", 16)
            text(d, (118, y + 20), kind, 17, "#586c76", mono=True)
            text(d, (118, y + 56), wrong, 32, "#947b77", mono=True)
            if p > 0:
                length = d.textlength(wrong, font=font(32, mono=True))
                d.line((116, y + 76, 116 + length * p, y + 76), fill="#b5675a", width=3)
                d.line((650, y + 72, 696, y + 72), fill="#138462", width=3)
                d.line([(685, y + 62), (696, y + 72), (685, y + 82)], fill="#138462", width=3)
                text(d, (745, y + 56), right[: int(len(right) * p)], 32, "#137653", True, True)
            if done:
                check(d, 1261, y + 64, "#138462")
        text(d, (1597, 465), str(3 - completed), 152, INK, True, anchor="mm")
        text(d, (1597, 590), "broken references", 23, "#586c76", anchor="mt")
        if u > 5.9:
            panel(d, (92, 849, 1828, 953), INK, INK, 18)
            badge(d, 116, 877, data["fixed"]["result"]["verdict"].upper(), MINT)
            text(d, (338, 888), "Same CLI. References resolve. Exit code 0.", 29, TEXT)
            check(d, 1774, 901, MINT)
    elif index == 4:
        reveal(im, (89, 173), "Uncertain? Keep it advisory.", 75, u)
        text(d, (96, 282), "Block only a proven falsehood.", 36, MUTED)
        panel(d, (96, 406, 808, 697))
        text(d, (128, 436), "DYNAMIC ENVIRONMENT KEY", 20, MUTED, mono=True)
        text(d, (128, 515), "os.environ[key]", 46, TEXT, mono=True)
        text(d, (128, 622), "Static value is unresolved.", 27, AMBER)
        wire(d, (808, 550), (1220, 550), t, AMBER)
        panel(d, (1220, 406, 1824, 697), "#2d302a", "#6a634d")
        badge(d, 1253, 445, data["dynamic"]["result"]["verdict"].upper(), AMBER)
        text(d, (1254, 531), "Human judgment.", 44, AMBER, True)
        text(d, (1254, 614), "exit code 0 · does not block", 26, TEXT)
        reveal(im, (97, 843), "Evidence first. Honest limits.", 50, u, 2.0, MINT)
    elif index == 5:
        reveal(im, (91, 173), "One engine. Four editors.", 77, u, color=INK)
        text(d, (97, 281), "The same verification engine, wherever you work.", 31, "#586c76")
        cx, cy = 958, 650
        for i, (name, detail, x, y) in enumerate(
            [
                ("CODEX", "MCP + Stop check", 342, 490),
                ("CLAUDE CODE", "Pre-edit + Stop check", 1548, 490),
                ("CURSOR", "MCP + Stop check", 342, 823),
                ("ANTIGRAVITY", "MCP + Stop check", 1548, 823),
            ]
        ):
            wire(d, (cx, cy), (x, y), t, "#268767", i * 0.25)
            panel(d, (x - 233, y - 73, x + 233, y + 73), "#f8faf4", "#c8d7cb")
            text(d, (x, y - 27), name, 28, INK, True, True, anchor="mm")
            text(d, (x, y + 22), detail, 23, "#586c76", anchor="mm")
        for r in (126, 161, 196):
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline="#cedbcf", width=2)
        d.ellipse((cx - 124, cy - 124, cx + 124, cy + 124), fill=INK)
        mark(d, cx - 49, cy - 49, 1.5)
        text(d, (cx, cy + 33), "weftgate", 28, TEXT, True, anchor="mm")
    else:
        sculpture(im, t, 1500, 520, 0.69)
        reveal(im, (89, 188), "Ship connected code.", 86, u, max_width=1450)
        reveal(im, (95, 306), "Start with the evidence in your repo.", 34, u, 0.3, MUTED, False)
        panel(d, (94, 465, 1150, 703), "#112c30", "#416e61")
        for i, value in enumerate(["pip install weftgate", "weftgate audit"]):
            text(d, (125, 514 + i * 86), "$", 37, MUTED, mono=True)
            text(d, (180, 514 + i * 86), value, 37, MINT if i == 0 else TEXT, mono=True)
        reveal(im, (97, 816), "github.com/Avinash-Amudala/weftgate", 40, u, 0.9, TEXT)
        reveal(
            im,
            (98, 898),
            "Try it. Share a reproduction. Help shape the gate.",
            28,
            u,
            1.3,
            MINT,
            False,
        )
    chapters = (
        "01 / THE DISCONNECT",
        "02 / MEET WEFTGATE",
        "03 / TRACE THE EVIDENCE",
        "04 / REPAIR + RECHECK",
        "05 / HONEST UNCERTAINTY",
        "06 / YOUR WORKFLOW",
        "07 / TRY IT",
    )
    chrome(im, t, chapters[index], light)
    return im


def frame_at(t: float, data: dict) -> Image.Image:
    index = max(i for i, start in enumerate(STARTS) if t >= start)
    u = t - STARTS[index]
    im = scene(index, u, t, data)
    # A short directional wipe gives chapters a physical transition, without flashes.
    if index and u < 0.42:
        old = scene(index - 1, STARTS[index] - STARTS[index - 1], t, data)
        p = ease(u / 0.42)
        cut = round(W * p)
        old.paste(im.crop((0, 0, cut, H)), (0, 0))
        ImageDraw.Draw(old).line((cut, 0, cut, H), fill=MINT, width=3)
        im = old
    if t > DURATION - 0.65:
        im = Image.blend(
            im, Image.new("RGB", (W, H), "#07111a"), clamp((t - DURATION + 0.65) / 0.65)
        )
    return im


def soundtrack(path: Path) -> None:
    """Original quiet stereo sound design: sine pads, plucks, and transition accents."""
    rate = 44100
    events = [
        (0, 146.83),
        (5, 220),
        (11, 293.66),
        (13.1, 440),
        (16.1, 349.23),
        (19.1, 293.66),
        (24, 196),
        (25, 392),
        (26.3, 493.88),
        (27.6, 587.33),
        (30, 783.99),
        (33, 174.61),
        (41, 220),
        (48, 293.66),
        (50, 440),
        (52, 587.33),
    ]
    with wave.open(str(path), "wb") as out:
        out.setparams((2, 2, rate, 0, "NONE", "not compressed"))
        for second in range(DURATION):
            block = array.array("h")
            for n in range(rate):
                t = second + n / rate
                fade = min(clamp(t / 2), clamp((DURATION - t) / 3))
                pad = sum(math.sin(2 * math.pi * hz * t) for hz in (73.416, 110, 146.832))
                sample = 0.013 * pad * (0.75 + 0.25 * math.sin(t * 0.55))
                accent = 0.0
                for start, hz in events:
                    dt = t - start
                    if 0 <= dt < 2.5:
                        env = (1 - math.exp(-dt * 60)) * math.exp(-dt * 3)
                        accent += (
                            0.065
                            * env
                            * (
                                math.sin(2 * math.pi * hz * dt)
                                + 0.25 * math.sin(2 * math.pi * hz * 2 * dt)
                            )
                        )
                left = (sample + accent) * fade
                right = (sample + accent * 0.94 + 0.006 * math.sin(2 * math.pi * 220.2 * t)) * fade
                block.extend((round(left * 32767), round(right * 32767)))
            if sys.byteorder != "little":
                block.byteswap()
            out.writeframes(block.tobytes())


def captions(out: Path) -> None:
    cues = [
        (0, 5, "The code looks right. But does it connect?"),
        (5, 11, "Weftgate checks environment variables, imports, and FastAPI route references."),
        (11, 16, "Run weftgate check app/broken.py. Trace each reference to repository evidence."),
        (16, 24, "Three broken references. Suggestions: requests, DATABASE_URL, and health."),
        (24, 30, "Apply the suggested names and run the same check."),
        (30, 33, "The corrected fixture returns ACCEPT, with exit code zero."),
        (33, 41, "A dynamic environment key returns REVIEW. Uncertainty does not block."),
        (
            41,
            48,
            "Native completion checks for Codex, Claude Code, Cursor and Antigravity. "
            "Activate hooks in your client.",
        ),
        (48, 58, "pip install weftgate. Run weftgate audit. Try it and share a reproduction."),
    ]
    out.write_text(
        "WEBVTT\n\n"
        + "\n\n".join(
            f"00:{a // 60:02d}:{a % 60:02d}.000 --> 00:{b // 60:02d}:{b % 60:02d}.000\n{line}"
            for a, b, line in cues
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable, help="Python with weftgate installed")
    parser.add_argument("--out", type=Path, default=Path("docs/assets"))
    parser.add_argument("--stills-only", action="store_true", help="Render a storyboard for review")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    data = evidence(
        str(Path(args.python).absolute()) if Path(args.python).is_file() else args.python
    )
    (args.out / "demo-evidence.json").write_text(json.dumps(data, indent=2) + "\n")
    frame_at(51, data).save(args.out / "demo-poster.png", optimize=True)
    frame_at(23, data).save(args.out / "demo-findings.png", optimize=True)
    moments = (3.7, 8, 23, 31.5, 38, 45, 51, 55)
    storyboard = Image.new("RGB", (1280, 1440), "#07111a")
    for i, t in enumerate(moments):
        preview = frame_at(t, data).resize((640, 360), Image.Resampling.LANCZOS)
        storyboard.paste(preview, ((i % 2) * 640, (i // 2) * 360))
    storyboard.save(args.out / "demo-storyboard.jpg", quality=92)
    captions(args.out / "demo.vtt")
    if args.stills_only:
        print(f"Storyboard and real CLI evidence saved to {args.out}", flush=True)
        return
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix="weftgate-film-") as tmp:
        audio = Path(tmp) / "soundtrack.wav"
        print("Synthesizing original sound design", flush=True)
        soundtrack(audio)
        command = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-s",
            f"{W}x{H}",
            "-pix_fmt",
            "rgb24",
            "-r",
            str(FPS),
            "-i",
            "-",
            "-i",
            str(audio),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "19",
            "-pix_fmt",
            "yuv420p",
            "-af",
            "volume=3",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            "-threads",
            "4",
            "-shortest",
            str(args.out / "weftgate-demo.mp4"),
        ]
        proc = subprocess.Popen(command, stdin=subprocess.PIPE)
        assert proc.stdin is not None
        try:
            for frame in range(DURATION * FPS):
                if frame % (FPS * 5) == 0:
                    print(f"Rendering {frame // FPS}/{DURATION}s", flush=True)
                proc.stdin.write(frame_at(frame / FPS, data).tobytes())
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise SystemExit("ffmpeg failed")
    # Two short complete beats form the README loop: evidence, then repaired verdict.
    gif_frames = []
    for start, end in ((19, 24), (28, 33)):
        for i in range(int((end - start) * 8)):
            gif_frames.append(
                frame_at(start + i / 8, data).resize((800, 450), Image.Resampling.LANCZOS)
            )
    gif_frames[0].save(
        args.out / "demo.gif",
        save_all=True,
        append_images=gif_frames[1:],
        duration=125,
        loop=0,
        optimize=True,
    )
    print(f"Film, storyboard, GIF, captions, and CLI evidence saved to {args.out}", flush=True)


if __name__ == "__main__":
    main()
