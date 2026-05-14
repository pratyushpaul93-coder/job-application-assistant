# ONBOARDING — pp-jobapp

You're stepping into a personal job-search pipeline that scrapes ATS APIs,
LLM-scores roles against a custom rubric, and tailors a resume per
matched job. The user (Pratyush) drives it through a Flask dashboard.
Everything is one-person scope — production for one user, not multi-tenant.

This file is the fast-orientation read. After this, [`README.md`](./README.md)
goes deeper, [`BACKLOG.md`](./BACKLOG.md) shows what's next, and
[`CHANGELOG.md`](./CHANGELOG.md) shows what just happened. Live data
shapes are in [`docs/sqlite-schema.md`](./docs/sqlite-schema.md) and
[`docs/data-contracts.md`](./docs/data-contracts.md); pipeline-specific
glossary in [`docs/definitions.md`](./docs/definitions.md).

## The 60-second mental model

```
companies registry (SQLite)
        │
        ▼
  detect_ats / discover_phase   ← finds ATS + slug for each company
        │
        ▼
  ats_endpoints (one row per (provider, slug))
        │
        ▼
  Scout (ats_scout.py)          ← fetches jobs from each provider's public API
        │  · Ashby / Greenhouse / Lever / Workday
        │  · 14-day recency filter (max_job_age_days)
        │  · title + JD pattern filters
        ▼
  job_postings (canonical job rows)
        │
        ▼
  Matcher (ats_matcher.py)      ← 3 stages: prefilter → cache → DeepSeek
        │
        ▼
  job_scores (1-5 per job + reason + flags + rubric_version)
        │
        ▼
  Dashboard (Flask)             ← shortlist UI, fit ratings, comments,
        │                          job-status tracking, per-job tool triggers
        │
        ├─→ Tailor (tailor.py)        ← Claude rewrites resume.txt per job
        │        └─→ Generate PDF (generate_pdf.py)
        │
        └─→ Outreach drafter          ← 2 A/B variants per applied job,
            (scripts/outreach/)         Sonnet 4.6 + 30-day-cached web
                                        research; edit + send-outcome capture
```

The sourcing pipeline (top, through `job_scores`) is batch and
operator-triggered. The two per-job tools (Tailor, Outreach) are
human-triggered one job at a time from the dashboard — they're siblings,
not a chain, and either can run without the other.

SQLite (`workspace/jobapp.db`) is the **canonical store** for every stage.
JSON files (`raw_jobs.json`, `shortlist.json`) are backup-only — nothing
in the live pipeline reads them.

## Hard conventions (read before editing)

1. **The DB is canonical.** If you're tempted to read or write a JSON file
   in a core path, stop and use `storage.py` instead. JSON exports are
   for backup/debug only.
2. **Memories you'll see referenced** — there's a Codex agent running
   alongside Claude Code on this VPS *and* on GitHub. Files and git state
   can drift between turns; don't assume what you wrote 10 minutes ago is
   still on disk. `git status` first.
3. **Recency filter is at the scout level.** Jobs older than
   `max_job_age_days` (config; default 14) are dropped *before* scoring,
   so they never enter the matcher. Old shortlisted jobs (already in
   `job_scores`) persist in the dashboard until something archives them.
4. **`days_ago` is recomputed live** at dashboard read time
   (`storage._compute_days_ago`). Never trust whatever was frozen in
   `raw_json` at scout time — it decays daily.
5. **Cache key is `(job_id, rubric_version)`.** Bumping `RUBRIC_VERSION`
   in `ats_matcher.py` is the deliberate signal that prior scores are
   stale and need re-scoring. Don't bump casually — it can mean ~$2 of
   DeepSeek calls on the next run.
6. **DeepSeek is the only paid component** in the per-job loop. Every
   other stage is free (regex, deterministic rules, cache lookup). The
   matcher writes errors as `[DS error, kept cached]` and falls back to
   the previous score rather than overwriting. Don't change that.
7. **Workday slug shape is `tenant:dc:site`** (e.g. `sailpoint:wd1:SailPoint`).
   The dc segment isn't derivable from anything, so it's encoded into
   the slug to keep `ats_url(provider, slug)` round-trippable.
