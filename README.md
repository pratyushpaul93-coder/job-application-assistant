# PP OpenClaw Job Application Pipeline
Server: pp-openclaw-jobapp | IP: 87.99.133.98 | Project: pp_openclaw_1_jobapplication
Last updated: April 7 2026

## Overall Objective
Automate end-to-end job search and application pipeline for Pratyush Paul.
Phase 1 (current): Find jobs + build tailored resumes on demand
Phase 2 (future): Auto-apply + LinkedIn outreach automation

## Target Roles
Strategy and Operations (Mgr/Sr Mgr/Dir), Chief of Staff, GTM Operations,
Sales Operations, Revenue Operations, Product Operations Mgr, TPM (AI/SaaS)

## Target Companies
High-growth SaaS Series A-D, AI-native startups, PE-backed tech, VC portfolio companies

## Target Locations
Chicago (remote OK) -- primary, Austin, San Francisco, New York

## Intended Workflow (Target State)
1. Cron triggers Scout at 7am Chicago (1pm UTC)
2. Scout searches Indeed + VC portfolio pages + Wellfound + YC + BuiltIn
3. Scout writes raw_jobs.json to /root/pp-jobapp/workspace/
4. Matcher scores each role 1-5, filters to 3+, sends WhatsApp shortlist
5. Pratyush reviews, replies: tailor [N]
6. Tailor builds .docx (Google Docs compatible) returned via WhatsApp

Future: Browser agent auto-apply, LinkedIn outreach, application tracking

## Agent Architecture

Agent 1: Job Scout
  Model: deepseek/deepseek-chat (DeepSeek V3)
  Skill: /root/pp-jobapp/workspace/skills/job-scout.md
  Output: /root/pp-jobapp/workspace/raw_jobs.json
  Trigger: cron or: openclaw agent --agent job-scout --message "Run your daily job scan now"

Agent 2: Job Matcher
  Model: deepseek/deepseek-chat (DeepSeek V3)
  Skill: /root/pp-jobapp/workspace/job-matcher/skills/job-matcher.md
  Input: raw_jobs.json | Output: shortlist.json + WhatsApp message
  Trigger: openclaw agent --agent job-matcher --message "Process raw_jobs.json and send WhatsApp shortlist"

Agent 3: Resume Tailor
  Model: anthropic/claude-sonnet-4-6 (Sonnet -- quality for resume writing)
  Skill: /root/pp-jobapp/workspace/resumes/skills/resume-tailor.md
  Output: tailored .docx + WhatsApp confirmation
  Trigger: WhatsApp reply "tailor [N]"

## Job Sources
Currently configured:
  - Indeed (3 Tavily searches per day)
  - a16z portfolio -- Day 0 of 3-day rotation
  - Bessemer portfolio -- Day 1
  - Sequoia portfolio -- Day 2

To add next session:
  - Wellfound: https://wellfound.com/jobs
  - Y Combinator: https://www.ycombinator.com/jobs
  - BuiltIn Chicago/Austin/NYC/SF
  - TopStartups.io

## API Keys (all in ~/.openclaw/openclaw.json)
Anthropic: connected | DeepSeek: connected + topped up April 6 2026
Tavily: connected (free tier) | WhatsApp: linked

## Monthly Cost
Hetzner CX21: $14.59/mo | DeepSeek: ~$1/mo | Anthropic Tailor: ~$2-3/mo
Tavily: free | Total: ~$17-19/mo

## Infrastructure
Hetzner CX21 (3 vCPU, 4GB RAM, 80GB SSD) | Ashburn VA | Ubuntu 24.04
SSH: ssh root@87.99.133.98 | OpenClaw v2026.4.5 | Node.js v24.14.1
Gateway: systemd on port 18789 (loopback only)

## Cron Job
Schedule: 0 13 * * * (1pm UTC = 7am Chicago)
Log: /root/pp-jobapp/cron.log | Verify: crontab -l

## KNOWN ISSUES -- Fix Next Session

CRITICAL 1: Scout hallucinating job listings
  Problem: Tavily returns aggregate counts not individual listings
  Scout makes up company names and scores -- output is FAKE
  Fix: Rewrite Scout to use web_fetch on specific URLs:
    Wellfound search results, VC portfolio Greenhouse/Lever boards,
    Indeed search results HTML page
  Approach: Give Scout 5-10 specific fetchable URLs per run

