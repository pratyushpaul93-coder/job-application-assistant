# PP OpenClaw Job Application Pipeline

**Server:** pp-openclaw-jobapp | **IP:** 87.99.133.98 | **Hetzner:** pp_openclaw_1_jobapplication (ID: 14075210)
**GitHub:** github.com/pratyushpaul93-coder/pp-openclaw-jobapp (private)
**Dashboard:** http://87.99.133.98:5000 (browser + mobile)

---

## Overall Objective

Automate the portions of the job search pipeline for Pratyush Paul. Scout jobs via ATS APIs, score with DeepSeek, review in dashboard, tailor resumes to PDF

## Target Roles

Strategy and Operations (Mgr/Sr Mgr/Dir), Chief of Staff, GTM Operations,
Sales Operations, Revenue Operations, Product Operations, TPM (AI/SaaS)

## Target Companies

High-growth SaaS Series A-D, AI-native startups, PE-backed tech, VC portfolio companies

---

## Architecture

### Core principle: LLM only where reasoning is needed

| Component | Script | Tool | Cost |
|-----------|--------|------|------|
| Scout | ats_scout.py | ATS JSON APIs (no LLM) | Free |
| Matcher | ats_matcher.py | DeepSeek API | ~$0.002/job |
| Dashboard | dashboard.py + dashboard_ui.html | Flask | Free |
| Resume Tailor | tailor.py | Claude Sonnet 4 | ~$0.05/resume |
| PDF Generator | generate_pdf.py | WeasyPrint | Free |
| Notifications | OpenClaw gateway | WhatsApp (pending) | Free |

### Daily pipeline (cron 1pm UTC = 7am Chicago)

ats_scout.py -> raw_jobs.json -> ats_matcher.py -> shortlist.json -> Dashboard review -> tailor.py -> generate_pdf.py -> PDF

---

## Scout: ATS API Direct Fetcher (ats_scout.py)

Scans companies via public JSON APIs. Zero LLM, zero hallucination risk, ~30 seconds runtime.

### ATS platforms

| Platform | Endpoint | Notes |
|----------|----------|-------|
| Ashby | api.ashbyhq.com/posting-api/job-board/{slug} | Returns publishedAt date |
| Greenhouse | api.greenhouse.io/v1/boards/{slug}/jobs | Returns updated_at date |
| Lever | api.lever.co/v0/postings/{slug} | Returns createdAt timestamp |

### Posting date capture

Scout captures posted_date and days_ago for every job. Dashboard shows color-coded freshness:
- Green: posted within 14 days
- Amber: 15-30 days
- Red: 30+ days (stale, deprioritize)

### Verified company slugs (45 companies)

Ashby: ramp, notion, vanta, harvey, elevenlabs, cohere, langchain, pinecone, sierra, linear, zapier, n8n
Greenhouse: gleanwork, brex, airtable, vercel, intercom, anthropic, wizsecurity
Lever: figma, mistral, wandb, spotify
Custom ATS (Tavily fallback): rippling
Broken slugs (TODO fix): cyera, wiz, figma, wandb

---

## Company List Management

### Three ways to add companies (TODO: migrate to companies.json)

1. VC portal scanner (weekly script) -- auto-detects ATS, adds to list
2. CLI: python3 scripts/add_company.py "Company Name" -- auto-detects ATS, verifies slug
3. Dashboard GUI "Add Company" button (planned) -- type name, auto-detects ATS
4. WhatsApp: "add company X" (planned)

### ATS auto-detection order

Try Ashby -> Greenhouse -> Lever -> mark as custom/Tavily fallback
Use whichever returns jobs > 0. Common slug variations: Glean=gleanwork, WandB=wandb

---

## Matcher: Scoring Pipeline (ats_matcher.py)

Reads raw_jobs.json, calls DeepSeek once per job to score 1-5 against Pratyush profile.
Writes shortlist.json and whatsapp_message.txt.

### Scoring rubric

5 = Excellent: target role + AI-native/SaaS company + consulting or marketplace background valued
4 = Good: role matches well, strong company, minor gaps
3 = Possible: role matches but company stage unclear OR SQL hard required
2 = Weak: adjacent role or poor company fit
1 = Skip

---

## Dashboard (dashboard.py + dashboard_ui.html)

Accessible at http://87.99.133.98:5000. Runs as systemd service (pp-dashboard), survives reboots.

