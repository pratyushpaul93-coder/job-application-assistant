# PP OpenClaw Job Application Pipeline

**Server:** pp-openclaw-jobapp | **IP:** 87.99.133.98 | **Hetzner Project:** pp_openclaw_1_jobapplication
**GitHub:** github.com/pratyushpaul93-coder/pp-openclaw-jobapp (private)

## Overall Objective
Automate end-to-end job search pipeline for Pratyush Paul.
- Phase 1 (current): Find jobs + shortlist + build tailored resumes on demand
- Phase 2 (future): Auto-apply + LinkedIn outreach automation

## Target Roles
Strategy and Operations (Mgr/Sr Mgr/Dir), Chief of Staff, GTM Operations,
Sales Operations, Revenue Operations, Product Operations, TPM (AI/SaaS)

## Target Companies
High-growth SaaS Series A-D, AI-native startups, PE-backed tech, VC portfolio companies

## Architecture

### Core principle: use LLM only where reasoning is needed
- Scout: pure Python, zero LLM, direct ATS JSON APIs (no hallucination risk)
- Matcher: Python + DeepSeek API for scoring (cheap, ~$0.002/job)
- Resume Tailor: Claude Sonnet via OpenClaw (reasoning-heavy, justified cost)
- Dashboard: Flask web app for human-in-the-loop review and selection
- WhatsApp: OpenClaw gateway for notifications and commands

### Pipeline flow
ats_scout.py -> raw_jobs.json -> ats_matcher.py -> shortlist.json -> Flask dashboard -> Resume Tailor -> .docx

### Cron (1pm UTC = 7am Chicago daily)
0 13 * * * python3 /root/pp-jobapp/scripts/ats_scout.py && python3 /root/pp-jobapp/scripts/ats_matcher.py

## Company List Design

### Single source of truth: scripts/companies.json (TODO: migrate from hardcoded list)
Each company entry contains: name, ats type, slug, stage, vertical, source, verified flag

### ATS auto-detection
For any new company, try APIs in order: Ashby -> Greenhouse -> Lever -> custom/Tavily fallback
Use whichever returns jobs > 0. Slug is usually company name lowercase but has exceptions
(e.g. Glean -> gleanwork, WandB -> wandb).

### Three ways to add companies
1. VC portal scanner (weekly script): fetches a16z/Bessemer/Sequoia portfolio pages,
   extracts company names, auto-detects ATS, adds to companies.json
2. Manual CLI: python3 scripts/add_company.py "Cursor" -- auto-detects ATS, verifies slug
3. WhatsApp trigger: message "add company Cursor" -> OpenClaw calls add_company.py

### Current verified company slugs
Ashby: ramp, notion, vanta, harvey, elevenlabs, cohere, langchain, pinecone, sierra, linear, zapier, n8n
Greenhouse: gleanwork, brex, cyera(broken), airtable, vercel, intercom, anthropic, wizsecurity(broken)
Lever: figma(broken), mistral, wandb(broken), spotify
Custom ATS (Tavily fallback): rippling

## Dashboard (Flask - TODO: build scripts/dashboard.py)
Accessible at http://87.99.133.98:5000
Features:
- Job cards with checkboxes (select which to apply for)
- Score badges (5/5, 4/5, 3/5) with color coding
- Free text comment textarea per job (feeds back into Matcher scoring)
- Quick tags: Apply now, Maybe later, SQL blocker, Too senior, Wrong vertical, Location issue
- Action buttons per job: Apply (direct URL), Tailor resume, View JD
- Bulk actions: Tailor all selected, Send to WhatsApp
- Filter pills: All, 5/5, 4/5, 3/5, Selected, Commented
- Stats bar: total scanned, shortlisted, selected, resumes drafted
- Comments saved to workspace/comments.json for Matcher to read on next run

## File Structure
/root/pp-jobapp/
  README.md
  CAREER_OPS_LEARNINGS.md
  scripts/
    ats_scout.py        -- ATS API scanner (25 companies, ~30 seconds, zero LLM)
    ats_matcher.py      -- DeepSeek scoring + WhatsApp message generation
    dashboard.py        -- Flask web dashboard (TODO)
    add_company.py      -- CLI to add new company with ATS auto-detection (TODO)
    vc_scanner.py       -- Weekly VC portfolio scraper (TODO)
    companies.json      -- Company list source of truth (TODO: migrate from hardcoded)
  workspace/
    raw_jobs.json       -- Scout output (gitignored)
    shortlist.json      -- Matcher output (gitignored)
    comments.json       -- Human feedback per job (gitignored)
    whatsapp_message.txt -- Generated WhatsApp shortlist

## API Keys (all in /root/.openclaw/openclaw.json)
- Anthropic: Claude Sonnet 4.6 for Resume Tailor
- DeepSeek: deepseek-chat for Matcher scoring (~$0.002/job)
- Tavily: web search fallback for custom ATS companies
- WhatsApp: linked to personal number (gateway pairing pending fix)

## Known Issues / Next Session
1. Gateway pairing broken -- WhatsApp sends not working (fix: openclaw pairing)
2. Broken company slugs: Cyera, Wiz, Figma, WandB (wrong ATS or moved platform)
3. Duplicate listings in Scout output (same role appearing 2-4x from ATS)
4. companies.json not yet created -- company list still hardcoded in ats_scout.py
5. Flask dashboard not yet built

## Next Session Priorities
1. Fix WhatsApp gateway pairing
2. Build Flask dashboard (scripts/dashboard.py)
3. Migrate company list to companies.json
4. Fix broken slugs (Cyera, Wiz, Figma, WandB)
5. Build add_company.py CLI with ATS auto-detection
