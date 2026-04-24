# PP OpenClaw Job Application Pipeline

**Server:** pp-openclaw-jobapp | **IP:** 87.99.133.98 | **Hetzner:** pp_openclaw_1_jobapplication (ID: 14075210)
**GitHub:** github.com/pratyushpaul93-coder/pp-openclaw-jobapp (private)
**Dashboard:** http://87.99.133.98:5000 (browser + mobile)

---

## Overall Objective

Automate the end-to-end job search pipeline for Pratyush Paul.
- Phase 1 (in progress): Scout jobs via ATS APIs, score with DeepSeek, review in dashboard, tailor resumes to PDF
- Phase 2 (next): WhatsApp delivery, auto-apply, LinkedIn outreach automation

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

---

## API Keys (in /root/.openclaw/openclaw.json and agent auth-profiles)

- Anthropic: Claude Sonnet 4 -- Resume Tailor
  Location: /root/.openclaw/agents/job-scout/auth-profiles.json (anthropic:default key)
- DeepSeek: deepseek-chat -- Matcher scoring (~$0.002/job)
  Location: openclaw.json models.providers.deepseek.apiKey
- Tavily: web search fallback for custom ATS companies
- WhatsApp: linked to personal number (gateway pairing fix pending)

---

## Known Issues / TODO

1. ~~Dashboard review panel button wiring broken~~ DONE (Session 6)
2. Floating bullet dots in AI/Technical Projects section of PDF -- WeasyPrint rendering artifact, different HTML structure from CORE EXPERIENCE bullets
3. Push all Session 4 changes to GitHub (pending confirmation)
4. WhatsApp gateway pairing broken -- sends not working yet
5. Broken ATS slugs: Cyera, Wiz, Figma, WandB (wrong platform or moved ATS)
6. Company list hardcoded in ats_scout.py -- migrate to companies.json
7. No deduplication in Scout output (same role can appear 2-4x from ATS)
8. Add applied_history.json tracker to flag already-applied companies in Scout results
9. DeepSeek credits depleted -- top up at platform.deepseek.com to restore scoring (all scores defaulting to 3/5)

---

## Session History

### Session 1 (April 6-7 2026)
- Provisioned Hetzner CX21 VPS, installed OpenClaw
- Connected WhatsApp, Tavily, DeepSeek, Anthropic APIs
- Built initial Scout + Matcher as OpenClaw skills (later replaced with pure Python)

### Session 2 (April 7 2026)
- Discovered Ashby/Greenhouse/Lever public JSON APIs (zero auth, zero hallucination)
- Rebuilt Scout as pure Python (ats_scout.py) -- 25 companies, zero LLM
- Rebuilt Matcher as Python + DeepSeek
- Built Flask dashboard with job cards, comments, quick tags, filters
- Created GitHub repo pp-openclaw-jobapp with SSH auth from VPS
- Established architecture: LLM only where reasoning needed

### Session 3 (April 8 2026)
- Added posting date capture (publishedAt/updated_at/createdAt) to Scout
- Dashboard updated: posting date badges, scan button states, tailor button, tailored badge
- Added fresh filter pill (posted <14 days)
- Built tailor.py: Claude Sonnet 4 resume tailoring against live JD
- Built generate_pdf.py: WeasyPrint PDF generation (Clean Classic template)
- PDF template: Carlito font, bold company, italic title, right-aligned dates
- 1-page enforcement: auto-adjusts line-height and font-size across 5 attempts
- Alice NY internship protection: hardcoded in master + verified post-generation
- AI/Technical Personal Projects section: conditional display based on JD
- Tailor endpoints added to dashboard API (/api/tailor, /api/tailor_status, /api/tailored_resumes)
- Tailor quality: summary mirrors JD language, bullets reordered by relevance, keywords injected

### Session 4 (April 8 2026)
- Built resume_library.txt: 12 versions with [UNIQUE] tags, outcomes, tailor instructions
- Library context injected into tailor.py prompt (15000 char limit, up from 3000)
- Master resume updates: Accenture B2B bullet expanded, FMCG bullet replaced with demand forecasting ($4M savings), OpenClaw pipeline renamed, SEC EDGAR + Spotify descriptions updated
- Education header changed to "Education and Other Experiences" everywhere: master_resume.txt, tailor.py (rule + section order enforcement), generate_pdf.py line 63, SECTIONS list
- tailor.py: version suffix support (optional 4th arg), anti-fabrication rules (Armor Defense = exactly 3 bullets), anti-compression rules (never drop metrics or method), company order and section order enforced, Civil Defense injection guaranteed
- generate_pdf.py: bullet CSS baseline set (v12: list-style-position inside, margin-left 11pt, padding-left 5pt)
- Harvey resume iterated through v1-v17; v17 is best version to date
- Dashboard: View JD button added, review panel built (Draft tab, Revise tab, Generate PDF, Download link), three new API endpoints (/api/revise, /api/generate_pdf, /api/download_pdf)
- tailorOrView() function built but not yet wired to Tailor button (TODO next session)

