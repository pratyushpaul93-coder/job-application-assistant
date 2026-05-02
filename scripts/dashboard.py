import json, os, re, threading, subprocess, csv
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)
WORKSPACE = '/root/pp-jobapp/workspace'
TAILORED_DIR = '/root/pp-jobapp/resumes/tailored'
SCRIPTS_DIR = '/root/pp-jobapp/scripts'

_VC_LABELS = {
    'accel': 'Accel',
    'general_catalyst': 'General Catalyst',
    'greylock': 'Greylock',
    'kleiner_perkins': 'Kleiner Perkins',
    'lightspeed': 'Lightspeed',
    'sequoia': 'Sequoia',
    'a16z': 'a16z',
    'bessemer': 'Bessemer',
}

def _vc_norm(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())

def _build_vc_map():
    m = {}
    csv_path = os.path.join(WORKSPACE, 'all_vc_companies.csv')
    if os.path.exists(csv_path):
        with open(csv_path, newline='') as f:
            for row in csv.DictReader(f):
                label = _VC_LABELS.get(row.get('vc', ''), row.get('vc', ''))
                for key in (_vc_norm(row.get('company_name', '')), _vc_norm(row.get('company_slug', ''))):
                    if key and key not in m:
                        m[key] = label
    a16z_path = os.path.join(SCRIPTS_DIR, 'a16z_companies.txt')
    a16z_set = set()
    if os.path.exists(a16z_path):
        for line in open(a16z_path):
            k = _vc_norm(line)
            if k:
                a16z_set.add(k)
                m.setdefault(k, _VC_LABELS['a16z'])
    master_path = os.path.join(SCRIPTS_DIR, 'companies_master.txt')
    if os.path.exists(master_path):
        for line in open(master_path):
            k = _vc_norm(line)
            if k and k not in a16z_set:
                m.setdefault(k, _VC_LABELS['bessemer'])
    return m

_VC_MAP = _build_vc_map()
_VC_SUFFIX_RE = re.compile(r'(inc|llc|labs?|ai|io|co|industries|technologies|technology|company)$')

def _lookup_vc(company_name):
    k = _vc_norm(company_name)
    if not k:
        return None
    if k in _VC_MAP:
        return _VC_MAP[k]
    stripped = _VC_SUFFIX_RE.sub('', k)
    if stripped and stripped != k and stripped in _VC_MAP:
        return _VC_MAP[stripped]
    return None

def _sanitize(s):
    """Lowercase, replace spaces/special chars with underscores, strip edges."""
    return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', s.lower())).strip('_')

def _resume_filename(company, role, ext=".pdf"):
    """Build PPaul_YYYYMMDD_company_role (max 3 words).ext"""
    date_str = datetime.now().strftime("%Y%m%d")
    company_s = _sanitize(company)
    words = _sanitize(role).split('_')[:3]
    role_s = '_'.join(words)
    return f"PPaul_{date_str}_{company_s}_{role_s}{ext}"

def _lookup_resume_meta(txt_filename):
    """Look up company_name and role_title from tailored_resumes.json for a given .txt filename."""
    p = os.path.join(WORKSPACE, "tailored_resumes.json")
    if not os.path.exists(p):
        return None, None
    for entry in json.load(open(p)):
        if entry.get("tailored_file") == txt_filename:
            return entry.get("company_name", ""), entry.get("role_title", "")
    return None, None

@app.route('/')
def index():
    return open('/root/pp-jobapp/scripts/dashboard_ui.html').read()

@app.route('/api/data')
def data():
    def load(f, default):
        p = os.path.join(WORKSPACE, f)
        return json.load(open(p)) if os.path.exists(p) else default
    shortlist = load('shortlist.json', {})
    jobs = shortlist.get('jobs', [])
    for j in jobs:
        vc = _lookup_vc(j.get('company_name', ''))
        if vc:
            j['vc'] = vc
    return jsonify({
        'jobs': jobs,
        'scan_date': shortlist.get('shortlist_date', 'unknown'),
        'companies': 25,
        'total_scanned': shortlist.get('total_scanned', 0),
        'total_shortlisted': shortlist.get('total_shortlisted', 0),
        'comments': load('comments.json', {}),
        'selected': load('selected.json', []),
        'job_status': load('job_status.json', {}),
        'feedback': load('feedback.json', {}),
    })

