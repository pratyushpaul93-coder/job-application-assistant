
import json, os
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
WORKSPACE = "/root/pp-jobapp/workspace"

HTML = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PP Job Pipeline</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f5f5;color:#111}
.header{background:#fff;padding:14px 20px;border-bottom:1px solid #e5e5e5;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}
.header h1{font-size:16px;font-weight:600}
.header .meta{font-size:12px;color:#888;margin-top:2px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:14px 16px;background:#fff;border-bottom:1px solid #e5e5e5}
.stat{background:#f9f9f9;border-radius:8px;padding:10px 12px}
.stat-label{font-size:11px;color:#888;margin-bottom:2px}
.stat-num{font-size:20px;font-weight:600}
.filters{padding:10px 16px;background:#fff;border-bottom:1px solid #e5e5e5;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.pill{font-size:12px;padding:4px 10px;border-radius:20px;border:1px solid #ddd;cursor:pointer;background:#fff;color:#555}
.pill.active{background:#111;color:#fff;border-color:#111}
.search{margin-left:auto;font-size:12px;padding:5px 10px;border:1px solid #ddd;border-radius:20px;width:150px}
.jobs{padding:10px 16px;max-width:900px;margin:0 auto}
.card{background:#fff;border:1px solid #e5e5e5;border-radius:12px;padding:14px 16px;margin-bottom:10px}
.card.selected{border-color:#1a7a55;border-width:2px}
.card-top{display:flex;gap:10px;align-items:flex-start}
.cb{width:20px;height:20px;border:1.5px solid #ccc;border-radius:4px;cursor:pointer;flex-shrink:0;margin-top:1px;display:flex;align-items:center;justify-content:center}
.cb.on{background:#1a7a55;border-color:#1a7a55;color:#fff;font-size:13px;font-weight:700}
.job-info{flex:1;min-width:0}
.title{font-size:14px;font-weight:600;margin-bottom:3px}
.meta{font-size:12px;color:#777;display:flex;gap:8px;flex-wrap:wrap}
.badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:20px;font-weight:600;margin-left:6px}
.b5{background:#dcf5eb;color:#0a5c38}
.b4{background:#dbeafe;color:#1e40af}
.b3{background:#f3f4f6;color:#555}
.sql-warn{color:#b45309;font-size:11px}
.sql-ok{color:#166534;font-size:11px}
.actions{display:flex;gap:6px;flex-shrink:0;flex-wrap:wrap}
.btn{font-size:12px;padding:5px 10px;border:1px solid #ddd;border-radius:6px;cursor:pointer;background:#fff;white-space:nowrap}
.btn-green{background:#1a7a55;color:#fff;border-color:#1a7a55}
.reason{font-size:12px;color:#666;margin:8px 0 0 30px;line-height:1.5}
.comment-wrap{margin:8px 0 0 30px}
textarea{width:100%;font-size:12px;padding:7px 10px;border:1px solid #ddd;border-radius:6px;background:#fafafa;color:#111;resize:vertical;font-family:inherit}
textarea:focus{outline:none;border-color:#1a7a55}
.tags{display:flex;gap:4px;margin-top:6px;flex-wrap:wrap}
.tag{font-size:11px;padding:2px 8px;border-radius:20px;border:1px solid #ddd;cursor:pointer;color:#555}
.tag.bad{background:#fef2f2;color:#991b1b;border-color:#fca5a5}
.tag.good{background:#f0fdf4;color:#166534;border-color:#86efac}
.tag.active-tag{font-weight:600;opacity:1}
.bar{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid #e5e5e5;padding:10px 16px;display:flex;align-items:center;justify-content:space-between}
.bar-btns{display:flex;gap:8px}
@media(max-width:600px){.stats{grid-template-columns:repeat(2,1fr)}.actions{display:none}}
</style>
</head>
<body>
<div class="header">
  <div><div class="header h1">Job pipeline</div><div class="meta" id="scan-meta">Loading...</div></div>
  <div style="display:flex;gap:8px">
    <button class="btn" onclick="runScan()">Run scan</button>
    <button class="btn btn-green" onclick="sendWhatsApp()">Send to WhatsApp</button>
  </div>
</div>
<div class="stats">
  <div class="stat"><div class="stat-label">Total scanned</div><div class="stat-num" id="st-total">-</div></div>
  <div class="stat"><div class="stat-label">Shortlisted</div><div class="stat-num" id="st-short">-</div></div>
  <div class="stat"><div class="stat-label">Selected</div><div class="stat-num" id="st-sel">0</div></div>
  <div class="stat"><div class="stat-label">Commented</div><div class="stat-num" id="st-com">0</div></div>
</div>
<div class="filters">
  <span class="pill active" data-filter="all" onclick="setFilter(this)">All</span>
  <span class="pill" data-filter="5" onclick="setFilter(this)">5/5</span>
  <span class="pill" data-filter="4" onclick="setFilter(this)">4/5</span>
  <span class="pill" data-filter="3" onclick="setFilter(this)">3/5</span>
  <span class="pill" data-filter="selected" onclick="setFilter(this)">Selected</span>
  <span class="pill" data-filter="commented" onclick="setFilter(this)">Commented</span>
  <input class="search" placeholder="Search..." oninput="doSearch(this.value)" />
</div>
<div class="jobs" id="jobs-list"></div>
<div style="height:60px"></div>
<div class="bar">
  <span style="font-size:13px;color:#555"><span id="bar-sel">0</span> selected</span>
  <div class="bar-btns">
    <button class="btn" onclick="tailorAll()">Tailor all resumes</button>
    <button class="btn btn-green" onclick="sendWhatsApp()">Send to WhatsApp</button>
  </div>
</div>

<script>
let jobs=[], comments={}, selected=new Set(), currentFilter="all", searchTerm="";

async function load(){
  const r=await fetch("/api/data");
  const d=await r.json();
  jobs=d.jobs||[];
  comments=d.comments||{};
  selected=new Set(d.selected||[]);
  document.getElementById("scan-meta").textContent="Last scan: "+d.scan_date+" — "+d.companies+" companies";
  document.getElementById("st-total").textContent=d.total_scanned||"-";
  document.getElementById("st-short").textContent=d.total_shortlisted||"-";
  render();
}

function render(){
  let filtered=jobs.filter(j=>{
    if(currentFilter==="5"&&j.match_score!==5)return false;
    if(currentFilter==="4"&&j.match_score!==4)return false;
    if(currentFilter==="3"&&j.match_score!==3)return false;
    if(currentFilter==="selected"&&!selected.has(j.job_url))return false;
    if(currentFilter==="commented"&&!comments[j.job_url])return false;
    if(searchTerm&&!(j.role_title+j.company_name).toLowerCase().includes(searchTerm))return false;
    return true;
  });
  const list=document.getElementById("jobs-list");
  list.innerHTML=filtered.map((j,i)=>{
    const id="job-"+i;
    const key=j.job_url;
    const isSel=selected.has(key);
    const com=comments[key]||{text:"",tags:[]};
    const score=j.match_score;
    const bc=score===5?"b5":score===4?"b4":"b3";
    const loc=j.remote_ok?"Remote":(j.location_raw||"?");
    const sqlHtml=j.sql_required?'<span class="sql-warn">SQL: required</span>':j.sql_mentioned?'<span class="sql-warn">SQL: mentioned</span>':'<span class="sql-ok">SQL: not mentioned</span>';
    const tagList=["Apply now","Maybe later","SQL blocker","Too senior","Wrong vertical","Location issue"];
    const tagsHtml=tagList.map(t=>{
      const cls=["Apply now"].includes(t)?"tag good":["SQL blocker","Too senior","Wrong vertical","Location issue"].includes(t)?"tag bad":"tag";
      const active=(com.tags||[]).includes(t)?" active-tag":"";
      return '<span class="'+cls+active+'" onclick="toggleTag(''+key+'',''+t+'')">'+t+'</span>';
    }).join("");
    return '<div class="card'+( isSel?" selected":"")+'" id="'+id+'">'
      +'<div class="card-top">'
      +'<div class="cb'+( isSel?" on":"")+'" onclick="toggleSel(''+key+'',''+id+'')">'+( isSel?"✓":"")+'</div>'
      +'<div class="job-info"><div class="title">'+j.role_title+'<span class="badge '+bc+'">'+score+'/5</span></div>'
      +'<div class="meta"><span>'+j.company_name+'</span><span>'+loc+'</span><span>'+j.company_stage+'</span><span>'+j.industry_vertical+'</span>'+sqlHtml+'</div></div>'
      +'<div class="actions">'
      +'<a href="'+j.apply_url+'" target="_blank"><button class="btn">Apply</button></a>'
      +'<button class="btn btn-green" onclick="tailorOne(''+j.role_title+'',''+j.company_name+'')" >Tailor</button></div></div>'
      +'<div class="reason">'+( j.reason||"")+'</div>'
      +'<div class="comment-wrap">'
      +'<textarea rows="1" placeholder="Add notes..." onchange="saveComment(''+key+'',this.value)">'+( com.text||"")+'</textarea>'
      +'<div class="tags">'+tagsHtml+'</div></div></div>';
  }).join("");
  document.getElementById("st-sel").textContent=selected.size;
  document.getElementById("st-com").textContent=Object.values(comments).filter(c=>c.text||( c.tags&&c.tags.length)).length;
  document.getElementById("bar-sel").textContent=selected.size;
}

function toggleSel(key,id){
  if(selected.has(key)){selected.delete(key);}else{selected.add(key);}
  fetch("/api/select",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key,selected:selected.has(key)})});
  render();
}

function saveComment(key,text){
  if(!comments[key])comments[key]={text:"",tags:[]};
  comments[key].text=text;
  fetch("/api/comment",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key,text,tags:comments[key].tags||[]})});
  render();
}

function toggleTag(key,tag){
  if(!comments[key])comments[key]={text:"",tags:[]};
  const tags=comments[key].tags||[];
  const idx=tags.indexOf(tag);
  if(idx>=0)tags.splice(idx,1);else tags.push(tag);
  comments[key].tags=tags;
  fetch("/api/comment",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key,text:comments[key].text||"",tags})});
  render();
}

function setFilter(el){
  document.querySelectorAll(".pill").forEach(p=>p.classList.remove("active"));
  el.classList.add("active");
  currentFilter=el.dataset.filter;
  render();
}

function doSearch(v){searchTerm=v.toLowerCase();render();}

function tailorOne(title,company){alert("Tailor: "+title+" @ "+company+" (Resume Tailor coming soon)");}
function tailorAll(){alert("Tailor all "+selected.size+" selected jobs (Resume Tailor coming soon)");}
function runScan(){alert("Triggering scan... check back in 2 minutes");fetch("/api/scan",{method:"POST"});}
function sendWhatsApp(){alert("WhatsApp send coming soon (gateway pairing pending)");}

load();
</script>
</body></html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/data")
def data():
    shortlist_path = os.path.join(WORKSPACE, "shortlist.json")
    comments_path = os.path.join(WORKSPACE, "comments.json")
    selected_path = os.path.join(WORKSPACE, "selected.json")
    shortlist = json.load(open(shortlist_path)) if os.path.exists(shortlist_path) else {}
    comments = json.load(open(comments_path)) if os.path.exists(comments_path) else {}
    selected = json.load(open(selected_path)) if os.path.exists(selected_path) else []
    return jsonify({
        "jobs": shortlist.get("jobs", []),
        "scan_date": shortlist.get("shortlist_date", "unknown"),
        "companies": 25,
        "total_scanned": shortlist.get("total_scanned", 0),
        "total_shortlisted": shortlist.get("total_shortlisted", 0),
        "comments": comments,
        "selected": selected,
    })

@app.route("/api/comment", methods=["POST"])
def comment():
    d = request.json
    path = os.path.join(WORKSPACE, "comments.json")
    comments = json.load(open(path)) if os.path.exists(path) else {}
    comments[d["key"]] = {"text": d.get("text",""), "tags": d.get("tags",[]), "updated": datetime.now().isoformat()}
    json.dump(comments, open(path,"w"), indent=2)
    return jsonify({"ok": True})

@app.route("/api/select", methods=["POST"])
def select():
    d = request.json
    path = os.path.join(WORKSPACE, "selected.json")
    selected = json.load(open(path)) if os.path.exists(path) else []
    key = d["key"]
    if d.get("selected") and key not in selected:
        selected.append(key)
    elif not d.get("selected") and key in selected:
        selected.remove(key)
    json.dump(selected, open(path,"w"), indent=2)
    return jsonify({"ok": True})

@app.route("/api/scan", methods=["POST"])
def scan():
    import subprocess, threading
    def run():
        subprocess.run(["python3", "/root/pp-jobapp/scripts/ats_scout.py"])
        subprocess.run(["python3", "/root/pp-jobapp/scripts/ats_matcher.py"])
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "message": "Scan started"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
