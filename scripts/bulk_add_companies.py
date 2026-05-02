#!/usr/bin/env python3
"""
bulk_add_companies.py — Bulk-feed company names through OpenClaw's existing
add_company endpoints. Resumable via a CSV checkpoint.

USAGE:
    python3 bulk_add_companies.py a16z_companies.txt
    python3 bulk_add_companies.py a16z_companies.txt --stage Unknown --vertical SaaS
    python3 bulk_add_companies.py a16z_companies.txt --sleep 2.0
    python3 bulk_add_companies.py a16z_companies.txt --dry-run     # detect only, no confirm

OUTPUT:
    bulk_add_results.csv — appended after every company. Re-runs skip names already in this file.
        company, status, ats, slug, total_jobs, error
        status ∈ {added, no_ats, duplicate, http_error, exception}
"""
import argparse, csv, json, os, sys, time, urllib.error, urllib.request

DASHBOARD = "http://localhost:5000"
RESULTS_CSV = "/root/pp-jobapp/scripts/bulk_add_results.csv"
COLUMNS = ["company", "status", "ats", "slug", "total_jobs", "error"]


def post(path, payload, timeout=30):
    """POST JSON; returns (status_code, parsed_body_or_none)."""
    req = urllib.request.Request(
        DASHBOARD + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = None
        return e.code, body
    except Exception as e:
        return None, {"error": f"{type(e).__name__}: {e}"}


def load_checkpoint():
    """Returns set of company names already processed."""
    done = set()
    if os.path.exists(RESULTS_CSV):
        with open(RESULTS_CSV) as f:
            reader = csv.DictReader(f)
            for row in reader:
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


def process(name, stage, vertical, dry_run):
    """Detect ATS for one company; if found and not dry-run, confirm."""
    code, body = post("/api/add_company/detect", {"name": name})
    if code != 200 or not body:
        return {
            "company": name, "status": "http_error", "ats": "", "slug": "",
            "total_jobs": "", "error": f"detect HTTP {code}: {body}",
        }
    if not body.get("found"):
        return {
            "company": name, "status": "no_ats", "ats": "", "slug": "",
            "total_jobs": "", "error": "tried " + ",".join(body.get("tried_slugs", [])),
        }
    ats = body["ats"]
    slug = body["slug"]
    total = body.get("total_jobs", 0)

    if dry_run:
        return {
            "company": name, "status": "would_add", "ats": ats, "slug": slug,
            "total_jobs": total, "error": "",
        }

    code, body = post("/api/add_company/confirm", {
        "name": name, "ats": ats, "slug": slug, "stage": stage, "vertical": vertical,
    })
    if code == 200 and body and body.get("ok"):
        return {
            "company": name, "status": "added", "ats": ats, "slug": slug,
            "total_jobs": total, "error": "",
        }
    if code == 409:
        return {
            "company": name, "status": "duplicate", "ats": ats, "slug": slug,
            "total_jobs": total, "error": (body or {}).get("error", ""),
        }
    return {
        "company": name, "status": "http_error", "ats": ats, "slug": slug,
        "total_jobs": total, "error": f"confirm HTTP {code}: {body}",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input_file", help="Newline-delimited list of company names")
    p.add_argument("--sleep", type=float, default=1.5, help="Seconds between detect calls")
    p.add_argument("--stage", default="Unknown", help="Default stage for added companies")
    p.add_argument("--vertical", default="SaaS", help="Default vertical for added companies")
    p.add_argument("--dry-run", action="store_true", help="Detect only; don't confirm")
    args = p.parse_args()

    with open(args.input_file) as f:
        names = [line.strip() for line in f if line.strip()]
    print(f"Loaded {len(names)} names from {args.input_file}")

    done = load_checkpoint()
    if done:
        print(f"Resuming — {len(done)} already processed in {RESULTS_CSV}")

    counts = {"added": 0, "no_ats": 0, "duplicate": 0, "http_error": 0,
              "exception": 0, "would_add": 0, "skipped": 0}

    for i, name in enumerate(names, 1):
        if name.lower() in done:
            counts["skipped"] += 1
            continue
        try:
            row = process(name, args.stage, args.vertical, args.dry_run)
        except Exception as e:
            row = {"company": name, "status": "exception", "ats": "", "slug": "",
                   "total_jobs": "", "error": f"{type(e).__name__}: {e}"}
        append_result(row)
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        marker = {"added": "✓", "would_add": "·", "no_ats": "—", "duplicate": "=",
                  "http_error": "!", "exception": "X"}.get(row["status"], "?")
        print(f"[{i:4d}/{len(names)}] {marker} {name:35s} → {row['status']}"
              + (f" ({row['ats']}/{row['slug']}, {row['total_jobs']} jobs)"
                 if row["status"] in ("added", "would_add") else ""))
        time.sleep(args.sleep)

    print("\n=== SUMMARY ===")
    for k, v in counts.items():
        if v:
            print(f"  {k:12s} {v}")
    print(f"\nResults: {RESULTS_CSV}")


if __name__ == "__main__":
    main()
