# PP OpenClaw Job Application Pipeline

**Server:** pp-openclaw-jobapp | **IP:** 87.99.133.98 | **Hetzner:** pp_openclaw_1_jobapplication (ID: 14075210)
**GitHub:** github.com/pratyushpaul93-coder/pp-openclaw-jobapp (private)
**Dashboard:** http://87.99.133.98:5000 (accessible from any browser including mobile)

## Overall Objective

Automate the end-to-end job search pipeline for Pratyush Paul.
- Phase 1 (current): Find real jobs, score them, review in dashboard, tailor resumes on demand
- Phase 2 (future): Auto-apply + LinkedIn outreach automation

## Target Roles

Strategy and Operations (Mgr/Sr Mgr/Dir), Chief of Staff, GTM Operations,
Sales Operations, Revenue Operations, Product Operations, TPM (AI/SaaS)

## Target Companies

High-growth SaaS Series A-D, AI-native startups, PE-backed tech, VC portfolio companies

---

## Architecture

### Core principle: LLM only where reasoning is needed

| Component | Tool | Cost | LLM? |
|-----------|------|------|-------|
| Scout | Pure Python + ATS JSON APIs | Free | No |
| Matcher | Python + DeepSeek API | ~$0.002/job | Yes (scoring) |
| Dashboard | Flask web app | Free | No |
| Resume Tailor | Claude Sonnet via OpenClaw | ~$0.05/resume | Yes (writing) |
| WhatsApp | OpenClaw gateway | Free | No |

### Pipeline flow

ats_scout.py -> raw_jobs.json -> ats_matcher.py -> shortlist.json -> Flask dashboard -> Resume Tailor -> .docx

### Daily cron (1pm UTC = 7am Chicago)

0 13 * * * python3 /root/pp-jobapp/scripts/ats_scout.py >> /root/pp-jobapp/cron.log 2>&1 && python3 /root/pp-jobapp/scripts/ats_matcher.py >> /root/pp-jobapp/cron.log 2>&1

---

## Scout: ATS API Direct Fetcher

Scans 25 companies via public JSON APIs (no auth, no Playwright, no hallucination risk).

### ATS platforms supported

**Ashby:** GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true
**Greenhouse:** GET https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true
**Lever:** GET https://api.lever.co/v0/postings/{slug}

### ATS auto-detection

For any new company, Scout tries: Ashby -> Greenhouse -> Lever -> custom/Tavily fallback.
Uses whichever returns jobs > 0. Slug is usually company name lowercase (exceptions: Glean=gleanwork, WandB=wandb).

### Current verified company list (25 companies)

Ashby: ramp, notion, vanta, harvey, elevenlabs, cohere, langchain, pinecone, sierra, linear, zapier, n8n
Greenhouse: gleanwork, brex, airtable, vercel, intercom, anthropic, wizsecurity
Lever: figma, mistral, wandb, spotify
Custom ATS (Tavily fallback): rippling
Broken slugs (fix next session): cyera, wiz, figma, wandb

---

## Company List Management

### Single source of truth (TODO: migrate to scripts/companies.json)

Each company entry: name, ats_type, slug, stage, vertical, source, verified flag

### Three ways to add companies

1. **VC portal scanner** (weekly): Fetches a16z/Bessemer/Sequoia portfolio pages, extracts company names,
   auto-detects ATS, adds to companies.json if not already present
2. **CLI tool** (manual): python3 scripts/add_company.py "Cursor" -- auto-detects ATS, verifies slug works, adds to file
3. **Dashboard GUI** (planned): Add Company button in dashboard UI -- enter company name, system auto-detects ATS,
   verifies the slug returns jobs, adds to companies.json and immediately includes in next scan
4. **WhatsApp trigger** (planned): Message "add company Cursor" -> OpenClaw calls add_company.py

### Comment-driven scoring refinement

Each job card in the dashboard has a free-text comment field and quick tags (Apply now, Maybe later,
SQL blocker, Too senior, Wrong vertical, Location issue). These save to workspace/comments.json.
The Matcher reads comments on every run to refine scoring for future shortlists.

---

## Dashboard (Flask -- scripts/dashboard.py)

Accessible at http://87.99.133.98:5000 from any browser or mobile device.
Runs as systemd service (pp-dashboard.service) -- survives reboots.

### Features

- Stats bar: total scanned, shortlisted, selected, commented
- Filter pills: All, 5/5, 4/5, 3/5, Selected, Commented
- Search box: filter by role title or company name
- Job cards (per role):
  - Score badge (5/5=green, 4/5=blue, 3/5=gray)
  - Company, location, stage, vertical, SQL mention flag
  - DeepSeek-generated fit reason
  - Checkbox to select for application
  - Apply button (direct URL to ATS listing)
  - Tailor button (triggers Resume Tailor -- coming next session)
  - Free text comment area (saves to comments.json)
  - Quick tags: Apply now, Maybe later, SQL blocker, Too senior, Wrong vertical, Location issue
