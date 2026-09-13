#!/usr/bin/env python3
"""Read launch metrics using the signed-in gh CLI; keep aggregate traffic local."""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
from pathlib import Path
from typing import Any


def api(path: str) -> Any:
    proc = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=False)
    if proc.returncode:
        return {"unavailable": True, "reason": proc.stderr.strip()}
    return json.loads(proc.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="Avinash-Amudala/weftgate")
    parser.add_argument("--out", type=Path, default=Path(".launch-metrics"))
    args = parser.parse_args()
    repo = api(f"repos/{args.repo}")
    if repo.get("unavailable"):
        raise SystemExit(repo["reason"])
    now = datetime.datetime.now(datetime.timezone.utc)
    report = {
        "measured_at": now.isoformat(),
        "repo": repo["full_name"],
        "stars": repo["stargazers_count"],
        "forks": repo["forks_count"],
        "open_issues_and_prs": repo["open_issues_count"],
        "traffic_views": api(f"repos/{args.repo}/traffic/views"),
        "traffic_clones": api(f"repos/{args.repo}/traffic/clones"),
        "note": "Aggregate GitHub activity; not installs or active users. No user telemetry.",
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / (now.strftime("%Y-%m-%dT%H-%M-%SZ") + ".json")
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{report['repo']}: {report['stars']} stars, {report['forks']} forks")
    print(f"Local snapshot: {path}")


if __name__ == "__main__":
    main()
