#!/usr/bin/env python3
"""Render the v0.2 brain film with executable context and memory evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw

from scripts import make_demo as base
from scripts.brain_visual import draw_brain, hero

DURATION = 78
base.DURATION = DURATION


def evidence(python):
    data = base.evidence(python)
    with tempfile.TemporaryDirectory(prefix="weftgate-brain-demo-") as tmp:
        root = Path(tmp) / "repo"
        subprocess.run(
            [
                python,
                "-c",
                "from weftgate.eval.fixture import write_fixture; "
                "import sys; write_fixture(sys.argv[1])",
                str(root),
            ],
            check=True,
        )
        env = dict(
            os.environ,
            WEFTGATE_CACHE=str(Path(tmp) / "cache"),
            WEFTGATE_LEDGER="0",
            XDG_CONFIG_HOME=str(Path(tmp) / "config"),
        )

        def call(*args):
            result = subprocess.run(
                [python, "-m", "weftgate", "--repo", str(root), *args],
                env=env,
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            return json.loads(result.stdout)

        data["context"] = call("card", "POST /api/orders", "--budget", "1200")
        data["saved"] = call(
            "remember",
            "Order contract",
            "Keep order creation in this handler.",
            "--file",
            "app/orders.py",
        )
        data["recalled"] = call("recall", "orders")
        path = root / "app/orders.py"
        path.write_text(path.read_text() + "\n# Contract implementation revised.\n")
        data["stale"] = call("recall", "orders")
        assert data["context"]["status"] == "resolved"
        assert any(
            i.get("node", {}).get("id") == "symbol:app/orders.py:create_order"
            for i in data["context"]["items"]
        )
        assert data["saved"]["state"] == "anchored" and len(data["recalled"]["items"]) == 1
        assert data["stale"]["hidden_stale"] == 1 and data["stale"]["items"] == []
    return data


def frame(t, data):
    if t < 48 and not 5 <= t < 11:
        return base.frame_at(t, data)
    im = base.background().copy()
    d = ImageDraw.Draw(im)
    text, panel, reveal = base.text, base.panel, base.reveal
    if t < 11:
        u = t - 5
        draw_brain(im, (1430, 525), 1.12, t)
        reveal(im, (90, 251), "A second brain.", 85, u)
        reveal(im, (90, 369), "Grounded in code.", 79, u, 0.18, base.MINT)
        reveal(im, (96, 537), "Understand. Remember. Verify.", 34, u, 0.6, base.MUTED, False)
        base.badge(d, 98, 766, "ONE LOCAL PACKAGE", base.MINT)
        chapter = "02 / MEET WEFTGATE"
    elif t < 58:
        u = t - 48
        reveal(im, (90, 174), "Understand the path.", 80, u)
        reveal(
            im,
            (95, 280),
            "A compact contract card, with source locations.",
            34,
            u,
            0.3,
            base.MUTED,
            False,
        )
        text(
            d,
            (100, 384),
            '$ weftgate card "POST /api/orders" --budget 1200',
            29,
            base.MINT,
            mono=True,
        )
        for i, (label, value, detail) in enumerate(
            [
                ("ROUTE", "POST /api/orders", "Observed registration"),
                ("HANDLER", "create_order", "app/orders.py"),
                ("CONTEXT", "Source pointers", "No full file bodies"),
            ]
        ):
            x = 95 + i * 595
            if i < 2:
                base.wire(d, (x + 530, 632), (x + 595, 632), t, base.MINT, i * 0.2)
            panel(d, (x, 513, x + 540, 740))
            text(d, (x + 28, 542), label, 20, base.BLUE, mono=True)
            text(d, (x + 28, 589), value, 31, base.TEXT, True, max_width=485)
            text(d, (x + 28, 658), detail, 24, base.MUTED)
        n = data["context"]["usage"]["bytes"]
        text(d, (99, 824), f"{n:,} JSON bytes returned  /  4,800 byte cap", 32, base.MINT)
        text(d, (99, 887), "Fixture measurement. Model token counts vary.", 25, base.MUTED)
        chapter = "07 / UNDERSTAND"
    elif t < 68:
        u = t - 58
        reveal(im, (90, 174), "Memory that notices change.", 70, u)
        text(d, (96, 280), "Keep the decision. Recheck its source.", 34, base.MUTED)
        draw_brain(im, (1462, 562), 0.96, t)
        panel(d, (94, 411, 1100, 733))
        text(d, (124, 445), "SAVED DECISION", 20, base.BLUE, mono=True)
        text(d, (124, 499), "Order contract", 43, base.TEXT, True)
        text(d, (124, 566), "Source: app/orders.py", 28, base.MUTED, mono=True)
        changed = u >= 4.5
        base.badge(
            d,
            125,
            645,
            "STALE: HIDDEN ON RECALL" if changed else "ANCHORED: SOURCE UNCHANGED",
            base.AMBER if changed else base.MINT,
        )
        text(
            d,
            (99, 826),
            "Source changed. Recall withholds the old note."
            if changed
            else "Store useful decisions explicitly, with file anchors.",
            30,
            base.TEXT,
        )
        text(
            d,
            (99, 888),
            "Anchors verify source freshness. They do not prove prose.",
            26,
            base.MUTED,
        )
        chapter = "08 / REMEMBER"
    else:
        u = t - 68
        draw_brain(im, (1515, 570), 0.78, t)
        reveal(im, (89, 188), "Give your agent a second brain.", 66, u)
        reveal(
            im,
            (95, 306),
            "Context. Memory. Verification. One local install.",
            34,
            u,
            0.3,
            base.MUTED,
            False,
        )
        panel(d, (94, 465, 1150, 703), "#112c30", "#416e61")
        text(d, (125, 514), "$ pip install weftgate", 37, base.MINT, mono=True)
        text(d, (125, 610), "$ weftgate setup --agents all --hooks", 27, base.TEXT, mono=True)
        reveal(im, (97, 816), "github.com/Avinash-Amudala/weftgate", 40, u, 0.9, base.TEXT)
        text(
            d,
            (99, 906),
            "Review and activate hooks in your editor. Keep CI checks required.",
            26,
            base.MUTED,
        )
        chapter = "09 / TRY IT"
    base.chrome(im, t, chapter)
    if t > 77.35:
        im = Image.blend(im, Image.new("RGB", im.size, "#07111a"), base.clamp((t - 77.35) / 0.65))
    return im


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--out", type=Path, default=Path("docs/assets"))
    parser.add_argument("--stills-only", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    python = str(Path(args.python).absolute()) if Path(args.python).is_file() else args.python
    data = evidence(python)
    (args.out / "demo-evidence.json").write_text(json.dumps(data, indent=2) + "\n")
    hero().save(args.out / "weftgate-brain.png", optimize=True)
    frame(72, data).save(args.out / "demo-poster.png", optimize=True)
    frame(23, data).save(args.out / "demo-findings.png", optimize=True)
    moments = (3.7, 8, 23, 31.5, 38, 45, 53, 61, 65, 73)
    storyboard = Image.new("RGB", (1280, 1800), "#07111a")
    for i, t in enumerate(moments):
        storyboard.paste(
            frame(t, data).resize((640, 360), Image.Resampling.LANCZOS),
            ((i % 2) * 640, (i // 2) * 360),
        )
    storyboard.save(args.out / "demo-storyboard.jpg", quality=93)
    base.captions(args.out / "demo.vtt")
    captions = (args.out / "demo.vtt").read_text()
    old = (
        "00:00:48.000 --> 00:00:58.000\npip install weftgate. "
        "Run weftgate audit. Try it and share a reproduction."
    )
    new = (
        "00:00:48.000 --> 00:00:58.000\nRequest compact source-backed contract cards. "
        "Token counts vary by model.\n\n"
        "00:00:58.000 --> 00:01:08.000\nSave decisions with file anchors. Changed sources "
        "are hidden on recall. Fresh sources do not prove prose.\n\n"
        "00:01:08.000 --> 00:01:18.000\npip install weftgate. "
        "Review and activate your editor hooks. "
        "Keep CI checks required."
    )
    assert old in captions
    (args.out / "demo.vtt").write_text(
        captions.replace(old, new).replace(
            "Weftgate checks environment variables, imports, and FastAPI route references.",
            "A local second brain grounded in code. Understand, remember, verify.",
        )
    )
    subtitles = []
    for number, block in enumerate(
        (args.out / "demo.vtt").read_text().strip().split("\n\n")[1:], 1
    ):
        lines = block.splitlines()
        lines[0] = lines[0].replace(".", ",")
        subtitles.append(str(number) + "\n" + "\n".join(lines))
    (args.out / "demo.srt").write_text("\n\n".join(subtitles) + "\n")
    if args.stills_only:
        print(f"Storyboard and real CLI evidence saved to {args.out}", flush=True)
        return
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix="weftgate-film-") as tmp:
        soundtrack = Path(tmp) / "soundtrack.wav"
        print("Synthesizing original sound design", flush=True)
        base.soundtrack(soundtrack)
        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-s",
            "1920x1080",
            "-pix_fmt",
            "rgb24",
            "-r",
            "30",
            "-i",
            "-",
            "-i",
            str(soundtrack),
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
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        try:
            for index in range(DURATION * 30):
                if index % 150 == 0:
                    print(f"Rendering {index // 30}/{DURATION}s", flush=True)
                proc.stdin.write(frame(index / 30, data).tobytes())
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise SystemExit("ffmpeg failed")
    frames = [
        frame(start + i / 6, data)
        .resize((640, 360), Image.Resampling.LANCZOS)
        .quantize(colors=96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        for start in (6, 21, 51, 63)
        for i in range(18)
    ]
    frames[0].save(
        args.out / "demo.gif",
        save_all=True,
        append_images=frames[1:],
        duration=167,
        loop=0,
        optimize=True,
    )
    print(f"Film, artwork and executable evidence saved to {args.out}", flush=True)


if __name__ == "__main__":
    main()
