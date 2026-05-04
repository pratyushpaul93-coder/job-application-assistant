"""
PP Job Matcher — unified scoring pipeline.

Stages, in order, per job:

  0. Manual override:
     If the user has set a manual_score on this job in job_interactions,
     that score wins. Written to current_shortlist with reason "[Manual]".

  1. Deterministic pre-filter (free, instant):
     Encodes the v2.2 rubric: US-only filter, deep-tech requirements,
     too-senior / too-junior titles, and conditional family rules
     (TPM in ML/AI Platform, Strategic Finance FP&A-led, etc.).
     Failures are scored 1 with a clear reason and saved immediately.

  2. Cache check (incremental):
     If a current_shortlist score already exists at the current
     RUBRIC_VERSION, keep it. Use --rescore-all to bypass.

  3. DeepSeek scoring (paid):
     Only runs on jobs that survived stage 1 and lack a fresh cached
     score. Picks up nuance the deterministic rubric misses.

Usage:
  python3 ats_matcher.py                  # incremental scan
  python3 ats_matcher.py --rescore-all    # force full re-score
  python3 ats_matcher.py --max-jobs 50    # cap for quick smoke checks

Bumping the rubric:
  When you change anything in the deterministic pre-filter or in the
  DeepSeek prompt that should invalidate prior scores, bump
  RUBRIC_VERSION below. Old scores will then re-score on the next run.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime

WORKSPACE = '/root/pp-jobapp/workspace'
SCRIPTS = '/root/pp-jobapp/scripts'
CONFIG_PATH = SCRIPTS + '/scout_config.json'
FEEDBACK = WORKSPACE + '/feedback.json'
DB_PATH = WORKSPACE + '/jobapp.db'
RAW_PATH = WORKSPACE + '/raw_jobs.json'
SHORTLIST_PATH = WORKSPACE + '/shortlist.json'

SCORER = 'current_shortlist'
RUBRIC_VERSION = '2.2'  # Bump when rule changes should invalidate prior scores.


# ============================================================
# Storage helpers
# ============================================================

def _storage():
    sys.path.insert(0, SCRIPTS)
    import storage
    return storage


def get_deepseek_key():
    try:
        cfg = json.load(open('/root/.openclaw/openclaw.json'))
        return cfg.get('models', {}).get('providers', {}).get('deepseek', {}).get('apiKey', '')
    except Exception:
        return ''


def _load_feedback_settings():
    try:
        cfg = json.load(open(CONFIG_PATH))
        s = cfg.get('scout_settings', {})
        return bool(s.get('feedback_loop_enabled', True)), int(s.get('feedback_max_examples', 8))
    except Exception:
        return True, 8


def _load_feedback():
    if os.path.exists(DB_PATH):
        try:
            storage = _storage()
            conn = storage.connect(DB_PATH)
            try:
                fb = storage.load_feedback_examples(conn)
            finally:
                conn.close()
            if fb:
                return fb
        except Exception as e:
            print('WARN: SQLite feedback load failed: ' + str(e)[:120] + '; falling back to feedback.json')
    if not os.path.exists(FEEDBACK):
        return {}
    try:
        return json.load(open(FEEDBACK))
    except Exception:
        return {}


def _load_jobs():
    if os.path.exists(DB_PATH):
        storage = _storage()
        conn = storage.connect(DB_PATH)
        try:
            return storage.load_jobs_for_matching(conn), 'SQLite job_postings'
        finally:
            conn.close()
    raw = json.load(open(RAW_PATH))
    return raw.get('jobs', []), RAW_PATH


def _load_existing_scores():
    """Return {job_id: (score, reason, flags, rubric_version)} for current_shortlist."""
    out = {}
    if not os.path.exists(DB_PATH):
        return out
    storage = _storage()
    conn = storage.connect(DB_PATH)
    try:
        for row in conn.execute(
            "SELECT job_id, score, reason, flags_json, rubric_version "
            "FROM job_scores WHERE scorer = ?",
            (SCORER,),
        ):
            try:
                flags = json.loads(row['flags_json'] or '[]')
            except Exception:
                flags = []
            out[row['job_id']] = {
                'score': row['score'],
                'reason': row['reason'] or '',
                'flags': flags,
                'rubric_version': row['rubric_version'] or '0',
            }
    finally:
        conn.close()
    return out


def _load_manual_overrides():
    """Return {job_id: (manual_score, manual_score_comment)} from job_interactions."""
    out = {}
    if not os.path.exists(DB_PATH):
        return out
    storage = _storage()
    conn = storage.connect(DB_PATH)
    try:
        for row in conn.execute(
            "SELECT job_id, manual_score, manual_score_comment "
            "FROM job_interactions WHERE manual_score IS NOT NULL"
        ):
            out[row['job_id']] = (int(row['manual_score']), row['manual_score_comment'] or '')
    finally:
        conn.close()
    return out


def _save_scores(scored_all):
    if not os.path.exists(DB_PATH):
        return
    storage = _storage()
    conn = storage.connect(DB_PATH)
    try:
        storage.save_job_scores(conn, scored_all, scorer=SCORER, rubric_version=RUBRIC_VERSION)
    finally:
        conn.close()


def _shortlist_from_db():
    """Read the full current_shortlist set from SQLite for the export file."""
    if not os.path.exists(DB_PATH):
        return None
    storage = _storage()
    conn = storage.connect(DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT j.id, j.title AS role_title, c.canonical_name AS company_name,
                   j.apply_url, j.job_url, j.location_raw, j.remote_ok,
                   j.posted_date, j.jd_text, j.raw_json,
                   c.stage AS company_stage, c.vertical AS industry_vertical,
                   s.score AS match_score, s.reason AS match_reason,
                   s.flags_json, s.rubric_version
            FROM job_scores s
            JOIN job_postings j ON j.id = s.job_id
            JOIN companies c ON c.id = j.company_id
            WHERE s.scorer = ?
              AND s.score >= 3
              AND j.status = 'active'
              AND c.active = 1
            """,
            (SCORER,),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            raw = json.loads(r['raw_json'] or '{}')
        except Exception:
            raw = {}
        j = dict(raw)
        j.update({
            'company_name': r['company_name'],
            'role_title': r['role_title'],
            'apply_url': r['apply_url'] or r['job_url'] or '',
            'job_url': r['job_url'] or r['apply_url'] or '',
            'location_raw': r['location_raw'] or '',
            'remote_ok': bool(r['remote_ok']),
            'posted_date': r['posted_date'] or '',
            'company_stage': r['company_stage'] or 'Unknown',
            'industry_vertical': r['industry_vertical'] or 'Unknown',
            'match_score': int(r['match_score']),
            'match_reason': r['match_reason'] or '',
            'reason': r['match_reason'] or '',
            'rubric_version': r['rubric_version'] or '0',
        })
        try:
            j['match_flags'] = json.loads(r['flags_json'] or '[]')
        except Exception:
            j['match_flags'] = []
        if 'jd_text' in j and len(j.get('jd_text', '')) > 500:
            j['jd_text'] = j['jd_text'][:500] + '...'
        out.append(j)
    return out