### Features

- Stats: total scanned, shortlisted, selected, commented
- Filter pills: All, 5/5, 4/5, 3/5, Selected, Commented, Posted <14d, Tailored
- Search by role or company name
- Job cards: score badge, company, location, stage, posting date (color-coded freshness), SQL flag
- Checkbox to select jobs for application
- Apply button (direct ATS link)
- View JD button (opens apply_url in new tab)
- Tailor button: fires tailor.py, shows "Tailoring..." status, polls until done
- Tailored badge on completed resumes (blue outline + check mark)
- Re-tailor option to regenerate
- Free text comment per job (saved to comments.json, feeds Matcher scoring)
- Mark Reviewed and Mark Applied buttons per job card, state persists across page refreshes
- Reviewed and Applied dropdown filter selects (All / Yes / No) in filter bar
- Scan button with states: "Run scan" -> "Scanning..." -> "Scan ready" (auto-reloads data)
- Bulk actions: Tailor selected, Send to WhatsApp
- Resume review panel: Draft tab (shows .txt content), Revise tab (comment box + Apply comments), Generate PDF button, inline Download link

### Dashboard API endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| /api/tailor | POST | Trigger tailor.py for a job, returns job_key |
| /api/tailor_status | GET | Poll tailor progress (status, filename) |
| /api/tailored_resumes | GET | List all tailored resume filenames |
| /api/revise | POST | Takes filename + comments, calls Claude to revise .txt in place |
| /api/generate_pdf | POST | Runs generate_pdf.py on a .txt file, returns pdf_filename (PPaul naming convention) |
| /api/download_pdf | GET | Regenerates PDF from latest .txt before serving, serves as download |
| /api/job_status | POST | Persist reviewed/applied state per job to job_status.json |
| /api/companies/delete | POST | Remove company from COMPANIES list + clean jobs from workspace JSONs |

### Planned features

- Application history tracker (dedup against prior applications)

---

## Resume Tailor (tailor.py)

Calls Claude Sonnet 4 to tailor master resume to a specific JD. Output is plain text .txt file.

### PP Resume Update Framework (governing rules)

1. Authentic reframing only -- never fabricate metrics or experiences
2. Natural keyword integration -- weave JD keywords into existing bullet points
3. ONE PAGE limit -- cut ruthlessly, never add filler
4. Lead with strongest anchor for this role type:
   - Marketplace/ops roles: Urban Company (unit economics, two-sided platform)
   - Consulting-adjacent: Strategy& Dubai (C-suite, M&A, market entry)
   - AI/product roles: Armor Defense + AI projects (SEC RAG, Spotify MCP)
   - GTM/Sales Ops: Accenture B2B marketplace (1.2M SEA launch)
5. Summary must mirror the JD language back at them
6. Keep all real metrics -- they are the proof
7. Education section always named "Education and Other Experiences"
8. Alice, New York internship always included (hardcoded verification in tailor.py)
9. AI/Technical Personal Projects section included ONLY if company is AI-native OR JD mentions technical skills
10. SQL requirements flagged at top with [SQL NOTE: required/preferred]
11. Armor Defense hardcoded to exactly 3 bullets -- never invent a 4th
12. Company order enforced: Armor Defense, Strategy&, Urban Company, Accenture (never reorder)
13. Section order enforced: SUMMARY -> CORE EXPERIENCE -> AI/TECHNICAL PROJECTS -> EDUCATION AND OTHER EXPERIENCES
14. Agency partnerships bullet always included; method/how never stripped from bullets

### Resume library context

tailor.py loads /root/pp-jobapp/resumes/resume_library.txt (up to 15000 chars) as context.
Library contains 12 versions: BASELINE, GOOGLE, SALESFORCE, ASANA, SUNO, UBER MEMBERSHIPS,
TECH STRAT AND PLANNING, WIZ GTM ANALYST, GRAINGER, HARVEY, TURO, EBAY.
Each version has verbatim bullets, [UNIQUE] tags, applied-to info, outcome, and tailor instructions.

### Alice internship protection

tailor.py includes a post-generation verification step that checks if Alice NY internship
is present in the output and injects it (along with Singapore Civil Defense Force line)
before the education section if missing. Both lines are hardcoded in master_resume.txt.

### tailor.py usage

python3 scripts/tailor.py <job_url> <role_title> <company_name> [version_suffix]

