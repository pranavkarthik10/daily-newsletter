#!/usr/bin/env python3
"""Build the edition and serve dist/site on 127.0.0.1.

  python3 scripts/preview.py            # sample edition, no network
  python3 scripts/preview.py --live     # build whatever is already in data/
"""
import argparse
import http.server
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import build

def main(argv=None):
    ap = argparse.ArgumentParser(description="Preview the paper locally")
    ap.add_argument("--live", action="store_true", help="Build from data/ instead of data/sample")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8787")))
    args = ap.parse_args(argv)
    publish = build.build_site(sample=not args.live)
    site = Path(publish["output"])
    port = args.port

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(site), **kw)
        def log_message(self, fmt, *a):
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % a))
        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if publish.get("private"):
                self.send_header("X-Robots-Tag", "noindex, nofollow")
            super().end_headers()
        def list_directory(self, path):
            self.send_error(404)
            return None

    try:
        http.server.ThreadingHTTPServer.allow_reuse_address = True
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as ex:
        raise SystemExit(f"could not listen on 127.0.0.1:{port} ({ex})")
    url = f"http://127.0.0.1:{port}{publish['path']}"
    print(f"preview {url}")
    if publish.get("private"):
        print("root URL is a blank page on purpose")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")

if __name__ == "__main__":
    main()
