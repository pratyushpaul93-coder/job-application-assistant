import json, os, re, threading, subprocess, csv, sys
from datetime import datetime
from flask import Flask, request, jsonify
from werkzeug.utils import safe_join

app = Flask(__name__)
WORKSPACE = '/root/pp-jobapp/workspace'
TAILORED_DIR = '/root/pp-jobapp/resumes/tailored'
SCRIPTS_DIR = '/root/pp-jobapp/scripts'
DB_PATH = os.path.join(WORKSPACE, 'jobapp.db')
sys.path.insert(0, SCRIPTS_DIR)
import storage
from keys import get_anthropic_key
from ats_matcher import SCORER  # 'current_shortlist' (defined ats_matcher.py:52)
# Threshold isn't centralized; matcher hardcodes >=3 at ats_matcher.py:187,
# storage.export_dashboard_payload defaults min_score=3 (storage.py:892).
MIN_MATCH_SCORE = 3

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
    """Look up company_name and role_title for a given .txt filename from the DB."""
    conn = _db_conn()
    if not conn:
        return None, None
    try:
        for entry in storage.export_tailored_resumes(conn):
            if entry.get("tailored_file") == txt_filename:
                return entry.get("company_name", ""), entry.get("role_title", "")
    finally:
        conn.close()
    return None, None

def _canonical_tailor_filename(role_title, company_name, version=""):
    """Mirror tailor.py's <YYYY-MM-DD>_<slug>[_<version>].txt construction."""
    slug = (role_title + "_" + company_name).lower().replace(" ", "_").replace("/", "_")[:50]
    date_str = datetime.now().strftime("%Y-%m-%d")
    suffix = ("_" + version) if version else ""
    return f"{date_str}_{slug}{suffix}.txt"

