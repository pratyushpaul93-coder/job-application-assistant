import json, urllib.request, os, datetime

WORKSPACE = '/root/pp-jobapp/workspace'

ROLE_KEYWORDS_POSITIVE = [
    'strategy & operations', 'strategy and operations', 'strategic operations',
    'strategy operations', 'bizops', 'biz ops', 'business operations',
    'operational strategy', 'operational excellence',
    'chief of staff', 'cos ',
    'gtm operations', 'gtm ops', 'go-to-market operations', 'go to market operations',
    'gtm strategy', 'gtm programs',
    'sales operations', 'sales ops',
    'revenue operations', 'revenue ops', 'revops', 'rev ops',
    'product operations', 'product ops',
    'growth operations', 'field operations manager',
    'head of operations', 'vp of operations', 'director of operations',
    'vp operations', 'director operations',
    'strategic program', 'strategic programs', 'strategic initiatives',
    'strategy and planning', 'strategy & planning',
    'program manager, strategy', 'program manager strategy',
    'technical program manager',
    'general manager',
    'gtm finance', 'strategic finance',
    'gtm onboarding', 'gtm readiness',
]

ROLE_KEYWORDS_NEGATIVE = [
    'security operations', 'soc analyst', 'it operations', 'it ops',
    'devops', 'dev ops', 'sre ', 'site reliability',
    'software engineer', 'software developer', 'ml engineer', 'ai engineer',
    'data engineer', 'data scientist', 'research engineer',
    'marketing operations', 'marketing ops',
    'hr operations', 'people operations analyst', 'people ops analyst',
    'facilities', 'legal operations',
    'customer success', 'support operations', 'customer operations analyst',
    'intern', 'junior', 'coordinator',
    'recruiting operations', 'talent operations',
    'financial operations analyst',
    'lifecycle marketing operations',
]

