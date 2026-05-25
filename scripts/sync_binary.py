#!/usr/bin/env python3
"""Download pre-built agent-runtime binaries from a GitHub release.

Usage:
    python scripts/sync_binary.py v0.1.0
"""
import sys
import urllib.request
from pathlib import Path

REPO = "levelplaneai/agent-runtime"

ASSETS = [
    "agent-runtime-darwin-arm64",
    "agent-runtime-darwin-amd64",
    "agent-runtime-linux-amd64",
    "agent-runtime-linux-arm64",
    "agent-runtime-windows-amd64.exe",
]

BIN_DIR = Path(__file__).parent.parent / "agent_runtime" / "bin"


def download(tag: str) -> None:
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    base = f"https://github.com/{REPO}/releases/download/{tag}"

    for asset in ASSETS:
        url = f"{base}/{asset}"
        dest = BIN_DIR / asset
        print(f"Downloading {asset} ...", flush=True)
        urllib.request.urlretrieve(url, dest)
        if not asset.endswith(".exe"):
            dest.chmod(0o755)

    print(f"Done — {len(ASSETS)} binaries written to {BIN_DIR}/")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <tag>  (e.g. v0.1.0)", file=sys.stderr)
        sys.exit(1)
    download(sys.argv[1])
