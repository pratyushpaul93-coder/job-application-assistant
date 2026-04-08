# PP OpenClaw Job Application Pipeline

**Server:** pp-openclaw-jobapp | **IP:** 87.99.133.98 | **Hetzner:** pp_openclaw_1_jobapplication (ID: 14075210)
**GitHub:** github.com/pratyushpaul93-coder/pp-openclaw-jobapp (private)
**Dashboard:** http://87.99.133.98:5000 (browser + mobile)

---

## Overall Objective

Automate the end-to-end job search pipeline for Pratyush Paul.
- Phase 1 (complete): Scout jobs via ATS APIs, score with DeepSeek, review in dashboard, tailor resumes to PDF
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

### Verified company slugs (25 companies)

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
- Tailor button: fires tailor.py, shows "Tailoring..." status, polls until done
- Tailored badge on completed resumes (blue outline + check mark)
- Re-tailor option to regenerate
- Free text comment per job (saved to comments.json, feeds Matcher scoring)
- Quick tags: Apply now, Maybe later, SQL blocker, Too senior, Wrong vertical, Location issue
- Scan button with states: "Run scan" -> "Scanning..." -> "Scan ready" (auto-reloads data)
- Bulk actions: Tailor selected, Send to WhatsApp

### Planned features

- Add Company button with ATS auto-detection
- Download PDF button per tailored resume
- Application history tracker (dedup against prior applications)
- Resume review panel in UI (show draft, add comments, apply revisions, generate final PDF)

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
7. Education section always named "Education and Internships"
8. Alice, New York internship always included (hardcoded verification in tailor.py)
9. AI/Technical Personal Projects section included ONLY if company is AI-native OR JD mentions technical skills
10. SQL requirements flagged at top with [SQL NOTE: required/preferred]

### Alice internship protection

