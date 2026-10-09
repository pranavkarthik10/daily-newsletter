#!/usr/bin/env python3
"""Pack dist/site into the file list the Vercel connector's create_deployment accepts.

The connector allows only a few "$file:" substitutions per call, so the paper is
packed into two files (HTML with CSS and JS inlined, and fonts as data URIs).
This script does not call Vercel and does not need a token.

  python3 scripts/deploy_vercel.py
Then pass dist/vercel/deploy_args.json as the arguments to create_deployment.
Do not add teamId; the connector's default scope is the right account.
"""
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

def _latin_fonts_css(site_fonts: Path, fonts_css: str) -> str:
    faces = {}
    for block in re.findall(r"@font-face \{.*?\}", fonts_css, re.S):
        url_m = re.search(r"url\((.*?)\)", block)
        if not url_m or not url_m.group(1).endswith("-latin.woff2"):
            continue
        fam = re.search(r"font-family: '(.*?)'", block).group(1)
        style = re.search(r"font-style: (\w+)", block).group(1)
        weight = int(re.search(r"font-weight: (\d+)", block).group(1))
        data = (site_fonts / url_m.group(1)).read_bytes()
        key = (fam, style, hashlib.md5(data).hexdigest())
        rng = re.search(r"unicode-range: ([^;]+);", block).group(1)
        face = faces.setdefault(key, {"w": [], "data": data, "rng": rng})
        face["w"].append(weight)
    out = []
    for (fam, style, _), face in faces.items():
        weights = face["w"]
        weight = f"{min(weights)} {max(weights)}" if len(weights) > 1 else str(weights[0])
        b64 = base64.b64encode(face["data"]).decode()
        out.append(
            f"@font-face{{font-family:'{fam}';font-style:{style};font-weight:{weight};font-display:swap;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');unicode-range:{face['rng']}}}"
        )
    return "\n".join(out) + "\n"

def pack(cfg=None):
    cfg = cfg or common.load_config()
    root = common.dist_root()
    site = root / "site"
    page_index = site / "index.html"
    if not page_index.exists():
        raise SystemExit("dist/site is missing. Run python3 scripts/build.py first.")
    publish = common.jload(root / "publish.json", {}) or {}
    private = bool(publish.get("private"))
    key = publish.get("path", "/").strip("/")
    if private:
        page_index = site / key / "index.html"
        if not page_index.exists():
            raise SystemExit(f"private edition missing {page_index}")
    out = root / "vercel"
    out.mkdir(parents=True, exist_ok=True)
    fonts_css = _latin_fonts_css(common.SITE / "fonts", (common.SITE / "fonts" / "fonts.css").read_text(encoding="utf-8"))
    (out / "fonts.css").write_text(fonts_css, encoding="utf-8")
    html = page_index.read_text(encoding="utf-8")
    style = (common.SITE / "style.css").read_text(encoding="utf-8")
    js = (common.SITE / "app.js").read_text(encoding="utf-8")
    html = re.sub(r'<link rel="stylesheet" href="fonts/fonts.css">', '<link rel="stylesheet" href="fonts.css">', html)
    html = re.sub(r'<link rel="stylesheet" href="style\.css\?v=\d+">', lambda m: f"<style>{style}</style>", html)
    html = re.sub(r'<script src="app\.js\?v=\d+"></script>', lambda m: f"<script>{js}</script>", html)
    if "<style>" not in html or "<script>" not in html:
        raise SystemExit("could not inline style.css and app.js; the built HTML was not recognized")
    (out / "page.html").write_text(html, encoding="utf-8")
    project = common.project_slug(cfg)
    blank = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="robots" content="noindex,nofollow"><title></title>'
        '<style>html{background:#f3efe6}</style></head><body></body></html>\n'
    )
    headers = [
        {"key": "X-Content-Type-Options", "value": "nosniff"},
        {"key": "Referrer-Policy", "value": "no-referrer" if private else "strict-origin-when-cross-origin"},
    ]
    if private:
        headers.insert(0, {"key": "X-Robots-Tag", "value": "noindex, nofollow"})
    vercel_json = {
        "trailingSlash": True,
        "headers": [
            {"source": "/(.*)", "headers": headers},
            {"source": "/(.*)", "headers": [{"key": "Cache-Control", "value": "no-cache"}]},
        ],
    }
    # Long-cache the font file specifically. Later header groups override per Vercel's rules
    # only when they match; keep a dedicated rule so fonts.css is cacheable.
    font_path = f"/{key}/fonts.css" if private else "/fonts.css"
    page_path = f"/{key}/" if private else "/"
    vercel_json["headers"].append({"source": page_path, "headers": [{"key": "Cache-Control", "value": "no-cache"}]})
    vercel_json["headers"].append({"source": font_path, "headers": [{"key": "Cache-Control", "value": "public, max-age=604800"}]})
    files = []
    if private:
        files.append({"file": "index.html", "encoding": "utf-8", "data": blank})
        files.append({"file": f"{key}/index.html", "encoding": "utf-8", "data": f"$file:{out / 'page.html'}"})
        files.append({"file": f"{key}/fonts.css", "encoding": "utf-8", "data": f"$file:{out / 'fonts.css'}"})
        robots = "User-agent: *\nDisallow: /\n"
    else:
        files.append({"file": "index.html", "encoding": "utf-8", "data": f"$file:{out / 'page.html'}"})
        files.append({"file": "fonts.css", "encoding": "utf-8", "data": f"$file:{out / 'fonts.css'}"})
        robots = "User-agent: *\nAllow: /\n"
    files.append({"file": "robots.txt", "encoding": "utf-8", "data": robots})
    files.append({"file": "vercel.json", "encoding": "utf-8", "data": json.dumps(vercel_json)})
    args = {
        "forceNew": "1",
        "skipAutoDetectionConfirmation": "1",
        "requestBody": {
            "name": project,
            "project": project,
            "target": "production",
            "projectSettings": {
                "framework": None,
                "buildCommand": None,
                "installCommand": None,
                "outputDirectory": None,
            },
            "files": files,
        },
    }
    dest = out / "deploy_args.json"
    dest.write_text(json.dumps(args), encoding="utf-8")
    print(f"page.html {len(html)//1024} KB, fonts.css {(out/'fonts.css').stat().st_size//1024} KB")
    print(f"wrote {dest}")
    print("Pass that JSON as the arguments to the Vercel connector create_deployment.")
    print("Do not add teamId. Create the project first if it does not exist (ssoProtection null).")
    return dest

if __name__ == "__main__":
    pack()
