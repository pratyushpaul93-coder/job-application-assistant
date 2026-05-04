import json, os, sys, urllib.request, datetime

WORKSPACE = "/root/pp-jobapp/workspace"
RESUMES_DIR = "/root/pp-jobapp/resumes"
OUTPUT_DIR = "/root/pp-jobapp/resumes/tailored"
SCRIPTS_DIR = "/root/pp-jobapp/scripts"
DB_PATH = WORKSPACE + "/jobapp.db"

FRAMEWORK = """
PP RESUME UPDATE FRAMEWORK:
1. Authentic reframing only - never fabricate metrics or experiences
2. Natural keyword integration - weave JD keywords into existing bullet points
3. One-page limit - cut ruthlessly, never add filler
4. Lead with strongest anchor for this role type:
   - Marketplace/ops roles: Urban Company (unit economics, two-sided platform)
   - Consulting-adjacent: Strategy& Dubai (C-suite, M&A, market entry)
   - AI/product roles: Armor Defense + AI projects (SEC RAG, Spotify MCP)
   - GTM/Sales Ops: Accenture B2B marketplace (1.2M launch)
5. Summary must mirror the JD language back at them
6. Keep all real metrics - they are the proof
7. Add AI/technical projects section if role is AI-native
"""

def get_api_key():
    try:
        cfg = json.load(open("/root/.openclaw/openclaw.json"))
        return json.load(open("/root/.openclaw/agents/job-scout/auth-profiles.json")).get("profiles",{}).get("anthropic:default",{}).get("key","")
    except:
        return ""

def fetch_jd(url):
    try:
        import re
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            content = r.read().decode("utf-8", errors="ignore")
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"\s+", " ", content).strip()
        return content[:6000]
    except Exception as e:
        return "Could not fetch JD: " + str(e)

def call_claude(prompt, api_key):
    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode())
        return resp["content"][0]["text"]

def record_tailored_resume(job_url, role_title, company_name, filename, date_str):
    if os.path.exists(DB_PATH):
        try:
            sys.path.insert(0, SCRIPTS_DIR)
            import storage
            conn = storage.connect(DB_PATH)
            try:
                storage.add_resume_artifact(
                    conn,
                    job_url=job_url,
                    role_title=role_title,
                    company_name=company_name,
                    filename_txt=filename,
                    tailored_date=date_str,
                    raw_metadata={
                        "job_url": job_url,
                        "role_title": role_title,
                        "company_name": company_name,
                        "tailored_file": filename,
                        "tailored_date": date_str,
                    },
                )
            finally:
                conn.close()
            return
        except Exception as e:
            print("WARN: SQLite tailored resume recording failed: " + str(e)[:120])

    tracker_path = os.path.join(WORKSPACE, "tailored_resumes.json")
    tracker = json.load(open(tracker_path)) if os.path.exists(tracker_path) else []
    tracker.append({
        "job_url": job_url,
        "role_title": role_title,
        "company_name": company_name,
        "tailored_file": filename,
        "tailored_date": date_str
    })
    json.dump(tracker, open(tracker_path, "w"), indent=2)