@app.route('/api/comment', methods=['POST'])
def comment():
    d = request.json
    p = os.path.join(WORKSPACE, 'comments.json')
    c = json.load(open(p)) if os.path.exists(p) else {}
    c[d['key']] = {'text': d.get('text',''), 'tags': d.get('tags',[]), 'updated': datetime.now().isoformat()}
    json.dump(c, open(p,'w'), indent=2)
    return jsonify({'ok': True})

@app.route('/api/select', methods=['POST'])
def select():
    d = request.json
    p = os.path.join(WORKSPACE, 'selected.json')
    sel = json.load(open(p)) if os.path.exists(p) else []
    k = d['key']
    if d.get('selected') and k not in sel: sel.append(k)
    elif not d.get('selected') and k in sel: sel.remove(k)
    json.dump(sel, open(p,'w'), indent=2)
    return jsonify({'ok': True})

@app.route("/api/feedback", methods=["POST"])
def feedback():
    d = request.json or {}
    key = (d.get("key") or d.get("job_url") or "").strip()
    raw_score = d.get("manual_score")
    comment = (d.get("comment") or "").strip()
    if not key:
        return jsonify({"error": "job_url (key) required"}), 400
    if raw_score is not None:
        try:
            score = int(raw_score)
        except (TypeError, ValueError):
            return jsonify({"error": "manual_score must be int 1-5 or null"}), 400
        if score < 1 or score > 5:
            return jsonify({"error": "manual_score must be 1-5"}), 400
    else:
        score = None
    p = os.path.join(WORKSPACE, "feedback.json")
    fb = json.load(open(p)) if os.path.exists(p) else {}
    prior = fb.get(key, {})
    if score is None and not comment:
        fb.pop(key, None)
        action = "deleted"
    else:
        entry = {
            "manual_score": score,
            "comment": comment,
            "updated": datetime.now().isoformat(),
        }
        if d.get("role_title"):
            entry["role_title"] = str(d["role_title"])[:200]
        if d.get("company_name"):
            entry["company_name"] = str(d["company_name"])[:120]
        fb[key] = entry
        action = "saved"
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(fb, f, indent=2)
    os.replace(tmp, p)
    return jsonify({
        "ok": True,
        "action": action,
        "prior_score": prior.get("manual_score"),
        "current_score": score,
    })


@app.route("/api/job_status", methods=["POST"])
def job_status():
    d = request.json
    key = d.get("key", "")
    field = d.get("field", "")
    value = d.get("value", False)
    if not key or field not in ("reviewed", "applied"):
        return jsonify({"error": "key and field (reviewed|applied) required"}), 400
    p = os.path.join(WORKSPACE, "job_status.json")
    statuses = json.load(open(p)) if os.path.exists(p) else {}
    statuses.setdefault(key, {})
    statuses[key][field] = value
    json.dump(statuses, open(p, "w"), indent=2)
    return jsonify({"ok": True})

