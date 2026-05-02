#!/usr/bin/env python3
"""
ats_scout_getro_match_new.py — Refresh raw_jobs.json (run ats_scout.py),
then DeepSeek-score ONLY jobs that aren't already in shortlist.json. Tag
new jobs with scan_batch='getro_vc_scan_2026_05'. Write merged shortlist.json.

Reuses the same scoring prompt + model as ats_matcher.py.
"""
import csv, datetime, json, os, subprocess, sys, urllib.request

sys.path.insert(0, "/root/pp-jobapp/scripts")
from ats_matcher import build_few_shot_block, _load_feedback_settings

WORKSPACE   = "/root/pp-jobapp/workspace"
SCOUT       = "/root/pp-jobapp/scripts/ats_scout.py"
RAW_JOBS    = WORKSPACE + "/raw_jobs.json"
SHORTLIST   = WORKSPACE + "/shortlist.json"
MAPPING_CSV = WORKSPACE + "/ats_mapping_779.csv"
SCAN_BATCH  = "getro_vc_scan_2026_05"
HARD_LIMIT  = 30000

PROFILE = (
    "Pratyush Paul - S&O professional, 6+ years. "
    "Background: Strategy& Dubai (consulting), Accenture Singapore (ops transformation), "
    "Urban Company Singapore (two-sided marketplace, unit economics), "
    "Armor Defense Chicago (cross-functional, built AI projects: SEC RAG + Spotify MCP). "
    "Target: S&O, CoS, GTM Ops, Sales Ops, Rev Ops, Product Ops, TPM at SaaS/AI startups. "
    "Strong fit: marketplace, AI-native, consulting valued, Series A-D. "
    "Location: all US. SQL: learning, flag as info only never reduce score."
)


def get_deepseek_key():
    try:
        cfg = json.load(open("/root/.openclaw/openclaw.json"))
        return cfg.get("models", {}).get("providers", {}).get("deepseek", {}).get("apiKey", "")
    except Exception:
        return ""


def score_job(job, api_key, few_shot_block=""):
    if not api_key:
        return 3, "No API key"
    prompt = (
        "Score this job 1-5 for candidate. Return ONLY JSON: {score: N, reason: one sentence}. "
        "5=excellent fit, 4=good, 3=possible, 2=weak, 1=skip. "
        "Profile: " + PROFILE + " "
        + (few_shot_block if few_shot_block else "")
        + "Job: " + job["role_title"] + " at " + job["company_name"] +
        " | Location: " + str(job.get("location_raw", "?")) +
        " | Stage: " + str(job.get("company_stage", "?")) +
        " | Vertical: " + str(job.get("industry_vertical", "?")) +
        " | AI company: " + str(job.get("ai_native", False)) +
        " | Remote: " + str(job.get("remote_ok", False))
    )
    try:
        payload = json.dumps({
            "model": "deepseek-chat",
            "max_tokens": 80,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
            content = resp["choices"][0]["message"]["content"].strip()
            if "{" in content:
                content = content[content.index("{"): content.rindex("}") + 1]
            result = json.loads(content)
            return int(result.get("score", 3)), str(result.get("reason", ""))
    except Exception as e:
        return 3, "error: " + str(e)[:60]


def job_key(j):
    """Stable identity for dedupe. Falls back through several URL fields."""
    return (j.get("apply_url") or j.get("job_url") or
            (j.get("company_name", "") + "|" + j.get("role_title", "")))


def load_getro_companies():
    """Set of normalized company names from ats_mapping_779.csv (any prior_status)."""
    out = set()
    if not os.path.exists(MAPPING_CSV):
        return out
    with open(MAPPING_CSV) as f:
        for r in csv.DictReader(f):
            out.add(r["company_name"].strip().lower())
    return out


def main():
    refresh = "--no-refresh" not in sys.argv

    if refresh:
        print("=== Running ats_scout.py to refresh raw_jobs.json ===")
        result = subprocess.run(["python3", SCOUT], capture_output=True, text=True, timeout=2400)
        sys.stdout.write(result.stdout[-2000:])
        if result.returncode != 0:
            print("ats_scout.py failed:", result.stderr[-1000:])
            sys.exit(1)
    else:
        print("Skipping scout refresh (--no-refresh).")

    raw = json.load(open(RAW_JOBS))
    jobs = raw.get("jobs", [])
    print(f"\nraw_jobs.json: {len(jobs)} jobs (post-scout)")

    if len(jobs) > HARD_LIMIT:
        print(f"!! ABORT: jobs ({len(jobs)}) exceeds 30,000 cap. Resume with explicit confirmation.")
        sys.exit(2)

    # Load existing shortlist (already scored)
    if os.path.exists(SHORTLIST):
        prior = json.load(open(SHORTLIST))
        prior_jobs = prior.get("jobs", [])
    else:
        prior_jobs = []
    scored_lookup = {job_key(j): j for j in prior_jobs}
    print(f"shortlist.json: {len(prior_jobs)} previously-scored jobs")

    getro_companies = load_getro_companies()
    print(f"getro_companies (from mapping CSV): {len(getro_companies)}")

    api_key = get_deepseek_key()
    print(f"DeepSeek key: {'found' if api_key else 'MISSING'}")

    fb_enabled, fb_max = _load_feedback_settings()
    few_shot_block = build_few_shot_block(fb_max) if fb_enabled else ""
    if few_shot_block:
        n_examples = few_shot_block.count("\n- ")
        print(f"Feedback loop: ENABLED, {n_examples} few-shot examples loaded")
    else:
        print(f"Feedback loop: {'enabled but no feedback yet' if fb_enabled else 'DISABLED via config'}")
    print("-" * 60)

    new_scored   = 0
    reused       = 0
    getro_tagged = 0
    out_jobs     = []

    for j in jobs:
        k = job_key(j)
        is_getro = j.get("company_name", "").strip().lower() in getro_companies
        if is_getro:
            j["scan_batch"] = SCAN_BATCH
            getro_tagged += 1

        prev = scored_lookup.get(k)
        if prev is not None:
            # Carry forward prior score; preserve scan_batch tag if we just set it.
            j["match_score"] = prev.get("match_score", 3)
            j["reason"]      = prev.get("reason", "")
            if "scan_batch" not in j and "scan_batch" in prev:
                j["scan_batch"] = prev["scan_batch"]
            reused += 1
        else:
            score, reason = score_job(j, api_key, few_shot_block)
            j["match_score"] = score
            j["reason"]      = reason
            new_scored += 1
            if new_scored % 25 == 0:
                print(f"  scored {new_scored} new jobs so far...")

        if j["match_score"] >= 3:
            out_jobs.append(j)

    out_jobs.sort(key=lambda x: x.get("match_score", 0), reverse=True)
    out = {
        "shortlist_date":     str(datetime.date.today()),
        "total_scanned":      len(jobs),
        "total_shortlisted":  len(out_jobs),
        "scan_batch_tagged":  getro_tagged,
        "jobs":               out_jobs,
    }
    json.dump(out, open(SHORTLIST, "w"), indent=2)
    print("-" * 60)
    print(f"reused (previously scored): {reused}")
    print(f"newly scored (DeepSeek):    {new_scored}")
    print(f"tagged scan_batch={SCAN_BATCH}: {getro_tagged}")
    print(f"shortlisted (>=3):          {len(out_jobs)}")
    print(f"Wrote {SHORTLIST}")


if __name__ == "__main__":
    main()
