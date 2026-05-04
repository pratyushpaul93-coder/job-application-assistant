"""
Matcher v2.2 — applies the job-matcher.md rubric to SQLite job_postings
Encodes the new JD-level hard skips and conditional family rules.
"""
import json
import re
import sys
from datetime import datetime
from collections import Counter

RAW_PATH = '/root/pp-jobapp/workspace/raw_jobs.json'
SHORTLIST_PATH = '/root/pp-jobapp/workspace/shortlist.json'
FEEDBACK_PATH = '/root/pp-jobapp/workspace/feedback.json'
DB_PATH = '/root/pp-jobapp/workspace/jobapp.db'
SCRIPTS_PATH = '/root/pp-jobapp/scripts'
SCORER = 'current_shortlist'


def load_storage():
    sys.path.insert(0, SCRIPTS_PATH)
    import storage
    return storage

# ----- Hard-skip patterns on JD (multi-year deep single-dimension tech) -----
DEEP_TECH_REQUIREMENT_PATTERNS = [
    r"\b(\d+)\+?\s*years?[^.]{0,80}\b(software engineering|programming|writing production code|coding)\b",
    r"\b(\d+)\+?\s*years?[^.]{0,80}\b(machine learning engineering|ml engineering|applied ml|training models|mlops)\b",
    r"\b(\d+)\+?\s*years?[^.]{0,80}\b(data engineering|data systems|data pipelines|etl|data warehouse)\b",
    r"\b(\d+)\+?\s*years?[^.]{0,80}\b(hardware operations|manufacturing operations|infrastructure deployment)\b",
    r"\b(\d+)\+?\s*years?[^.]{0,80}\b(solutions architecture|technical pre-?sales|developer relations|technical product marketing|technical enablement)\b",
    r"\b(\d+)\+?\s*years?[^.]{0,80}\b(fp&a|financial planning|treasury|core finance|accounting)\b",
    # Direct phrasing
    r"must (be able to )?(code|ship code) (in production|daily)",
    r"strong programming background",
    r"professional software engineering experience",
]

# Years-of-experience extraction (general)
YOE_RE = re.compile(r"\b(\d+)\+?\s*years?\s+(?:of\s+)?(?:experience|exp)\b", re.I)

# TPM domain classification
TPM_TECHNICAL_DOMAINS = [
    "ml platform", "ml/ai platform", "ai platform", "machine learning platform",
    "genai infrastructure", "genai infra", "foundation model", "foundation models",
    "compute infrastructure", "inference infrastructure", "hardware",
    "tokens-as-a-service", "token-as-a-service", "data platform",
    "kernel", "compiler", "low-level systems",
]
TPM_OK_DOMAINS = [
    "launches", "launch", "ads", "growth", "gtm", "go-to-market",
    "marketplace", "product ops", "portfolio", "trust and safety",
    "monetization", "ads performance",
]

STRATEGIC_FINANCE_OPS_SIGNALS = [
    "gtm finance", "revenue finance", "business partner", "ops partner",
    "strategy & finance", "strategic partner", "strategic operations",
]
STRATEGIC_FINANCE_CORE_SIGNALS = [
    "fp&a", "financial planning and analysis", "month-end close",
    "treasury", "general ledger", "audit", "tax",
    "head of strategic finance", "vp of finance",
]


def has_deep_tech_requirement(jd, title):
    jd_l = (jd or "").lower()
    for pat in DEEP_TECH_REQUIREMENT_PATTERNS:
        m = re.search(pat, jd_l)
        if m:
            # If a years figure is present, only flag if >=5
            yrs_match = re.match(r"\\b\\(\\d+\\)", pat)  # not relied on
            grp = m.group(0)
            yrs_in = re.search(r"(\d+)\+?\s*years?", grp)
            if yrs_in:
                if int(yrs_in.group(1)) >= 5:
                    return True, grp
            else:
                return True, grp
    return False, None


