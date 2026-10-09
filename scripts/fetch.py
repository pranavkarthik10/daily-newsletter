#!/usr/bin/env python3
"""Fetch public sources (Hacker News, RSS/Atom, JSON feeds, Open-Meteo) into data/.

X, calendar, and email are not fetched here. The bot writes those through the
connectors; see docs/SCHEMAS.md and scripts/ingest.py.

Exit 0 when at least one source succeeded (or a previous good copy was kept).
Exit 1 when nothing could be fetched and there is no previous data.
"""
import html
import json
import re
import sys
import time
import datetime as dt
import gzip
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 daily-newsletter/1.0"
)

def http_get(url, timeout=20, max_bytes=5_000_000):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, application/json, text/xml, text/html;q=0.8, */*;q=0.5",
        "Accept-Encoding": "gzip",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = res.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise RuntimeError("response too large")
            enc = (res.headers.get("Content-Encoding") or "").lower()
            if "gzip" in enc or data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            return data
    except urllib.error.HTTPError as ex:
        raise RuntimeError(f"HTTP {ex.code}") from ex

def clean(s, n=None):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(re.sub(r"\s+", " ", s)).strip()
    if n and len(s) > n:
        cut = s[:n].rsplit(" ", 1)[0].rstrip(",;:.")
        s = (cut or s[:n]) + "…"
    return s

def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""

def child_text(el, names):
    names = set(names)
    for c in list(el):
        if local(c.tag) in names:
            return "".join(c.itertext()).strip()
    return ""

def entry_link(el):
    best = ""
    for c in list(el):
        if local(c.tag) != "link":
            continue
        href = (c.attrib.get("href") or "").strip()
        text = "".join(c.itertext()).strip()
        candidate = href or (text if text.startswith("http") else "")
        if not candidate:
            continue
        rel = c.attrib.get("rel", "alternate")
        if rel in ("alternate", "") or not best:
            if rel == "alternate" or not best:
                best = candidate
    return best

def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.isoformat()
    except Exception:
        pass
    try:
        return parsedate_to_datetime(s).isoformat()
    except Exception:
        return None

def domain(url):
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1) if m else ""

def parse_xml(data):
    data = re.sub(b"[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]", b"", data)
    return ET.fromstring(data)

def fetch_rss(feed):
    root = parse_xml(http_get(feed["url"]))
    out = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        title = clean(child_text(el, ("title",)))
        url = entry_link(el)
        summ = child_text(el, ("description", "summary", "content", "encoded"))
        if feed.get("id") == "arxiv":
            summ = re.sub(r"^arXiv:\S+\s+Announce Type:\s*\S+\s*Abstract:\s*", "", clean(summ))
        else:
            summ = clean(summ, 260)
        if feed.get("id") == "ghtrending":
            title = title.replace(" / ", "/")
        published = parse_date(child_text(el, ("pubDate", "published", "updated", "date")))
        author = clean(child_text(el, ("creator", "author", "name"))) or None
        if not title or not url:
            continue
        out.append({
            "title": title, "url": url, "summary": summ or None,
            "author": author, "published": published, "domain": domain(url),
        })
        if len(out) >= feed.get("limit", 20):
            break
    if not out:
        raise RuntimeError("no entries")
    return out

def og_description(url):
    try:
        data = http_get(url, timeout=6, max_bytes=200_000)
        text = data.decode("utf-8", "replace")
        patterns = [
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                d = clean(m.group(1), 320)
                if len(d) > 40:
                    return d
    except Exception:
        return None
    return None

def fetch_hn(feed):
    ids = json.loads(http_get(feed["url"]))[: feed.get("limit", 30)]
    def one(i):
        return json.loads(http_get(f"https://hacker-news.firebaseio.com/v0/item/{i}.json", timeout=15))
    with ThreadPoolExecutor(12) as ex:
        raw = list(ex.map(one, ids))
    items = []
    for it in raw:
        if not it or it.get("dead") or it.get("deleted") or not it.get("id"):
            continue
        hn_url = f"https://news.ycombinator.com/item?id={it['id']}"
        url = it.get("url") or hn_url
        items.append({
            "title": html.unescape(it.get("title") or ""),
            "url": url,
            "discuss": hn_url,
            "domain": domain(it.get("url")) or "news.ycombinator.com",
            "points": it.get("score", 0),
            "comments": it.get("descendants", 0),
            "by": it.get("by"),
            "published": dt.datetime.fromtimestamp(it.get("time") or 0, dt.timezone.utc).isoformat(),
            "summary": clean(it.get("text"), 320) if it.get("text") else None,
        })
    with ThreadPoolExecutor(4) as ex:
        decks = list(ex.map(lambda x: x["summary"] or og_description(x["url"]), items[:4]))
    for item, deck in zip(items[:4], decks):
        item["summary"] = deck
    return items

def fetch_lobsters(feed):
    out = []
    for row in json.loads(http_get(feed["url"]))[: feed.get("limit", 20)]:
        url = row.get("url") or row.get("comments_url")
        out.append({
            "title": row.get("title"),
            "url": url,
            "discuss": row.get("comments_url"),
            "points": row.get("score"),
            "comments": row.get("comment_count"),
            "tags": row.get("tags") or [],
            "summary": clean(row.get("description"), 220) or None,
            "published": row.get("created_at"),
            "domain": domain(url),
        })
    if not out:
        raise RuntimeError("no entries")
    return out

def fetch_hf(feed):
    out = []
    for row in json.loads(http_get(feed["url"]))[: feed.get("limit", 20)]:
        paper = row.get("paper") or {}
        pid = paper.get("id")
        if not pid:
            continue
        out.append({
            "title": clean(paper.get("title") or row.get("title")),
            "url": f"https://huggingface.co/papers/{pid}",
            "summary": clean(paper.get("ai_summary") or paper.get("summary"), 260) or None,
            "points": paper.get("upvotes"),
            "published": row.get("publishedAt") or paper.get("publishedAt"),
            "domain": "huggingface.co",
        })
    out.sort(key=lambda x: -(x.get("points") or 0))
    if not out:
        raise RuntimeError("no entries")
    return out

def fetch_json(feed):
    payload = json.loads(http_get(feed["url"]))
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise RuntimeError("JSON feed is not a list")
    out = []
    for row in rows[: feed.get("limit", 20)]:
        if not isinstance(row, dict):
            continue
        url = row.get("url") or row.get("link")
        title = clean(row.get("title") or row.get("name"))
        if not title or not url:
            continue
        out.append({
            "title": title, "url": url,
            "summary": clean(row.get("summary") or row.get("description"), 260) or None,
            "published": row.get("published") or row.get("date"),
            "author": row.get("author"),
            "domain": domain(url),
        })
    if not out:
        raise RuntimeError("no entries")
    return out

FETCHERS = {
    "hn": fetch_hn, "rss": fetch_rss, "lobsters": fetch_lobsters,
    "hf_papers": fetch_hf, "json": fetch_json,
}

def fetch_weather(cfg):
    loc = (cfg.get("paper") or {}).get("location") or {}
    if loc.get("lat") is None or loc.get("lon") is None:
        raise RuntimeError("paper.location needs lat and lon")
    qs = urllib.parse.urlencode({
        "latitude": loc["lat"], "longitude": loc["lon"],
        "timezone": (cfg.get("paper") or {}).get("timezone") or "UTC",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "forecast_days": 4,
        "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m,apparent_temperature",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_probability_max,daylight_duration,uv_index_max",
    })
    w = json.loads(http_get("https://api.open-meteo.com/v1/forecast?" + qs, timeout=15))
    w["location"] = loc.get("name") or ""
    w["wmo_text"] = {str(k): v for k, v in common.WMO.items()}
    return w

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Fetch public sources into data/")
    ap.add_argument("--config")
    ap.add_argument("--data")
    args = ap.parse_args(argv)
    cfg = common.load_config(args.config)
    for w in common.validate(cfg):
        print("warning:", w, file=sys.stderr)
    data = Path(args.data) if args.data else common.data_dir(sample=False)
    data.mkdir(parents=True, exist_ok=True)
    status = {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "feeds": {}}
    feeds_out = {}

    def run(feed):
        kind = feed.get("type")
        if kind not in FETCHERS:
            return feed, None, {"ok": False, "error": f"unknown type {kind!r}"}
        started = time.time()
        try:
            items = FETCHERS[kind](feed)
            return feed, items, {"ok": True, "count": len(items), "secs": round(time.time() - started, 1)}
        except Exception as ex:
            return feed, None, {"ok": False, "error": f"{type(ex).__name__}: {ex}"[:200]}

    feeds = [f for f in (cfg.get("feeds") or []) if isinstance(f, dict) and f.get("id")]
    with ThreadPoolExecutor(8) as ex:
        for feed, items, st in ex.map(run, feeds):
            status["feeds"][feed["id"]] = st
            if items is not None:
                feeds_out[feed["id"]] = {"name": feed.get("name") or feed["id"], "items": items}
    prev_path = data / "feeds.json"
    if prev_path.exists():
        prev = common.jload(prev_path, {}) or {}
        for fid, st in status["feeds"].items():
            if not st.get("ok") and isinstance(prev.get(fid), dict):
                feeds_out[fid] = prev[fid]
                st["stale"] = True
    try:
        (data / "weather.json").write_text(json.dumps(fetch_weather(cfg), indent=2), encoding="utf-8")
        status["weather"] = {"ok": True}
    except Exception as ex:
        status["weather"] = {"ok": False, "error": str(ex)[:200]}
    prev_path.write_text(json.dumps(feeds_out, indent=2), encoding="utf-8")
    (data / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    for fid, st in status["feeds"].items():
        flag = "OK " if st.get("ok") else ("STALE" if st.get("stale") else "ERR")
        print(f"{flag:5} {fid:14} {st.get('count', st.get('error'))}")
    print("weather", status["weather"])
    any_ok = any(st.get("ok") or st.get("stale") for st in status["feeds"].values()) or status["weather"].get("ok")
    return 0 if any_ok else 1

if __name__ == "__main__":
    sys.exit(main())
