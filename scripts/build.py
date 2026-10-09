#!/usr/bin/env python3
"""Render a static edition into dist/site from newsletter.config.json + data/*.json.

No network. No credentials. Section kinds are dispatched through RENDERERS and
SIDEBAR at the bottom of this file. To add a kind: document the JSON in
docs/SCHEMAS.md, write a renderer, and register it.
"""
import datetime as dt
import html
import json
import math
import re
import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

e = lambda s: html.escape(str(s if s is not None else ""), quote=True)
_REL = re.compile(r"^([+-])(\d+)([smhd])$")

def parse_ts(s, now):
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return dt.datetime.fromtimestamp(s, dt.timezone.utc)
    text = str(s).strip()
    m = _REL.match(text)
    if m:
        sign, n, unit = m.group(1), int(m.group(2)), m.group(3)
        delta = {"s": dt.timedelta(seconds=n), "m": dt.timedelta(minutes=n),
                 "h": dt.timedelta(hours=n), "d": dt.timedelta(days=n)}[unit]
        return now + delta if sign == "+" else now - delta
    try:
        d = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if d.tzinfo is None:
        return d.replace(tzinfo=now.tzinfo or dt.timezone.utc)
    return d

def href(url):
    u = str(url or "").strip()
    if u.startswith(("https://", "http://", "mailto:")):
        return e(u)
    return ""

def link(url, inner):
    h = href(url)
    return f'<a href="{h}">{inner}</a>' if h else inner

def clock(d):
    h = d.hour % 12 or 12
    return f"{h}:{d.minute:02d}{'a' if d.hour < 12 else 'p'}"

def fmt_stamp(d):
    if not d:
        return "never"
    h = d.hour % 12 or 12
    am = "AM" if d.hour < 12 else "PM"
    return d.strftime("%b ") + str(d.day) + f", {h}:{d.minute:02d} {am}"

def k(n):
    n = n or 0
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    if n >= 1e6:
        return f"{n/1e6:.1f}M"
    if n >= 1e4:
        return f"{n/1e3:.1f}K"
    return f"{int(n):,}"

def trunc(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0].rstrip(",;:")
    return (cut or s[:n]) + "…"

def meta(*parts):
    bits = [p for p in parts if p]
    if not bits:
        return ""
    return '<div class="meta">' + ' <span class="dot">·</span> '.join(bits) + '</div>'

def when(s, now):
    d = parse_ts(s, now)
    if not d:
        return ""
    mins = (now - d.astimezone(now.tzinfo)).total_seconds() / 60
    if mins < 1:
        label = "just now"
    elif mins < 60:
        label = f"{max(1, int(mins))}m ago"
    elif mins < 60 * 24:
        label = f"{int(mins // 60)}h ago"
    else:
        label = f"{int(mins // 1440)}d ago"
    attr = f' data-ts="{int(d.timestamp()*1000)}"'
    return f'<span class="ago"{attr}>{e(label)}</span>'

def moon_phase(d):
    synodic = 29.53058867
    ref = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)
    age = ((d - ref).total_seconds() / 86400) % synodic
    names = ["New moon", "Waxing crescent", "First quarter", "Waxing gibbous",
             "Full moon", "Waning gibbous", "Last quarter", "Waning crescent"]
    idx = int((age / synodic) * 8 + 0.5) % 8
    illum = (1 - math.cos(2 * math.pi * age / synodic)) / 2
    return names[idx], round(illum * 100)

def align_weather(w, today):
    """Shift a sample forecast so its first day lines up with today."""
    if not isinstance(w, dict):
        return w
    daily = w.get("daily") or {}
    days = daily.get("time") or []
    if not days or today.isoformat() in days:
        return w
    try:
        shift = (today - dt.date.fromisoformat(days[0])).days
    except Exception:
        return w
    if not shift:
        return w
    daily["time"] = [(dt.date.fromisoformat(t) + dt.timedelta(days=shift)).isoformat() for t in days]
    for key in ("sunrise", "sunset"):
        if key not in daily:
            continue
        shifted = []
        for s in daily[key]:
            try:
                shifted.append((dt.datetime.fromisoformat(s) + dt.timedelta(days=shift)).isoformat())
            except Exception:
                shifted.append(s)
        daily[key] = shifted
    return w