def detect_yoe(jd):
    if not jd:
        return None
    matches = [int(m.group(1)) for m in YOE_RE.finditer(jd)]
    if not matches:
        return None
    # Use the highest stated YoE as the floor
    return max(matches)


def classify_tpm(title, jd):
    t = title.lower()
    jd_l = (jd or "").lower()
    if "technical program manager" not in t and "tpm" not in t:
        return None
    blob = t + " " + jd_l[:1500]
    if any(k in blob for k in TPM_TECHNICAL_DOMAINS):
        return "technical_skip"
    if any(k in blob for k in TPM_OK_DOMAINS):
        return "ok"
    return "neutral"


def classify_strategic_finance(title, jd):
    t = title.lower()
    if "strategic finance" not in t and "gtm finance" not in t:
        return None
    jd_l = (jd or "").lower()
    blob = t + " " + jd_l[:1500]
    ops_score = sum(1 for s in STRATEGIC_FINANCE_OPS_SIGNALS if s in blob)
    core_score = sum(1 for s in STRATEGIC_FINANCE_CORE_SIGNALS if s in blob)
    if core_score > ops_score:
        return "core_finance_skip"
    return "ops_ok"


def is_too_senior_title(title):
    t = title.lower()
    senior_markers = [
        "vp ", "vp,", "vp of", "vice president", "chief ", "head of",
        "svp", "evp", "senior director", "sr. director", "sr director",
    ]
    # Don't skip "Head of Operations"-type roles outright — they're rubric-positive
    if any(s in t for s in ["vp ", "vp,", "vp of", "vice president",
                            "svp", "evp", "senior director",
                            "sr. director", "sr director"]):
        return True
    return False


def is_too_junior_title(title):
    t = title.lower()
    junior_markers = ["analyst", "associate", "coordinator", "intern", "junior"]
    return any(j in t for j in junior_markers)


# ----- US location detection -----
US_STATES = {
    "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in",
    "ia","ks","ky","la","me","md","ma","mi","mn","ms","mo","mt","ne","nv",
    "nh","nj","nm","ny","nc","nd","oh","ok","or","pa","ri","sc","sd","tn",
    "tx","ut","vt","va","wa","wv","wi","wy","dc",
}
US_CITY_TOKENS = [
    "new york", "nyc", "san francisco", " sf,", "bay area", "los angeles",
    " la,", "chicago", "boston", "seattle", "austin", "atlanta", "denver",
    "miami", "dallas", "houston", "philadelphia", "portland", "san diego",
    "washington d.c.", "washington dc", "minneapolis", "san jose",
    "palo alto", "menlo park", "mountain view", "sunnyvale", "santa monica",
    "santa clara", "redwood city", "berkeley", "oakland",
]
NON_US_TOKENS = [
    # countries / regions clearly non-US
    "canada", "toronto", "vancouver", "montreal", "ottawa", "calgary",
    "united kingdom", " uk,", " uk.", " london", "manchester", "edinburgh", "dublin",
    "germany", "berlin", "munich", "hamburg",
    "france", "paris", "lyon",
    "netherlands", "amsterdam", "rotterdam",
    "spain", "madrid", "barcelona",
    "italy", "rome", "milan",
    "norway", "oslo", "sweden", "stockholm", "denmark", "copenhagen",
    "finland", "helsinki", "switzerland", "zurich", "geneva",
    "israel", "tel aviv",
    "india", "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad", "chennai", "pune",
    "singapore", "hong kong", "tokyo", "japan", "seoul", "korea",
    "australia", "sydney", "melbourne",
    "kazakhstan", "almaty",
    "brazil", "sao paulo", "mexico city", "mexico,",
    "europe", "emea", "apac", "latam",
]