def _refresh_standardized_snapshot(txt_filename, company, role):
    """Copy canonical <date>_<slug>.txt to PPaul_<date>_<company>_<role>.txt and rebuild
    its PDF, so the Download link always serves the latest tailor/revise output.
    Returns the new PDF basename on success, None otherwise."""
    import subprocess as sp, shutil
    if not company or not role:
        return None
    txt_path = _tailored_path(txt_filename, {".txt"})
    if not txt_path or not os.path.exists(txt_path):
        return None
    new_base = _resume_filename(company, role, ext="")
    new_txt_path = os.path.join(TAILORED_DIR, new_base + ".txt")
    new_pdf_path = os.path.join(TAILORED_DIR, new_base + ".pdf")
    try:
        shutil.copy2(txt_path, new_txt_path)
        sp.run(
            ["python3", "/root/pp-jobapp/scripts/generate_pdf.py", new_txt_path, new_pdf_path],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return None
    return new_base + ".pdf"

def _tailored_path(filename, allowed_exts=None):
    """Resolve a user-provided tailored-resume filename inside TAILORED_DIR."""
    filename = (filename or "").strip()
    if not filename:
        return None
    if allowed_exts and not any(filename.endswith(ext) for ext in allowed_exts):
        return None
    path = safe_join(TAILORED_DIR, filename)
    if not path:
        return None
    base = os.path.abspath(TAILORED_DIR)
    resolved = os.path.abspath(path)
    if os.path.commonpath([base, resolved]) != base:
        return None
    return resolved

def _db_conn():
    if not os.path.exists(DB_PATH):
        return None
    return storage.connect(DB_PATH)


def _require_db():
    """Open a DB connection or abort the request with HTTP 500.

    The dashboard is SQLite-native; legacy JSON fallback has been removed.
    Routes use this so the failure mode is visible (500 + clear message)
    rather than silent stale-JSON reads.
    """
    conn = _db_conn()
    if conn is None:
        from flask import abort
        abort(
            500,
            description=(
                f"SQLite DB required at {DB_PATH}. "
                "Run: python3 scripts/migrate_to_db.py --reset"
            ),
        )
    return conn

@app.route('/')
def index():
    return open('/root/pp-jobapp/scripts/dashboard_ui.html').read()

DESIGNS_DIR = '/root/pp-jobapp/designs'

@app.route('/designs/')
@app.route('/designs/<path:filename>')
def designs(filename='index.html'):
    """Serve design-mockup HTML/CSS for in-browser review. Read-only, scoped to designs/."""
    from flask import send_from_directory, abort
    safe = safe_join(DESIGNS_DIR, filename)
    if not safe or not os.path.isfile(safe):
        abort(404)
    base = os.path.abspath(DESIGNS_DIR)
    if os.path.commonpath([base, os.path.abspath(safe)]) != base:
        abort(404)
    return send_from_directory(DESIGNS_DIR, filename)

@app.route('/api/data')
def data():
    conn = _require_db()
    try:
        payload = storage.export_dashboard_payload(conn)
    finally:
        conn.close()
    for j in payload.get('jobs', []):
        vc = _lookup_vc(j.get('company_name', ''))
        if vc:
            j['vc'] = vc
    return jsonify(payload)

@app.route('/api/comment', methods=['POST'])
def comment():
    d = request.json
    key = d['key']
    text = d.get('text', '')
    tags = d.get('tags', [])
    conn = _require_db()
    try:
        storage.update_job_interaction(conn, key, comment=text, tags=tags)
    finally:
        conn.close()
    return jsonify({'ok': True})

@app.route('/api/select', methods=['POST'])
def select():
    d = request.json
    k = d['key']
    conn = _require_db()
    try:
        storage.update_job_interaction(conn, k, selected=bool(d.get('selected')))
    finally:
        conn.close()
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
    action = "deleted" if (score is None and not comment) else "saved"

    conn = _require_db()
    try:
        prior_score = None
        job_id = storage.job_id_for_url(conn, key)
        if job_id is not None:
            row = conn.execute(
                "SELECT manual_score FROM job_interactions WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is not None:
                prior_score = row["manual_score"]
        storage.update_job_interaction(
            conn,
            key,
            manual_score=score,
            manual_score_comment=comment,
            clear_manual_score=(score is None),
        )
    finally:
        conn.close()
    return jsonify({
        "ok": True,
        "action": action,
        "prior_score": prior_score,
        "current_score": score,
    })


@app.route("/api/job_status", methods=["POST"])
def job_status():
    d = request.json
    key = d.get("key", "")
    field = d.get("field", "")
    value = d.get("value", False)
    if not key or field not in ("reviewed", "applied", "reached_out", "no_outreach"):
        return jsonify({"error": "key and field (reviewed|applied|reached_out|no_outreach) required"}), 400
    conn = _require_db()
    try:
        storage.update_job_interaction(conn, key, **{field: bool(value)})
    finally:
        conn.close()
    return jsonify({"ok": True})

@app.route("/api/scan", methods=["POST"])
def scan():
    import datetime as dt
    status_path = os.path.join(WORKSPACE, "scan_status.json")
    json.dump({"status": "running", "started": str(dt.datetime.now())}, open(status_path, "w"))
    def run():
        # Scout writes job_postings directly; no migrate_to_db step needed.
        subprocess.run(["python3", "/root/pp-jobapp/scripts/ats_scout.py"])
        subprocess.run(["python3", "/root/pp-jobapp/scripts/ats_matcher.py"])
        import datetime as dt2
        json.dump({"status": "done", "finished": str(dt2.datetime.now())}, open(status_path, "w"))
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})
@app.route("/api/tailor", methods=["POST"])
def tailor_route():
    return _run_tailor(request.json or {}, comments="")

@app.route("/api/regenerate", methods=["POST"])
def regenerate_route():
    """Re-run tailor.py with the user's comments injected. Same model (Sonnet 4.6)
    as the initial Tailor flow; differs only in that the comment text is added
    to the prompt as USER GUIDANCE."""
    d = request.json or {}
    comments = (d.get("comments") or "").strip()
    return _run_tailor(d, comments=comments)

def _run_tailor(d, *, comments=""):
    status_path = os.path.join(WORKSPACE, "tailor_status.json")
    import datetime as dt
    json.dump({"status": "running", "role": d.get("role_title",""), "company": d.get("company_name",""), "started": str(dt.datetime.now())}, open(status_path, "w"))
    def run():
        import subprocess as sp
        role = d.get("role_title","")
        company = d.get("company_name","")
        cmd = ["python3", "/root/pp-jobapp/scripts/tailor.py", d.get("job_url",""), role, company]
        if comments:
            cmd += ["--comments", comments]
        result = sp.run(cmd, capture_output=True, text=True, timeout=120)
        import datetime as dt2
        if result.returncode == 0:
            _refresh_standardized_snapshot(_canonical_tailor_filename(role, company), company, role)
            json.dump({"status": "done", "role": role, "company": company}, open(status_path, "w"))
        else:
            json.dump({"status": "error", "error": (result.stderr or result.stdout)[-300:]}, open(status_path, "w"))
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/tailor_status")
def tailor_status():
    p = os.path.join(WORKSPACE, "tailor_status.json")
    return jsonify(json.load(open(p)) if os.path.exists(p) else {"status": "idle"})

