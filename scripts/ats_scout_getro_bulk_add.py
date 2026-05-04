#!/usr/bin/env python3
"""
ats_scout_getro_bulk_add.py — Process the 779 Getro VC companies through
the ATS detect/confirm flow directly via storage.py and emit a single rich
state CSV (ats_mapping_779.csv). Resumable via the existing
bulk_add_results.csv checkpoint shared with bulk_add_companies.py.

USAGE:
    python3 ats_scout_getro_bulk_add.py --sleep 0.5

INPUTS:
    /home/claude/pp-jobapp/workspace/all_ranked_779.csv   (read-only)
    /root/pp-jobapp/scripts/bulk_add_results.csv          (checkpoint, append)

OUTPUT:
    /root/pp-jobapp/workspace/ats_mapping_779.csv
"""
import argparse, csv, os, re, sys, time, urllib.parse

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
import storage

INPUT_CSV  = "/home/claude/pp-jobapp/workspace/all_ranked_779.csv"
OUTPUT_CSV = "/root/pp-jobapp/workspace/ats_mapping_779.csv"
CHECKPOINT = "/root/pp-jobapp/scripts/bulk_add_results.csv"
SCOUT_PY   = "/root/pp-jobapp/scripts/ats_scout.py"
DB_PATH    = "/root/pp-jobapp/workspace/jobapp.db"

NAME_SUFFIXES = (" ai", " labs", " inc", " incorporated", " technologies",
                 " hq", " co", " corp", " ltd", " llc", " gmbh")


def norm_name(s):
    s = (s or "").strip().lower()
    for _ in range(3):
        for suf in NAME_SUFFIXES:
            if s.endswith(suf):
                s = s[: -len(suf)].strip()
    return re.sub(r"[^a-z0-9]", "", s)


def load_companies_seed():
    """Parse COMPANIES list from ats_scout.py. Returns norm_name -> entry dict."""
    seed = {}
    if not os.path.exists(SCOUT_PY):
        return seed
    src = open(SCOUT_PY).read()
    m = re.search(r"COMPANIES\s*=\s*(\[.*?\])", src, re.DOTALL)
    if not m:
        return seed
    try:
        entries = eval(m.group(1))
    except Exception:
        return seed
    for e in entries:
        nm = e.get("name", "")
        if nm:
            seed[norm_name(nm)] = e
    return seed

OUTPUT_COLUMNS = [
    "rank", "company_name", "fit_score", "ats_provider", "ats_slug", "ats_url",
    "open_jobs_getro", "open_jobs_actual", "vc_count", "headcount_range",
    "funding_stage", "vertical_assigned", "prior_status",
]
CHECKPOINT_COLUMNS = ["company", "status", "ats", "slug", "total_jobs", "error"]


def derive_vertical(industries):
    s = (industries or "").lower()
    if any(k in s for k in (
        "cybersecurity", "computer & network security", "cloud security",
        "privacy and security", "network security",
    )):
        return "Security"
    if any(k in s for k in ("fintech", "financial services", "payments")):
        return "Fintech"
    if "marketplace" in s:
        return "Marketplace"
    if any(k in s for k in (
        "artificial intelligence", "ai/ml", "machine learning",
        "generative ai", "ai-powered", "foundational ai",
    )):
        return "AI"
    return "SaaS"


def slug_from_url(url):
    if not url:
        return ""
    try:
        host = urllib.parse.urlparse(url.strip()).hostname or ""
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    stem = host.split(".")[0] if host else ""
    return re.sub(r"[^a-z0-9-]", "", stem.lower())


def build_ats_url(ats, slug):
    if not slug:
        return ""
    if ats == "ashby":      return f"https://jobs.ashbyhq.com/{slug}"
    if ats == "greenhouse": return f"https://boards.greenhouse.io/{slug}"
    if ats == "lever":      return f"https://jobs.lever.co/{slug}"
    return ""


def load_checkpoint():
    """Map norm_name(company_name) -> latest checkpoint row dict."""
    by_name = {}
    if not os.path.exists(CHECKPOINT):
        return by_name
    with open(CHECKPOINT) as f:
        for row in csv.DictReader(f):
            by_name[norm_name(row["company"])] = row
    return by_name


def row_from_seed(rec, seed_entry):
    """Project a COMPANIES seed entry into ats_mapping schema."""
    out = base_mapping_row(rec)
    ats  = seed_entry.get("ats", "")
    slug = seed_entry.get("slug", "")
    out["prior_status"] = "already_added"
    out["ats_provider"] = ats if ats in ("ashby", "greenhouse", "lever") else "unknown"
    out["ats_slug"]     = slug
    out["ats_url"]      = build_ats_url(ats, slug)
    return out


