# Demo: catch a broken connection before it ships

[Watch the 52-second, 1080p MP4](assets/weftgate-demo.mp4). The video is silent, with
all explanations visible on screen. [WebVTT captions](assets/demo.vtt) and a
[lightweight GIF](assets/demo.gif) are included.

The renderer runs the real public CLI against a temporary fixture containing three
intentional mistakes. It records the exit codes and JSON in
[demo-evidence.json](assets/demo-evidence.json). These are fixture results, not a
claim of production accuracy or a guarantee about another project.

## Reproduce

```bash
pip install -e '.[demo]'
python scripts/make_demo.py --python "$(command -v python)" --out docs/assets
```

Rendering uses Pillow and imageio-ffmpeg only in the optional `demo` extra. On Linux,
install DejaVu Sans and DejaVu Sans Mono fonts. No repository contents are uploaded.

## Transcript

- 0–7 s: Catch broken connections in agent-written code. One local gate, no API key.
- 7–14 s: A fixture contains `requestz`, `DATABSE_URL`, and an undefined `helth` handler.
- 14–27 s: The gate rejects each hard contradiction and suggests the corresponding name.
- 27–36 s: Correct the three names. The same CLI now returns `accept`, exit code 0.
- 36–44 s: A computed environment key returns `review`, exit code 0. Uncertainty does not block.
- 44–52 s: Install `weftgate`, run `weftgate audit`, and inspect the supported contracts.

Source: [scripts/make_demo.py](../scripts/make_demo.py). Asset license: Apache-2.0,
as for the repository. Fonts are rendered using locally installed fonts and are not distributed.
