import json, os, threading, subprocess
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)
WORKSPACE = '/root/pp-jobapp/workspace'

@app.route('/')
def index():
    return open('/root/pp-jobapp/scripts/dashboard_ui.html').read()

@app.route('/api/data')
def data():
    def load(f, default):
        p = os.path.join(WORKSPACE, f)
        return json.load(open(p)) if os.path.exists(p) else default
    shortlist = load('shortlist.json', {})
    return jsonify({
        'jobs': shortlist.get('jobs', []),
        'scan_date': shortlist.get('shortlist_date', 'unknown'),
        'companies': 25,
        'total_scanned': shortlist.get('total_scanned', 0),
        'total_shortlisted': shortlist.get('total_shortlisted', 0),
        'comments': load('comments.json', {}),
        'selected': load('selected.json', []),
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
    return jsonify(json.load(open(p)) if os.path.exists(p) else [])

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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
