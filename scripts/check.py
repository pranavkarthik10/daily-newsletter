#!/usr/bin/env python3
"""Offline checks: sample edition, secret path, and connector ingest. No network."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import build
import ingest

ROOT = common.ROOT
# Split so the source tree does not contain the personal strings this template must not ship.
BANNED = ("Pra" "nav", "3vxykRG13" "IXq", "Stand" "up", "Post" "mortem", "morning-tab-" "delta", "ping" "gy")

def fail(msg):
    print("FAIL", msg, file=sys.stderr)
    raise SystemExit(1)

def main():
    tmp = Path(tempfile.mkdtemp(prefix="daily-newsletter-check-"))
    try:
        os.environ.pop("NEWSLETTER_DATA", None)
        os.environ.pop("NEWSLETTER_CONFIG", None)
        os.environ["NEWSLETTER_DIST"] = str(tmp / "dist-public")
        secret = tmp / "secret"
        os.environ["NEWSLETTER_SECRET_FILE"] = str(secret)
        publish = build.build_site(sample=True)
        if publish.get("private"):
            fail("sample config should be a public edition")
        if secret.exists():
            fail("public build created a secret file")
        index = Path(publish["output"]) / "index.html"
        text = index.read_text(encoding="utf-8")
        for needle in ("The Morning Tab", "Executives at OpenAI", "Cloudflare acquires", "Printed for Reader", "The Almanac", "Inside Today"):
            if needle not in text:
                fail(f"sample page missing {needle!r}")
        if "noindex" in text:
            fail("public sample page should be indexable")
        if "example content" not in text:
            fail("sample page should be marked as example content")
        for word in BANNED:
            if word in text:
                fail(f"sample page contains {word!r}")
        # Private edition: blank root, paper only under the secret path, stable key.
        cfg = json.loads((ROOT / "newsletter.config.json").read_text(encoding="utf-8"))
        for sec in cfg.get("private_sections") or []:
            if sec.get("id") in ("calendar", "email"):
                sec["enabled"] = True
        data = tmp / "data"
        shutil.copytree(ROOT / "data" / "sample", data)
        (data / "email.json").write_text(json.dumps({
            "updated_at": "-5m", "ok": True, "provider": "gmail",
            "messages": [{
                "subject": "Example: Galley proofs",
                "from": "Ada Example",
                "from_email": "ada@example.com",
                "snippet": "The morning galleys are ready.",
                "date": "-20m",
                "link": "https://example.com/mail/1",
                "unread": True,
                "important": True,
            }],
        }), encoding="utf-8")
        (data / "calendar.json").write_text(json.dumps({
            "updated_at": "-5m", "ok": True, "provider": "google",
            "events": [{
                "title": "Example: Design review",
                "start": "-30m",
                "end": "-5m",
                "all_day": False,
                "location": "Studio",
                "link": "https://example.com/cal/1",
                "tentative": False,
            }],
        }), encoding="utf-8")
        cfg_path = tmp / "private.config.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        os.environ["NEWSLETTER_CONFIG"] = str(cfg_path)
        os.environ["NEWSLETTER_DATA"] = str(data)
        os.environ["NEWSLETTER_DIST"] = str(tmp / "dist-private")
        pub1 = build.build_site(sample=False, config_path=cfg_path, data_path=data)
        pub2 = build.build_site(sample=False, config_path=cfg_path, data_path=data)
        if pub1["path"] != pub2["path"] or not pub1.get("private"):
            fail("secret path was not stable")
        site = Path(pub1["output"])
        root_html = (site / "index.html").read_text(encoding="utf-8")
        if "Example: Galley proofs" in root_html or "Design review" in root_html:
            fail("private content leaked onto /")
        if "noindex" not in root_html:
            fail("blank root should be noindex")
        key = pub1["path"].strip("/")
        secret_html = (site / key / "index.html").read_text(encoding="utf-8")
        for needle in ("Example: Galley proofs", "Example: Design review", "noindex", "Correspondence", "Your Day"):
            if needle not in secret_html:
                fail(f"private page missing {needle!r}")
        robots = (site / "robots.txt").read_text(encoding="utf-8")
        if "Disallow: /" not in robots:
            fail("private robots.txt should disallow /")
        # Ingest raw connector shapes into a throwaway data dir.
        os.environ["NEWSLETTER_DATA"] = str(tmp / "ingested")
        raw_cal = tmp / "raw_cal.json"
        raw_cal.write_text(json.dumps({
            "summary": "Primary",
            "timeZone": "America/New_York",
            "events": [{
                "summary": "Example: Press check",
                "status": "confirmed",
                "start": {"dateTime": "2026-10-09T15:00:00-04:00"},
                "end": {"dateTime": "2026-10-09T15:30:00-04:00"},
                "location": "Newsroom",
                "htmlLink": "https://example.com/cal/2",
                "attendees": [{"self": True, "responseStatus": "accepted"}],
            }],
        }), encoding="utf-8")
        raw_mail = tmp / "raw_mail.json"
        raw_mail.write_text(json.dumps({"messages": [{
            "id": "abc",
            "snippet": "See you at the desk.",
            "internalDate": "1760000000000",
            "labelIds": ["UNREAD", "IMPORTANT"],
            "payload": {"headers": [
                {"name": "Subject", "value": "Example: Desk note"},
                {"name": "From", "value": "News Editor <editor@example.com>"},
            ]},
        }]}), encoding="utf-8")
        raw_x = tmp / "raw_x.json"
        raw_x.write_text(json.dumps({"data": [{
            "id": "1", "name": "Example headline", "hook": "A hook.",
            "summary": "A summary.", "url": "https://example.com/x/1",
            "updated_at": "2026-10-09T12:00:00Z",
            "category": "News", "contexts": {"topics": ["Technology"]},
        }]}), encoding="utf-8")
        raw_posts = tmp / "raw_posts.json"
        raw_posts.write_text(json.dumps({
            "includes": {"users": [{"id": "u1", "name": "Sample Voice", "username": "samplevoice"}]},
            "data": [{
                "id": "99", "author_id": "u1", "text": "This is an example post long enough to keep.",
                "created_at": "2026-10-09T12:00:00Z",
                "public_metrics": {"like_count": 40, "retweet_count": 2, "reply_count": 1},
            }],
        }), encoding="utf-8")
        ingest.main(["calendar", str(raw_cal)])
        ingest.main(["email", str(raw_mail)])
        ingest.main(["x", "--news", f"ai:{raw_x}", "--posts", str(raw_posts), "--min-likes", "10"])
        (tmp / "items.json").write_text(json.dumps([
            {"title": "Example note", "url": "https://example.com/n", "summary": "A note."}
        ]), encoding="utf-8")
        ingest.main(["items", "notebook", str(tmp / "items.json")])
        ingested = Path(os.environ["NEWSLETTER_DATA"])
        cal = json.loads((ingested / "calendar.json").read_text())
        if cal["events"][0]["title"] != "Example: Press check" or not cal["ok"]:
            fail("calendar ingest")
        mail = json.loads((ingested / "email.json").read_text())
        if mail["messages"][0]["subject"] != "Example: Desk note" or mail["messages"][0]["from"] != "News Editor":
            fail("email ingest")
        x = json.loads((ingested / "x.json").read_text())
        if not x["news"]["ai"] or x["posts"][0]["handle"] != "samplevoice":
            fail("x ingest")
        notes = json.loads((ingested / "sections" / "notebook.json").read_text())
        if notes["items"][0]["title"] != "Example note":
            fail("items ingest")
        # Vercel pack of the private build uses two $file substitutions and a blank root.
        os.environ["NEWSLETTER_DIST"] = str(tmp / "dist-private")
        os.environ["NEWSLETTER_CONFIG"] = str(cfg_path)
        import deploy_vercel
        args_path = deploy_vercel.pack(cfg)
        packed = json.loads(args_path.read_text())
        files = packed["requestBody"]["files"]
        names = [f["file"] for f in files]
        if "index.html" not in names or not any(n.endswith("/index.html") and n != "index.html" for n in names):
            fail(f"vercel pack paths unexpected: {names}")
        if "teamId" in packed or "teamId" in packed["requestBody"]:
            fail("vercel args include teamId")
        file_subs = [f for f in files if str(f.get("data", "")).startswith("$file:")]
        if len(file_subs) > 4:
            fail("too many $file substitutions")
        blank = next(f for f in files if f["file"] == "index.html")
        if "Galley" in blank["data"]:
            fail("vercel root file contains private content")
        print("ok")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        os.environ.pop("NEWSLETTER_DIST", None)
        os.environ.pop("NEWSLETTER_DATA", None)
        os.environ.pop("NEWSLETTER_CONFIG", None)
        os.environ.pop("NEWSLETTER_SECRET_FILE", None)

if __name__ == "__main__":
    main()
