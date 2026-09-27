#!/usr/bin/env python3
"""Fetch the audited upstream revision without initializing the parent repository.

Only the Turtlebot subtree is checked out. Existing checkouts are verified, never
reset or updated. --check performs no network requests or filesystem mutations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def verify(checkout: Path, config: dict) -> None:
    if not (checkout / ".git").exists():
        raise ValueError(f"Not an upstream Git checkout: {checkout}")
    if git("remote", "get-url", "origin", cwd=checkout) != config["repository"]:
        raise ValueError("Existing checkout has an unexpected origin; left unchanged.")
    actual = git("rev-parse", "HEAD", cwd=checkout)
    if actual != config["revision"]:
        raise ValueError(f"Expected {config['revision']}, found {actual}; left unchanged.")
    if git("status", "--porcelain", "--untracked-files=no", cwd=checkout):
        raise ValueError("Upstream tracked files are modified; left unchanged.")
    untracked = git("ls-files", "--others", "--exclude-standard", cwd=checkout).splitlines()
    if any(name != "COLCON_IGNORE" for name in untracked):
        raise ValueError("Upstream checkout contains untracked files; inspect them before use.")
    for filename in config["data_files"]:
        if not (checkout / config["data_directory"] / filename).is_file():
            raise ValueError(f"Missing upstream data file: {filename}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify only; do not clone or write files.")
    args = parser.parse_args()
    try:
        config = json.loads((ROOT / "config" / "upstream.json").read_text(encoding="utf-8"))
        if not re.fullmatch(r"[0-9a-f]{40}", config["revision"]):
            raise ValueError("Upstream pin must be a full 40-character commit hash.")
        external = (ROOT / "external").resolve()
        checkout = (ROOT / config["checkout_path"]).resolve()
        if external.parent != ROOT or checkout.parent != external or checkout.name != "SafeLLMRA":
            raise ValueError("Upstream destination must be external/SafeLLMRA.")
        if not checkout.exists():
            if args.check:
                raise ValueError("Upstream is not fetched. Run scripts/fetch_upstream.py first.")
            external.mkdir(parents=True, exist_ok=True)
            git("clone", "--filter=blob:none", "--sparse", "--no-checkout", "--depth", "1",
                "--no-tags", config["repository"], str(checkout))
            git("fetch", "--depth", "1", "origin", config["revision"], cwd=checkout)
            git("sparse-checkout", "set", *config["sparse_paths"], cwd=checkout)
            git("checkout", "--detach", config["revision"], cwd=checkout)
        verify(checkout, config)
        marker = checkout / "COLCON_IGNORE"
        if args.check and not marker.is_file():
            raise ValueError("Missing COLCON_IGNORE; run without --check to isolate upstream discovery.")
        if not args.check:
            marker.write_text("# Build explicitly selected Turtlebot packages in a separate workspace.\n", encoding="utf-8")
        print(f"Verified {config['name']} {config['revision']} at {checkout}")
        print("Source pin verified; runtime compatibility and formal enforcement remain unverified.")
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        message = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f"Upstream setup failed: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
