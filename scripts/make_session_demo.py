#!/usr/bin/env python3
"""Render a memory-first vertical film from independently invoked, checked CLI calls.

Run: python -m scripts.make_session_demo [--stills-only]
Requires the optional demo extra. No editor UI or automatic chat capture is simulated.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw

from scripts import make_demo as base
from scripts.brain_visual import draw_brain

WIDTH, HEIGHT, FPS, SECONDS = 900, 1600, 24, 36
SCENES = (0, 5, 11, 18, 24, 30)


def evidence(python):
    with tempfile.TemporaryDirectory(prefix="weftgate-session-") as tmp:
        root = Path(tmp) / "repo"
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "examples/session-memory",
            root,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        env = dict(
            os.environ,
            WEFTGATE_CACHE=str(Path(tmp) / "cache"),
            WEFTGATE_LEDGER="0",
            XDG_CONFIG_HOME=str(Path(tmp) / "config"),
            PATH=str(Path(python).parent) + os.pathsep + os.environ.get("PATH", ""),
        )
        for args in (
            ["git", "init", "-q"],
            ["git", "add", "."],
            [
                "git",
                "-c",
                "user.name=Weftgate Demo",
                "-c",
                "user.email=demo@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
        ):
            subprocess.run(args, cwd=root, env=env, check=True, capture_output=True)

        def call(*args):
            result = subprocess.run(
                [python, "-m", "weftgate", "--repo", str(root), *args],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            return json.loads(result.stdout)

        saved = call(
            "remember",
            "Order retries",
            "Keep order creation idempotent.",
            "--file",
            "orders.py",
            "--id",
            "demo-order-retries",
        )
        brief = call("brief", "order retries", "--reference", "create_order", "--budget", "1200")
        handoff = call(
            "handoff",
            "Order retries",
            "Duplicate order test passes. Next: review persistence.",
            "--file",
            "orders.py",
            "--run",
            "--require-ready",
            "--id",
            "demo-handoff",
        )
        source = root / "orders.py"
        source.write_text(source.read_text() + "\n# The implementation is being reconsidered.\n")
        stale = call("recall", "order retries")
        data = {
            "version": "0.3.0",
            "saved": saved,
            "brief": brief,
            "handoff": handoff,
            "stale": stale,
        }
        assert saved["state"] == "anchored", saved
        assert "Keep order creation idempotent." in json.dumps(brief), brief
        assert "create_order" in json.dumps(brief), brief
        assert brief["resolution"] == [{"reference": "create_order", "status": "resolved"}], brief
        assert handoff["state"] == "ready" and handoff["evidence"]["tests_observed"], handoff
        assert handoff["evidence"]["tree_unchanged"], handoff
        assert stale["hidden_stale"] >= 1 and not stale["items"], stale
        return data


def frame(t, data):
    im = Image.new("RGB", (WIDTH, HEIGHT), "#081420")
    d = ImageDraw.Draw(im)
    for x in range(42, WIDTH, 42):
        for y in range(40, HEIGHT, 42):
            d.ellipse((x, y, x + 2, y + 2), fill="#203445")
    index = max(i for i, start in enumerate(SCENES) if t >= start)
    u = t - SCENES[index]

    def text(x, y, value, size=34, color=base.TEXT, bold=False, mono=False):
        base.text(d, (x, y), value, size, color, bold, mono, max_width=WIDTH - x - 65)

    def heading(line1, line2):
        text(64, 246, line1, 76, bold=True)
        text(64, 344, line2, 76, base.MINT, True)

    def card(label, lines, accent=base.MINT, y=920):
        base.panel(d, (60, y, 840, y + 270), "#132937", "#395164")
        text(88, y + 32, label, 22, accent, True, True)
        for i, line in enumerate(lines):
            text(88, y + 95 + i * 56, line, 32)

    text(64, 118, "weftgate", 38, bold=True)
    text(580, 128, f"0{index + 1} / LOCAL BRAIN", 18, base.MUTED, mono=True)
    if index == 0:
        heading("New session.", "Same project brain.")
        draw_brain(im, (450, 712), 0.72, t)
        card(
            "KEEP THE CONTEXT THAT MATTERS",
            ["Decisions. Source pointers.", "A useful handoff for the next agent."],
        )
        text(70, 1250, "Codex · Claude Code · Cursor · Antigravity", 25, base.MUTED)
        text(70, 1300, "Connect each client to the same local repo.", 27, base.MUTED)
    elif index == 1:
        heading("Save the decision.", "Anchor it to code.")
        draw_brain(im, (450, 683), 0.6, t)
        card("01 / REMEMBER", ["Keep order creation idempotent.", "Source: orders.py"], base.BLUE)
        text(70, 1250, "Explicit notes, saved locally.", 32, base.MUTED)
        text(70, 1300, "No automatic chat-history capture.", 27, base.MUTED)
    elif index == 2:
        heading("Start fresh.", "Recall what matters.")
        for j, label in enumerate(("PREVIOUS SESSION", "LOCAL NOTEBOOK", "NEXT SESSION")):
            y = 520 + j * 105
            base.panel(d, (110, y, 790, y + 80))
            text(143, y + 25, label, 25, base.BLUE if j == 1 else base.TEXT, mono=True)
            if j < 2:
                d.line((450, y + 80, 450, y + 103), fill=base.MINT, width=3)
        card(
            '02 / BRIEF "ORDER RETRIES"',
            ["Saved decision + create_order source", "Compact context, with a size budget."],
        )
        text(70, 1250, "Each demo step is a new CLI process.", 29, base.MUTED)
        text(70, 1300, "Shared CLI/MCP tools. Model token counts vary.", 24, base.MUTED)
    elif index == 3:
        heading("Hand off the work.", "Keep the evidence.")
        draw_brain(im, (450, 685), 0.6, t)
        card(
            "03 / HANDOFF --RUN",
            ["Duplicate-order test: passed", "Next: review persistence."],
            base.MINT,
        )
        text(70, 1250, "Observed test output saved with the summary.", 28, base.MUTED)
        text(70, 1300, "Historical evidence. Recheck in the next session.", 25, base.MUTED)
    elif index == 4:
        heading("The source changes.", "Old notes step aside.")
        draw_brain(im, (450, 685), 0.6, t)
        card(
            "04 / FRESHNESS CHECK",
            [
                f"{data['stale']['hidden_stale']} stale notes hidden on recall.",
                "Review the decision against current code.",
            ],
            base.AMBER,
        )
        text(70, 1250, "Verification supports the whole workflow.", 29, base.MUTED)
        text(70, 1300, "Fresh sources do not prove a note's prose.", 26, base.MUTED)
    else:
        heading("Give your agents", "a shared memory.")
        draw_brain(im, (450, 700), 0.64, t)
        card(
            "FREE · OPEN SOURCE · ONE PACKAGE",
            ["pip install weftgate", "weftgate setup --agents all"],
            y=950,
        )
        text(70, 1270, "Try the session-memory example.", 32, base.MUTED)
        text(70, 1322, "Star the repo if it helps your workflow.", 27, base.MUTED)
    text(65, 1424, "github.com/Avinash-Amudala/weftgate", 27, base.MINT)
    text(65, 1476, "ANIMATED WALKTHROUGH · EXECUTED CLI EVIDENCE", 16, base.MUTED, mono=True)
    d.rectangle((0, HEIGHT - 7, WIDTH * t / SECONDS, HEIGHT), fill=base.MINT)
    if u < 0.25:
        im = Image.blend(Image.new("RGB", im.size, "#081420"), im, base.ease(u / 0.25))
    return im


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stills-only", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("docs/assets/session"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    data = evidence(sys.executable)
    (args.out / "evidence.json").write_text(json.dumps(data, indent=2) + "\n")
    board = Image.new("RGB", (900, 1066), "#081420")
    for i, start in enumerate(SCENES):
        board.paste(frame(start + 2, data).resize((300, 533)), ((i % 3) * 300, (i // 3) * 533))
    board.save(args.out / "storyboard.jpg", quality=95)
    frame(2, data).save(args.out / "poster.png", optimize=True)
    captions = [
        "New session. Same project brain. Connect each agent to the same local repository.",
        "Save decisions explicitly and anchor them to code. No automatic transcript capture.",
        "Resume with relevant memories and compact source pointers. Model token counts vary.",
        "Save a handoff with observed test output. Historical evidence must be checked again.",
        "Changed source files hide old notes on recall. Freshness does not prove prose.",
        "pip install weftgate. Try the session-memory example. Star the repo if it helps.",
    ]
    blocks = [
        f"00:00:{a:02}.000 --> 00:00:{b:02}.000\n{caption}"
        for a, b, caption in zip(SCENES, (*SCENES[1:], SECONDS), captions, strict=True)
    ]
    (args.out / "captions.vtt").write_text("WEBVTT\n\n" + "\n\n".join(blocks) + "\n")
    if args.stills_only:
        print("CLI evidence passed; storyboard rendered.")
        return
    base.DURATION = SECONDS
    with tempfile.TemporaryDirectory(prefix="weftgate-audio-") as tmp:
        audio = Path(tmp) / "audio.wav"
        base.soundtrack(audio)
        command = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{WIDTH}x{HEIGHT}",
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
            "20",
            "-pix_fmt",
            "yuv420p",
            "-af",
            "volume=3",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            "-threads",
            "4",
            "-shortest",
            str(args.out / "weftgate-session-memory.mp4"),
        ]
        proc = subprocess.Popen(command, stdin=subprocess.PIPE)
        try:
            for i in range(SECONDS * FPS):
                if i % (6 * FPS) == 0:
                    print(f"Rendering {i // FPS}/{SECONDS}s", flush=True)
                proc.stdin.write(frame(i / FPS, data).tobytes())
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise SystemExit("ffmpeg failed")
    print("Film rendered from checked CLI evidence.")


if __name__ == "__main__":
    main()
