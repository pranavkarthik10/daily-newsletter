#!/usr/bin/env python3
"""Publish dist/site to a gh-pages branch of the current repo.

  python3 scripts/deploy_github_pages.py --pack     # instructions only
  python3 scripts/deploy_github_pages.py            # git push the branch

The push force-updates only the pages branch (default gh-pages), never main.
Private sections are refused when the GitHub repo is public: a public branch
would publish the secret path. Pass --allow-public only if you accept that.

Credentials: whatever `git push` already uses (gh auth, SSH, or a token).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

def run(cmd, cwd, check=True):
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise SystemExit(f"{' '.join(cmd)} failed:\n{proc.stderr.strip() or proc.stdout.strip()}")
    return proc

def visibility():
    proc = subprocess.run(
        ["gh", "repo", "view", "--json", "visibility"],
        cwd=common.ROOT, text=True, capture_output=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout).get("visibility")
    except json.JSONDecodeError:
        return None

def remote_url():
    proc = run(["git", "remote", "get-url", "origin"], common.ROOT)
    return proc.stdout.strip()

def write_pack(branch, site):
    out = common.dist_root() / "github-pages"
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.txt").write_text(
        "GitHub Pages\n"
        "============\n"
        f"Built site: {site}\n"
        f"Branch:     {branch}  (force-updated; main is never touched)\n\n"
        "From the repo root, with git credentials that can push:\n"
        "  python3 scripts/deploy_github_pages.py\n\n"
        "Then in the repo settings, set Pages to deploy from that branch, root.\n"
        "A project site is served at https://<user>.github.io/<repo>/.\n"
        "Relative links in the paper work there. Add deploy.domain to write a\n"
        "CNAME file if you use a custom domain.\n",
        encoding="utf-8",
    )
    print(f"wrote {out / 'README.txt'}")

def publish(cfg, allow_public):
    site = common.dist_root() / "site"
    if not (site / "index.html").exists():
        raise SystemExit("dist/site is missing. Run python3 scripts/build.py first.")
    branch = (cfg.get("deploy") or {}).get("github_pages_branch") or "gh-pages"
    if branch in ("main", "master"):
        raise SystemExit("refusing to publish onto main or master; set deploy.github_pages_branch to gh-pages")
    private = bool(common.enabled_private(cfg))
    vis = visibility() if private else None
    if private and vis == "PUBLIC" and not allow_public:
        raise SystemExit(
            "private sections are on and this GitHub repo is public. "
            "A public gh-pages branch would expose the secret path. "
            "Use Vercel or Cloudflare, make the repo private, or pass --allow-public if you accept the risk."
        )
    if private and vis is None and not allow_public:
        raise SystemExit(
            "private sections are on and `gh repo view` could not confirm the repo is private. "
            "Pass --allow-public to push anyway, or switch the deploy target."
        )
    write_pack(branch, site)
    url = os.environ.get("GITHUB_PAGES_REMOTE_URL") or remote_url()
    tmp = Path(tempfile.mkdtemp(prefix="daily-newsletter-pages-"))
    try:
        shutil.copytree(site, tmp, dirs_exist_ok=True)
        domain = ((cfg.get("deploy") or {}).get("domain") or "").strip()
        if domain:
            (tmp / "CNAME").write_text(domain + "\n", encoding="utf-8")
        run(["git", "init"], tmp)
        run(["git", "checkout", "-b", branch], tmp)
        run(["git", "config", "user.email", "daily-newsletter@localhost"], tmp)
        run(["git", "config", "user.name", "daily-newsletter"], tmp)
        run(["git", "add", "-A"], tmp)
        run(["git", "commit", "-m", "Publish daily edition"], tmp)
        run(["git", "remote", "add", "origin", url], tmp)
        print(f"pushing {branch} to {url}")
        run(["git", "push", "--force", "origin", f"HEAD:{branch}"], tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    enable_pages(branch)
    print(f"pushed {branch}.")

def enable_pages(branch):
    """Best-effort: turn GitHub Pages on for the branch. The git push already succeeded."""
    view = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner"],
        cwd=common.ROOT, text=True, capture_output=True,
    )
    if view.returncode != 0:
        print("Could not enable Pages automatically. In the repo settings, set Pages to this branch, root.")
        return
    try:
        name = json.loads(view.stdout)["nameWithOwner"]
    except (json.JSONDecodeError, KeyError):
        print("Could not enable Pages automatically. In the repo settings, set Pages to this branch, root.")
        return
    body = json.dumps({"build_type": "legacy", "source": {"branch": branch, "path": "/"}})
    proc = subprocess.run(
        ["gh", "api", "--method", "POST", f"repos/{name}/pages", "--input", "-"],
        input=body, text=True, capture_output=True,
    )
    if proc.returncode == 0:
        print(f"GitHub Pages enabled from {branch}.")
        return
    # Already configured: update the source branch.
    proc = subprocess.run(
        ["gh", "api", "--method", "PUT", f"repos/{name}/pages", "--input", "-"],
        input=body, text=True, capture_output=True,
    )
    if proc.returncode == 0:
        print(f"GitHub Pages source set to {branch}.")
    else:
        print("Pushed the branch. Enable Pages in the repo settings (branch " + branch + ", folder root) if it is not on yet.")

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Publish dist/site to GitHub Pages")
    ap.add_argument("--pack", action="store_true")
    ap.add_argument("--allow-public", action="store_true")
    args = ap.parse_args(argv)
    cfg = common.load_config()
    branch = (cfg.get("deploy") or {}).get("github_pages_branch") or "gh-pages"
    site = common.dist_root() / "site"
    if args.pack:
        if not (site / "index.html").exists():
            raise SystemExit("dist/site is missing. Run python3 scripts/build.py first.")
        write_pack(branch, site)
        return 0
    publish(cfg, args.allow_public)
    return 0

if __name__ == "__main__":
    sys.exit(main())
