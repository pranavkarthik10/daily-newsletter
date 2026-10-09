# Example edition

Everything in this folder is **example content for the offline preview**. It is not live news, not a reader's mail, and not a calendar. `python3 scripts/build.py --sample` (and `python3 scripts/preview.py`) render it without connectors or network.

Headlines on the front page match the demo edition so the layout can be checked. Private files (`calendar.json`, `email.json`, `sections/notebook.json`) stay off the page until those sections are enabled in `newsletter.config.json`.

Relative times such as `-5m` and `+26h` are a preview convenience. Live files written by `scripts/fetch.py` and `scripts/ingest.py` use ISO-8601 timestamps. See `docs/SCHEMAS.md`.