def weather_bits(W, now):
    if not W or "current" not in W or "daily" not in W:
        return None
    try:
        c, d = W["current"], W["daily"]
        txt = {str(k): v for k, v in common.WMO.items()}
        txt.update({str(k): v for k, v in (W.get("wmo_text") or {}).items()})
        i = 0
        today = now.date().isoformat()
        for j, day in enumerate(d.get("time") or []):
            if day == today:
                i = j
                break
        cond = txt.get(str(c.get("weather_code")), "fair")
        hi = round(d["temperature_2m_max"][i])
        lo = round(d["temperature_2m_min"][i])
        day_cond = txt.get(str(d["weather_code"][i]), cond)
        temp = round(c["temperature_2m"])
        rain = d.get("precipitation_probability_max", [None])[i]
        line = f"{cond} and {temp}°, high {hi}°, low {lo}°"
        if isinstance(rain, (int, float)) and rain >= 30:
            line += f", {int(rain)}% chance of rain"
        sr = dt.datetime.fromisoformat(d["sunrise"][i])
        ss = dt.datetime.fromisoformat(d["sunset"][i])
        dl = (d.get("daylight_duration") or [0])[i] / 3600
        fc = []
        times = d["time"]
        for j in range(i + 1, min(i + 4, len(times))):
            fc.append((
                dt.date.fromisoformat(times[j]).strftime("%a"),
                txt.get(str(d["weather_code"][j]), ""),
                round(d["temperature_2m_max"][j]),
                round(d["temperature_2m_min"][j]),
            ))
        uv = (d.get("uv_index_max") or [None])[i]
        return dict(
            line=line, cond=day_cond, hi=hi, lo=lo, sunrise=sr, sunset=ss,
            daylight=f"{int(dl)}h {int(round((dl % 1) * 60))}m",
            rain=int(rain) if isinstance(rain, (int, float)) else 0,
            uv=uv, forecast=fc, location=W.get("location") or "",
        )
    except Exception as ex:
        print(f"warning: weather data unusable ({ex})", file=sys.stderr)
        return None

def issue_number(cfg, today):
    raw = (cfg.get("paper") or {}).get("founded")
    if not raw:
        return 1
    try:
        founded = dt.date.fromisoformat(raw)
    except Exception:
        return 1
    n = (today - founded).days + 1
    return n if n > 0 else 1

def placement_of(sec):
    if sec.get("placement") in ("sidebar", "section"):
        return sec["placement"]
    if sec.get("kind") in ("calendar", "email"):
        return "sidebar"
    return "section"

def split_enabled(cfg):
    public = [s for s in (cfg.get("sections") or []) if not s.get("private")]
    private = [s for s in (cfg.get("sections") or []) if s.get("private") and s.get("enabled", True)]
    private += [s for s in (cfg.get("private_sections") or []) if s.get("enabled")]
    return public, private

