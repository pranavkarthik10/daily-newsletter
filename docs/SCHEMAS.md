# Connector data schemas

The build never calls a connector. It reads JSON from `data/` and renders it. Write these files yourself, or let `scripts/ingest.py` reshape a raw connector response into them.

Unknown keys are ignored. Times are ISO-8601 (`2026-10-09T15:00:00-04:00` or `...Z`). The sample edition also accepts relative times (`-5m`, `-2h`, `+1d`) so a preview stays current; ingest always writes ISO-8601.

If a file is missing, or `"ok": false`, the section shows an empty state and the rest of the paper still builds.

## `data/x.json`

One file for every X section. `x_news` sections read `news.<topic>`. `x_posts` sections read `posts`.

```json
{
  "updated_at": "2026-10-09T14:00:00Z",
  "news": {
    "ai": [
      {
        "title": "Headline",
        "url": "https://example.com/story",
        "hook": "One sentence, optional.",
        "summary": "The deck, optional.",
        "updated_at": "2026-10-09T13:00:00Z",
        "topics": ["Technology", "AI"],
        "category": "News"
      }
    ]
  },
  "posts": [
    {
      "text": "The post text.",
      "author": "Display Name",
      "handle": "username",
      "likes": 120,
      "reposts": 10,
      "replies": 3,
      "created_at": "2026-10-09T12:00:00Z",
      "url": "https://x.com/username/status/1"
    }
  ]
}
```

`category: "News"` is preferred for the front-page lead (the first `x_news` section's topic, or `front.lead_topic`). Other categories still appear in the section.

Raw X connector responses (a `data` array of stories, or a posts search with `includes.users`) can be passed to:

```
python3 scripts/ingest.py x --news ai:raw_ai.json coding:raw_code.json --posts raw_posts.json
```

Story objects may use `name` instead of `title`. Posts may be the v2 search shape (`public_metrics`, `note_tweet`, `author_id`). `--min-likes` defaults to 10.

## `data/calendar.json`

Sidebar box when a `calendar` section is enabled. Google Calendar and Outlook both normalize to this.

```json
{
  "updated_at": "2026-10-09T14:00:00Z",
  "ok": true,
  "provider": "google",
  "calendar": "Primary",
  "timeZone": "America/New_York",
  "events": [
    {
      "title": "Design review",
      "start": "2026-10-09T10:00:00-04:00",
      "end": "2026-10-09T11:00:00-04:00",
      "all_day": false,
      "location": "Studio",
      "link": "https://calendar.google.com/event?eid=example",
      "video": null,
      "tentative": false
    }
  ]
}
```

All-day events use `YYYY-MM-DD` in `start` and `"all_day": true`.

`scripts/ingest.py calendar raw.json` accepts:

- this normalized shape
- a Google Calendar `events.list` / connector payload (`events[].summary`, `start.dateTime` or `start.date`, `htmlLink`, attendees with `self`)
- a Microsoft Graph calendar list (`value[].subject`, `start.dateTime`, `webLink`, `isAllDay`)

Cancelled events and events the reader declined are dropped. On connector failure:

```
python3 scripts/ingest.py calendar-error "connector unavailable"
```

## `data/email.json`

Sidebar box when an `email` section is enabled. Subjects and senders only; do not put message bodies in the page.

```json
{
  "updated_at": "2026-10-09T14:00:00Z",
  "ok": true,
  "provider": "gmail",
  "messages": [
    {
      "subject": "The proofs are in",
      "from": "Ada Lovelace",
      "from_email": "ada@example.com",
      "snippet": "Short preview, optional. Not required for the box.",
      "date": "2026-10-09T09:14:00-04:00",
      "link": "https://mail.google.com/mail/u/0/#inbox/abc",
      "unread": true,
      "important": true
    }
  ]
}
```

`scripts/ingest.py email raw.json` accepts this shape, a Gmail `messages` array (`payload.headers` for Subject and From, `snippet`, `internalDate`, `labelIds`), or a Graph mail list (`value[].subject`, `from.emailAddress`, `bodyPreview`, `receivedDateTime`, `isRead`).

```
python3 scripts/ingest.py email-error "connector unavailable"
```

## `data/sections/<id>.json`

Generic **items** section. This is the extension point: any connector can file a list of links. Point the section's `data` field at the file (default `sections/<id>.json`).

```json
{
  "updated_at": "2026-10-09T14:00:00Z",
  "ok": true,
  "items": [
    {
      "title": "A saved link",
      "url": "https://example.com/post",
      "summary": "Optional deck.",
      "source": "Optional source name",
      "published": "2026-10-09T08:00:00Z"
    }
  ]
}
```

`placement` on the section is `"section"` (below the fold, default) or `"sidebar"` (a small box).

```
python3 scripts/ingest.py items notebook raw.json
```

`raw.json` may be the object above or a bare list of `{title, url, summary, source, published}`. `name` is accepted as `title`, `link` as `url`.

## `data/feeds.json` and `data/weather.json`

Written by `scripts/fetch.py`. You do not author these by hand unless you are making sample data.

`feeds.json` maps a feed id to `{name, items: [{title, url, summary, published, domain, points, comments, discuss}]}`.

`weather.json` is an Open-Meteo forecast plus `location` and `wmo_text`. `status.json` records which fetches succeeded. A failed feed keeps the previous good copy and is marked `stale`.

## Adding a kind

Prefer an `items` section. A new kind is a renderer in `scripts/build.py`:

1. Document the JSON here.
2. Write a function on `Edition` that returns HTML.
3. Register it in `RENDERERS` (below the fold) and, if it is a box, in `SIDEBAR`.

Kinds shipped today: `hn`, `feeds`, `x_news`, `x_posts`, `items`, `calendar`, `email`.
