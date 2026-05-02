#!/usr/bin/env python3
"""
ats_scout_getro_bulk_add.py — Process the 779 Getro VC companies through
the dashboard's add_company flow and emit a single rich state CSV
(ats_mapping_779.csv). Resumable via the existing bulk_add_results.csv
checkpoint shared with bulk_add_companies.py.

USAGE:
    python3 ats_scout_getro_bulk_add.py --sleep 0.5

INPUTS:
    /home/claude/pp-jobapp/workspace/all_ranked_779.csv   (read-only)
    /root/pp-jobapp/scripts/bulk_add_results.csv          (checkpoint, append)

OUTPUT:
    /root/pp-jobapp/workspace/ats_mapping_779.csv
"""
import argparse, csv, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

INPUT_CSV  = "/home/claude/pp-jobapp/workspace/all_ranked_779.csv"
OUTPUT_CSV = "/root/pp-jobapp/workspace/ats_mapping_779.csv"
CHECKPOINT = "/root/pp-jobapp/scripts/bulk_add_results.csv"
SCOUT_PY   = "/root/pp-jobapp/scripts/ats_scout.py"
DASHBOARD  = "http://localhost:5000"

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


def post(path, payload, timeout=90):
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
        try:    body = json.loads(e.read().decode())
        except: body = None
        return e.code, body
    except Exception as e:
        return None, {"error": f"{type(e).__name__}: {e}"}


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


def process_live(rec, sleep_s):
    """Run detect (and confirm if hit) for one company. Returns (mapping_row, checkpoint_row)."""
    name = rec["company_name"].strip()
    out  = base_mapping_row(rec)

    # Pass 1: detect by company_name
    code, body = post("/api/add_company/detect", {"name": name})
    if code != 200 or not body:
        chk = {"company": name, "status": "http_error", "ats": "", "slug": "",
               "total_jobs": "", "error": f"detect HTTP {code}: {str(body)[:80]}"}
        out["prior_status"] = f"previously_failed:http_error:{chk['error'][:80]}"
        return out, chk

    if not body.get("found"):
        # Pass 2: try slug derived from company_url as a fresh detect call
        url_slug = slug_from_url(rec.get("company_url", ""))
        name_slug = re.sub(r"[^a-z0-9]", "", name.lower())
        if url_slug and url_slug != name_slug and len(url_slug) >= 3:
            time.sleep(sleep_s)
            code2, body2 = post("/api/add_company/detect", {"name": url_slug})
            if code2 == 200 and body2 and body2.get("found"):
                body = body2
            else:
                tried = ",".join(body.get("tried_slugs", [])) + "|url:" + url_slug
                chk = {"company": name, "status": "no_ats", "ats": "", "slug": "",
                       "total_jobs": "", "error": tried}
                return out, chk
        else:
            chk = {"company": name, "status": "no_ats", "ats": "", "slug": "",
                   "total_jobs": "", "error": ",".join(body.get("tried_slugs", []))}
            return out, chk

    ats   = body["ats"]
    slug  = body["slug"]
    total = body.get("total_jobs", 0)

    out["ats_provider"]     = ats
    out["ats_slug"]         = slug
    out["ats_url"]          = build_ats_url(ats, slug)
    out["open_jobs_actual"] = total

    # Confirm — registers in COMPANIES list inside ats_scout.py
    time.sleep(sleep_s)
    stage    = (rec.get("funding_stage") or "Unknown").strip() or "Unknown"
    vertical = out["vertical_assigned"]
    code, body = post("/api/add_company/confirm",
                      {"name": name, "ats": ats, "slug": slug,
                       "stage": stage, "vertical": vertical})
    if code == 200 and body and body.get("ok"):
        chk = {"company": name, "status": "added", "ats": ats, "slug": slug,
               "total_jobs": total, "error": ""}
        out["prior_status"] = "new"
        return out, chk
    if code == 409:
        chk = {"company": name, "status": "duplicate", "ats": ats, "slug": slug,
               "total_jobs": total, "error": (body or {}).get("error", "")}
        out["prior_status"] = "already_added"
        return out, chk

    chk = {"company": name, "status": "http_error", "ats": ats, "slug": slug,
           "total_jobs": total, "error": f"confirm HTTP {code}: {str(body)[:80]}"}
    out["prior_status"] = f"previously_failed:http_error:{chk['error'][:80]}"
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

    consecutive_http_errors = 0
    mapping_rows = []
    counters = {"new_added": 0, "new_no_ats": 0, "new_http_error": 0,
                "already_added": 0, "previously_failed": 0}

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
            mr, chk = process_live(rec, args.sleep)
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
            consecutive_http_errors = 0
        elif status == "no_ats":
            counters["new_no_ats"] += 1; marker = "-"
            consecutive_http_errors = 0
        elif status == "http_error":
            counters["new_http_error"] += 1; marker = "!"
            consecutive_http_errors += 1
        elif status == "duplicate":
            counters["already_added"] += 1; marker = "="
            consecutive_http_errors = 0
        else:
            counters["new_http_error"] += 1; marker = "?"

        extra = (f" ({chk['ats']}/{chk['slug']}, {chk['total_jobs']} jobs)"
                 if status in ("added", "duplicate") else "")
        print(f"[{i:4d}/{len(rows)}] {marker} {name:35s} -> {status}{extra}")

        if consecutive_http_errors >= 5:
            print(f"!! 5 consecutive HTTP errors. Aborting; rerun later to resume.")
            break

        time.sleep(args.sleep)

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
    for k in ("new_added", "new_no_ats", "new_http_error",
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