def is_us_location(job):
    """
    Heuristic US-only filter.
    Returns (is_us: bool, reason: str)
    """
    loc = (job.get("location_raw") or "").lower().strip()
    remote = bool(job.get("remote_ok"))

    if not loc:
        # Unknown location: keep if remote_ok flag is set (assume US-friendly), else skip
        return (True, "no location, remote_ok") if remote else (False, "no location and not remote")

    # Hard non-US tokens win
    for tok in NON_US_TOKENS:
        if tok in loc:
            # Exception: "remote - us" should not be killed by a stray "us" comparison;
            # this loop only fires on real non-US tokens
            return False, f"non-US token: {tok.strip()}"

    # Explicit US/USA/United States
    if any(t in loc for t in ["united states", "usa", " us ", "us-", "u.s.", "remote - us", "remote us"]):
        return True, "explicit US"

    # State abbreviations (look for ", XX" pattern)
    for m in re.finditer(r",\s*([a-zA-Z]{2})\b", loc):
        if m.group(1).lower() in US_STATES:
            return True, f"US state: {m.group(1).upper()}"

    # State full names
    state_names = [
        "california", "new york state", "texas", "florida", "illinois",
        "massachusetts", "washington state", "georgia", "colorado",
        "north carolina", "virginia", "pennsylvania", "ohio", "michigan",
        "arizona", "oregon", "minnesota",
    ]
    for s in state_names:
        if s in loc:
            return True, f"US state: {s}"

    # Major US cities
    for c in US_CITY_TOKENS:
        if c in loc:
            return True, f"US city: {c.strip(', ')}"

    # Remote without country tag → assume US (most US startups post "Remote" meaning US-remote)
    if "remote" in loc and remote:
        return True, "remote (assumed US)"

    return False, f"location not recognized as US: {loc[:60]}"


