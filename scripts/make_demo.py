#!/usr/bin/env python3
"""Render a silent, captioned product demo from real gate results.

Requires the optional demo extra (Pillow + imageio-ffmpeg). No network is used
by the renderer. Run from an installed checkout: python scripts/make_demo.py.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
FPS = 24
DURATION = 52
BG = "#0c1217"
PANEL = "#141d25"
BORDER = "#293943"
TEXT = "#edf1ec"
MUTED = "#91a4b0"
GREEN = "#8de4b1"
RED = "#ff9c8f"
AMBER = "#f1ce86"
FONTS: dict[tuple[int, bool, bool], ImageFont.FreeTypeFont] = {}


def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold, mono)
    if key not in FONTS:
        candidates = (
            [
                "/System/Library/Fonts/Menlo.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            ]
            if mono
            else [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
                if bold
                else "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                if bold
                else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        )
        for candidate in candidates:
            if Path(candidate).is_file():
                FONTS[key] = ImageFont.truetype(candidate, size)
                break
        else:
            raise SystemExit("Install DejaVu Sans and DejaVu Sans Mono fonts to render the demo.")
    return FONTS[key]


def label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    size: int = 30,
    fill: str = TEXT,
    bold: bool = False,
    mono: bool = False,
) -> None:
    draw.text(xy, text, font=font(size, bold, mono), fill=fill)


def box(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    fill: str = PANEL,
    outline: str = BORDER,
    radius: int = 22,
) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=2)


def logo(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1) -> None:
    def p(a: int, b: int) -> tuple[int, int]:
        return int(x + a * scale), int(y + b * scale)

    for i in range(3):
        draw.line(
            [p(0, i * 15), p(25, i * 15), p(40, 30 - i * 15), p(62, 30 - i * 15)],
            fill=GREEN,
            width=max(2, int(4 * scale)),
        )
    for a, b in [(0, 0), (0, 15), (0, 30), (62, 0), (62, 15), (62, 30)]:
        px, py = p(a, b)
        r = max(3, int(4 * scale))
        draw.ellipse((px - r, py - r, px + r, py + r), fill=GREEN)


def base(step: str) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    for x in range(900, W, 60):
        for y in range(40, H, 60):
            d.ellipse((x, y, x + 2, y + 2), fill="#25313a")
    logo(d, 98, 62)
    label(d, (183, 49), "weftgate", 40, bold=True)
    label(d, (1480, 63), step, 21, fill=MUTED, mono=True)
    d.line((96, 133, 1824, 133), fill=BORDER, width=2)
    label(d, (98, 1015), "LOCAL  /  NO API KEY  /  OPEN SOURCE", 21, fill=MUTED, mono=True)
    label(d, (1380, 1015), "VERIFY THE CONNECTIONS", 21, fill=MUTED, mono=True)
    return im


def terminal(draw: ImageDraw.ImageDraw, title: str, y: int = 392) -> None:
    box(draw, (96, y, 1824, 961))
    for i, c in enumerate(("#ff8077", "#f1ce86", "#8de4b1")):
        draw.ellipse((127 + i * 29, y + 27, 142 + i * 29, y + 42), fill=c)
    label(draw, (260, y + 21), title, 23, fill=MUTED, mono=True)
    draw.line((97, y + 67, 1823, y + 67), fill=BORDER, width=2)


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


def scenes(data: dict) -> list[Image.Image]:
    out = []
    im = base("01 / THE PROBLEM")
    d = ImageDraw.Draw(im)
    label(d, (96, 215), "Looks right.", 119, bold=True)
    label(d, (96, 347), "Doesn’t connect.", 119, fill=GREEN, bold=True)
    label(d, (102, 525), "Catch broken env, import, and route references", 42, fill=MUTED)
    label(d, (102, 584), "before agent-written code ships.", 42, fill=MUTED)
    for i, (a, b) in enumerate(
        [("ENV READ", "DECLARATION"), ("IMPORT", "LOCKFILE"), ("ROUTE", "HANDLER")]
    ):
        x = 98 + i * 580
        box(d, (x, 728, x + 546, 878))
        label(d, (x + 26, 754), a, 22, fill=MUTED, mono=True)
        d.line((x + 26, 827, x + 352, 827), fill=GREEN, width=3)
        d.ellipse((x + 345, 820, x + 359, 834), fill=GREEN)
        label(d, (x + 240, 754), b, 22, fill=TEXT, mono=True)
    out.append(im)

    im = base("02 / THE CHANGE")
    d = ImageDraw.Draw(im)
    label(d, (96, 197), "Three small mistakes.", 79, bold=True)
    label(d, (99, 297), "Each one crosses a file boundary.", 36, fill=MUTED)
    terminal(d, "app/broken.py")
    lines = [
        ("import requestz", RED),
        ("", TEXT),
        ('SECRET = os.environ["DATABSE_URL"]', RED),
        ("", TEXT),
        ('app.add_api_route("/late", helth)', RED),
    ]
    for i, (line, color) in enumerate(lines):
        label(d, (131, 501 + i * 67), str([3, 4, 8, 9, 10][i]).rjust(2), 27, fill=MUTED, mono=True)
        label(d, (219, 498 + i * 67), line, 40, fill=color, mono=True)
    out.append(im)

    rejected = {
        f["oracle"]: f for f in data["broken"]["result"]["findings"] if f["level"] == "reject"
    }
    for count in (1, 2, 3):
        im = base("03 / VERIFY")
        d = ImageDraw.Draw(im)
        label(d, (96, 190), "Check the wiring.", 80, bold=True)
        label(d, (100, 298), "$ weftgate check app/broken.py", 34, fill=GREEN, mono=True)
        for i, (oracle, kind) in enumerate(
            [("imports_lockfile", "IMPORT"), ("env_vars", "ENV VAR"), ("routes_fastapi", "ROUTE")]
        ):
            y = 409 + i * 165
            if i >= count:
                continue
            f = rejected[oracle]
            box(d, (96, y, 1824, y + 143))
            box(d, (122, y + 28, 302, y + 78), fill="#392727", outline="#734e48", radius=10)
            label(d, (145, y + 38), "REJECT", 26, fill=RED, bold=True, mono=True)
            label(d, (331, y + 28), kind, 20, fill=MUTED, mono=True)
            subject = {
                "env_vars": "DATABSE_URL",
                "imports_lockfile": "requestz",
                "routes_fastapi": "helth",
            }[oracle]
            label(d, (331, y + 69), subject, 37, bold=True, mono=True)
            label(d, (971, y + 29), "DID YOU MEAN", 20, fill=MUTED, mono=True)
            label(d, (970, y + 69), f["suggestions"][0], 37, fill=GREEN, bold=True, mono=True)
        if count == 3:
            label(
                d,
                (103, 941),
                "3 proven broken references.  3 actionable suggestions.",
                27,
                fill=RED,
            )
        out.append(im)

    im = base("04 / FIX + RECHECK")
    d = ImageDraw.Draw(im)
    label(d, (96, 190), "Fix. Check. Ship.", 80, bold=True)
    label(d, (100, 298), "The same gate verifies the corrected code.", 36, fill=MUTED)
    terminal(d, "app/broken.py — corrected")
    for i, line in enumerate(
        [
            "import requests",
            'SECRET = os.environ["DATABASE_URL"]',
            'app.add_api_route("/late", health)',
        ]
    ):
        label(d, (137, 501 + i * 67), line, 37, fill=GREEN, mono=True)
    d.line((134, 745, 1786, 745), fill=BORDER, width=2)
    label(d, (137, 785), "$ weftgate check app/broken.py", 31, fill=MUTED, mono=True)
    label(d, (137, 847), "ACCEPT", 42, fill=GREEN, bold=True, mono=True)
    label(d, (390, 856), "0 rejects  ·  exit code 0", 29, fill=TEXT, mono=True)
    out.append(im)

    im = base("05 / THE TRUST RULE")
    d = ImageDraw.Draw(im)
    label(d, (96, 192), "Uncertainty stays advisory.", 72, bold=True)
    label(d, (101, 295), "A computed key is a review, never a false rejection.", 34, fill=MUTED)
    terminal(d, "dynamic.py")
    label(d, (138, 505), "value = os.environ[key]", 43, fill=TEXT, mono=True)
    box(d, (134, 628, 388, 700), fill="#3b3326", outline="#786341", radius=12)
    label(d, (174, 643), "REVIEW", 36, fill=AMBER, bold=True, mono=True)
    label(d, (437, 648), "Cannot resolve a dynamic name.", 33, fill=AMBER)
    label(d, (138, 803), "exit code 0", 32, fill=GREEN, mono=True)
    label(d, (138, 862), "Only a proven false reference blocks by default.", 31, fill=MUTED)
    out.append(im)

    im = base("06 / TRY IT")
    d = ImageDraw.Draw(im)
    label(d, (96, 205), "Your repo. Your evidence.", 80, bold=True)
    label(d, (100, 317), "One gate for your terminal, agent, and pull requests.", 34, fill=MUTED)
    box(d, (96, 435, 1824, 670))
    label(d, (140, 475), "$ pip install weftgate", 45, fill=GREEN, mono=True)
    label(d, (140, 556), "$ weftgate audit", 45, fill=TEXT, mono=True)
    for i, text in enumerate(["CLI", "MCP", "GITHUB ACTION", "PRE-COMMIT"]):
        x = 98 + [0, 240, 480, 960][i]
        label(d, (x, 750), text, 25, fill=MUTED, mono=True)
    label(d, (98, 854), "github.com/Avinash-Amudala/weftgate", 42, bold=True)
    label(
        d, (101, 925), "Try the demo. Report a false block. Help improve the gate.", 27, fill=GREEN
    )
    out.append(im)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python", default=sys.executable, help="Interpreter with weftgate installed"
    )
    parser.add_argument("--out", type=Path, default=Path("docs/assets"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    data = evidence(args.python)
    (args.out / "demo-evidence.json").write_text(json.dumps(data, indent=2) + "\n")
    cards = scenes(data)
    cards[0].save(args.out / "demo-poster.png", optimize=True)
    cards[4].save(args.out / "demo-findings.png", optimize=True)
    timeline = [(0, 0), (7, 1), (14, 2), (17, 3), (20, 4), (27, 5), (36, 6), (44, 7)]
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
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
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-threads",
        "4",
        str(args.out / "weftgate-demo.mp4"),
    ]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    gif_frames = []
    current = -1
    for frame in range(DURATION * FPS):
        t = frame / FPS
        index = max(i for i, (start, _) in enumerate(timeline) if t >= start)
        start, scene = timeline[index]
        elapsed = t - start
        if index != current:
            print(f"Rendering scene {index + 1}/{len(timeline)} at {start}s", flush=True)
            current = index
        im = cards[scene].copy()
        if index and elapsed < 0.36:
            alpha = (1 - math.cos(math.pi * elapsed / 0.36)) / 2
            im = Image.blend(cards[timeline[index - 1][1]], im, alpha)
        d = ImageDraw.Draw(im)
        d.rectangle((0, H - 5, int(W * t / DURATION), H), fill=GREEN)
        proc.stdin.write(im.tobytes())
        if frame % (FPS // 6) == 0 and 14 <= t < 27:
            gif_frames.append(im.resize((960, 540), Image.Resampling.LANCZOS))
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg failed")
    gif_frames[0].save(
        args.out / "demo.gif",
        save_all=True,
        append_images=gif_frames[1:],
        duration=167,
        loop=0,
        optimize=True,
    )
    cues = [
        (0, 7, "Looks right. Doesn’t connect. Verify env, import, and route references."),
        (7, 14, "Three mistakes: requestz, DATABSE_URL, and the helth handler."),
        (14, 27, "Weftgate rejects all three and suggests requests, DATABASE_URL, and health."),
        (27, 36, "Correct the references. Run the same check. ACCEPT, exit code 0."),
        (36, 44, "A dynamic environment key returns REVIEW, exit code 0."),
        (44, 52, "Install weftgate and audit your repository. CLI, MCP, GitHub Action, and hooks."),
    ]

    def stamp(s: int) -> str:
        return f"00:00:{s:02d}.000"

    (args.out / "demo.vtt").write_text(
        "WEBVTT\n\n" + "\n\n".join(f"{stamp(a)} --> {stamp(b)}\n{c}" for a, b, c in cues) + "\n"
    )
    print(f"Demo, GIF, captions, poster, and actual evidence saved to {args.out}", flush=True)


if __name__ == "__main__":
    main()