8. **Dashboard CSS is single-file and token-driven** (2026-05-12 redesign).
   The `<style>` block at the top of `dashboard_ui.html` begins with a
   `:root{}` token block (colors, type, spacing, shadows, motion). Every
   component rule consumes those tokens via `var(--...)`. Never rename
   the legacy class names (`.active`, `.on`, `.pill`, `.sort-btn`,
   `.fbtn`, `.sbtn`, `.b3/.b4/.b5`, `.detect-card`, etc.) — the JS reads
   them. Add new modifiers (`.btn--primary`, `.is-loading`, …) alongside.
   `designs/tokens.css` is the canonical token source; mockups consume it
   directly, the dashboard inlines a copy.

## Where things live

```
pp-jobapp/
├── scripts/                    ← all live code
│   ├── storage.py              ← DB access, detect_ats, _ATS_SIGNATURES, schema
│   ├── ats_scout.py            ← per-provider fetchers + dispatch loop
│   ├── ats_matcher.py          ← 3-stage scoring (prefilter → cache → DeepSeek)
│   ├── dashboard.py            ← Flask routes; reads via storage.py
│   ├── dashboard_ui.html       ← single-page UI
│   ├── tailor.py               ← Claude resume tailor
│   ├── generate_pdf.py         ← weasyprint
│   ├── outreach/               ← outreach drafter (per-job, human-triggered)
│   │   ├── drafter.py          ←   research + compose orchestration
│   │   ├── kit.yaml            ←   voice blocks, openers, CTAs, 5 slants
│   │   └── budget.py           ←   daily-spend cap ($5 default)
│   ├── url_enrichment.py       ← Tavily / Haiku URL discovery
│   ├── scout_config.json       ← title + JD patterns, settings
│   └── keys.py                 ← API keys (gitignored)
├── tools/                      ← one-off / human-run scripts
│   ├── phase2_unknown_audit.py
│   ├── backfill_workday.py
│   ├── scope_spa_provider_hints.py
│   └── render_spike.py
├── docs/
│   ├── sqlite-schema.md        ← every table + key
│   ├── data-contracts.md       ← cross-component invariants
│   ├── definitions.md          ← glossary (recency, days_ago, missed-by-discover, …)
│   ├── scraper-integration.md  ← how to add a new scraper
│   └── investigations/         ← deep-dive analyses behind backlog decisions
├── workspace/                  ← runtime data (gitignored)
│   ├── jobapp.db               ← canonical SQLite store
│   ├── raw_jobs.json           ← backup of last scout run
│   └── shortlist.json          ← backup of last matcher run
├── resumes/                    ← base resume + tailored outputs
├── designs/                    ← design-system mockups for the dashboard UI
│   ├── tokens.css              ← canonical token block (colors, type, spacing)
│   ├── 00-tokens-preview.html  ← swatches + button-state matrix
│   ├── 01..06-*.html           ← per-screen mockups (pipeline, jobs, …)
│   └── index.html              ← TOC
├── README.md                   ← full project description
├── BACKLOG.md                  ← prioritized work, read this BEFORE picking up anything
├── CHANGELOG.md                ← reverse-chron of meaningful changes
└── ONBOARDING.md               ← this file
```

## Common workflows

### Run a scout + match cycle (manual; no cron)

```bash
python3 scripts/ats_scout.py        # fetches jobs for all active endpoints
python3 scripts/ats_matcher.py      # scores via prefilter → cache → DeepSeek
```

Scout writes to `job_postings`; matcher writes to `job_scores`. Both
upsert; safe to re-run. Last full run took ~30-40 min; matcher run with
warm cache cost ~$0.18.

### Discover ATS endpoints for new / stale companies

```bash
python3 scripts/ats_scout.py --discover
```

Probes every active company without an active endpoint, plus any whose
`last_checked_at` is >30 days old. Writes to `ats_endpoints`. Idempotent.

### Add a new company manually

The dashboard has an "Add Company" form (auto-detects ATS). Or via CLI:

```bash
python3 scripts/bulk_add_companies.py path/to/list.txt
```

### Re-score everything from scratch

```bash
python3 scripts/ats_matcher.py --rescore-all
```

Bypasses the cache for one run. Bump `RUBRIC_VERSION` in `ats_matcher.py`
if you're making rule changes that should invalidate prior scores.

### Inspect pipeline state

```bash
sqlite3 workspace/jobapp.db
# .tables / .schema <name> for structure
# Quick health check examples are in tools/audit/
```

### Run an investigation