def append_checkpoint(row):
    new_file = not os.path.exists(CHECKPOINT)
    with open(CHECKPOINT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CHECKPOINT_COLUMNS)
        if new_file:
            w.writeheader()
        w.writerow(row)


def base_mapping_row(rec):
    return {
        "rank":              rec["rank"],
        "company_name":      rec["company_name"].strip(),
        "fit_score":         rec["fit_score"],
        "ats_provider":      "unknown",
        "ats_slug":          "",
        "ats_url":           "",
        "open_jobs_getro":   rec.get("open_jobs_count", ""),
        "open_jobs_actual":  "",
        "vc_count":          rec["vc_count"],
        "headcount_range":   rec["headcount_range"],
        "funding_stage":     rec["funding_stage"],
        "vertical_assigned": derive_vertical(rec.get("industries", "")),
        "prior_status":      "new",
    }


def row_from_checkpoint(rec, chk):
    """Project a previously-processed checkpoint row into ats_mapping schema."""
    out = base_mapping_row(rec)
    status = (chk.get("status") or "").lower()
    ats    = chk.get("ats", "") or ""
    slug   = chk.get("slug", "") or ""
    total  = chk.get("total_jobs", "") or ""
    err    = (chk.get("error", "") or "")[:80]

    if status in ("added", "duplicate"):
        out["prior_status"]     = "already_added"
        out["ats_provider"]     = ats if ats in ("ashby", "greenhouse", "lever") else "unknown"
        out["ats_slug"]         = slug
        out["ats_url"]          = build_ats_url(ats, slug)
        out["open_jobs_actual"] = total
    elif status == "no_ats":
        out["prior_status"] = "previously_failed:no_ats"
    elif status == "http_error":
        out["prior_status"] = f"previously_failed:http_error:{err}"
    elif status == "exception":
        out["prior_status"] = f"previously_failed:exception:{err}"
    elif status == "would_add":
        out["prior_status"]     = "previously_failed:would_add(dry_run)"
        out["ats_provider"]     = ats if ats in ("ashby", "greenhouse", "lever") else "unknown"
        out["ats_slug"]         = slug
        out["ats_url"]          = build_ats_url(ats, slug)
        out["open_jobs_actual"] = total
    else:
        out["prior_status"] = f"previously_failed:{status or 'unknown'}"
    return out