COMPANIES = [
    {'name': 'Ramp', 'ats': 'ashby', 'slug': 'ramp', 'stage': 'Series D+', 'vertical': 'Fintech'},
    {'name': 'Notion', 'ats': 'ashby', 'slug': 'notion', 'stage': 'Series C', 'vertical': 'SaaS'},
    {'name': 'Vanta', 'ats': 'ashby', 'slug': 'vanta', 'stage': 'Series C', 'vertical': 'SaaS'},
    {'name': 'Harvey', 'ats': 'ashby', 'slug': 'harvey', 'stage': 'Series C', 'vertical': 'AI'},
    {'name': 'ElevenLabs', 'ats': 'ashby', 'slug': 'elevenlabs', 'stage': 'Series C', 'vertical': 'AI'},
    {'name': 'Cohere', 'ats': 'ashby', 'slug': 'cohere', 'stage': 'Series D', 'vertical': 'AI'},
    {'name': 'LangChain', 'ats': 'ashby', 'slug': 'langchain', 'stage': 'Series A', 'vertical': 'AI'},
    {'name': 'Pinecone', 'ats': 'ashby', 'slug': 'pinecone', 'stage': 'Series B', 'vertical': 'AI'},
    {'name': 'Sierra', 'ats': 'ashby', 'slug': 'sierra', 'stage': 'Series B', 'vertical': 'AI'},
    {'name': 'Linear', 'ats': 'ashby', 'slug': 'linear', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Zapier', 'ats': 'ashby', 'slug': 'zapier', 'stage': 'Bootstrapped', 'vertical': 'SaaS'},
    {'name': 'n8n', 'ats': 'ashby', 'slug': 'n8n', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Glean', 'ats': 'greenhouse', 'slug': 'gleanwork', 'stage': 'Series E', 'vertical': 'AI'},
    {'name': 'Brex', 'ats': 'greenhouse', 'slug': 'brex', 'stage': 'Series D', 'vertical': 'Fintech'},
    {'name': 'Cyera', 'ats': 'greenhouse', 'slug': 'cyera', 'stage': 'Series C', 'vertical': 'SaaS'},
    {'name': 'Airtable', 'ats': 'greenhouse', 'slug': 'airtable', 'stage': 'Series F', 'vertical': 'SaaS'},
    {'name': 'Vercel', 'ats': 'greenhouse', 'slug': 'vercel', 'stage': 'Series D', 'vertical': 'AI'},
    {'name': 'Intercom', 'ats': 'greenhouse', 'slug': 'intercom', 'stage': 'Public', 'vertical': 'SaaS'},
    {'name': 'Anthropic', 'ats': 'greenhouse', 'slug': 'anthropic', 'stage': 'Series E', 'vertical': 'AI'},
    {'name': 'Wiz', 'ats': 'greenhouse', 'slug': 'wizsecurity', 'stage': 'Series E', 'vertical': 'SaaS'},
    {'name': 'Figma', 'ats': 'lever', 'slug': 'figma', 'stage': 'Public', 'vertical': 'SaaS'},
    {'name': 'Mistral', 'ats': 'lever', 'slug': 'mistral', 'stage': 'Series B', 'vertical': 'AI'},
    {'name': 'Weights & Biases', 'ats': 'lever', 'slug': 'wandb', 'stage': 'Series C', 'vertical': 'AI'},
    {'name': 'Spotify', 'ats': 'lever', 'slug': 'spotify', 'stage': 'Public', 'vertical': 'Marketplace'},
    {'name': 'Rippling', 'ats': 'tavily', 'slug': 'rippling', 'stage': 'Series F', 'vertical': 'SaaS'},
]

def fetch_url(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except:
        return None

def parse_date(raw):
    if not raw:
        return ''
    try:
        return raw[:10]
    except:
        return str(raw)[:10]

def days_ago(date_str):
    if not date_str:
        return None
    try:
        d = datetime.date.fromisoformat(date_str[:10])
        return (datetime.date.today() - d).days
    except:
        return None

def is_target_role(title):
    t = title.lower()
    if not any(k in t for k in ROLE_KEYWORDS_POSITIVE):
        return False
    if any(k in t for k in ROLE_KEYWORDS_NEGATIVE):
        return False
    return True

def fetch_ashby(company):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company['slug']}?includeCompensation=true"
    data = fetch_url(url)
    if not data:
        return [], 0
    all_jobs = data.get('jobs', [])
    matches = []
    for j in all_jobs:
        title = j.get('title', '')
        if not is_target_role(title):
            continue
        location = j.get('location', '') or ''
        if isinstance(location, dict):
            location = location.get('name', '')
        posted = parse_date(j.get('publishedAt', ''))
        matches.append({
            'company_name': company['name'],
            'role_title': title,
            'apply_url': j.get('applyUrl') or j.get('jobUrl', ''),
            'job_url': j.get('jobUrl', ''),
            'source': 'ashby',
            'date_found': str(datetime.date.today()),
            'posted_date': posted,
            'days_ago': days_ago(posted),
            'location_raw': location,
            'remote_ok': j.get('isRemote', False),
            'company_stage': company.get('stage', 'Unknown'),
            'industry_vertical': company.get('vertical', 'Unknown'),
            'ai_native': company.get('vertical') == 'AI',
            'compensation': j.get('compensation', {}).get('compensationTierSummary', '') if j.get('compensation') else '',
        })
    return matches, len(all_jobs)

def fetch_greenhouse(company):
    url = f"https://api.greenhouse.io/v1/boards/{company['slug']}/jobs?content=true"
    data = fetch_url(url)
    if not data:
        return [], 0
    all_jobs = data.get('jobs', [])
    matches = []
    for j in all_jobs:
        title = j.get('title', '')
        if not is_target_role(title):
            continue
        location = j.get('location', {})
        if isinstance(location, dict):
            location = location.get('name', '')
        posted = parse_date(j.get('updated_at', '') or j.get('first_published', ''))
        matches.append({
            'company_name': company['name'],
            'role_title': title,
            'apply_url': j.get('absolute_url', ''),
            'job_url': j.get('absolute_url', ''),
            'source': 'greenhouse',
            'date_found': str(datetime.date.today()),
            'posted_date': posted,
            'days_ago': days_ago(posted),
            'location_raw': location,
            'remote_ok': 'remote' in location.lower() if location else False,
            'company_stage': company.get('stage', 'Unknown'),
            'industry_vertical': company.get('vertical', 'Unknown'),
            'ai_native': company.get('vertical') == 'AI',
            'compensation': '',
        })
    return matches, len(all_jobs)

def fetch_lever(company):
    url = f"https://api.lever.co/v0/postings/{company['slug']}"
    data = fetch_url(url)
    if not data or not isinstance(data, list):
        return [], 0
    matches = []
    for j in data:
        title = j.get('text', '')
        if not is_target_role(title):
            continue
        cats = j.get('categories', {})
        location = cats.get('location', '') or ''
        raw_ts = j.get('createdAt', 0)
        posted = ''
        if raw_ts:
            try:
                posted = str(datetime.date.fromtimestamp(raw_ts / 1000))
            except:
                posted = ''
        matches.append({
            'company_name': company['name'],
            'role_title': title,
            'apply_url': j.get('applyUrl', j.get('hostedUrl', '')),
            'job_url': j.get('hostedUrl', ''),
            'source': 'lever',
            'date_found': str(datetime.date.today()),
            'posted_date': posted,
            'days_ago': days_ago(posted),
            'location_raw': location,
            'remote_ok': 'remote' in location.lower() if location else False,
            'company_stage': company.get('stage', 'Unknown'),
            'industry_vertical': company.get('vertical', 'Unknown'),
            'ai_native': company.get('vertical') == 'AI',
            'compensation': '',
        })
    return matches, len(data)

print("PP Job Scout - ATS API Scan")
print("Date: " + str(datetime.date.today()))
print("Companies: " + str(len(COMPANIES)))
print("-" * 50)

all_jobs = []
errors = []
company_stats = []

for company in COMPANIES:
    ats = company['ats']
    try:
        if ats == 'ashby':
            matches, total = fetch_ashby(company)
        elif ats == 'greenhouse':
            matches, total = fetch_greenhouse(company)
        elif ats == 'lever':
            matches, total = fetch_lever(company)
        else:
            print("  " + company['name'] + ": skipped (custom ATS)")
            company_stats.append({'company': company['name'], 'ats': 'custom', 'total_jobs': 0, 'matches': 0, 'status': 'skipped'})
            continue
        status = 'ok' if total > 0 else 'empty'
        print("  " + company['name'] + " (" + ats + "): " + str(len(matches)) + " potential matches, " + str(total) + " total jobs")
        all_jobs.extend(matches)
        company_stats.append({'company': company['name'], 'ats': ats, 'total_jobs': total, 'matches': len(matches), 'status': status})
    except Exception as e:
        errors.append(company['name'] + ": " + str(e))
        print("  " + company['name'] + ": ERROR - " + str(e))
        company_stats.append({'company': company['name'], 'ats': ats, 'total_jobs': 0, 'matches': 0, 'status': 'error'})

print("-" * 50)
print("Total potential matches: " + str(len(all_jobs)))
broken = [s['company'] for s in company_stats if s['total_jobs'] == 0 and s['status'] != 'skipped']
if broken:
    print("Companies returning 0 jobs: " + str(broken))

if all_jobs:
    sample = all_jobs[0]
    print("Sample posting date: " + str(sample.get('posted_date', 'N/A')) + " (" + str(sample.get('days_ago', '?')) + " days ago)")

output = {
    'scan_date': str(datetime.date.today()),
    'scan_method': 'ats_api_direct',
    'total_companies_scanned': len(COMPANIES),
    'total_matches': len(all_jobs),
    'company_stats': company_stats,
    'jobs': all_jobs,
    'errors': errors,
}
os.makedirs(WORKSPACE, exist_ok=True)
with open(WORKSPACE + '/raw_jobs.json', 'w') as f:
    json.dump(output, f, indent=2)
print("Written to " + WORKSPACE + "/raw_jobs.json")