@app.route("/api/scan", methods=["POST"])
def scan():
    import datetime as dt
    status_path = os.path.join(WORKSPACE, "scan_status.json")
    json.dump({"status": "running", "started": str(dt.datetime.now())}, open(status_path, "w"))
    def run():
        subprocess.run(["python3", "/root/pp-jobapp/scripts/ats_scout.py"])
        subprocess.run(["python3", "/root/pp-jobapp/scripts/ats_matcher.py"])
        import datetime as dt2
        json.dump({"status": "done", "finished": str(dt2.datetime.now())}, open(status_path, "w"))
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})
@app.route("/api/tailor", methods=["POST"])
def tailor_route():
    d = request.json
    status_path = os.path.join(WORKSPACE, "tailor_status.json")
    import datetime as dt
    json.dump({"status": "running", "role": d.get("role_title",""), "company": d.get("company_name",""), "started": str(dt.datetime.now())}, open(status_path, "w"))
    def run():
        import subprocess as sp
        result = sp.run(["python3", "/root/pp-jobapp/scripts/tailor.py", d.get("job_url",""), d.get("role_title",""), d.get("company_name","")], capture_output=True, text=True, timeout=120)
        import datetime as dt2
        if result.returncode == 0:
            json.dump({"status": "done", "role": d.get("role_title",""), "company": d.get("company_name","")}, open(status_path, "w"))
        else:
            json.dump({"status": "error", "error": result.stderr[:300]}, open(status_path, "w"))
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/tailor_status")
def tailor_status():
    p = os.path.join(WORKSPACE, "tailor_status.json")
    return jsonify(json.load(open(p)) if os.path.exists(p) else {"status": "idle"})

@app.route("/api/tailored_resumes")
def tailored_resumes():
    p = os.path.join(WORKSPACE, "tailored_resumes.json")
    if not os.path.exists(p):
        return jsonify([])
    data = json.load(open(p))
    for item in data:
        if item.get("job_url","").endswith("/application"):
            item["job_url"] = item["job_url"][:-len("/application")]
    return jsonify(data)

@app.route("/api/scan_status")
def scan_status():
    p = os.path.join(WORKSPACE, "scan_status.json")
    return jsonify(json.load(open(p)) if os.path.exists(p) else {"status": "idle"})

@app.route("/api/tailored_resume_content")
def tailored_resume_content():
    filename = request.args.get("file", "")
    filepath = os.path.join("/root/pp-jobapp/resumes/tailored", filename)
    if os.path.exists(filepath):
        return jsonify({"content": open(filepath).read()})
    return jsonify({"error": "not found"}), 404



@app.route("/api/revise", methods=["POST"])
def revise():
    import subprocess as sp, datetime as dt
    d = request.json
    filename = d.get("filename", "")
    comments = d.get("comments", "")
    filepath = os.path.join("/root/pp-jobapp/resumes/tailored", filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "file not found"}), 404
    current_content = open(filepath).read()
    cfg = json.load(open("/root/.openclaw/openclaw.json"))
    api_key = json.load(open("/root/.openclaw/agents/job-scout/auth-profiles.json")).get("profiles",{}).get("anthropic:default",{}).get("key","")
    import urllib.request
    prompt = (
        "You are editing a tailored resume for Pratyush Paul.\n\n"
        "CURRENT RESUME:\n" + current_content + "\n\n"
        "REVISION INSTRUCTIONS:\n" + comments + "\n\n"
        "Apply the revision instructions to the resume. Output ONLY the revised resume text, no preamble, no markdown. "
        "Keep all metrics intact. Keep one page worth of content. "
        "Keep the same structure and section order."
    )
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode())
        revised = resp["content"][0]["text"]
    open(filepath, "w").write(revised)
    return jsonify({"ok": True, "content": revised})

@app.route("/api/generate_pdf", methods=["POST"])
def generate_pdf_route():
    import subprocess as sp, shutil
    d = request.json
    filename = d.get("filename", "")
    txt_path = os.path.join(TAILORED_DIR, filename)
    if not os.path.exists(txt_path):
        return jsonify({"error": "txt file not found"}), 404

    # Resolve company/role for the new naming convention
    company = d.get("company_name", "")
    role = d.get("role_title", "")
    if not company or not role:
        c, r = _lookup_resume_meta(filename)
        company = company or c or ""
        role = role or r or ""

    if company and role:
        new_base = _resume_filename(company, role, ext="")
        new_txt = new_base + ".txt"
        new_pdf = new_base + ".pdf"
        # Copy source .txt to the new standardized name
        new_txt_path = os.path.join(TAILORED_DIR, new_txt)
        shutil.copy2(txt_path, new_txt_path)
        pdf_path = os.path.join(TAILORED_DIR, new_pdf)
    else:
        # Fallback: use original name structure
        new_pdf = filename.replace(".txt", ".pdf")
        pdf_path = os.path.join(TAILORED_DIR, new_pdf)
        new_txt_path = txt_path

    result = sp.run(["python3", "/root/pp-jobapp/scripts/generate_pdf.py", new_txt_path, pdf_path], capture_output=True, text=True, timeout=60)
    if result.returncode == 0:
        return jsonify({"ok": True, "pdf_filename": new_pdf})
    return jsonify({"error": result.stderr[-1000:]}), 500

