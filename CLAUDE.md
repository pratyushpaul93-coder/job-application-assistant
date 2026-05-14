# pp-jobapp — Claude Code project brief

## What this is
Automated job-application pipeline. Scrapes ATS APIs on demand, scores fit cheaply with DeepSeek, tailors a master resume with Claude Sonnet 4.6 against high-scoring roles, renders PDF, surfaces everything in a Flask dashboard for human review.

GitHub: `pratyushpaul93-coder/pp-openclaw-jobapp` (private)
Trigger: **operator-only — no cron, no scheduler.** Run scripts (or click "Run Scan" in the dashboard) when fresh data is wanted.

## Start-of-session reading order
1. [`ONBOARDING.md`](./ONBOARDING.md) — 60-second mental model + hard conventions
2. [`BACKLOG.md`](./BACKLOG.md) — what's next (read before picking anything up)
3. [`CHANGELOG.md`](./CHANGELOG.md) — what shipped recently (reverse-chron)
4. [`README.md`](./README.md) — full architecture + design rationale
5. [`docs/`](./docs/) — `sqlite-schema.md`, `data-contracts.md`, `definitions.md`, `scraper-integration.md`

## Component map
| Component | Script | Model / tool | Cost/call |
|-----------|--------|--------------|-----------|
| Scout | `scripts/ats_scout.py` | Ashby/Greenhouse/Lever/Workday JSON APIs (no LLM) | $0 |
| Matcher | `scripts/ats_matcher.py` | 4 stages: manual override → deterministic pre-filter → cache → DeepSeek V3 | ~$0.002/scored job |
| Tailor | `scripts/tailor.py` | Claude Sonnet 4.6 | ~$0.05 |
| Regenerate | `dashboard.py /api/regenerate` | Sonnet 4.6, user comments injected as USER GUIDANCE | ~$0.05 |
| Revise (inline edit) | `dashboard.py /api/revise` | Claude Haiku 4.5 | ~$0.005 |
| PDF | `scripts/generate_pdf.py` | WeasyPrint, Clean Classic template, auto-1-page | $0 |
| Outreach drafter | `scripts/outreach/drafter.py` | Sonnet 4.6 (research stage: + native `web_search_20250305`, cached 30d per company; compose stage: no search) | research ~$0.20 cache-miss / $0 cache-hit; compose ~$0.02 per variant; 2 variants/click |
| Dashboard | `scripts/dashboard.py` + `dashboard_ui.html` | Flask + vanilla JS | $0 |
| External list ingest | `scripts/ingest/<source>.py` | Convention + shared `common.py` helper | $0 |

## Architectural principles (do not violate without asking)
1. **SQLite (`workspace/jobapp.db`) is canonical.** Jobs, scores, dashboard state, resume artifacts, ATS endpoints — all live in the DB. JSON files in `workspace/` are backup-only; nothing in the live pipeline reads them. Dashboard fails loudly (HTTP 500) if DB missing.
2. **Scout is zero-LLM, zero-hallucination.** Pure Python against public ATS APIs. Never add LLM calls here.
3. **Matcher gates Tailor.** Cheap models score volume; expensive models only see survivors. Sonnet is invoked per-job by the human via the dashboard.
4. **Cost-minimize first.** Before any LLM call, ask: can this be heuristic, cached, or skipped? (See [[feedback-llm-search-cost]] memory for the $13 web-search incident.)
5. **Manual-trigger only.** No cron, no scheduler. Decision logged in BACKLOG 2026-05-06; reframe any "schedule it" suggestion as a manual cadence.
6. **`days_ago` is recomputed live** from `posted_date` at dashboard read time (`storage._compute_days_ago`). Never trust the frozen value in `raw_json`.
7. **`RUBRIC_VERSION` is the cache key.** Bumping it re-scores everything (~$2 on a typical pool). Currently `'2.2'`.
8. **14-day recency filter (`max_job_age_days`)** runs at the fetcher level, before any scoring. Saves DeepSeek spend on stale postings.

## tailor.py invariants — these must always hold
- Armor Defense section: exactly 3 bullets
- Anti-compression rules prevent metric stripping
- Section order enforced: Summary → Core Experience → AI/Technical Projects → Education and Other
- Company order in Core Experience never reordered
- Alice internship + Singapore Civil Defense Force: always present
- Resume library: 12 versions with `[UNIQUE - ...]` tags
- Library context window in prompt: 15,000 characters

## ATS provider status (as of 2026-05-13)
- **Scannable (job-fetching):** Ashby, Greenhouse, Lever, Workday
- **Detect-only:** workable, smartrecruiters, bamboohr, personio, recruitee, jazzhr, teamtailor, comeet, plus the 7 enterprise ATSes added 2026-05-13 (eightfold, avature, brassring, icims, phenom, taleo, oraclehcm). Detect-only providers count in dashboard stats but don't contribute job matches yet. The planned universal fetcher for them is SerpAPI Google Jobs — see BACKLOG Tier 1 #1e.
- **Slug shapes:** simple subdomain for most. Compound for: Workday `tenant:dc:site`, Brassring `partnerid:siteid`, Oracle HCM `tenant:region:siteNumber`. Compound slugs round-trip through `ats_url(provider, slug)` so they stay reconstructable.

## Dashboard endpoint reminders
Full list in [`README.md`](./README.md). The model-split ones to keep straight:
- `/api/tailor` — fresh tailor (Sonnet 4.6, no comments)
- `/api/regenerate` — full re-tailor with user comments as USER GUIDANCE (Sonnet 4.6)
- `/api/revise` — inline edit on the existing draft (Haiku 4.5)
- `/api/generate_pdf`, `/api/download_pdf` — PDF rendering
- `/api/outreach/draft` — multi-variant outreach (Sonnet 4.6 research stage cached 30d/company + Sonnet compose stage per slant). Returns `{variant_group_id, slants, drafts, research_cost_usd, compose_cost_usd}`. Gated by `outreach.budget` (HTTP 429 on cap-hit).
- `/api/outreach/{drafts,counts,slants,update,pick_winner,outcome,delete}` — list / counts / slant catalog / inline edit / winner pick / outcome capture / delete.
- Event delegation only — zero inline `onclick` in `dashboard_ui.html`.

## Deploy workflow (the established pattern)
For changes to any script:
1. Backup: `cp /root/pp-jobapp/scripts/<file>.py /root/pp-jobapp/scripts/<file>.py.bak.$(date +%s)`
2. Apply change
3. Verify: `grep -n "<expected new string>" /root/pp-jobapp/scripts/<file>.py`
4. If `dashboard.py` changed, restart Flask via systemd:
   `systemctl restart pp-dashboard.service && systemctl status pp-dashboard.service --no-pager | head -15`

The dashboard runs as the `pp-dashboard.service` systemd unit (`Restart=always`, auto-starts on boot). **Do not use `pkill -f dashboard.py` to restart** — systemd will respawn it within 5s and you'll race it. Use `systemctl restart`.

## Concurrent agents
Codex may also be editing files on this VPS and on GitHub. Re-read files before editing across turns; `git fetch && git status` before pushing. See [[concurrent_codex_agent]] memory.

## When updating this file
If you change architecture or invariants during a session, update this file in the same commit. Keep it ≤120 lines — push detail into `README.md` / `ONBOARDING.md` / `BACKLOG.md` instead. The TODO backlog itself lives in [`BACKLOG.md`](./BACKLOG.md) — don't duplicate it here.
