#!/usr/bin/env python3
"""Normalize connector payloads into the JSON files the build reads.

The build does not care how a file was produced. You can write the normalized
documents in docs/SCHEMAS.md yourself and skip this script. Use ingest when
you have a raw connector response (Google Calendar, Microsoft Graph, Gmail,
or the X search tools) and want it reshaped.

  python3 scripts/ingest.py x --news ai:raw.json --posts raw_posts.json
  python3 scripts/ingest.py x --normalized data/x.json
  python3 scripts/ingest.py calendar raw.json
  python3 scripts/ingest.py calendar-error "connector unavailable"
  python3 scripts/ingest.py email raw.json
  python3 scripts/ingest.py email-error "connector unavailable"
  python3 scripts/ingest.py items SECTION_ID raw.json
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def load_loose(path):
    t = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    if not t:
        raise SystemExit(f"empty file: {path}")
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    i, j = t.find("{"), t.rfind("}")
    a, b = t.find("["), t.rfind("]")
    if i != -1 and j > i and (a == -1 or i < a):
        return json.loads(t[i:j + 1])
    if a != -1 and b > a:
        return json.loads(t[a:b + 1])
    raise SystemExit(f"no JSON found in {path}")

def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path}")

def data_path(name):
    return common.data_dir(sample=False) / name

def clean_post(text):
    text = html.unescape(text or "")
    text = re.sub(r"(\s*https://t\.co/\w+)+\s*$", "", text.strip())
    return text.strip()

def ingest_x(args):
    if args.normalized:
        d = load_loose(args.normalized)
        if not isinstance(d, dict) or "news" not in d and "posts" not in d:
            raise SystemExit("normalized X JSON needs news and/or posts")
        d.setdefault("news", {})
        d.setdefault("posts", [])
        d["updated_at"] = d.get("updated_at") or now()
        write(data_path("x.json"), d)
        return
    order = ["ai", "coding", "business", "tech"]
    news, seen = {}, set()
    pairs = []
    for spec in args.news or []:
        if ":" not in spec:
            raise SystemExit(f"--news expects topic:file, got {spec!r}")
        pairs.append(spec.split(":", 1))
    pairs.sort(key=lambda p: order.index(p[0]) if p[0] in order else 99)
    for topic, path in pairs:
        payload = load_loose(path)
        rows = payload.get("data") if isinstance(payload, dict) else payload
        for s in rows or []:
            if not isinstance(s, dict):
                continue
            sid = s.get("id") or s.get("url") or s.get("name")
            if sid in seen:
                continue
            seen.add(sid)
            news.setdefault(topic, []).append({
                "id": s.get("id"),
                "title": s.get("name") or s.get("title"),
                "hook": s.get("hook"),
                "summary": s.get("summary"),
                "url": s.get("url") or (f"https://x.com/i/trending/{s['id']}" if s.get("id") else None),
                "updated_at": s.get("updated_at"),
                "topics": (s.get("contexts") or {}).get("topics") or s.get("topics") or [],
                "category": s.get("category"),
            })
    for topic in news:
        news[topic].sort(key=lambda s: s.get("updated_at") or "", reverse=True)
    posts, seen_txt = [], set()
    for path in args.posts or []:
        d = load_loose(path)
        if isinstance(d, dict) and "posts" in d and "data" not in d:
            posts.extend(d["posts"])
            continue
        users = {u.get("id"): u for u in (d.get("includes") or {}).get("users", [])} if isinstance(d, dict) else {}
        rows = d.get("data") if isinstance(d, dict) else d
        for p in rows or []:
            if not isinstance(p, dict):
                continue
            metrics = p.get("public_metrics") or {}
            full = ((p.get("note_tweet") or {}).get("text")) or p.get("text") or ""
            text = clean_post(full)
            if len(text) < 25 or text[:80] in seen_txt or metrics.get("like_count", p.get("likes") or 0) < args.min_likes:
                continue
            seen_txt.add(text[:80])
            user = users.get(p.get("author_id"), {})
            truncated = not p.get("note_tweet") and len(p.get("text") or "") >= 270
            if truncated and not text.endswith(("…", ".", "!", "?")):
                text += "…"
            handle = user.get("username") or p.get("handle")
            posts.append({
                "id": p.get("id"),
                "text": text,
                "author": user.get("name") or p.get("author"),
                "handle": handle,
                "likes": metrics.get("like_count", p.get("likes") or 0),
                "reposts": metrics.get("retweet_count", p.get("reposts") or 0),
                "replies": metrics.get("reply_count", p.get("replies") or 0),
                "created_at": p.get("created_at"),
                "url": p.get("url") or (f"https://x.com/{handle or 'i'}/status/{p['id']}" if p.get("id") else None),
            })
    posts.sort(key=lambda p: (p.get("likes") or 0) + 3 * (p.get("reposts") or 0), reverse=True)
    out = {"updated_at": now(), "news": news, "posts": posts}
    write(data_path("x.json"), out)
    print("x:", {k: len(v) for k, v in news.items()}, "posts:", len(posts))

def _google_events(d):
    events = []
    for ev in d.get("events") or []:
        if ev.get("status") == "cancelled":
            continue
        me = next((a for a in ev.get("attendees") or [] if a.get("self")), None)
        if me and me.get("responseStatus") == "declined":
            continue
        start, end = ev.get("start") or {}, ev.get("end") or {}
        if isinstance(start, str):
            return None  # already normalized
        loc = (ev.get("location") or "").split(",")[0].strip()
        loc = re.sub(r"^[A-Za-z ]+-\d+-", "", loc)
        events.append({
            "title": ev.get("summary") or "(busy)",
            "start": start.get("dateTime") or start.get("date"),
            "end": end.get("dateTime") or end.get("date"),
            "all_day": "date" in start and "dateTime" not in start,
            "location": loc or None,
            "link": ev.get("htmlLink"),
            "video": ev.get("hangoutLink"),
            "tentative": bool(me and me.get("responseStatus") in ("tentative", "needsAction")),
        })
    events.sort(key=lambda x: x.get("start") or "")
    return {
        "updated_at": now(), "ok": True, "provider": "google",
        "calendar": d.get("summary"), "timeZone": d.get("timeZone"), "events": events,
    }

def _graph_events(d):
    events = []
    for ev in d.get("value") or []:
        if ev.get("isCancelled"):
            continue
        start = (ev.get("start") or {}).get("dateTime")
        end = (ev.get("end") or {}).get("dateTime")
        loc = ((ev.get("location") or {}).get("displayName")) or None
        events.append({
            "title": ev.get("subject") or "(busy)",
            "start": start, "end": end,
            "all_day": bool(ev.get("isAllDay")),
            "location": loc,
            "link": ev.get("webLink"),
            "video": None,
            "tentative": ev.get("showAs") == "tentative",
        })
    events.sort(key=lambda x: x.get("start") or "")
    return {"updated_at": now(), "ok": True, "provider": "outlook", "events": events}

def ingest_calendar(args):
    d = load_loose(args.file)
    if not isinstance(d, dict):
        raise SystemExit("calendar payload must be a JSON object")
    if isinstance(d.get("events"), list) and d["events"] and isinstance(d["events"][0].get("start"), str) and d["events"][0].get("title"):
        d["ok"] = d.get("ok", True)
        d["updated_at"] = d.get("updated_at") or now()
        write(data_path("calendar.json"), d)
        print("calendar.json:", len(d["events"]), "events (normalized)")
        return
    if isinstance(d.get("events"), list) and (not d["events"] or isinstance((d["events"][0].get("start") or {}), dict) or "summary" in (d["events"][0] if d["events"] else {})):
        out = _google_events(d)
    elif "value" in d:
        out = _graph_events(d)
    else:
        raise SystemExit("unrecognized calendar payload; write the normalized schema in docs/SCHEMAS.md instead")
    write(data_path("calendar.json"), out)
    print("calendar.json:", len(out["events"]), "events")

def mark_error(name, message):
    key = "events" if name == "calendar.json" else "messages"
    write(data_path(name), {"updated_at": now(), "ok": False, "error": message, key: []})

def _header(msg, name):
    for h in ((msg.get("payload") or {}).get("headers") or []):
        if (h.get("name") or "").lower() == name.lower():
            return h.get("value") or ""
    return ""

def _parse_from(value):
    m = re.match(r"\s*(.*?)\s*<([^>]+)>\s*$", value or "")
    if m:
        return m.group(1).strip('" ') or m.group(2), m.group(2)
    return value or "", ""

def _gmail_messages(rows):
    out = []
    for msg in rows:
        if not isinstance(msg, dict):
            continue
        if msg.get("subject") and not msg.get("payload"):
            out.append({
                "subject": msg.get("subject"),
                "from": msg.get("from"),
                "from_email": msg.get("from_email"),
                "snippet": msg.get("snippet"),
                "date": msg.get("date"),
                "link": msg.get("link"),
                "unread": msg.get("unread", True),
                "important": bool(msg.get("important")),
            })
            continue
        subject = _header(msg, "Subject") or "(no subject)"
        who, email = _parse_from(_header(msg, "From"))
        internal = msg.get("internalDate")
        date = None
        if internal:
            try:
                date = dt.datetime.fromtimestamp(int(internal) / 1000, dt.timezone.utc).isoformat()
            except Exception:
                date = None
        labels = msg.get("labelIds") or []
        out.append({
            "subject": subject,
            "from": who,
            "from_email": email or None,
            "snippet": msg.get("snippet"),
            "date": date,
            "link": f"https://mail.google.com/mail/u/0/#inbox/{msg['id']}" if msg.get("id") else None,
            "unread": "UNREAD" in labels or msg.get("unread", True),
            "important": "IMPORTANT" in labels or bool(msg.get("important")),
        })
    return out

def _graph_messages(rows):
    out = []
    for msg in rows:
        sender = ((msg.get("from") or {}).get("emailAddress") or {})
        out.append({
            "subject": msg.get("subject") or "(no subject)",
            "from": sender.get("name"),
            "from_email": sender.get("address"),
            "snippet": msg.get("bodyPreview"),
            "date": msg.get("receivedDateTime"),
            "link": msg.get("webLink"),
            "unread": not msg.get("isRead", False),
            "important": (msg.get("importance") or "").lower() == "high",
        })
    return out

def ingest_email(args):
    d = load_loose(args.file)
    if isinstance(d, list):
        rows, provider = d, "gmail"
        messages = _gmail_messages(rows)
    elif isinstance(d, dict) and isinstance(d.get("messages"), list):
        messages = _gmail_messages(d["messages"])
        provider = d.get("provider") or "gmail"
    elif isinstance(d, dict) and isinstance(d.get("value"), list):
        messages = _graph_messages(d["value"])
        provider = "outlook"
    else:
        raise SystemExit("unrecognized email payload; write the normalized schema in docs/SCHEMAS.md instead")
    messages.sort(key=lambda m: m.get("date") or "", reverse=True)
    write(data_path("email.json"), {"updated_at": now(), "ok": True, "provider": provider, "messages": messages})
    print("email.json:", len(messages), "messages")

def ingest_items(args):
    d = load_loose(args.file)
    rows = d.get("items") if isinstance(d, dict) else d
    if not isinstance(rows, list):
        raise SystemExit("items payload must be a list or {items: [...]}")
    items = []
    for it in rows:
        if not isinstance(it, dict):
            continue
        items.append({
            "title": it.get("title") or it.get("name") or "",
            "url": it.get("url") or it.get("link") or "",
            "summary": it.get("summary") or it.get("snippet") or it.get("description") or "",
            "source": it.get("source") or it.get("author") or "",
            "published": it.get("published") or it.get("date") or it.get("updated_at"),
        })
    sid = re.sub(r"[^A-Za-z0-9_-]+", "-", args.section_id).strip("-")
    if not sid:
        raise SystemExit("section id is empty")
    out = {"updated_at": now(), "ok": True, "items": items}
    write(data_path("sections") / f"{sid}.json", out)
    print(f"sections/{sid}.json:", len(items), "items")

def main(argv=None):
    ap = argparse.ArgumentParser(description="Normalize connector JSON into data/")
    sub = ap.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("x")
    x.add_argument("--news", nargs="*", help="topic:file pairs, e.g. ai:data/raw/ai.json")
    x.add_argument("--posts", nargs="*")
    x.add_argument("--normalized", help="file that is already in the x.json schema")
    x.add_argument("--min-likes", type=int, default=10)
    c = sub.add_parser("calendar")
    c.add_argument("file")
    ce = sub.add_parser("calendar-error")
    ce.add_argument("message")
    em = sub.add_parser("email")
    em.add_argument("file")
    ee = sub.add_parser("email-error")
    ee.add_argument("message")
    it = sub.add_parser("items")
    it.add_argument("section_id")
    it.add_argument("file")
    args = ap.parse_args(argv)
    if args.cmd == "x":
        ingest_x(args)
    elif args.cmd == "calendar":
        ingest_calendar(args)
    elif args.cmd == "calendar-error":
        mark_error("calendar.json", args.message)
    elif args.cmd == "email":
        ingest_email(args)
    elif args.cmd == "email-error":
        mark_error("email.json", args.message)
    elif args.cmd == "items":
        ingest_items(args)
    return 0

if __name__ == "__main__":
    sys.exit(main())