@app.route("/api/download_pdf")
def download_pdf():
    from flask import send_file
    import subprocess as sp
    filename = request.args.get("file", "") or request.args.get("filename", "")
    if not filename:
        return "Not found", 404

    # Determine source .txt and target .pdf paths
    if filename.endswith(".pdf"):
        pdf_name = filename
        txt_name = filename.replace(".pdf", ".txt")
    else:
        txt_name = filename
        pdf_name = filename.replace(".txt", ".pdf")

    txt_path = os.path.join(TAILORED_DIR, txt_name)
    pdf_path = os.path.join(TAILORED_DIR, pdf_name)

    # Regenerate PDF from latest .txt before serving
    if os.path.exists(txt_path):
        sp.run(["python3", "/root/pp-jobapp/scripts/generate_pdf.py", txt_path, pdf_path],
               capture_output=True, text=True, timeout=60)

    if os.path.exists(pdf_path):
        # Build a clean download name using the new convention if we can resolve metadata
        download_name = pdf_name
        company, role = _lookup_resume_meta(txt_name)
        if company and role:
            download_name = _resume_filename(company, role, ext=".pdf")
        return send_file(pdf_path, as_attachment=True, download_name=download_name)
    return "Not found", 404




@app.route("/api/add_company/detect", methods=["POST"])
def add_company_detect():
    import urllib.request as _ur, json as _json, re as _re
    d = request.json or {}
    name = d.get("name", "").strip()
    if not name:
        return jsonify({"error": "company name required"}), 400
    base = _re.sub(r"[^a-z0-9]", "", name.lower())
    base_hyphen = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    candidates = list(dict.fromkeys([base, base_hyphen, base + "hq", "get" + base, base + "-ai", base + "so"]))
    def _get(url):
        try:
            req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with _ur.urlopen(req, timeout=8) as r:
                return _json.loads(r.read().decode())
        except:
            return None
    for slug in candidates:
        data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false")
        if data and data.get("jobs"):
            jobs = data["jobs"]
            return jsonify({"found": True, "ats": "ashby", "slug": slug, "total_jobs": len(jobs), "sample_titles": [j.get("title","") for j in jobs[:5]]})
    for slug in candidates:
        data = _get(f"https://api.greenhouse.io/v1/boards/{slug}/jobs")
        if data and data.get("jobs"):
            jobs = data["jobs"]
            return jsonify({"found": True, "ats": "greenhouse", "slug": slug, "total_jobs": len(jobs), "sample_titles": [j.get("title","") for j in jobs[:5]]})
    for slug in candidates:
        data = _get(f"https://api.lever.co/v0/postings/{slug}")
        if isinstance(data, list) and data:
            return jsonify({"found": True, "ats": "lever", "slug": slug, "total_jobs": len(data), "sample_titles": [j.get("text","") for j in data[:5]]})
    return jsonify({"found": False, "tried_slugs": candidates})