class Edition:
    def __init__(self, cfg, data, now):
        self.cfg = cfg
        self.data = Path(data)
        self.now = now
        self.paper = cfg.get("paper") or {}
        self.feeds = common.jload(self.data / "feeds.json", {}) or {}
        self.x = common.jload(self.data / "x.json", {"news": {}, "posts": []}) or {"news": {}, "posts": []}
        self.weather = align_weather(common.jload(self.data / "weather.json", None), now.date())
        self.status = common.jload(self.data / "status.json", {}) or {}
        self.calendar = common.jload(self.data / "calendar.json", None)
        self.email = common.jload(self.data / "email.json", None)
        self.blobs = {}
        secdir = self.data / "sections"
        if secdir.is_dir():
            for p in sorted(secdir.glob("*.json")):
                self.blobs[p.stem] = common.jload(p, None)
        self.feed_names = {f["id"]: f.get("name") or f["id"] for f in cfg.get("feeds") or [] if f.get("id")}
        self.used = set()
        self.example = bool(
            (self.feeds or {}).get("_example") or (self.x or {}).get("_example")
            or any(isinstance(v, dict) and v.get("_example") for v in (self.feeds or {}).values() if isinstance(v, dict))
        )
        # Top-level _example on feeds.json, or the directory is the shipped sample.
        if (self.data / "README.md").exists() and (self.data.name == "sample"):
            self.example = True

    def blob(self, sec):
        rel = sec.get("data")
        if rel:
            return common.jload(self.data / rel, None)
        return self.blobs.get(sec.get("id"))

    def ts(self, s):
        return parse_ts(s, self.now)

    def when(self, s):
        return when(s, self.now)

    # ---------------------------------------------------------------- weather / almanac
    def almanac_box(self, wb):
        rows = []
        if wb:
            rows += [
                ("Sunrise", clock(wb["sunrise"])),
                ("Sunset", clock(wb["sunset"])),
                ("Daylight", wb["daylight"]),
                ("High / low", f'{wb["hi"]}° / {wb["lo"]}°'),
                ("Chance of rain", f'{wb["rain"]}%'),
                ("UV index", f'{wb["uv"]:.0f}' if isinstance(wb.get("uv"), (int, float)) else "—"),
            ]
        mp, il = moon_phase(self.now)
        rows.append(("Moon", f"{mp}, {il}%"))
        doy = self.now.timetuple().tm_yday
        y = self.now.year
        ylen = 366 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 365
        rows.append(("Day of year", f"{doy} of {ylen}"))
        h = '<section class="box" id="almanac"><h3 class="box-h">The Almanac</h3><ul class="rows">'
        h += "".join(f"<li><span>{e(a)}</span><span>{e(b)}</span></li>" for a, b in rows) + "</ul>"
        if wb and wb["forecast"]:
            h += '<div class="fc">' + "".join(
                f'<div class="fc-d"><div class="fc-n">{e(n)}</div><div class="fc-t">{hi}°<span>/{lo}°</span></div><div class="fc-c">{e(c)}</div></div>'
                for n, c, hi, lo in wb["forecast"]
            ) + "</div>"
        loc = (wb or {}).get("location") or (self.paper.get("location") or {}).get("name") or ""
        foot = f"{e(loc)} · Open-Meteo" if loc else "Open-Meteo"
        h += f'<div class="box-foot">{foot}</div></section>'
        return h

    def contents_box(self, sections):
        lis = "".join(
            f'<li><a href="#s-{e(s.get("id"))}">{e(s.get("title") or s.get("id"))}</a></li>'
            for s in sections
        )
        return f'<section class="box" id="contents"><h3 class="box-h">Inside Today</h3><ul class="toc">{lis}</ul></section>'

    def ev_row(self, ev, extra_cls=""):
        if ev.get("all_day") or not self.ts(ev.get("start")):
            t, attrs = "all day", ""
        else:
            s = self.ts(ev["start"]).astimezone(self.now.tzinfo)
            en = self.ts(ev.get("end"))
            t = clock(s)
            attrs = f' data-start="{int(s.timestamp()*1000)}"'
            if en:
                en = en.astimezone(self.now.tzinfo)
                attrs += f' data-end="{int(en.timestamp()*1000)}"'
                tip = f"{clock(s)}–{clock(en)}"
                if ev.get("location"):
                    tip += " · " + ev["location"]
                attrs += f' title="{e(tip)}"'
        loc = f'<span class="ev-loc">{e(ev.get("location"))}</span>' if ev.get("location") else ""
        cls = "ev" + (" tent" if ev.get("tentative") else "") + extra_cls
        inner = f'<span class="ev-title">{e(ev.get("title") or "(busy)")}{loc}</span><span class="ev-time">{e(t)}</span>'
        return f'<li class="{cls}"{attrs}>{link(ev.get("link"), inner)}</li>'

    def cal_days(self):
        cal = self.calendar
        if not isinstance(cal, dict) or cal.get("ok") is False:
            return None, None
        days = {}
        for ev in cal.get("events") or []:
            if ev.get("all_day"):
                try:
                    day = dt.date.fromisoformat(str(ev.get("start"))[:10])
                except Exception:
                    continue
            else:
                s = self.ts(ev.get("start"))
                if not s:
                    continue
                day = s.astimezone(self.now.tzinfo).date()
            if day < self.now.date():
                continue
            days.setdefault(day, []).append(ev)
        today = days.get(self.now.date(), [])
        ahead = {d: v for d, v in sorted(days.items()) if d > self.now.date()}
        return today, ahead

    def calendar_box(self, sec):
        title = sec.get("title") or "Your Day"
        today, ahead = self.cal_days()
        h = [f'<section class="box" id="box-{e(sec.get("id") or "calendar")}"><h3 class="box-h">{e(title)}</h3>']
        if today is None:
            h.append('<p class="empty">The calendar desk could not reach your calendar this morning.</p>')
        elif not today:
            h.append('<p class="empty">Nothing on the calendar today. An open day.</p>')
        else:
            h.append('<ul class="evs">' + "".join(self.ev_row(x) for x in today) + "</ul>")
        if ahead:
            n = sum(len(v) for v in ahead.values())
            h.append(f'<details class="ahead"><summary><span>Week ahead</span><span class="cnt">{n}</span></summary>')
            for d, evs in ahead.items():
                label = d.strftime("%A, %b ") + str(d.day)
                h.append(f'<div class="ahead-day">{e(label)}</div><ul class="evs">' + "".join(self.ev_row(x) for x in evs) + "</ul>")
            h.append("</details>")
        elif today is not None:
            h.append('<p class="empty small">Nothing scheduled for the rest of the week.</p>')
        updated = self.ts((self.calendar or {}).get("updated_at")) if isinstance(self.calendar, dict) else None
        if updated:
            h.append(f'<div class="box-foot">Synced {e(fmt_stamp(updated.astimezone(self.now.tzinfo)))}</div>')
        h.append("</section>")
        return "".join(h)

    def email_box(self, sec):
        title = sec.get("title") or "Correspondence"
        mail = self.email
        h = [f'<section class="box" id="box-{e(sec.get("id") or "email")}"><h3 class="box-h">{e(title)}</h3>']
        if not isinstance(mail, dict) or mail.get("ok") is False:
            h.append('<p class="empty">The correspondence desk could not reach your inbox this morning.</p>')
            messages = None
        else:
            messages = mail.get("messages") or []
            if not messages:
                h.append('<p class="empty">No unread letters worth setting in type.</p>')
            else:
                rows = []
                for m in messages[: sec.get("max", sec.get("show", 8))]:
                    who = m.get("from") or m.get("from_email") or ""
                    loc = f'<span class="ev-loc">{e(who)}</span>' if who else ""
                    sub = e(m.get("subject") or "(no subject)")
                    stamp = self.ts(m.get("date"))
                    t = clock(stamp.astimezone(self.now.tzinfo)) if stamp else ""
                    cls = "ev letter" + (" unread" if m.get("unread", True) else "")
                    inner = f'<span class="ev-title">{sub}{loc}</span><span class="ev-time">{e(t)}</span>'
                    rows.append(f'<li class="{cls}">{link(m.get("link"), inner)}</li>')
                h.append('<ul class="evs">' + "".join(rows) + "</ul>")
        updated = self.ts(mail.get("updated_at")) if isinstance(mail, dict) else None
        if updated:
            h.append(f'<div class="box-foot">Synced {e(fmt_stamp(updated.astimezone(self.now.tzinfo)))}</div>')
        h.append("</section>")
        return "".join(h)

    def items_box(self, sec):
        title = sec.get("title") or sec.get("id") or "Notes"
        blob = self.blob(sec)
        h = [f'<section class="box" id="box-{e(sec.get("id"))}"><h3 class="box-h">{e(title)}</h3>']
        items = None if not isinstance(blob, dict) or blob.get("ok") is False else (blob.get("items") or [])
        if items is None:
            h.append('<p class="empty">This desk did not file today.</p>')
        elif not items:
            h.append('<p class="empty">Nothing filed here today.</p>')
        else:
            rows = []
            for it in items[: sec.get("show", 8)]:
                loc = f'<span class="ev-loc">{e(it.get("source"))}</span>' if it.get("source") else ""
                inner = f'<span class="ev-title">{e(it.get("title") or "Untitled")}{loc}</span>'
                rows.append(f"<li class=\"ev\">{link(it.get('url'), inner)}</li>")
            h.append('<ul class="evs">' + "".join(rows) + "</ul>")
        h.append("</section>")
        return "".join(h)

    # ---------------------------------------------------------------- stories
    def feed_items(self, sec):
        out = []
        for fid in sec.get("feeds") or []:
            f = self.feeds.get(fid) or {}
            name = self.feed_names.get(fid, f.get("name") or fid)
            for it in (f.get("items") or [])[: sec.get("per_feed", 6)]:
                out.append(dict(it, source=name, fid=fid))
        if sec.get("kind") == "feeds" and len(sec.get("feeds") or []) > 1:
            floor = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
            out.sort(key=lambda x: self.ts(x.get("published")) or floor, reverse=True)
        return [x for x in out if x.get("url") not in self.used]

    def item_feed(self, it, i):
        summ = f'<p class="dek">{e(trunc(it.get("summary"), 220))}</p>' if i < 2 and it.get("summary") else ""
        extra = []
        fid = it.get("fid")
        if it.get("points") is not None and fid in ("lobsters", "hfpapers"):
            word = "upvotes" if fid == "hfpapers" else "points"
            extra.append(f'{it["points"]} {word}')
        if it.get("discuss") and it.get("comments") is not None:
            extra.append(link(it["discuss"], f'{it["comments"]} comments'))
        title = link(it.get("url"), e(it.get("title")))
        return (f'<h4 class="hl{" hl-lg" if i == 0 else ""}">{title}</h4>{summ}'
                + meta(f'via {e(it.get("source"))}', *extra, self.when(it.get("published"))))

    def item_hn(self, it, n):
        bits = [e(it.get("domain") or ""), f'{it.get("points") or 0} points']
        if it.get("discuss"):
            bits.append(link(it["discuss"], f'{it.get("comments") or 0} comments'))
        title = link(it.get("url"), e(it.get("title")))
        return (f'<div class="num">{n}</div><div><h4 class="hl">{title}</h4>'
                + meta(*bits, self.when(it.get("published"))) + "</div>")

    def item_xnews(self, it, i):
        hook = it.get("hook") or it.get("summary")
        dek = f'<p class="dek">{e(trunc(hook, 230))}</p>' if hook else ""
        topics = " & ".join((it.get("topics") or [])[:2])
        title = link(it.get("url"), e(it.get("title")))
        return (f'<h4 class="hl{" hl-lg" if i == 0 else ""}">{title}</h4>{dek}'
                + meta("on X", e(topics) if topics else "", self.when(it.get("updated_at") or it.get("published"))))

    def item_post(self, p):
        raw = re.sub(r"\s*https://t\.co/\w+", "", p.get("text") or "").strip()
        txt = e(trunc(raw, 420)).replace("\n\n", "<br><br>").replace("\n", " ")
        quote = link(p.get("url"), txt)
        who = f'<b>{e(p.get("author") or p.get("handle") or "")}</b>'
        if p.get("handle"):
            who += f' @{e(p["handle"])}'
        return (f'<blockquote class="post">{quote}</blockquote>'
                + meta(who, f'{k(p.get("likes"))} likes', f'{k(p.get("reposts"))} reposts', self.when(p.get("created_at"))))

    def rows_html(self, rows, show):
        if not rows:
            return '<p class="empty">No dispatches from this desk today.</p>'
        body = "<ol class=\"items\">" + "".join(
            f'<li class="item {c}{" extra" if i >= show else ""}">{r}</li>'
            for i, (c, r) in enumerate(rows)
        ) + "</ol>"
        if len(rows) > show:
            n = len(rows) - show
            body += f'<button class="more" data-n="{n}">{n} more</button>'
        return body

    def section_shell(self, sec, body, src=""):
        return (
            f'<section class="sec" id="s-{e(sec.get("id"))}" data-id="{e(sec.get("id"))}"><header class="sec-h">'
            f'<div class="kicker">{e(sec.get("kicker") or "")}</div>'
            f'<button class="fold" aria-label="Collapse section" title="Collapse / expand">−</button>'
            f'<h2 class="sec-t">{e(sec.get("title") or sec.get("id"))}</h2>{src}</header>'
            f'<div class="sec-b">{body}</div></section>'
        )

    def render_hn(self, sec):
        hn = (self.feeds.get("hn") or {}).get("items") or []
        items = [x for x in hn if x.get("url") not in self.used]
        start = len(hn) - len(items) + 1
        rows = [("hn-row", self.item_hn(it, start + i)) for i, it in enumerate(items)]
        rows = rows[: sec.get("max", 30)]
        return self.section_shell(sec, self.rows_html(rows, sec.get("show", 10)))

    def render_feeds(self, sec):
        items = self.feed_items(sec)[: sec.get("max", 20)]
        rows = [("", self.item_feed(it, i)) for i, it in enumerate(items)]
        present = []
        for fid in sec.get("feeds") or []:
            if fid in self.feeds and (self.feeds[fid].get("items")):
                present.append(self.feed_names.get(fid, fid))
        src = '<div class="srcs">' + " · ".join(e(n) for n in present) + "</div>" if present else ""
        return self.section_shell(sec, self.rows_html(rows, sec.get("show", 8)), src)

    def render_x_news(self, sec):
        topic = sec.get("topic")
        items = [x for x in ((self.x.get("news") or {}).get(topic) or []) if x.get("url") not in self.used]
        items = items[: sec.get("max", 15)]
        rows = [("", self.item_xnews(it, i)) for i, it in enumerate(items)]
        return self.section_shell(sec, self.rows_html(rows, sec.get("show", 5)))

    def render_x_posts(self, sec):
        per, items = {}, []
        cap = sec.get("per_handle", 3)
        for p in self.x.get("posts") or []:
            if not (p.get("text") or "").strip():
                continue
            handle = p.get("handle") or ""
            per[handle] = per.get(handle, 0) + 1
            if per[handle] <= cap:
                items.append(p)
        items = items[: sec.get("max", 20)]
        rows = [("", self.item_post(p)) for p in items]
        return self.section_shell(sec, self.rows_html(rows, sec.get("show", 6)))

    def render_items(self, sec):
        blob = self.blob(sec)
        if not isinstance(blob, dict) or blob.get("ok") is False:
            body = '<p class="empty">This desk did not file today.</p>'
            return self.section_shell(sec, body)
        items = blob.get("items") or []
        norm = []
        for it in items:
            if not isinstance(it, dict):
                continue
            norm.append(dict(it, source=it.get("source") or "", fid=sec.get("id")))
        norm = [x for x in norm if x.get("url") not in self.used][: sec.get("max", 20)]
        rows = [("", self.item_feed(it, i)) for i, it in enumerate(norm)]
        return self.section_shell(sec, self.rows_html(rows, sec.get("show", 8)))

    def render_calendar_section(self, sec):
        today, ahead = self.cal_days()
        if today is None:
            body = '<p class="empty">The calendar desk could not reach your calendar this morning.</p>'
        elif not today and not ahead:
            body = '<p class="empty">Nothing on the calendar. An open week.</p>'
        else:
            chunks = []
            if today:
                chunks.append('<ul class="evs">' + "".join(self.ev_row(x) for x in today) + "</ul>")
            for d, evs in (ahead or {}).items():
                label = d.strftime("%A, %b ") + str(d.day)
                chunks.append(f'<div class="ahead-day">{e(label)}</div><ul class="evs">' + "".join(self.ev_row(x) for x in evs) + "</ul>")
            body = "".join(chunks) or '<p class="empty">Nothing on the calendar today. An open day.</p>'
        return self.section_shell(sec, body)

    def render_email_section(self, sec):
        # Reuse the box markup inside a section so a correspondence column still looks like the paper.
        inner = self.email_box(sec)
        return self.section_shell(sec, inner)

    def render_sidebar(self, sec):
        kind = sec.get("kind")
        fn = SIDEBAR.get(kind)
        if not fn:
            print(f"warning: no sidebar renderer for kind {kind!r} ({sec.get('id')})", file=sys.stderr)
            return ""
        return fn(self, sec)

    def render_section(self, sec):
        kind = sec.get("kind")
        fn = RENDERERS.get(kind)
        if not fn:
            print(f"warning: unknown section kind {kind!r} on {sec.get('id')}; skipping", file=sys.stderr)
            return ""
        return fn(self, sec)

    # ---------------------------------------------------------------- front page
    def take_x_lead(self):
        front = self.cfg.get("front") or {}
        topic = front.get("lead_topic")
        if not topic:
            for s in self.cfg.get("sections") or []:
                if s.get("kind") == "x_news" and s.get("topic"):
                    topic = s["topic"]
                    break
        stories = (self.x.get("news") or {}).get(topic) or [] if topic else []
        if not stories:
            return None
        news = [x for x in stories if x.get("category") == "News" and x.get("url") not in self.used]
        pool = news or [x for x in stories if x.get("url") not in self.used]
        if not pool:
            return None
        lead = pool[0]
        self.used.add(lead.get("url"))
        return lead

    def first_unused_hn(self):
        for it in (self.feeds.get("hn") or {}).get("items") or []:
            if it.get("url") not in self.used:
                return it
        return None

    def first_unused_feed_item(self):
        for fid, f in self.feeds.items():
            if fid.startswith("_") or fid == "hn" or not isinstance(f, dict):
                continue
            for it in f.get("items") or []:
                if it.get("url") and it["url"] not in self.used:
                    return dict(it, source=self.feed_names.get(fid, f.get("name") or fid), fid=fid)
        return None

    def front_lead(self):
        lead = self.take_x_lead()
        if lead:
            para = ((lead.get("hook") or "") + (" " if lead.get("hook") and lead.get("summary") else "") + (lead.get("summary") or "")).strip()
            kicker = " · ".join((lead.get("topics") or [])[:2]) or "On X"
            article = (
                f'<article class="lead"><div class="kicker">{e(kicker)}</div>'
                f'<h2 class="lead-hl">{link(lead.get("url"), e(lead.get("title")))}</h2>'
                + (f'<p class="lead-p dropcap">{e(para)}</p>' if para else "")
                + meta("via X", "trending story", self.when(lead.get("updated_at")))
                + "</article>"
            )
        else:
            it = self.first_unused_hn()
            source = "Hacker News"
            if not it:
                it = self.first_unused_feed_item()
                source = (it or {}).get("source") or "The Wires"
            if not it:
                article = (
                    '<article class="lead"><div class="kicker">Front Page</div>'
                    '<h2 class="lead-hl">The wires are quiet this morning.</h2>'
                    '<p class="lead-p">Nothing has landed on the desk yet. Public sources may still be fetching, or this edition has no feeds turned on.</p></article>'
                )
            else:
                self.used.add(it.get("url"))
                para = it.get("summary") or ""
                bits = [f"via {e(source)}"]
                if it.get("points") is not None and source == "Hacker News":
                    bits.append(f'{it.get("points") or 0} points')
                if it.get("discuss"):
                    bits.append(link(it["discuss"], f'{it.get("comments") or 0} comments'))
                bits.append(self.when(it.get("published")))
                article = (
                    f'<article class="lead"><div class="kicker">{e(source)}</div>'
                    f'<h2 class="lead-hl">{link(it.get("url"), e(it.get("title")))}</h2>'
                    + (f'<p class="lead-p dropcap">{e(para)}</p>' if para else "")
                    + meta(*bits) + "</article>"
                )
        briefs = self.front_briefs()
        return article + briefs

    def front_briefs(self):
        front = self.cfg.get("front") or {}
        specs = front.get("brief_topics") or [
            {"topic": "business", "label": "Business"},
            {"topic": "coding", "label": "Coding"},
            {"topic": "tech", "label": "Technology"},
        ]
        picked = []
        for spec in specs:
            if isinstance(spec, (list, tuple)) and len(spec) == 2:
                topic, label = spec
            else:
                topic, label = spec.get("topic"), spec.get("label") or spec.get("topic")
            for s in (self.x.get("news") or {}).get(topic) or []:
                if s.get("url") and s["url"] not in self.used:
                    self.used.add(s["url"])
                    picked.append((label, s, "via X"))
                    break
        if not picked:
            # News-only editions still get the three-across row, from the wires.
            for fid in (front.get("wires") or [])[:3]:
                f = self.feeds.get(fid) or {}
                for it in f.get("items") or []:
                    if it.get("url") and it["url"] not in self.used:
                        self.used.add(it["url"])
                        name = self.feed_names.get(fid, f.get("name") or fid)
                        picked.append((name, it, "via " + e(name)))
                        break
        if not picked:
            return ""
        cards = []
        for label, s, via in picked:
            dek_src = s.get("hook") or s.get("summary") or ""
            dek = f'<p class="dek">{e(trunc(dek_src, 200))}</p>' if dek_src else ""
            stamp = s.get("updated_at") or s.get("published")
            cards.append(
                f'<article class="brief"><div class="kicker">{e(label)}</div>'
                f'<h3 class="hl hl-md">{link(s.get("url"), e(s.get("title")))}</h3>{dek}'
                + meta(via, self.when(stamp))
                + "</article>"
            )
        return '<div class="briefs">' + "".join(cards) + "</div>"

    def front_second(self):
        hn = [it for it in ((self.feeds.get("hn") or {}).get("items") or []) if it.get("url") not in self.used]
        parts = []
        if hn:
            top = hn[0]
            self.used.add(top.get("url"))
            parts.append(
                f'<article class="second"><div class="kicker">Technology</div>'
                f'<h2 class="second-hl">{link(top.get("url"), e(top.get("title")))}</h2>'
                + (f'<p class="second-p">{e(top.get("summary"))}</p>' if top.get("summary") else "")
                + meta("via Hacker News", f'{top.get("points") or 0} points',
                       link(top.get("discuss"), f'{top.get("comments") or 0} comments') if top.get("discuss") else "")
                + '</article><ul class="stack">'
            )
            for it in hn[1:5]:
                self.used.add(it.get("url"))
                parts.append(
                    f'<li><h3 class="hl hl-sm">{link(it.get("url"), e(it.get("title")))}</h3>'
                    + meta(e(it.get("domain") or ""), f'{it.get("points") or 0} points',
                           link(it.get("discuss"), f'{it.get("comments") or 0} comments') if it.get("discuss") else "")
                    + "</li>"
                )
            parts.append("</ul>")
        else:
            parts.append('<div class="kicker">Technology</div><p class="empty">Hacker News is quiet.</p>')
        wires = self.wires_block()
        if wires:
            parts.append(wires)
        return "".join(parts)

    def wires_block(self):
        ids = (self.cfg.get("front") or {}).get("wires") or []
        if not ids:
            ids = [f["id"] for f in (self.cfg.get("feeds") or []) if f.get("id") and f["id"] != "hn"][:4]
        lis = []
        for fid in ids:
            f = self.feeds.get(fid)
            if not isinstance(f, dict):
                continue
            it = next((x for x in (f.get("items") or []) if x.get("url") and x["url"] not in self.used), None)
            if not it:
                continue
            self.used.add(it["url"])
            name = self.feed_names.get(fid, f.get("name") or fid)
            dek = f'<p class="dek">{e(trunc(it.get("summary"), 170))}</p>' if it.get("summary") else ""
            lis.append(
                f'<li><h3 class="hl hl-sm">{link(it.get("url"), e(it.get("title")))}</h3>{dek}'
                + meta(f'via {e(name)}', self.when(it.get("published"))) + "</li>"
            )
        if not lis:
            return ""
        return '<div class="press"><div class="kicker">From the Wires</div><ul class="stack">' + "".join(lis) + "</ul></div>"

    def page(self, private):
        wb = weather_bits(self.weather, self.now)
        P = self.paper
        name = P.get("name") or "The Morning Tab"
        no = issue_number(self.cfg, self.now.date())
        vol = P.get("volume") or "I"
        reader = (P.get("reader") or "").strip()
        reader_html = f"<br><span>Printed for {e(reader)}</span>" if reader else ""
        search = P.get("search") or "https://www.google.com/search"
        if not str(search).startswith("https://"):
            search = "https://www.google.com/search"
        date_str = self.now.strftime("%A, %B ") + str(self.now.day) + self.now.strftime(", %Y")
        public, private_secs = split_enabled(self.cfg)
        side_secs, below = [], []
        for s in public + private_secs:
            (side_secs if placement_of(s) == "sidebar" else below).append(s)
        # Front page consumes stories first so sections don't repeat the lead.
        lead = self.front_lead()
        second = self.front_second()
        side = "".join(self.render_sidebar(s) for s in side_secs)
        side += self.almanac_box(wb) + self.contents_box(below)
        secs = "".join(self.render_section(s) for s in below)
        feeds_status = (self.status.get("feeds") or {}) if isinstance(self.status, dict) else {}
        ok = sum(1 for v in feeds_status.values() if isinstance(v, dict) and (v.get("ok") or v.get("stale")))
        tot = len(feeds_status)
        fu = self.ts(self.status.get("fetched_at")) if isinstance(self.status, dict) else None
        xu = self.ts(self.x.get("updated_at")) if isinstance(self.x, dict) else None
        cal_bit = ""
        if any(s.get("kind") == "calendar" for s in private_secs):
            cu = self.ts((self.calendar or {}).get("updated_at")) if isinstance(self.calendar, dict) else None
            cal_bit = " · Calendar " + e(fmt_stamp(cu.astimezone(self.now.tzinfo) if cu else None))
        css = int((common.SITE / "style.css").stat().st_mtime_ns) if (common.SITE / "style.css").exists() else 0
        robots = '<meta name="robots" content="noindex,nofollow">' if private else ""
        referrer = '<meta name="referrer" content="no-referrer">' if private else ""
        comment = "<!-- Preview built from example content in data/sample. Not a live edition. -->" if self.example else ""
        tzname = self.now.tzname() or ""
        weather_line = wb["line"] if wb else "no report"
        title = f"{name} — {self.now.strftime('%a %b ')}{self.now.day}"
        return f'''<!doctype html>
<html lang="en"><head>{comment}<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
{robots}{referrer}
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='10' fill='%23f3efe6'/%3E%3Ctext x='32' y='47' font-family='Georgia,serif' font-weight='700' font-size='44' text-anchor='middle' fill='%231b1a17'%3ET%3C/text%3E%3C/svg%3E">
<link rel="stylesheet" href="fonts/fonts.css"><link rel="stylesheet" href="style.css?v={css}">
</head><body><div class="paper">
<header class="mast">
  <div class="ears"><div class="ear l">No. {no} &nbsp;·&nbsp; Vol. {e(vol)}{reader_html}</div>
  <form class="ear r search" action="{e(search)}" method="get" role="search"><input name="q" placeholder="Search the wires…" aria-label="Search" autocomplete="off"><span class="kbd">/</span></form></div>
  <h1 class="title"><a href="./">{e(name)}</a></h1>
  <p class="tagline">“{e(P.get("tagline") or "")}”</p>
  <div class="dateline"><span>{e(date_str)}</span><span>{e(P.get("edition") or "Morning Edition")}</span><span>Weather desk: {e(weather_line)}</span></div>
</header>
<main class="front">
  <div class="col c1">{lead}</div>
  <div class="col c2">{second}</div>
  <aside class="col side">{side}</aside>
</main>
<div class="fold-rule"><span>The Rest of the Paper</span></div>
<div class="sections">{secs}</div>
<footer class="foot"><div>{e(name)} is set in Playfair Display &amp; Libre Caslon and printed on the Grok Bot press. No ads, no trackers.</div>
<div>Wires refreshed {e(fmt_stamp(fu.astimezone(self.now.tzinfo) if fu else None))} ({ok}/{tot} sources) · X desk {e(fmt_stamp(xu.astimezone(self.now.tzinfo) if xu else None))}{cal_bit} · Built {e(fmt_stamp(self.now))} {e(tzname)}</div></footer>
</div><script src="app.js?v={css}"></script></body></html>'''