---

## Key Design Decisions

1. ATS JSON APIs as primary source -- zero hallucination, no auth, no Playwright
2. Pure Python for Scout -- no LLM, no API cost, runs in 30 seconds
3. External companies.json as future source of truth (not yet migrated)
4. Dashboard comments feed back into Matcher scoring over time
5. Human-in-the-loop always -- system never submits applications
6. Cost: DeepSeek for scoring, Claude only for resume tailoring
7. 1-page resume enforcement via automatic CSS adjustment in generate_pdf.py
8. Alice NY internship always present -- hardcoded protection against Claude omitting it
9. Clean Classic resume template -- ATS-safe, Carlito/Calibri font, consulting-appropriate
10. Resume library context in tailor.py -- 12 prior versions guide tone, anchor selection, and keyword patterns

---

## Prioritized TODO List (Updated April 13 2026)

### P1 — Do Next Session

1. **Add company delete button to Companies tab** — frontend ✕ button exists in dashboard_ui.html calling /api/companies/delete, backend now working. Wire up and test end-to-end.
2. **DeepSeek credits** — top up at platform.deepseek.com to restore match scoring (currently all jobs defaulting to 3/5 with 402 error)

### P2 — Next Few Sessions

3. **TAILOR_FEEDBACK.md aggregator** — accumulate revision lessons to feed back into tailor.py prompt as standing instructions
4. **Push Session 6 changes to GitHub**
5. **Broken ATS slugs** — fix Cyera, Wiz, Figma, WandB (wrong platform or slug moved)
6. **PDF floating bullet dots** — WeasyPrint rendering artifact in AI/Technical Projects section
7. **Scout deduplication** — same role appearing 2-4x in raw_jobs.json output

### P3 — Backlog

8. **Migrate company list to companies.json** — currently hardcoded in ats_scout.py
9. **applied_history.json tracker** — flag already-applied companies in Scout/dashboard
10. **WhatsApp gateway pairing** — sends still broken
11. **Improvement loops for Tailor/Matcher/Scout** — feed non-standard applications (e.g. United Airlines, non-SaaS roles) as signal to improve scoring rubric and resume anchors over time
12. **Add Wellfound / BuiltIn / YC as Scout sources**
13. **Cleanup OpenClaw-dropped files** — AGENTS.md, IDENTITY.md, SOUL.md, TOOLS.md, USER.md, HEARTBEAT.md should be gitignored or deleted

### Session 6 (April 24 2026)
- Added POST /api/companies/delete endpoint: removes company from ats_scout.py COMPANIES list (case-insensitive eval-based parsing), cleans matching jobs and company_stats from shortlist.json and raw_jobs.json
- Added POST /api/job_status and GET /api/job_status_all endpoints: persist reviewed/applied state per job to workspace/job_status.json
- Dashboard: added Mark Reviewed and Mark Applied buttons per job card, state persists across page refreshes
- Dashboard: added Reviewed and Applied dropdown filter selects (All / Yes / No) to filter bar
- Dashboard: removed quick tags (Apply now, Maybe later, SQL blocker, Too senior, Wrong vertical, Location issue) to reduce clutter — can be re-added later
- Dashboard: fixed download_pdf to always regenerate PDF from latest .txt before serving (fixes stale PDF bug where post-revision downloads returned pre-revision version)
- PDF filename format changed to: PPaul_<YYYYMMDD>_<company>_<role_condensed_3_words>.pdf
- DeepSeek API returning 402 Payment Required — all match scores defaulting to 3/5, reason field showing error. Action needed: top up DeepSeek credits at platform.deepseek.com

### Session 5 Context (April 13 2026)

- Cron ran successfully today at 13:00 UTC — raw_jobs.json (52K) and shortlist.json (51K) both fresh
- Dashboard running on PID 117134 (up since Apr 11)
- tailorOrView() appears wired at line 230 but needs verification — did not get to test review panel this session
- tailor.py currently accepts: job_url, role_title, company_name (3 args only, no version suffix passed from dashboard)
- Full tailor.py and dashboard code NOT yet pulled this session — pull before building
