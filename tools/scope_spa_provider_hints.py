"""Scope the lightweight SPA fallback: count provider-hostname mentions in
static HTML for the 190 companies in workspace/phase2_probe_results_20260507.csv
that were categorized as `js_rendered_spa`.

For each company we fetch homepage + the same careers paths the audit used,
then look for *bare provider hostname mentions* (e.g., `greenhouse.io`,
`lever.co`, `ashbyhq.com`) in the raw HTML. Crucially, the existing detector
already ran on these — they returned `unknown/not_found`. So a hostname
mention here is exactly the population the lightweight provider-hint
fallback could recover.

Output:
    workspace/spa_scoping_<DATE>.csv  - one row per company:
        id, name, url, providers_mentioned (semicolon-joined), n_providers
    Stdout summary: per-provider company count + total-coverage line.

Pure HTTP + regex. No LLM, no DB writes.
"""
from __future__ import annotations

import csv
import datetime
import os
import re
import socket
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.join(ROOT, "workspace")
INPUT_CSV = os.path.join(WORKSPACE, "phase2_probe_results_20260507.csv")

CAREERS_PATHS = ["/careers", "/jobs", "/career", "/work-with-us", "/join", "/join-us", "/about/careers"]
UA = "Mozilla/5.0 (compatible; pp-jobapp-audit/1.0)"
HTTP_TIMEOUT = 8
WORKERS = 16

# Bare hostname patterns. We are NOT trying to capture slugs here — only
# whether the provider's hostname appears anywhere in the static HTML.
# A match means: "lightweight fallback would have a provider hint to chase."
HOSTNAME_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse",       re.compile(r"\bboards\.greenhouse\.io|job-boards\.greenhouse\.io\b", re.I)),
    ("ashby",            re.compile(r"\b(?:jobs|embed)\.ashbyhq\.com\b", re.I)),
    ("lever",            re.compile(r"\bjobs\.lever\.co\b", re.I)),
    ("workable",         re.compile(r"\bapply\.workable\.com\b", re.I)),
    ("smartrecruiters",  re.compile(r"\b(?:careers|jobs)\.smartrecruiters\.com\b", re.I)),
    ("bamboohr",         re.compile(r"\.bamboohr\.com\b", re.I)),
    ("personio",         re.compile(r"\.jobs\.personio\.(?:com|de)\b", re.I)),
    ("recruitee",        re.compile(r"\.recruitee\.com\b", re.I)),
    ("jazzhr",           re.compile(r"\.applytojob\.com\b", re.I)),
    ("teamtailor",       re.compile(r"\.teamtailor\.com\b", re.I)),
    ("workday",          re.compile(r"\.(?:wd[0-9]+|myworkday(?:jobs)?)\.com\b", re.I)),
    ("icims",            re.compile(r"\.icims\.com\b", re.I)),
    ("eightfold",        re.compile(r"\.eightfold\.ai\b", re.I)),
    ("breezy",           re.compile(r"\.breezy\.hr\b", re.I)),
    ("jobvite",          re.compile(r"\bjobs\.jobvite\.com\b", re.I)),
    ("successfactors",   re.compile(r"\bsuccessfactors\.com\b", re.I)),
    ("phenom",           re.compile(r"\bphenompeople\.com\b", re.I)),
    ("comeet",           re.compile(r"\bcomeet\.co\b", re.I)),
]


def fetch(url: str) -> str:
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read(2_000_000).decode("utf-8", errors="replace")
    except (HTTPError, URLError, socket.timeout, TimeoutError, UnicodeDecodeError, Exception):
        return ""


def absolute(base: str, path: str) -> str:
    p = urlparse(base)
    return urlunparse((p.scheme or "https", p.netloc, path, "", "", ""))


def scan_company(row: dict) -> dict:
    """Fetch homepage + careers paths; return set of providers mentioned in any."""
    url = row["url"].strip()
    providers: set[str] = set()
    if not url:
        return {"id": row["id"], "name": row["name"], "url": url, "providers": providers}
    pages = [url] + [absolute(url, p) for p in CAREERS_PATHS]
    for page_url in pages:
        html = fetch(page_url)
        if not html:
            continue
        for name, pat in HOSTNAME_PATTERNS:
            if pat.search(html):
                providers.add(name)
    return {"id": row["id"], "name": row["name"], "url": url, "providers": providers}


def main():
    if not os.path.exists(INPUT_CSV):
        print(f"missing input: {INPUT_CSV}", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_CSV) as f:
        rows = [r for r in csv.DictReader(f) if r["category"] == "js_rendered_spa"]
    print(f"scanning {len(rows)} js_rendered_spa companies…", file=sys.stderr)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(scan_company, r): r for r in rows}
        for i, fut in enumerate(as_completed(futures), 1):
            results.append(fut.result())
            if i % 25 == 0:
                print(f"  {i}/{len(rows)}", file=sys.stderr)

    # Summary
    per_provider: Counter[str] = Counter()
    n_with_any = 0
    for r in results:
        if r["providers"]:
            n_with_any += 1
        for p in r["providers"]:
            per_provider[p] += 1

    print()
    print(f"## SPA scoping summary ({len(results)} companies)")
    print()
    print(f"Companies mentioning ≥1 provider hostname in static HTML: "
          f"**{n_with_any} / {len(results)}** "
          f"({n_with_any / len(results) * 100:.0f}%)")
    print()
    print("Per-provider counts (a company may appear in multiple rows):")
    print()
    print("| Provider | Companies |")
    print("|---|---:|")
    for prov, cnt in per_provider.most_common():
        print(f"| {prov} | {cnt} |")
    print()
    print("Decision rule: >50% lightweight-first; <20% straight to Playwright; "
          "in between requires judgment.")

    # Write detailed CSV
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    out_csv = os.path.join(WORKSPACE, f"spa_scoping_{date_str}.csv")
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "url", "providers_mentioned", "n_providers"])
        for r in sorted(results, key=lambda x: -len(x["providers"])):
            w.writerow([r["id"], r["name"], r["url"], ";".join(sorted(r["providers"])), len(r["providers"])])
    print(f"\nDetailed CSV: {out_csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