def _write_shortlist_export(scored_all, total_scanned, score_counts, skip_reasons, non_us):
    """Backup/debug export — dashboard reads from SQLite, not this file.

    The export reflects the FULL DB state for current_shortlist, not just the
    jobs touched in this run. Otherwise a partial / interrupted run would
    silently truncate the file and break older dashboards that still read it.
    """
    keepers = _shortlist_from_db()
    if keepers is None:
        # No DB available: fall back to in-memory slice (legacy path).
        keepers = [j for j in scored_all if j.get('match_score', 1) >= 3]
    keepers.sort(key=lambda j: (
        -j['match_score'],
        0 if j.get('ai_native') else 1,
        j.get('days_ago', 9999),
    ))
    out = {
        'shortlist_date': str(datetime.now().date()),
        'rubric_version': RUBRIC_VERSION,
        'total_scanned': total_scanned,
        'total_non_us_filtered': non_us,
        'score_distribution': dict(sorted(score_counts.items())),
        'total_shortlisted': len(keepers),
        'skip_reason_summary': dict(skip_reasons.most_common(15)),
        'jobs': keepers,
    }
    with open(SHORTLIST_PATH, 'w') as f:
        json.dump(out, f, indent=2)


# ============================================================
# Few-shot prompt builder for DeepSeek
# ============================================================