Example:
python3 scripts/tailor.py 'https://jobs.ashbyhq.com/harvey/abc123' 'GTM Strategy and Operations' 'Harvey' 'v17'

Note: Ashby and Greenhouse render as JS SPAs -- tailor.py fetches the URL directly.
If JD content is blank, paste JD text manually into a .txt file and pass as job_url with file:// prefix.

---

## PDF Generator (generate_pdf.py)

Converts tailored .txt to a formatted PDF using WeasyPrint.

### Design spec (Clean Classic template)

- Font: Carlito (metrically identical to Calibri, open source, installed via apt)
- Body: 10pt, line-height 1.28-1.30
- Margins: 0.5in top/bottom, 0.55in left/right
- Name: 18pt bold, Arial/Carlito
- Section headers: 9.5pt bold uppercase with bottom border rule
- Company name: bold
- Company location: plain text (split from company name at first comma)
- Job title: italic, not bold
- Dates: plain text, right-aligned, not bold
- Bullets: disc style, 11pt left margin, 3pt text padding, list-style-position: inside
- Education: org bold, role italic, dates right-aligned
- Links: LinkedIn (https://www.linkedin.com/in/pratyushpaul/) and GitHub (https://github.com/pratyushpaul93-coder)
- Education section header hardcoded on line 63: "Education and Other Experiences"

### 1-page enforcement

generate_pdf.py automatically tries multiple CSS configurations to fit content to 1 page:
1. line-height 1.28, font 10pt
2. line-height 1.22, font 10pt
3. line-height 1.16, font 10pt
4. line-height 1.16, font 9.5pt
5. line-height 1.12, font 9.5pt
If still >1 page after all attempts: warns user that content needs trimming.

### Dependencies

WeasyPrint 68.1 (pip3 install weasyprint)
libpango-1.0-0, libpangoft2-1.0-0, libpangocairo-1.0-0 (apt-get)
fonts-crosextra-carlito (apt-get) -- Calibri clone

---

## Resume Files

/root/pp-jobapp/resumes/
  master_resume.txt              -- Source of truth for all tailoring
  resume_library.txt             -- 12 prior resume versions with [UNIQUE] tags and tailor instructions (15000 char context window)
  resume_meta.json               -- Metadata + key anchors per resume version
  tailored/                      -- Generated tailored .txt files
    YYYY-MM-DD_role_company.txt  -- Plain text tailored resume
    YYYY-MM-DD_role_company.pdf  -- Final formatted PDF
    YYYY-MM-DD_role_company.html -- Debug HTML (intermediate step)

---

## File Structure

/root/pp-jobapp/
  README.md                       -- this file (source of truth on VPS, pushed to GitHub)
  CAREER_OPS_LEARNINGS.md         -- Learnings from career-ops repo + ATS API research
  scripts/
    ats_scout.py                  -- ATS scanner (25 companies, ~30 sec, zero LLM)
    ats_matcher.py                -- DeepSeek scoring + WhatsApp message generation
    dashboard.py                  -- Flask backend
    dashboard_ui.html             -- Dashboard frontend
    tailor.py                     -- Claude Sonnet 4 resume tailor (library context, anti-fabrication rules)
    generate_pdf.py               -- WeasyPrint PDF generator (Clean Classic template, line 63 hardcoded)
    add_company.py                -- TODO: CLI with ATS auto-detection
    vc_scanner.py                 -- TODO: weekly VC portfolio scanner
  resumes/
    master_resume.txt             -- Master resume (source of truth)
    resume_library.txt            -- Prior resume versions for tailor context (12 versions, 15000 char limit)
    resume_meta.json              -- Resume versions metadata
    tailored/                     -- Tailored .txt, .pdf, .html files
  workspace/
    raw_jobs.json                 -- Scout output (gitignored)
    shortlist.json                -- Matcher output (gitignored)
    comments.json                 -- Dashboard comments (gitignored)
    selected.json                 -- Dashboard selections (gitignored)
    job_status.json               -- Reviewed/Applied state per job (gitignored)
    whatsapp_message.txt          -- WhatsApp shortlist (gitignored)
    tailored_resumes.json         -- Tracker of all tailored resumes (gitignored)
    scan_status.json              -- Scan progress for dashboard button (gitignored)
    tailor_status.json            -- Tailor progress for dashboard button (gitignored)