@app.route("/api/add_company/confirm", methods=["POST"])
def add_company_confirm():
    import re as _re
    d = request.json or {}
    name     = d.get("name", "").strip()
    ats      = d.get("ats", "").strip()
    slug     = d.get("slug", "").strip()
    stage    = d.get("stage", "Unknown").strip()
    vertical = d.get("vertical", "SaaS").strip()
    if not all([name, ats, slug]):
        return jsonify({"error": "name, ats, slug required"}), 400
    scout_path = "/root/pp-jobapp/scripts/ats_scout.py"
    content = open(scout_path).read()
    if f"'slug': '{slug}'" in content:
        return jsonify({"error": f"Slug '{slug}' already exists in COMPANIES"}), 409
    pattern = _re.compile(r"(COMPANIES\s*=\s*\[.*?\])", _re.DOTALL)
    m = pattern.search(content)
    if not m:
        return jsonify({"error": "Could not parse COMPANIES list"}), 500
    new_entry = f"    {{'name': '{name}', 'ats': '{ats}', 'slug': '{slug}', 'stage': '{stage}', 'vertical': '{vertical}'}},\n"
    old_block = m.group(1).rstrip()
    if old_block.endswith("]"):
        new_block = old_block[:-1].rstrip()
        if not new_block.endswith(","):
            new_block += ","
        new_block += "\n" + new_entry + "]"
    else:
        return jsonify({"error": "Unexpected COMPANIES format"}), 500
    new_content = content[:m.start(1)] + new_block + content[m.end(1):]
    open(scout_path, "w").write(new_content)
    return jsonify({"ok": True, "message": f"{name} ({ats}/{slug}) added to COMPANIES"})




@app.route("/api/companies/delete", methods=["POST"])
def delete_company():
    import re as _re
    data = request.get_json(force=True)
    name = (data or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    # 1) Remove from COMPANIES list in ats_scout.py (text-level rewrite)
    scout_path = "/root/pp-jobapp/scripts/ats_scout.py"
    scout = open(scout_path).read()
    pattern = _re.compile(r"COMPANIES\s*=\s*(\[.*?\])", _re.DOTALL)
    m = pattern.search(scout)
    if not m:
        return jsonify({"error": "Could not parse COMPANIES in ats_scout.py"}), 500
    try:
        entries = eval(m.group(1))
    except Exception:
        return jsonify({"error": "Failed to eval COMPANIES"}), 500
    new_entries = [e for e in entries if e.get("name", "").lower() != name.lower()]
    if len(new_entries) == len(entries):
        return jsonify({"error": f"Company '{name}' not found"}), 404
    new_block = "[\n" + ",\n".join("    " + repr(e) for e in new_entries) + "\n]"
    new_content = scout[:m.start(1)] + new_block + scout[m.end(1):]
    open(scout_path, "w").write(new_content)

    # 2) Clean workspace JSON files
    name_lower = name.lower()
    for fname in ("shortlist.json", "raw_jobs.json"):
        fpath = os.path.join(WORKSPACE, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath) as f:
            jdata = json.load(f)
        if isinstance(jdata.get("jobs"), list):
            jdata["jobs"] = [j for j in jdata["jobs"] if j.get("company_name", "").lower() != name_lower]
        if isinstance(jdata.get("company_stats"), list):
            jdata["company_stats"] = [s for s in jdata["company_stats"] if s.get("company", "").lower() != name_lower]
        with open(fpath, "w") as f:
            json.dump(jdata, f, indent=2)

    return jsonify({"ok": True, "removed": name})


@app.route("/api/companies")
def companies():
    import re as _re
    # Parse COMPANIES list from ats_scout.py
    scout_path = "/root/pp-jobapp/scripts/ats_scout.py"
    scout = open(scout_path).read()
    pattern = _re.compile(r"COMPANIES\s*=\s*(\[.*?\])", _re.DOTALL)
    m = pattern.search(scout)
    companies = []
    if m:
        try:
            companies = eval(m.group(1))
        except:
            companies = []

    # Merge with raw_jobs.json scan stats
    raw_path = os.path.join(WORKSPACE, "raw_jobs.json")
    stats_by_company = {}
    scan_date = None
    if os.path.exists(raw_path):
        raw = json.load(open(raw_path))
        scan_date = raw.get("scan_date", None)
        for s in raw.get("company_stats", []):
            stats_by_company[s["company"]] = s

    result = []
    for c in companies:
        s = stats_by_company.get(c["name"], {})
        result.append({
            "name": c["name"],
            "ats": c["ats"],
            "slug": c["slug"],
            "stage": c.get("stage", "Unknown"),
            "vertical": c.get("vertical", "Unknown"),
            "total_jobs": s.get("total_jobs", None),
            "matches": s.get("matches", None),
            "status": s.get("status", "not scanned"),
            "last_scanned": scan_date,
        })
    return jsonify({"companies": result, "scan_date": scan_date, "total": len(result)})



@app.route("/api/tailor_manual", methods=["POST"])
def tailor_manual():
    import datetime as dt, subprocess as sp, tempfile, os as _os
    d = request.json or {}
    role_title   = d.get("role_title", "").strip()
    company_name = d.get("company_name", "").strip()
    job_url      = d.get("job_url", "").strip()
    jd_text      = d.get("jd_text", "").strip()
    version      = d.get("version", "").strip()

    if not role_title or not company_name:
        return jsonify({"error": "role_title and company_name required"}), 400
    if not job_url and not jd_text:
        return jsonify({"error": "job_url or jd_text required"}), 400

    status_path = os.path.join(WORKSPACE, "tailor_status.json")
    json.dump({"status": "running", "role": role_title, "company": company_name,
               "started": str(dt.datetime.now())}, open(status_path, "w"))

    def run():
        import datetime as dt2, subprocess as _sp, tempfile as _tmp, os as _os
        try:
            # If raw JD text supplied, write to temp file and pass as file:// url
            if jd_text:
                tmp = _tmp.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
                tmp.write(jd_text)
                tmp.close()
                url_arg = "file://" + tmp.name
            else:
                url_arg = job_url

            cmd = ["python3", "/root/pp-jobapp/scripts/tailor.py",
                   url_arg, role_title, company_name]
            if version:
                cmd.append(version)

            result = _sp.run(cmd, capture_output=True, text=True, timeout=120)

            if jd_text and _os.path.exists(tmp.name):
                _os.unlink(tmp.name)

            if result.returncode == 0:
                json.dump({"status": "done", "role": role_title, "company": company_name},
                          open(status_path, "w"))
            else:
                json.dump({"status": "error", "error": result.stderr[:500]},
                          open(status_path, "w"))
        except Exception as e:
            json.dump({"status": "error", "error": str(e)}, open(status_path, "w"))

    import threading as _th
    _th.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})


