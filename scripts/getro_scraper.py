#!/usr/bin/env python3
"""
Getro VC Portfolio Scraper
==========================

Scrapes companies and active jobs from Getro-powered VC job boards.

Usage on Hetzner VPS:
    cd /root/pp-jobapp/scripts
    python3 getro_scraper.py --discover              # Find the API endpoint (run once)
    python3 getro_scraper.py --vc accel              # Scrape one VC
    python3 getro_scraper.py --all                   # Scrape all configured VCs
    python3 getro_scraper.py --all --output companies.csv

Output: CSV with one row per (vc, company) with active job counts.

Author: built for pp_openclaw_1_jobapplication
"""

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# ==============================================================================
# CONFIG: VC job boards (all Getro-powered)
# ==============================================================================
# Most Getro boards live at jobs.<vc>.com. Each board has an internal "board
# slug" or "collection" identifier the API uses. We'll discover it dynamically
# the first time we hit each board.

VC_BOARDS = {
    "accel":            "https://jobs.accel.com",
    "general_catalyst": "https://jobs.generalcatalyst.com",
    "lightspeed":       "https://jobs.lsvp.com",
    "index":            "https://jobs.indexventures.com",
    "kleiner_perkins":  "https://jobs.kleinerperkins.com",
    "greylock":         "https://jobs.greylock.com",
    "sequoia":          "https://jobs.sequoiacap.com",
    # Founders Fund, GV, Thrive: not on Getro — handled separately
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


# ==============================================================================
# STEP 1: API Discovery
# ==============================================================================

def discover_api(board_url: str) -> dict:
    """
    Inspect a Getro job board's HTML to find:
    - the API base URL (e.g., https://jobs.getro.com/api/v2)
    - the board's collection/community slug
    - the internal board ID
    """
    print(f"  fetching {board_url}/companies ...")
    r = requests.get(f"{board_url}/companies", headers=HEADERS, timeout=30)
    r.raise_for_status()
    html = r.text

    discovery = {
        "board_url": board_url,
        "html_length": len(html),
        "next_data": None,
        "api_refs": [],
        "slugs": {},
    }

    # 1) Next.js __NEXT_DATA__ — almost every Getro board is a Next.js app
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            discovery["next_data_keys"] = list(data.keys())
            page_props = data.get("props", {}).get("pageProps", {})
            discovery["page_props_keys"] = list(page_props.keys())
            # The board config usually lives in pageProps with keys like
            # `collection`, `community`, or `currentCollection`.
            for key in ["collection", "community", "currentCollection",
                        "board", "config", "settings"]:
                if key in page_props:
                    val = page_props[key]
                    if isinstance(val, dict):
                        discovery["slugs"][key] = {
                            k: v for k, v in val.items()
                            if k in ("id", "slug", "name", "subdomain")
                        }
            # Some boards put companies right in the initial state
            if "companies" in page_props:
                comps = page_props["companies"]
                if isinstance(comps, list):
                    discovery["initial_company_count"] = len(comps)
                    discovery["initial_company_sample"] = comps[:3]
        except json.JSONDecodeError as e:
            discovery["next_data_error"] = str(e)

    # 2) Find any *.getro.com API references
    api_refs = re.findall(r'https?://[a-z0-9.-]*getro\.com[^\s"\'<>]*', html)
    discovery["api_refs"] = sorted(set(api_refs))[:15]

    # 3) Find subdomain in URL — gives us the board slug
    sub = re.match(r'https?://jobs\.([a-z0-9-]+)\.', board_url)
    if sub:
        discovery["url_slug"] = sub.group(1)

    return discovery


# ==============================================================================
# STEP 2: Try the known Getro public APIs
# ==============================================================================
# Empirically, Getro's job boards call endpoints like:
#   https://jobs.getro.com/api/v2/job_boards/<slug>/companies
#   https://api.getro.com/api/v2/collections/<id>/companies
# We'll try a few patterns and use whichever returns 200.

API_PATTERNS = [
    # pattern, description
    ("https://jobs.getro.com/api/v2/job_boards/{slug}/companies?page={page}&per_page=100",
     "jobs.getro.com job_boards"),
    ("https://api.getro.com/api/v2/collections/{slug}/companies?page={page}&per_page=100",
     "api.getro.com collections"),
    ("https://api.getro.com/v2/collections/{slug}/companies.json?page={page}&per_page=100",
     "api.getro.com collections.json"),
]


def try_fetch_companies(slug: str, max_pages: int = 50) -> tuple[list, str]:
    """
    Try each known API pattern. Return (companies_list, working_pattern).
    Stops at first 200 OK.
    """
    for pattern, desc in API_PATTERNS:
        url_test = pattern.format(slug=slug, page=1)
        try:
            r = requests.get(url_test, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                try:
                    data = r.json()
                    print(f"    ✓ Pattern works: {desc}")
                    print(f"      First page returned: {type(data).__name__}, "
                          f"keys: {list(data.keys()) if isinstance(data, dict) else 'list'}")
                    # Now paginate
                    return paginate(pattern, slug, max_pages), pattern
                except json.JSONDecodeError:
                    continue
        except requests.RequestException:
            continue

    return [], ""


def paginate(pattern: str, slug: str, max_pages: int) -> list:
    """Walk all pages of a working API pattern."""
    all_companies = []
    for page in range(1, max_pages + 1):
        url = pattern.format(slug=slug, page=page)
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            break
        data = r.json()
        # Getro responses are usually {items: [...], meta: {...}}
        items = (data.get("items") or data.get("companies")
                 or data.get("data") or [])
        if not items:
            break
        all_companies.extend(items)
        print(f"      page {page}: +{len(items)} companies (total {len(all_companies)})")
        # Check for next page hint
        meta = data.get("meta") or {}
        if meta.get("page", page) >= meta.get("total_pages", page):
            break
        time.sleep(0.5)  # be polite
    return all_companies


# ==============================================================================
# STEP 3: HTML fallback — parse the rendered company cards
# ==============================================================================

def scrape_html_fallback(board_url: str) -> list:
    """
    If the API discovery fails, fall back to parsing the HTML cards.
    Note: Getro boards are usually paginated via 'Load more' button which is JS,
    so this only gets the first ~12 companies per board. Use API when possible.
    """
    r = requests.get(f"{board_url}/companies", headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    companies = []
    # Getro company cards are <a href="/companies/<slug>"> wrapping company info
    for link in soup.select('a[href^="/companies/"]'):
        href = link.get("href", "")
        if "/jobs/" in href:
            continue
        name = None
        img = link.find("img")
        if img and img.get("alt"):
            name = img["alt"].strip()
        if not name:
            h = link.find(["h2", "h3", "h4"])
            if h:
                name = h.get_text(strip=True)
        if name and not any(c["name"] == name for c in companies):
            companies.append({
                "name": name,
                "url": board_url + href,
                "source": "html_fallback",
            })
    return companies


# ==============================================================================
# STEP 4: Normalize and write CSV
# ==============================================================================

def normalize(company: dict, vc: str) -> dict:
    """Map raw Getro company JSON to our flat schema."""
    # Field names vary slightly across API versions
    return {
        "vc": vc,
        "company": company.get("name") or company.get("title") or "",
        "url": (company.get("url") or company.get("website")
                or company.get("domain") or ""),
        "description": (company.get("description") or company.get("about")
                        or "")[:500],
        "industry": ", ".join(company.get("industries", [])
                              if isinstance(company.get("industries"), list)
                              else []),
        "stage": company.get("funding_stage") or company.get("stage") or "",
        "headcount": company.get("headcount") or company.get("size") or "",
        "open_jobs": company.get("jobs_count") or company.get("active_jobs_count") or 0,
        "logo_url": company.get("logo_url") or company.get("image") or "",
    }


def write_csv(rows: list, path: str):
    if not rows:
        print(f"  (no rows to write)")
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {len(rows)} rows to {path}")


# ==============================================================================
# Main
# ==============================================================================

def scrape_vc(vc_name: str, board_url: str) -> list:
    print(f"\n=== Scraping {vc_name} ({board_url}) ===")

    # Step 1: discover the API
    discovery = discover_api(board_url)
    print(f"  url_slug: {discovery.get('url_slug')}")
    print(f"  api_refs found: {len(discovery.get('api_refs', []))}")
    if discovery.get("initial_company_count"):
        print(f"  found {discovery['initial_company_count']} companies in __NEXT_DATA__")

    # Step 2: try APIs
    slug = discovery.get("url_slug", vc_name)
    raw_companies, pattern = try_fetch_companies(slug)

    # Step 3: HTML fallback if API failed
    if not raw_companies:
        print(f"  API failed for {vc_name}, using HTML fallback (limited)")
        raw_companies = scrape_html_fallback(board_url)

    # Step 4: normalize
    return [normalize(c, vc_name) for c in raw_companies]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true",
                    help="Inspect API patterns, don't scrape")
    ap.add_argument("--vc", help="Scrape just one VC")
    ap.add_argument("--all", action="store_true", help="Scrape all VCs")
    ap.add_argument("--output", default="vc_companies.csv")
    args = ap.parse_args()

    if args.discover:
        for vc, url in VC_BOARDS.items():
            print(f"\n--- {vc} ---")
            try:
                d = discover_api(url)
                print(json.dumps({k: v for k, v in d.items()
                                  if k != "html_length"}, indent=2, default=str)[:1500])
            except Exception as e:
                print(f"  ERROR: {e}")
        return

    targets = []
    if args.vc:
        if args.vc not in VC_BOARDS:
            print(f"Unknown VC. Available: {list(VC_BOARDS.keys())}")
            sys.exit(1)
        targets = [(args.vc, VC_BOARDS[args.vc])]
    elif args.all:
        targets = list(VC_BOARDS.items())
    else:
        ap.print_help()
        sys.exit(1)

    all_rows = []
    for vc, url in targets:
        try:
            rows = scrape_vc(vc, url)
            all_rows.extend(rows)
            print(f"  -> {len(rows)} companies for {vc}")
        except Exception as e:
            print(f"  ERROR scraping {vc}: {e}")

    write_csv(all_rows, args.output)


if __name__ == "__main__":
    main()