def process_live(conn, rec, sleep_s):
    """Run detect (and register if hit) for one company. Returns (mapping_row, checkpoint_row)."""
    name = rec["company_name"].strip()
    out  = base_mapping_row(rec)
    company_url = rec.get("company_url", "") or None

    result = storage.detect_ats(name, company_url)
    if not result or not result.get("provider"):
        tried = result.get("tried_slugs", []) if result else []
        if result and result.get("dead_url"):
            err = "dead_url:" + ",".join(tried)
        else:
            err = ",".join(tried)
        chk = {"company": name, "status": "no_ats", "ats": "", "slug": "",
               "total_jobs": "", "error": err}
        return out, chk

    ats   = result["provider"]
    slug  = result["slug"]
    total = result.get("total_jobs") or 0

    out["ats_provider"]     = ats
    out["ats_slug"]         = slug
    out["ats_url"]          = build_ats_url(ats, slug)
    out["open_jobs_actual"] = total

    stage    = (rec.get("funding_stage") or "Unknown").strip() or "Unknown"
    vertical = out["vertical_assigned"]
    existing = storage.get_ats_endpoint(conn, ats, slug)
    if existing and existing["status"] == "active":
        chk = {"company": name, "status": "duplicate", "ats": ats, "slug": slug,
               "total_jobs": total, "error": f"ATS endpoint '{ats}/{slug}' already exists"}
        out["prior_status"] = "already_added"
        return out, chk
    try:
        storage.add_dashboard_company(
            conn, name=name, provider=ats, slug=slug,
            stage=stage, vertical=vertical, open_jobs_actual=total,
        )
    except Exception as e:
        chk = {"company": name, "status": "exception", "ats": ats, "slug": slug,
               "total_jobs": total, "error": f"{type(e).__name__}: {e}"}
        out["prior_status"] = f"previously_failed:exception:{str(e)[:80]}"
        return out, chk

    chk = {"company": name, "status": "added", "ats": ats, "slug": slug,
           "total_jobs": total, "error": ""}
    out["prior_status"] = "new"
    return out, chk


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sleep", type=float, default=0.5)
    p.add_argument("--limit", type=int, default=0, help="Process only first N rows (debugging)")
    args = p.parse_args()

    with open(INPUT_CSV) as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[:args.limit]
    print(f"Loaded {len(rows)} rows from {INPUT_CSV}")

    chk_index    = load_checkpoint()
    seed_index   = load_companies_seed()
    print(f"Checkpoint has {len(chk_index)} prior rows in {CHECKPOINT}")
    print(f"Seed (COMPANIES list) has {len(seed_index)} entries in {SCOUT_PY}")

    if not os.path.exists(DB_PATH):
        print(f"FATAL: SQLite DB not found at {DB_PATH}")
        sys.exit(1)
    conn = storage.connect(DB_PATH)

    mapping_rows = []
    counters = {"new_added": 0, "new_no_ats": 0, "new_exception": 0,
                "already_added": 0, "previously_failed": 0}

    try:
        for i, rec in enumerate(rows, 1):
            name = rec["company_name"].strip()
            key  = norm_name(name)

            # Priority 1: COMPANIES list in ats_scout.py (canonical registry)
            if key in seed_index:
                mr = row_from_seed(rec, seed_index[key])
                mapping_rows.append(mr)
                counters["already_added"] += 1
                print(f"[{i:4d}/{len(rows)}] = {name:35s} -> seed/{seed_index[key].get('ats','?')}/{seed_index[key].get('slug','?')}")
                continue

            # Priority 2: bulk_add_results.csv checkpoint
            if key in chk_index:
                mr = row_from_checkpoint(rec, chk_index[key])
                mapping_rows.append(mr)
                if mr["prior_status"] == "already_added":
                    counters["already_added"] += 1
                    marker = "="
                else:
                    counters["previously_failed"] += 1
                    marker = "."
                print(f"[{i:4d}/{len(rows)}] {marker} {name:35s} -> {mr['prior_status']}")
                continue

            try:
                mr, chk = process_live(conn, rec, args.sleep)
            except Exception as e:
                chk = {"company": name, "status": "exception", "ats": "", "slug": "",
                       "total_jobs": "", "error": f"{type(e).__name__}: {e}"}
                mr = base_mapping_row(rec)
                mr["prior_status"] = f"previously_failed:exception:{str(e)[:80]}"

            append_checkpoint(chk)
            mapping_rows.append(mr)

            status = chk["status"]
            if status == "added":
                counters["new_added"] += 1; marker = "+"
            elif status == "no_ats":
                counters["new_no_ats"] += 1; marker = "-"
            elif status == "exception":
                counters["new_exception"] += 1; marker = "X"
            elif status == "duplicate":
                counters["already_added"] += 1; marker = "="
            else:
                counters["new_exception"] += 1; marker = "?"

            extra = (f" ({chk['ats']}/{chk['slug']}, {chk['total_jobs']} jobs)"
                     if status in ("added", "duplicate") else "")
            print(f"[{i:4d}/{len(rows)}] {marker} {name:35s} -> {status}{extra}")

            time.sleep(args.sleep)
    finally:
        conn.close()

    # Write ats_mapping_779.csv
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        w.writeheader()
        for r in mapping_rows:
            w.writerow(r)
    print(f"\nWrote {len(mapping_rows)} rows -> {OUTPUT_CSV}")

    # Summary
    by_provider = {"ashby": 0, "greenhouse": 0, "lever": 0, "unknown": 0}
    for r in mapping_rows:
        by_provider[r["ats_provider"]] = by_provider.get(r["ats_provider"], 0) + 1
    tier1 = [r for r in mapping_rows if int(r["rank"]) <= 25]
    t1_known = sum(1 for r in tier1 if r["ats_provider"] != "unknown")

    print("\n=== SUMMARY ===")
    for k in ("new_added", "new_no_ats", "new_exception",
              "already_added", "previously_failed"):
        print(f"  {k:22s} {counters[k]}")
    print(f"\n  ATS provider breakdown (all 779):")
    total_known = sum(by_provider[k] for k in ("ashby", "greenhouse", "lever"))
    for k in ("ashby", "greenhouse", "lever", "unknown"):
        print(f"    {k:11s} {by_provider[k]}")
    pct = 100.0 * total_known / max(1, len(mapping_rows))
    print(f"    overall hit rate: {total_known}/{len(mapping_rows)} = {pct:.1f}%")
    t1_pct = 100.0 * t1_known / max(1, len(tier1))
    print(f"  Tier 1 (top 25) hit rate: {t1_known}/{len(tier1)} = {t1_pct:.1f}%")


if __name__ == "__main__":
    main()