Pattern: pure Python script in `tools/`, no LLM/HTTP-paid components,
write outputs to `workspace/`, document method + findings under
`docs/investigations/YYYY-MM-DD_<topic>.md`. The Phase 2 audit
(`tools/phase2_unknown_audit.py` + matching investigation doc) is the
template.

## Current state (2026-05-09)

**Pipeline numbers** (post-2026-05-09 scout+match):
- 3,141 active companies, 1,309 with an active endpoint (42%)
- 1,278 scannable endpoints (Ashby 614, Greenhouse 497, Lever 140, Workday 27)
- ~44K open jobs available; ~814 surface after the 14-day filter
- 450 currently shortlisted (score ≥3)
- 2,033 historical scored jobs (1,985 at rubric `'2.2'`, 48 at legacy `'0'`)

**What just shipped (this week, see CHANGELOG):**
- Workday provider support end-to-end (detection + fetcher + JD parity)
- `workday_job_jds` cache table (30-day TTL)
- 14-day recency filter at the scout level (configurable)
- Live `days_ago` in dashboard (no more frozen values)
- `_http_get_text` body cap raised 300KB → 2MB (was silently dropping
  large careers pages from detection)

**What's next (BACKLOG, top of stack):**
- Tier 1 #1 — detector bug fixes (Greenhouse `embed/job_board/js`
  variant, Workable/bamboohr/teamtailor in slug-candidate probing,
  Ashby URL-encoded multi-word slugs). +422 estimated matched. Highest
  yield-per-effort.
- Tier 2 #2 — URL enrichment cost discipline (post the $13 incident on
  2026-05-04).

**Strategic note:** the 2,000-matched-jobs goal no longer closes from
in-population work alone. Best ceiling from current backlog is ~1,300-1,500
matches. Closing the gap requires bringing forward Tier 4 sourcing items
(5K expansion, Form D scraper). Detail in
`docs/investigations/2026-05-07_phase2_unknown_audit.md` (Addendum 2026-05-08).

## A few things to be careful about

- **The twin / alias issue is live** (Backlog #3). Companies with
  multiple normalized_names (e.g. `mistral` + `mistralai`) can "steal"
  each other's endpoints when `discover_phase` runs, because
  `ats_endpoints.UNIQUE(provider, slug)` flips ownership on conflict.
  Net impact on a single scan is usually nil; running discover_phase
  repeatedly can ping-pong attribution. Defer the consolidation tool
  until it actually causes pain.
- **Workday boards skew enterprise.** Match yield per board is lower
  than Ashby/Greenhouse for our specific rubric. JD parity helped
  (24% uplift), but don't expect Workday to dominate matches.
- **Anti-bot blocks (Cloudflare/Akamai) are real.** ~4 of 32 known
  Workday companies plus a long tail of others return 403 to our UA.
  No fix yet; tracked implicitly under the audit's "unreachable" bucket.
- **DeepSeek occasionally errors.** Matcher's fallback-to-cache logic
  handles this; just don't change the `if score == 0:` branch in
  `ats_matcher.py:660-664` without thinking.

## When you're done with a session

If you made non-trivial code changes:
1. Update [`CHANGELOG.md`](./CHANGELOG.md) with a dated entry.
2. If a backlog item shipped, move it to **Removed** in [`BACKLOG.md`](./BACKLOG.md)
   and renumber the remaining items contiguously (current style).
3. If a backlog item changed shape or got demoted/promoted, edit it in
   place with a dated note.
4. If you wrote an investigation, drop it in `docs/investigations/`
   with the date prefix.
5. Don't update CHANGELOG for trivial bug fixes — `git log` is enough.
   The bar is "would a future contributor benefit from knowing this in
   six months?"

## Pointers to deeper docs

- [`README.md`](./README.md) — full architecture + design rationale, why
  this is built the way it is
- [`BACKLOG.md`](./BACKLOG.md) — prioritized work with effort/yield framing
- [`CHANGELOG.md`](./CHANGELOG.md) — what shipped and why
- [`docs/sqlite-schema.md`](./docs/sqlite-schema.md) — every table, every key
- [`docs/data-contracts.md`](./docs/data-contracts.md) — cross-component
  invariants
- [`docs/definitions.md`](./docs/definitions.md) — pipeline glossary
- [`docs/scraper-integration.md`](./docs/scraper-integration.md) — how to add a
  new scraper
- [`docs/investigations/`](./docs/investigations/) — deep-dive analyses
  behind backlog decisions (e.g. why JS-rendering work was demoted)