@app.route("/api/tailored_resumes")
def tailored_resumes():
    conn = _require_db()
    try:
        data = storage.export_tailored_resumes(conn)
    finally:
        conn.close()
    for item in data:
        if item.get("job_url", "").endswith("/application"):
            item["job_url"] = item["job_url"][:-len("/application")]
    return jsonify(data)

@app.route("/api/scan_status")
def scan_status():
    p = os.path.join(WORKSPACE, "scan_status.json")
    return jsonify(json.load(open(p)) if os.path.exists(p) else {"status": "idle"})


@app.route("/api/pipeline")
def pipeline():
    """Read-only state-of-the-pipeline payload for the Pipeline tab."""
    conn = _require_db()
    try:
        cur = conn.cursor()

        total_active = cur.execute(
            "SELECT COUNT(*) AS n FROM companies WHERE active=1"
        ).fetchone()["n"]

        with_url = cur.execute(
            "SELECT COUNT(*) AS n FROM companies "
            "WHERE active=1 AND website_url IS NOT NULL AND website_url != ''"
        ).fetchone()["n"]

        with_active_ats = cur.execute(
            "SELECT COUNT(DISTINCT ae.company_id) AS n "
            "FROM ats_endpoints ae JOIN companies c ON c.id = ae.company_id "
            "WHERE c.active=1 AND ae.status='active'"
        ).fetchone()["n"]

        total_jobs = cur.execute(
            "SELECT COUNT(*) AS n FROM job_postings"
        ).fetchone()["n"]

        scored_jobs = cur.execute(
            "SELECT COUNT(DISTINCT job_id) AS n FROM job_scores WHERE scorer = ?",
            (SCORER,),
        ).fetchone()["n"]

        matched_jobs = cur.execute(
            "SELECT COUNT(DISTINCT job_id) AS n FROM job_scores "
            "WHERE scorer = ? AND score >= ?",
            (SCORER, MIN_MATCH_SCORE),
        ).fetchone()["n"]

        # Section 2: companies with website_url but no working ATS endpoint
        gap_rows = cur.execute(
            """
            WITH cand AS (
              SELECT c.id FROM companies c
              WHERE c.active=1
                AND c.website_url IS NOT NULL AND c.website_url != ''
                AND NOT EXISTS (
                  SELECT 1 FROM ats_endpoints ae
                  WHERE ae.company_id=c.id AND ae.status='active'
                )
            )
            SELECT
              CASE WHEN ae.status IS NULL THEN 'never_probed' ELSE ae.status END AS bucket,
              COUNT(DISTINCT c.id) AS n
            FROM cand c LEFT JOIN ats_endpoints ae ON ae.company_id = c.id
            GROUP BY bucket ORDER BY n DESC
            """
        ).fetchall()
        gap = [{"status": r["bucket"], "count": r["n"]} for r in gap_rows]

        # Section 3: working ATS endpoints by provider
        prov_rows = cur.execute(
            """
            SELECT ae.provider AS provider, COUNT(DISTINCT ae.company_id) AS n
            FROM ats_endpoints ae JOIN companies c ON c.id = ae.company_id
            WHERE c.active=1 AND ae.status='active'
            GROUP BY ae.provider ORDER BY n DESC
            """
        ).fetchall()
        providers = [{"provider": r["provider"], "count": r["n"]} for r in prov_rows]

        # Section 4: top companies by matched jobs
        top_rows = cur.execute(
            """
            SELECT c.canonical_name AS name, COUNT(DISTINCT j.id) AS n
            FROM job_scores s
            JOIN job_postings j ON j.id = s.job_id
            JOIN companies c ON c.id = j.company_id
            WHERE s.scorer = ? AND s.score >= ?
            GROUP BY c.id ORDER BY n DESC, c.canonical_name LIMIT 15
            """,
            (SCORER, MIN_MATCH_SCORE),
        ).fetchall()
        top_companies = [{"name": r["name"], "count": r["n"]} for r in top_rows]

        # Section 5: last-run timestamps
        last_scout = cur.execute(
            "SELECT MAX(updated_at) AS t FROM ats_endpoints"
        ).fetchone()["t"]
        last_match = cur.execute(
            "SELECT MAX(scored_at) AS t FROM job_scores WHERE scorer = ?",
            (SCORER,),
        ).fetchone()["t"]
    finally:
        conn.close()

    funnel = [
        {"stage": "Active companies",
         "count": total_active, "source": "companies WHERE active=1"},
        {"stage": "With website_url",
         "count": with_url,
         "source": "companies WHERE active=1 AND website_url IS NOT NULL AND != ''"},
        {"stage": "With ≥1 working ATS endpoint",
         "count": with_active_ats,
         "source": "DISTINCT ats_endpoints.company_id WHERE status='active'"},
        {"stage": "Jobs scraped",
         "count": total_jobs, "source": "COUNT(*) FROM job_postings"},
        {"stage": "Jobs scored",
         "count": scored_jobs,
         "source": f"DISTINCT job_id FROM job_scores WHERE scorer='{SCORER}'"},
        {"stage": f"Jobs above threshold (≥{MIN_MATCH_SCORE})",
         "count": matched_jobs,
         "source": f"... AND score >= {MIN_MATCH_SCORE}"},
    ]

    return jsonify({
        "funnel": funnel,
        "gap": gap,
        "providers": providers,
        "top_companies": top_companies,
        "last_scout": last_scout,
        "last_matcher": last_match,
        "scorer": SCORER,
        "min_match_score": MIN_MATCH_SCORE,
    })

