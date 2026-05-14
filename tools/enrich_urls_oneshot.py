#!/usr/bin/env python3
"""
enrich_urls_oneshot.py
======================
One-shot URL enrichment for companies in jobapp.db with NULL website_url.

Workflow:
  Phase 1 (dry-run):  python3 tools/enrich_urls_oneshot.py --dry-run
                      -> writes workspace/enrichment_review.csv
                      -> NO database writes (jobapp.db.companies untouched)
                      -> populates enrichment_cache for resumability

  Phase 2 (review):   you eyeball the CSV, edit the `action` column to
                      'commit' / 'skip' for any rows you want to override

  Phase 3 (commit):   python3 tools/enrich_urls_oneshot.py --commit
                      -> reads workspace/enrichment_review.csv
                      -> updates companies.website_url for action='commit' rows

The cache (enrichment_cache table) makes the dry-run resumable: if it crashes
or you re-run, cached results are reused so you don't pay for them twice.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

# Make sibling import work whether script is run from project root or tools/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from url_enrichment import (  # noqa: E402
    EnrichmentResult, normalize_name, normalize_url,
    cache_get, cache_put,
    deepseek_enrich_many, claude_websearch_many,
    head_verify, head_status_ok,
)
from keys import get_anthropic_key, get_deepseek_key  # noqa: E402


DB_PATH       = "/root/pp-jobapp/workspace/jobapp.db"
CSV_PATH      = "/root/pp-jobapp/workspace/enrichment_review.csv"

CSV_COLUMNS = [
    "company_id", "company_name", "proposed_url", "source",
    "confidence", "head_status", "reasoning", "action",
]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def fetch_companies_missing_url(db_path: str) -> List[Dict[str, Any]]:
    """Return active companies with NULL or empty website_url."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("""
            SELECT id, canonical_name
            FROM companies
            WHERE (website_url IS NULL OR website_url = '')
              AND active = 1
            ORDER BY id
        """).fetchall()
        return [{"id": r[0], "name": r[1]} for r in rows]
    finally:
        conn.close()


def update_company_url(db_path: str, company_id: int, url: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE companies SET website_url = ? WHERE id = ?",
                     (url, company_id))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Action recommendation
# ---------------------------------------------------------------------------

def recommend_action(result: EnrichmentResult) -> str:
    """
    Auto-set the CSV action field based on confidence + verification.
      'commit' - high confidence, verified
      'review' - medium/low confidence OR tier-2 result (manual eyeball)
      'skip'   - no URL found
    """
    if result.url is None:
        return "skip"
    if result.confidence == "high" and head_status_ok(result.head_status) \
            and result.source == "deepseek":
        return "commit"
    return "review"


# ---------------------------------------------------------------------------
# Dry-run pipeline
# ---------------------------------------------------------------------------

def run_dry(db_path: str, csv_path: str, limit: Optional[int] = None) -> None:
    print("\n=== ENRICHMENT DRY-RUN ===")

    deepseek_key  = get_deepseek_key()
    anthropic_key = get_anthropic_key()

    if not deepseek_key:
        print("ERROR: DeepSeek key not found in /root/.openclaw/openclaw.json")
        sys.exit(1)
    if not anthropic_key:
        print("WARNING: Anthropic key not found in auth-profiles.json; tier-2 (web search) will be skipped")

    # 1. Fetch companies needing enrichment
    companies = fetch_companies_missing_url(db_path)
    if limit:
        companies = companies[:limit]
    print(f"Companies missing website_url: {len(companies)}")
    if not companies:
        print("Nothing to do.")
        return

    # 2. Partition into cached vs needs-fetch
    cached_results: Dict[int, EnrichmentResult] = {}
    needs_tier1: List[Dict[str, Any]] = []
    for c in companies:
        cached = cache_get(db_path, c["name"])
        if cached is not None:
            cached_results[c["id"]] = cached
        else:
            needs_tier1.append(c)

    print(f"  cached:        {len(cached_results)}")
    print(f"  needs tier-1:  {len(needs_tier1)}")

    # 3. Tier 1: DeepSeek
    tier1_results: Dict[int, EnrichmentResult] = {}
    if needs_tier1:
        print("\n--- Tier 1: DeepSeek (no web search) ---")
        names = [c["name"] for c in needs_tier1]
        ids   = [c["id"]   for c in needs_tier1]

        def progress(done, total):
            print(f"  batch {done}/{total} complete", flush=True)

        t0 = time.time()
        ds_raw = deepseek_enrich_many(names, deepseek_key, progress_callback=progress)
        print(f"  DeepSeek done in {time.time() - t0:.1f}s")

        # Verify URLs and stash results
        print("--- HEAD verification ---")
        for cid, name, ds in zip(ids, names, ds_raw):
            url = normalize_url(ds.get("url") or "")
            conf = ds.get("confidence", "unknown")
            reasoning = ds.get("reasoning", "")
            head_status: Optional[int] = None

            if url and conf in ("high", "medium"):
                head_status = head_verify(url)

            verified = url and head_status_ok(head_status)
            tier1_results[cid] = EnrichmentResult(
                name_original=name,
                url=url if verified else None,
                source="deepseek" if verified else "deepseek_unverified",
                confidence=conf,
                head_status=head_status,
                reasoning=reasoning,
            )

    # 4. Tier 2 candidates: tier-1 returned no verified URL
    tier2_inputs = [(cid, r) for cid, r in tier1_results.items() if r.url is None]
    tier2_results: Dict[int, EnrichmentResult] = {}

    if tier2_inputs and anthropic_key:
        print(f"\n--- Tier 2: Claude Haiku + web_search ({len(tier2_inputs)} companies) ---")
        names = [r.name_original for _, r in tier2_inputs]
        ids   = [cid            for cid, _ in tier2_inputs]

        def progress2(done, total):
            print(f"  {done}/{total} complete", flush=True)

        t0 = time.time()
        cl_raw = claude_websearch_many(names, anthropic_key, progress_callback=progress2)
        print(f"  Claude done in {time.time() - t0:.1f}s")

        print("--- HEAD verification (tier 2) ---")
        for cid, name, cl in zip(ids, names, cl_raw):
            url = normalize_url(cl.get("url") or "")
            conf = cl.get("confidence", "unknown")
            reasoning = cl.get("reasoning", "")
            head_status: Optional[int] = None
            if url:
                head_status = head_verify(url)

            verified = url and head_status_ok(head_status)
            tier2_results[cid] = EnrichmentResult(
                name_original=name,
                url=url if verified else None,
                source="claude_websearch" if verified else "claude_websearch_unverified",
                confidence=conf,
                head_status=head_status,
                reasoning=reasoning,
            )

    # 5. Merge final results, write to cache, write CSV
    all_results: Dict[int, EnrichmentResult] = {}
    all_results.update(cached_results)
    for cid, r in tier1_results.items():
        if cid in tier2_results:
            t2 = tier2_results[cid]
            # Use tier-2 if it succeeded, else keep tier-1 (with reason context)
            all_results[cid] = t2 if t2.url else t2  # tier-2 result either way (it ran)
        else:
            all_results[cid] = r

    # Persist to cache (only the ones we just fetched, not cache hits)
    fresh_ids = set(tier1_results.keys()) | set(tier2_results.keys())
    for cid, r in all_results.items():
        if cid in fresh_ids:
            cache_put(db_path, r)

    # 6. Write CSV
    company_lookup = {c["id"]: c["name"] for c in companies}
    rows_for_csv = []
    counts = {"commit": 0, "review": 0, "skip": 0}
    for cid in sorted(all_results.keys()):
        r = all_results[cid]
        action = recommend_action(r)
        counts[action] += 1
        rows_for_csv.append({
            "company_id":   cid,
            "company_name": company_lookup.get(cid, r.name_original),
            "proposed_url": r.url or "",
            "source":       r.source,
            "confidence":   r.confidence,
            "head_status":  r.head_status if r.head_status is not None else "",
            "reasoning":    r.reasoning,
            "action":       action,
        })

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows_for_csv)

    print(f"\n=== DRY RUN COMPLETE ===")
    print(f"Wrote: {csv_path}")
    print(f"  action=commit:  {counts['commit']:5d}  (will be applied on --commit)")
    print(f"  action=review:  {counts['review']:5d}  (manual eyeball; edit action to 'commit' or 'skip')")
    print(f"  action=skip:    {counts['skip']:5d}  (no URL found)")
    print(f"\nNext steps:")
    print(f"  1. Review:  less {csv_path}")
    print(f"  2. Edit any 'review' rows to 'commit' or 'skip' as desired")
    print(f"  3. Apply:   python3 tools/enrich_urls_oneshot.py --commit")


# ---------------------------------------------------------------------------
# Commit phase
# ---------------------------------------------------------------------------

def run_commit(db_path: str, csv_path: str) -> None:
    print("\n=== ENRICHMENT COMMIT ===")
    if not Path(csv_path).exists():
        print(f"ERROR: {csv_path} not found. Run --dry-run first.")
        sys.exit(1)

    rows: List[Dict[str, Any]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    to_commit = [r for r in rows if r["action"].strip().lower() == "commit"
                 and r["proposed_url"].strip()]
    print(f"Total CSV rows:        {len(rows)}")
    print(f"Rows to commit:        {len(to_commit)}")
    print(f"Rows to skip/review:   {len(rows) - len(to_commit)}")

    if not to_commit:
        print("Nothing to commit.")
        return

    confirm = input(f"\nProceed to update {len(to_commit)} companies.website_url? [y/N]: ")
    if confirm.strip().lower() != "y":
        print("Aborted.")
        return

    updated = 0
    for r in to_commit:
        try:
            cid = int(r["company_id"])
        except ValueError:
            print(f"  SKIP bad id: {r['company_id']}")
            continue
        url = r["proposed_url"].strip()
        update_company_url(db_path, cid, url)
        updated += 1

    print(f"\n=== COMMIT COMPLETE ===")
    print(f"Updated {updated} companies.")
    print(f"\nNext: re-run discover with --max-age-days 0 to re-probe these companies:")
    print(f"  python3 scripts/ats_scout.py --max-age-days 0")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="One-shot URL enrichment for jobapp.db")
    p.add_argument("--dry-run", action="store_true",
                   help="Run enrichment, write CSV, no DB updates to companies table")
    p.add_argument("--commit",  action="store_true",
                   help="Read reviewed CSV and update companies.website_url")
    p.add_argument("--db",      default=DB_PATH, help=f"DB path (default: {DB_PATH})")
    p.add_argument("--csv",     default=CSV_PATH, help=f"CSV path (default: {CSV_PATH})")
    p.add_argument("--limit",   type=int, default=None,
                   help="Limit to first N companies (for testing)")
    args = p.parse_args()

    if args.dry_run == args.commit:
        p.error("Specify exactly one of --dry-run or --commit")

    if args.dry_run:
        run_dry(args.db, args.csv, limit=args.limit)
    else:
        run_commit(args.db, args.csv)


if __name__ == "__main__":
    main()