- Bulk action bar: Tailor all selected, Send to WhatsApp
- Run scan button: triggers Scout + Matcher in background

### Planned dashboard features

- Add Company button: enter company name, auto-detect ATS, verify slug, add to company list
- Deduplication indicator: flag roles appearing multiple times from same ATS
- Resume status: show which roles have drafts ready

---

## Matcher: Scoring + WhatsApp Message Generation

Reads raw_jobs.json, calls DeepSeek once per job to score 1-5 against Pratyush profile.
Writes shortlist.json (all jobs with scores) and whatsapp_message.txt (top 10 for WhatsApp).

### Scoring criteria (via DeepSeek prompt)

5 = Excellent: target role + strong company + matches background (consulting, marketplace, AI)
4 = Good: role matches, strong company, minor gaps
3 = Possible: role matches but company unclear OR SQL hard required
2 = Weak: adjacent role or poor company fit
1 = Skip

---

## File Structure

/root/pp-jobapp/
  README.md                       -- this file
  CAREER_OPS_LEARNINGS.md         -- learnings from career-ops repo + ATS API research
  scripts/
    ats_scout.py                  -- ATS API scanner (25 companies, ~30 sec, zero LLM)
    ats_matcher.py                -- DeepSeek scoring + WhatsApp message generation
    dashboard.py                  -- Flask backend (serves dashboard_ui.html)
    dashboard_ui.html             -- Dashboard frontend (job cards, comments, filters)
    add_company.py                -- CLI to add company with ATS auto-detection (TODO)
    vc_scanner.py                 -- Weekly VC portfolio scanner (TODO)
    companies.json                -- Company list source of truth (TODO: migrate from hardcoded)
  workspace/
    raw_jobs.json                 -- Scout output, gitignored
    shortlist.json                -- Matcher output, gitignored
    comments.json                 -- Human feedback per job, gitignored
    selected.json                 -- Dashboard selections, gitignored
    whatsapp_message.txt          -- Generated WhatsApp shortlist, gitignored

---

## API Keys (in /root/.openclaw/openclaw.json)

- Anthropic: Claude Sonnet 4.6 for Resume Tailor
- DeepSeek: deepseek-chat for Matcher scoring (~$0.002/job)
- Tavily: web search fallback for custom ATS companies
- WhatsApp: linked to personal number (gateway pairing fix pending)

---

## Known Issues

1. Gateway pairing broken -- WhatsApp sends not working yet
2. Broken ATS slugs: Cyera, Wiz, Figma, WandB (wrong platform or moved ATS)
3. Duplicate listings: same role appearing 2-4x from ATS (dedup needed in Scout)
4. Company list hardcoded in ats_scout.py (migrate to companies.json next session)
5. Resume Tailor not yet wired to dashboard Tailor button

---

## Next Session Priorities

1. Fix WhatsApp gateway pairing so shortlist delivers to phone
2. Wire Tailor button in dashboard to Resume Tailor agent
3. Migrate company list to companies.json external config
4. Build add_company.py CLI with ATS auto-detection
5. Build Add Company button in dashboard UI
6. Fix broken slugs: Cyera, Wiz, Figma, WandB
7. Add deduplication to Scout output
8. Push dashboard_ui.html to GitHub

---

## Session History

### Session 1 (April 6-7 2026)
- Provisioned Hetzner CX21 VPS, installed OpenClaw
- Connected WhatsApp, Tavily, DeepSeek, Anthropic APIs
- Built initial Scout + Matcher as OpenClaw skills

### Session 2 (April 7 2026)
- Discovered Ashby/Greenhouse/Lever public JSON APIs (zero auth, zero hallucination)
- Rebuilt Scout as pure Python script (ats_scout.py) -- 25 companies, 83 real jobs, ~30 seconds
- Rebuilt Matcher as Python + DeepSeek (ats_matcher.py) -- 61 shortlisted, WhatsApp message generated
- Read and documented career-ops learnings (CAREER_OPS_LEARNINGS.md)
- Built Flask dashboard with job cards, comments, quick tags, filters
- Created GitHub repo pp-openclaw-jobapp with SSH key auth from VPS
- Established architecture principle: LLM only where reasoning needed

## Key Design Decisions

1. ATS JSON APIs > Playwright > WebSearch for job discovery (speed, reliability, zero hallucination)
2. Pure Python for Scout -- no LLM, no hallucination risk, no API cost
3. External companies.json as source of truth (not hardcoded) -- enables GUI/CLI/WhatsApp updates
4. Dashboard comments feed back into Matcher scoring to improve quality over time
5. Human-in-the-loop always: system never submits applications, Pratyush always decides
6. Cost minimization: DeepSeek for scoring (~$0.002/job), Claude only for Resume Tailor