@app.route("/api/tailored_resume_content")
def tailored_resume_content():
    filename = request.args.get("file", "")
    filepath = _tailored_path(filename, {".txt"})
    if not filepath:
        return jsonify({"error": "invalid filename"}), 400
    if os.path.exists(filepath):
        return jsonify({"content": open(filepath).read()})
    return jsonify({"error": "not found"}), 404



@app.route("/api/revise", methods=["POST"])
def revise():
    import subprocess as sp, datetime as dt
    d = request.json
    filename = d.get("filename", "")
    comments = d.get("comments", "")
    filepath = _tailored_path(filename, {".txt"})
    if not filepath:
        return jsonify({"error": "invalid filename"}), 400
    if not os.path.exists(filepath):
        return jsonify({"error": "file not found"}), 404
    current_content = open(filepath).read()
    api_key = get_anthropic_key()
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
    company, role = _lookup_resume_meta(filename)
    _refresh_standardized_snapshot(filename, company, role)
    return jsonify({"ok": True, "content": revised})

@app.route("/api/generate_pdf", methods=["POST"])
def generate_pdf_route():
    import subprocess as sp, shutil
    d = request.json
    filename = d.get("filename", "")
    txt_path = _tailored_path(filename, {".txt"})
    if not txt_path:
        return jsonify({"error": "invalid filename"}), 400
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
    elif filename.endswith(".txt"):
        txt_name = filename
        pdf_name = filename.replace(".txt", ".pdf")
    else:
        return "Invalid filename", 400

    txt_path = _tailored_path(txt_name, {".txt"})
    pdf_path = _tailored_path(pdf_name, {".pdf"})
    if not txt_path or not pdf_path:
        return "Invalid filename", 400

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
    d = request.json or {}
    name = d.get("name", "").strip()
    if not name:
        return jsonify({"error": "company name required"}), 400
    website_url = d.get("website_url")
    result = storage.detect_ats(name, website_url)
    if result and result.get("provider"):
        return jsonify({
            "found": True,
            "ats": result["provider"],
            "slug": result["slug"],
            "total_jobs": result.get("total_jobs"),
            "sample_titles": result.get("sample_titles", []),
            "found_via": result.get("found_via", "slug_candidates"),
        })
    if result and result.get("dead_url"):
        return jsonify({
            "found": False,
            "dead_url": True,
            "tried_slugs": result.get("tried_slugs", []),
        })
    return jsonify({"found": False, "tried_slugs": []})


