#!/usr/bin/env python3
"""
Test Getro API hypothesis.

We know Accel's network ID = 8672 from the deep discovery output.
This script tries 6 different URL patterns to see which one Getro's
public API actually uses, then dumps a sample response so we know the
JSON shape.

Usage:
    python3 getro_api_test.py 2>&1 | tee /root/pp-jobapp/workspace/getro_api_test.log
"""

import json
import requests

ACCEL_ID = "8672"
GC_ID = "222"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://jobs.accel.com",
    "Referer": "https://jobs.accel.com/",
}

# Patterns to try, ordered by most likely first
PATTERNS = [
    "https://api.getro.com/v2/collections/{id}/companies?page=1&per_page=10",
    "https://api.getro.com/api/v2/collections/{id}/companies?page=1&per_page=10",
    "https://jobs.getro.com/api/v2/collections/{id}/companies?page=1&per_page=10",
    "https://api.getro.com/v1/networks/{id}/companies?page=1&per_page=10",
    "https://api.getro.com/v2/networks/{id}/companies?page=1&per_page=10",
    "https://app.getro.com/api/v2/collections/{id}/companies?page=1&per_page=10",
    "https://api.getro.com/v2/collections/{id}/organizations?page=1&per_page=10",
    "https://api.getro.com/v2/collections/{id}/jobs?page=1&per_page=10",
]


def probe(network_id, label):
    print(f"\n{'='*70}")
    print(f"  Probing {label} (network_id={network_id})")
    print('='*70)

    found_pattern = None

    for pattern in PATTERNS:
        url = pattern.format(id=network_id)
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            print(f"\n  [{r.status_code}] {url}")

            if r.status_code == 200:
                # Got something! See if it's JSON
                try:
                    data = r.json()
                    print(f"  ✓ JSON response received")
                    print(f"  Type: {type(data).__name__}")

                    if isinstance(data, dict):
                        print(f"  Top-level keys: {list(data.keys())}")
                        # Look for company-list-shaped fields
                        for k in ["items", "companies", "data", "results",
                                  "organizations", "records"]:
                            if k in data:
                                v = data[k]
                                if isinstance(v, list):
                                    print(f"  ✓ Found '{k}' list with {len(v)} items")
                                    if v and isinstance(v[0], dict):
                                        print(f"  Sample item keys: "
                                              f"{list(v[0].keys())[:15]}")
                                        print(f"  First item (truncated):")
                                        print(json.dumps(v[0], indent=4,
                                                         default=str)[:1500])
                                    found_pattern = pattern
                                    break

                        # If no list found, dump some metadata
                        if not found_pattern:
                            for k in ["meta", "pagination", "total", "count"]:
                                if k in data:
                                    print(f"  {k}: {data[k]}")

                    elif isinstance(data, list):
                        print(f"  Got list of {len(data)} items")
                        if data and isinstance(data[0], dict):
                            print(f"  Sample item keys: "
                                  f"{list(data[0].keys())[:15]}")
                            found_pattern = pattern

                    if found_pattern:
                        break

                except json.JSONDecodeError:
                    body_preview = r.text[:200]
                    print(f"  Got 200 but not JSON: {body_preview!r}")

            elif r.status_code in (401, 403):
                # Endpoint exists but needs auth
                print(f"  Auth required — endpoint may exist")
                print(f"  Body preview: {r.text[:200]!r}")

            elif r.status_code == 404:
                print(f"  Not found")

            else:
                print(f"  Body preview: {r.text[:150]!r}")

        except requests.RequestException as e:
            print(f"  Request error: {e}")

    if found_pattern:
        print(f"\n  >>> WORKING PATTERN: {found_pattern}")
    else:
        print(f"\n  >>> NO PATTERN MATCHED")
    return found_pattern


# Test both known IDs
accel_pattern = probe(ACCEL_ID, "Accel")
gc_pattern = probe(GC_ID, "General Catalyst")

print(f"\n\n{'='*70}")
print(f"  SUMMARY")
print('='*70)
print(f"  Accel pattern: {accel_pattern}")
print(f"  GC pattern:    {gc_pattern}")