def select_few_shot_examples(max_n=8):
    fb = _load_feedback()
    if not fb:
        return []
    rows = []
    for key, e in fb.items():
        score = e.get('manual_score')
        if not isinstance(score, int) or score < 1 or score > 5:
            continue
        rows.append({
            'score': score,
            'comment': (e.get('comment') or '').strip(),
            'title': (e.get('role_title') or '').strip() or '(unknown role)',
            'company': (e.get('company_name') or '').strip() or '(unknown company)',
            'updated': e.get('updated', ''),
        })
    if not rows:
        return []
    high = [r for r in rows if r['score'] >= 4]
    low = [r for r in rows if r['score'] <= 2]
    mid = [r for r in rows if r['score'] == 3]

    def rank(bucket):
        return sorted(bucket, key=lambda r: (bool(r['comment']), r['updated']), reverse=True)
    high, low, mid = rank(high), rank(low), rank(mid)
    picked, seen = [], set()

    def take(bucket, n):
        for r in bucket:
            if len(picked) >= max_n or n <= 0:
                return
            sig = (r['score'], r['title'], r['company'])
            if sig in seen:
                continue
            picked.append(r); seen.add(sig); n -= 1
    take(high, 2); take(low, 2); take(mid, 2)
    leftovers = rank([r for r in rows if (r['score'], r['title'], r['company']) not in seen])
    take(leftovers, max_n - len(picked))
    return picked


def build_few_shot_block(max_n=8):
    examples = select_few_shot_examples(max_n)
    if not examples:
        return ''
    lines = [
        "Calibration examples — these are the user's own ratings on prior roles. "
        "Use them to anchor your scoring style:"
    ]
    for r in examples:
        line = f"- {r['title']} at {r['company']} — User rated {r['score']}/5"
        if r['comment']:
            line += f". Comment: {r['comment']}"
        line += '.'
        lines.append(line)
    lines.append('')
    return '\n'.join(lines) + '\n'


PROFILE = (
    "Pratyush Paul - S&O professional, 6+ years. "
    "Background: Strategy& Dubai (consulting), Accenture Singapore (ops transformation), "
    "Urban Company Singapore (two-sided marketplace, unit economics), "
    "Armor Defense Chicago (cross-functional, built AI projects: SEC RAG + Spotify MCP). "
    "Target: S&O, CoS, GTM Ops, Sales Ops, Rev Ops, Product Ops, TPM at SaaS/AI startups. "
    "Strong fit: marketplace, AI-native, consulting valued, Series A-D. "
    "Location: all US. SQL: learning, flag as info only never reduce score."
)


# ============================================================
# Stage 1 — Deterministic pre-filter (v2.2 rubric)
# ============================================================

DEEP_TECH_REQUIREMENT_PATTERNS = [
    r"\b(\d+)\+?\s*years?[^.]{0,80}\b(software engineering|programming|writing production code|coding)\b",
    r"\b(\d+)\+?\s*years?[^.]{0,80}\b(machine learning engineering|ml engineering|applied ml|training models|mlops)\b",
    r"\b(\d+)\+?\s*years?[^.]{0,80}\b(data engineering|data systems|data pipelines|etl|data warehouse)\b",
    r"\b(\d+)\+?\s*years?[^.]{0,80}\b(hardware operations|manufacturing operations|infrastructure deployment)\b",
    r"\b(\d+)\+?\s*years?[^.]{0,80}\b(solutions architecture|technical pre-?sales|developer relations|technical product marketing|technical enablement)\b",
    r"\b(\d+)\+?\s*years?[^.]{0,80}\b(fp&a|financial planning|treasury|core finance|accounting)\b",
    r"must (be able to )?(code|ship code) (in production|daily)",
    r"strong programming background",
    r"professional software engineering experience",
]

