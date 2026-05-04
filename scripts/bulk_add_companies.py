#!/usr/bin/env python3
"""
bulk_add_companies.py — Bulk-feed company names through the ATS detect/confirm
flow directly via storage.py. Resumable via a CSV checkpoint.

USAGE:
    python3 bulk_add_companies.py a16z_companies.txt
    python3 bulk_add_companies.py a16z_companies.txt --stage Unknown --vertical SaaS
    python3 bulk_add_companies.py a16z_companies.txt --sleep 2.0
    python3 bulk_add_companies.py a16z_companies.txt --dry-run     # detect only

OUTPUT:
    bulk_add_results.csv — appended after every company. Re-runs skip names already in this file.
        company, status, ats, slug, total_jobs, error
        status ∈ {added, no_ats, duplicate, exception, would_add}
"""
import argparse, csv, os, sys, time

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
import storage

DB_PATH = "/root/pp-jobapp/workspace/jobapp.db"
RESULTS_CSV = "/root/pp-jobapp/scripts/bulk_add_results.csv"
COLUMNS = ["company", "status", "ats", "slug", "total_jobs", "error"]


def load_checkpoint():
    """Returns set of company names already processed."""
    done = set()
    if os.path.exists(RESULTS_CSV):
        with open(RESULTS_CSV) as f:
            for row in csv.DictReader(f):
                done.add(row["company"].strip().lower())
    return done


def append_result(row):
    """Append one row to the CSV, creating header if needed."""
    new_file = not os.path.exists(RESULTS_CSV)
    with open(RESULTS_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new_file:
            w.writeheader()
        w.writerow(row)


def process(conn, name, stage, vertical, dry_run):
    """Detect ATS for one company; if found and not dry-run, register it."""
    result = storage.detect_ats(name)
    if not result or not result.get("provider"):
        return {
            "company": name, "status": "no_ats", "ats": "", "slug": "",
            "total_jobs": "",
            "error": "tried " + ",".join(result.get("tried_slugs", []) if result else []),
        }
    ats = result["provider"]
    slug = result["slug"]
    total = result.get("total_jobs", 0)

    if dry_run:
        return {
            "company": name, "status": "would_add", "ats": ats, "slug": slug,
            "total_jobs": total, "error": "",
        }

    existing = storage.get_ats_endpoint(conn, ats, slug)
    if existing and existing["status"] == "active":
        return {
            "company": name, "status": "duplicate", "ats": ats, "slug": slug,
            "total_jobs": total, "error": f"ATS endpoint '{ats}/{slug}' already exists",
        }
    storage.add_dashboard_company(
        conn, name=name, provider=ats, slug=slug,
        stage=stage, vertical=vertical, open_jobs_actual=total,
    )
    return {
        "company": name, "status": "added", "ats": ats, "slug": slug,
        "total_jobs": total, "error": "",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input_file", help="Newline-delimited list of company names")
    p.add_argument("--sleep", type=float, default=1.5, help="Seconds between detect calls")
    p.add_argument("--stage", default="Unknown", help="Default stage for added companies")
    p.add_argument("--vertical", default="SaaS", help="Default vertical for added companies")
    p.add_argument("--dry-run", action="store_true", help="Detect only; don't register")
    args = p.parse_args()

    with open(args.input_file) as f:
        names = [line.strip() for line in f if line.strip()]
    print(f"Loaded {len(names)} names from {args.input_file}")

    done = load_checkpoint()
    if done:
        print(f"Resuming — {len(done)} already processed in {RESULTS_CSV}")

    if not os.path.exists(DB_PATH):
        print(f"FATAL: SQLite DB not found at {DB_PATH}")
        sys.exit(1)
    conn = storage.connect(DB_PATH)

    counts = {"added": 0, "no_ats": 0, "duplicate": 0,
              "exception": 0, "would_add": 0, "skipped": 0}

    try:
        for i, name in enumerate(names, 1):
            if name.lower() in done:
                counts["skipped"] += 1
                continue
            try:
                row = process(conn, name, args.stage, args.vertical, args.dry_run)
            except Exception as e:
                row = {"company": name, "status": "exception", "ats": "", "slug": "",
                       "total_jobs": "", "error": f"{type(e).__name__}: {e}"}
            append_result(row)
            counts[row["status"]] = counts.get(row["status"], 0) + 1
            marker = {"added": "+", "would_add": ".", "no_ats": "-", "duplicate": "=",
                      "exception": "X"}.get(row["status"], "?")
            print(f"[{i:4d}/{len(names)}] {marker} {name:35s} -> {row['status']}"
                  + (f" ({row['ats']}/{row['slug']}, {row['total_jobs']} jobs)"
                     if row["status"] in ("added", "would_add", "duplicate") else ""))
            time.sleep(args.sleep)
    finally:
        conn.close()

    print("\n=== SUMMARY ===")
    for k, v in counts.items():
        if v:
            print(f"  {k:12s} {v}")
    print(f"\nResults: {RESULTS_CSV}")


if __name__ == "__main__":
    main()
