#!/usr/bin/env python3
"""
Getro deep-discovery script.

Goal: dump the full structure of pageProps.network and any nested data
so we can find:
  1. The numeric collection_id / network_id
  2. The companies array (if pre-loaded in __NEXT_DATA__)
  3. Any API endpoint hints

Usage:
    python3 getro_discover_deep.py 2>&1 | tee /root/pp-jobapp/workspace/getro_deep.log
"""

import json
import re
import requests

BOARDS = {
    "accel":            "https://jobs.accel.com",
    "general_catalyst": "https://jobs.generalcatalyst.com",
    "lightspeed":       "https://jobs.lsvp.com",
    "kleiner_perkins":  "https://jobs.kleinerperkins.com",
    "greylock":         "https://jobs.greylock.com",
    "sequoia":          "https://jobs.sequoiacap.com",
}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
}


def summarize(obj, depth=0, max_depth=3, prefix=""):
    """Recursively summarize a JSON object's shape."""
    indent = "  " * depth
    if depth > max_depth:
        print(f"{indent}{prefix}... (max depth)")
        return

    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict):
                print(f"{indent}{prefix}{k}: dict({len(v)} keys)")
                summarize(v, depth + 1, max_depth, "")
            elif isinstance(v, list):
                if v and isinstance(v[0], dict):
                    print(f"{indent}{prefix}{k}: list[{len(v)}] of dict, "
                          f"first-keys={list(v[0].keys())[:8]}")
                    if depth < max_depth:
                        print(f"{indent}  sample[0]:")
                        summarize(v[0], depth + 2, max_depth, "")
                else:
                    print(f"{indent}{prefix}{k}: list[{len(v)}] = "
                          f"{str(v[:3])[:120]}")
            else:
                # scalar
                val_str = repr(v)[:100]
                print(f"{indent}{prefix}{k}: {type(v).__name__} = {val_str}")
    elif isinstance(obj, list):
        print(f"{indent}{prefix}list[{len(obj)}]")
        if obj and isinstance(obj[0], dict):
            summarize(obj[0], depth + 1, max_depth, "[0].")


def inspect(name, url):
    print(f"\n{'=' * 70}")
    print(f"  {name}: {url}")
    print('=' * 70)

    try:
        r = requests.get(f"{url}/companies", headers=HEADERS, timeout=30)
    except Exception as e:
        print(f"  REQUEST ERROR: {e}")
        return

    print(f"  Status: {r.status_code}, length: {len(r.text)}")

    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        r.text, re.DOTALL,
    )
    if not m:
        print("  No __NEXT_DATA__ found")
        # Maybe it's a different framework — look for window.__INITIAL_STATE__
        m2 = re.search(
            r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
            r.text, re.DOTALL,
        )
        if m2:
            print("  Found window.__INITIAL_STATE__ instead")
            try:
                data = json.loads(m2.group(1))
                summarize(data)
            except Exception as e:
                print(f"  parse err: {e}")
        return

    try:
        data = json.loads(m.group(1))
    except Exception as e:
        print(f"  __NEXT_DATA__ parse error: {e}")
        return

    page_props = data.get("props", {}).get("pageProps", {})
    print(f"\n  pageProps keys: {list(page_props.keys())}")

    # The network object holds the board's identity
    network = page_props.get("network")
    if network:
        print(f"\n  >>> network object:")
        summarize(network, max_depth=2)

    # Companies may be pre-loaded
    for k in ("companies", "initialCompanies", "companiesData", "items"):
        if k in page_props:
            v = page_props[k]
            if isinstance(v, dict):
                print(f"\n  >>> {k} (dict):")
                summarize(v, max_depth=2)
            elif isinstance(v, list):
                print(f"\n  >>> {k}: list of {len(v)}")
                if v:
                    print(f"  sample[0] keys: {list(v[0].keys())[:15]}")
                    summarize(v[0], max_depth=1)

    # Also look anywhere in the JSON for collection_id, network_id, board_id
    raw = json.dumps(data)
    for needle in ["collection_id", "network_id", "board_id",
                   "collectionId", "networkId", "boardId"]:
        m = re.search(rf'"{needle}"\s*:\s*([^,}}]+)', raw)
        if m:
            print(f"  found in raw JSON: {needle} = {m.group(1)[:50]}")


for name, url in BOARDS.items():
    try:
        inspect(name, url)
    except Exception as e:
        print(f"  ERROR: {e}")
