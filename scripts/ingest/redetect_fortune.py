#!/usr/bin/env python3
"""Re-run ATS detection on companies of a given source that have no active ATS.

After the 2026-05-12 _http_get_text header upgrade (full browser headers
including Sec-Fetch-* + Accept-Language), several enterprise careers pages
that were Cloudflare-403'd before are now reachable. This script targets a
specific source's failure cohort so we get a clean before/after delta without
spending hours re-checking the whole DB.

Usage:
    python3 -m ingest.redetect_fortune                              # default: fortune_1000
    python3 -m ingest.redetect_fortune --source builtin_bptw        # Built In cos
    python3 -m ingest.redetect_fortune --source fortune_1000 --limit 20
    python3 -m ingest.redetect_fortune --workers 8                  # default 8
"""
from __future__ import annotations
import argparse, os, sys, time
import concurrent.futures as cf

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)
import storage  # noqa: E402

DB_PATH = "/root/pp-jobapp/workspace/jobapp.db"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="fortune_1000",
                    help="company_sources.source_type to redetect (default: fortune_1000)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    conn = storage.connect(DB_PATH)
    rows = conn.execute("""
        SELECT c.id, c.canonical_name, c.website_url, c.employee_count
        FROM companies c
        JOIN company_sources cs ON cs.company_id=c.id AND cs.source_type=?
        WHERE c.active=1 AND c.website_url IS NOT NULL AND c.website_url != ''
          AND NOT EXISTS (SELECT 1 FROM ats_endpoints e
                          WHERE e.company_id=c.id AND e.status='active')
        ORDER BY c.employee_count DESC
    """, (args.source,)).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    print(f"[redetect source={args.source}] targets={len(rows)} workers={args.workers}", flush=True)

    def detect(row):
        try:
            return row["id"], row["canonical_name"], storage.detect_ats(
                row["canonical_name"], row["website_url"]
            ), None
        except Exception as e:
            return row["id"], row["canonical_name"], None, f"{type(e).__name__}: {e}"

    hits = 0
    misses = 0
    errors = 0
    by_provider = {}

    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, fut in enumerate(cf.as_completed([ex.submit(detect, r) for r in rows]), 1):
            cid, name, result, err = fut.result()
            if err:
                errors += 1
                continue
            if result and not result.get("dead_url") and result.get("provider"):
                prov = result["provider"]
                slug = result["slug"]
                # Upsert the endpoint as active (delete prior not_found first)
                try:
                    conn.execute(
                        "DELETE FROM ats_endpoints WHERE company_id=? AND status='not_found'",
                        (cid,),
                    )
                    storage.upsert_ats_endpoint(
                        conn, cid, provider=prov, slug=slug, status="active",
                        open_jobs_actual=result.get("total_jobs"),
                        raw_metadata={"detected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                      "found_via": result.get("found_via"),
                                      "sample_titles": result.get("sample_titles", [])},
                    )
                    conn.commit()
                    hits += 1
                    by_provider[prov] = by_provider.get(prov, 0) + 1
                    print(f"  HIT  {name[:35]:<35s} → {prov}/{slug}  ({result.get('total_jobs','?')} jobs)", flush=True)
                except Exception as e:
                    errors += 1
                    print(f"  DB ERR {name!r}: {e}", flush=True)
            else:
                misses += 1
            if i % 50 == 0:
                rate = i / (time.time() - t0)
                eta = (len(rows) - i) / max(rate, 0.01)
                print(f"  ── progress {i}/{len(rows)} hits={hits} misses={misses} errors={errors}  "
                      f"rate={rate:.2f}/s eta={eta/60:.1f}m", flush=True)

    print(f"\n[redetect_fortune] DONE  hits={hits} misses={misses} errors={errors} "
          f"elapsed={(time.time()-t0)/60:.1f}m", flush=True)
    print("  by provider:", by_provider)


if __name__ == "__main__":
    main()
