#!/usr/bin/env python3
"""
backfill_ats_detection.py — run discover_phase() against all eligible
companies in the DB to populate ats_endpoints.

USAGE (typical overnight run):
    cd /root/pp-jobapp
    tmux new -d -s backfill 'python3 tools/backfill_ats_detection.py 2>&1 | tee workspace/backfill_$(date +%Y%m%d_%H%M).log'
    # ... go to sleep ...
    tmux attach -t backfill   # to check progress
    # OR
    tail -f workspace/backfill_*.log

USAGE (test run):
    python3 tools/backfill_ats_detection.py --limit 50 --dry-run

DESIGN NOTES
- Resumable: discover_phase() filters out companies with active or
  recent not_found endpoints, so killing and restarting picks up where
  it left off. last_checked_at acts as the resumption pointer.
- Conservative defaults: max_age_days=30 means companies marked
  not_found in the last 30 days will not be re-tried in this run.
- Pre-flight: counts eligible companies + semantic twins before
  starting so you know roughly what to expect.
- Periodic checkpointing: prints a heartbeat every BATCH_SIZE companies.
"""
import argparse
import datetime
import os
import sqlite3
import sys
import time
from pathlib import Path

# Line-buffer stdout so heartbeats are visible live through `tee` (no TTY → block buffer otherwise).
sys.stdout.reconfigure(line_buffering=True)

# Add scripts/ to path so we can import scout and storage
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import storage          # noqa: E402
import ats_scout        # noqa: E402

DB_PATH = "/root/pp-jobapp/workspace/jobapp.db"
BATCH_SIZE = 25  # heartbeat frequency (matches discover_phase progress prints)


def preflight(conn) -> dict:
    """Count what we're about to process. Returns a stats dict."""
    c = conn.cursor()

    # Companies eligible for discovery (active, no active endpoint, no recent not_found)
    c.execute("""
        SELECT COUNT(*) FROM companies c
        WHERE c.active = 1
          AND NOT EXISTS (
              SELECT 1 FROM ats_endpoints e
              WHERE e.company_id = c.id
                AND e.status IN ('active', 'skipped')
          )
          AND NOT EXISTS (
              SELECT 1 FROM ats_endpoints e
              WHERE e.company_id = c.id
                AND e.status = 'not_found'
                AND e.last_checked_at > datetime('now', '-30 days')
          )
    """)
    eligible = c.fetchone()[0]

    # Of those, how many have a website_url (probable hit rate is higher)
    c.execute("""
        SELECT COUNT(*) FROM companies c
        WHERE c.active = 1
          AND c.website_url IS NOT NULL AND c.website_url != ''
          AND NOT EXISTS (
              SELECT 1 FROM ats_endpoints e
              WHERE e.company_id = c.id AND e.status IN ('active', 'skipped')
          )
          AND NOT EXISTS (
              SELECT 1 FROM ats_endpoints e
              WHERE e.company_id = c.id AND e.status = 'not_found'
                AND e.last_checked_at > datetime('now', '-30 days')
          )
    """)
    eligible_with_url = c.fetchone()[0]

    # Currently active endpoints (baseline)
    c.execute("SELECT COUNT(*) FROM ats_endpoints WHERE status = 'active'")
    current_active = c.fetchone()[0]

    # Semantic twin estimate: companies whose first 8 alnum chars of normalized_name
    # match another company's. Rough heuristic, not exact, but signals scale.
    c.execute("""
        SELECT COUNT(*) FROM (
            SELECT substr(normalized_name, 1, 8) AS prefix
            FROM companies WHERE active = 1
            GROUP BY prefix HAVING COUNT(*) > 1
        )
    """)
    twin_prefix_groups = c.fetchone()[0]

    return {
        "eligible": eligible,
        "eligible_with_url": eligible_with_url,
        "current_active_endpoints": current_active,
        "twin_prefix_groups_approx": twin_prefix_groups,
    }