def compute_score(job):
    title = job.get("role_title", "")
    jd = job.get("jd_text", "")
    company = job.get("company_name", "")
    stage = (job.get("company_stage") or "").lower()
    vertical = (job.get("industry_vertical") or "").lower()
    ai_native = bool(job.get("ai_native"))

    flags = []
    reasons = []

    # ----- Hard skips -----
    yoe = detect_yoe(jd)
    if yoe is not None and yoe >= 8:
        return 1, "Hard skip: requires {}+ years experience".format(yoe), flags

    if is_too_senior_title(title):
        return 1, "Hard skip: title too senior (VP/SVP/Senior Director)", flags

    if is_too_junior_title(title):
        return 1, "Hard skip: title too junior (Analyst/Associate/Coordinator)", flags

    deep, snippet = has_deep_tech_requirement(jd, title)
    if deep:
        return 1, "Hard skip: deep single-dimension tech requirement (\"{}\")".format(
            snippet[:80].strip()), flags

    # ----- Conditional family rules -----
    tpm_class = classify_tpm(title, jd)
    if tpm_class == "technical_skip":
        return 1, "Hard skip: TPM in deep technical domain (ML/AI Platform/GenAI infra/Hardware)", flags

    sf_class = classify_strategic_finance(title, jd)
    if sf_class == "core_finance_skip":
        return 1, "Hard skip: Strategic Finance role is FP&A/core-finance-led, not ops-led", flags

    # ----- Base scoring -----
    score = 3  # default "possible fit"
    t = title.lower()

    # Strong title family bumps
    core_strategy = [
        "strategy and operations", "strategy & operations", "strategic operations",
        "biz ops", "bizops", "business operations",
        "chief of staff", "founding chief of staff",
        "gtm operations", "gtm ops", "revenue operations", "revops",
        "sales operations", "sales ops",
        "product operations", "product ops",
        "growth operations",
        "founding gtm", "founding operations", "founding business",
        "founding strategy", "founding revenue",
    ]
    nice_titles = [
        "strategic initiatives", "strategic programs", "strategic program",
        "strategy and planning", "strategy & planning",
        "implementation strategist", "implementation manager", "implementation lead",
        "deployment strategist",
        "ai implementation", "ai enablement", "ai strategy",
        "special projects", "platform operations", "gtm systems",
        "revenue systems", "business systems",
        "general manager",
    ]
    forward_deployed_pm_like = [
        "forward deployed product manager", "forward-deployed product manager",
        "forward deployed strategist", "forward-deployed strategist",
    ]

    if any(c in t for c in core_strategy):
        score = 4
        reasons.append("core target role family")
    elif any(c in t for c in forward_deployed_pm_like):
        score = 4
        reasons.append("forward-deployed PM/strategist (target)")
    elif any(c in t for c in nice_titles):
        score = 3
        reasons.append("adjacent target role")
    elif "technical program manager" in t or "tpm" in t:
        if tpm_class == "ok":
            score = 4
            reasons.append("TPM in target domain (Launches/Ads/GTM)")
        else:
            score = 3
            reasons.append("TPM, domain unclear")
    elif "technical account manager" in t:
        score = 3
        reasons.append("TAM (adjacent, customer-facing strategy)")
    elif "customer engineer" in t:
        score = 3
        reasons.append("customer engineer (adjacent)")
    elif "strategic finance" in t or "gtm finance" in t:
        if sf_class == "ops_ok":
            score = 3
            reasons.append("strategic/GTM finance, ops-leaning")
        else:
            score = 3
            reasons.append("strategic finance")

    # ----- Positive signal bumps -----
    if ai_native:
        score = min(5, score + 1)
        reasons.append("AI-native company")

    if "marketplace" in vertical:
        score = min(5, score + 1)
        reasons.append("marketplace vertical (Urban Co fit)")

    target_verticals = ["ai", "marketplace", "fintech", "comms tech", "communications", "logistics"]
    if any(v in vertical for v in target_verticals):
        if "marketplace" not in vertical:  # avoid double-bump
            reasons.append(f"target vertical: {vertical}")

    if "series b" in stage or "series c" in stage:
        if score < 5:
            reasons.append(f"sweet-spot stage ({stage})")

    # ----- Soft penalties -----
    if "series a" in stage or "seed" in stage:
        flags.append(f"early stage: {stage}")

    jd_l = (jd or "").lower()
    if "sql" in jd_l:
        if re.search(r"sql[^.]{0,40}(required|must|strong)", jd_l):
            flags.append("SQL: required")
        else:
            flags.append("SQL: mentioned")

    # YoE info flag
    if yoe is not None and yoe >= 6:
        flags.append(f"requires {yoe}+ YoE")

    # Cap and floor
    score = max(1, min(5, score))

    reason_text = "; ".join(reasons) if reasons else "rubric default"
    return score, reason_text, flags


