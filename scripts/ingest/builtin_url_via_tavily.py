#!/usr/bin/env python3
"""Recover website_url for Built In companies via Tavily web search.

Background: We were IP-banned by Built In's WAF after the direct-scrape attempt
on 2026-05-12. Tavily gives us the same data (URL → company homepage) via a
third-party search API with no rate-limit issues from our perspective.

Strategy:
- Query: f"{name} official website {hq_city or ''}".strip()
- Take top scored result whose host isn't on a DISALLOW list (LinkedIn, Built In,
  Wikipedia, Crunchbase, Glassdoor, Indeed, ZoomInfo, etc.)
- Reduce URL to scheme+netloc (drop paths like /contact-us)
- storage.upsert_company(..., website_url=...)
- Cache every API response to workspace/data/external/builtin_bptw/<date>/tavily/
  so a re-run is free.

Usage:
    python3 -m ingest.builtin_url_via_tavily              # all eligible
    python3 -m ingest.builtin_url_via_tavily --limit 20   # smoke
"""
from __future__ import annotations
import argparse, json, os, re, sys, time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)
import storage  # noqa: E402
from keys import get_tavily_key  # noqa: E402

CACHE_ROOT = Path("/root/pp-jobapp/workspace/data/external/builtin_bptw")
TAVILY_URL = "https://api.tavily.com/search"

# Apex domains to skip — directories, aggregators, profiles, social
DISALLOWED_APEXES = {
    "builtin.com", "linkedin.com", "wikipedia.org", "crunchbase.com",
    "glassdoor.com", "indeed.com", "zoominfo.com", "owler.com",
    "facebook.com", "twitter.com", "instagram.com", "youtube.com",
    "pitchbook.com", "tracxn.com", "ycombinator.com", "bbb.org",
    # Job aggregators
    "lensa.com", "ziprecruiter.com", "simplyhired.com", "jobgether.com",
    "monster.com", "snagajob.com", "careerbuilder.com", "dice.com",
    "jora.com", "workable.com", "lever.co", "greenhouse.io", "ashbyhq.com",
    # Misc directories
    "x.com", "github.com", "medium.com", "reddit.com", "bloomberg.com",
    "reuters.com", "forbes.com", "businesswire.com", "prnewswire.com",
    "yelp.com", "trustpilot.com",
}

# Strings that, if present in any subdomain label, indicate staging/dev/test
_STAGING_LABEL_PATTERNS = re.compile(r"\b(staging|stg|dev|test|preview|qa|sandbox|k8s|internal)\b")


def tavily_search(api_key: str, query: str, *, max_results: int = 5) -> dict | None:
    payload = json.dumps({
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
    }).encode()
    req = Request(TAVILY_URL, data=payload, headers={"Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            return None
        except URLError:
            time.sleep(1)
    return None


def _apex(host: str) -> str:
    """Derive apex domain. 'jobs.zs.com' → 'zs.com', 'portal.afterpay.com' → 'afterpay.com'.

    Two-label fallback. Doesn't handle co.uk/com.au correctly (would yield co.uk),
    but our list is overwhelmingly US tech — acceptable failure mode (caller can
    re-search the few non-US misfires).
    """
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    # Heuristic: if penultimate label is a known 2nd-level TLD, keep 3 parts.
    second_level_tlds = {"co", "com", "ac", "gov", "org", "net"}
    if parts[-2] in second_level_tlds and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def pick_url(results: list[dict]) -> str | None:
    """Pick the highest-scored result whose apex domain isn't a directory site.

    Reduces any URL to scheme + apex (drops jobs./careers./portal./app./www.
    subdomains). Filters staging-looking hostnames.
    """
    seen_apexes: set[str] = set()
    for r in results:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        try:
            host = urlparse(url).netloc.lower()
        except ValueError:
            continue
        if _STAGING_LABEL_PATTERNS.search(host):
            continue
        apex = _apex(host)
        if apex in DISALLOWED_APEXES or apex in seen_apexes:
            seen_apexes.add(apex)
            continue
        seen_apexes.add(apex)
        return f"https://{apex}"
    return None


def build_query(name: str, hq_city: str | None, industry_tags: list[str] | None) -> str:
    parts = [name, "official website"]
    if industry_tags:
        parts.append(industry_tags[0])
    if hq_city:
        parts.append(hq_city)
    return " ".join(parts).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.3, help="seconds between API calls")
    args = ap.parse_args()

    api_key = get_tavily_key()
    if not api_key:
        sys.exit("FATAL: Tavily API key missing — /root/.tavily/key")

    cache_dir = CACHE_ROOT / date.today().isoformat() / "tavily"
    cache_dir.mkdir(parents=True, exist_ok=True)

    conn = storage.connect("/root/pp-jobapp/workspace/jobapp.db")
    rows = conn.execute("""
        SELECT c.id, c.canonical_name, c.hq_city, cs.raw_metadata_json
        FROM companies c
        JOIN company_sources cs ON cs.company_id=c.id AND cs.source_type='builtin_bptw'
        WHERE c.active=1 AND (c.website_url IS NULL OR c.website_url='')
        ORDER BY c.id
    """).fetchall()
    if args.limit:
        rows = rows[:args.limit]

    print(f"[builtin_url_via_tavily] targets={len(rows)}", flush=True)

    found = 0
    blank = 0
    errors = 0
    t0 = time.time()

    for i, r in enumerate(rows, 1):
        name = r["canonical_name"]
        hq = r["hq_city"]
        try:
            meta = json.loads(r["raw_metadata_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        industry_tags = meta.get("industry_tags") or []

        # Cache key — use company id + slug-of-name so we can replay
        cache_path = cache_dir / f"{r['id']}.json"
        if cache_path.exists():
            resp = json.loads(cache_path.read_text())
        else:
            query = build_query(name, hq, industry_tags)
            resp = tavily_search(api_key, query)
            if resp is None:
                errors += 1
                if errors <= 5:
                    print(f"  ERROR  Tavily failed for {name!r}", flush=True)
                time.sleep(args.sleep)
                continue
            cache_path.write_text(json.dumps(resp))
            time.sleep(args.sleep)

        url = pick_url(resp.get("results") or [])
        if url:
            try:
                storage.upsert_company(conn, name, website_url=url)
                conn.commit()
                found += 1
            except Exception as e:
                errors += 1
                if errors <= 5:
                    print(f"  DB ERR for {name!r}: {e}", flush=True)
        else:
            blank += 1

        if i % 50 == 0 or i == len(rows):
            rate = i / (time.time() - t0)
            eta = (len(rows) - i) / max(rate, 0.01)
            print(f"  {i}/{len(rows)}  found={found} blank={blank} errors={errors}  "
                  f"rate={rate:.1f}/s eta={eta/60:.1f}m", flush=True)

    print(f"\n[builtin_url_via_tavily] DONE  total={len(rows)} "
          f"found={found} blank={blank} errors={errors} "
          f"elapsed={(time.time()-t0)/60:.1f}m", flush=True)


if __name__ == "__main__":
    main()
