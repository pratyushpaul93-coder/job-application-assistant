# SQLite Schema

`workspace/jobapp.db` is the canonical store for company, ATS, job, score,
dashboard, and resume state. Scout, Matcher, Tailor, and the Dashboard all
read and write here directly; JSON exports are backup-only.

## Tables

### `companies`

One canonical row per company.

- `canonical_name` — display name.
- `normalized_name` — duplicate-prevention key, unique.
- `website_url`, `stage`, `vertical`, `headcount_range` — company metadata.
- `active` — whether Scout should scan this company.

### `company_sources`

One row per place a company was discovered. Examples: `ats_scout`,
`name_list`, `getro_vc`, `ats_mapping`, `bulk_add_checkpoint`,
`dashboard_manual`. Lets a company appear in many VC lists without
becoming many companies.

### `ats_endpoints`

One row per ATS endpoint.

- `provider` — `ashby`, `greenhouse`, `lever`, or a known non-scan
  provider (e.g. `broken`, `tavily` placeholders).
- `slug` — ATS board slug.
- Unique key: `(provider, slug)`.
- `status` — `active`, `failed`, `skipped`, `deleted`.

### `scan_runs`

One row per Scout invocation. Stores `scan_date`, `scan_method`,
`config_version`, `total_companies_scanned`, `total_matches`, and
per-company stats / errors in `raw_metadata_json`. Written by Scout
itself via `storage.add_scan_run`.

### `job_postings`

One canonical row per job posting.

- Unique key: `(source, external_job_id)`.
- `external_job_id` is extracted from ATS URLs when possible, otherwise
  derived from a stable hash.
- Stores normalized title, URLs, location, dates, JD text, and the raw
  ATS payload in `raw_json`.

### `job_url_aliases`

Maps every observed `job_url` / `apply_url` to the canonical `job_id`.
Lets historical URL-keyed dashboard state and future URL variants from
the same ATS resolve to the same posting.

### `job_scores`

One row per `(job_id, scorer)`. Carries:

- `score` (1–5)
- `reason` (free text)
- `flags_json` (matcher-emitted flags)
- `rubric_version` (e.g. `"2.2"`) — used by the matcher's incremental
  cache to decide whether a stored score is still valid against the
  current rubric. Defaults to `"0"` for legacy/imported scores so the
  next matcher run will re-score them under the current rubric.

Scorer values currently in use:

- `current_shortlist` — `ats_matcher.py` writes here. The dashboard
  reads this scorer for its main job view.
- `manual` — user-entered scores from the dashboard's fit-rating UI.

### `job_interactions`

Dashboard / user state for a job, keyed by `job_id`:

- `selected`, `reviewed`, `applied`
- `comment`, `tags_json`
- `manual_score`, `manual_score_comment`

### `resume_artifacts`

Tailored resume outputs linked to a job and company where possible.
Stores `.txt` and expected `.pdf` filenames plus source job URL.

## Validation Rules

`scripts/migrate_to_db.py` validates on every bootstrap run:

- DB company count is at least the hardcoded `COMPANIES` count.
- DB job count is at least `raw_jobs.json` job count.
- Unique normalized company names.
- Unique ATS provider/slug pairs.
- Unique `(source, external_job_id)` job IDs.

Run:

```bash
python3 scripts/migrate_to_db.py --reset
python3 tests/smoke_test.py
```

## New Scrapers

New scrapers should write to SQLite via `scripts/storage.py`. Avoid
creating long-lived JSON registries — backup-only exports are fine,
but the DB must be the canonical writer.

- Company / list scraper results → `companies` and `company_sources`
- ATS detector results → `ats_endpoints`
- Job results → `job_postings` (and `job_url_aliases` automatically via
  `upsert_job_posting`)
- Scoring results → `job_scores`
- Scout-style runs → `scan_runs` via `storage.add_scan_run`

See `docs/scraper-integration.md` for concrete code patterns.
