#!/usr/bin/env python3
"""Fetch public sources, build, and pack the configured deploy target.

  python3 scripts/prepare.py
  python3 scripts/prepare.py --no-fetch
  python3 scripts/prepare.py --publish     # also publish cloudflare or github-pages

Does not call Vercel. After a Vercel pack, the bot sends dist/vercel/deploy_args.json
to the Vercel connector.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def run(script, extra=None):
    cmd = [sys.executable, str(ROOT / script), *(extra or [])]
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)

def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch, build, and pack the edition")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--sample", action="store_true", help="Skip fetch and build the sample edition")
    ap.add_argument("--publish", action="store_true", help="Publish when the target supports it")
    args = ap.parse_args(argv)
    if args.sample:
        run("build.py", ["--sample"])
    else:
        if not args.no_fetch:
            run("fetch.py")
        run("build.py")
    run("deploy.py", [] if args.publish else ["--pack"])
    return 0

if __name__ == "__main__":
    sys.exit(main())
