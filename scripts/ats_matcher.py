import json, urllib.request, os, datetime

WORKSPACE   = '/root/pp-jobapp/workspace'
CONFIG_PATH = '/root/pp-jobapp/scripts/scout_config.json'
FEEDBACK    = WORKSPACE + '/feedback.json'

def get_deepseek_key():
    try:
        cfg = json.load(open('/root/.openclaw/openclaw.json'))
        return cfg.get('models',{}).get('providers',{}).get('deepseek',{}).get('apiKey','')
    except:
        return ''

def _load_feedback_settings():
    try:
        cfg = json.load(open(CONFIG_PATH))
        s = cfg.get('scout_settings', {})
        return bool(s.get('feedback_loop_enabled', True)), int(s.get('feedback_max_examples', 8))
    except Exception:
        return True, 8

def _load_feedback():
    if not os.path.exists(FEEDBACK):
        return {}
    try:
        return json.load(open(FEEDBACK))
    except Exception:
        return {}

def select_few_shot_examples(max_n=8):
    """Return a list of formatted few-shot example strings.
    Prioritization: 2 high(4-5), 2 low(1-2), 2 mid(3), then fillers.
    Within each bucket, prefer entries with comments and most-recent updates.
    """
    fb = _load_feedback()
    if not fb:
        return []
    rows = []
    for key, e in fb.items():
        score = e.get('manual_score')
        if not isinstance(score, int) or score < 1 or score > 5:
            continue
        rows.append({
            'score':   score,
            'comment': (e.get('comment') or '').strip(),
            'title':   (e.get('role_title') or '').strip() or '(unknown role)',
            'company': (e.get('company_name') or '').strip() or '(unknown company)',
            'updated': e.get('updated', ''),
        })
    if not rows:
        return []
    high = [r for r in rows if r['score'] >= 4]
    low  = [r for r in rows if r['score'] <= 2]
    mid  = [r for r in rows if r['score'] == 3]
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
    lines = ['Calibration examples — these are the user\'s own ratings on prior roles. '
             'Use them to anchor your scoring style:']
    for r in examples:
        line = f"- {r['title']} at {r['company']} — User rated {r['score']}/5"
        if r['comment']:
            line += f". Comment: {r['comment']}"
        line += '.'
        lines.append(line)
    lines.append('')  # trailing blank line
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

def score_job(job, api_key, few_shot_block=''):
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
        " | Location: " + str(job.get('location_raw','?')) +
        " | Stage: " + str(job.get('company_stage','?')) +
        " | Vertical: " + str(job.get('industry_vertical','?')) +
        " | AI company: " + str(job.get('ai_native',False)) +
        " | Remote: " + str(job.get('remote_ok',False)) + "\n\n"
        "JD:\n" + (jd or '(no JD body)')
    )
    try:
        payload = json.dumps({
            "model": "deepseek-chat",
            "max_tokens": 120,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()
        req = urllib.request.Request(
            'https://api.deepseek.com/v1/chat/completions',
            data=payload,
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + api_key}
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read().decode())
            content = resp['choices'][0]['message']['content'].strip()
            if '{' in content:
                content = content[content.index('{'):content.rindex('}')+1]
            result = json.loads(content)
            return int(result.get('score', 0)), str(result.get('reason', ''))
    except Exception as e:
        return 0, 'error: ' + str(e)[:120]

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

if __name__ == '__main__':
    api_key = get_deepseek_key()
    print('PP Job Matcher')
    print('Date: ' + str(datetime.date.today()))
    print('DeepSeek key: ' + ('found' if api_key else 'MISSING'))

    fb_enabled, fb_max = _load_feedback_settings()
    few_shot_block = build_few_shot_block(fb_max) if fb_enabled else ''
    if few_shot_block:
        n_lines = few_shot_block.count('\n- ')
        print('Feedback loop: ENABLED, ' + str(n_lines) + ' few-shot examples loaded')
    else:
        print('Feedback loop: ' + ('enabled but no feedback yet' if fb_enabled else 'DISABLED via config'))

    raw = json.load(open(WORKSPACE + '/raw_jobs.json'))
    jobs = raw.get('jobs', [])
    scan_date = raw.get('scan_date', str(datetime.date.today()))
    print('Loaded ' + str(len(jobs)) + ' jobs from ' + scan_date)
    print('-' * 50)

    scored = []
    for job in jobs:
        score, reason = score_job(job, api_key, few_shot_block)
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
