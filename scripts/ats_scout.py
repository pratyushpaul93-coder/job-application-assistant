import json, urllib.request, datetime, os

WORKSPACE = '/root/pp-jobapp/workspace'

# Role keywords - POSITIVE (must match at least one)
# Covers: S&O, CoS, GTM Ops, Sales Ops, Rev Ops, Product Ops, Strategic Programs
ROLE_KEYWORDS_POSITIVE = [
    # Strategy & Operations variants
    'strategy & operations', 'strategy and operations', 'strategic operations',
    'strategy operations', 'bizops', 'biz ops', 'business operations',
    'operational strategy', 'operational excellence',
    # Chief of Staff
    'chief of staff', 'cos ',
    # GTM Operations
    'gtm operations', 'gtm ops', 'go-to-market operations', 'go to market operations',
    'gtm strategy', 'gtm programs',
    # Sales Operations
    'sales operations', 'sales ops',
    # Revenue Operations
    'revenue operations', 'revenue ops', 'revops', 'rev ops',
    # Product Operations
    'product operations', 'product ops',
    # Growth/Field Operations
    'growth operations', 'field operations manager',
    'head of operations', 'vp of operations', 'director of operations',
    'vp operations', 'director operations',
    # Strategic Programs & Planning
    'strategic program', 'strategic programs', 'strategic initiatives',
    'strategy and planning', 'strategy & planning',
    'program manager, strategy', 'program manager strategy',
    'technical program manager',
    # General Manager
    'general manager',
    # Finance & Ops adjacent
    'gtm finance', 'strategic finance',
    # Onboarding & Readiness (S&O adjacent at startups)
    'gtm onboarding', 'gtm readiness',
]

# Negative keywords - if any match, skip the role
ROLE_KEYWORDS_NEGATIVE = [
    'security operations', 'soc analyst', 'it operations', 'it ops',
    'devops', 'dev ops', 'sre ', 'site reliability',
    'software engineer', 'software developer', 'ml engineer', 'ai engineer',
    'data engineer', 'data scientist', 'research engineer',
    'marketing operations', 'marketing ops',  # too functional
    'hr operations', 'people operations analyst', 'people ops analyst',
    'facilities', 'legal operations',
    'customer success', 'support operations', 'customer operations analyst',
    'intern', 'junior', 'coordinator',
    'recruiting operations', 'talent operations',
    'financial operations analyst',  # too junior
    'lifecycle marketing operations',  # too functional
]

COMPANIES = [
    # Ashby
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
    # Greenhouse
    {'name': 'Glean', 'ats': 'greenhouse', 'slug': 'gleanwork', 'stage': 'Series E', 'vertical': 'AI'},
    {'name': 'Brex', 'ats': 'greenhouse', 'slug': 'brex', 'stage': 'Series D', 'vertical': 'Fintech'},
    {'name': 'Cyera', 'ats': 'greenhouse', 'slug': 'cyera', 'stage': 'Series C', 'vertical': 'SaaS'},
    {'name': 'Airtable', 'ats': 'greenhouse', 'slug': 'airtable', 'stage': 'Series F', 'vertical': 'SaaS'},
    {'name': 'Vercel', 'ats': 'greenhouse', 'slug': 'vercel', 'stage': 'Series D', 'vertical': 'AI'},
    {'name': 'Intercom', 'ats': 'greenhouse', 'slug': 'intercom', 'stage': 'Public', 'vertical': 'SaaS'},
    {'name': 'Anthropic', 'ats': 'greenhouse', 'slug': 'anthropic', 'stage': 'Series E', 'vertical': 'AI'},
    {'name': 'Wiz', 'ats': 'greenhouse', 'slug': 'wizsecurity', 'stage': 'Series E', 'vertical': 'SaaS'},
    # Lever
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
    except Exception as e:
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
        matches.append({
            'company_name': company['name'],
            'role_title': title,
            'apply_url': j.get('applyUrl') or j.get('jobUrl', ''),
            'job_url': j.get('jobUrl', ''),
            'source': 'ashby',
            'date_found': str(datetime.date.today()),
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
        matches.append({
            'company_name': company['name'],
            'role_title': title,
            'apply_url': j.get('absolute_url', ''),
            'job_url': j.get('absolute_url', ''),
            'source': 'greenhouse',
            'date_found': str(datetime.date.today()),
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
        matches.append({
            'company_name': company['name'],
            'role_title': title,
            'apply_url': j.get('applyUrl', j.get('hostedUrl', '')),
            'job_url': j.get('hostedUrl', ''),
            'source': 'lever',
            'date_found': str(datetime.date.today()),
            'location_raw': location,
            'remote_ok': 'remote' in location.lower() if location else False,
            'company_stage': company.get('stage', 'Unknown'),
            'industry_vertical': company.get('vertical', 'Unknown'),
            'ai_native': company.get('vertical') == 'AI',
            'compensation': '',
        })
    return matches, len(data)

# Main scan
print(f"PP Job Scout - ATS API Scan")
print(f"Date: {datetime.date.today()}")
print(f"Companies: {len(COMPANIES)}")
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
            print(f"  {company['name']}: skipped (custom ATS - use Tavily fallback)")
            company_stats.append({'company': company['name'], 'ats': 'custom', 'total_jobs': 0, 'matches': 0, 'status': 'skipped'})
            continue

        status = 'ok' if total > 0 else 'empty'
        print(f"  {company['name']} ({ats}): {len(matches)} potential matches, {total} total jobs")
        all_jobs.extend(matches)
        company_stats.append({'company': company['name'], 'ats': ats, 'total_jobs': total, 'matches': len(matches), 'status': status})

    except Exception as e:
        errors.append(f"{company['name']}: {e}")
        print(f"  {company['name']}: ERROR - {e}")
        company_stats.append({'company': company['name'], 'ats': ats, 'total_jobs': 0, 'matches': 0, 'status': f'error: {e}'})

print("-" * 50)
print(f"Total potential matches: {len(all_jobs)}")
print(f"Companies returning 0 jobs (check slugs): {[s['company'] for s in company_stats if s['total_jobs'] == 0 and s['status'] != 'skipped']}")

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
with open(f'{WORKSPACE}/raw_jobs.json', 'w') as f:
    json.dump(output, f, indent=2)

print(f"Written to {WORKSPACE}/raw_jobs.json")
