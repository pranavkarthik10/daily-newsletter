#!/usr/bin/env python3
"""Publish dist/site to Cloudflare Pages, or print the commands if no token is set.

Direct upload uses the Pages API (stdlib only):
  CLOUDFLARE_API_TOKEN   API token with Cloudflare Pages: Edit
  CLOUDFLARE_ACCOUNT_ID  account id

Wrangler is the other path (Pages or Workers static assets). This script tries
the direct API when both variables are set. It never prints the token.

  python3 scripts/deploy_cloudflare.py            # upload if credentials exist
  python3 scripts/deploy_cloudflare.py --pack     # write wrangler.toml and instructions only
"""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:32]

def iter_files(site: Path):
    for path in sorted(p for p in site.rglob("*") if p.is_file()):
        rel = "/" + path.relative_to(site).as_posix()
        yield rel, path.read_bytes()

def multipart(manifest, files):
    boundary = "----dailynewsletter" + uuid.uuid4().hex
    body = bytearray()
    body += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="manifest"\r\n'
        f"Content-Type: application/json\r\n\r\n"
    ).encode() + json.dumps(manifest).encode() + b"\r\n"
    for name, content in files:
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return boundary, bytes(body)

def api(method, url, token, data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode("utf-8", "replace")
        try:
            return json.loads(detail)
        except json.JSONDecodeError:
            raise SystemExit(f"Cloudflare HTTP {ex.code}: {detail[:400]}") from ex

def ensure_project(account, project, token):
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/pages/projects"
    got = api("GET", f"{url}/{project}", token)
    if got.get("success"):
        return
    created = api("POST", url, token, data=json.dumps({
        "name": project, "production_branch": "main",
    }).encode(), headers={"Content-Type": "application/json"})
    if not created.get("success"):
        raise SystemExit("could not create the Pages project: " + json.dumps(created.get("errors") or created)[:500])
    print(f"created Cloudflare Pages project {project}")

def upload(site: Path, account, project, token):
    ensure_project(account, project, token)
    manifest, pending = {}, []
    for rel, content in iter_files(site):
        digest = file_hash(content)
        manifest[rel] = digest
        pending.append((digest, content))
    boundary, body = multipart(manifest, pending)
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/pages/projects/{project}/deployments"
    result = api("POST", url, token, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    if not result.get("success"):
        raise SystemExit("Pages deploy failed: " + json.dumps(result.get("errors") or result)[:800])
    deployment = result.get("result") or {}
    url_out = deployment.get("url") or ""
    aliases = deployment.get("aliases") or []
    print("deployed", url_out or aliases or deployment.get("id"))
    return deployment

def write_pack(cfg, site: Path):
    project = common.project_slug(cfg)
    out = common.dist_root() / "cloudflare"
    out.mkdir(parents=True, exist_ok=True)
    toml = (
        f'name = "{project}"\n'
        'compatibility_date = "2026-10-09"\n'
        "\n"
        "[assets]\n"
        'directory = "../site"\n'
        'html_handling = "auto-trailing-slash"\n'
        'not_found_handling = "404-page"\n'
    )
    (out / "wrangler.toml").write_text(toml, encoding="utf-8")
    (out / "README.txt").write_text(
        "Cloudflare Pages (direct upload or Wrangler)\n"
        "===========================================\n"
        f"Site directory: {site}\n"
        f"Project name:   {project}\n\n"
        "Pages, Wrangler:\n"
        f"  npx wrangler pages deploy {site} --project-name {project}\n\n"
        "Pages, direct API (what scripts/deploy_cloudflare.py does):\n"
        "  export CLOUDFLARE_API_TOKEN=...   # Pages Edit\n"
        "  export CLOUDFLARE_ACCOUNT_ID=...\n"
        "  python3 scripts/deploy_cloudflare.py\n\n"
        "Workers static assets, from this directory:\n"
        "  npx wrangler deploy\n"
        "The wrangler.toml next to this file points [assets].directory at ../site.\n",
        encoding="utf-8",
    )
    print(f"wrote {out / 'wrangler.toml'}")
    return project

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Deploy dist/site to Cloudflare Pages")
    ap.add_argument("--pack", action="store_true", help="Write helper files only")
    args = ap.parse_args(argv)
    cfg = common.load_config()
    site = common.dist_root() / "site"
    if not (site / "index.html").exists():
        raise SystemExit("dist/site is missing. Run python3 scripts/build.py first.")
    project = write_pack(cfg, site)
    if args.pack:
        return 0
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not token or not account:
        print("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID are not both set.")
        print(f"Pack is in {common.dist_root() / 'cloudflare'}. See docs/DEPLOY.md.")
        return 0
    upload(site, account, project, token)
    return 0

if __name__ == "__main__":
    sys.exit(main())
