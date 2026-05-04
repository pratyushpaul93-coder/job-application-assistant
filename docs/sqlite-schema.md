# SQLite Schema

`workspace/jobapp.db` is the planned canonical store for company, ATS, job,
score, dashboard, and resume state. The migration is additive for now: existing
JSON/CSV files remain the live runtime contracts until each component is cut
over deliberately.

## Tables

### `companies`

One canonical row per company.

- `canonical_name`: display name.
- `normalized_name`: duplicate-prevention key, unique.
- `website_url`, `stage`, `vertical`, `headcount_range`: company metadata.
- `active`: whether Scout should scan this company once cut over.

### `company_sources`

One row per place a company came from.

Examples: `ats_scout`, `name_list`, `getro_vc`, `ats_mapping`,
`bulk_add_checkpoint`.

This allows a company to appear in multiple VC lists without becoming multiple
companies.

### `ats_endpoints`

One row per ATS endpoint.

- `provider`: `ashby`, `greenhouse`, `lever`, or a known non-scan provider.
- `slug`: ATS board slug.
- Unique key: `provider + slug`.
- `status`: `active`, `failed`, `skipped`, etc.

### `scan_runs`

One row per Scout run. Stores scan metadata and keeps job rows separate from
run-level state.

### `job_postings`

One canonical row per job posting.

- Unique key: `source + external_job_id`.
- `external_job_id` is extracted from ATS URLs when possible, otherwise derived
  from a stable hash.
- Stores normalized title, URLs, location, dates, JD text, and raw JSON.

### `job_url_aliases`

Maps old URL-keyed dashboard state to stable job IDs.

This is important because historical files use both `job_url` and `apply_url`
as keys.

### `job_scores`

One score per scorer per job.

Examples: `current_shortlist`, `manual`, later `deepseek` or `rubric_v22`.

### `job_interactions`

Dashboard/user state for a job:

- selected
- reviewed
- applied
- comment/tags
- manual score/comment

### `resume_artifacts`

Tailored resume outputs linked to a job and company where possible.

Stores `.txt` and expected `.pdf` filenames plus source job URL for historical
compatibility.

## Validation Rules

The migration script currently validates:

- DB company count is at least the hardcoded `COMPANIES` count.
- DB job count is at least `raw_jobs.json` job count.
- unique normalized company names.
- unique ATS provider/slug pairs.
- unique source/external job IDs.

Run:

```bash
python3 scripts/migrate_to_db.py --reset
python3 tests/smoke_test.py
```

## New Scrapers

New scrapers should write to SQLite via `scripts/storage.py`:

- company/list scraper results: `companies` and `company_sources`
- ATS detector results: `ats_endpoints`
- job results: `job_postings` and `job_url_aliases`
- scoring results: `job_scores`

See `docs/scraper-integration.md` for concrete examples.