YOE_RE = re.compile(r"\b(\d+)\+?\s*years?\s+(?:of\s+)?(?:experience|exp)\b", re.I)

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

US_STATES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in",
    "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv",
    "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn",
    "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
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


def _has_deep_tech_requirement(jd):
    jd_l = (jd or "").lower()
    for pat in DEEP_TECH_REQUIREMENT_PATTERNS:
        m = re.search(pat, jd_l)
        if m:
            grp = m.group(0)
            yrs = re.search(r"(\d+)\+?\s*years?", grp)
            if yrs:
                if int(yrs.group(1)) >= 5:
                    return True, grp
            else:
                return True, grp
    return False, None


def _detect_yoe(jd):
    if not jd:
        return None
    matches = [int(m.group(1)) for m in YOE_RE.finditer(jd)]
    return max(matches) if matches else None


def _classify_tpm(title, jd):
    t = title.lower()
    if "technical program manager" not in t and " tpm" not in (" " + t):
        return None
    blob = t + " " + (jd or "").lower()[:1500]
    if any(k in blob for k in TPM_TECHNICAL_DOMAINS):
        return "technical_skip"
    if any(k in blob for k in TPM_OK_DOMAINS):
        return "ok"
    return "neutral"


def _classify_strategic_finance(title, jd):
    t = title.lower()
    if "strategic finance" not in t and "gtm finance" not in t:
        return None
    blob = t + " " + (jd or "").lower()[:1500]
    ops_score = sum(1 for s in STRATEGIC_FINANCE_OPS_SIGNALS if s in blob)
    core_score = sum(1 for s in STRATEGIC_FINANCE_CORE_SIGNALS if s in blob)
    return "core_finance_skip" if core_score > ops_score else "ops_ok"


def _is_too_senior_title(title):
    t = title.lower()
    return any(s in t for s in [
        "vp ", "vp,", "vp of", "vice president",
        "svp", "evp", "senior director", "sr. director", "sr director",
    ])


def _is_too_junior_title(title):
    t = title.lower()
    return any(j in t for j in ["analyst", "associate", "coordinator", "intern", "junior"])


def _is_us_location(job):
    loc = (job.get("location_raw") or "").lower().strip()
    remote = bool(job.get("remote_ok"))
    if not loc:
        return (True, "no location, remote_ok") if remote else (False, "no location, not remote")
    for tok in NON_US_TOKENS:
        if tok in loc:
            return False, f"non-US token: {tok.strip()}"
    if any(t in loc for t in ["united states", "usa", " us ", "us-", "u.s.", "remote - us", "remote us"]):
        return True, "explicit US"
    for m in re.finditer(r",\s*([a-zA-Z]{2})\b", loc):
        if m.group(1).lower() in US_STATES:
            return True, f"US state: {m.group(1).upper()}"
    state_names = [
        "california", "new york state", "texas", "florida", "illinois",
        "massachusetts", "washington state", "georgia", "colorado",
        "north carolina", "virginia", "pennsylvania", "ohio", "michigan",
        "arizona", "oregon", "minnesota",
    ]
    for s in state_names:
        if s in loc:
            return True, f"US state: {s}"
    for c in US_CITY_TOKENS:
        if c in loc:
            return True, f"US city: {c.strip(', ')}"
    if "remote" in loc and remote:
        return True, "remote (assumed US)"
    return False, f"location not recognized as US: {loc[:60]}"


