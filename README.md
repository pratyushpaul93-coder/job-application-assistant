# Job Application Assistant

An automated, end-to-end job application pipeline for senior strategy and operations roles. Built to streamline the most time-consuming parts of a job search — finding target companies and roles, and accurately customizing a resume against each one — while keeping a human in the loop on every submission.

Built by [Pratyush Paul](https://github.com/pratyushpaul93-coder) during an active job search for S&O / GTM Ops / Chief of Staff roles at AI-native and SaaS startups.

> **A note on customization.** This pipeline was built around a specific profile, target-role set, and resume framework. The architecture and ATS / VC-board sourcing logic generalize cleanly, but the resume tailoring layer, scoring rubric, and target-company list are personal. Anyone forking this should expect to swap out the master resume, scoring criteria, and seed company list before it's useful for them.

---

## Architecture

The system has two halves. A **sourcing pipeline** that finds and ranks jobs,
and a set of **per-job tools** in a Flask dashboard that act on the survivors.

**Sourcing pipeline:** `discover` → `scan` → `score` → `shortlist`

- **Discover**: Find ATS endpoints for companies in DB.
  `storage.detect_ats(name, website_url)` is the canonical detection
  function (pure, importable). `ats_scout.discover_phase(conn)`
  orchestrates discovery across the DB. `tools/backfill_ats_detection.py`
  is the one-time backfill runner.
- **Scan**: Pull jobs from known endpoints.
  `python3 scripts/ats_scout.py` iterates `ats_endpoints` and fetches
  roles via Ashby/Greenhouse/Lever public APIs.
- **Score**: DeepSeek-rate jobs against the candidate profile.
  `python3 scripts/ats_matcher.py` reads `job_postings`, writes `job_scores`.
- **Shortlist**: Jobs that pass the score threshold are written to
  `workspace/shortlist.json` for review.

**Per-job tools** (Flask dashboard, human-triggered per job — see the
[Dashboard](#dashboard) section for details):

- **Tailor**: Customize the master resume against a specific JD
  (`scripts/tailor.py`, Sonnet 4.6), render to one-page PDF.
- **Outreach drafter**: Generate post-application outreach messages in the
  candidate's voice (`scripts/outreach/`, Sonnet 4.6 + cached web research).
  Produces 2 A/B-testable variants per job from 5 named "slants"; captures
  edits and send outcomes to improve future drafts. See CHANGELOG 2026-05-13/14.
- **Job-status tracking**: Reviewed / Applied / Reached-out / No-outreach
  state per job, plus 1-5 fit scoring.

All components read and write `workspace/jobapp.db` (SQLite) as the canonical
store — they're loosely coupled at the data layer, so any one can run without
the others.

**Day-to-day:** `python3 scripts/ats_scout.py && python3 scripts/ats_matcher.py`
(or click "Run Scan" in the dashboard). For new ingest sources or
backfilling, run `python3 scripts/ats_scout.py --discover` first. Tailor and
Outreach are triggered per-job from the dashboard.

See [BACKLOG.md](./BACKLOG.md) for active engineering work and a dated
operational log of major changes; `git log` is the canonical change history.

---

## The problem

Generic job boards and mass-apply tools optimize for volume. For senior strategy and operations roles — where the right job is one of maybe thirty a week, and the wrong job costs forty-five minutes of resume tailoring — the bottleneck isn't applying faster. It's filtering harder and tailoring better.

This pipeline is built around three constraints:

1. **No hallucination on job listings.** Every role comes from a real ATS.
2. **LLMs only where reasoning is needed.** Scoring and resume tailoring, nothing else.
3. **Human-in-the-loop always.** The system never auto-submits applications.

---

## What it does

The pipeline gives users two complementary ways to find target roles:

**Sourcing breadth — VC portfolio scraping.** A scraper pulls portfolio companies from major VC job boards (Accel, General Catalyst, Lightspeed, Sequoia, Kleiner Perkins, Greylock — all powered by Getro). At time of publishing, this surfaced roughly 2,000 portfolio companies across the six VCs covered. These can be filtered into a working target list and fed into Scout.

**Sourcing precision — manual company adds.** Users can add specific target companies one at a time through the dashboard or via CLI, with automatic ATS detection (Ashby, Greenhouse, Lever, Workday).

The pipeline is operator-triggered (no cron); each stage is an idempotent
script the user runs when they want a fresh pull:

1. **Scout** scans every target company by hitting their public ATS JSON endpoints — no scraping, no Playwright, no auth — and applies title and JD pattern filters from a config file. Results are written directly to SQLite.
2. **Matcher** scores every fresh role 1–5 in a four-stage pipeline (manual override → deterministic pre-filter → cache hit → DeepSeek V3 for the survivors), with an incremental cache so cost stays flat as the pool grows.
3. **Dashboard** reads the shortlist from SQLite with filters, posting-date freshness, comments, and a per-job tailor button.
4. **Tailor** rewrites the master resume against the live JD using Claude Sonnet 4.6 (~$0.05 per resume), governed by a strict framework that prevents fabrication and enforces structural rules.
5. **PDF generator** produces a 1-page PDF using a custom Clean Classic template that auto-tightens spacing to fit one page.
6. The user reviews, downloads, and submits manually.

Total cost to operate end-to-end is roughly **$2–3/month** in API spend plus VPS hosting.

---

## Architecture details

### Core principle: LLM only where reasoning is needed

| Component | Script | Tool | Why |
|-----------|--------|------|-----|
| Scout | `ats_scout.py` | ATS JSON APIs (no LLM) | Zero hallucination, zero auth, ~30 sec runtime |
| Matcher | `ats_matcher.py` | DeepSeek V3 (`deepseek-chat`) | Cheap reasoning ($0.002/job) for relevance scoring |
| Dashboard | `dashboard.py` + `dashboard_ui.html` | Flask + vanilla JS | Local review UI, no deployment overhead |
| Resume Tailor | `tailor.py` | Claude Sonnet 4.6 (`claude-sonnet-4-6`) | Quality matters — used sparingly, only on selected roles |
| Resume Regenerate | `dashboard.py` `/api/regenerate` | Claude Sonnet 4.6 (`claude-sonnet-4-6`) | Full re-tailor from master + JD + user comments. Use when initial tailoring missed the right framing |
| Resume Revise | `dashboard.py` `/api/revise` | Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) | Fast follow-up edits to an already-tailored resume — Haiku is sufficient for narrow revision instructions |
| PDF Generator | `generate_pdf.py` | WeasyPrint | Open-source, deterministic, no template lock-in |
| External list ingest | `scripts/ingest/<source>.py` | Convention + shared helper | Fortune 1000 (Kaggle), Built In BPTW (web scrape), Tavily URL recovery — added 2026-05-11/12 |
| VC Sourcing | `getro_scraper.py` | Getro internal APIs | ~2,000 companies across 6 top-tier VCs |
| Bulk Onboarding | `bulk_add_companies.py`, `ats_scout_getro_bulk_add.py` | ATS auto-detection | Batch-imports VC scrape results into Scout |

### Pipeline (operator-triggered)

```
ats_scout.py    →  job_postings + scan_runs       (+ raw_jobs.json backup)
                      ↓
ats_matcher.py  →  job_scores [scorer=current_shortlist, +rubric_version]
                                                   (+ shortlist.json backup)
                      ↓
                Dashboard reads SQLite
                      ↓
                [click Tailor on a job]
                      ↓
tailor.py       →  resume_artifacts + tailored .txt
                      ↓
generate_pdf.py →  tailored .pdf
```

**SQLite is canonical for everything.** JSON files in `workspace/` are
backup-only artifacts — the dashboard, matcher, and scout all read and
write the DB directly. Missing-DB behavior fails loudly (HTTP 500 from the
dashboard, with a pointer to `migrate_to_db.py`) rather than silently
falling back to stale JSON.

---

## VC Portfolio Scraper

The Scout target list can be expanded dramatically by pulling portfolio companies from VC job boards. Most top-tier VCs use [Getro](https://getro.com) for their boards, so a single scraper unlocks many VCs at once.

At time of publishing, the production scraper (`getro_scraper.py`) covered six VCs and pulled roughly 2,000 companies:

| VC | Companies |
|---|---:|
| Accel | 568 |
| General Catalyst | 504 |
| Lightspeed | 488 |
| Sequoia | 250 |
| Kleiner Perkins | 109 |
| Greylock | 71 |
| **Total** | **~1,990** |

VC portfolio scraping is one approach to sourcing breadth, not the only one. Operator networks, accelerator job boards (YC Work at a Startup), and curated communities (Pavilion, Revenue Collective) cover meaningful overlap and gap. Users serious about sourcing should layer multiple approaches.

---

## Scout: Direct ATS API Fetcher

Most job-search bots use Playwright or scrape rendered HTML. Both are brittle and prone to silent breakage. The actual ATS platforms (Ashby, Greenhouse, Lever, Workday) all expose **public JSON endpoints** that require no auth — they were built to power third-party job boards. Scout uses them directly:

| Platform | Endpoint | Date field |
|----------|----------|------------|
| Ashby | `api.ashbyhq.com/posting-api/job-board/{slug}` | `publishedAt` |
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{slug}/jobs` | `updated_at` |
| Lever | `api.lever.co/v0/postings/{slug}` | `createdAt` |
| Workday | `{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` (POST) | `postedOn` (relative string, parsed heuristically) |

Workday is structurally different from the other three — POST-based, paginated 20 per page, listing returns title-only with no JD. Scout therefore runs a two-stage flow for Workday: listing fetch → drop title-negative rejections → parallel JD fetch via the per-job cxs endpoint, with a 30-day DB-backed cache (`workday_job_jds` table). This brings Workday matching to behavioral parity with the others (`jd_fallback` fires).

Every job is captured with its real posting date, so the dashboard can color-code freshness (green <14 days, amber 15–30, red 30+) and de-prioritize stale listings. Scout itself applies a configurable **recency filter** (`max_job_age_days` in `scout_config.json`, default 14) at the fetcher level — jobs older than the cutoff are dropped before scoring, capping DeepSeek spend on stale postings. Workday rows carry an approximate `posted_date` derived from the relative `postedOn` string (`today - days_ago`).

Scout reads its company registry from SQLite (`companies` joined to `ats_endpoints`) and writes matches directly to `job_postings` as it scans, with one `scan_runs` row recorded at the end. `workspace/raw_jobs.json` is also written on every run as a backup-only artifact — nothing in the live pipeline reads it. A hardcoded `COMPANIES` list in `ats_scout.py` remains as a fallback for when the DB is unreachable (slated for removal — see [BACKLOG.md item 13](./BACKLOG.md)).

Title and JD pattern filters live in `scripts/scout_config.json` and run before any DB write, so the Matcher's scoring volume stays manageable and filters can be tuned without touching code.

---

## Matcher: four-stage scoring pipeline

The Matcher is a single script (`ats_matcher.py`) that runs four stages per job, in order. The first three are free; only Stage 3 hits an LLM.

**Stage 0 — Manual override.** If the user has rated this job through the dashboard's fit-score UI, that rating wins. Score and reason are written to SQLite under `scorer='current_shortlist'` with reason prefixed `[Manual]`. Stages 1–3 are skipped.

**Stage 1 — Deterministic pre-filter.** Encodes the v2.2 rubric as Python rules: US-only location filter, multi-year deep single-dimension tech requirements (e.g. "8+ years in solutions architecture" or "5+ years in core finance / FP&A"), too-senior / too-junior titles, and conditional family rules (TPM in ML/AI Platform → skip, Strategic Finance FP&A-led → skip, etc.). Failures are scored 1 with a clear reason. Free, instant, runs on every job.

**Stage 2 — Cache check.** If the existing `job_scores` row's `rubric_version` matches the matcher's current `RUBRIC_VERSION`, keep it. No DeepSeek call. Bumping `RUBRIC_VERSION` in `ats_matcher.py` is the deliberate signal that prior scores are stale and need re-scoring; `--rescore-all` is the override.

**Stage 3 — DeepSeek scoring.** Only runs on jobs that survived Stage 1 and lack a fresh cached score. Uses few-shot examples drawn from the user's manual ratings (`job_interactions.manual_score`) so the LLM's calibration tracks the user's actual judgment. Score / reason / flags get written to `job_scores`, stamped with the current `rubric_version`.

The rubric:

- **5** — Target role + strong company fit + background-aligned signal
- **4** — Role matches well, strong company, minor gaps
- **3** — Role matches but company stage unclear, or hard requirements only partially met
- **2** — Adjacent role or weak company fit
- **1** — Skip

`workspace/shortlist.json` is also written on every run as a backup/debug artifact. Its content is queried fresh from `job_scores`, so a partial / interrupted run cannot truncate the file.

DeepSeek was chosen over GPT-4 / Claude for Stage 3 because the reasoning is light (rubric application) and the volume after pre-filter is small (typically 50–200 jobs that survive the deterministic stage). Cost matters more than ceiling — and the deterministic pre-filter does most of the rejection work for free.

### Cost shape

The first run after a `RUBRIC_VERSION` bump scores everything fresh — typically a few hundred DeepSeek calls (~$0.50–$2.00 depending on pool size). Every run after that hits the cache for unchanged jobs and only scores newly-scouted listings, usually a few cents.

---

## Dashboard

A Flask app that runs as a `systemd` service and survives reboots. Accessible from browser and mobile.

The dashboard is fully SQLite-native: jobs come from `job_postings`,
shortlist scores from `job_scores`, and comments / selected / reviewed /
applied / manual fit scores / tailored resume mappings are stored against
stable DB job IDs. URL aliases (`job_url_aliases`) resolve historical
`job_url` / `apply_url` variants to the same posting. When the DB is
missing, every endpoint returns `HTTP 500` with a clear pointer to
`migrate_to_db.py`, so stale-data bugs surface loudly.

`days_ago` is **recomputed live** from `posted_date` on every `/api/data`
request (`storage._compute_days_ago`), not read from the value frozen
into `raw_json` at scout time. So freshness stats and the `Posted <14d`
filter stay accurate even between scout runs.

**Visual system (2026-05-12 redesign).** Linear/Vercel-leaning SaaS aesthetic.
Token-driven CSS: a single `:root{}` block at the top of `dashboard_ui.html`
defines colors (single indigo accent `#5b5bd6`, neutrals + semantic), type
(Inter via `rsms.me/inter` with system fallback, 11-28px ramp), spacing
(4px grid), three-tier shadow, focus ring, and motion. Every component
consumes those tokens via `var(--...)`. Mockups for the design language live
in `/root/pp-jobapp/designs/` and are browseable on the running dashboard at
`/designs/` (a read-only Flask route).

**Features:**

- Stats bar — total scanned, shortlisted, reviewed, applied
- Filter pills + multi-select dropdowns — score (5/4/3), VC, Reviewed, Applied
- Search — by role or company
- Job cards — score badge, company, VC tag, location, stage, posting date with
  freshness color, SQL flag. Job title is itself a hyperlink to the JD (Apply
  + View JD buttons removed; title-link consolidates them).
- **Jobs tab — two-section split** (added 2026-05-12):
  - **To apply** (LEFT) — untouched jobs. Per-section filter pills:
    All / Untailored / Tailored. Sorted by score desc.
  - **To reach out** (RIGHT) — reviewed or applied jobs. Per-section pills:
    `Applied │ Reached out · No outreach · Reviewed` — a divider + "end
    state" label separate the active queue from the three terminal states.
    Sorted by most-recently-touched via `job_interactions.updated_at`. The
    header count always reflects the Applied bucket.
  Reviewed and Applied are mutually exclusive end states; the UI hides the
  inactive Mark X once one is set.
- Stats bar — Total scanned · Shortlisted · Reviewed · Applied · Reached out
- Per-job actions — Tailor (fires `tailor.py`, polls until done), Comment,
  Mark Reviewed, **Mark reached out** + **Mark no outreach** (mutually
  exclusive sub-states of applied), 1-5 fit score, **Draft outreach**
- Outreach drafter — `Draft outreach` button on reviewed/applied cards
  opens a modal that generates 2 named-slant variants (e.g. Builder + Tight)
  for A/B testing. The flow is two explicit clicks — **Research company**
  (Sonnet 4.6 + web_search, cached per-company 30 days, paid once) then
  **Generate variants** (composes serially from cached research) — split so
  the input-heavy research call doesn't collide with the per-minute rate
  limit. Inline-edit both, recompose a single variant under a different
  slant, pick a winner, mark sent, tag outcome (response / no_response).
  See `outreach/` and CHANGELOG 2026-05-13/14.
- Bulk actions — Tailor selected
- Resume review panel — Draft tab (current `.txt`), Revision comments
  textarea, **Apply comments ↻** (Haiku 4.5 inline edit) +
  **Regenerate** (Sonnet 4.6 full re-tailor with comments injected as
  USER GUIDANCE), Generate PDF, inline Download. Download regenerates from
  the canonical .txt via `_refresh_standardized_snapshot()` on every
  tailor/revise so the file you download is never stale.
- Pipeline tab — KPI tiles + bespoke SVG-style funnel chart (6 stages,
  company-scale vs job-scale, color-coded drop deltas) + 2-col supporting
  tables (gap + provider on left, top-15 companies with sparkbars on right)
- Add Company — type a company name, the system auto-detects ATS and adds
  it to Scout's target list

**API endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/tailor` | POST | Trigger `tailor.py` for a job (Sonnet 4.6, no comments) |
| `/api/regenerate` | POST | Re-run `tailor.py` with user comments injected (Sonnet 4.6) |
| `/api/tailor_status` | GET | Poll tailor / regenerate progress |
| `/api/tailored_resumes` | GET | List all tailored resume filenames |
| `/api/revise` | POST | Apply free-text comments as inline edit (Haiku 4.5) |
| `/api/generate_pdf` | POST | Generate PDF from `.txt` |
| `/api/download_pdf` | GET | Regenerate and serve PDF |
| `/api/job_status` | POST | Persist job status (`field ∈ {reviewed, applied, reached_out, no_outreach}`) |
| `/api/add_company/detect` | POST | Detect a company's ATS and slug |
| `/api/add_company/confirm` | POST | Add a detected company to Scout |
| `/api/companies/delete` | POST | Remove a company and clean workspace |
| `/api/outreach/research` | POST | Research a company (or `peek` the cache). Step 1 of the split outreach flow |
| `/api/outreach/draft` | POST | Compose 2 outreach variants from cached research (serial compose). Returns `{variant_group_id, slants, drafts, research_cost_usd, compose_cost_usd}`. HTTP 429 if daily cap exceeded |
| `/api/outreach/recompose` | POST | Recompose a single existing draft under a new slant, in place (sibling variant untouched) |
| `/api/outreach/drafts` | GET | List all drafts (across variant groups) for a `job_id` |
| `/api/outreach/counts` | GET | Per-job-url attempt counts (powers the card button badge) |
| `/api/outreach/slants` | GET | Catalog of available slants (Operator/Builder/Analyst/Tight/Warm) |
| `/api/outreach/update` | POST | Inline-save edits to a draft's body/subject, or change status to `sent` |
| `/api/outreach/pick_winner` | POST | Mark a draft as the chosen variant in its group |
| `/api/outreach/outcome` | POST | Tag a sent draft with `response` or `no_response` |
| `/api/outreach/delete` | POST | Delete a single variant |
| `/designs/<path>` | GET | Serve mockup HTML/CSS from `designs/` (read-only) |

There is also a local debugging endpoint at `/api/bash`, but it is disabled by default.
It only responds when `PP_JOBAPP_ENABLE_BASH_API=1` is set and the request comes from localhost.

---

## Resume Tailor

The hardest component of the pipeline. The naive version — "give an LLM a JD and a resume, ask for a tailored version" — fabricates metrics, drops bullets, reorders sections randomly, and tends to overflow to 1.3 pages. The current implementation is a heavily-constrained Sonnet 4.6 prompt governed by an explicit framework.

### The PP Resume Update Framework

This is personal to the author's resume and history, but the structure generalizes — anyone forking this should write their own equivalent.

1. **Authentic reframing only.** Never fabricate metrics or experiences.
2. **Natural keyword integration.** Weave JD keywords into existing bullets.
3. **One page, hard limit.** Cut ruthlessly, never add filler.
4. **Lead with the strongest anchor for the role type.** The framework defines mappings from role archetypes to which prior role to lead with.
5. **Summary mirrors the JD's language back at it.**
6. **All real metrics preserved** — they're the proof.
7. **Section order enforced** — Summary → Core Experience → AI/Technical Projects → Education and Other Experiences.
8. **Company order enforced** — never reorder roles in Core Experience.
9. **Per-company bullet counts capped** to prevent the LLM from inventing content (e.g., a role with three real bullets stays at three, never expanded to four).
10. **Method/how never stripped from bullets** — anti-compression rule.
11. **Conditional sections** — AI/Technical Projects section only included for AI-native companies or JDs that mention technical skills.
12. **Hardcoded protections** — load-bearing line items (e.g., a key internship, a credential) verified post-generation and re-injected if the LLM dropped them.
13. **ASCII-only punctuation** — em-dash (`—`) / en-dash (`–`) replaced with hyphen (`-`) throughout the output. Enforced as a prompt rule on `tailor.py` (added 2026-05-12) since the rendered PDF was occasionally mixing both.

### Resume library context

`tailor.py` loads a curated library of prior tailored versions (~15,000 characters) as context, each tagged with `[UNIQUE]` markers on distinctive bullets and the application outcome. This grounds the tailor in patterns that have actually been sent rather than letting the LLM reinvent the structure each time.

### Usage

```bash
python3 scripts/tailor.py <job_url> <role_title> <company_name> [version_suffix]

# Example
python3 scripts/tailor.py 'https://jobs.ashbyhq.com/example/abc123' 'Strategy & Operations Manager' 'Example' 'v3'
```

Note: Ashby and Greenhouse render JDs as JS SPAs. `tailor.py` fetches the underlying JSON endpoint where possible, and accepts a `file://` path for manually-pasted JDs as a fallback.

---

## PDF Generator

Converts tailored `.txt` to a 1-page PDF using WeasyPrint. The template ("Clean Classic") was tuned over many iterations against ATS parsers and human readers.

**Spec:**

- Font — Carlito (open-source Calibri clone, metrically identical, installs cleanly on Ubuntu)
- Body — 10pt, line-height 1.28–1.30
- Margins — 0.5in top/bottom, 0.55in left/right
- Section headers — 9.5pt bold uppercase with bottom border rule
- Company — bold; role title — italic; dates — plain, right-aligned
- Bullets — disc, 11pt left margin, 3pt text padding

**Auto 1-page enforcement.** If the resume overflows, `generate_pdf.py` automatically tries five progressively tighter CSS configurations before warning the user.

**Dependencies:**

```bash
pip install weasyprint
sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 fonts-crosextra-carlito
```

---

## Repo structure

```
job-application-assistant/
├── README.md                              ← this file
├── scripts/
│   ├── ats_scout.py                       ← Scout (Ashby/Greenhouse/Lever) — writes job_postings + scan_runs directly
│   ├── ats_matcher.py                     ← Unified four-stage matcher (manual → pre-filter → cache → DeepSeek)
│   ├── dashboard.py                       ← Flask backend (SQLite-native; HTTP 500 if DB missing)
│   ├── dashboard_ui.html                  ← Frontend
│   ├── tailor.py                          ← Claude Sonnet 4.6 tailor with framework rules
│   ├── generate_pdf.py                    ← WeasyPrint PDF generator
│   ├── storage.py                         ← SQLite schema and storage helpers
│   ├── migrate_to_db.py                   ← One-shot bootstrap: import seed/legacy files into SQLite
│   │
│   ├── getro_scraper.py                   ← Production VC portfolio scraper (CSV output, --all/--vc modes)
│   │
│   ├── bulk_add_companies.py              ← Resumable bulk import from a .txt list
│   ├── ats_scout_getro_bulk_add.py        ← Same flow for Getro VC scrape output
│   ├── ats_scout_getro_match_new.py       ← Re-scout + score only NEW jobs (batched)
│   │
│   ├── scout_config.json                  ← Title and JD pattern filters
│   ├── companies_master.txt               ← Seed list for migrate_to_db.py
│   └── a16z_companies.txt                 ← Seed list for migrate_to_db.py
│
├── docs/
│   ├── data-contracts.md                  ← Live data contracts: SQLite tables, JSON exports, failure modes
│   ├── sqlite-schema.md                   ← SQLite table reference
│   └── scraper-integration.md             ← How new scrapers should write to the DB
│
├── tests/
│   └── smoke_test.py                      ← Offline safety checks
│
└── edgar_formd_scraper.py                 ← Adjacent experiment (see below)
```

User-specific files (master resume, resume library, applied history), local DBs,
runtime workspace files, and generated resumes/PDFs are gitignored.

---

## Adjacent experiment: SEC Form D scraper

`edgar_formd_scraper.py` is a separate workstream — a two-stage Form D pipeline that pulls quarterly `form.idx` files from SEC EDGAR, filters out funds / REITs / trusts, and parses `primary_doc.xml` for fundraise signals. The hypothesis: companies that just closed a round are disproportionately likely to be hiring, and Form D filings surface that signal earlier than press releases.

It's not wired into the main pipeline yet. Treated here as a sibling experiment rather than a core component.

---

## Setup

```bash
# 1. Clone and install
git clone https://github.com/pratyushpaul93-coder/job-application-assistant
cd job-application-assistant
pip install -r requirements.txt
sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 fonts-crosextra-carlito

# 2. Set environment variables
export ANTHROPIC_API_KEY=your_key_here
export DEEPSEEK_API_KEY=your_key_here

# 3. Customize for your search
#    - Replace resumes/master_resume.txt with your own
#    - Seed companies through SQLite/import scripts or dashboard Add Company
#    - Edit scripts/scout_config.json with your title/JD patterns
#    - Adapt the scoring rubric in ats_matcher.py to your criteria
#    - Rewrite the resume framework in tailor.py to your structure

# 4. Bootstrap SQLite from seed files
#    (one-shot — only needed on a fresh install or after wiping the DB)
python3 scripts/migrate_to_db.py --reset

# 5. Run the pipeline (manual; no cron)
python3 scripts/ats_scout.py        # writes job_postings + scan_runs
python3 scripts/ats_matcher.py      # writes job_scores
python3 scripts/dashboard.py        # then open http://localhost:5000
```

The dashboard's "Run Scan" button runs steps 5a and 5b in sequence as a
background thread, so day-to-day you'll only invoke them by hand for
debugging.

### Smoke test

Run the offline smoke test before changing core scripts:

```bash
python3 tests/smoke_test.py
```

### SQLite storage

`workspace/jobapp.db` is the canonical store for companies, ATS endpoints,
jobs, scores, dashboard state, and tailored resume mappings. Scout, Matcher,
Tailor, and the Dashboard all read and write the DB directly.

`migrate_to_db.py` is a **one-shot bootstrap tool** that imports seed files
(`companies_master.txt`, `all_vc_companies.csv`, `ats_mapping_779.csv`,
`bulk_add_results.csv`) and any historical JSON/CSV backups into the DB.
It is not part of the run-time pipeline.

```bash
# Fresh install / DB recovery:
python3 scripts/migrate_to_db.py --reset
```

See `docs/data-contracts.md` for the live data contracts and failure modes,
`docs/sqlite-schema.md` for the DB tables, and
`docs/scraper-integration.md` for how new scrapers should write results.

`workspace/raw_jobs.json` and `workspace/shortlist.json` are written on
every Scout / Matcher run as backup-only artifacts (the JSON files carry
a `_note` field marking them as such). Pre-migration JSON state files
are archived under `workspace/archive/json_legacy/` — see
[CHANGELOG.md](./CHANGELOG.md) for migration context.

To force the hardcoded `COMPANIES` fallback during debugging:

```bash
PP_JOBAPP_COMPANY_SOURCE=legacy python3 scripts/ats_scout.py
```

---

## Tech stack

Python 3.12 · Flask · WeasyPrint · DeepSeek V3 · Claude Sonnet 4.6 · Claude Haiku 4.5 · Hetzner CX21 · systemd · vanilla JS (no framework)

---

## Why I built this

I'm looking for senior S&O / GTM Ops / Chief of Staff roles at AI-native and SaaS startups (Series A–D), and I wanted three things from a job-search system: a pipeline I could run on demand that surfaced real listings I could trust, scoring grounded in my actual profile rather than keyword overlap, and resume tailoring that didn't fabricate. None of the off-the-shelf tools met all three. So I built this. It saves me roughly six hours a week and has materially improved my application quality.

If you're hiring for those roles and want to talk: pratyushpaul93@gmail.com · [LinkedIn](https://www.linkedin.com/in/pratyushpaul/)
