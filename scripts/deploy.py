#!/usr/bin/env python3
"""Pack or publish the built site for newsletter.config.json -> deploy.target.

  python3 scripts/deploy.py                 # pack; publish cloudflare/github-pages if creds exist
  python3 scripts/deploy.py --pack          # never publish
  python3 scripts/deploy.py --target vercel # override the config for this run

Targets: static, vercel, cloudflare, github-pages.
Vercel is always pack-only: the bot calls the Vercel connector with the args file.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import deploy_cloudflare
import deploy_github_pages
import deploy_vercel

def pack_static(cfg):
    site = common.dist_root() / "site"
    note = common.dist_root() / "STATIC_HOST.txt"
    publish = common.jload(common.dist_root() / "publish.json", {}) or {}
    note.write_text(
        "Any static host\n"
        "===============\n"
        f"Upload the contents of:\n  {site}\n\n"
        f"The edition is {'private' if publish.get('private') else 'public'}.\n"
        f"Serve it so that {publish.get('path', '/')} is the paper.\n"
        "Do not upload dist/publish.json or .secret_path.\n"
        "Turn off directory listings so a private path cannot be browsed.\n",
        encoding="utf-8",
    )
    print(f"static site ready at {site}")
    print(f"wrote {note}")

def main(argv=None):
    ap = argparse.ArgumentParser(description="Pack or publish the built edition")
    ap.add_argument("--pack", action="store_true", help="Write helper files only")
    ap.add_argument("--target", choices=("static", "vercel", "cloudflare", "github-pages"))
    ap.add_argument("--allow-public", action="store_true", help="Allow GitHub Pages with private sections")
    args = ap.parse_args(argv)
    cfg = common.load_config()
    target = args.target or (cfg.get("deploy") or {}).get("target") or "static"
    site = common.dist_root() / "site"
    if not (site / "index.html").exists():
        raise SystemExit("dist/site is missing. Run python3 scripts/build.py first.")
    if target == "static":
        pack_static(cfg)
        return 0
    if target == "vercel":
        deploy_vercel.pack(cfg)
        return 0
    if target == "cloudflare":
        if args.pack:
            return deploy_cloudflare.main(["--pack"])
        return deploy_cloudflare.main([])
    if target == "github-pages":
        cmd = ["--pack"] if args.pack else []
        if args.allow_public:
            cmd.append("--allow-public")
        return deploy_github_pages.main(cmd)
    raise SystemExit(f"unknown target {target}")

if __name__ == "__main__":
    sys.exit(main() or 0)