@app.route("/api/add_company/confirm", methods=["POST"])
def add_company_confirm():
    d = request.json or {}
    name     = d.get("name", "").strip()
    ats      = d.get("ats", "").strip()
    slug     = d.get("slug", "").strip()
    stage    = d.get("stage", "Unknown").strip()
    vertical = d.get("vertical", "SaaS").strip()
    open_jobs_actual = d.get("open_jobs_actual")
    if not all([name, ats, slug]):
        return jsonify({"error": "name, ats, slug required"}), 400
    conn = _db_conn()
    if not conn:
        return jsonify({"error": "SQLite DB not found; run scripts/migrate_to_db.py --reset"}), 500
    try:
        existing = storage.get_ats_endpoint(conn, ats, slug)
        if existing and existing["status"] == "active":
            return jsonify({"error": f"ATS endpoint '{ats}/{slug}' already exists"}), 409
        storage.add_dashboard_company(
            conn,
            name=name,
            provider=ats,
            slug=slug,
            stage=stage,
            vertical=vertical,
            open_jobs_actual=open_jobs_actual,
        )
    finally:
        conn.close()
    return jsonify({"ok": True, "message": f"{name} ({ats}/{slug}) added to SQLite company registry"})




@app.route("/api/companies/delete", methods=["POST"])
def delete_company():
    data = request.get_json(force=True)
    name = (data or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    conn = _db_conn()
    if not conn:
        return jsonify({"error": "SQLite DB not found; run scripts/migrate_to_db.py --reset"}), 500
    try:
        removed = storage.deactivate_company_by_name(conn, name)
    finally:
        conn.close()
    if not removed:
        return jsonify({"error": f"Company '{name}' not found"}), 404

    return jsonify({"ok": True, "removed": name})


@app.route("/api/companies")
def companies():
    conn = _db_conn()
    if conn:
        try:
            companies = storage.load_scout_companies(conn)
            summary = storage.export_company_scan_summary(conn)
        finally:
            conn.close()
    else:
        companies = []
        summary = {"scan_date": None, "stats_by_company": {}}

    stats_by_company = summary["stats_by_company"]
    scan_date = summary["scan_date"]
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
                _refresh_standardized_snapshot(
                    _canonical_tailor_filename(role_title, company_name, version),
                    company_name, role_title,
                )
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
    if os.environ.get("PP_JOBAPP_ENABLE_BASH_API") != "1":
        return jsonify({"error": "bash API disabled"}), 403
    if request.remote_addr not in ("127.0.0.1", "::1", "localhost"):
        return jsonify({"error": "bash API is local-only"}), 403
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


# ── Outreach drafts ───────────────────────────────────────────────
# Drafts a ~250-word outreach message in Pratyush's voice for an applied job,
# using Anthropic's native web_search tool to ground the company paragraph.
# Synchronous: the round-trip takes ~30-60s; the UI shows a spinner.

@app.route("/api/outreach/draft", methods=["POST"])
def outreach_draft_route():
    """Generate 2 outreach variants for a job. Optional `slants` overrides auto-selection."""
    from outreach.drafter import generate_variants, DEFAULT_MODEL, OPUS_MODEL
    from outreach.budget import BudgetExceeded
    d = request.json or {}
    try:
        job_id = int(d.get("job_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "job_id required (int)"}), 400
    if not job_id:
        return jsonify({"error": "job_id required"}), 400
    model = OPUS_MODEL if d.get("use_opus") else DEFAULT_MODEL
    slants = d.get("slants") or None
    try:
        payload = generate_variants(job_id, slants=slants, model=model)
        return jsonify(payload)
    except BudgetExceeded as e:
        return jsonify({"error": str(e), "kind": "budget_exceeded"}), 429
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/outreach/slants", methods=["GET"])
def outreach_slants_route():
    from outreach.drafter import list_slants
    return jsonify({"slants": list_slants()})


@app.route("/api/outreach/research", methods=["POST"])
def outreach_research_route():
    """Standalone research step. Splits the old draft flow's "research + compose"
    into two clicks so the user can let the per-minute rate-limit window clear
    between the (expensive) research call and the compose calls.

    Body: {job_id, peek?: bool, force_refresh?: bool, use_opus?: bool}
      - peek=true → cache-only check; no API call. Returns metadata or 404.
      - force_refresh=true → re-run research even if cached.
      - default → cache-or-run.
    """
    from outreach.drafter import (
        _fetch_job_context, peek_research, get_or_research_company,
        DEFAULT_MODEL, OPUS_MODEL,
    )
    from outreach.budget import BudgetExceeded
    d = request.json or {}
    try:
        job_id = int(d.get("job_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "job_id required (int)"}), 400
    if not job_id:
        return jsonify({"error": "job_id required"}), 400
    ctx = _fetch_job_context(job_id)
    if not ctx:
        return jsonify({"error": f"job_id {job_id} not found"}), 404
    if d.get("peek"):
        info = peek_research(ctx["company_id"])
        if not info:
            return jsonify({"cached": False, "company": ctx["company"]}), 200
        info["cached"] = True
        info["company"] = ctx["company"]
        return jsonify(info)
    model = OPUS_MODEL if d.get("use_opus") else DEFAULT_MODEL
    try:
        payload = get_or_research_company(ctx, model=model, force_refresh=bool(d.get("force_refresh")))
        return jsonify({
            "from_cache": payload.get("from_cache", False),
            "fetched_at": payload.get("fetched_at"),
            "sources_count": len(payload.get("sources", [])),
            "cost_usd": 0.0 if payload.get("from_cache") else payload.get("cost_usd", 0.0),
            "model": payload.get("model"),
            "company": ctx["company"],
        })
    except BudgetExceeded as e:
        return jsonify({"error": str(e), "kind": "budget_exceeded"}), 429
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/outreach/recompose", methods=["POST"])
def outreach_recompose_route():
    """Replace a single existing draft's content with a fresh compose using a
    new slant. Preserves draft_id + variant_group_id; the sibling variant in
    the same group is untouched. Research is loaded from cache when fresh."""
    from outreach.drafter import recompose_variant, DEFAULT_MODEL, OPUS_MODEL
    from outreach.budget import BudgetExceeded
    d = request.json or {}
    try:
        draft_id = int(d.get("draft_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "draft_id required (int)"}), 400
    slant = (d.get("slant") or "").strip()
    if not draft_id or not slant:
        return jsonify({"error": "draft_id and slant required"}), 400
    model = OPUS_MODEL if d.get("use_opus") else DEFAULT_MODEL
    try:
        payload = recompose_variant(draft_id, slant=slant, model=model)
        return jsonify(payload)
    except BudgetExceeded as e:
        return jsonify({"error": str(e), "kind": "budget_exceeded"}), 429
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/outreach/pick_winner", methods=["POST"])
def outreach_pick_winner_route():
    from outreach.drafter import pick_winner
    d = request.json or {}
    try:
        draft_id = int(d.get("draft_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "draft_id required (int)"}), 400
    if not draft_id:
        return jsonify({"error": "draft_id required"}), 400
    return jsonify(pick_winner(draft_id))


@app.route("/api/outreach/outcome", methods=["POST"])
def outreach_outcome_route():
    from outreach.drafter import set_outcome
    d = request.json or {}
    try:
        draft_id = int(d.get("draft_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "draft_id required (int)"}), 400
    if not draft_id:
        return jsonify({"error": "draft_id required"}), 400
    outcome = d.get("outcome")
    notes = d.get("notes")
    try:
        return jsonify(set_outcome(draft_id, outcome, notes))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/outreach/drafts", methods=["GET"])
def outreach_list_route():
    from outreach.drafter import list_drafts
    job_id = request.args.get("job_id", type=int)
    if not job_id:
        return jsonify({"error": "job_id required"}), 400
    return jsonify({"drafts": list_drafts(job_id)})


@app.route("/api/outreach/counts", methods=["GET"])
def outreach_counts_route():
    from outreach.drafter import draft_counts_by_job_url
    return jsonify({"counts": draft_counts_by_job_url()})


@app.route("/api/outreach/update", methods=["POST"])
def outreach_update_route():
    from outreach.drafter import update_draft
    d = request.json or {}
    try:
        draft_id = int(d.get("draft_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "draft_id required (int)"}), 400
    if not draft_id:
        return jsonify({"error": "draft_id required"}), 400
    try:
        return jsonify(update_draft(
            draft_id,
            body=d.get("body"),
            subject=d.get("subject"),
            status=d.get("status"),
        ))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/outreach/delete", methods=["POST"])
def outreach_delete_route():
    from outreach.drafter import delete_draft
    d = request.json or {}
    try:
        draft_id = int(d.get("draft_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "draft_id required (int)"}), 400
    if not draft_id:
        return jsonify({"error": "draft_id required"}), 400
    return jsonify(delete_draft(draft_id))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
