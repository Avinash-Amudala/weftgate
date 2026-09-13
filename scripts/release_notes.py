"""Extract exactly one version from the changelog, including its final line."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def extract(text: str, version: str) -> str:
    match = re.search(r"^## \[" + re.escape(version.removeprefix("v")) + r"\].*$", text, re.M)
    if match is None:
        raise ValueError(f"no changelog entry for {version}")
    start = match.end()
    end = re.search(r"^## ", text[start:], re.M)
    return text[start : start + end.start() if end else len(text)].strip() + "\n"


if __name__ == "__main__":
    print(extract(Path("CHANGELOG.md").read_text(), sys.argv[1]), end="")