# BASH EXECUTION API (used by Claude for remote debugging)
import uuid, threading
bash_jobs = {}

@app.route("/api/bash", methods=["POST"])
def run_bash():
    data = request.json or {}
    command = data.get("command", "").strip()
    if not command:
        return jsonify({"error": "no command provided"}), 400
    blocked = ["rm -rf /", "mkfs", "dd if=", "> /etc", "auth-profiles", "openclaw.json"]
    if any(b in command for b in blocked):
        return jsonify({"error": "REFUSED: command blocked"}), 403
    job_id = str(uuid.uuid4())
    bash_jobs[job_id] = {"status": "running", "output": None}
    def run():
        try:
            import subprocess as _sp
            result = _sp.run(
                command, shell=True, capture_output=True, text=True,
                timeout=60, cwd="/root/pp-jobapp"
            )
            out = result.stdout
            if result.stderr.strip():
                out = out + chr(10) + "STDERR: " + result.stderr
            bash_jobs[job_id] = {"status": "done", "output": out.strip()}
        except Exception as e:
            bash_jobs[job_id] = {"status": "error", "output": "ERROR: " + str(e)}
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})

@app.route("/api/bash_status", methods=["GET"])
def bash_status():
    job_id = request.args.get("job_id", "")
    if job_id not in bash_jobs:
        return jsonify({"status": "error", "output": "job_id not found"}), 404
    return jsonify(bash_jobs[job_id])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
