#!/usr/bin/env python3
"""Shared paths, config loading, and small helpers. Standard library only."""
import json, os, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

KINDS = ("hn", "feeds", "x_news", "x_posts", "items", "calendar", "email")

# WMO weather interpretation codes used by Open-Meteo. Stored on the weather
# JSON too, so a built page does not need this table, but the build falls back to it.
WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "passing showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail",
}

def config_path():
    return Path(os.environ.get("NEWSLETTER_CONFIG", ROOT / "newsletter.config.json"))

def data_dir(sample=False):
    if os.environ.get("NEWSLETTER_DATA"):
        return Path(os.environ["NEWSLETTER_DATA"])
    return ROOT / "data" / "sample" if sample else ROOT / "data"

def dist_root():
    return Path(os.environ.get("NEWSLETTER_DIST", ROOT / "dist"))

def secret_file():
    return Path(os.environ.get("NEWSLETTER_SECRET_FILE", ROOT / ".secret_path"))

def jload(path, default=None):
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        print(f"warning: {p} is not valid JSON ({e})", file=sys.stderr)
        return default

def load_config(path=None):
    p = Path(path) if path else config_path()
    if not p.exists():
        raise SystemExit(f"missing config: {p}")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise SystemExit(f"config must be a JSON object: {p}")
    return cfg

def validate(cfg):
    """Return human-readable warnings. Never raises."""
    warns = []
    paper = cfg.get("paper") or {}
    if not paper.get("name"):
        warns.append("paper.name is empty; the masthead will fall back to The Morning Tab")
    if not paper.get("timezone"):
        warns.append("paper.timezone is missing; times will use UTC")
    loc = paper.get("location") or {}
    if loc and (loc.get("lat") is None or loc.get("lon") is None):
        warns.append("paper.location needs lat and lon (run scripts/geocode.py)")
    feeds = cfg.get("feeds") or []
    ids = [f.get("id") for f in feeds]
    if any(not i for i in ids):
        warns.append("a feed is missing an id")
    dupes = {i for i in ids if i and ids.count(i) > 1}
    if dupes:
        warns.append("duplicate feed ids: " + ", ".join(sorted(dupes)))
    known = set(ids)
    seen_sec = []
    for s in (cfg.get("sections") or []) + (cfg.get("private_sections") or []):
        sid = s.get("id") or "?"
        seen_sec.append(sid)
        kind = s.get("kind")
        if kind not in KINDS:
            warns.append(f"section {sid} has unknown kind {kind!r}")
        for fid in s.get("feeds") or []:
            if fid not in known:
                warns.append(f"section {sid} references unknown feed {fid}")
        if kind == "x_news" and not s.get("topic"):
            warns.append(f"section {sid} (x_news) needs a topic")
    if len(seen_sec) != len(set(seen_sec)):
        warns.append("duplicate section ids")
    target = (cfg.get("deploy") or {}).get("target", "static")
    if target not in ("static", "vercel", "cloudflare", "github-pages"):
        warns.append(f"unknown deploy.target {target!r}")
    return warns

def enabled_private(cfg):
    """Sections that carry personal data and therefore force a secret path."""
    out = []
    for s in cfg.get("sections") or []:
        if s.get("private") and s.get("enabled", True):
            out.append(s)
    for s in cfg.get("private_sections") or []:
        if s.get("enabled"):
            out.append(s)
    return out

def read_secret():
    f = secret_file()
    if not f.exists():
        return None
    key = f.read_text(encoding="utf-8").strip()
    if key and re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
        return key
    print(f"warning: ignoring malformed secret file {f}", file=sys.stderr)
    return None

def ensure_secret():
    """Return the stable secret path segment, creating it once."""
    import secrets
    key = read_secret()
    if key:
        return key
    key = secrets.token_urlsafe(9)
    f = secret_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(key + "\n", encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return key

def project_slug(cfg):
    raw = (cfg.get("deploy") or {}).get("project_name") or "daily-newsletter"
    slug = re.sub(r"[^a-z0-9-]+", "-", str(raw).lower()).strip("-")
    return (slug or "daily-newsletter")[:60]
