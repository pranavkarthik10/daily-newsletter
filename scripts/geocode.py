#!/usr/bin/env python3
"""Resolve a city name to latitude, longitude, and timezone via Open-Meteo.

  python3 scripts/geocode.py "New York"
Prints a JSON list. No API key.
"""
import json
import sys
import urllib.parse
import urllib.request

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        raise SystemExit("usage: geocode.py \"City name\"")
    query = " ".join(argv)
    qs = urllib.parse.urlencode({"name": query, "count": 5, "language": "en", "format": "json"})
    req = urllib.request.Request(
        "https://geocoding-api.open-meteo.com/v1/search?" + qs,
        headers={"User-Agent": "daily-newsletter/1.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        payload = json.loads(res.read().decode("utf-8"))
    results = []
    for row in payload.get("results") or []:
        results.append({
            "name": ", ".join(p for p in (row.get("name"), row.get("admin1"), row.get("country")) if p),
            "city": row.get("name"),
            "lat": row.get("latitude"),
            "lon": row.get("longitude"),
            "timezone": row.get("timezone"),
            "country": row.get("country"),
        })
    json.dump(results, sys.stdout, indent=2)
    sys.stdout.write("\n")
    if not results:
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