tailor.py includes a post-generation verification step that checks if Alice NY internship
is present in the output and injects it before Singapore Civil Defense Force if missing.
Alice is also hardcoded in master_resume.txt as the source of truth.

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
- Bullets: disc style, 11pt left margin, 3pt text padding
- Education: org bold, role italic, dates right-aligned
- Links: LinkedIn (https://www.linkedin.com/in/pratyushpaul/) and GitHub (https://github.com/pratyushpaul93-coder)

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
    tailor.py                     -- Claude Sonnet resume tailor
    generate_pdf.py               -- WeasyPrint PDF generator (Clean Classic template)
    add_company.py                -- TODO: CLI with ATS auto-detection
    vc_scanner.py                 -- TODO: weekly VC portfolio scanner
  resumes/
    master_resume.txt             -- Master resume (source of truth)
    resume_meta.json              -- Resume versions metadata
    tailored/                     -- Tailored .txt, .pdf, .html files
  workspace/
    raw_jobs.json                 -- Scout output (gitignored)
    shortlist.json                -- Matcher output (gitignored)
    comments.json                 -- Dashboard comments (gitignored)
    selected.json                 -- Dashboard selections (gitignored)
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


### Session 4 (April 8 2026)

#### Resume Library Built
- Built `/root/pp-jobapp/resumes/resume_library.txt` — structured text file with 12 resume versions
- Each version has: full verbatim bullets, summary, unique strengths callouts, [UNIQUE] tags on distinctive bullets, applied-to info, outcome, and tailor instructions
- Versions in library: BASELINE, GOOGLE, SALESFORCE, ASANA, SUNO, UBER MEMBERSHIPS, TECH STRAT AND PLANNING, WIZ GTM ANALYST, GRAINGER, HARVEY, TURO, EBAY
- Library context injected into tailor.py prompt (15000 char limit, up from 3000)
- Tailor instructions at bottom of library file guide which version to use as base for each role type

#### Master Resume Updates
- Accenture B2B bullet: added detail (competitor analysis, target store segmentation, assortment, sourcing, pricing, operations)
- Accenture FMCG bullet: replaced with new demand forecasting bullet — "Created demand forecasting model for global shipping giant to better allocate empty containers for sales across 300+ ports worldwide, improving forecasting efficiency by 1% and generating ~$4M in annual savings"
- AI/Technical Projects: renamed PP OpenClaw Pipeline to "OpenClaw Job Hunting Pipeline", updated to 100+ companies
- AI/Technical Projects: updated SEC EDGAR and Spotify descriptions to be more concise and descriptive
- Education section header: changed from "EDUCATION AND INTERNSHIPS" to "EDUCATION AND OTHER EXPERIENCES" in master + generate_pdf.py line 63

#### tailor.py Improvements
- Library truncation fixed: 3000 -> 15000 chars
- Version suffix support: now accepts optional 4th arg for versioning (e.g. 'v9', 'v10')
- Anti-fabrication rules added: Armor Defense hardcoded to exactly 3 bullets, never invent a 4th
- Anti-compression rules: never remove method/how from bullets, never drop metrics, agency partnerships bullet always included
- Section order enforced: SUMMARY -> CORE EXPERIENCE -> AI/TECHNICAL PROJECTS -> EDUCATION AND OTHER EXPERIENCES
- Company order enforced: Armor Defense, Strategy&, Urban Company, Accenture (never reorder)
- Education header rule: always output "EDUCATION AND OTHER EXPERIENCES"
- Alice + Civil Defense injection: both lines always guaranteed present in output

#### generate_pdf.py Improvements
- Education header rewrite (line 63): hardcoded display now says "Education and Other Experiences"
- SECTIONS list updated: "EDUCATION AND OTHER EXPERIENCES" added as recognized section
- Bullet CSS: list-style-position: inside with margin-left 11pt and padding-left 5pt (v12 baseline — known good)

#### Harvey Resume — Version History
- v1-v8: Earlier sessions, iterating on formatting and content
- v9: First run with library context (15000 chars), Ashby JD fetched successfully (6000 chars)
- v10: Fixed library truncation + version suffix support
- v11: Added anti-fabrication + anti-compression rules, bullet CSS fix attempt
- v12: Best formatting baseline — bullets correct, all content present except Civil Defense + AI projects section order
- v13: Civil Defense injection fixed, Education header attempted
- v14: Section order enforced (broke company order — reverted)
- v15: Rollback attempt
- v16: Education header fixed in tailor.py + SECTIONS list, AI/Technical Projects above Education
- v17: Line 63 hardcoded fix — Education and Other Experiences confirmed correct. Civil Defense present. Best version to date.

#### Dashboard UI — Review Panel Built (partially wired)
- 3 new backend endpoints added to dashboard.py:
  - POST /api/revise — takes filename + comments, calls Claude to revise .txt in place
  - POST /api/generate_pdf — runs generate_pdf.py on a .txt file, returns pdf_filename
  - GET /api/download_pdf — serves PDF file as download
- View JD button added to each job card (opens apply_url in new tab)
- Review panel HTML built — Draft tab (shows .txt content), Revise tab (comment box + Apply comments button)
- Generate PDF button + inline Download link in review panel
- tailorOrView() function built — opens panel if tailored, re-tails if panel already open
- TODO next session: fix button wiring (tailorOrView not connected to Tailor button — anchor string mismatch)
- TODO next session: test full end-to-end flow: Tailor -> Review draft -> Add comments -> Apply -> Generate PDF -> Download

#### Known Issues / Next Session TODO
1. Dashboard review panel button wiring broken — tailorOrView() built but Tailor button still calls tailorJob() directly
2. Floating bullet dots in AI/Technical Projects section of PDF — WeasyPrint rendering artifact, different HTML structure from CORE EXPERIENCE bullets
3. Push all session 4 changes to GitHub
4. Test full review panel flow end-to-end once button is wired
5. Consider adding: applied_history.json tracker to flag already-applied companies in Scout results

---

## Known Issues / TODO

1. WhatsApp gateway pairing broken -- sends not working yet
2. Broken ATS slugs: Cyera, Wiz, Figma (wrong platform or moved ATS)
3. Company list hardcoded in ats_scout.py -- migrate to companies.json
4. Resume Tailor button in dashboard not yet downloading PDF (shows status only)
5. No deduplication in Scout output (same role can appear 2-4x from ATS)
6. Resume review UI not built (planned: show draft in dashboard, add comments, revise, generate PDF)

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
