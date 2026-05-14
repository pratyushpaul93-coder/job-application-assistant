#!/usr/bin/env python3
"""
retry_tier2_failures.py
========================
Re-runs tier-2 (Claude Haiku + web_search) on enrichment_cache rows that
previously failed due to rate-limiting or transient errors.

Use when:
  - A previous enrich_urls_oneshot.py run had tier-2 failures (e.g., 429s)
  - You've fixed the underlying issue (e.g., reduced concurrency, added retry)
  - You want to retry only the failed companies, not re-do tier-1

Workflow:
  1. python3 tools/enrich_urls_oneshot.py --dry-run    (initial run, some fail)
  2. python3 tools/retry_tier2_failures.py --dry-run   (preview retries)
  3. python3 tools/retry_tier2_failures.py --apply     (actually retry)
  4. python3 tools/enrich_urls_oneshot.py --dry-run    (regenerates CSV from cache)
  5. (review CSV, --commit as usual)

Identifies retryable rows by:
  - source IN ('claude_websearch_unverified', 'unknown')
  - reasoning containing rate-limit/api-error indicators
  - OR: --include-all flag to retry every non-deepseek-success row
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

# Make sibling imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from url_enrichment import (  # noqa: E402
    EnrichmentResult, normalize_url,
    cache_put,
    claude_websearch_many,
    head_verify, head_status_ok,
    CLAUDE_PACING_SEC, CLAUDE_WORKERS,
)
from keys import get_anthropic_key  # noqa: E402


DB_PATH = "/root/pp-jobapp/workspace/jobapp.db"


def find_retryable_rows(db_path: str, mode: str = "default") -> List[Dict[str, Any]]:
    """
    Find rows in enrichment_cache that should be retried via tier-2.

    Modes:
      'default'      : rate-limit/api-error tier-2 failures only (~551 rows)
      'comprehensive': adds DeepSeek medium/low confidence + any HEAD-fails
                       Best when you want web-search verification of DeepSeek
                       hedge cases. (~685 rows on first run)
      'all'          : every non-claude_websearch-success row. Last resort.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if mode == "all":
            rows = conn.execute("""
                SELECT name_normalized, name_original, source, confidence,
                       head_status, reasoning
                FROM enrichment_cache
                WHERE source != 'claude_websearch'
                ORDER BY name_original
            """).fetchall()
        elif mode == "comprehensive":
            # Tier-2 failures (rate-limit/api-error) + DeepSeek hedges + any HEAD-fail
            rows = conn.execute("""
                SELECT name_normalized, name_original, source, confidence,
                       head_status, reasoning
                FROM enrichment_cache
                WHERE
                    -- Rate-limited / API-error tier-2 failures
                    (source IN ('claude_websearch_unverified', 'unknown',
                                'claude_websearch_rate_limited')
                     AND (reasoning LIKE '%429%'
                          OR reasoning LIKE '%rate_limited%'
                          OR reasoning LIKE '%api_error%'
                          OR reasoning LIKE '%timeout%'
                          OR reasoning LIKE '%parse_error%'))
                    -- DeepSeek medium/low confidence: web-search-verify their hedges
                    OR (source = 'deepseek' AND confidence IN ('medium', 'low'))
                    -- DeepSeek HEAD failures (rare, but catch them)
                    OR (source LIKE 'deepseek%'
                        AND (head_status IS NULL OR head_status >= 400))
                ORDER BY name_original
            """).fetchall()
        else:  # default
            rows = conn.execute("""
                SELECT name_normalized, name_original, source, confidence,
                       head_status, reasoning
                FROM enrichment_cache
                WHERE source IN ('claude_websearch_unverified', 'unknown',
                                 'claude_websearch_rate_limited',
                                 'deepseek_unverified')
                  AND (reasoning LIKE '%429%'
                       OR reasoning LIKE '%rate_limited%'
                       OR reasoning LIKE '%api_error%'
                       OR reasoning LIKE '%timeout%')
                ORDER BY name_original
            """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def retry_via_tier2(rows: List[Dict[str, Any]], anthropic_key: str) -> int:
    """Run tier-2 on the given rows and update cache. Returns count of new successes."""
    names = [r["name_original"] for r in rows]
    # Build name -> previous-row lookup for fallback preservation
    prior_by_name = {r["name_original"]: r for r in rows}

    estimated_min = (len(names) * (CLAUDE_PACING_SEC + 3)) / 60.0  # ~3s per call + pacing
    print(f"\nRunning tier-2 on {len(names)} companies "
          f"(workers={CLAUDE_WORKERS}, pacing={CLAUDE_PACING_SEC}s)")
    print(f"Estimated runtime: ~{estimated_min:.1f} min")
    print()

    def progress(done, total):
        if done == 1 or done % 10 == 0 or done == total:
            print(f"  {done}/{total} complete", flush=True)

    t0 = time.time()
    cl_results = claude_websearch_many(names, anthropic_key, progress_callback=progress)
    elapsed = time.time() - t0
    print(f"\nTier-2 done in {elapsed:.1f}s")

    # HEAD verify each result
    print("\n--- HEAD verification ---")
    new_successes = 0
    new_unverified = 0
    new_rate_limited = 0
    new_unknown = 0
    deepseek_preserved = 0

    for cl in cl_results:
        name = cl["name"]
        url = normalize_url(cl.get("url") or "")
        confidence = cl.get("confidence", "unknown")
        reasoning = cl.get("reasoning", "")
        head_status = head_verify(url) if url else None
        verified = url and head_status_ok(head_status)

        # Determine source label and decide whether to preserve a prior good URL
        prior = prior_by_name.get(name, {})
        prior_source = prior.get("source", "")
        prior_was_deepseek = prior_source == "deepseek"

        if verified:
            source = "claude_websearch"
            new_successes += 1
        elif confidence == "rate_limited":
            # Tier-2 still rate-limited. If we had a prior DeepSeek answer,
            # leave the cache row alone (don't overwrite with worse data).
            if prior_was_deepseek:
                deepseek_preserved += 1
                continue  # skip cache_put — keep existing deepseek row
            source = "claude_websearch_rate_limited"
            new_rate_limited += 1
        elif url:
            # Tier-2 returned a URL but HEAD failed.
            # If we had DeepSeek high+verified before, keep it; tier-2 unverified is worse.
            if prior_was_deepseek:
                deepseek_preserved += 1
                continue
            source = "claude_websearch_unverified"
            new_unverified += 1
        else:
            # Tier-2 returned no URL.
            # If DeepSeek had one, keep it.
            if prior_was_deepseek:
                deepseek_preserved += 1
                continue
            source = "unknown"
            new_unknown += 1

        result = EnrichmentResult(
            name_original=name,
            url=url if verified else None,
            source=source,
            confidence=confidence,
            head_status=head_status,
            reasoning=reasoning,
        )
        cache_put(DB_PATH, result)

    print()
    print(f"Results:")
    print(f"  Verified URLs (claude_websearch):       {new_successes}")
    print(f"  HEAD-fail (claude_websearch_unverified): {new_unverified}")
    print(f"  Still rate-limited:                     {new_rate_limited}")
    print(f"  No URL found (unknown):                 {new_unknown}")
    print(f"  DeepSeek preserved (tier-2 was worse):  {deepseek_preserved}")

    return new_successes


def main():
    p = argparse.ArgumentParser(
        description="Retry tier-2 enrichment on rate-limited / errored / hedge rows."
    )
    p.add_argument("--dry-run", action="store_true",
                   help="Just show which rows would be retried; don't call API.")
    p.add_argument("--apply",   action="store_true",
                   help="Actually run tier-2 retries and update cache.")
    p.add_argument("--mode", choices=["default", "comprehensive", "all"],
                   default="comprehensive",
                   help="Retry scope. default=tier-2 failures only (~551). "
                        "comprehensive=adds DeepSeek medium/low + HEAD-fails (~685). "
                        "all=every non-success row.")
    p.add_argument("--db", default=DB_PATH, help=f"DB path (default: {DB_PATH})")
    p.add_argument("--limit", type=int, default=None,
                   help="Limit retries to first N (testing).")
    args = p.parse_args()

    if args.dry_run == args.apply:
        p.error("Specify exactly one of --dry-run or --apply")

    print("\n=== TIER-2 RETRY ===")
    print(f"Mode: {args.mode}\n")

    rows = find_retryable_rows(args.db, mode=args.mode)
    if args.limit:
        rows = rows[:args.limit]

    print(f"Retryable rows found: {len(rows)}")
    if not rows:
        print("Nothing to retry.")
        return

    # Show breakdown by source
    from collections import Counter
    src_counts = Counter(r["source"] for r in rows)
    print("By previous source:")
    for src, n in src_counts.most_common():
        print(f"  {src:35s} {n}")

    # Sample reasoning patterns
    print(f"\nSample of first 5 rows:")
    for r in rows[:5]:
        reasoning_short = (r["reasoning"] or "")[:60]
        print(f"  {r['name_original'][:30]:30s} | {r['source']:30s} | {reasoning_short}")

    if args.dry_run:
        print(f"\n=== DRY RUN ===")
        print(f"Would retry {len(rows)} rows.")
        print(f"Estimated runtime: ~{(len(rows) * (CLAUDE_PACING_SEC + 3)) / 60.0:.1f} min")
        print(f"Estimated cost:   ~${len(rows) * 0.002:.2f} (Claude Haiku 4.5 + web search)")
        print(f"\nRun with --apply to execute.")
        return

    # APPLY path
    anthropic_key = get_anthropic_key()
    if not anthropic_key:
        print("ERROR: Anthropic key missing.", file=sys.stderr)
        sys.exit(1)

    confirm = input(f"\nProceed to retry {len(rows)} rows? [y/N]: ")
    if confirm.strip().lower() != "y":
        print("Aborted.")
        return

    new_successes = retry_via_tier2(rows, anthropic_key)

    print(f"\n=== RETRY COMPLETE ===")
    print(f"New verified URLs: {new_successes}")
    print(f"\nNext: regenerate the review CSV from updated cache:")
    print(f"  python3 tools/enrich_urls_oneshot.py --dry-run")
    print(f"  (then review CSV, --commit as usual)")


if __name__ == "__main__":
    main()