CRITICAL 2: Gateway pairing error (blocks WhatsApp sends)
  Error: pairing required on every CLI agent call
  Falls back to embedded mode -- runs but cannot send WhatsApp
  Fix options:
    A: Trigger agents via WhatsApp message to Pratyush number
    B: openclaw message send after agent run
    C: Find correct config key to disable loopback pairing

MEDIUM: Scout doing Matcher work
  Fix: Add to Scout skill -- Stop after writing raw_jobs.json

MEDIUM: Skill files too compressed (~34 lines)
  Fix: Edit full versions via VS Code Remote SSH

LOW: .docx output for Tailor (currently writes .md)
  Fix: Install python-docx + update Tailor skill

## Next Session Checklist

Priority 1:
[ ] Rewrite Scout -- web_fetch real listings not Tavily aggregate
[ ] Fix gateway pairing -- get WhatsApp sends working
[ ] Test full pipeline: Scout -> raw_jobs.json -> Matcher -> WhatsApp
[ ] Verify shortlist has REAL company names and apply URLs

Priority 2:
[ ] Rewrite skill files via VS Code Remote SSH (fuller versions)
[ ] Add Scout STOP instruction
[ ] Add Wellfound + BuiltIn + YC sources to Scout
[ ] .docx output for Tailor
[ ] Fix cron with gateway token

Priority 3 (future):
[ ] Browser agent for auto-applying
[ ] LinkedIn outreach drafting
[ ] Application tracking (Google Sheets)
[ ] Interview prep skill

## File Structure
/root/pp-jobapp/
  README.md
  cron.log
  workspace/
    skills/job-scout.md
    job-matcher/skills/job-matcher.md
    resumes/skills/resume-tailor.md
    raw_jobs.json        -- Scout output
    shortlist.json       -- Matcher output
    whatsapp_summary.md  -- WhatsApp draft
    resumes/             -- Tailored resume outputs

Agent dirs: ~/.openclaw/agents/[job-scout|job-matcher|resume-tailor]/skills/
Config: ~/.openclaw/openclaw.json

## VS Code Remote SSH
1. Cmd+Shift+P -> Remote-SSH: Connect to Host -> 87.99.133.98
2. Open folder: /root/pp-jobapp/workspace
3. Edit skill files directly

## GitHub Storage
Create private repo: pp-openclaw-jobapp
Store: README + skill files (NO api keys or job JSON data)
Setup:
  cd /root/pp-jobapp
  git remote add origin git@github.com:pratyushpaul93-coder/pp-openclaw-jobapp.git
  echo "*.json" >> .gitignore && echo "cron.log" >> .gitignore
  git add README.md workspace/skills/ workspace/job-matcher/skills/ workspace/resumes/skills/
  git commit -m "Initial pipeline setup April 2026"
  git push -u origin main

## PP Resume Framework (Tailor reference)
1. Authenticity first -- never fabricate
2. Keyword integration -- weave JD language naturally
3. Reframe dont reinvent
4. One page ruthlessly
5. Impact over activity
6. Mirror seniority language

Experience anchor order (startup roles):
  1. Urban Company Singapore -- LEAD (marketplace, unit economics)
  2. Strategy& Dubai (consulting, C-suite)
  3. Accenture Singapore (large-scale ops)
  4. Armor Defense Chicago (cross-functional, AI projects)

Technical differentiator (AI-native roles):
  SEC EDGAR RAG (Python, sentence-transformers, Claude Haiku, numpy)
  Spotify MCP (OAuth, SQLite, five-tier fallback)

SQL: "Foundational SQL with active development focus" (8-week plan in progress)

## Session History
April 6-7 2026 (Session 1):
  - Provisioned Hetzner CX21 VPS in Ashburn VA
  - Installed Node.js 24.14.1 + OpenClaw 2026.4.5
  - Connected WhatsApp + Tavily Search
  - Configured DeepSeek V3 for Scout + Matcher
  - Configured Sonnet 4.6 for Resume Tailor
  - Set up systemd gateway (survives reboots)
  - Set up cron job (1pm UTC daily)
  - Created 3 SKILL.md files (Scout, Matcher, Tailor)
  - Registered all 3 agents in openclaw.json
  - Confirmed skills load from workspace/skills/ path
  - Scout ran in embedded mode multiple times
  - Found: Scout hallucination bug (fix next session)
  - Found: Gateway pairing bug (fix next session)
  - Chrome extension connected for browser automation
