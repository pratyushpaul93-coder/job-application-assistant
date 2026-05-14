#!/usr/bin/env python3
"""Backfill website_url for Built In companies that don't have one.

Built In list pages don't carry the company website — it lives on the per-company
detail page at builtin.com/company/<slug>, in a "View Website" anchor with a UTM-
tagged href. We deferred this fetch at initial ingest. This script recovers it.

Strategy:
- Query companies where source_type='builtin_bptw' AND website_url IS NULL.
- For each, pull builtin_slug from raw_metadata.lists[0].builtin_slug.
- Fetch builtin.com/company/<slug>, regex out the View Website href, strip UTM
  params, and storage.upsert_company(... website_url=...).

Idempotent — re-runnable. Caches every fetched HTML to workspace/data/external/
builtin_bptw/<date>/details/<slug>.html for replay.

Usage:
    python3 -m ingest.builtin_url_backfill              # all eligible
    python3 -m ingest.builtin_url_backfill --limit 50   # quick smoke
    python3 -m ingest.builtin_url_backfill --workers 4  # default 4
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)
import storage  # noqa: E402

DETAILS_ROOT = Path("/root/pp-jobapp/workspace/data/external/builtin_bptw")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://builtin.com/awards/us/2025/best-places-to-work",
}

# Two patterns to be safe — the @click handler is the most specific marker
_WEBSITE_RE_PRIMARY = re.compile(
    r'<a[^>]+href="(https?://[^"]+)"[^>]*@click="trackViewWebsite\(\)"',
    re.IGNORECASE,
)
_WEBSITE_RE_FALLBACK = re.compile(
    r'<a[^>]+href="(https?://[^"]+)"[^>]*>\s*View Website\s*</a>',
    re.IGNORECASE,
)


def _strip_utm(url: str) -> str:
    """Drop utm_* / ref params; keep everything else."""
    try:
        p = urlparse(url)
    except ValueError:
        return url
    if not p.query:
        return url
    keep = []
    for part in p.query.split("&"):
        k = part.split("=", 1)[0].lower()
        if k.startswith("utm_") or k in {"ref", "referrer"}:
            continue
        keep.append(part)
    new_q = "&".join(keep)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_q, ""))


def fetch_detail(slug: str, cache_dir: Path, max_retries: int = 3) -> str | None:
    """Return HTML body for builtin.com/company/<slug>; cache on disk.

    Built In rate-limits aggressively — bare 'Mozilla/5.0' UA + concurrency >2
    triggers WAF 403s within ~50 requests. Mitigations:
    - Full browser-mimic header set
    - Retry-after backoff on 403/429 (exponential up to max_retries)
    - 404 is cached as empty string so we don't retry
    """
    cache_path = cache_dir / f"{slug}.html"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    url = f"https://builtin.com/company/{slug}"
    for attempt in range(max_retries):
        req = Request(url, headers=HEADERS)
        try:
            with urlopen(req, timeout=15) as r:
                html = r.read().decode("utf-8", errors="replace")
            cache_path.write_text(html, encoding="utf-8")
            return html
        except HTTPError as e:
            if e.code == 404:
                return ""
            if e.code in (403, 429) and attempt < max_retries - 1:
                wait = 2 ** (attempt + 2)  # 4s, 8s, 16s
                time.sleep(wait)
                continue
            raise
    return None


def extract_website(html: str) -> str | None:
    if not html:
        return None
    m = _WEBSITE_RE_PRIMARY.search(html) or _WEBSITE_RE_FALLBACK.search(html)
    if not m:
        return None
    return _strip_utm(m.group(1).strip()).rstrip("/")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=1,
                    help="Built In rate-limits aggressively; 1 worker is the safe default")
    ap.add_argument("--sleep", type=float, default=1.5, help="sleep per worker between requests")
    args = ap.parse_args()

    cache_dir = DETAILS_ROOT / date.today().isoformat() / "details"
    cache_dir.mkdir(parents=True, exist_ok=True)

    conn = storage.connect("/root/pp-jobapp/workspace/jobapp.db")
    # Pull eligible cos: active, no website_url, in builtin_bptw, with a slug in metadata
    rows = conn.execute("""
        SELECT c.id, c.canonical_name, cs.raw_metadata_json
        FROM companies c
        JOIN company_sources cs ON cs.company_id=c.id AND cs.source_type='builtin_bptw'
        WHERE c.active=1 AND (c.website_url IS NULL OR c.website_url='')
        ORDER BY c.id
    """).fetchall()

    tasks = []
    for r in rows:
        meta = json.loads(r["raw_metadata_json"] or "{}")
        lists = meta.get("lists") or []
        slug = lists[0].get("builtin_slug") if lists else None
        if slug:
            tasks.append((r["id"], r["canonical_name"], slug))
    if args.limit:
        tasks = tasks[: args.limit]

    print(f"[builtin_url_backfill] eligible={len(rows)}, with-slug={len(tasks)}", flush=True)
    if not tasks:
        return

    found = 0
    missing = 0
    errors = 0

    def worker(task):
        cid, name, slug = task
        try:
            html = fetch_detail(slug, cache_dir)
            url = extract_website(html)
            time.sleep(args.sleep)
            return cid, name, slug, url, None
        except Exception as e:
            return cid, name, slug, None, f"{type(e).__name__}: {e}"

    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, fut in enumerate(cf.as_completed([ex.submit(worker, t) for t in tasks]), 1):
            cid, name, slug, url, err = fut.result()
            if err:
                errors += 1
                if errors <= 10:
                    print(f"  ERROR {name!r} ({slug}): {err}", flush=True)
            elif url:
                try:
                    storage.upsert_company(conn, name, website_url=url)
                    conn.commit()
                    found += 1
                except Exception as e:
                    errors += 1
                    print(f"  DB ERROR {name!r}: {e}", flush=True)
            else:
                missing += 1
            if i % 100 == 0:
                rate = i / (time.time() - t0)
                eta = (len(tasks) - i) / max(rate, 0.01)
                print(f"  {i}/{len(tasks)}  found={found} missing={missing} errors={errors}  "
                      f"rate={rate:.1f}/s eta={eta/60:.1f}m", flush=True)

    print(f"\n[builtin_url_backfill] DONE  total={len(tasks)} "
          f"found={found} missing={missing} errors={errors} "
          f"elapsed={(time.time()-t0)/60:.1f}m", flush=True)


if __name__ == "__main__":
    main()
