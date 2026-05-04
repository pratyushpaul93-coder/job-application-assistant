# Scraper Integration

New sourcing scrapers should write into SQLite through `scripts/storage.py`.
Avoid creating another long-lived registry file unless it is a raw export for
debugging or reproducibility.

## Which Tables To Update

### 1. Company or portfolio scrapers

Examples: Getro VC boards, accelerator/company lists, newly-funded company
sources.

Write to:

- `companies`
  - one canonical row per company
  - use `storage.upsert_company(...)`
- `company_sources`
  - one row per source appearance
  - use `storage.add_company_source(...)`

Do not create duplicate company rows for the same company across sources.
`companies.normalized_name` is the current exact duplicate key. If a scraper
finds aliases such as `Mistral` vs `Mistral AI`, keep the raw source row in
`company_sources`; merge/alias cleanup should happen deliberately.

### 2. ATS detection scrapers

Examples: Ashby/Greenhouse/Lever detector, dashboard Add Company flow, bulk
ATS discovery.

Write to:

- `ats_endpoints`
  - use `storage.upsert_ats_endpoint(...)`
  - unique key is `provider + slug`

Set:

- `status='active'` for scannable Ashby/Greenhouse/Lever endpoints.
- `status='failed'` for attempted but invalid endpoints worth remembering.
- `status='skipped'` for non-scannable legacy placeholders.
- `status='deleted'` when the user removes a company from active Scout.

### 3. Job scrapers / ATS scanners

Examples: Scout, any future direct ATS scraper, Form D-to-careers-page scanner
once it finds real jobs.

Write to:

- `job_postings`
  - use `storage.upsert_job_posting(...)`
  - unique key is `source + external_job_id`
- `job_url_aliases`
  - automatically maintained by `upsert_job_posting`
- `scan_runs`
  - use `storage.add_scan_run(...)` once per scan to record metadata
    (date, config version, totals, per-company stats)

Scout writes `job_postings` and `scan_runs` directly. `workspace/raw_jobs.json`
is also written every run as a backup-only artifact (top-level `_note` field
marks it as such), but nothing in the live pipeline reads it.

When adding new job scrapers, preserve these field names so the rest of the
pipeline can consume them without translation:

- `company_name`
- `role_title`
- `apply_url`
- `job_url`
- `source`
- `date_found`
- `posted_date`
- `days_ago`
- `location_raw`
- `remote_ok`
- `company_stage`
- `industry_vertical`
- `ai_native`
- `compensation`
- `jd_text`
- `match_reason`
- `matched_keyword`

### 4. Scoring processes

The unified `scripts/ats_matcher.py` is the single matcher. It runs three
stages per job, in order: manual override → deterministic pre-filter (US
filter, deep-tech hard skips, conditional family rules) → DeepSeek for the
survivors. Stage 3 is skipped when an existing score at the current
`RUBRIC_VERSION` is already cached.

Write to:

- `job_scores`
  - use `storage.add_job_score(..., rubric_version=...)` or
    `storage.save_job_scores(..., rubric_version=...)`.

Scorer values:

- `current_shortlist` — written by `ats_matcher.py`. The dashboard reads this.
- `manual` — written when the user enters a manual fit score in the dashboard.

Bumping the rubric: when matcher logic or the DeepSeek prompt changes in a way
that should invalidate prior scores, bump `RUBRIC_VERSION` in
`scripts/ats_matcher.py`. Cached scores at the old version will re-score on
the next run. For an explicit full re-score regardless of version:

```bash
python3 scripts/ats_matcher.py --rescore-all
```

The dashboard reads shortlisted jobs from SQLite by joining `job_postings` to
`job_scores` with scorer `current_shortlist`. The matcher still exports
`shortlist.json` as a backup/debug artifact, but the normal UI path no longer
depends on that file.

### 5. Dashboard/user state

Write to:

- `job_interactions`
  - use `storage.update_job_interaction(...)`

Dashboard reads and writes SQLite when `workspace/jobapp.db` is available and
falls back to legacy JSON only if the DB is unavailable. Matcher scripts read
manual feedback from SQLite first and save current scores back to `job_scores`.

## Recommended Scraper Pattern

```python
import storage

conn = storage.connect()
try:
    company_id = storage.upsert_company(
        conn,
        name=company_name,
        website_url=website_url,
        stage=funding_stage,
        vertical=vertical,
        headcount_range=headcount_range,
        active=False,
    )
    storage.add_company_source(
        conn,
        company_id,
        source_type="getro_vc",
        source_name="sequoia",
        source_rank=rank,
        fit_score=fit_score,
        raw_name=raw_company_name,
        raw_metadata=raw_row,
    )
    conn.commit()
finally:
    conn.close()
```

For ATS detection:

```python
endpoint_id = storage.upsert_ats_endpoint(
    conn,
    company_id,
    provider="ashby",
    slug="example",
    ats_url=storage.ats_url("ashby", "example"),
    status="active",
    open_jobs_actual=total_jobs,
)
```

For jobs:

```python
job_id = storage.upsert_job_posting(
    conn,
    job,
    company_id=company_id,
    ats_endpoint_id=endpoint_id,
)
```
