import json, os, sys, urllib.request, datetime

WORKSPACE = "/root/pp-jobapp/workspace"
RESUMES_DIR = "/root/pp-jobapp/resumes"
OUTPUT_DIR = "/root/pp-jobapp/resumes/tailored"

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
        "model": "claude-sonnet-4-20250514",
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

def run(job_url, role_title, company_name):
    api_key = get_api_key()
    if not api_key:
        print("ERROR: No Anthropic API key")
        return None

    master = open(os.path.join(RESUMES_DIR, "master_resume.txt")).read()
    jd = fetch_jd(job_url)
    print("JD fetched: " + str(len(jd)) + " chars")

    prompt = (
        "You are an expert resume tailor for Pratyush Paul, a Strategy and Operations professional.\n\n"
        + FRAMEWORK + "\n\n"
        "MASTER RESUME:\n" + master + "\n\n"
        "JOB: " + role_title + " at " + company_name + "\n"
        "JOB DESCRIPTION:\n" + jd + "\n\n"
        "TASK: Produce a tailored resume. Output ONLY the resume text, no preamble, no markdown.\n"
        "Rules:\n"
        "- Keep all real metrics exactly as stated\n"
        "- Reorder bullets to lead with most relevant experience for this role\n"
        "- Rewrite summary (3-4 lines) to mirror this JD language and needs\n"
        "- Integrate 3-5 keywords from JD naturally into existing bullets\n"
        "- Keep AI/Technical Projects section if company is AI-native\n"
        "- Flag SQL requirements with [SQL NOTE: required/preferred] at top\n"
        "- Plain text format, same structure as master resume\n"
        "- ONE PAGE worth of content maximum"
    )

    print("Calling Claude Sonnet...")
    tailored = call_claude(prompt, api_key)

    slug = (role_title + "_" + company_name).lower().replace(" ", "_").replace("/", "_")[:50]
    date_str = str(datetime.date.today())
    filename = date_str + "_" + slug + ".txt"
    filepath = os.path.join(OUTPUT_DIR, filename)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    open(filepath, "w").write(tailored)

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

    # Verify Alice internship is present - inject if missing
    if "Alice" not in tailored:
        alice_line = "Alice, New York | Sales Strategy and Operations Intern | Jul 2016 - Jul 2017"
        if "Singapore Civil Defense" in tailored:
            tailored = tailored.replace(
                "Singapore Civil Defense Force",
                alice_line + "\nSingapore Civil Defense Force"
            )
        elif "National University" in tailored:
            # Add after NUS line
            lines = tailored.split("\n")
            for i, line in enumerate(lines):
                if "National University" in line:
                    lines.insert(i + 1, alice_line)
                    break
            tailored = "\n".join(lines)
        open(filepath, "w").write(tailored)
        print("Alice internship injected (was missing from Claude output)")
    else:
        print("Alice internship present - OK")

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
