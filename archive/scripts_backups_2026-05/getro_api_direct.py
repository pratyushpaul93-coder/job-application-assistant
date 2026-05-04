#!/usr/bin/env python3
"""
Test the Getro /api-boards/search-companies endpoint directly.

Discovered from XHR capture:
  POST https://jobs.<vc>.com/api-boards/search-companies
  Returns JSON with a "companies" array.

This script tries a minimal POST to each of the 6 boards and dumps:
  - HTTP status
  - Response keys
  - Number of companies returned
  - Sample company fields
  - Pagination info

Usage:
    python3 getro_api_direct.py 2>&1 | tee /root/pp-jobapp/workspace/getro_api_direct.log
"""

import json
import requests

BOARDS = [
    ("accel",            "https://jobs.accel.com"),
    ("general_catalyst", "https://jobs.generalcatalyst.com"),
    ("lightspeed",       "https://jobs.lsvp.com"),
    ("kleiner_perkins",  "https://jobs.kleinerperkins.com"),
    ("greylock",         "https://jobs.greylock.com"),
    ("sequoia",          "https://jobs.sequoiacap.com"),
]

# Minimal POST body. Let's start with empty filters and see what they accept.
# Multiple body shapes to try, in order of likelihood:
PAYLOADS_TO_TRY = [
    # Try 1: completely empty
    {},
    # Try 2: typical pagination
    {"page": 1, "perPage": 100},
    # Try 3: with filters object
    {"filters": {}, "page": 1, "perPage": 100},
    # Try 4: search-style with q
    {"q": "", "page": 1, "perPage": 100},
]


def make_headers(board_url):
    return {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": board_url,
        "Referer": f"{board_url}/companies",
    }


def probe(label, board_url):
    print(f"\n{'='*70}")
    print(f"  {label}: {board_url}")
    print('='*70)

    endpoint = f"{board_url}/api-boards/search-companies"
    headers = make_headers(board_url)

    for i, payload in enumerate(PAYLOADS_TO_TRY):
        print(f"\n  Try {i+1}: payload = {json.dumps(payload)}")
        try:
            r = requests.post(endpoint, headers=headers,
                              json=payload, timeout=20)
            print(f"  Status: {r.status_code}")

            if r.status_code != 200:
                # Show error body
                print(f"  Body: {r.text[:300]!r}")
                continue

            try:
                data = r.json()
            except json.JSONDecodeError:
                print(f"  Got 200 but not JSON: {r.text[:200]!r}")
                continue

            print(f"  ✓ JSON received")
            print(f"  Top-level keys: {list(data.keys())}")

            # Look for companies
            companies = data.get("companies") or data.get("items") or []
            print(f"  Companies in response: {len(companies)}")

            if companies and isinstance(companies[0], dict):
                first = companies[0]
                print(f"  First company keys: {list(first.keys())[:20]}")
                # Pretty-print a trimmed sample
                sample = {
                    k: (v[:150] + "...") if isinstance(v, str) and len(v) > 150
                       else v
                    for k, v in first.items()
                    if k in ("id", "name", "slug", "description", "url",
                             "domain", "logoUrl", "stage", "headcount",
                             "industries", "industryTags", "openJobsCount",
                             "jobsCount", "activeJobsCount")
                }
                print(f"  Sample (trimmed):")
                print(json.dumps(sample, indent=4)[:1500])

            # Pagination info
            for k in ("total", "totalCount", "totalPages", "meta",
                      "pagination"):
                if k in data:
                    print(f"  {k}: {json.dumps(data[k])[:200]}")

            # If we got companies, stop trying more payloads
            if companies:
                print(f"\n  >>> WORKING PAYLOAD for {label}")
                return data

        except requests.RequestException as e:
            print(f"  Request error: {e}")

    print(f"\n  >>> NO PAYLOAD WORKED for {label}")
    return None


results = {}
for label, url in BOARDS:
    try:
        r = probe(label, url)
        results[label] = r is not None
    except Exception as e:
        print(f"  ERROR: {e}")
        results[label] = False

print(f"\n\n{'='*70}")
print(f"  SUMMARY")
print('='*70)
for label, ok in results.items():
    print(f"  {label}: {'✓ working' if ok else '✗ failed'}")