def prefilter(job):
    """Stage 1: deterministic checks. Returns (skip_score, reason, flags) or None to continue."""
    title = job.get("role_title", "") or ""
    jd = job.get("jd_text", "") or ""

    apply_url = job.get("apply_url") or ""
    if not apply_url or not apply_url.startswith("http"):
        return 1, "missing or invalid apply URL", []

    us_ok, us_reason = _is_us_location(job)
    if not us_ok:
        return 1, f"Non-US: {us_reason}", []

    yoe = _detect_yoe(jd)
    if yoe is not None and yoe >= 8:
        return 1, f"requires {yoe}+ years experience", []

    if _is_too_senior_title(title):
        return 1, "title too senior (VP/SVP/Senior Director)", []

    if _is_too_junior_title(title):
        return 1, "title too junior (Analyst/Associate/Coordinator)", []

    deep, snippet = _has_deep_tech_requirement(jd)
    if deep:
        return 1, f'deep single-dimension tech requirement ("{snippet[:80].strip()}")', []

    tpm = _classify_tpm(title, jd)
    if tpm == "technical_skip":
        return 1, "TPM in deep technical domain (ML/AI Platform/GenAI infra/Hardware)", []

    sf = _classify_strategic_finance(title, jd)
    if sf == "core_finance_skip":
        return 1, "Strategic Finance role is FP&A/core-finance-led, not ops-led", []

    return None  # survived pre-filter


# ============================================================
# Stage 3 — DeepSeek
# ============================================================

