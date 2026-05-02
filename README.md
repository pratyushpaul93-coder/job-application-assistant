# Job Application Assistant

An automated, end-to-end job application pipeline for senior strategy and operations roles. Built to streamline the most time-consuming parts of a job search — finding target companies and roles, and accurately customizing a resume against each one — while keeping a human in the loop on every submission.

Built by [Pratyush Paul](https://github.com/pratyushpaul93-coder) during an active job search for S&O / GTM Ops / Chief of Staff roles at AI-native and SaaS startups.

> **A note on customization.** This pipeline was built around a specific profile, target-role set, and resume framework. The architecture and ATS / VC-board sourcing logic generalize cleanly, but the resume tailoring layer, scoring rubric, and target-company list are personal. Anyone forking this should expect to swap out the master resume, scoring criteria, and seed company list before it's useful for them.

---

## The problem

Generic job boards and mass-apply tools optimize for volume. For senior strategy and operations roles — where the right job is one of maybe thirty a week, and the wrong job costs forty-five minutes of resume tailoring — the bottleneck isn't applying faster. It's filtering harder and tailoring better.

This pipeline is built around three constraints:

1. **No hallucination on job listings.** Every role comes from a real ATS, never an LLM-generated summary.
2. **LLMs only where reasoning is needed.** Scoring and resume tailoring, nothing else.
3. **Human-in-the-loop always.** The system never auto-submits applications.

---

## What it does

The pipeline gives users two complementary ways to find target roles:

**Sourcing breadth — VC portfolio scraping.** A scraper pulls portfolio companies from major VC job boards (Accel, General Catalyst, Lightspeed, Sequoia, Kleiner Perkins, Greylock — all powered by Getro). At time of publishing, this surfaced roughly 2,000 portfolio companies across the six VCs covered. These can be filtered into a working target list and fed into the daily Scout.

**Sourcing precision — manual company adds.** Users can add specific target companies one at a time through the dashboard or via CLI, with automatic ATS detection (Ashby, Greenhouse, Lever).

Once a company is in the target list, the daily pipeline runs automatically:

1. **Scout** scans every target company by hitting their public ATS JSON endpoints — no scraping, no Playwright, no auth — and applies title and JD pattern filters from a config file.
2. **Matcher** scores every fresh role 1–5 using DeepSeek V3 (~$0.002 per job), grounded by a feedback loop that incorporates the user's prior comments and dashboard signals.
3. **Dashboard** surfaces the shortlist with filters, posting-date freshness, comments, and a per-job tailor button.
4. **Tailor** rewrites the master resume against the live JD using Claude Sonnet 4 (~$0.05 per resume), governed by a strict framework that prevents fabrication and enforces structural rules.
5. **PDF generator** produces a 1-page PDF using a custom Clean Classic template that auto-tightens spacing to fit one page.
6. The user reviews, downloads, and submits manually.

Total cost to operate end-to-end is roughly **$2–3/month** in API spend plus VPS hosting.

---

## Architecture

### Core principle: LLM only where reasoning is needed

| Component | Script | Tool | Why |
|-----------|--------|------|-----|
| Scout | `ats_scout.py` | ATS JSON APIs | Zero hallucination, zero auth, ~30 sec runtime |
| Matcher | `ats_matcher.py` | DeepSeek V3 | Cheap reasoning ($0.002/job) for relevance scoring |
| Dashboard | `dashboard.py` + `dashboard_ui.html` | Flask + vanilla JS | Local review UI, no deployment overhead |
| Resume Tailor | `tailor.py` | Claude Sonnet 4 | Quality matters — used sparingly, only on selected roles |
| PDF Generator | `generate_pdf.py` | WeasyPrint | Open-source, deterministic, no template lock-in |
| VC Sourcing | `getro_scraper.py` | Getro internal APIs | ~2,000 companies across 6 top-tier VCs |
| Bulk Onboarding | `bulk_add_companies.py`, `ats_scout_getro_bulk_add.py` | ATS auto-detection | Batch-imports VC scrape results into the daily Scout |

### Daily pipeline

```
ats_scout.py  →  raw_jobs.json
                      ↓
ats_matcher.py  →  shortlist.json + whatsapp_message.txt
                      ↓
              Dashboard (review)
                      ↓
              [click Tailor on a job]
                      ↓
tailor.py  →  YYYY-MM-DD_role_company.txt
                      ↓
generate_pdf.py  →  YYYY-MM-DD_role_company.pdf
```

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

Getting to a working scraper required reverse-engineering Getro's API across two underlying platform versions — Accel and General Catalyst run on an older page-paginated API at `api.getro.com`, while Lightspeed, Sequoia, Kleiner Perkins, and Greylock run on a newer cursor-paginated API at the board domain itself. Network IDs and request signatures had to be discovered through a mix of `__NEXT_DATA__` inspection and Playwright XHR capture. The repo contains the discovery scripts (`getro_discover_deep.py`, `getro_capture_xhr.py`, `getro_api_test.py`, `getro_api_direct.py`) that were used to figure this out, alongside the final production scraper.

VC portfolio scraping is one approach to sourcing breadth, not the only one. Operator networks, accelerator job boards (YC Work at a Startup), and curated communities (Pavilion, Revenue Collective) cover meaningful overlap and gap. Users serious about sourcing should layer multiple approaches.

---

## Scout: Direct ATS API Fetcher

Most job-search bots use Playwright or scrape rendered HTML. Both are brittle and prone to silent breakage. The actual ATS platforms (Ashby, Greenhouse, Lever) all expose **public JSON endpoints** that require no auth — they were built to power third-party job boards. Scout uses them directly:

| Platform | Endpoint | Date field |
|----------|----------|------------|
| Ashby | `api.ashbyhq.com/posting-api/job-board/{slug}` | `publishedAt` |
| Greenhouse | `api.greenhouse.io/v1/boards/{slug}/jobs` | `updated_at` |
| Lever | `api.lever.co/v0/postings/{slug}` | `createdAt` |

Every job is captured with its real posting date, so the dashboard can color-code freshness (green <14 days, amber 15–30, red 30+) and de-prioritize stale listings.

Scout applies title and JD pattern filters from `scripts/scout_config.json` before writing `raw_jobs.json`. This keeps the Matcher's scoring volume manageable and lets users tune their filters without touching code.

---

## Matcher: Scoring with a feedback loop

For each fresh job pulled by Scout, the Matcher calls DeepSeek V3 once to score it 1–5 against the user's profile and target criteria. A typical rubric:

- **5** — Target role + strong company fit + background-aligned signal
- **4** — Role matches well, strong company, minor gaps
- **3** — Role matches but company stage unclear, or hard requirements (e.g., specific tools) only partially met
- **2** — Adjacent role or weak company fit
- **1** — Skip

Output is `shortlist.json` filtered to scores of 3+, plus a formatted WhatsApp digest.

The Matcher reads `feedback.json` on every run, which aggregates dashboard comments and reviewed/applied state from prior cycles. This creates a closed loop: comments left on a job ("too junior," "wrong stack," "great fit") shape how similar roles get scored next time.

DeepSeek was chosen over GPT-4 / Claude here because the reasoning is light (rubric application) and the volume is high (50–200 jobs/day) — cost matters more than ceiling.

---

## Dashboard

A Flask app that runs as a `systemd` service and survives reboots. Accessible from browser and mobile.

**Features:**

- Stats bar — total scanned, shortlisted, selected, commented
- Filter pills — score (5/4/3), Selected, Commented, Posted <14d, Tailored, Reviewed, Applied
- Search — by role or company
- Job cards — score badge, company, location, stage, posting date with freshness color, SQL flag
- Per-job actions — Apply (deep link to ATS), View JD, Tailor (fires `tailor.py`, polls until done), Comment (free text, fed into Matcher feedback loop), Mark Reviewed, Mark Applied
- Bulk actions — Tailor selected, Send to WhatsApp
- Resume review panel — Draft tab (current `.txt`), Revise tab (free-text comments → Apply), Generate PDF, inline Download
- Add Company — type a company name, the system auto-detects ATS and adds it to the daily Scout

**API endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/tailor` | POST | Trigger `tailor.py` for a job |
| `/api/tailor_status` | GET | Poll tailor progress |
| `/api/tailored_resumes` | GET | List all tailored resume filenames |
| `/api/revise` | POST | Apply free-text comments to existing tailored `.txt` |
| `/api/generate_pdf` | POST | Generate PDF from `.txt` |
| `/api/download_pdf` | GET | Regenerate and serve PDF |
| `/api/job_status` | POST | Persist Reviewed/Applied state |
| `/api/add_company` | POST | Add a company with ATS auto-detection |
| `/api/companies/delete` | POST | Remove a company and clean workspace |

---

## Resume Tailor

The hardest component of the pipeline. The naive version — "give an LLM a JD and a resume, ask for a tailored version" — fabricates metrics, drops bullets, reorders sections randomly, and tends to overflow to 1.3 pages. The current implementation is a heavily-constrained Sonnet 4 prompt governed by an explicit framework.

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
11. **Hard requirements flagged at top** (e.g., `[SQL NOTE: required/preferred]`) so the user can deprioritize gating roles.
12. **Conditional sections** — AI/Technical Projects section only included for AI-native companies or JDs that mention technical skills.
13. **Hardcoded protections** — load-bearing line items (e.g., a key internship, a credential) verified post-generation and re-injected if the LLM dropped them.

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
│   ├── ats_scout.py                       ← Scout (Ashby/Greenhouse/Lever) with config-driven filters
│   ├── ats_matcher.py                     ← DeepSeek scoring + feedback loop + WhatsApp digest
│   ├── dashboard.py                       ← Flask backend
│   ├── dashboard_ui.html                  ← Frontend
│   ├── tailor.py                          ← Claude Sonnet 4 tailor with framework rules
│   ├── generate_pdf.py                    ← WeasyPrint PDF generator
│   │
│   ├── getro_scraper.py                   ← Production VC portfolio scraper (CSV output, --all/--vc modes)
│   ├── getro_discover_deep.py             ← Network ID discovery via __NEXT_DATA__
│   ├── getro_capture_xhr.py               ← Playwright XHR capture for newer Getro boards
│   ├── getro_api_test.py                  ← URL-pattern hypothesis testing
│   ├── getro_api_direct.py                ← Direct API client used during reverse-engineering
│   │
│   ├── bulk_add_companies.py              ← Resumable bulk import from a .txt list
│   ├── ats_scout_getro_bulk_add.py        ← Same flow for Getro VC scrape output
│   ├── ats_scout_getro_match_new.py       ← Re-scout + score only NEW jobs (batched)
│   │
│   ├── scout_config.json                  ← Title and JD pattern filters
│   ├── companies_master.txt               ← Active target company list
│   └── a16z_companies.txt                 ← Example seed list
│
└── edgar_formd_scraper.py                 ← Adjacent experiment (see below)
```

User-specific files (master resume, resume library, applied history) and runtime workspace files (Scout output, dashboard state) are gitignored.

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
#    - Edit scripts/companies_master.txt with target companies
#    - Edit scripts/scout_config.json with your title/JD patterns
#    - Adapt the scoring rubric in ats_matcher.py to your criteria
#    - Rewrite the resume framework in tailor.py to your structure

# 4. Run
python3 scripts/ats_scout.py
python3 scripts/ats_matcher.py
python3 scripts/dashboard.py    # then open http://localhost:5000
```

---

## Roadmap

- Migrate hardcoded company list out of `ats_scout.py` into a single `companies.json`
- Deduplication in Scout output (same role can appear across multiple ATS instances)
- `applied_history.json` to flag already-applied companies in fresh scans
- Wire the Form D scraper into the daily pipeline as a "newly-funded" sourcing signal
- WhatsApp gateway pairing
- Browser agent for assisted (not autonomous) form-filling

---

## Tech stack

Python 3.12 · Flask · WeasyPrint · DeepSeek V3 · Claude Sonnet 4 · Hetzner CX21 · systemd · vanilla JS (no framework)

---

## Why I built this

I'm looking for senior S&O / GTM Ops / Chief of Staff roles at AI-native and SaaS startups (Series A–D), and I wanted three things from a job-search system: a daily pipeline that surfaced real listings I could trust, scoring grounded in my actual profile rather than keyword overlap, and resume tailoring that didn't fabricate. None of the off-the-shelf tools met all three. So I built this. It saves me roughly six hours a week and has materially improved my application quality.

If you're hiring for those roles and want to talk: pratyushpaul93@gmail.com · [LinkedIn](https://www.linkedin.com/in/pratyushpaul/)
