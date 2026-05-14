#!/usr/bin/env python3
"""
clear_notfound_for_committed.py
================================
Targeted cache clearer. Removes 'not_found' rows from ats_endpoints for
companies whose URLs were just populated by enrich_urls_oneshot.py --commit.

This is the precision alternative to running ats_scout.py with
--max-age-days 0, which would force re-probe of EVERY not_found row in the
DB (including the ones the recent backfill just confirmed are dead). By
contrast, this script only clears the cache for the small set of companies
we actually expect new probes to succeed for.

Workflow:
  1. python3 tools/enrich_urls_oneshot.py --dry-run
  2. (review CSV)
  3. python3 tools/enrich_urls_oneshot.py --commit
  4. python3 tools/clear_notfound_for_committed.py        <-- this script
  5. python3 scripts/ats_scout.py --discover --then-scan

Source of truth: workspace/enrichment_review.csv (action='commit' rows only).
The script reads which company_ids were committed and selectively clears
their ats_endpoints not_found entries.

Default behavior is DRY-RUN (preview only). Use --apply to actually delete.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path
from typing import List, Set


DB_PATH  = "/root/pp-jobapp/workspace/jobapp.db"
CSV_PATH = "/root/pp-jobapp/workspace/enrichment_review.csv"


def load_committed_ids(csv_path: str) -> Set[int]:
    """Read enrichment_review.csv and return company_ids that were committed."""
    committed: Set[int] = set()
    if not Path(csv_path).exists():
        print(f"ERROR: {csv_path} not found.", file=sys.stderr)
        print("Run enrich_urls_oneshot.py --dry-run + --commit first.", file=sys.stderr)
        sys.exit(1)

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["action"].strip().lower() == "commit":
                try:
                    committed.add(int(row["company_id"]))
                except (ValueError, KeyError):
                    continue
    return committed


def find_notfound_rows(db_path: str, company_ids: Set[int]) -> List[tuple]:
    """Find ats_endpoints rows with status='not_found' for the given companies."""
    if not company_ids:
        return []
    conn = sqlite3.connect(db_path)
    try:
        # SQLite has a 999 host-parameter cap; chunk if needed.
        results = []
        ids_list = list(company_ids)
        for i in range(0, len(ids_list), 900):
            chunk = ids_list[i:i + 900]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(f"""
                SELECT ae.id, ae.company_id, c.canonical_name, ae.provider, ae.last_checked_at
                FROM ats_endpoints ae
                JOIN companies c ON c.id = ae.company_id
                WHERE ae.status = 'not_found'
                  AND ae.company_id IN ({placeholders})
                ORDER BY c.canonical_name
            """, chunk).fetchall()
            results.extend(rows)
        return results
    finally:
        conn.close()


def delete_notfound_rows(db_path: str, endpoint_ids: List[int]) -> int:
    """Delete the given ats_endpoints rows. Returns count deleted."""
    if not endpoint_ids:
        return 0
    conn = sqlite3.connect(db_path)
    try:
        deleted = 0
        for i in range(0, len(endpoint_ids), 900):
            chunk = endpoint_ids[i:i + 900]
            placeholders = ",".join("?" * len(chunk))
            cur = conn.execute(
                f"DELETE FROM ats_endpoints WHERE id IN ({placeholders})",
                chunk,
            )
            deleted += cur.rowcount
        conn.commit()
        return deleted
    finally:
        conn.close()


def main():
    p = argparse.ArgumentParser(
        description="Clear not_found ATS cache for newly-enriched companies."
    )
    p.add_argument("--apply", action="store_true",
                   help="Actually delete rows (default: dry-run preview only).")
    p.add_argument("--db",  default=DB_PATH,  help=f"DB path (default: {DB_PATH})")
    p.add_argument("--csv", default=CSV_PATH, help=f"CSV path (default: {CSV_PATH})")
    args = p.parse_args()

    print("\n=== TARGETED NOT_FOUND CACHE CLEAR ===\n")

    # 1. Read committed IDs from CSV
    committed_ids = load_committed_ids(args.csv)
    print(f"Committed companies in CSV: {len(committed_ids)}")
    if not committed_ids:
        print("Nothing to clear.")
        return

    # 2. Find their not_found rows
    rows = find_notfound_rows(args.db, committed_ids)
    print(f"Matching not_found rows in ats_endpoints: {len(rows)}\n")

    if not rows:
        print("No not_found rows match. Nothing to clear.")
        print("(This is normal if these companies were never previously "
              "scanned, or have non-not_found endpoints already.)")
        return

    # 3. Provider breakdown for visibility
    by_provider: dict = {}
    for _, _, _, provider, _ in rows:
        by_provider[provider] = by_provider.get(provider, 0) + 1
    print("By provider:")
    for prov in sorted(by_provider, key=lambda k: -by_provider[k]):
        print(f"  {prov:20s} {by_provider[prov]}")
    print()

    # 4. Sample preview
    sample_n = min(10, len(rows))
    print(f"Sample (first {sample_n} of {len(rows)}):")
    print(f"  {'endpoint_id':>12}  {'company':40s}  {'provider':15s}  {'last_checked'}")
    for ep_id, comp_id, name, prov, last in rows[:sample_n]:
        name_disp = (name[:37] + "...") if name and len(name) > 40 else (name or "")
        print(f"  {ep_id:>12}  {name_disp:40s}  {prov:15s}  {last}")
    print()

    # 5. Apply or preview
    if not args.apply:
        print("=== DRY RUN (no changes made) ===")
        print(f"Would delete {len(rows)} not_found rows.")
        print("Re-run with --apply to actually delete:")
        print(f"  python3 tools/clear_notfound_for_committed.py --apply")
        return

    confirm = input(f"Delete {len(rows)} not_found rows? [y/N]: ")
    if confirm.strip().lower() != "y":
        print("Aborted.")
        return

    endpoint_ids = [r[0] for r in rows]
    deleted = delete_notfound_rows(args.db, endpoint_ids)

    print(f"\n=== CLEARED ===")
    print(f"Deleted {deleted} ats_endpoints rows.")
    print(f"\nNext: re-run discover to re-probe these companies with their new URLs.")
    print(f"  python3 scripts/ats_scout.py --discover --then-scan")
    print(f"  (default --max-age-days=30 is fine; the cache is now empty for "
          f"these companies)")


if __name__ == "__main__":
    main()