def run(job_url, role_title, company_name):
    api_key = get_api_key()
    if not api_key:
        print("ERROR: No Anthropic API key")
        return None

    master = open(os.path.join(RESUMES_DIR, "master_resume.txt")).read()
    library_path = os.path.join(RESUMES_DIR, "resume_library.txt")
    library = open(library_path).read() if os.path.exists(library_path) else ""
    jd = fetch_jd(job_url)
    print("JD fetched: " + str(len(jd)) + " chars")

    prompt = (
        "You are an expert resume tailor for Pratyush Paul, a Strategy and Operations professional.\n\n"
        + FRAMEWORK + "\n\n"
        "MASTER RESUME (source of truth for all facts and metrics):\n" + master + "\n\n"
        "RESUME LIBRARY (alternative framings by role type - use these as building blocks):\n" + library[:15000] + "\n\n"
        "JOB: " + role_title + " at " + company_name + "\n"
        "JOB DESCRIPTION:\n" + jd + "\n\n"
        "TASK: Produce a tailored resume. Output ONLY the resume text, no preamble, no markdown.\n"
        "Rules:\n"
        "- Keep all real metrics exactly as stated -- AND keep the context around them (the how and the so what)\n"
        "- Keep 3-4 bullets per role minimum. Never drop below 3\n"
        "- Each bullet should be 1.5-2 full lines long when rendered. HARD CAP: 2 lines per bullet, never more. Write FULL, DETAILED bullets but stop at the 2-line ceiling\n"
        "- Bullet structure: [Action verb] + [what you did in detail] + [how/method] + [measurable result]. Include all 4 parts\n"
        "- Within a single role, no two bullets may start with the same action verb. Vary openers (Led/Drove/Built/Designed/Owned/Launched/Negotiated/Restructured/Scaled/Partnered/Delivered/Recommended, etc.)\n"
        "- Do NOT write short punchy bullets. Write complete sentences with full context, exactly like these examples:\n"
        "  GOOD: Led migration of cybersecurity technology platform used by 400+ clients, providing secure monitored cloud infra with inheritable compliance, reaching 80% adoption within 3 months while retaining 98% of clients\n"
        "  BAD: Led platform migration for 400+ clients, achieving 80% adoption\n"
        "  GOOD: Conducted market research and financial modeling to recommend acquisition targets valued at $10M+ that expanded product portfolio by 30% and entered 2 new market segments\n"
        "  BAD: Financial modeling to recommend $10M+ targets expanding portfolio by 30%\n"
        "- Prefer shortening bullets over dropping them. But never make bullets shorter than 1.5 rendered lines\n"
        "- NEVER remove the method/how from a bullet when compressing. The HOW is a differentiator. Only cut adjectives and filler words\n"
        "- NEVER drop or thin out metrics. If a bullet has a percent or dollar figure, it must survive intact\n"
        "- NEVER add bullets not grounded in the master resume. If no real metric exists for a bullet, drop it rather than writing a vague one\n"
        "- Armor Defense has EXACTLY 3 bullets in the master resume. Never write a 4th Armor Defense bullet under any circumstances. 3 bullets only.\n"
        "- The agency partnerships bullet from Urban Company (10% cost reduction, 15% quality improvement) must always be included\n"
        "- Preserve specific product/context details (e.g. what the platform does, what market it served) -- these are differentiators\n"
        "- Do not drop entire bullets to save space. Instead: tighten wording, cut adjectives, combine where natural\n"
        "- Target density: 3-4 tight bullets per role, each with an action verb + what + measurable result\n"
        "- Reorder bullets to lead with most relevant experience for this role\n"
        "- Rewrite summary (3-4 lines) to mirror this JD language and needs\n"
        "- Integrate 3-5 keywords from JD naturally into existing bullets\n"
        "- Keep AI/Technical Projects section if company is AI-native\n"
        "- Flag SQL requirements with [SQL NOTE: required/preferred] at top\n"
        "- Education section must be titled exactly: EDUCATION AND OTHER EXPERIENCES\n"
        "- Section order must always be: 1) SUMMARY 2) CORE EXPERIENCE (chronological, most recent first) 3) AI/TECHNICAL PROJECTS 4) EDUCATION AND OTHER EXPERIENCES\n"
        "- NEVER reorder the companies within CORE EXPERIENCE. Always: Armor Defense first, then Strategy&, then Urban Company, then Accenture\n"
        "- Plain text format, same structure as master resume\n"
        "- Contact line (line 2) MUST include phone, email, LinkedIn URL, and GitHub URL exactly as in master resume. NEVER drop the GitHub link.\n"
        "- ONE PAGE total — STRICT. If content overflows, tighten bullets (cut adjectives/filler) before adding anything. Never exceed one page."
    )

    print("Calling Claude Sonnet...")
    tailored = call_claude(prompt, api_key)

    slug = (role_title + "_" + company_name).lower().replace(" ", "_").replace("/", "_")[:50]
    date_str = str(datetime.date.today())
    import sys as _sys
    version = ""
    if len(_sys.argv) > 4:
        version = "_" + _sys.argv[4]
    filename = date_str + "_" + slug + version + ".txt"
    filepath = os.path.join(OUTPUT_DIR, filename)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    open(filepath, "w").write(tailored)

    record_tailored_resume(job_url, role_title, company_name, filename, date_str)

    # Verify contact line has both LinkedIn and GitHub - inject if missing
    contact_line = "(312) 678-3629 | pratyushpaul93@gmail.com | linkedin.com/in/pratyushpaul | github.com/pratyushpaul93-coder"
    has_li = "linkedin.com/in/pratyushpaul" in tailored.lower()
    has_gh = "github.com/pratyushpaul93-coder" in tailored.lower()
    if not (has_li and has_gh):
        lines = tailored.split("\n")
        for i, line in enumerate(lines):
            if "pratyushpaul93@gmail.com" in line or "678-3629" in line:
                lines[i] = contact_line
                break
        tailored = "\n".join(lines)
        open(filepath, "w").write(tailored)
        print(f"Contact line repaired (had_linkedin={has_li}, had_github={has_gh})")

    # Verify Alice internship is present - inject if missing
    alice_line = "Alice, New York | Sales Strategy and Operations Intern | Jul 2016 - Jul 2017"
    civdef_line = "Singapore Civil Defense Force | Lieutenant (Rota Commander) | Mar 2012 - Mar 2014"

    if "Alice" not in tailored:
        if "Singapore Civil Defense" in tailored:
            tailored = tailored.replace("Singapore Civil Defense Force", alice_line + "\n" + civdef_line)
        elif "National University" in tailored:
            lines = tailored.split("\n")
            for i, line in enumerate(lines):
                if "National University" in line:
                    lines.insert(i + 1, civdef_line)
                    lines.insert(i + 1, alice_line)
                    break
            tailored = "\n".join(lines)
        open(filepath, "w").write(tailored)
        print("Alice + Civil Defense injected")
    elif "Singapore Civil Defense" not in tailored:
        tailored = tailored.replace(alice_line, alice_line + "\n" + civdef_line)
        open(filepath, "w").write(tailored)
        print("Civil Defense injected (was missing)")
    else:
        print("Alice + Civil Defense both present - OK")

    print("Saved: " + filepath)
    print("\n" + "="*60)
    print(tailored[:2000])
    print("="*60)
    return filepath

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python3 tailor.py <job_url> <role_title> <company_name>")
        sys.exit(1)
    run(sys.argv[1], sys.argv[2], sys.argv[3])
