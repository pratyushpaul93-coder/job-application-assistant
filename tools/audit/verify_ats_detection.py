#!/usr/bin/env python3
"""
verify_ats_detection.py — back-test ATS slug detection strategies on real
companies that don't currently have an active ATS endpoint in our DB.

READ-ONLY by policy. Probes public ATS APIs (Ashby, Greenhouse, Lever) and
scrapes public careers pages. Does NOT write to the SQLite DB.

For each sample company, tests three detection strategies:
  1. Current 6-candidate slug logic (mirror of dashboard.py add_company_detect)
  2. Expanded ~30-candidate slug logic (suffixes, prefixes, suffix-stripping, domain stem)
  3. Website probing — fetch /careers, /jobs etc, regex-detect ATS embeds

Output: prints summary table + writes detail CSV to workspace/ats_detection_audit.csv
"""
import urllib.request, urllib.error, json, re, time, csv, sys
import ssl

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
TIMEOUT_API = 8
TIMEOUT_HTML = 10
INTER_REQ_DELAY = 0.4

ssl_ctx = ssl.create_default_context()


def http_get_json(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=TIMEOUT_API, context=ssl_ctx) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def http_get_text(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT_HTML, context=ssl_ctx) as r:
            return r.read().decode('utf-8', errors='ignore')[:300000]
    except Exception:
        return None


def test_ashby(slug):
    d = http_get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    return bool(d and d.get('jobs'))


def test_greenhouse(slug):
    d = http_get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    return bool(d and d.get('jobs'))


def test_lever(slug):
    d = http_get_json(f"https://api.lever.co/v0/postings/{slug}")
    return isinstance(d, list) and len(d) > 0


def test_provider(provider, slug):
    if provider == 'ashby':
        return test_ashby(slug)
    if provider == 'greenhouse':
        return test_greenhouse(slug)
    if provider == 'lever':
        return test_lever(slug)
    return False


def first_hit(candidates, providers=('ashby', 'greenhouse', 'lever')):
    for slug in candidates:
        for p in providers:
            if test_provider(p, slug):
                return (p, slug)
            time.sleep(INTER_REQ_DELAY * 0.3)
    return None


def current_candidates(name):
    base = re.sub(r"[^a-z0-9]", "", name.lower())
    base_hyphen = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return list(dict.fromkeys([base, base_hyphen, base + "hq", "get" + base, base + "-ai", base + "so"]))


def expanded_candidates(name, website_url=None):
    base = re.sub(r"[^a-z0-9]", "", name.lower())
    base_hyphen = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    cands = [base, base_hyphen]
    for suf in ['hq', 'io', 'ai', 'app', 'tech', 'data', 'labs', 'inc', 'health', 'bio',
                'software', 'careers', 'jobs', 'work', 'global', 'studio']:
        cands.append(base + suf)
        cands.append(base + '-' + suf)
        if base_hyphen != base:
            cands.append(base_hyphen + '-' + suf)
    cands += ['get' + base, 'join' + base, 'try' + base, 'use' + base, 'with' + base]
    name_lower = name.lower()
    for strip in [' labs', ' inc', ' health', ' security', ' ai', ' technologies',
                  ' technology', ' tech', ' bio', ' global', ' insurance', ' systems',
                  ' software', ' group', ' co']:
        if name_lower.endswith(strip):
            stripped = name_lower[:-len(strip)].strip()
            cands.append(re.sub(r"[^a-z0-9]", "", stripped))
            cands.append(re.sub(r"[^a-z0-9]+", "-", stripped).strip("-"))
    if website_url:
        m = re.match(r'https?://(?:www\.)?([^./]+)', website_url)
        if m:
            domain_stem = m.group(1).lower()
            cands.append(domain_stem)
            cands.append(re.sub(r'[^a-z0-9]', '', domain_stem))
            cands.append('get' + domain_stem)
    return list(dict.fromkeys([c for c in cands if c and len(c) > 1]))


PROBE_PATHS = ['', '/careers', '/jobs', '/about/careers', '/company/careers',
               '/careers/', '/jobs/', '/work-with-us', '/join-us', '/company']

ATS_SIGNATURES = [
    ('greenhouse', r'boards\.greenhouse\.io/embed/job_board\?for=([a-z0-9_-]+)', 1),
    ('greenhouse', r'boards\.greenhouse\.io/([a-z0-9_-]+)(?:[/"\'?#]|$)', 1),
    ('greenhouse', r'job-boards\.greenhouse\.io/([a-z0-9_-]+)', 1),
    ('ashby',      r'jobs\.ashbyhq\.com/([a-z0-9_.-]+?)(?:[/"\'?#]|$)', 1),
    ('ashby',      r'embed\.ashbyhq\.com/([a-z0-9_.-]+?)(?:[/"\'?#]|$)', 1),
    ('lever',      r'jobs\.lever\.co/([a-z0-9_-]+)', 1),
    ('workable',   r'apply\.workable\.com/([a-z0-9_-]+)', 1),
    ('workday',    r'([a-z0-9_-]+)\.(?:wd[0-9]+|my)\.myworkdayjobs\.com', 1),
    ('smartrecruiters', r'(?:careers|jobs)\.smartrecruiters\.com/([a-z0-9_-]+)', 1),
    ('bamboohr',   r'([a-z0-9_-]+)\.bamboohr\.com/(?:jobs|careers)', 1),
    ('rippling-ats', r'ats\.rippling\.com/([a-z0-9_-]+)', 1),
    ('personio',   r'([a-z0-9_-]+)\.jobs\.personio\.(?:com|de)', 1),
    ('recruitee',  r'([a-z0-9_-]+)\.recruitee\.com', 1),
    ('jazzhr',     r'([a-z0-9_-]+)\.applytojob\.com', 1),
    ('teamtailor', r'([a-z0-9_-]+)\.teamtailor\.com', 1),
    ('pinpoint',   r'([a-z0-9_-]+)\.pinpointhq\.com', 1),
]


