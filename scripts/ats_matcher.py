import json, urllib.request, os, datetime

WORKSPACE = '/root/pp-jobapp/workspace'

def get_deepseek_key():
    try:
        cfg = json.load(open('/root/.openclaw/openclaw.json'))
        return cfg.get('models',{}).get('providers',{}).get('deepseek',{}).get('apiKey','')
    except:
        return ''

PROFILE = (
    "Pratyush Paul - S&O professional, 6+ years. "
    "Background: Strategy& Dubai (consulting), Accenture Singapore (ops transformation), "
    "Urban Company Singapore (two-sided marketplace, unit economics), "
    "Armor Defense Chicago (cross-functional, built AI projects: SEC RAG + Spotify MCP). "
    "Target: S&O, CoS, GTM Ops, Sales Ops, Rev Ops, Product Ops, TPM at SaaS/AI startups. "
    "Strong fit: marketplace, AI-native, consulting valued, Series A-D. "
    "Location: all US. SQL: learning, flag as info only never reduce score."
)

def score_job(job, api_key):
    if not api_key:
        return 3, "No API key"
    prompt = (
        "Score this job 1-5 for candidate. Return ONLY JSON: {score: N, reason: one sentence}. "
        "5=excellent fit, 4=good, 3=possible, 2=weak, 1=skip. "
        "Profile: " + PROFILE + " "
        "Job: " + job['role_title'] + " at " + job['company_name'] + 
        " | Location: " + str(job.get('location_raw','?')) +
        " | Stage: " + str(job.get('company_stage','?')) +
        " | Vertical: " + str(job.get('industry_vertical','?')) +
        " | AI company: " + str(job.get('ai_native',False)) +
        " | Remote: " + str(job.get('remote_ok',False))
    )
    try:
        payload = json.dumps({
            "model": "deepseek-chat",
            "max_tokens": 80,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()
        req = urllib.request.Request(
            'https://api.deepseek.com/v1/chat/completions',
            data=payload,
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + api_key}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode())
            content = resp['choices'][0]['message']['content'].strip()
            if '{' in content:
                content = content[content.index('{'):content.rindex('}')+1]
            result = json.loads(content)
            return int(result.get('score', 3)), str(result.get('reason', ''))
    except Exception as e:
        return 3, 'error: ' + str(e)[:40]

def build_whatsapp(shortlist, scan_date, total):
    lines = [
        'Job Shortlist - ' + scan_date,
        str(len(shortlist)) + ' matches from ' + str(total) + ' real listings',
        ''
    ]
    for i, job in enumerate(shortlist[:10], 1):
        loc = 'Remote' if job.get('remote_ok') else str(job.get('location_raw','?'))
        sql = ' | SQL:Required' if job.get('sql_required') else (' | SQL:Mentioned' if job.get('sql_mentioned') else '')
        lines.append(str(i) + '. ' + str(job['match_score']) + '/5 - ' + job['role_title'] + ' @ ' + job['company_name'])
        lines.append('   ' + loc + ' | ' + str(job.get('company_stage','?')) + sql)
        lines.append('   ' + str(job.get('reason','')))
        lines.append('   ' + str(job.get('apply_url','')))
        lines.append('')
    lines.append("Reply 'tailor N' to draft resume for that role.")
    return chr(10).join(lines)

api_key = get_deepseek_key()
print('PP Job Matcher')
print('Date: ' + str(datetime.date.today()))
print('DeepSeek key: ' + ('found' if api_key else 'MISSING'))

raw = json.load(open(WORKSPACE + '/raw_jobs.json'))
jobs = raw.get('jobs', [])
scan_date = raw.get('scan_date', str(datetime.date.today()))
print('Loaded ' + str(len(jobs)) + ' jobs from ' + scan_date)
print('-' * 50)

scored = []
for job in jobs:
    score, reason = score_job(job, api_key)
    if score >= 3:
        job['match_score'] = score
        job['reason'] = reason
        scored.append(job)
        print('  ' + str(score) + '/5 - ' + job['role_title'] + ' @ ' + job['company_name'])

scored.sort(key=lambda x: x['match_score'], reverse=True)
print('-' * 50)
print('Shortlisted: ' + str(len(scored)) + ' roles scoring 3+')

shortlist = {
    'shortlist_date': str(datetime.date.today()),
    'total_scanned': len(jobs),
    'total_shortlisted': len(scored),
    'jobs': scored
}
json.dump(shortlist, open(WORKSPACE + '/shortlist.json', 'w'), indent=2)
print('Written to ' + WORKSPACE + '/shortlist.json')

msg = build_whatsapp(scored, scan_date, len(jobs))
open(WORKSPACE + '/whatsapp_message.txt', 'w').write(msg)
print('')
print('--- WHATSAPP MESSAGE ---')
print(msg[:1500])
print('--- END ---')
