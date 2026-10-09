# Bot setup

You are a Grok Bot setting up a personal morning paper from this repo. Read this file and follow it. Talk to the reader in plain language. Do the work yourself: write the config, run the scripts, call connectors, deploy. Do not ask them to edit JSON.

The paper is a static site. You fetch public sources, write connector JSON, build, and deploy. There is no GitHub Action to wire up.

## First conversation

Ask **one question at a time**. Offer a suggestion, accept a short answer, then go on. Skip ahead if they already answered.

1. **Name.** What should the masthead say? Suggest **The Morning Tab**.
2. **Tagline.** Suggest **All the news that fits your history.**
3. **Reader line.** The corner says “Printed for ___.” Ask what name to print. Suggest their first name. This is a label, not a login.
4. **City.** Where is the weather desk? Run `python3 scripts/geocode.py "City"` and confirm the place, latitude, longitude, and timezone before writing them into `paper.location` and `paper.timezone`.
5. **Interests.** Read `config/catalog.json`. Name the groups (AI, technology, coding, startups, markets, science, design, security, world news) and ask which ones they want. They can say “the demo” to keep the default tech paper.
6. **Sources.** Start with X and the news wires. For each chosen interest, offer two or three feeds from the catalog (name and one-line description, not a wall of URLs). Always offer Hacker News if they want a front page. Turn on an `x_news` section per topic they care about, using that group's `x_queries`, and one `x_posts` section if they want voices. Use the group's `x_accounts` as the default list; let them add or drop handles. Confirm before you enable a long list.
7. **Private sections, off unless they ask.** Ask if they want any of these on the paper:
   - **Calendar** (“Your Day”): Google Calendar or Outlook.
   - **Email** (“Correspondence”): important unread subjects from Gmail or Outlook. Subjects and senders only.
   - **Anything else** (notes, reading list, a ticket queue): an `items` section. Copy the disabled `notebook` entry in `private_sections`.
   For each yes, check the connector with a trivial read (list calendars, or fetch one recent message, or a one-result X search). If it is not connected, say so, leave that section `enabled: false`, and tell them where to connect it. Do not enable a section you could not read.
8. **Where it should live.** Offer four choices, with the credential in the same breath:
   - **Vercel** — the Vercel connector. You will create the project if needed and deploy with `create_deployment`. No token file.
   - **Cloudflare Pages** — they set `CLOUDFLARE_API_TOKEN` (Pages: Edit) and `CLOUDFLARE_ACCOUNT_ID`. Wrangler is the alternative.
   - **GitHub Pages** — git push to a `gh-pages` branch on a repo they choose. If any private section is on, the repo must be **private**.
   - **Just the folder** — you build `dist/site` and they upload it, or you stop there.
   If a private section is on, recommend Vercel or Cloudflare. Say plainly that GitHub Pages on a public repo would publish the secret path.
9. **What time** in the morning, in their timezone. Suggest 6:30. Store it as `routine.time`. `paper.timezone` is the clock.

Then stop asking and build.

## Install, configure, build, deploy

Clone into their workspace (a fork is optional; a local copy is enough):

```
git clone https://github.com/pranavkarthik10/daily-newsletter.git ~/daily-newsletter
cd ~/daily-newsletter
```

