#!/usr/bin/env python3
"""Build platform-tagged wheels for all supported targets.

Requires: pip install build wheel
Run from the repo root after running sync_binary.py.
"""
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BIN_DIR = REPO_ROOT / "agent_runtime" / "bin"
DIST_DIR = REPO_ROOT / "dist"

# (binary_name, wheel_platform_tag)
TARGETS = [
    ("agent-runtime-darwin-arm64",        "macosx_11_0_arm64"),
    ("agent-runtime-darwin-amd64",        "macosx_10_12_x86_64"),
    ("agent-runtime-linux-amd64",         "manylinux2014_x86_64"),
    ("agent-runtime-linux-arm64",          "manylinux2014_aarch64"),
    ("agent-runtime-windows-amd64.exe",   "win_amd64"),
]


def run(*args: str) -> None:
    subprocess.run(args, check=True, cwd=REPO_ROOT)


def build_all() -> None:
    DIST_DIR.mkdir(exist_ok=True)

    # Stash all binaries before the loop so wiping bin/ doesn't destroy sources
    tmp_bins = REPO_ROOT / "_bins_tmp"
    if tmp_bins.exists():
        shutil.rmtree(tmp_bins)
    shutil.copytree(BIN_DIR, tmp_bins)

    for binary_name, platform_tag in TARGETS:
        src = tmp_bins / binary_name
        if not src.exists():
            print(f"ERROR: {src} not found — run sync_binary.py first", file=sys.stderr)
            shutil.rmtree(tmp_bins)
            sys.exit(1)

        # Wipe bin/ and stage only this binary
        for f in BIN_DIR.iterdir():
            f.unlink()
        shutil.copy2(src, BIN_DIR / binary_name)
        if not binary_name.endswith(".exe"):
            (BIN_DIR / binary_name).chmod(0o755)

        # Build a generic any wheel
        tmp_dist = REPO_ROOT / "_wheel_tmp"
        if tmp_dist.exists():
            shutil.rmtree(tmp_dist)
        run(sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(tmp_dist))

        # Find the produced wheel
        wheels = list(tmp_dist.glob("*.whl"))
        if len(wheels) != 1:
            print(f"ERROR: expected 1 wheel in {tmp_dist}, got {wheels}", file=sys.stderr)
            sys.exit(1)
        wheel_path = wheels[0]

        # Re-tag it with the correct platform
        run(sys.executable, "-m", "wheel", "tags",
            "--platform-tag", platform_tag,
            "--remove",
            str(wheel_path))

        # wheel tags writes the new wheel next to the original; move to dist/
        retagged = list(tmp_dist.glob(f"*{platform_tag}*.whl"))
        if not retagged:
            # fallback: wheel may have been written in place
            retagged = list(tmp_dist.glob("*.whl"))
        for w in retagged:
            shutil.move(str(w), str(DIST_DIR / w.name))
            print(f"  {w.name}")

        shutil.rmtree(tmp_dist)
        print(f"Built {platform_tag}")

    # Restore all binaries to bin/
    for f in BIN_DIR.iterdir():
        f.unlink()
    for f in tmp_bins.iterdir():
        shutil.copy2(f, BIN_DIR / f.name)
        if not f.name.endswith(".exe"):
            (BIN_DIR / f.name).chmod(0o755)
    shutil.rmtree(tmp_bins)

    print(f"\nDone — wheels in {DIST_DIR}/")


if __name__ == "__main__":
    build_all()