# Extension point: register a new kind here. Sidebar kinds render a .box;
# everything else renders a below-the-fold .sec. `items` is the generic
# connector payload (data/sections/<id>.json) and is the easiest kind to add.
RENDERERS = {
    "hn": Edition.render_hn,
    "feeds": Edition.render_feeds,
    "x_news": Edition.render_x_news,
    "x_posts": Edition.render_x_posts,
    "items": Edition.render_items,
    "calendar": Edition.render_calendar_section,
    "email": Edition.render_email_section,
}
SIDEBAR = {
    "calendar": Edition.calendar_box,
    "email": Edition.email_box,
    "items": Edition.items_box,
}

BLANK = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="robots" content="noindex,nofollow"><title></title>'
    '<style>html,body{margin:0;background:#f3efe6;height:100%}</style>'
    '</head><body></body></html>\n'
)

def copy_assets(dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(common.SITE / "style.css", dest / "style.css")
    shutil.copy(common.SITE / "app.js", dest / "app.js")
    fonts = dest / "fonts"
    if fonts.exists():
        shutil.rmtree(fonts)
    shutil.copytree(common.SITE / "fonts", fonts)

def build_site(sample=False, config_path=None, data_path=None, now=None):
    cfg = common.load_config(config_path)
    for w in common.validate(cfg):
        print("warning:", w, file=sys.stderr)
    tzname = (cfg.get("paper") or {}).get("timezone") or "UTC"
    try:
        tz = ZoneInfo(tzname)
    except Exception as ex:
        raise SystemExit(f"unknown timezone {tzname!r} ({ex}). Use an IANA name like America/New_York.")
    now = now or dt.datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    data = Path(data_path) if data_path else common.data_dir(sample=sample)
    private_secs = common.enabled_private(cfg)
    private = bool(private_secs)
    key = common.ensure_secret() if private else None
    root = common.dist_root()
    site = root / "site"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    edition = Edition(cfg, data, now)
    html_page = edition.page(private)
    if private:
        page_dir = site / key
        copy_assets(page_dir)
        (page_dir / "index.html").write_text(html_page, encoding="utf-8")
        (site / "index.html").write_text(BLANK, encoding="utf-8")
        (site / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
        path = f"/{key}/"
    else:
        copy_assets(site)
        (site / "index.html").write_text(html_page, encoding="utf-8")
        (site / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
        path = "/"
    (site / ".nojekyll").write_text("", encoding="utf-8")
    publish = {
        "private": private,
        "path": path,
        "sample": bool(sample or edition.example),
        "built_at": now.isoformat(timespec="seconds"),
        "output": str(site),
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "publish.json").write_text(json.dumps(publish, indent=2) + "\n", encoding="utf-8")
    mode = "private" if private else "public"
    print(f"built {mode} edition -> {site}{path if path != '/' else '/index.html'}")
    if private:
        print(f"secret path: {path}  (stored in {common.secret_file()})")
        print("/ is a blank page. The path is the only protection; do not commit it or post it publicly.")
    return publish

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Build the static edition into dist/site")
    ap.add_argument("--sample", action="store_true", help="Render data/sample (no connectors, no network)")
    ap.add_argument("--config", help="Path to newsletter.config.json")
    ap.add_argument("--data", help="Directory of feeds.json, x.json, and section files")
    args = ap.parse_args(argv)
    build_site(sample=args.sample, config_path=args.config, data_path=args.data)

if __name__ == "__main__":
    main()