If they want their own git history, create a **new** repo and point `origin` at it. Keep this template as `upstream` if you like. If any private section is enabled, that repo must be private. Do not commit `data/` (except you won't have sample changes), `.secret_path`, or `dist/`.

Write `newsletter.config.json`:

- `paper`: name, tagline, reader, timezone, location, `founded` set to today's date, `edition` “Morning Edition”.
- `feeds`: only what they chose. Copy objects from `config/catalog.json` or keep defaults they liked.
- `sections`: one block per desk. `kind` is `hn`, `feeds`, `x_news`, `x_posts`, or `items`. Match the shapes already in the file.
- `private_sections`: leave entries in the file. Set `enabled` true only for the ones they asked for and you could read.
- `deploy.target`: `vercel`, `cloudflare`, `github-pages`, or `static`. `deploy.project_name`: a slug such as `daily-newsletter`.
- `front.wires`: three or four feed ids for the “From the Wires” column. `front.brief_topics`: up to three `{topic, label}` pairs for the strip under the lead.

Show them a local preview before the first deploy if a browser is handy:

```
python3 scripts/preview.py
```

That serves the **example** edition at `http://127.0.0.1:8787/`. Then build theirs:

```
python3 scripts/fetch.py
```

Fetch exits 0 if at least one public source worked. A dead feed is kept from the previous copy when there is one, and listed as `ERR` or `STALE`. Don't fail the whole morning for one feed.

Write connector files (schemas in `docs/SCHEMAS.md`):

- X: for each enabled `x_news` section, search news with its `queries` (a day or two back). For `x_posts`, search those accounts, exclude replies and reposts, last 48 hours. Normalize with `scripts/ingest.py x --news topic:file --posts file`, or write `data/x.json` directly. Do not invent headlines.
- Calendar, if enabled: events from today through eight days. `scripts/ingest.py calendar raw.json`. On failure: `scripts/ingest.py calendar-error "connector unavailable"`.
- Email, if enabled: important unread messages, a short list. `scripts/ingest.py email raw.json`. On failure: `scripts/ingest.py email-error "..."`.
- Other `items` sections: `data/sections/<id>.json`.

```
python3 scripts/build.py
python3 scripts/deploy.py --pack
```

Then publish:

- **Vercel.** Create the project if needed, with SSO / password protection off, or the reader cannot open the page. Call `create_deployment` with the JSON in `dist/vercel/deploy_args.json`. Do not pass `teamId`.
- **Cloudflare.** Export the token and account id, run `python3 scripts/deploy_cloudflare.py`. Or `npx wrangler pages deploy dist/site --project-name <slug>`.
- **GitHub Pages.** `python3 scripts/deploy_github_pages.py`. It force-updates only the pages branch.
- **Static.** Give them `dist/site` and `docs/DEPLOY.md`.

Verify: open the URL and check the masthead date is today. A private edition's `/` is a blank cream page; the paper is only at `/<secret>/` (printed by the build, also in `.secret_path`). Tell them the URL once, in a private channel.

Details per host: `docs/DEPLOY.md`.

## Daily routine

Register a routine at `routine.time` in `paper.timezone`. Use this intent, with the path, time, and target filled in. Do not freeze tool names or arguments; call whatever connectors are actually available that morning.

```
Each morning at {time} ({timezone}), refresh the paper in {checkout}:

1. Run python3 scripts/fetch.py. If one feed fails, continue.
2. For each enabled X section, pull fresh news and posts with the X connector
   using the queries and accounts in newsletter.config.json. Write data/x.json
   (docs/SCHEMAS.md). Do not invent stories. If X is down, keep yesterday's
   data/x.json and note it locally.
3. If calendar is enabled, list events from today through eight days and
   write data/calendar.json. If the connector fails, run
   scripts/ingest.py calendar-error and continue.
4. If email is enabled, write important unread subjects to data/email.json.
   If it fails, run scripts/ingest.py email-error and continue.
5. Refresh any other enabled items section into data/sections/<id>.json.
6. Run python3 scripts/build.py, then pack and publish with the configured
   target (Vercel connector create_deployment using dist/vercel/deploy_args.json,
   scripts/deploy_cloudflare.py, or scripts/deploy_github_pages.py).
7. Open the live URL and confirm the masthead shows today's date.
8. Message the reader only if the build or deploy failed, or a private
   connector failed. Stay quiet when the edition goes out.

Do not commit data/, dist/, or .secret_path. Do not paste the secret path
into a shared or public channel.
```

`python3 scripts/prepare.py` does steps 1 and the build/pack. It does not call connectors or Vercel. You still do those.

## Later changes

When they ask to add or drop something, edit `newsletter.config.json` and rebuild. Don't make them do it.

- **Add a feed.** Copy the object from `config/catalog.json` into `feeds` (or invent one: `id`, `name`, `type` of `rss`, `hn`, `lobsters`, `hf_papers`, or `json`, and `url`). Add the id to a section's `feeds`, or add a section (`kind` `feeds`, plus `kicker`, `title`, `show`, `max`). Fetch, build, deploy.
- **Remove a feed or section.** Delete it from the config. A section with no items renders an empty state; deleting it is cleaner. Rebuild and deploy.
- **Turn on a private section.** Confirm the connector, set `enabled` true, write its JSON, build. The paper **moves** off `/` onto `/<secret>/` and `/` becomes blank. Tell them the new URL once, in private. The old public URL is no longer the paper.
- **Turn the last private section off.** The next build serves the paper at `/` again. The secret file stays on disk, unused, until a private section is enabled again.
- **New section type.** Add a `private_sections` (or `sections`) object with `kind` `items`, a new `id`, and `data` `sections/<id>.json`. You only need a new renderer in `scripts/build.py` if a list of links is not enough. Document any new JSON in `docs/SCHEMAS.md`.

## Privacy

- News-only papers are served at `/` and may be indexed.
- If **any** private section is enabled (calendar, email, an items section fed from their accounts, or any section with `"private": true`), the build publishes only under a random path. The path is generated once, stored in `.secret_path`, and reused. `/` is a blank page. The HTML is `noindex`. `robots.txt` disallows everything.
- The path is the only protection. There is no password. Anyone with the URL can read calendar titles and email subjects. Say that to the reader when you hand it over.
- Never commit `data/`, `dist/`, `.secret_path`, or raw connector output. Never put the secret path in a public repo, a public chat, a screenshot you will post, or the daily success message.
- Do not enable GitHub Pages for a private edition on a public repository.
- Losing `.secret_path` mints a new path on the next private build. The previous URL stops working. Don't delete the file unless they ask to rotate it.
