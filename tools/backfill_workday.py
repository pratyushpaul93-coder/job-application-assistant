"""Backfill ATS endpoints for the 32 companies the 2026-05-07 audit
identified as 'has_provider:workday' in the unknown bucket.

For each, re-runs storage.detect_ats() (which now supports Workday) and
upserts the result into ats_endpoints. Records the outcome per company so
we can report yield against the 32-company expectation.

Idempotent — safe to re-run; upsert deduplicates on (provider, slug).
"""
from __future__ import annotations

import csv
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import storage  # noqa: E402

INPUT_CSV = os.path.join(ROOT, "workspace", "phase2_probe_results_20260507.csv")
DB_PATH = os.path.join(ROOT, "workspace", "jobapp.db")


def main():
    with open(INPUT_CSV) as f:
        rows = [r for r in csv.DictReader(f) if r["category"] == "has_provider:workday"]
    print(f"Backfilling {len(rows)} Workday-tagged companies from audit…\n")

    conn = storage.connect(DB_PATH)
    counts = Counter()
    per_company: list[tuple[str, str, str]] = []  # (name, outcome, detail)

    for i, row in enumerate(rows, 1):
        cid = int(row["id"])
        name = row["name"]
        url = row["url"]
        try:
            result = storage.detect_ats(name, url)
        except Exception as e:
            counts["error"] += 1
            per_company.append((name, "error", f"{type(e).__name__}: {e}"))
            print(f"[{i:2d}/{len(rows)}] {name}: ERROR — {type(e).__name__}: {e}")
            continue

        if not result or not result.get("provider"):
            counts["miss"] += 1
            per_company.append((name, "miss", ""))
            print(f"[{i:2d}/{len(rows)}] {name}: MISS")
            continue

        if result.get("dead_url"):
            counts["dead_url"] += 1
            per_company.append((name, "dead_url", ""))
            print(f"[{i:2d}/{len(rows)}] {name}: dead URL")
            continue

        provider = result["provider"]
        slug = result["slug"]
        total = result.get("total_jobs")
        ats_url = storage.ats_url(provider, slug)
        try:
            storage.upsert_ats_endpoint(
                conn, cid,
                provider=provider, slug=slug,
                ats_url=ats_url,
                status="active",
                open_jobs_actual=total if isinstance(total, int) else None,
                raw_metadata={"found_via": result.get("found_via", ""), "backfill": "workday_2026-05-08"},
            )
            conn.commit()
            counts[f"hit:{provider}"] += 1
            per_company.append((name, f"hit:{provider}", f"{slug} (total={total})"))
            print(f"[{i:2d}/{len(rows)}] {name}: HIT {provider}/{slug}  total={total}")
        except Exception as e:
            counts["upsert_error"] += 1
            per_company.append((name, "upsert_error", f"{type(e).__name__}: {e}"))
            print(f"[{i:2d}/{len(rows)}] {name}: UPSERT ERROR — {type(e).__name__}: {e}")

    conn.close()
    print()
    print("## Backfill summary")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    print()
    print(f"Hits / total: {sum(v for k, v in counts.items() if k.startswith('hit'))} / {len(rows)}")


if __name__ == "__main__":
    main()