def probe_website(url):
    if not url:
        return None
    base = url.rstrip('/')
    for path in PROBE_PATHS:
        full_url = base + path
        html = http_get_text(full_url)
        if not html:
            continue
        for provider, pattern, grp in ATS_SIGNATURES:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                slug = m.group(grp).rstrip('/').lower()
                if slug in ('embed', 'jobs', 'careers', 'job_board'):
                    continue
                return {'provider': provider, 'slug': slug, 'found_at': full_url}
        time.sleep(INTER_REQ_DELAY * 0.5)
    return None


SAMPLE = [
    ("ServiceChannel",       "https://servicechannel.com"),
    ("Captions",             "https://captions.ai/"),
    ("Anduril",              "https://anduril.com"),
    ("Thrive Global",        "https://thriveglobal.com/"),
    ("Flock Safety",         "https://flocksafety.com/"),
    ("Fabric",               "https://fabrichealth.com"),
    ("Empathy",              "https://empathy.com"),
    ("Cityblock Health",     "https://cityblock.com"),
    ("Snaptrude",            "https://snaptrude.com"),
    ("Blank Street",         "https://blankstreet.com"),
    ("Resilience Insurance", "https://resilienceinsurance.com/"),
    ("Somethings",           "https://somethings.com"),
    ("Whisper.ai",           "https://whisper.ai/"),
    ("Oasis Security",       "https://oasis.security"),
    ("BetDEX Labs",          "https://betdex.com/"),
]

print("=== Sanity check: known-good slugs ===")
print(f"  greenhouse/anthropic: {'OK' if test_greenhouse('anthropic') else 'FAIL'}")
print(f"  ashby/ramp:           {'OK' if test_ashby('ramp') else 'FAIL'}")
print(f"  lever/spotify:        {'OK' if test_lever('spotify') else 'FAIL'}")
print()
print("If any of the above say FAIL, the test results below are invalid.")
print("=" * 70)
print()

results = []
for i, (name, url) in enumerate(SAMPLE):
    print(f"[{i+1}/{len(SAMPLE)}] {name}")
    print(f"    url: {url}")

    cur_cands = current_candidates(name)
    cur_hit = first_hit(cur_cands)
    print(f"    current ({len(cur_cands)}): {cur_hit if cur_hit else 'MISS'}")

    if not cur_hit:
        exp_cands = expanded_candidates(name, url)
        exp_hit = first_hit(exp_cands)
        print(f"    expanded ({len(exp_cands)}): {exp_hit if exp_hit else 'MISS'}")
    else:
        exp_cands = []
        exp_hit = cur_hit

    web_hit = None
    if not cur_hit and not exp_hit:
        web_hit = probe_website(url)
        print(f"    website probe: {web_hit if web_hit else 'NOTHING DETECTED'}")

    if cur_hit:
        outcome = 'current_logic_hit'
    elif exp_hit:
        outcome = f'expanded_slugs_hit:{exp_hit[0]}'
    elif web_hit:
        outcome = f'website_probe_hit:{web_hit["provider"]}'
    else:
        outcome = 'no_strategy_hit'

    print(f"    => {outcome}")
    print()

    results.append({
        'name': name, 'url': url,
        'current_hit': cur_hit,
        'current_candidates_tried': len(cur_cands),
        'expanded_hit': exp_hit if exp_hit != cur_hit else None,
        'expanded_candidates_tried': len(exp_cands) if not cur_hit else 0,
        'website_probe_hit': web_hit,
        'outcome': outcome,
    })
    time.sleep(INTER_REQ_DELAY)

print("=" * 70)
print("SUMMARY")
print("=" * 70)
buckets = {}
for r in results:
    o = r['outcome'].split(':')[0]
    buckets.setdefault(o, [])
    buckets[o].append(r['name'])
for outcome, names in sorted(buckets.items(), key=lambda x: -len(x[1])):
    print(f"  {outcome:30s} {len(names)}/{len(results)}  ({', '.join(names[:5])}{'...' if len(names)>5 else ''})")

out_path = '/tmp/ats_detection_audit.csv'
try:
    with open(out_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['name', 'url', 'outcome', 'current_hit', 'expanded_hit', 'website_probe_hit'])
        for r in results:
            w.writerow([r['name'], r['url'], r['outcome'],
                        json.dumps(r['current_hit']), json.dumps(r['expanded_hit']),
                        json.dumps(r['website_probe_hit'])])
    print(f"\nDetailed results written to: {out_path}")
except Exception as e:
    print(f"\nCould not write CSV ({e}); results still printed above.")
