# Deploy targets

`python3 scripts/build.py` writes a plain static site to `dist/site/`. That folder is the edition. `dist/publish.json` (outside the site folder) records whether it is public (`/`) or private (`/<secret>/`). Do not upload `dist/publish.json` or `.secret_path`.

`python3 scripts/deploy.py --pack` writes the helper for `deploy.target` in `newsletter.config.json`. `python3 scripts/prepare.py` fetches, builds, and packs. Add `--publish` to actually publish Cloudflare or GitHub Pages.

| Target | `deploy.target` | What the bot needs |
| --- | --- | --- |
| Any static host | `static` | Nothing. Upload `dist/site`. |
| Vercel | `vercel` | The Vercel connector. No token in the repo. |
| Cloudflare Pages or Workers | `cloudflare` | `CLOUDFLARE_API_TOKEN` (Pages: Edit) and `CLOUDFLARE_ACCOUNT_ID`, or Wrangler logged in with that token. |
| GitHub Pages | `github-pages` | Git credentials that can push, and `gh` if you want Pages turned on for you. |

`deploy.project_name` (default `daily-newsletter`) is the Vercel project, the Cloudflare project, and the slug used in docs. It is lowercased.

## Any static host

Upload the **contents** of `dist/site/` to the web root (S3, Netlify Drop, nginx, a bucket). `python3 scripts/deploy.py --pack` writes `dist/STATIC_HOST.txt` with the same note.

Turn off directory listings. On a private edition the secret is the directory name; an index of `/` would reveal it. The paper uses relative links, so it works at `/` or at `/<secret>/`.

## Vercel

The connector deploys; this repo only packs the arguments.

1. Create a project named `deploy.project_name` if it does not exist. Turn off Vercel Authentication / SSO protection (`ssoProtection` null, no password protection). Otherwise the reader needs a Vercel login to open their own paper.
2. `python3 scripts/deploy_vercel.py` writes `dist/vercel/deploy_args.json`.
3. Call the Vercel connector **`create_deployment`** with that JSON as the arguments. Do not add `teamId`; the connection's default account is the right one, and an explicit team id is rejected. Two files are passed as `$file:` paths (the inlined page and the fonts). The connector fills those in.
4. `target` is `production`, so the production alias moves to the new deployment. A failed deploy leaves the previous one up.
5. Verify the production URL. Public edition: `https://<project>.vercel.app/` contains today's masthead date. Private edition: `/` is a blank cream page, and the paper is at `https://<project>.vercel.app/<secret>/`.

No install or build command runs on Vercel. The pack inlines CSS, JS, and the Latin fonts so the call stays small.

## Cloudflare Pages and Workers

`python3 scripts/deploy_cloudflare.py --pack` writes `dist/cloudflare/wrangler.toml` and a short README. The site it uploads is `dist/site`.

**Pages, direct API** (stdlib, no Wrangler):

```
export CLOUDFLARE_API_TOKEN=...    # Cloudflare Pages: Edit
export CLOUDFLARE_ACCOUNT_ID=...
python3 scripts/deploy_cloudflare.py
```

The script creates the Pages project if needed and uploads a deployment. It does not print the token.

**Pages, Wrangler** (the token can come from `wrangler login` or the same env var):

```
npx wrangler pages deploy dist/site --project-name daily-newsletter
```

**Workers static assets**, from `dist/cloudflare`:

```
npx wrangler deploy
```

The toml there points `[assets].directory` at `../site`. Use whichever of Pages or Workers you already have; both serve the same folder. Pages is the one the script uploads itself.

Verify the `pages.dev` or workers.dev URL the same way as Vercel: blank `/` when a private section is on, paper at `/<secret>/`.

## GitHub Pages

```
python3 scripts/deploy_github_pages.py
```

This force-updates **only** the branch in `deploy.github_pages_branch` (default `gh-pages`). It will not push to `main` or `master`. The commit is made in a temporary repo so your working tree is untouched. After the push it tries to enable Pages from that branch at the repository root.

A project site is served at `https://<user>.github.io/<repo>/`. Relative links work. Set `deploy.domain` to a custom domain and the script writes a `CNAME` file on that branch only.

**Private sections and a public repo do not mix.** The secret path would be in a public branch. The script refuses unless the repo is private, or you pass `--allow-public` (don't, unless the reader understands the link is not a secret). Prefer Vercel or Cloudflare for a private edition.

First-time manual fallback: Settings → Pages → deploy from the `gh-pages` branch, folder `/`.

## Private path on every target

The layout is the same folder everywhere:

- Public: `dist/site/index.html` is the paper. `robots.txt` allows crawling.
- Private: `dist/site/index.html` is blank and `noindex`. The paper, CSS, JS, and fonts are under `dist/site/<secret>/`. `robots.txt` disallows `/`. The secret is created once in `.secret_path` and reused.

News-only editions stay at `/`. The moment any private section is enabled, the next build moves the paper and leaves `/` blank.
