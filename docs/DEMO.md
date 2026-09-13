# Demo: follow the evidence

[Watch the 58-second, 1080p motion film](https://github.com/Avinash-Amudala/weftgate/releases/download/v0.1.1/weftgate-demo-motion.mp4).
Animated evidence paths, a perspective woven gate, and a repair sequence explain how
Weftgate checks relationships across files. The film includes original synthesized
sound design; every explanation is also visible on screen, so it works muted.
[WebVTT captions](assets/demo.vtt), a [lightweight GIF](assets/demo.gif), and a
[storyboard](assets/demo-storyboard.jpg) are included.

This is an animated walkthrough, not a screen recording. The renderer runs the real
public CLI against a temporary fixture containing three intentional mistakes. It
records the exit codes and JSON in [demo-evidence.json](assets/demo-evidence.json)
and uses the actual suggestions and verdicts in the animation. These are fixture
results, not a claim of production accuracy or a guarantee about another project.

## Reproduce

```bash
pip install -e '.[demo]'
python scripts/make_demo.py --python "$(command -v python)" --out docs/assets
# Optional: review the storyboard before rendering the video.
python scripts/make_demo.py --stills-only --out /tmp/weftgate-storyboard
```

Rendering uses Pillow and imageio-ffmpeg only in the optional `demo` extra. The
58-second MP4 is 1920 × 1080 at 30 fps, with H.264 video, AAC stereo audio, and
fast-start playback. On Linux, install DejaVu Sans and DejaVu Sans Mono fonts.
No repository contents are uploaded by the renderer. Rendering regenerates the
fixture evidence and checks the broken, fixed, and dynamic outcomes before export.

## Transcript

- 0–5 s: The code looks right. But does it connect? Three tiny typos break references.
- 5–11 s: A moving, woven gate represents checking environment, import, and route contracts.
- 11–24 s: Trace `requestz`, `DATABSE_URL`, and `helth` to repository evidence.
  The gate rejects the references and suggests `requests`, `DATABASE_URL`, and `health`.
- 24–33 s: Apply the suggested names. The broken-reference count falls to zero.
  The same CLI returns `accept`, exit code 0. This is not a claim that application tests passed.
- 33–41 s: A dynamic environment key returns `review`, exit code 0. Uncertainty stays advisory.
- 41–48 s: CLI, MCP, GitHub Action, and hooks use one verification engine.
- 48–58 s: Install `weftgate`, run `weftgate audit`, and share a reproduction.

Source: [scripts/make_demo.py](../scripts/make_demo.py). Geometry, animation, and
sound are generated from that source; no stock assets, external music, or voices
are used. Asset license: Apache-2.0, as for the repository. Locally installed fonts
are rendered but not distributed.