def deepseek_score(job, api_key, few_shot_block=''):
    if not api_key:
        return 0, "error: no API key"
    jd = (job.get('jd_text') or '')[:4000]
    prompt = (
        "Score this job 1-5 for the candidate. Return ONLY JSON: {score: N, reason: one sentence}. "
        "5=excellent fit, 4=good, 3=possible, 2=weak, 1=skip. "
        "Weigh the JD body heavily — title can mislead. "
        "Profile: " + PROFILE + "\n\n"
        + (few_shot_block if few_shot_block else '')
        + "Role: " + job['role_title'] + " at " + job['company_name'] +
        " | Location: " + str(job.get('location_raw', '?')) +
        " | Stage: " + str(job.get('company_stage', '?')) +
        " | Vertical: " + str(job.get('industry_vertical', '?')) +
        " | AI company: " + str(job.get('ai_native', False)) +
        " | Remote: " + str(job.get('remote_ok', False)) + "\n\n"
        "JD:\n" + (jd or '(no JD body)')
    )
    try:
        payload = json.dumps({
            "model": "deepseek-chat",
            "max_tokens": 120,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            'https://api.deepseek.com/v1/chat/completions',
            data=payload,
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + api_key},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read().decode())
            content = resp['choices'][0]['message']['content'].strip()
            if '{' in content:
                content = content[content.index('{'):content.rindex('}') + 1]
            result = json.loads(content)
            return int(result.get('score', 0)), str(result.get('reason', ''))
    except Exception as e:
        return 0, 'error: ' + str(e)[:120]


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="PP unified job matcher")
    parser.add_argument(
        "--rescore-all", action="store_true",
        help="Force re-score every job, ignoring cached scores at the current rubric_version.",
    )
    parser.add_argument(
        "--max-jobs", type=int, default=None,
        help="Stop after scoring this many jobs (smoke testing).",
    )
    args = parser.parse_args()

    api_key = get_deepseek_key()
    print('PP Job Matcher')
    print('Date:           ' + str(datetime.now().date()))
    print('Rubric version: ' + RUBRIC_VERSION)
    print('Scorer:         ' + SCORER)
    print('Mode:           ' + ('FULL RE-SCORE' if args.rescore_all else 'incremental'))
    print('DeepSeek key:   ' + ('found' if api_key else 'MISSING'))

    fb_enabled, fb_max = _load_feedback_settings()
    few_shot_block = build_few_shot_block(fb_max) if fb_enabled else ''
    if few_shot_block:
        n_lines = few_shot_block.count('\n- ')
        print(f'Feedback loop:  ENABLED, {n_lines} few-shot examples')
    else:
        print('Feedback loop:  ' + ('enabled but no feedback yet' if fb_enabled else 'DISABLED via config'))

    jobs, job_source = _load_jobs()
    print(f'Loaded {len(jobs)} jobs from {job_source}')
    print('-' * 70)

    existing_scores = {} if args.rescore_all else _load_existing_scores()
    manual_overrides = _load_manual_overrides()

    score_counts = Counter()
    skip_reasons = Counter()
    counters = Counter()  # manual / prefilter / cached / deepseek
    non_us = 0
    scored_all = []

    for i, job in enumerate(jobs):
        if args.max_jobs is not None and i >= args.max_jobs:
            break

        job_id = job.get('_job_id')
        score = None
        reason = ''
        flags = []
        rubric_v = RUBRIC_VERSION

        # Stage 0: manual override
        if job_id is not None and job_id in manual_overrides:
            ms, mc = manual_overrides[job_id]
            score, reason = ms, f"[Manual] {mc}".rstrip()
            counters['manual'] += 1

        # Stage 1: deterministic pre-filter
        if score is None:
            pre = prefilter(job)
            if pre is not None:
                score, reason, flags = pre
                if reason.startswith("Non-US"):
                    non_us += 1
                counters['prefilter'] += 1

        # Stage 2: cache check
        if score is None and job_id in existing_scores:
            cached = existing_scores[job_id]
            if cached['rubric_version'] == RUBRIC_VERSION:
                score = cached['score']
                reason = cached['reason']
                flags = cached['flags']
                rubric_v = cached['rubric_version']
                counters['cached'] += 1

        # Stage 3: DeepSeek
        if score is None:
            score, reason = deepseek_score(job, api_key, few_shot_block)
            if score == 0:
                # DeepSeek error; preserve any existing cached score rather than overwriting
                if job_id in existing_scores:
                    cached = existing_scores[job_id]
                    score = cached['score']
                    reason = '[DS error, kept cached] ' + (cached['reason'] or '')
                    flags = cached['flags']
                    rubric_v = cached['rubric_version']
                    counters['deepseek_err_kept'] += 1
                else:
                    score = 1
                    reason = 'DeepSeek error: ' + reason
                    counters['deepseek_err_default'] += 1
            else:
                counters['deepseek'] += 1

        score_counts[score] += 1
        if score == 1:
            head = reason.split(':')[0] if ':' in reason else reason[:40]
            skip_reasons[head] += 1

        scored_job = dict(job)
        scored_job['match_score'] = score
        scored_job['match_reason'] = reason
        scored_job['reason'] = reason
        scored_job['match_flags'] = flags
        scored_job['rubric_version'] = rubric_v
        scored_all.append(scored_job)

    _save_scores(scored_all)
    _write_shortlist_export(scored_all, len(jobs), score_counts, skip_reasons, non_us)

    run_keepers = sum(1 for s, c in score_counts.items() if s >= 3 for _ in range(c))
    print(f'This run scored:   {sum(score_counts.values())}')
    print(f'Stage breakdown:   manual={counters["manual"]} | prefilter={counters["prefilter"]} '
          f'| cached={counters["cached"]} | deepseek={counters["deepseek"]} '
          f'| ds_err_kept={counters["deepseek_err_kept"]} | ds_err_default={counters["deepseek_err_default"]}')
    print(f'Score distribution (this run): {dict(sorted(score_counts.items()))}')
    print(f'Non-US filtered (this run):    {non_us}')
    print(f'This run, score >=3:           {run_keepers}')
    full = _shortlist_from_db()
    if full is not None:
        print(f'Total in shortlist (DB):       {len(full)}')
    print()
    print('Top skip reasons:')
    for r, c in skip_reasons.most_common(8):
        print(f'  {c:5d}  {r}')
    if os.path.exists(DB_PATH):
        print()
        print(f'Saved to SQLite job_scores (scorer={SCORER}, rubric_version={RUBRIC_VERSION})')


if __name__ == '__main__':
    main()