def load_feedback():
    try:
        storage = load_storage()
        conn = storage.connect(DB_PATH)
        try:
            fb = storage.load_feedback_examples(conn)
        finally:
            conn.close()
        if fb:
            return fb
    except Exception as e:
        print(f"WARNING: SQLite feedback load failed: {str(e)[:120]}; falling back to feedback.json")
    try:
        with open(FEEDBACK_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def load_jobs():
    try:
        storage = load_storage()
        conn = storage.connect(DB_PATH)
        try:
            jobs = storage.load_jobs_for_matching(conn)
        finally:
            conn.close()
        return {"jobs": jobs, "config_version": "sqlite"}, "SQLite job_postings"
    except Exception as e:
        print(f"WARNING: SQLite job load failed: {str(e)[:120]}; falling back to raw_jobs.json")
    with open(RAW_PATH) as f:
        return json.load(f), RAW_PATH


def save_scores(scored_jobs):
    try:
        storage = load_storage()
        conn = storage.connect(DB_PATH)
        try:
            storage.save_job_scores(conn, scored_jobs, scorer=SCORER)
        finally:
            conn.close()
        print(f"Saved scores to SQLite job_scores as scorer={SCORER}")
    except Exception as e:
        print(f"WARNING: SQLite score save failed: {str(e)[:120]}")


def main():
    raw, source = load_jobs()
    print(f"Loaded {len(raw.get('jobs', []))} jobs from {source}")

    feedback = load_feedback()

    jobs = raw["jobs"]
    scored = []
    scored_all = []
    score_counts = Counter()
    skip_reasons = Counter()

    non_us_skipped = 0
    for job in jobs:
        # Validation: real company, real apply URL
        if not job.get("company_name") or not job.get("apply_url"):
            reason = "missing company or apply URL"
            scored_all.append({**job, "match_score": 1, "match_reason": reason, "reason": reason, "match_flags": []})
            continue
        if not job["apply_url"].startswith("http"):
            reason = "invalid apply URL"
            scored_all.append({**job, "match_score": 1, "match_reason": reason, "reason": reason, "match_flags": []})
            continue

        # US-only filter
        us_ok, us_reason = is_us_location(job)
        if not us_ok:
            non_us_skipped += 1
            reason = f"Non-US location ({us_reason[:30]})"
            skip_reasons[reason] += 1
            scored_all.append({**job, "match_score": 1, "match_reason": reason, "reason": reason, "match_flags": []})
            continue

        score, reason, flags = compute_score(job)
        score_counts[score] += 1

        # Override with manual feedback if present
        url = job.get("apply_url") or job.get("job_url")
        if url in feedback:
            manual = feedback[url]
            score = manual["manual_score"]
            reason = f"[Manual override] {manual.get('comment', '') or 'previously scored'}"

        scored_job = dict(job)
        scored_job["match_score"] = score
        scored_job["match_reason"] = reason
        scored_job["reason"] = reason
        scored_job["match_flags"] = flags
        scored_all.append(scored_job)

        if score == 1:
            # Track top reasons for skips
            skip_reasons[reason.split(":")[0] if ":" in reason else reason[:40]] += 1
            continue

        out = dict(scored_job)
        out["match_score"] = score
        out["match_reason"] = reason
        out["match_flags"] = flags
        # trim jd_text to keep file size manageable
        if "jd_text" in out and len(out["jd_text"]) > 500:
            out["jd_text"] = out["jd_text"][:500] + "..."
        scored.append(out)

    # Sort: score desc, then ai_native first, then days_ago asc
    scored.sort(key=lambda j: (
        -j["match_score"],
        0 if j.get("ai_native") else 1,
        j.get("days_ago", 9999),
    ))

    out = {
        "shortlist_date": str(datetime.now().date()),
        "config_version": raw.get("config_version", "?"),
        "total_scanned": len(jobs),
        "total_non_us_filtered": non_us_skipped,
        "total_scored": sum(score_counts.values()),
        "score_distribution": dict(sorted(score_counts.items())),
        "total_shortlisted": len(scored),
        "skip_reason_summary": dict(skip_reasons.most_common(15)),
        "jobs": scored,
    }

    with open(SHORTLIST_PATH, "w") as f:
        json.dump(out, f, indent=2)
    save_scores(scored_all)

    print(f"Total scanned: {out['total_scanned']}")
    print(f"Non-US filtered: {out['total_non_us_filtered']}")
    print(f"Score distribution: {out['score_distribution']}")
    print(f"Shortlisted: {out['total_shortlisted']}")
    print()
    print("Top skip reasons:")
    for r, c in skip_reasons.most_common(10):
        print(f"  {c:4d}  {r}")
    print()
    print(f"Top 15 by score:")
    for j in scored[:15]:
        flags = " | ".join(j["match_flags"]) if j["match_flags"] else ""
        print(f"  {j['match_score']}/5  {j['role_title'][:55]:55s}  @ {j['company_name'][:25]:25s}")
        print(f"        {j['match_reason']}")
        if flags:
            print(f"        flags: {flags}")


if __name__ == "__main__":
    main()
