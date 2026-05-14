"""Spike v2: render N SPAs from the unknown bucket with Playwright and check
whether the rendered DOM exposes an ATS slug that HTTP-only detection missed.

Differences from v1:
  - bigger random sample (default 20 companies)
  - longer wait (`networkidle` up to 8s)
  - tries apex + careers.<host> + jobs.<host> + 4 path variants
  - also reports bare hostname mentions (lightweight-recoverable signal in
    rendered DOM, even when the slug regex doesn't capture)

Decision target: hit-rate. If ≥30% of sampled SPAs yield a slug via rendering,
build out tools/render_phase.py. If <10%, rethink — most of the +190 yield
estimate is illusory.
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, "/root/pp-jobapp/scripts")
import storage  # noqa: E402
from playwright.sync_api import sync_playwright

INPUT_CSV = "/root/pp-jobapp/workspace/phase2_probe_results_20260507.csv"

# Bare hostname patterns (any provider mention, no slug needed). Tells us
# whether rendering at least surfaces a provider hint.
HOSTNAME_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse",       re.compile(r"\bboards\.greenhouse\.io|job-boards\.greenhouse\.io\b", re.I)),
    ("ashby",            re.compile(r"\b(?:jobs|embed)\.ashbyhq\.com\b", re.I)),
    ("lever",            re.compile(r"\bjobs\.lever\.co\b", re.I)),
    ("workable",         re.compile(r"\bapply\.workable\.com\b", re.I)),
    ("smartrecruiters",  re.compile(r"\b(?:careers|jobs)\.smartrecruiters\.com\b", re.I)),
    ("bamboohr",         re.compile(r"\.bamboohr\.com\b", re.I)),
    ("teamtailor",       re.compile(r"\.teamtailor\.com\b", re.I)),
    ("workday",          re.compile(r"\.(?:wd[0-9]+|myworkday(?:jobs)?)\.com\b", re.I)),
    ("icims",            re.compile(r"\.icims\.com\b", re.I)),
    ("eightfold",        re.compile(r"\.eightfold\.ai\b", re.I)),
    ("personio",         re.compile(r"\.jobs\.personio\.(?:com|de)\b", re.I)),
    ("recruitee",        re.compile(r"\.recruitee\.com\b", re.I)),
    ("jazzhr",           re.compile(r"\.applytojob\.com\b", re.I)),
    ("breezy",           re.compile(r"\.breezy\.hr\b", re.I)),
    ("phenom",           re.compile(r"\bphenompeople\.com\b", re.I)),
    ("successfactors",   re.compile(r"\bsuccessfactors\.com\b", re.I)),
    ("jobvite",          re.compile(r"\bjobs\.jobvite\.com\b", re.I)),
]

PATH_VARIANTS = ["", "/careers", "/jobs", "/about/careers"]
SUBDOMAIN_VARIANTS = ["careers", "jobs"]
WAIT_AFTER_LOAD_MS = 3000


def expand_urls(base_url: str) -> list[str]:
    p = urlparse(base_url)
    host = p.netloc or p.path
    scheme = p.scheme or "https"
    apex = host.lstrip("www.")
    urls = [f"{scheme}://{host.rstrip('/')}{path}" for path in PATH_VARIANTS]
    for sub in SUBDOMAIN_VARIANTS:
        urls.append(f"{scheme}://{sub}.{apex}")
    return urls


def search_html(html: str) -> tuple[str | None, str | None, str | None, str]:
    """Returns (slug_provider, slug, hostname_provider, snippet).

    slug_provider is a provider whose full _ATS_SIGNATURES regex captured a
    slug. hostname_provider is any bare hostname mention (broader signal).
    Either may be None.
    """
    for provider, pattern in storage._ATS_SIGNATURES:
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            return provider, m.group(1), provider, m.group(0)[:120]
    for provider, pat in HOSTNAME_PATTERNS:
        m = pat.search(html)
        if m:
            return None, None, provider, m.group(0)[:120]
    return None, None, None, ""


def render_and_search(page, url: str) -> tuple[str | None, str | None, str | None, str]:
    try:
        page.goto(url, timeout=15000, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(WAIT_AFTER_LOAD_MS)
        html = page.content()
    except Exception as e:
        return None, None, None, f"NAV_FAIL: {type(e).__name__}"
    return search_html(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="random sample size")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    with open(INPUT_CSV) as f:
        rows = [r for r in csv.DictReader(f) if r["category"] == "js_rendered_spa"]
    random.seed(args.seed)
    sample = random.sample(rows, min(args.n, len(rows)))

    slug_hits: list[tuple[str, str, str]] = []      # (name, provider, slug)
    hostname_only_hits: list[tuple[str, str]] = []  # (name, provider)
    nothing: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (compatible; pp-jobapp-spike/1.0)",
            ignore_https_errors=True,
        )
        for i, row in enumerate(sample, 1):
            page = ctx.new_page()
            urls = expand_urls(row["url"])
            outcome: str = "miss"
            print(f"\n[{i}/{len(sample)}] {row['name']} ({row['url']})")
            for url in urls:
                slug_prov, slug, host_prov, snippet = render_and_search(page, url)
                if slug_prov:
                    print(f"  SLUG HIT @ {url}: {slug_prov}/{slug}  {snippet!r}")
                    slug_hits.append((row["name"], slug_prov, slug or ""))
                    outcome = "slug"
                    break
                if host_prov and outcome != "host":
                    print(f"  hostname mention @ {url}: {host_prov}  {snippet!r}")
                    hostname_only_hits.append((row["name"], host_prov))
                    outcome = "host"
                    # keep iterating in case a later URL gives a real slug
            if outcome == "miss":
                print("  no signal across all variants")
                nothing.append(row["name"])
            page.close()
        ctx.close()
        browser.close()

    print()
    print(f"## Spike results (n={len(sample)})")
    print(f"  slug hits: **{len(slug_hits)}** ({len(slug_hits)/len(sample)*100:.0f}%)")
    print(f"  hostname-only hits: {len(hostname_only_hits)}")
    print(f"  nothing: {len(nothing)}")
    if slug_hits:
        print("\nSlug hits:")
        for name, prov, slug in slug_hits:
            print(f"  {name}: {prov}/{slug}")
    if hostname_only_hits:
        print("\nHostname-only hits:")
        for name, prov in hostname_only_hits:
            print(f"  {name}: {prov}")


if __name__ == "__main__":
    main()