def main():
    parser = argparse.ArgumentParser(description="Backfill ATS endpoint discovery")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max companies to process (default: all eligible)")
    parser.add_argument("--max-age-days", type=int, default=30,
                        help="Re-try not_found companies older than this (default: 30)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run preflight only, don't actually call discover_phase")
    parser.add_argument("--db", default=DB_PATH, help="Path to SQLite DB")
    args = parser.parse_args()

    started_at = datetime.datetime.now()
    print(f"=" * 70)
    print(f"ATS Detection Backfill")
    print(f"Started: {started_at.isoformat()}")
    print(f"DB: {args.db}")
    print(f"Limit: {args.limit if args.limit else 'all eligible'}")
    print(f"Max age days: {args.max_age_days}")
    print(f"Dry run: {args.dry_run}")
    print(f"=" * 70)

    if not os.path.exists(args.db):
        print(f"FATAL: DB not found at {args.db}", flush=True)
        sys.exit(1)

    conn = storage.connect(args.db)
    try:
        # Preflight
        stats = preflight(conn)
        print()
        print(f"PRE-FLIGHT STATS")
        print(f"-" * 40)
        print(f"  Eligible companies:           {stats['eligible']:>5}")
        print(f"  Eligible WITH website_url:    {stats['eligible_with_url']:>5}")
        print(f"  Eligible WITHOUT website_url: {stats['eligible'] - stats['eligible_with_url']:>5}")
        print(f"  Current active endpoints:     {stats['current_active_endpoints']:>5}")
        print(f"  Approx twin-prefix groups:    {stats['twin_prefix_groups_approx']:>5}")
        print()

        # Estimate runtime: ~2-4 sec/company average (varies hugely with hits vs misses)
        n_to_run = min(stats["eligible"], args.limit) if args.limit else stats["eligible"]
        est_min = (n_to_run * 3) // 60
        est_max = (n_to_run * 6) // 60
        print(f"  Estimated runtime: {est_min}-{est_max} minutes (very rough)")
        print()

        if args.dry_run:
            print("DRY RUN — exiting without calling discover_phase")
            return

        if n_to_run == 0:
            print("Nothing to do — exiting.")
            return

        # Run it
        print(f"Calling ats_scout.discover_phase(limit={args.limit}, max_age_days={args.max_age_days})")
        print(f"Heartbeats every {BATCH_SIZE} companies (or whatever discover_phase prints)")
        print()
        result = ats_scout.discover_phase(
            conn,
            limit=args.limit,
            max_age_days=args.max_age_days,
        )

        # Summary
        ended_at = datetime.datetime.now()
        elapsed = ended_at - started_at
        print()
        print(f"=" * 70)
        print(f"DONE")
        print(f"=" * 70)
        print(f"  Started:  {started_at.isoformat()}")
        print(f"  Finished: {ended_at.isoformat()}")
        print(f"  Elapsed:  {elapsed}")
        print()
        print(f"  Results:")
        print(f"    Tried:     {result.get('tried', 0):>5}")
        print(f"    Hits:      {result.get('hits', 0):>5}")
        print(f"    Misses:    {result.get('misses', 0):>5}")
        print(f"    Dead URLs: {result.get('dead_urls', 0):>5}")
        print(f"    Errors:    {result.get('errors', 0):>5}")
        print()
        if result.get("by_provider"):
            print(f"  By provider:")
            for prov, n in sorted(result["by_provider"].items(), key=lambda x: -x[1]):
                print(f"    {prov:<20} {n:>5}")
        print()

        # Final endpoint count for at-a-glance comparison
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM ats_endpoints WHERE status = 'active'")
        new_active = c.fetchone()[0]
        delta = new_active - stats["current_active_endpoints"]
        print(f"  Active endpoints: {stats['current_active_endpoints']} -> {new_active}  (+{delta})")
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
